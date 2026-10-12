"""Tests for the payments module: state machine, test gateway, and the
eSewa HMAC primitives. No network, no keys — the whole point of test mode."""

import pytest

import parking_backend.database as db
from parking_backend import payments as paymod
from parking_backend.payments import (
    EsewaGateway,
    esewa_signature,
    set_payment_status,
    transition_ok,
)

SimGateway = paymod.TestGateway


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    yield


def _booking(bid="BK-TEST1"):
    db.add_booking(
        {
            "id": bid,
            "slot": 1,
            "date": "2030-01-01",
            "time": "10:00",
            "dur": 2,
            "name": "Test",
            "phone": "",
            "plate": "BA 1 PA 0001",
            "amount": 90,
            "status": "UPCOMING",
        }
    )
    return bid


def test_state_machine_happy_path():
    bid = _booking()
    assert set_payment_status(bid, "PENDING")["to"] == "PENDING"
    assert set_payment_status(bid, "PAID")["to"] == "PAID"
    assert set_payment_status(bid, "REFUNDED")["to"] == "REFUNDED"


def test_state_machine_blocks_skips():
    bid = _booking("BK-TEST2")
    with pytest.raises(ValueError):
        set_payment_status(bid, "PAID")  # UNPAID -> PAID is illegal
    with pytest.raises(ValueError):
        set_payment_status("BK-NOPE", "PENDING")  # unknown booking


def test_transition_table():
    assert transition_ok("UNPAID", "PENDING")
    assert transition_ok("PENDING", "PAID")
    assert transition_ok("PAID", "REFUNDED")
    assert not transition_ok("PAID", "PENDING")  # terminal states are sticky
    assert not transition_ok("REFUNDED", "PENDING")


def test_test_gateway_full_cycle():
    gw = SimGateway()
    res = gw.initiate("BK-TEST1", 90)
    assert res["txn_id"].startswith("TEST-")
    assert "TEST MODE" in res["note"]
    assert gw.verify(res["txn_id"])["status"] == "PENDING"
    assert SimGateway.settle(res["txn_id"])["status"] == "PAID"
    assert gw.verify(res["txn_id"])["status"] == "PAID"
    with pytest.raises(ValueError):
        SimGateway.settle("TEST-NOPE")


def test_test_gateway_refuses_live():
    with pytest.raises(RuntimeError):
        SimGateway(live=True)


def test_esewa_signature_is_deterministic():
    s1 = esewa_signature("90", "BK-1-123", "EPAYTEST", "secret")
    s2 = esewa_signature("90", "BK-1-123", "EPAYTEST", "secret")
    assert s1 == s2 and len(s1) == 64
    assert esewa_signature("91", "BK-1-123", "EPAYTEST", "secret") != s1


def test_esewa_callback_accepts_valid_and_rejects_forged():
    gw = EsewaGateway("EPAYTEST", "test-secret", sandbox=True)
    payload = {
        "total_amount": "90",
        "transaction_uuid": "BK-1-123",
        "status": "COMPLETE",
    }
    payload["signature"] = esewa_signature("90", "BK-1-123", "EPAYTEST", "test-secret")
    assert gw.verify_callback(payload)["status"] == "PAID"

    forged = dict(payload, signature="0" * 64)
    assert gw.verify_callback(forged)["status"] == "FAILED"

    pending = dict(payload)
    pending["status"] = "PENDING"
    pending["signature"] = esewa_signature("90", "BK-1-123", "EPAYTEST", "test-secret")
    # signature covers amount+uuid+code only, so re-signing isn't needed here;
    # status PENDING must never yield PAID:
    assert gw.verify_callback(pending)["status"] == "PENDING"


def test_esewa_and_khalti_require_credentials():
    with pytest.raises(ValueError):
        EsewaGateway("", "")
    from parking_backend.payments import KhaltiGateway

    with pytest.raises(ValueError):
        KhaltiGateway("")
