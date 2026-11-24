"""GitHub and Google sign-in for the ContriMap web app (replaces the former Express service).

Sessions are stateless, HMAC-signed cookies, so they survive server restarts and need no session store.
Sign-out clears the cookie and records the session id as revoked until it would have expired anyway.

Configuration (all optional; with neither provider configured the app works signed-out):
    GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET   (callback: {API}/api/auth/github/callback)
    GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET   (callback: {API}/api/auth/google/callback)
    CONTRIMAP_PUBLIC_API_URL   public base URL of this API, used to build callback URLs (default http://localhost:8001)
    CONTRIMAP_FRONTEND_URL     where to send the user afterwards (default http://localhost:5173/ContriMap-website/)
    CONTRIMAP_SESSION_SECRET   signing key (default: generated once and kept in data/session_secret)
    CONTRIMAP_COOKIE_SECURE=1  mark cookies Secure (required when served over HTTPS)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("CONTRIMAP_AUTH_DIR", ROOT / "data"))
SESSION_COOKIE = "contrimap_session"
STATE_COOKIE = "contrimap_oauth_state"
SESSION_SECONDS = 14 * 24 * 3600
STATE_SECONDS = 10 * 60

PROVIDERS: dict[str, dict[str, str]] = {
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user",
        "env": "GITHUB_OAUTH",
    },
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
        "env": "GOOGLE_OAUTH",
    },
}

router = APIRouter(prefix="/api/auth", tags=["auth"])
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _credentials(provider: str) -> tuple[str, str] | None:
    prefix = PROVIDERS[provider]["env"]
    client_id, secret = os.getenv(f"{prefix}_CLIENT_ID"), os.getenv(f"{prefix}_CLIENT_SECRET")
    return (client_id, secret) if client_id and secret else None


def configured_providers() -> dict[str, bool]:
    return {name: _credentials(name) is not None for name in PROVIDERS}


def _api_url() -> str:
    return os.getenv("CONTRIMAP_PUBLIC_API_URL", "http://localhost:8001").rstrip("/")


def _frontend_url(path: str = "") -> str:
    base = os.getenv("CONTRIMAP_FRONTEND_URL", "http://localhost:5173/ContriMap-website/").rstrip("/")
    return f"{base}{path}"


def _callback_url(provider: str) -> str:
    return os.getenv(f"{PROVIDERS[provider]['env']}_REDIRECT_URI") or f"{_api_url()}/api/auth/{provider}/callback"


def _secret() -> bytes:
    configured = os.getenv("CONTRIMAP_SESSION_SECRET")
    if configured:
        return configured.encode()
    path = DATA / "session_secret"
    with _LOCK:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_hex(32), encoding="utf-8")
        return path.read_text(encoding="utf-8").strip().encode()


def _cookie_args(max_age: int) -> dict[str, Any]:
    return {"max_age": max_age, "httponly": True, "samesite": "lax", "secure": os.getenv("CONTRIMAP_COOKIE_SECURE") == "1", "path": "/"}


# ---------------------------------------------------------------------------
# Signed tokens
# ---------------------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def verify(token: str | None) -> dict[str, Any] | None:
    """Payload of a valid, unexpired, unrevoked token; otherwise None."""
    if not token or token.count(".") != 1:
        return None
    body, mac = token.split(".")
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if float(payload.get("exp", 0)) < time.time() or payload.get("sid") in _revoked():
        return None
    return payload


# ---------------------------------------------------------------------------
# Revocation (sign-out)
# ---------------------------------------------------------------------------
def _revoked_path() -> Path:
    return DATA / "revoked_sessions.json"


def _revoked() -> dict[str, float]:
    path = _revoked_path()
    if not path.exists():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    now = time.time()
    return {sid: expiry for sid, expiry in entries.items() if expiry > now}


def revoke(payload: dict[str, Any]) -> None:
    with _LOCK:
        entries = _revoked()
        entries[str(payload["sid"])] = float(payload["exp"])
        path = _revoked_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries), encoding="utf-8")


def current_user(request: Request) -> dict[str, Any] | None:
    payload = verify(request.cookies.get(SESSION_COOKIE))
    return payload.get("user") if payload else None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def _safe_next(value: str | None) -> str:
    """Only same-app relative paths, so the callback cannot be turned into an open redirect."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value[:300]


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    providers = configured_providers()
    return {"user": current_user(request), "providers": providers, "configured": any(providers.values())}


@router.get("/{provider}")
def start(provider: str, next: str | None = None) -> RedirectResponse:  # noqa: A002 - query parameter name
    if provider not in PROVIDERS:
        return JSONResponse(status_code=404, content={"detail": "Unknown sign-in provider."})
    credentials = _credentials(provider)
    if credentials is None:
        return RedirectResponse(_frontend_url(f"/sign-in?error=not_configured&provider={provider}"), status_code=302)
    state = secrets.token_urlsafe(24)
    params = {"client_id": credentials[0], "redirect_uri": _callback_url(provider), "state": state, "scope": PROVIDERS[provider]["scope"]}
    if provider == "google":
        params.update({"response_type": "code", "prompt": "select_account", "access_type": "online"})
    response = RedirectResponse(f"{PROVIDERS[provider]['authorize']}?{urlencode(params)}", status_code=302)
    response.set_cookie(STATE_COOKIE, sign({"state": state, "provider": provider, "next": _safe_next(next), "exp": time.time() + STATE_SECONDS, "sid": "state"}), **_cookie_args(STATE_SECONDS))
    return response


def _profile(provider: str, code: str, credentials: tuple[str, str]) -> dict[str, Any]:
    token_request = {"client_id": credentials[0], "client_secret": credentials[1], "code": code, "redirect_uri": _callback_url(provider)}
    if provider == "github":
        token = requests.post(PROVIDERS[provider]["token"], json=token_request, headers={"Accept": "application/json"}, timeout=15).json()
        access = token.get("access_token")
        if not access:
            raise RuntimeError(token.get("error_description") or "GitHub returned no access token")
        user = requests.get("https://api.github.com/user", headers={"Authorization": f"Bearer {access}", "Accept": "application/vnd.github+json"}, timeout=15)
        user.raise_for_status()
        data = user.json()
        return {"provider": "github", "login": data["login"], "name": data.get("name") or data["login"], "avatarUrl": data.get("avatar_url"), "github": data["login"]}
    token = requests.post(PROVIDERS[provider]["token"], data={**token_request, "grant_type": "authorization_code"}, timeout=15).json()
    access = token.get("access_token")
    if not access:
        raise RuntimeError(token.get("error_description") or "Google returned no access token")
    user = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {access}"}, timeout=15)
    user.raise_for_status()
    data = user.json()
    return {"provider": "google", "login": data.get("email"), "name": data.get("name") or data.get("email"), "avatarUrl": data.get("picture"), "github": None}


@router.get("/{provider}/callback")
def callback(provider: str, request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> RedirectResponse:
    saved = verify(request.cookies.get(STATE_COOKIE))
    next_path = (saved or {}).get("next", "/")
    credentials = _credentials(provider) if provider in PROVIDERS else None

    def finish(path: str) -> RedirectResponse:
        response = RedirectResponse(_frontend_url(path), status_code=302)
        response.delete_cookie(STATE_COOKIE, path="/")
        return response

    if error:  # the user cancelled on the provider's page
        return finish(f"{next_path}{'&' if '?' in next_path else '?'}login=cancelled")
    if credentials is None or not code or not saved or saved.get("provider") != provider or not hmac.compare_digest(str(saved.get("state")), str(state or "")):
        return finish(f"{next_path}{'&' if '?' in next_path else '?'}login=failed")
    try:
        user = _profile(provider, code, credentials)
    except Exception:  # noqa: BLE001 - any provider failure is reported to the user the same way
        return finish(f"{next_path}{'&' if '?' in next_path else '?'}login=failed")
    response = finish(f"{next_path}{'&' if '?' in next_path else '?'}login=success")
    response.set_cookie(SESSION_COOKIE, sign({"user": user, "exp": time.time() + SESSION_SECONDS, "sid": secrets.token_hex(12)}), **_cookie_args(SESSION_SECONDS))
    return response


@router.post("/logout")
def logout(request: Request) -> JSONResponse:
    payload = verify(request.cookies.get(SESSION_COOKIE))
    if payload:
        revoke(payload)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


__all__ = ["configured_providers", "current_user", "revoke", "router", "sign", "verify"]
