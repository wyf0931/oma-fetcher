"""Pay-as-you-go billing: SKU listing, order creation, Alipay notify handling.

Design notes
------------
* Orders are created with a client-supplied ``idempotency_key`` so a retry never
  double-charges; the same key returns the existing pending order.
* Alipay async notifies drive the ``pending -> paid`` transition. ``mark_order_paid``
  is idempotent (unique credit-ledger grant per order), so Alipay's repeated
  notifies never double-grant credits.
* Alipay's notify reaches us over the public internet; signature verification uses
  Alipay's public key. The notify handler answers plain ``success`` only after the
  database transition commits, and ``failure`` otherwise so Alipay retries.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from .alipay import AlipayClient, AlipayError
from .auth import Principal
from .main import envelope, store

router = APIRouter(prefix="/api/billing", tags=["billing"])

# The single seeded pay-as-you-go pack. Kept in one place so the catalog stays
# editable without touching schema or routes.
DEFAULT_SKU = {
    "code": "fetch-1000",
    "name": "1000 次网页抓取",
    "units": 1000,
    "price_cents": 4900,  # ¥49.00
    "currency": "CNY",
    "sort_order": 0,
}

# A ¥0.10 sandbox smoke-test pack. Seeded hidden (active=0) and only surfaced
# when DEBUG=on, so it never appears in the real catalog or in production.
TEST_SKU = {
    "code": "test-01",
    "name": "测试商品 · 1 次抓取",
    "units": 1,
    "price_cents": 10,  # ¥0.10
    "currency": "CNY",
    "sort_order": 99,
}


def new_out_trade_no() -> str:
    """Globally-unique merchant order number for Alipay (alnum/underscore only)."""
    return f"F{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{secrets.token_hex(6).upper()}"


def cents_to_yuan(cents: int) -> str:
    return f"{cents / 100:.2f}"


def get_alipay_client() -> AlipayClient | None:
    from .config import settings

    if not settings.alipay_enabled:
        return None
    return AlipayClient(
        app_id=settings.alipay_app_id,
        gateway=settings.alipay_gateway,
        merchant_private_key=settings.alipay_merchant_private_key,
        alipay_public_key=settings.alipay_alipay_public_key,
    )


async def current_user_principal(request: Request) -> Principal | None:
    """Resolve the caller for billing endpoints (session cookie or bearer key)."""
    from .main import current_principal

    return current_principal(request)


def ensure_logged_in(principal: Principal | None) -> int | None:
    """Return the user id for an authenticated account, else None (anonymous/bearer-only)."""
    if principal is None or principal.user_id is None:
        return None
    return int(principal.user_id)


def ensure_seed() -> None:
    """Insert the default pay-as-you-go SKU, plus a hidden ¥0.10 test pack on DEBUG."""
    from .config import settings

    if store.available:
        store.seed_sku(
            code=DEFAULT_SKU["code"],
            name=DEFAULT_SKU["name"],
            units=DEFAULT_SKU["units"],
            price_cents=DEFAULT_SKU["price_cents"],
            currency=DEFAULT_SKU["currency"],
            payment_provider="alipay",
            sort_order=DEFAULT_SKU["sort_order"],
        )
        if settings.debug:
            store.seed_sku(
                code=TEST_SKU["code"],
                name=TEST_SKU["name"],
                units=TEST_SKU["units"],
                price_cents=TEST_SKU["price_cents"],
                currency=TEST_SKU["currency"],
                payment_provider="alipay",
                sort_order=TEST_SKU["sort_order"],
                active=0,
            )


@router.get("/test-sku")
async def get_test_sku() -> object:
    """Expose the ¥0.10 sandbox test SKU only when DEBUG=on."""
    from .config import settings

    if not settings.debug:
        return envelope(4105, "not available", status_code=404)
    ensure_seed()
    sku = store.get_sku_by_code(TEST_SKU["code"], include_hidden=True)
    if sku is None:
        return envelope(4101, "test sku unavailable", status_code=404)
    return envelope(0, "ok", {**sku, "price_yuan": cents_to_yuan(int(sku["price_cents"]))})


@router.get("/skus")
async def list_skus() -> object:
    ensure_seed()
    if not store.available:
        return envelope(4003, "storage is not ready", status_code=503)
    skus = [
        {**sku, "price_yuan": cents_to_yuan(int(sku["price_cents"])), "price_cents": int(sku["price_cents"])}
        for sku in store.list_active_skus()
    ]
    return envelope(0, "ok", {"skus": skus, "payment_enabled": get_alipay_client() is not None})


@router.get("/credits")
async def credit_balance(principal: Principal | None = Depends(current_user_principal)) -> object:
    user_id = ensure_logged_in(principal)
    if user_id is None:
        return envelope(4010, "a signed-in account is required", status_code=401)
    if not store.available:
        return envelope(4003, "storage is not ready", status_code=503)
    return envelope(0, "ok", {"credits": store.credit_balance(user_id)})


@router.post("/orders")
async def create_order(
    request: Request,
    principal: Principal | None = Depends(current_user_principal),
) -> object:
    user_id = ensure_logged_in(principal)
    if user_id is None:
        return envelope(4010, "a signed-in account is required", status_code=401)
    if not store.available:
        return envelope(4003, "storage is not ready", status_code=503)
    alipay = get_alipay_client()
    if alipay is None:
        return envelope(4100, "payment is not configured on this deployment", status_code=503)

    ensure_seed()
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return envelope(1001, "invalid JSON body", status_code=400)
    sku_code = str(payload.get("sku_code") or DEFAULT_SKU["code"])
    try:
        quantity = int(payload.get("quantity") or 1)
    except (TypeError, ValueError):
        return envelope(1002, "quantity must be an integer", status_code=422)
    idempotency_key = payload.get("idempotency_key")
    if quantity < 1 or quantity > 100:
        return envelope(1002, "quantity must be between 1 and 100", status_code=422)

    from .config import settings

    # The hidden test SKU is only purchasable on DEBUG and only as a single unit.
    include_hidden = settings.debug and sku_code == TEST_SKU["code"]
    if include_hidden:
        quantity = 1
    sku = store.get_sku_by_code(sku_code, include_hidden=include_hidden)
    if sku is None:
        return envelope(4101, "unknown sku", status_code=404)

    out_trade_no = new_out_trade_no()
    try:
        order = store.create_order(
            user_id=user_id,
            sku=sku,
            quantity=quantity,
            out_trade_no=out_trade_no,
            idempotency_key=str(idempotency_key) if idempotency_key else None,
        )
    except Exception as exc:  # noqa: BLE001
        return envelope(4102, str(exc), status_code=500)

    if order["status"] != "pending":
        # Idempotent replay of an already-paid/closed order: report current state.
        return envelope(0, "ok", {"order": order, "payment_form_html": None})

    try:
        form_html = alipay.build_page_pay_form(
            out_trade_no=order["out_trade_no"],
            total_amount_yuan=cents_to_yuan(int(order["amount_cents"])),
            subject=f"{sku['name']} x{quantity}",
            notify_url=settings.alipay_notify_url or None,
            return_url=settings.alipay_return_url or None,
        )
    except AlipayError as exc:
        return envelope(4103, str(exc), status_code=500)

    return envelope(0, "ok", {"order": order, "payment_form_html": form_html})


@router.get("/orders/{order_id}")
async def get_order(
    order_id: int,
    principal: Principal | None = Depends(current_user_principal),
) -> object:
    """Return an order, actively confirming payment via Alipay while pending.

    Without a public ``notify_url`` Alipay cannot reach us, so the authoritative
    check is ``alipay.trade.query``. The Web UI polls this to grant credits as
    soon as the buyer actually pays.
    """
    user_id = ensure_logged_in(principal)
    if user_id is None:
        return envelope(4010, "a signed-in account is required", status_code=401)
    order = store.get_order(order_id)
    if order is None or int(order["user_id"]) != user_id:
        return envelope(4104, "order not found", status_code=404)

    if order["status"] == "pending":
        alipay = get_alipay_client()
        if alipay is not None:
            try:
                result = await alipay.trade_query(out_trade_no=order["out_trade_no"])
            except AlipayError:
                result = {}
            status = result.get("trade_status")
            if status in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
                try:
                    amount_cents = round(float(result.get("total_amount", "0")) * 100)
                except ValueError:
                    amount_cents = int(order["amount_cents"])
                store.mark_order_paid(
                    order_id=order_id,
                    trade_no=result.get("trade_no", ""),
                    trade_status=status,
                    amount_cents=amount_cents,
                    notify_raw=result,
                    verified=False,
                )
                order = store.get_order(order_id) or order
            elif status == "TRADE_CLOSED":
                store.mark_order_closed(order_id=order_id)
                order = store.get_order(order_id) or order

    return envelope(0, "ok", {"order": order, "credits": store.credit_balance(user_id)})


@router.post("/alipay/notify")
async def alipay_notify(request: Request) -> PlainTextResponse:
    """Alipay async notify receiver. Verifies, applies idempotently, answers success."""
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    alipay = get_alipay_client()
    if alipay is None:
        return PlainTextResponse("failure")

    if not alipay.verify(params):
        return PlainTextResponse("failure")

    out_trade_no = params.get("out_trade_no", "")
    order = store.get_order_by_out_trade_no(out_trade_no) if out_trade_no else None
    if order is None:
        return PlainTextResponse("failure")

    # Guard against a mismatched / forged-but-signed payload: app_id and amount
    # must match the order we created.
    from .config import settings

    if params.get("app_id") != settings.alipay_app_id:
        return PlainTextResponse("failure")
    try:
        notified_cents = round(float(params.get("total_amount", "0")) * 100)
    except ValueError:
        return PlainTextResponse("failure")
    if notified_cents != int(order["amount_cents"]):
        return PlainTextResponse("failure")

    trade_status = params.get("trade_status", "")
    trade_no = params.get("trade_no", "")
    try:
        if trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
            # Idempotent: re-notifies return None and we still answer success.
            store.mark_order_paid(
                order_id=int(order["id"]),
                trade_no=trade_no,
                trade_status=trade_status,
                amount_cents=notified_cents,
                notify_raw=params,
                verified=True,
            )
        else:
            store.record_payment_event(
                order_id=int(order["id"]),
                trade_no=trade_no,
                notify_id=params.get("notify_id"),
                trade_status=trade_status,
                amount_cents=notified_cents,
                notify_raw=params,
                verified=True,
            )
            if trade_status == "TRADE_CLOSED":
                store.mark_order_closed(order_id=int(order["id"]))
    except Exception:  # noqa: BLE001 - any failure makes Alipay retry the notify
        return PlainTextResponse("failure")
    return PlainTextResponse("success")
