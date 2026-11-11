"""User-scoping tests: the core security boundary of the P3 isolation layer.

These exercise the storage + service layers directly (no HTTP router) so they do
not depend on main.py. Every assertion here is about user A not being able to
reach user B's documents or API keys.
"""

import asyncio
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from app import service
from app.storage import DocumentStore, StorageResult

_HASHER = PasswordHasher()


def make_store(tmp_path: Path) -> DocumentStore:
    dictionary = tmp_path / "custom.txt"
    dictionary.write_text("国家标准 10\n", encoding="utf-8")
    store = DocumentStore(str(tmp_path / "research.db"), str(dictionary))
    store.initialize()
    assert store.available
    return store


def make_users(store: DocumentStore) -> tuple[int, int]:
    # These tests exercise data isolation, not authentication; the password_hash
    # value is irrelevant, so we store a real argon2 hash of a throwaway secret.
    password_hash = _HASHER.hash("isolation-test-password")
    user_a = store.create_user(email="a@example.com", password_hash=password_hash, display_name="A")
    user_b = store.create_user(email="b@example.com", password_hash=password_hash, display_name="B")
    return int(user_a["id"]), int(user_b["id"])


def persist_for(store: DocumentStore, user_id: int, slug: str, content: str) -> StorageResult:
    url = f"https://example.com/{slug}"
    return store.persist(
        requested_url=url,
        final_url=url,
        content=content,
        page={
            "url": url,
            "title": slug,
            "description": slug,
            "hostname": "example.com",
            "date": "2026-09-09",
            "tags": [],
        },
        strategy="httpx",
        status_code=200,
        content_type="text/html",
        attempts=[],
        raw_response={"code": 0},
        user_id=user_id,
    )


# -- Storage layer isolation -------------------------------------------------


def test_search_scopes_documents_to_their_owner(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_a, user_b = make_users(store)
    doc_a = persist_for(store, user_a, "alpha", "国家标准 alpha content")
    doc_b = persist_for(store, user_b, "beta", "国家标准 beta content")

    # The query matches BOTH documents; scoping must still hide the other user's.
    ids_a = {row["id"] for row in store.search(query="国家标准", hostname=None, published_after=None, published_before=None, limit=10, user_id=user_a)}
    ids_b = {row["id"] for row in store.search(query="国家标准", hostname=None, published_after=None, published_before=None, limit=10, user_id=user_b)}
    admin_ids = {row["id"] for row in store.search(query="国家标准", hostname=None, published_after=None, published_before=None, limit=10)}

    assert ids_a == {doc_a.document_id}
    assert ids_b == {doc_b.document_id}
    assert admin_ids == {doc_a.document_id, doc_b.document_id}


def test_list_documents_scopes_rows_and_total(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_a, user_b = make_users(store)
    doc_a = persist_for(store, user_a, "alpha", "content a")
    persist_for(store, user_b, "beta", "content b")

    rows_a, total_a = store.list_documents(page=1, page_size=20)
    assert total_a == 2  # admin/no-scope view sees everything

    rows_b, total_b = store.list_documents(page=1, page_size=20, user_id=user_a)
    assert total_b == 1
    assert [row["id"] for row in rows_b] == [doc_a.document_id]

    _, total_c = store.list_documents(page=1, page_size=20, user_id=user_b)
    assert total_c == 1


def test_get_document_hides_other_users_document(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_a, user_b = make_users(store)
    doc_a = persist_for(store, user_a, "alpha", "content a")

    assert store.get_document(doc_a.document_id, user_id=user_a) is not None
    assert store.get_document(doc_a.document_id) is not None  # admin view
    assert store.get_document(doc_a.document_id, user_id=user_b) is None


def test_delete_document_denies_non_owner(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_a, user_b = make_users(store)
    doc_a = persist_for(store, user_a, "alpha", "content a")

    assert store.delete_document(doc_a.document_id, user_id=user_b) is False
    assert store.get_document(doc_a.document_id) is not None  # still intact

    assert store.delete_document(doc_a.document_id, user_id=user_a) is True
    assert store.get_document(doc_a.document_id) is None


def test_api_key_listing_and_deletion_are_scoped_to_owner(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_a, user_b = make_users(store)
    _, key_a = store.create_api_key(user_id=user_a, name="a-key", scopes=["fetch"], expires_at=None, pepper="p" * 32)
    _, key_b = store.create_api_key(user_id=user_b, name="b-key", scopes=["fetch"], expires_at=None, pepper="p" * 32)

    keys_a = store.list_api_keys(user_id=user_a)
    assert [key["id"] for key in keys_a] == [key_a["id"]]

    # A cannot delete B's key; B can delete their own.
    assert store.delete_api_key(key_b["id"], user_id=user_a) is False
    assert store.delete_api_key(key_b["id"], user_id=user_b) is True
    assert store.list_api_keys(user_id=user_b) == []


# -- Service layer isolation -------------------------------------------------


def test_service_search_and_list_scoping(monkeypatch, tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_a, user_b = make_users(store)
    doc_a = persist_for(store, user_a, "alpha", "国家标准 alpha content")
    doc_b = persist_for(store, user_b, "beta", "国家标准 beta content")
    monkeypatch.setattr(service, "store", store)

    search_a = asyncio.run(service.search_documents(query="国家标准", user_id=user_a))
    assert {row["id"] for row in search_a.data} == {doc_a.document_id}

    list_b = asyncio.run(service.list_documents(user_id=user_b))
    assert {row["id"] for row in list_b.data} == {doc_b.document_id}
    assert list_b.meta["total"] == 1

    admin_list = asyncio.run(service.list_documents())
    assert admin_list.meta["total"] == 2


def test_service_get_document_denies_non_owner(monkeypatch, tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_a, user_b = make_users(store)
    doc_a = persist_for(store, user_a, "alpha", "content a")
    monkeypatch.setattr(service, "store", store)

    ok = asyncio.run(service.get_document(doc_a.document_id, user_id=user_a))
    assert ok.code == 0

    denied = asyncio.run(service.get_document(doc_a.document_id, user_id=user_b))
    assert denied.code == 4041
    assert denied.status_code == 404


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
