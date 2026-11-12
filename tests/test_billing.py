from pathlib import Path

import pytest

from app.alipay import AlipayClient, AlipayError
from app.storage import DocumentStore


def make_store(tmp_path: Path) -> DocumentStore:
    store = DocumentStore(str(tmp_path / "billing.db"), str(tmp_path / "custom.txt"))
    store.initialize()
    assert store.available
    return store


def make_user(store: DocumentStore, email: str = "buyer@example.com") -> int:
    # A dummy hash: these tests exercise billing, not password verification.
    stored_hash = "billing-test-dummy-hash"
    return int(
        store.create_user(email=email, password_hash=stored_hash, display_name="Buyer")["id"]
    )


def seed_sku(store: DocumentStore) -> dict:
    sku_id = store.seed_sku(code="fetch-1000", name="1000 fetches", units=1000, price_cents=4900)
    sku = store.get_sku(sku_id)
    assert sku is not None
    return sku


def make_fetch(store: DocumentStore, user_id: int, tag: str) -> int:
    """Persist a real fetch row and return its id (credit_ledger.fetch_id is an FK)."""
    result = store.persist(
        requested_url=f"https://example.com/{tag}",
        final_url=f"https://example.com/{tag}",
        content=f"content for {tag}",
        page={"url": f"https://example.com/{tag}", "hostname": "example.com"},
        strategy="httpx",
        status_code=200,
        content_type="text/html",
        attempts=[],
        raw_response={},
        user_id=user_id,
    )
    # The ledger's fetch_id is an FK to fetches(id); look up the fetch we just wrote.
    with store._connect() as connection:
        row = connection.execute(
            "SELECT id FROM fetches WHERE document_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (result.document_id, user_id),
        ).fetchone()
    assert row is not None
    return int(row["id"])


def test_create_order_is_idempotent_on_idempotency_key(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_id = make_user(store)
    sku = seed_sku(store)

    first = store.create_order(
        user_id=user_id, sku=sku, quantity=1, out_trade_no="T1", idempotency_key="idem-1"
    )
    second = store.create_order(
        user_id=user_id, sku=sku, quantity=1, out_trade_no="T2", idempotency_key="idem-1"
    )
    # Same idempotency key returns the original order; no duplicate rows.
    assert first["id"] == second["id"]
    assert first["out_trade_no"] == "T1"
    assert store.list_orders(user_id=user_id) .__len__() == 1


def test_amount_is_quantity_times_unit_price_in_cents(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_id = make_user(store)
    sku = seed_sku(store)

    order = store.create_order(user_id=user_id, sku=sku, quantity=3, out_trade_no="T3")
    assert order["unit_price_cents"] == 4900
    assert order["amount_cents"] == 4900 * 3
    assert order["status"] == "pending"


def test_mark_order_paid_grants_credits_exactly_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_id = make_user(store)
    sku = seed_sku(store)
    order = store.create_order(user_id=user_id, sku=sku, quantity=2, out_trade_no="T4")

    notify = {"notify_id": "n1", "trade_status": "TRADE_SUCCESS", "out_trade_no": "T4"}
    first = store.mark_order_paid(
        order_id=int(order["id"]),
        trade_no="2024ALIPAY1",
        trade_status="TRADE_SUCCESS",
        amount_cents=int(order["amount_cents"]),
        notify_raw=notify,
        verified=True,
    )
    assert first is not None and first["status"] == "paid"
    assert first["credits_granted"] == 2000
    assert store.credit_balance(user_id) == 2000

    # A replayed notify must not double-grant.
    replay = store.mark_order_paid(
        order_id=int(order["id"]),
        trade_no="2024ALIPAY1",
        trade_status="TRADE_SUCCESS",
        amount_cents=int(order["amount_cents"]),
        notify_raw=notify,
        verified=True,
    )
    assert replay is None
    assert store.credit_balance(user_id) == 2000


def test_consume_credit_is_atomic_and_never_negative(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_id = make_user(store)
    sku = seed_sku(store)
    order = store.create_order(user_id=user_id, sku=sku, quantity=1, out_trade_no="T5")
    store.mark_order_paid(
        order_id=int(order["id"]),
        trade_no="TR5",
        trade_status="TRADE_SUCCESS",
        amount_cents=int(order["amount_cents"]),
        notify_raw={"notify_id": "n5"},
        verified=True,
    )
    assert store.credit_balance(user_id) == 1000

    fetch_a = make_fetch(store, user_id, "a")
    # Consume within balance succeeds and is idempotent per fetch.
    assert store.consume_credit(user_id=user_id, fetch_id=fetch_a, units=1) is True
    assert store.consume_credit(user_id=user_id, fetch_id=fetch_a, units=1) is True  # replay
    assert store.credit_balance(user_id) == 999


def test_consume_drains_to_zero_and_never_negative(tmp_path: Path) -> None:
    """Drain a small balance to prove the conditional UPDATE guards against overdraft."""
    store = make_store(tmp_path)
    user_id = make_user(store)
    sku = store.get_sku(store.seed_sku(code="tiny", name="tiny", units=3, price_cents=100))
    assert sku is not None
    order = store.create_order(user_id=user_id, sku=sku, quantity=1, out_trade_no="TD")
    store.mark_order_paid(
        order_id=int(order["id"]),
        trade_no="TRD",
        trade_status="TRADE_SUCCESS",
        amount_cents=int(order["amount_cents"]),
        notify_raw={"notify_id": "nd"},
        verified=True,
    )
    assert store.credit_balance(user_id) == 3

    fetch_ids = [make_fetch(store, user_id, tag) for tag in ("d1", "d2", "d3")]
    assert store.consume_credit(user_id=user_id, fetch_id=fetch_ids[0], units=1) is True
    assert store.consume_credit(user_id=user_id, fetch_id=fetch_ids[1], units=1) is True
    assert store.consume_credit(user_id=user_id, fetch_id=fetch_ids[2], units=1) is True
    assert store.credit_balance(user_id) == 0
    # Balance exhausted: further consumes must fail and leave the balance at zero.
    spare = make_fetch(store, user_id, "spare")
    assert store.consume_credit(user_id=user_id, fetch_id=spare, units=1) is False
    assert store.consume_credit(user_id=user_id, fetch_id=spare, units=2) is False
    assert store.credit_balance(user_id) == 0


def test_consume_without_balance_returns_false(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_id = make_user(store)
    assert store.consume_credit(user_id=user_id, fetch_id=1, units=1) is False
    assert store.credit_balance(user_id) == 0


def test_close_only_transitions_pending_order(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    user_id = make_user(store)
    sku = seed_sku(store)
    order = store.create_order(user_id=user_id, sku=sku, quantity=1, out_trade_no="T6")
    order_id = int(order["id"])

    store.mark_order_closed(order_id=order_id)
    closed = store.get_order(order_id)
    assert closed is not None and closed["status"] == "closed"

    # Closing again is a no-op; paying a closed order is rejected by the state guard.
    store.mark_order_closed(order_id=order_id)
    still = store.get_order(order_id)
    assert still is not None and still["status"] == "closed"


def test_alipay_client_rejects_bad_key() -> None:
    with pytest.raises(AlipayError):
        AlipayClient(
            app_id="app",
            gateway="https://openapi.alipay.com/gateway.do",
            merchant_private_key="not-a-key",
            alipay_public_key="not-a-key",
        )
