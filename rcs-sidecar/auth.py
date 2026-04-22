import os
import jwt
from fastapi import HTTPException, Header

JWT_SECRET = os.getenv("RCS_JWT_SECRET")
JWT_ALGORITHM = os.getenv("RCS_JWT_ALGORITHM", "HS256")

def verify_token(authorization: str = Header(None)) -> dict:
    if not JWT_SECRET:
        return {"sub": "demo-project", "role": "admin"}
    
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
