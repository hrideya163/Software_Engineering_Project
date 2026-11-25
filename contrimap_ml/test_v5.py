"""Tests for sign-in (signed sessions, OAuth flow, sign-out) and the recommendations response (no network).

    python -m pytest contrimap_ml/test_v5.py -q
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from contrimap_ml import auth


@pytest.fixture()
def auth_env(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DATA", tmp_path)
    monkeypatch.setenv("CONTRIMAP_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("CONTRIMAP_FRONTEND_URL", "http://app.test/base/")
    monkeypatch.setenv("CONTRIMAP_PUBLIC_API_URL", "http://api.test")
    for name in ("GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    from contrimap_ml.api import app

    return TestClient(app, follow_redirects=False)


def test_signed_tokens_round_trip_and_reject_tampering(auth_env):
    token = auth.sign({"user": {"login": "ada"}, "exp": time.time() + 60, "sid": "s1"})
    assert auth.verify(token)["user"]["login"] == "ada"
    body, mac = token.split(".")
    assert auth.verify(f"{body}x.{mac}") is None
    assert auth.verify(f"{body}.{mac[:-2]}aa") is None
    assert auth.verify(auth.sign({"exp": time.time() - 1, "sid": "s2"})) is None
    assert auth.verify("not-a-token") is None and auth.verify(None) is None


def test_revoked_sessions_stop_verifying(auth_env):
    payload = {"user": {"login": "ada"}, "exp": time.time() + 60, "sid": "s3"}
    token = auth.sign(payload)
    auth.revoke(payload)
    assert auth.verify(token) is None


def test_safe_next_blocks_open_redirects():
    assert auth._safe_next("/recommendations?x=1") == "/recommendations?x=1"
    for bad in ("//evil.com", "https://evil.com", "\\\\evil", "", None):
        assert auth._safe_next(bad) == "/"


def test_me_without_providers(auth_env):
    body = auth_env.get("/api/auth/me").json()
    assert body == {"user": None, "providers": {"github": False, "google": False}, "configured": False}


def test_unconfigured_provider_returns_to_sign_in_page(auth_env):
    response = auth_env.get("/api/auth/github?next=/profile")
    assert response.status_code == 302
    assert response.headers["location"] == "http://app.test/base/sign-in?error=not_configured&provider=github"
    assert auth_env.get("/api/auth/unknown").status_code == 404


def _configure_github(monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "secret")


def test_github_flow_signs_in_persists_and_signs_out(auth_env, monkeypatch):
    _configure_github(monkeypatch)
    assert auth_env.get("/api/auth/me").json()["providers"]["github"] is True
    start = auth_env.get("/api/auth/github?next=/recommendations")
    location = urlparse(start.headers["location"])
    query = parse_qs(location.query)
    assert location.netloc == "github.com" and query["redirect_uri"] == ["http://api.test/api/auth/github/callback"]
    state = query["state"][0]

    monkeypatch.setattr(auth, "_profile", lambda provider, code, credentials: {"provider": "github", "login": "ada", "name": "Ada", "avatarUrl": None, "github": "ada"})
    done = auth_env.get(f"/api/auth/github/callback?code=abc&state={state}")
    assert done.headers["location"] == "http://app.test/base/recommendations?login=success"
    assert auth_env.get("/api/auth/me").json()["user"]["login"] == "ada"

    old_cookie = auth_env.cookies.get(auth.SESSION_COOKIE)
    assert auth_env.post("/api/auth/logout").json() == {"ok": True}
    assert auth_env.get("/api/auth/me").json()["user"] is None
    # A copy of the old cookie no longer works after sign-out.
    auth_env.cookies.set(auth.SESSION_COOKIE, old_cookie)
    assert auth_env.get("/api/auth/me").json()["user"] is None


def test_callback_rejects_wrong_state_and_reports_cancellation(auth_env, monkeypatch):
    _configure_github(monkeypatch)
    auth_env.get("/api/auth/github?next=/profile")
    wrong = auth_env.get("/api/auth/github/callback?code=abc&state=forged")
    assert wrong.headers["location"].endswith("/profile?login=failed")
    auth_env.get("/api/auth/github?next=/profile")
    cancelled = auth_env.get("/api/auth/github/callback?error=access_denied")
    assert cancelled.headers["location"].endswith("/profile?login=cancelled")
    assert auth_env.get("/api/auth/me").json()["user"] is None


def test_provider_failure_redirects_with_failed(auth_env, monkeypatch):
    _configure_github(monkeypatch)
    state = parse_qs(urlparse(auth_env.get("/api/auth/github").headers["location"]).query)["state"][0]

    def boom(*_):
        raise RuntimeError("token exchange failed")

    monkeypatch.setattr(auth, "_profile", boom)
    assert auth_env.get(f"/api/auth/github/callback?code=abc&state={state}").headers["location"] == "http://app.test/base/?login=failed"


def test_recommendations_return_weights_and_hidden_counts(auth_env, monkeypatch):
    from contrimap_ml import service

    def ranked(owner, repo, profile, mode="balanced", limit=30, user=None):
        if repo == "broken":
            raise service.GitHubError("Not found on GitHub.", 404)
        return {"repository": f"{owner}/{repo}", "weights": {"stack_match": 0.2}, "hidden": [{"number": 9}], "issues": [{"score": 0.4 if repo == "a" else 0.7, "issue": {"number": 1}}]}

    monkeypatch.setattr(service, "ranked_issues", ranked)
    body = auth_env.post("/api/recommendations", json={"profile": {"tech_stack": ["Python"]}, "repositories": ["o/a", "o/b", "o/broken"]}).json()
    assert [item["repository"] for item in body["issues"]] == ["o/b", "o/a"]
    assert body["weights"] == {"stack_match": 0.2} and body["hidden"] == 2
    assert body["searched"] == ["o/a", "o/b"] and "o/broken" in body["errors"]
