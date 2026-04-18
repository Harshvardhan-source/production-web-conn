"""
auth_service/main.py  —  FastAPI Authentication Microservice
=============================================================
Runs on port 8001 (separate from Django on 8000).
Handles: /auth/register  /auth/login  /auth/logout  /auth/me

Run:  uvicorn auth_service.main:app --port 8001 --reload
"""

from fastapi import FastAPI, HTTPException, Depends, Response, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from pydantic import BaseModel, EmailStr, field_validator
from pymongo import MongoClient
import bcrypt as _bcrypt
import certifi, jwt, re
from datetime import datetime, timedelta, timezone
from typing import Optional
import os
from dotenv import load_dotenv
load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

MONGO_URI   = os.getenv("MONGODB_URL")
DB_NAME     = "SurveyDataBase"
JWT_SECRET  = os.getenv("JWT_SECRET")
JWT_ALG     = "HS256"
TOKEN_EXP_H = 24

bearer = HTTPBearer(auto_error=False)

# ─── Persistent MongoDB client ────────────────────────────────────────────────

_mongo_client: MongoClient = None
_mongo_db                  = None


def get_db():
    # ── FIX 1: raise a clear 503 instead of crashing with NoneType error ─────
    if _mongo_db is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Database not connected. "
                "Check that MONGODB_URL is set in your .env file and "
                "that MongoDB Atlas is reachable from this machine."
            )
        )
    return _mongo_db


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Constituency Connect — Auth Service", version="1.0.0")


# ─── CORS ─────────────────────────────────────────────────────────────────────
# ── FIX 2: CORS must be added BEFORE any route definitions and must cover
#    BOTH localhost:3000 (CRA) and localhost:5173 (Vite).
#    The allow_origin_regex is the reliable fallback for any localhost port. ──

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://production-web-conn.onrender.com",
        "https://frontend-production-web.onrender.com"
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Regex catches ANY localhost port — so :3000, :5173, :4000 all work
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,   # REQUIRED for cookies / Authorization header
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# ─── Startup / Shutdown ───────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    global _mongo_client, _mongo_db

    # ── FIX 3: validate MONGO_URI before trying to connect ────────────────────
    if not MONGO_URI:
        print("[Auth] ✗ MONGO_URI / MONGODB_URL is not set in .env — DB will be unavailable")
        return

    if not JWT_SECRET or JWT_SECRET == "change-me-in-production":
        print("[Auth] ⚠  JWT_SECRET is missing or is the default value — set it in .env")

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
        # Force a real connection check (raises if unreachable)
        _mongo_client.server_info()
        _mongo_db = _mongo_client[DB_NAME]

        # Index so email lookups are fast
        _mongo_db["UserReg"].create_index("Email", unique=True, background=True)

        print(f"[Auth] ✓ MongoDB connected  →  {DB_NAME}")

    except Exception as exc:
        print(f"[Auth] ✗ MongoDB connection FAILED: {exc}")
        print("[Auth]   MONGO_URI seen by FastAPI:", MONGO_URI[:40] if MONGO_URI else "None")
        print("[Auth]   Fix: check MONGODB_URL in backend/.env")
        # _mongo_db stays None — get_db() will return HTTP 503 on every request


@app.on_event("shutdown")
def shutdown():
    if _mongo_client:
        _mongo_client.close()


# ─── JWT helpers ──────────────────────────────────────────────────────────────

def create_token(username: str, email: str) -> str:
    payload = {
        "sub":      email,
        "username": username,
        "exp":      datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXP_H),
        "iat":      datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


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
    return decode_token(token)


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

# ── Blocked email domains ─────────────────────────────────────────────────────
_BLOCKED_DOMAINS = {
    "test.com","example.com","mailinator.com","guerrillamail.com",
    "tempmail.com","throwaway.email","yopmail.com","trashmail.com",
    "dispostable.com","maildrop.cc","sharklasers.com","spam4.me",
    "fakeinbox.com","getairmail.com","mailnull.com","spamgourmet.com",
}
ROLES_ALL = {"mla", "pa", "corporator", "booth_worker"}


class RegisterBody(BaseModel):
    username: str
    email:    EmailStr
    password: str
    role:     str
    ward:     Optional[str] = ""
    booth:    Optional[str] = ""

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

    @field_validator("email")
    @classmethod
    def email_domain_ok(cls, v):
        domain = v.split("@")[-1].lower()
        if domain in _BLOCKED_DOMAINS:
            raise ValueError("Please use a real email address.")
        return v.lower()

    @field_validator("role")
    @classmethod
    def role_ok(cls, v):
        v = v.strip().lower()
        if v not in ROLES_ALL:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(sorted(ROLES_ALL))}")
        return v


class LoginBody(BaseModel):
    email:    EmailStr
    password: str


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/auth/health")
def health():
    """Quick check — confirms FastAPI is running and shows DB status."""
    return {
        "status":   "ok",
        "db":       "connected" if _mongo_db is not None else "disconnected",
        "db_name":  DB_NAME,
    }


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.post("/auth/register", status_code=201)
def register(body: RegisterBody, response: Response):
    db = get_db()

    if db["UserReg"].find_one({"Email": body.email}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="Email already registered.")

    # Validate required fields by role
    if body.role == "corporator" and not (body.ward or "").strip():
        raise HTTPException(status_code=422, detail="Ward is required for Corporator role.")
    if body.role == "booth_worker" and not (body.booth or "").strip():
        raise HTTPException(status_code=422, detail="Booth number is required for Booth Worker role.")

    hashed = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt(rounds=10)).decode()

    db["UserReg"].insert_one({
        "Time_stamp":  datetime.utcnow(),
        "Username":    body.username,
        "Email":       body.email,
        "Password":    hashed,
        "role":        body.role,
        "ward":        body.ward  or "",
        "booth":       body.booth or "",
        "status":      "pending",     # all new users need admin approval
        "requestedAt": datetime.utcnow(),
        "approvedAt":  None,
        "approvedBy":  None,
    })

    # Do NOT set a cookie or return a token — user must wait for approval
    return {
        "success":  True,
        "username": body.username,
        "email":    body.email,
        "role":     body.role,
        "status":   "pending",
        "message":  "Registration submitted. Pending admin approval.",
    }


@app.post("/auth/login")
def login(body: LoginBody, response: Response):
    db   = get_db()
    user = db["UserReg"].find_one({"Email": body.email})

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    stored = user["Password"]
    if stored.startswith("pbkdf2_") or stored.startswith("bcrypt_django"):
        from django.contrib.auth.hashers import check_password as django_check
        pwd_ok = django_check(body.password, stored)
    else:
        try:
            pwd_ok = _bcrypt.checkpw(body.password.encode(), stored.encode())
        except Exception:
            pwd_ok = (stored == body.password)

    if not pwd_ok:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # ── Check approval status ─────────────────────────────────────────────────
    status = user.get("status", "pending")
    if status == "pending":
        raise HTTPException(
            status_code=403,
            detail="Your account is pending admin approval. Please wait.",
        )
    if status == "rejected":
        raise HTTPException(
            status_code=403,
            detail="Your registration has been rejected. Please contact the admin.",
        )

    token = create_token(user["Username"], body.email)
    _set_cookie(response, token)
    return {
        "success":  True,
        "username": user["Username"],
        "email":    body.email,
        "role":     user.get("role",  "booth_worker"),
        "ward":     user.get("ward",  ""),
        "booth":    user.get("booth", ""),
        "status":   status,
        "token":    token,
    }


@app.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("cc_token", path="/")
    return {"success": True}


@app.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    db      = get_db()
    profile = db["UserReg"].find_one({"Email": user["sub"]}) or {}
    return {
        "success":  True,
        "username": user["username"],
        "email":    user["sub"],
        "role":     profile.get("role",   "booth_worker"),
        "ward":     profile.get("ward",   ""),
        "booth":    profile.get("booth",  ""),
        "status":   profile.get("status", "pending"),
    }


# ─── Cookie helper ────────────────────────────────────────────────────────────

def _set_cookie(response: Response, token: str):
    response.set_cookie(
        key="cc_token",
        value=token,
        httponly=True,
        secure=False,       # set True in production (HTTPS only)
        samesite="lax",
        max_age=TOKEN_EXP_H * 3600,
        path="/",
    )