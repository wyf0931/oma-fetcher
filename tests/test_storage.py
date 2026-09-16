from pathlib import Path

from app.storage import DocumentStore


def make_store(tmp_path: Path) -> DocumentStore:
    dictionary = tmp_path / "custom.txt"
    dictionary.write_text("国家标准 10\n外文版 10\n", encoding="utf-8")
    store = DocumentStore(str(tmp_path / "research.db"), str(dictionary))
    store.initialize()
    assert store.available
    return store


def persist_sample(store: DocumentStore):
    return store.persist(
        requested_url="https://samr.gov.cn/request",
        final_url="https://samr.gov.cn/final",
        content="市场监管总局公开征求国家标准外文版管理办法意见。",
        page={
            "url": "https://samr.gov.cn/final",
            "title": "国家标准外文版管理办法征求意见",
            "description": "市场监管总局公开征求意见",
            "hostname": "samr.gov.cn",
            "date": "2026-09-09",
            "tags": ["意见,国家标准", "市场监管"],
        },
        strategy="httpx",
        status_code=200,
        content_type="text/html",
        attempts=[{"strategy": "httpx", "reason": "success"}],
        raw_response={"code": 0},
    )


def test_persist_deduplicates_content_but_keeps_fetch_history(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = persist_sample(store)
    second = persist_sample(store)

    assert not first.deduplicated
    assert second.deduplicated
    assert first.document_id == second.document_id
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fetches").fetchone()[0] == 2


def test_search_uses_title_tags_content_and_filters(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    persist_sample(store)

    results = store.search(
        query="国家标准",
        hostname="samr.gov.cn",
        published_after="2026-01-01",
        published_before="2026-12-31",
        limit=10,
    )
    assert len(results) == 1
    assert results[0]["title"] == "国家标准外文版管理办法征求意见"
    assert "<mark>" in results[0]["snippet"]
    assert store.search(query="国家标准", hostname="other.example", published_after=None, published_before=None, limit=10) == []


def test_normalize_tags_splits_comma_separated_metadata() -> None:
    assert DocumentStore.normalize_tags(["意见,国家标准", "市场，监管", "国家标准"]) == ["意见", "国家标准", "市场", "监管"]


def test_successful_route_is_reused_then_expired_on_failure(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_route_success(
        hostname="itu.int",
        target_kind="page",
        strategy="scrapling_stealth",
        extraction_method="article_cards",
        ttl_hours=168,
    )
    assert store.get_route("www.itu.int", "page").strategy == "scrapling_stealth"
    store.record_route_failure(hostname="itu.int", target_kind="page", strategy="scrapling_stealth")
    assert store.get_route("itu.int", "page") is None


def test_document_list_detail_and_delete(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    saved = persist_sample(store)

    rows, total = store.list_documents(page=1, page_size=20, content="国家标准")
    assert total == 1
    assert rows[0]["id"] == saved.document_id
    detail = store.get_document(saved.document_id)
    assert detail is not None
    assert detail["content"]
    assert len(detail["fetches"]) == 1
    assert store.delete_document(saved.document_id)
    assert store.get_document(saved.document_id) is None
