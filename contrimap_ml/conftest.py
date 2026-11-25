"""Test isolation: every test gets an empty in-memory store, never the local SQLite file or Supabase."""

import os

import pytest

os.environ.setdefault("CONTRIMAP_WARMUP", "0")


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """Tests never reach a real LLM: keys from .env are removed; tests that need a provider set (and mock) one."""
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CONTRIMAP_FORCE_LLM", "GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _memory_store():
    from contrimap_ml import store

    store.configure(store.Store(None))
    yield
    store.configure(None)
