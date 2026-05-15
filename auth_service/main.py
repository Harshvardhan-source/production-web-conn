"""
auth_service/main.py  —  FastAPI Authentication Microservice (hardened)
========================================================================
Runs on port 8001 (separate from Django on 8000).
Handles: /auth/register  /auth/login  /auth/logout  /auth/me

Security changes vs previous version
─────────────────────────────────────
  SEC-1  Rate limiting — slowapi, 5 req/min on login + register per IP
  SEC-2  JWT blocklist — jti claim + MongoDB ttl-index for true logout
  SEC-3  Hard startup failure when JWT_SECRET is missing or default
  SEC-4  Token no longer returned in JSON body (httponly cookie only)
  SEC-5  Plaintext password fallback removed; unknown hash = hard 401

Run:  uvicorn auth_service.main:app --port 8001 --reload

Extra dependency (add to requirements.txt):
    slowapi>=0.1.9
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
import certifi
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Response, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, field_validator
from pymongo import MongoClient, ASCENDING
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

load_dotenv()

logger = logging.getLogger("auth_service")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

# ─── Config ───────────────────────────────────────────────────────────────────

MONGO_URI   = os.getenv("MONGODB_URL")
DB_NAME     = "SurveyDataBase"
JWT_SECRET  = os.getenv("JWT_SECRET")
JWT_ALG     = "HS256"
TOKEN_EXP_M = 60           # access-token lifetime in minutes (was 24 h)
BLOCKLIST_C = "TokenBlocklist"   # collection name for revoked JTIs

bearer = HTTPBearer(auto_error=False)

# ─── SEC-1  Rate limiter ──────────────────────────────────────────────────────
# Key is the real client IP.  Override with X-Forwarded-For if behind a trusted
# proxy by setting the FORWARDED_ALLOW_IPS env-var understood by uvicorn.

limiter = Limiter(key_func=get_remote_address, default_limits=[])

# ─── Persistent MongoDB client ────────────────────────────────────────────────

_mongo_client: MongoClient | None = None
_mongo_db                         = None


def get_db():
    if _mongo_db is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Database not connected. "
                "Check that MONGODB_URL is set in your .env file and "
                "that MongoDB Atlas is reachable from this machine."
            ),
        )
    return _mongo_db


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Constituency Connect — Auth Service", version="2.0.0")

# Wire rate-limiter into FastAPI
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS ─────────────────────────────────────────────────────────────────────

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://production-web-conn-bzpt.onrender.com",
        "https://frontend-production-web-e44x.onrender.com",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# ─── Startup / Shutdown ───────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    global _mongo_client, _mongo_db

    # SEC-3 ── Hard failure when JWT_SECRET is absent or still the default ─────
    if not JWT_SECRET or JWT_SECRET == "change-me-in-production":
        raise RuntimeError(
            "[Auth] JWT_SECRET is not set or is the default placeholder. "
            "Set a strong random secret in .env before starting the service."
        )

    if not MONGO_URI:
        logger.error("[Auth] MONGODB_URL is not set — DB will be unavailable")
        return

    try:
        _mongo_client = MongoClient(
            MONGO_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=5000,
            maxPoolSize=20,
            minPoolSize=2,
            waitQueueTimeoutMS=3000,
        )
        _mongo_client.server_info()   # raises if unreachable
        _mongo_db = _mongo_client[DB_NAME]

        # Email uniqueness index
        _mongo_db["UserReg"].create_index("Email", unique=True, background=True)

        # SEC-2 ── TTL index: MongoDB auto-deletes expired JTIs ───────────────
        # The "exp" field stores a Python datetime; MongoDB removes the document
        # automatically once that moment passes (with ~60 s resolution).
        _mongo_db[BLOCKLIST_C].create_index(
            [("exp", ASCENDING)],
            expireAfterSeconds=0,
            background=True,
        )
        _mongo_db[BLOCKLIST_C].create_index("jti", unique=True, background=True)

        logger.info("[Auth] ✓ MongoDB connected  →  %s", DB_NAME)

    except Exception as exc:
        logger.error("[Auth] MongoDB connection FAILED: %s", exc)
        logger.error("[Auth] MONGO_URI prefix: %s", (MONGO_URI or "")[:40])
        # _mongo_db stays None — get_db() returns HTTP 503 on every request


@app.on_event("shutdown")
def shutdown():
    if _mongo_client:
        _mongo_client.close()


# ─── JWT helpers ──────────────────────────────────────────────────────────────

def create_token(username: str, email: str) -> str:
    """
    Issue a signed JWT.  Every token gets a unique `jti` so it can be
    individually revoked in the blocklist (SEC-2).
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub":      email,
        "username": username,
        "jti":      str(uuid.uuid4()),   # SEC-2: unique token ID
        "exp":      now + timedelta(minutes=TOKEN_EXP_M),
        "iat":      now,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


# SEC-2 ── Blocklist helpers ───────────────────────────────────────────────────

def _is_revoked(jti: str) -> bool:
    """Return True if this jti has been blocklisted (i.e. the user logged out)."""
    db = get_db()
    return db[BLOCKLIST_C].find_one({"jti": jti}, {"_id": 1}) is not None


def _revoke_token(payload: dict) -> None:
    """
    Add the token's jti to the blocklist.
    Store the expiry datetime so the TTL index can clean it up automatically.
    """
    db  = get_db()
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti:
        return
    # exp comes back from PyJWT as a datetime when decode_token is used
    exp_dt = exp if isinstance(exp, datetime) else datetime.fromtimestamp(exp, tz=timezone.utc)
    try:
        db[BLOCKLIST_C].insert_one({"jti": jti, "exp": exp_dt})
    except Exception:
        pass  # duplicate insert on double-click logout — ignore silently


def _token_from_request(
    request:     Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> str:
    token = request.cookies.get("cc_token")
    if not token and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return token


def get_current_user(token: str = Depends(_token_from_request)) -> dict:
    payload = decode_token(token)
    # SEC-2 ── Reject tokens that have been explicitly revoked ─────────────────
    if _is_revoked(payload.get("jti", "")):
        raise HTTPException(status_code=401, detail="Token has been revoked. Please log in again.")
    return payload


# ─── Password helpers ─────────────────────────────────────────────────────────

def _verify_password(plain: str, stored: str) -> bool:
    """
    Verify a plaintext password against a stored hash.

    Supports:
      • bcrypt hashes (default for all new accounts)
      • Django PBKDF2 hashes (migration path for legacy accounts)

    SEC-5 — The old plaintext-comparison fallback is intentionally removed.
    If the hash format is unrecognised, we raise 401 rather than silently
    comparing raw strings.
    """
    if stored.startswith("pbkdf2_") or stored.startswith("bcrypt_django"):
        try:
            from django.contrib.auth.hashers import check_password as django_check
            return django_check(plain, stored)
        except ImportError:
            logger.error("Django not installed but Django-format hash found for user — denying login.")
            return False

    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        try:
            return _bcrypt.checkpw(plain.encode(), stored.encode())
        except Exception as exc:
            logger.warning("bcrypt.checkpw raised unexpectedly: %s — denying login.", exc)
            return False

    # SEC-5 ── Unknown format: deny rather than fall back to plaintext ─────────
    logger.error("Unrecognised password hash format — denying login.")
    return False


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    username: str
    email:    EmailStr
    password: str
    role:     str = ""
    ward:     str = ""
    booth:    str = ""

    @field_validator("username")
    @classmethod
    def username_ok(cls, v):
        if not v.strip():
            raise ValueError("Username is required.")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8 or not re.search(r"[A-Za-z]", v) or not re.search(r"[0-9]", v):
            raise ValueError("Password must be 8+ chars with letters and numbers.")
        return v


class LoginBody(BaseModel):
    email:    EmailStr
    password: str


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/auth/health")
def health():
    """Quick check — confirms FastAPI is running and shows DB status."""
    return {
        "status":  "ok",
        "db":      "connected" if _mongo_db is not None else "disconnected",
        "db_name": DB_NAME,
    }


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.post("/auth/register", status_code=201)
@limiter.limit("5/minute")          # SEC-1: max 5 registrations per IP per minute
def register(request: Request, body: RegisterBody, response: Response):
    db = get_db()

    if db["UserReg"].find_one({"Email": body.email}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="Email already registered.")

    hashed = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt(rounds=12)).decode()

    db["UserReg"].insert_one({
        "Time_stamp": datetime.now(timezone.utc),
        "Username":   body.username,
        "Email":      body.email,
        "Password":   hashed,
        "status":     "pending",
        "role":       body.role,
        "ward":       body.ward,
        "booth":      body.booth,
    })

    token = create_token(body.username, body.email)
    _set_cookie(response, token)

    # SEC-4 ── Token NOT returned in body — httponly cookie is the only channel
    return {
        "success":  True,
        "username": body.username,
        "email":    body.email,
        "role":     body.role,
        "ward":     body.ward,
        "booth":    body.booth,
        "status":   "pending",
    }


@app.post("/auth/login")
@limiter.limit("5/minute")          # SEC-1: brute-force protection per IP
def login(request: Request, body: LoginBody, response: Response):
    db   = get_db()
    user = db["UserReg"].find_one({"Email": body.email})

    # Deliberate: same error for "no user" and "wrong password" (user enumeration prevention)
    if not user or not _verify_password(body.password, user.get("Password", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    acct_status = user.get("status", "approved")
    if acct_status == "pending":
        raise HTTPException(status_code=403, detail="Your account is pending admin approval.")
    if acct_status == "rejected":
        raise HTTPException(status_code=403, detail="Your registration was rejected. Contact the admin.")
    if acct_status == "disabled":
        raise HTTPException(status_code=403, detail="Your account has been disabled. Contact the office.")

    token = create_token(user["Username"], body.email)
    _set_cookie(response, token)

    # SEC-4 ── Token NOT returned in body
    return {
        "success":  True,
        "username": user["Username"],
        "email":    body.email,
        "role":     user.get("role",  ""),
        "ward":     user.get("ward",  ""),
        "booth":    user.get("booth", ""),
        "status":   acct_status,
    }


@app.post("/auth/logout")
def logout(
    request:  Request,
    response: Response,
    token:    str = Depends(_token_from_request),
):
    # SEC-2 ── Decode and revoke the token so it can't be reused ───────────────
    try:
        payload = decode_token(token)
        _revoke_token(payload)
    except HTTPException:
        pass   # already expired or invalid — still clear the cookie

    response.delete_cookie("cc_token", path="/", samesite="none", secure=True)
    return {"success": True}


@app.post("/auth/verify-admin")
@limiter.limit("5/minute")          # SEC-1: protect admin re-auth too
def verify_admin(request: Request, body: LoginBody):
    """
    Re-authentication gate for the Admin Panel.
    Verifies the currently logged-in admin's password without issuing a new token.
    Returns 200 on success, 401 on wrong password, 403 if not an admin role.
    """
    db   = get_db()
    user = db["UserReg"].find_one({"Email": body.email})

    if not user:
        raise HTTPException(status_code=401, detail="Incorrect password.")

    if user.get("role", "") not in ("mla", "pa"):
        raise HTTPException(status_code=403, detail="You do not have admin privileges.")

    if not _verify_password(body.password, user.get("Password", "")):
        raise HTTPException(status_code=401, detail="Incorrect password. Please try again.")

    return {"success": True, "message": "Verified."}


@app.get("/auth/me")
def me(response: Response, user: dict = Depends(get_current_user)):
    db      = get_db()
    profile = db["UserReg"].find_one({"Email": user["sub"]}) or {}

    # Rotate the token so the old jti is still valid (no revocation needed here).
    # If you want strict single-session semantics, revoke the old jti here too.
    fresh_token = create_token(user["username"], user["sub"])
    _set_cookie(response, fresh_token)

    # SEC-4 ── Token NOT returned in body
    return {
        "success":  True,
        "username": user["username"],
        "email":    user["sub"],
        "role":     profile.get("role",   ""),
        "ward":     profile.get("ward",   ""),
        "booth":    profile.get("booth",  ""),
        "status":   profile.get("status", "pending"),
    }


# ─── Cookie helper ────────────────────────────────────────────────────────────

def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="cc_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=TOKEN_EXP_M * 60,
        path="/",
    )