"""Minimal Alipay Vibe Pay client for AI web-app page payments.

Implements just what this service needs, using ``cryptography`` for RSA2 rather
than pulling in Alipay's legacy Python SDK (which is Python 3.13 incompatible):

* ``build_page_pay_form`` — sign a ``alipay.trade.page.pay`` request and render
  the auto-submitting HTML form that redirects the buyer to Alipay.
* ``verify_notify`` — validate an async ``notify_url`` POST against Alipay's
  public key and confirm it is a successful trade.

Signed-string rules follow Alipay's spec: drop ``sign``/``sign_type``, drop
empty values, sort remaining keys, join as ``k=v&`` and sign with RSA2
(SHA256WithRSA). See docs/vibe-pay/ai-web-app-payment-qianyi in the Alipay
Agent-pay documentation center.
"""

from __future__ import annotations

import base64
import html
from typing import Any
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

PAGE_PAY_METHOD = "alipay.trade.page.pay"
QUERY_METHOD = "alipay.trade.query"
SUCCESS_PRODUCT_CODE = "FAST_INSTANT_TRADE_PAY"
TRADE_SUCCESS_STATUSES = {"TRADE_SUCCESS", "TRADE_FINISHED"}


class AlipayError(RuntimeError):
    pass


def _wrap_base64(body: str, header: str) -> str:
    """Wrap a bare base64 key body as a PEM with 64-char lines."""
    return f"-----BEGIN {header}-----\n" + "\n".join(body[i : i + 64] for i in range(0, len(body), 64)) + f"\n-----END {header}-----\n"


def _load_private_key(pem: str) -> rsa.RSAPrivateKey:
    """Parse a merchant RSA2 private key from PEM, PKCS#8 or PKCS#1 (raw base64).

    Alipay hands Python/Node integrations a PKCS#1 body (``appPrivatePkcsKey``)
    and Java a PKCS#8 body. Both wrap the same RSA key, so try PKCS#8 first and
    fall back to PKCS#1 rather than assuming a single wrapper.
    """
    text = pem.strip()
    if "BEGIN" not in text:
        body = "".join(text.split())
        candidates = [
            _wrap_base64(body, "PRIVATE KEY"),      # PKCS#8
            _wrap_base64(body, "RSA PRIVATE KEY"),  # PKCS#1
        ]
    else:
        candidates = [text]
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            key = serialization.load_pem_private_key(candidate.encode("utf-8"), password=None)
        except (ValueError, TypeError) as exc:
            last_error = exc
            continue
        if isinstance(key, rsa.RSAPrivateKey):
            return key
        last_error = AlipayError(f"merchant key is {type(key).__name__}, expected RSA")
    raise AlipayError(f"invalid ALIPAY_MERCHANT_PRIVATE_KEY: {last_error}")


def _load_public_key(pem: str) -> rsa.RSAPublicKey:
    text = pem.strip()
    if "BEGIN" not in text:
        body = "".join(text.split())
        text = (
            "-----BEGIN PUBLIC KEY-----\n"
            + "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
            + "\n-----END PUBLIC KEY-----\n"
        )
    try:
        key = serialization.load_pem_public_key(text.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise AlipayError(f"invalid ALIPAY_ALIPAY_PUBLIC_KEY: {exc}") from exc
    if not isinstance(key, rsa.RSAPublicKey):
        raise AlipayError("ALIPAY_ALIPAY_PUBLIC_KEY is not an RSA public key")
    return key


def _signed_string(params: dict[str, str]) -> str:
    """Alipay canonical string: sorted keys, skip empty values, k=v joined by &."""
    items = sorted((key, value) for key, value in params.items() if value not in ("", None))
    return "&".join(f"{key}={value}" for key, value in items)


class AlipayClient:
    def __init__(self, *, app_id: str, gateway: str, merchant_private_key: str, alipay_public_key: str) -> None:
        self.app_id = app_id
        self.gateway = gateway.rstrip("/")
        self._private_key = _load_private_key(merchant_private_key)
        self._alipay_public_key = _load_public_key(alipay_public_key)

    def _sign(self, params: dict[str, str]) -> str:
        message = _signed_string(params).encode("utf-8")
        try:
            signature = self._private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:  # noqa: BLE001 - normalize crypto failures
            raise AlipayError(f"alipay signing failed: {exc}") from exc
        return base64.b64encode(signature).decode("ascii")

    def verify(self, params: dict[str, str]) -> bool:
        """Verify a signed Alipay payload (async notify or sync return)."""
        sign = params.get("sign")
        if not sign:
            return False
        to_verify = {k: v for k, v in params.items() if k not in ("sign", "sign_type") and v not in ("", None)}
        message = _signed_string(to_verify).encode("utf-8")
        try:
            self._alipay_public_key.verify(
                base64.b64decode(sign),
                message,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    def _common_params(self, *, notify_url: str | None, return_url: str | None) -> dict[str, str]:
        params: dict[str, str] = {
            "app_id": self.app_id,
            "method": PAGE_PAY_METHOD,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
        }
        if notify_url:
            params["notify_url"] = notify_url
        if return_url:
            params["return_url"] = return_url
        return params

    def page_pay_fields(
        self,
        *,
        out_trade_no: str,
        total_amount_yuan: str,
        subject: str,
        notify_url: str | None = None,
        return_url: str | None = None,
    ) -> dict[str, str]:
        """Build the signed form fields for ``alipay.trade.page.pay``."""
        biz_content = {
            "out_trade_no": out_trade_no,
            "total_amount": total_amount_yuan,
            "subject": subject,
            "product_code": SUCCESS_PRODUCT_CODE,
        }
        params = self._common_params(notify_url=notify_url, return_url=return_url)
        import json

        params["biz_content"] = json.dumps(biz_content, ensure_ascii=False)
        params["sign"] = self._sign(params)
        return params

    def build_page_pay_form(self, **kwargs: Any) -> str:
        """Render the auto-submitting HTML form that forwards the buyer to Alipay.

        Alipay requires ``charset`` in the action URL's query string (not only in
        the POST body) — omitting it triggers ``invalid-signature`` in a real
        browser, so mirror the official SDK's action URL here.
        """
        fields = self.page_pay_fields(**kwargs)
        inputs = "\n".join(
            f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}" />'
            for key, value in fields.items()
        )
        charset = fields.get("charset", "utf-8")
        action = f"{self.gateway}?charset={quote(charset, safe='')}"
        return (
            f'<form id="alipay-submit" name="alipaysubmit" action="{html.escape(action)}" '
            f'method="post">\n{inputs}\n'
            '<input type="submit" value="Pay" style="display:none" />\n</form>\n'
            "<script>document.getElementById('alipay-submit').submit();</script>"
        )

    def page_pay_redirect_url(self, **kwargs: Any) -> str:
        """GET-style gateway URL (alternative to the POST form for simple redirects)."""
        fields = self.page_pay_fields(**kwargs)
        query = "&".join(f"{key}={quote(value, safe='')}" for key, value in fields.items())
        return f"{self.gateway}?{query}"

    def is_success_notify(self, params: dict[str, str]) -> bool:
        """True when params are a verified async notify of a successful trade."""
        if not self.verify(params):
            return False
        return params.get("trade_status") in TRADE_SUCCESS_STATUSES

    async def trade_query(self, *, out_trade_no: str) -> dict[str, Any]:
        """Call ``alipay.trade.query`` against the configured gateway.

        Returns the parsed ``alipay_trade_query_response`` object, or raises
        ``AlipayError`` on a non-zero result. Used as the authoritative payment
        check when no public ``notify_url`` is configured.
        """
        import json as _json

        biz = _json.dumps({"out_trade_no": out_trade_no}, ensure_ascii=False)
        params = {
            "app_id": self.app_id,
            "method": QUERY_METHOD,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": biz,
        }
        params["sign"] = self._sign(params)
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.gateway, data=params)
        result = self._parse_gateway_response(response.text)
        return result

    @staticmethod
    def _parse_gateway_response(text: str) -> dict[str, Any]:
        """Extract the ``<method>_response`` object from a gateway payload.

        The sandbox sometimes labels the response ``text/html`` and mixes in GBK
        bytes around the JSON, so don't trust the content-type: slice out the
        balanced JSON object directly.
        """
        import json as _json

        start = text.find("{")
        if start == -1:
            raise AlipayError("gateway returned no JSON object")
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        payload = _json.loads(text[start : index + 1])
                    except ValueError as exc:
                        raise AlipayError("gateway JSON was malformed") from exc
                    for value in payload.values():
                        if isinstance(value, dict):
                            return value
                    raise AlipayError("gateway JSON had no response object")
        raise AlipayError("gateway JSON was unbalanced")
