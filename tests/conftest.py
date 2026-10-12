"""Pytest bootstrap: point the app at a throwaway database BEFORE any
parking_backend module is imported (config reads env at import time)."""
import os
import tempfile

_tmp = tempfile.mkstemp(prefix="parkx_test_", suffix=".db")[1]
os.environ["DB_PATH"] = _tmp
os.environ.setdefault("PAYMENTS_MODE", "test")
os.environ.setdefault("ADMIN_API_KEY", "")
