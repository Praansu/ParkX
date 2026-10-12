"""Tests for operator auth: key hashing, role lookup, and HTTP guards."""

import pytest

import parking_backend.database as db
from parking_backend.auth import (
    ROLE_RANK,
    create_operator,
    hash_key,
    lookup_role,
)


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    yield


def test_hash_is_stable_and_not_plaintext():
    h1, h2 = hash_key("pkx_abc"), hash_key("pkx_abc")
    assert h1 == h2
    assert h1 != "pkx_abc"
    assert len(h1) == 64


def test_create_and_lookup_roles():
    owner_key = create_operator("boss", role="owner")
    att_key = create_operator("gate", role="attendant")
    assert owner_key.startswith("pkx_")
    assert lookup_role(owner_key) == "owner"
    assert lookup_role(att_key) == "attendant"
    assert lookup_role("pkx_wrong") is None
    assert lookup_role("") is None


def test_role_ranking():
    assert ROLE_RANK["owner"] > ROLE_RANK["attendant"]


def test_bad_role_rejected():
    with pytest.raises(ValueError):
        create_operator("x", role="superadmin")
