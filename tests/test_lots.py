"""Multi-lot support: migration defaults, lot CRUD, per-lot pricing,
booking isolation across lots, and AI helper scoping."""

import sqlite3

import pytest

import parking_backend.database as db
from parking_backend.ai import check_slot_availability, find_available_slots


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db.init_db()
    db.seed_default_lot()
    yield


def test_seed_default_lot_exists():
    lot = db.get_lot("main")
    assert lot is not None
    assert int(lot["slot_count"]) == 3
    assert [s["label"] for s in db.get_lot_slots("main")] == ["1", "2", "3"]


def test_create_lot_validation():
    with pytest.raises(ValueError):
        db.create_lot("bad0", "Bad", 0)
    with pytest.raises(ValueError):
        db.create_lot("bad201", "Bad", 201)


def test_duplicate_lot_rejected():
    db.create_lot("t2-dup", "Dup Lot", 2)
    with pytest.raises(sqlite3.IntegrityError):
        db.create_lot("t2-dup", "Dup Lot", 2)


def test_per_lot_pricing_with_fallback():
    db.create_lot("t2-price", "Price Lot", 4, pricing_json='{"1": 999, "2": 50}')
    assert db.get_lot_price("t2-price", 1) == 999
    # unknown duration falls back to the global table
    from parking_backend.config import PRICES

    assert db.get_lot_price("t2-price", 8) == PRICES[8]
    # lot without pricing uses the global table entirely
    assert db.get_lot_price("main", 1) == PRICES[1]


def test_legacy_rows_default_to_main():
    with db.get_connection() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(bookings)").fetchall()]
        assert "lot_id" in cols
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
        assert "lot_id" in cols


def test_booking_isolation_across_lots():
    db.create_lot("t2-iso-a", "Iso A", 3)
    db.create_lot("t2-iso-b", "Iso B", 3)
    db.add_booking(
        {
            "id": "BK-T2ISO1",
            "lot_id": "t2-iso-a",
            "slot": 1,
            "date": "2030-05-01",
            "time": "10:00",
            "dur": 2,
            "name": "T",
            "phone": "",
            "plate": "X",
            "amount": 90,
            "status": "UPCOMING",
        }
    )
    # same slot/time free on the other lot, taken on this one
    assert check_slot_availability(1, "2030-05-01", "10:00", 2, "t2-iso-b") is True
    assert check_slot_availability(1, "2030-05-01", "10:00", 2, "t2-iso-a") is False
    # legacy default still targets main
    assert check_slot_availability(1, "2030-05-01", "10:00", 2) is True


def test_find_available_slots_respects_lot_size():
    db.create_lot("t2-big", "Big Lot", 5)
    free = find_available_slots("2030-06-01", "09:00", 1, "t2-big")
    assert free == [1, 2, 3, 4, 5]
    free_main = find_available_slots("2030-06-01", "09:00", 1)
    assert free_main == [1, 2, 3]


def test_get_bookings_filters_by_lot():
    rows = db.get_bookings(lot_id="t2-iso-a")
    assert all(r["lot_id"] == "t2-iso-a" for r in rows)
    assert any(r["id"] == "BK-T2ISO1" for r in rows)
