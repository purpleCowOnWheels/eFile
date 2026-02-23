"""Tests for SessionStore encrypt/decrypt/list/migrate."""

from __future__ import annotations

import json

import pytest
from pfile.models.filer import FilingStatus
from pfile.models.session import FilingSession
from pfile.session.store import SessionNotFoundError, SessionStore


def _make_session(**kwargs) -> FilingSession:
    return FilingSession(
        tax_year=kwargs.get("tax_year", 2024),
        filing_status=kwargs.get("filing_status", FilingStatus.SINGLE),
    )


@pytest.fixture
def store(tmp_path):
    return SessionStore(base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

def test_save_and_load(store):
    session = _make_session()
    store.save(session)
    loaded = store.load(session.id)
    assert loaded.id == session.id
    assert loaded.tax_year == 2024


def test_save_updates_updated_at(store):
    session = _make_session()
    original_ts = session.updated_at
    store.save(session)
    loaded = store.load(session.id)
    assert loaded.updated_at >= original_ts


def test_load_missing_raises(store):
    with pytest.raises(SessionNotFoundError):
        store.load("nonexistent-id")


def test_delete_removes_file(store):
    session = _make_session()
    store.save(session)
    store.delete(session.id)
    with pytest.raises(SessionNotFoundError):
        store.load(session.id)


def test_delete_missing_raises(store):
    with pytest.raises(SessionNotFoundError):
        store.delete("nonexistent-id")


def test_exists(store):
    session = _make_session()
    assert not store.exists(session.id)
    store.save(session)
    assert store.exists(session.id)


# ---------------------------------------------------------------------------
# Encryption on disk
# ---------------------------------------------------------------------------

def test_saved_file_is_not_plain_json(store, tmp_path):
    session = _make_session()
    store.save(session)
    raw = (tmp_path / f"{session.id}.json").read_bytes()
    # Must not be readable as plain JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)


def test_saved_file_starts_with_fernet_token(store, tmp_path):
    session = _make_session()
    store.save(session)
    raw = (tmp_path / f"{session.id}.json").read_bytes()
    assert raw[:2] == b"gA"


def test_file_permissions_owner_only(store, tmp_path):
    session = _make_session()
    store.save(session)
    path = tmp_path / f"{session.id}.json"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


# ---------------------------------------------------------------------------
# Plaintext migration
# ---------------------------------------------------------------------------

def test_plaintext_session_migrated_on_load(store, tmp_path):
    """A legacy plaintext JSON session should be transparently encrypted on load."""
    session = _make_session()
    plain_json = session.model_dump_json()
    path = tmp_path / f"{session.id}.json"
    path.write_text(plain_json, encoding="utf-8")

    loaded = store.load(session.id)
    assert loaded.id == session.id

    # File should now be encrypted
    raw = path.read_bytes()
    assert raw[:2] == b"gA"


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_returns_all_sessions(store):
    s1 = _make_session(tax_year=2023)
    s2 = _make_session(tax_year=2024)
    store.save(s1)
    store.save(s2)
    sessions = store.list()
    assert len(sessions) == 2


def test_list_sorted_newest_first(store):
    import time
    s1 = _make_session(tax_year=2023)
    store.save(s1)
    time.sleep(0.01)
    s2 = _make_session(tax_year=2024)
    store.save(s2)
    sessions = store.list()
    assert sessions[0].tax_year == 2024


def test_list_skips_corrupt_files(store, tmp_path):
    (tmp_path / "bad.json").write_bytes(b"not-valid-data-at-all")
    s = _make_session()
    store.save(s)
    sessions = store.list()
    assert len(sessions) == 1
    assert sessions[0].id == s.id
