"""Payments module — collect parking fees online (Nepal gateways).

Design: a small gateway interface so Khalti / eSewa / test-mode all speak
the same language. Bookings carry a `payment_status` column driven by a
strict state machine:

    UNPAID -> PENDING -> PAID | FAILED
    PAID  -> REFUNDED   (refunds are gateway-side; we record the outcome)

Rules enforced here, not in callers:
- Money movement only happens through initiate() + verify().
- A booking is NEVER marked PAID from a client callback alone — eSewa
  redirects and Khalti return URLs are untrusted input; only a
  server-to-server verification (Khalti lookup) or a verified HMAC
  signature (eSewa callback) flips state.
- TestGateway lets the whole flow run with zero keys (demos, CI).

Live use requires merchant credentials (registered company + PAN):
set PAYMENTS_MODE=live plus the gateway keys. Until then everything
runs against TestGateway and says so in its responses.
"""

import hashlib
import hmac
import secrets
import time
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from parking_backend import database as db

# --- State machine ---------------------------------------------------------

VALID_TRANSITIONS = {
    "UNPAID": {"PENDING", "FAILED"},
    "PENDING": {"PAID", "FAILED"},
    "PAID": {"REFUNDED"},
    "FAILED": {"PENDING"},  # retry allowed
    "REFUNDED": set(),
}

TERMINAL_PAID = "PAID"


def transition_ok(from_status: str, to_status: str) -> bool:
    return to_status in VALID_TRANSITIONS.get(from_status or "UNPAID", set())


def set_payment_status(booking_id: str, to_status: str, txn_id: str = "") -> dict:
    """Move a booking's payment_status through the state machine.

    Raises ValueError on illegal transitions so callers can't skip states.
    """
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        raise ValueError(f"Booking {booking_id} not found.")
    current = booking.get("payment_status") or "UNPAID"
    if not transition_ok(current, to_status):
        raise ValueError(f"Illegal payment transition {current} -> {to_status}.")
    db.update_payment_status(booking_id, to_status, txn_id)
    return {"booking_id": booking_id, "from": current, "to": to_status}


# --- Gateway interface -----------------------------------------------------


class PaymentGateway(ABC):
    name: str = "base"

    @abstractmethod
    def initiate(self, booking_id: str, amount_npr: int, **kwargs) -> dict:
        """Start a payment. Returns {txn_id, pay_url, note}."""

    @abstractmethod
    def verify(self, txn_id: str) -> dict:
        """Server-side status check. Returns {status, raw} where status is
        one of PENDING | PAID | FAILED | REFUNDED."""


# --- Test gateway (no keys, for demos + CI) --------------------------------

_test_ledger: dict = {}


class TestGateway(PaymentGateway):
    """Fake gateway: initiate always works, payments stay PENDING until the
    test-only settle endpoint flips them. Refuses to run in live mode."""

    name = "test"

    def __init__(self, live: bool = False):
        if live:
            raise RuntimeError("TestGateway must never run with PAYMENTS_MODE=live.")
        self.live = live

    def initiate(self, booking_id: str, amount_npr: int, **kwargs) -> dict:
        txn_id = f"TEST-{secrets.token_hex(4).upper()}"
        _test_ledger[txn_id] = {
            "booking_id": booking_id,
            "amount_npr": amount_npr,
            "status": "PENDING",
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        return {
            "txn_id": txn_id,
            "pay_url": f"/api/payments/test/pay/{txn_id}",
            "note": "TEST MODE — no real money moves. Settle via the test endpoint.",
        }

    def verify(self, txn_id: str) -> dict:
        entry = _test_ledger.get(txn_id)
        if not entry:
            return {"status": "FAILED", "raw": {"error": "unknown txn_id"}}
        return {"status": entry["status"], "raw": dict(entry)}

    @staticmethod
    def settle(txn_id: str) -> dict:
        entry = _test_ledger.get(txn_id)
        if not entry:
            raise ValueError(f"Unknown test transaction {txn_id}.")
        entry["status"] = "PAID"
        return {"txn_id": txn_id, "status": "PAID"}


# --- Khalti (REST v2: initiate -> pidx -> lookup) ----------------------------

KHALTI_SANDBOX = "https://dev.khalti.com"
KHALTI_PROD = "https://khalti.com"


class KhaltiGateway(PaymentGateway):
    """Khalti ePayment v2. Amounts go in paisa (1 NPR = 100 paisa).
    Never mark PAID from the return_url alone — always lookup the pidx."""

    name = "khalti"

    def __init__(
        self, secret_key: str, base_url: str = KHALTI_SANDBOX, timeout: float = 15.0
    ):
        if not secret_key:
            raise ValueError("KHALTI_SECRET_KEY is required for live Khalti payments.")
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Key {self.secret_key}",
            "Content-Type": "application/json",
        }

    def initiate(
        self, booking_id: str, amount_npr: int, return_url: str = "", **kwargs
    ) -> dict:
        payload = {
            "return_url": return_url,
            "website_url": return_url.rsplit("/", 1)[0]
            if "/" in return_url
            else return_url,
            "amount": int(amount_npr) * 100,
            "purchase_order_id": booking_id,
            "purchase_order_name": f"ParkX booking {booking_id}",
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/v2/epayment/initiate/",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        pidx = data.get("pidx")
        if not pidx:
            raise ValueError(f"Khalti initiate gave no pidx: {data}")
        # NOTE: the caller records the payment row (routes own all DB writes
        # for bookings so test and live gateways behave identically).
        return {
            "txn_id": pidx,
            "pay_url": data.get("payment_url"),
            "note": "Redirect the driver here; verify the pidx server-side after return.",
        }

    def verify(self, txn_id: str) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/v2/epayment/lookup/",
                json={"pidx": txn_id},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        status = str(data.get("status", "")).upper()
        mapped = {
            "COMPLETED": "PAID",
            "PENDING": "PENDING",
            "USER_CANCELLED": "FAILED",
            "EXPIRED": "FAILED",
        }.get(status, "PENDING")
        return {"status": mapped, "raw": data}


# --- eSewa (ePay v2: HMAC-signed form + signed callback) ---------------------

ESEWA_UAT_FORM = "https://rc-epay.esewa.com.np/api/epay/main/v2/form"
ESEWA_PROD_FORM = "https://epay.esewa.com.np/api/epay/main/v2/form"
ESEWA_UAT_STATUS = "https://uat.esewa.com.np/api/epay/transaction/status/"
ESEWA_PROD_STATUS = "https://epay.esewa.com.np/api/epay/transaction/status/"


def esewa_signature(
    total_amount: str, transaction_uuid: str, product_code: str, secret_key: str
) -> str:
    """HMAC-SHA256 (hex) over comma-joined signed fields, in the exact order
    listed in signed_field_names. Any deviation = invalid signature."""
    message = f"{total_amount},{transaction_uuid},{product_code}"
    return hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()


class EsewaGateway(PaymentGateway):
    """eSewa ePay v2. Form fields are generated locally (pure HMAC, no network);
    completion is proven by the signed success callback, re-verified here."""

    name = "esewa"

    def __init__(self, merchant_code: str, secret_key: str, sandbox: bool = True):
        if not merchant_code or not secret_key:
            raise ValueError("ESEWA_MERCHANT_CODE and ESEWA_SECRET_KEY are required.")
        self.merchant_code = merchant_code
        self.secret_key = secret_key
        self.form_url = ESEWA_UAT_FORM if sandbox else ESEWA_PROD_FORM
        self.status_url = ESEWA_UAT_STATUS if sandbox else ESEWA_PROD_STATUS

    def initiate(
        self,
        booking_id: str,
        amount_npr: int,
        success_url: str = "",
        failure_url: str = "",
        **kwargs,
    ) -> dict:
        total = str(int(amount_npr))
        txn_uuid = f"{booking_id}-{int(time.time())}"
        signature = esewa_signature(
            total, txn_uuid, self.merchant_code, self.secret_key
        )
        fields = {
            "amount": total,
            "tax_amount": "0",
            "total_amount": total,
            "transaction_uuid": txn_uuid,
            "product_code": self.merchant_code,
            "product_service_charge": "0",
            "product_delivery_charge": "0",
            "success_url": success_url,
            "failure_url": failure_url,
            "signed_field_names": "total_amount,transaction_uuid,product_code",
            "signature": signature,
        }
        # NOTE: the caller records the payment row (see KhaltiGateway).
        return {
            "txn_id": txn_uuid,
            "pay_url": self.form_url,
            "form_fields": fields,
            "note": "POST these fields as a form to pay_url from the driver browser.",
        }

    def verify_callback(self, data: dict) -> dict:
        """Validate a decoded eSewa success-callback payload. Returns PAID only
        when the HMAC signature checks out AND status is COMPLETE."""
        try:
            total = str(data.get("total_amount", ""))
            txn_uuid = str(data.get("transaction_uuid", ""))
            received = str(data.get("signature", ""))
            expected = esewa_signature(
                total, txn_uuid, self.merchant_code, self.secret_key
            )
            if not hmac.compare_digest(received, expected):
                return {"status": "FAILED", "raw": {"error": "signature mismatch"}}
            if str(data.get("status", "")).upper() == "COMPLETE":
                return {"status": "PAID", "raw": data}
            return {"status": "PENDING", "raw": data}
        except Exception as e:
            return {"status": "FAILED", "raw": {"error": str(e)}}

    def verify(self, txn_id: str) -> dict:
        return {
            "status": "PENDING",
            "raw": {"note": "Use verify_callback() on the signed redirect payload."},
        }


# --- Gateway factory ---------------------------------------------------------


def get_gateway(name: str = "", live: bool = False) -> PaymentGateway:
    """Resolve a gateway by name. Anything unconfigured falls back to test
    mode loudly — live money never moves by accident."""
    from parking_backend import config as cfg

    name = (name or cfg.PAYMENTS_GATEWAY).lower()
    live = live or (cfg.PAYMENTS_MODE == "live")
    if name == "khalti":
        if live or cfg.KHALTI_SECRET_KEY:
            base = cfg.KHALTI_PROD if live else cfg.KHALTI_BASE
            return KhaltiGateway(cfg.KHALTI_SECRET_KEY, base)
        print("[PAY] Khalti requested without keys — using TEST gateway.")
    if name == "esewa":
        if live or cfg.ESEWA_SECRET_KEY:
            return EsewaGateway(
                cfg.ESEWA_MERCHANT_CODE, cfg.ESEWA_SECRET_KEY, sandbox=not live
            )
        print("[PAY] eSewa requested without keys — using TEST gateway.")
    return TestGateway(live=False)
