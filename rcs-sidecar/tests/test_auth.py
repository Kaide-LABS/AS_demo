import pytest
from fastapi import HTTPException
from auth import verify_token, JWT_SECRET, JWT_ALGORITHM
import jwt
import os

def test_jwt_verification_valid(monkeypatch):
    if not JWT_SECRET:
        monkeypatch.setenv("RCS_JWT_SECRET", "test_secret")
    
    secret = os.getenv("RCS_JWT_SECRET", "test_secret")
    algo = os.getenv("RCS_JWT_ALGORITHM", "HS256")
    
    token = jwt.encode({"sub": "test-project"}, secret, algorithm=algo)
    payload = verify_token(f"Bearer {token}")
    assert payload["sub"] == "test-project"

def test_jwt_verification_expired(monkeypatch):
    if not JWT_SECRET:
        monkeypatch.setenv("RCS_JWT_SECRET", "test_secret")
    
    secret = os.getenv("RCS_JWT_SECRET", "test_secret")
    algo = os.getenv("RCS_JWT_ALGORITHM", "HS256")
    
    # exp in the past
    token = jwt.encode({"sub": "test-project", "exp": 1000000000}, secret, algorithm=algo)
    with pytest.raises(HTTPException) as exc:
        verify_token(f"Bearer {token}")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Token expired"

def test_jwt_skipped_in_dev(monkeypatch):
    monkeypatch.setenv("RCS_JWT_SECRET", "")
    import auth
    monkeypatch.setattr(auth, "JWT_SECRET", None)
    
    payload = auth.verify_token("Bearer anything")
    assert payload["sub"] == "demo-project"
