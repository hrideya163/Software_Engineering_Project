"""Persistent storage for computed results: Supabase (PostgreSQL) with a local SQLite fallback.

Every cached entity lives in its own table with a text ``key`` that already contains what invalidates it
(commit SHA, issue content version, model version, LLM model, profile hash), plus a JSON ``data`` column and
an optional ``expires_at``. A stale result is therefore never returned: a new commit, an edited issue or a
retrained model produces a different key. A small in-memory LRU sits in front of the database.

Backends, chosen by ``CONTRIMAP_STORE`` (default: ``supabase`` when ``SUPABASE_URL`` is set, else ``sqlite``):
    supabase  PostgREST API of a Supabase project: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (backend only).
              Tables come from supabase/migrations/*.sql.
    sqlite    data/contrimap_store.sqlite3 (stdlib, no server); same tables.
    memory    nothing persisted (tests).
If the database is unreachable the store logs once, serves from memory and retries after a cool-down, so the
application keeps working without it.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

# Table -> seconds a stored value stays valid (None = until its key changes).
TABLES: dict[str, int | None] = {
    "repository_heads": 600,          # resolved default-branch commit, so a restart skips the git round trip
    "repository_snapshots": None,     # per commit + snapshot version
    "repository_metrics": None,       # per commit + graph version
    "issue_predictions": None,        # per issue content + commit + model version
    "issue_analyses": None,           # per issue content + commit + model version + profile
    "similar_issues": 6 * 3600,       # recent closed history changes, so these expire
    "explanations": None,             # per issue content + commit + model version + LLM model + profile
    "user_profiles": None,            # per user id
}
EXTRA_COLUMNS = ("repository", "sha", "model_version")
COOLDOWN_SECONDS = 60
MEMORY_ENTRIES = 4096


class StoreUnavailable(RuntimeError):
    pass


class _Memory:
    """Bounded LRU with per-entry expiry, in front of the persistent backend."""

    def __init__(self, capacity: int = MEMORY_ENTRIES) -> None:
        self._data: OrderedDict[tuple[str, str], tuple[float | None, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._capacity = capacity

    def get(self, table: str, key: str) -> Any | None:
        with self._lock:
            hit = self._data.get((table, key))
            if hit is None:
                return None
            expiry, value = hit
            if expiry is not None and expiry < time.time():
                self._data.pop((table, key), None)
                return None
            self._data.move_to_end((table, key))
            return value

    def put(self, table: str, key: str, value: Any, expiry: float | None) -> None:
        with self._lock:
            self._data[(table, key)] = (expiry, value)
            self._data.move_to_end((table, key))
            while len(self._data) > self._capacity:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class _SQLite:
    name = "sqlite"

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            for table in TABLES:
                db.execute(f"create table if not exists {table} (key text primary key, repository text, sha text, model_version text, data text not null, created_at real not null, expires_at real)")
            db.execute("create table if not exists feedback_events (id integer primary key autoincrement, user_id text not null, repository text not null, number integer not null, action text not null, title text, text text, created_at real not null)")
            db.execute("create index if not exists feedback_events_user on feedback_events (user_id, created_at)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def get_many(self, table: str, keys: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        now = time.time()
        with self._lock, self._connect() as db:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                rows = db.execute(f"select key, data, expires_at from {table} where key in ({','.join('?' * len(chunk))})", chunk).fetchall()
                out.update({key: json.loads(data) for key, data, expires in rows if expires is None or expires > now})
        return out

    def put_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        with self._lock, self._connect() as db:
            db.executemany(
                f"insert into {table} (key, repository, sha, model_version, data, created_at, expires_at) values (?, ?, ?, ?, ?, ?, ?) "
                "on conflict(key) do update set data = excluded.data, created_at = excluded.created_at, expires_at = excluded.expires_at",
                [(row["key"], row.get("repository"), row.get("sha"), row.get("model_version"), json.dumps(row["data"]), time.time(), row.get("expires_at_epoch")) for row in rows],
            )

    def add_event(self, event: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            db.execute("insert into feedback_events (user_id, repository, number, action, title, text, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                       (event["user_id"], event["repository"], event["number"], event["action"], event.get("title", ""), event.get("text", ""), event["time"]))

    def events(self, user: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute("select repository, number, action, title, text, created_at from feedback_events where user_id = ? order by created_at, id", (user,)).fetchall()
        return [{"repository": r[0], "number": r[1], "action": r[2], "title": r[3] or "", "text": r[4] or "", "time": r[5]} for r in rows]


class _Supabase:
    """Supabase's PostgREST API over HTTPS; the service-role key never leaves the backend."""

    name = "supabase"

    def __init__(self, url: str, key: str, timeout: float = 4.0, write_timeout: float = 30.0) -> None:
        # Accept the project URL with or without the "/rest/v1" suffix some dashboard pages show.
        root = url.rstrip("/")
        self.base = (root[: -len("/rest/v1")] if root.endswith("/rest/v1") else root) + "/rest/v1"
        self.timeout = timeout
        self.write_timeout = write_timeout  # snapshots of large repositories are several MB
        self.session = requests.Session()
        self.session.headers.update({"apikey": key, "Content-Type": "application/json"})
        # Legacy service_role keys are JWTs and also go in Authorization; new "sb_secret_..." keys are sent only as apikey.
        if not key.startswith("sb_"):
            self.session.headers["Authorization"] = f"Bearer {key}"

    def _call(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        try:
            timeout = self.timeout if method == "GET" else self.write_timeout
            response = self.session.request(method, f"{self.base}/{path}", timeout=timeout, **kwargs)
        except requests.RequestException as error:
            raise StoreUnavailable(f"Supabase unreachable ({error.__class__.__name__})") from error
        if response.status_code >= 400:
            raise StoreUnavailable(f"Supabase error {response.status_code}: {response.text[:200]}")
        return response

    @staticmethod
    def _in_list(values: Iterable[str]) -> str:
        quoted = ",".join('"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"' for value in values)
        return f"in.({quoted})"

    def get_many(self, table: str, keys: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for start in range(0, len(keys), 40):  # keeps URLs well under PostgREST/proxy limits
            chunk = keys[start:start + 40]
            params = {"select": "key,data", "key": self._in_list(chunk), "or": f'(expires_at.is.null,expires_at.gt."{now}")'}
            out.update({row["key"]: row["data"] for row in self._call("GET", table, params=params).json()})
        return out

    def put_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        payload = [{"key": row["key"], "repository": row.get("repository"), "sha": row.get("sha"), "model_version": row.get("model_version"), "data": row["data"],
                    "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row["expires_at_epoch"])) if row.get("expires_at_epoch") else None} for row in rows]
        for start in range(0, len(payload), 200):
            self._call("POST", table, params={"on_conflict": "key"}, data=json.dumps(payload[start:start + 200]), headers={"Prefer": "resolution=merge-duplicates,return=minimal"})

    def add_event(self, event: dict[str, Any]) -> None:
        body = {"user_id": event["user_id"], "repository": event["repository"], "number": event["number"], "action": event["action"], "title": event.get("title", ""), "text": event.get("text", ""),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(event["time"])) + f".{int((event['time'] % 1) * 1e6):06d}Z"}
        self._call("POST", "feedback_events", data=json.dumps(body), headers={"Prefer": "return=minimal"})

    def events(self, user: str) -> list[dict[str, Any]]:
        from datetime import datetime

        rows = self._call("GET", "feedback_events", params={"select": "repository,number,action,title,text,created_at", "user_id": f"eq.{user}", "order": "created_at.asc,id.asc"}).json()
        return [{**{k: row[k] for k in ("repository", "number", "action")}, "title": row.get("title") or "", "text": row.get("text") or "",
                 "time": datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).timestamp()} for row in rows]

    def ping(self) -> None:
        self._call("GET", "user_profiles", params={"select": "key", "limit": "1"})


_MISSING = object()  # remembered "not in the database" marker
MISS_SECONDS = 60


class Store:
    def __init__(self, backend: Any | None) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self.backend = backend
        self.memory = _Memory()
        self._down_until = 0.0
        self._lock = threading.Lock()
        # One writer thread: database writes leave the request path but keep their order.
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="contrimap-store-writer")
        self._pending: list = []
        self.stats = {"memory_hits": 0, "store_hits": 0, "misses": 0, "writes": 0, "errors": 0}

    @property
    def name(self) -> str:
        return self.backend.name if self.backend else "memory"

    def _available(self) -> bool:
        return self.backend is not None and time.time() >= self._down_until

    def _failed(self, error: Exception) -> None:
        with self._lock:
            first = self._down_until < time.time()
            self._down_until = time.time() + COOLDOWN_SECONDS
            self.stats["errors"] += 1
        if first:
            logger.warning("%s store unavailable, serving from memory for %ss: %s", self.name, COOLDOWN_SECONDS, error)

    def get_many(self, table: str, keys: Iterable[str]) -> dict[str, Any]:
        keys = list(dict.fromkeys(keys))
        found: dict[str, Any] = {}
        known_missing: set[str] = set()
        for key in keys:
            value = self.memory.get(table, key)
            if value is _MISSING:
                known_missing.add(key)
            elif value is not None:
                found[key] = value
        self.stats["memory_hits"] += len(found)
        missing = [key for key in keys if key not in found and key not in known_missing]
        if missing and self._available():
            try:
                stored = self.backend.get_many(table, missing)
            except Exception as error:  # noqa: BLE001 - storage problems must never break a request
                self._failed(error)
                stored = None
            if stored is not None:
                ttl = TABLES.get(table)
                for key in missing:
                    if key in stored:
                        self.memory.put(table, key, stored[key], time.time() + ttl if ttl else None)
                    else:  # remember the miss briefly, so absent rows (e.g. no Claude explanation yet) cost one query a minute
                        self.memory.put(table, key, _MISSING, time.time() + MISS_SECONDS)
                found.update(stored)
                self.stats["store_hits"] += len(stored)
        self.stats["misses"] += len(keys) - len(found)
        return found

    def get(self, table: str, key: str) -> Any | None:
        return self.get_many(table, [key]).get(key)

    def _write(self, table: str, rows: list[dict[str, Any]]) -> bool:
        try:
            self.backend.put_many(table, rows)
            self.stats["writes"] += len(rows)
            return True
        except Exception as error:  # noqa: BLE001
            self._failed(error)
            return False

    def put_many(self, table: str, values: Mapping[str, Any], meta: Mapping[str, Mapping[str, Any]] | None = None, ttl: int | None = None, wait: bool = False) -> bool:
        """Write through memory to the database.

        By default the database write happens on a background thread (the value is already in memory, so the
        request does not wait for it) and True means "queued". ``wait=True`` writes synchronously and returns
        whether the database accepted it (migrations, tests).
        """
        ttl = ttl if ttl is not None else TABLES.get(table)
        expiry = time.time() + ttl if ttl else None
        for key, value in values.items():
            self.memory.put(table, key, value, expiry)
        if not values or not self._available():
            return not values
        rows = [{"key": key, "data": value, "expires_at_epoch": expiry, **{column: (meta or {}).get(key, {}).get(column) for column in EXTRA_COLUMNS}} for key, value in values.items()]
        if wait:
            return self._write(table, rows)
        future = self._writer.submit(self._write, table, rows)
        with self._lock:
            self._pending = [item for item in self._pending if not item.done()] + [future]
        return True

    def put(self, table: str, key: str, value: Any, ttl: int | None = None, wait: bool = False, **meta: Any) -> bool:
        return self.put_many(table, {key: value}, {key: meta}, ttl, wait=wait)

    def flush(self, timeout: float = 60.0) -> None:
        """Wait for queued background writes (tests, shutdown, migration)."""
        with self._lock:
            pending = list(self._pending)
        for future in pending:
            future.result(timeout=timeout)

    # Append-only feedback log -------------------------------------------------
    def add_event(self, event: dict[str, Any]) -> bool:
        if not self._available():
            return False
        try:
            self.backend.add_event(event)
            return True
        except Exception as error:  # noqa: BLE001
            self._failed(error)
            return False

    def events(self, user: str) -> list[dict[str, Any]] | None:
        """All feedback events of ``user`` oldest first, or None when the store cannot answer."""
        if not self._available():
            return None
        try:
            return self.backend.events(user)
        except Exception as error:  # noqa: BLE001
            self._failed(error)
            return None

    def health(self) -> dict[str, Any]:
        status: dict[str, Any] = {"backend": self.name, "available": self._available(), **self.stats}
        if isinstance(self.backend, _Supabase) and self._available():
            try:
                self.backend.ping()
            except Exception as error:  # noqa: BLE001
                self._failed(error)
                status.update({"available": False, "error": str(error)[:200]})
        return status


def _build() -> Store:
    choice = os.getenv("CONTRIMAP_STORE", "").lower() or ("supabase" if os.getenv("SUPABASE_URL") else "sqlite")
    if choice == "supabase":
        url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if url and key:
            return Store(_Supabase(url, key))
        logger.warning("CONTRIMAP_STORE=supabase but SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are missing; using SQLite")
        choice = "sqlite"
    if choice == "sqlite":
        try:
            return Store(_SQLite(Path(os.getenv("CONTRIMAP_SQLITE_PATH", ROOT / "data" / "contrimap_store.sqlite3"))))
        except sqlite3.Error as error:
            logger.warning("SQLite store unavailable (%s); results are kept in memory only", error)
    return Store(None)


_STORE: Store | None = None
_BUILD_LOCK = threading.Lock()


def current() -> Store:
    global _STORE
    with _BUILD_LOCK:
        if _STORE is None:
            _STORE = _build()
        return _STORE


def configure(store: Store | None) -> None:
    """Replace the process-wide store (tests)."""
    global _STORE
    with _BUILD_LOCK:
        _STORE = store


def get_many(table: str, keys: Iterable[str]) -> dict[str, Any]:
    return current().get_many(table, keys)


def get(table: str, key: str) -> Any | None:
    return current().get(table, key)


def put_many(table: str, values: Mapping[str, Any], meta: Mapping[str, Mapping[str, Any]] | None = None, ttl: int | None = None) -> bool:
    return current().put_many(table, values, meta, ttl)


def put(table: str, key: str, value: Any, ttl: int | None = None, **meta: Any) -> bool:
    return current().put(table, key, value, ttl, **meta)


__all__ = ["Store", "StoreUnavailable", "TABLES", "configure", "current", "get", "get_many", "put", "put_many"]
