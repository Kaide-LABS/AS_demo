import os
import sys
import pytest
from fastapi import HTTPException
import jwt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import auth


def test_jwt_verification_valid(monkeypatch):
    secret = "test_secret_key_for_testing_32b"
    monkeypatch.setattr(auth, "JWT_SECRET", secret)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")

    token = jwt.encode({"sub": "test-project"}, secret, algorithm="HS256")
    payload = auth.verify_token(f"Bearer {token}")
    assert payload["sub"] == "test-project"


def test_jwt_verification_expired(monkeypatch):
    secret = "test_secret_key_for_testing_32b"
    monkeypatch.setattr(auth, "JWT_SECRET", secret)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")

    token = jwt.encode({"sub": "test-project", "exp": 1000000000}, secret, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(f"Bearer {token}")
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail.lower()


def test_jwt_skipped_in_dev(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET", None)
    payload = auth.verify_token("Bearer anything")
    assert payload["sub"] == "demo-project"
