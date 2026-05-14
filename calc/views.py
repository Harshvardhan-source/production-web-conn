"""
views.py — All API endpoints return JSON for React frontend.
Django backend is purely an API server; React handles all UI.
"""
import time as _time
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.contrib.auth.hashers import make_password, check_password
from django.conf import settings

from pymongo import MongoClient
import certifi
import pandas as pd
import json
import re
import traceback
from datetime import datetime, timezone
import math
from bson import ObjectId
import ast
import jwt as pyjwt
import threading
import anthropic as _anthropic_mod

# ═══════════════════════════════════════════════════════════════════════════════
# WARD REFERENCE — SINGLE SOURCE OF TRUTH
# All ward/booth lookups in this file use these dicts.  Never duplicate locally.
# ═══════════════════════════════════════════════════════════════════════════════
WARD_FULL_DATA = {
    21: {"name": "PADAVU",              "booths": [31, 32, 33, 55, 56, 57, 58]},
    24: {"name": "DEREBAIL SOUTH",      "booths": [9, 11, 13, 17]},
    25: {"name": "DEREBAIL WEST",       "booths": [1, 2, 3, 5, 6, 7, 8]},
    26: {"name": "DEREBAIL SOUTH WEST", "booths": [4, 10, 89, 90, 91, 92, 94]},
    27: {"name": "BOLOOR",              "booths": [82, 83, 84, 88, 93, 95, 96, 97]},
    28: {"name": "MANNAGUDDA",          "booths": [12, 75, 78, 79, 80, 81, 85, 86, 87]},
    29: {"name": "KAMBLA",              "booths": [68, 69, 71, 72, 73]},
    30: {"name": "KODIALBAIL",          "booths": [14, 22, 24, 25, 26, 66, 67, 70]},
    31: {"name": "BEJAI",               "booths": [15, 16, 18, 19, 20, 21, 23]},
    32: {"name": "KADRI NORTH",         "booths": [27, 28, 29, 30, 63]},
    33: {"name": "KADRI SOUTH",         "booths": [59, 61, 62, 64, 65]},
    34: {"name": "SHIVBHAG",            "booths": [45, 60, 134, 135, 136, 139]},
    35: {"name": "PADAVU CENTRAL",      "booths": [34, 35, 39, 40, 43, 44]},
    36: {"name": "PADAVU POORVA",       "booths": [36, 37, 38, 41, 42]},
    37: {"name": "MAROLI",              "booths": [48, 49, 50, 51, 52, 53, 54]},
    38: {"name": "BENDUR",              "booths": [133, 138, 140, 166, 167, 171]},
    39: {"name": "FALNIR",              "booths": [162, 163, 164, 165, 172, 173, 174, 175]},
    40: {"name": "COURT",               "booths": [129, 130, 131, 132, 146, 147]},
    41: {"name": "CENTRAL",             "booths": [124, 125, 126, 127, 128]},
    42: {"name": "DONGERKERY",          "booths": [74, 76, 77, 112, 115, 117, 118]},
    43: {"name": "KUDROLI",             "booths": [108, 109, 110, 111, 113, 114]},
    44: {"name": "NAVAYATH",            "booths": [116, 119, 120, 121, 122, 123]},
    45: {"name": "PORT",                "booths": [148, 151, 152, 153, 238, 239]},
    46: {"name": "CANTONMENT",          "booths": [141, 145, 149, 150]},
    47: {"name": "MILAGRIS",            "booths": [142, 143, 144, 168, 169, 170]},
    48: {"name": "VALENCIA",            "booths": [137, 176, 177, 178, 187]},
    49: {"name": "KANKANADY",           "booths": [179, 180, 181, 182, 183, 184, 185, 186]},
    50: {"name": "ALAPE DAKSHINA",      "booths": [188, 189, 190, 191, 192, 213, 214, 215]},
    51: {"name": "ALAPE UTTARA",        "booths": [46, 47, 193, 194, 195, 196, 202]},
    52: {"name": "KANNUR",              "booths": [197, 198, 199, 200, 201, 203, 204, 205]},
    53: {"name": "BAJAL",               "booths": [206, 207, 208, 209, 210, 211, 212]},
    54: {"name": "JEPPINAMUGER",        "booths": [216, 217, 218, 219, 220, 221, 222, 223, 249]},
    55: {"name": "ATTAVARA",            "booths": [154, 155, 156, 157, 226, 227, 247, 248]},
    56: {"name": "MANGALADEVI",         "booths": [228, 229, 231, 232, 233]},
    57: {"name": "HOIGE BAZAR",         "booths": [235, 237, 240, 244]},
    58: {"name": "BOLAR",               "booths": [230, 234, 236, 241, 242, 243]},
    59: {"name": "JEPPU",               "booths": [158, 159, 160, 161, 224, 225, 245, 246]},
    60: {"name": "BENGRE",              "booths": [98, 99, 100, 101, 102, 103, 104, 105, 106, 107]},
}

# Derived lookups — computed once at import time, O(1) access everywhere
# ward_number (int/str) → name
WARD_NUM_TO_NAME = {str(k): v["name"] for k, v in WARD_FULL_DATA.items()}
WARD_NUM_TO_NAME.update({k: v["name"] for k, v in WARD_FULL_DATA.items()})  # int keys too

# booth (int/str) → ward_number (str)
BOOTH_TO_WARD = {}
for _wnum, _wdata in WARD_FULL_DATA.items():
    for _b in _wdata["booths"]:
        BOOTH_TO_WARD[str(_b)] = str(_wnum)
        BOOTH_TO_WARD[_b]      = str(_wnum)

# ward_name (upper) → list of booth ints
WARD_NAME_TO_BOOTHS = {v["name"].upper(): v["booths"] for v in WARD_FULL_DATA.values()}

# ── 2023 polled/notpolled collection uses SurveyOpt-style ward names ───────────
# Maps WARD_FULL_DATA name (UPPER) → ward name stored in 2023_polled_notpolled
_WARD_FULL_TO_CSV = {
    "PADAVU":              "PADAV-WEST",
    "PADAVU CENTRAL":      "PADAV CENTRAL",
    "PADAVU POORVA":       "PADAV-EAST",
    "DEREBAIL SOUTH WEST": "DEREBAIL NAIRUTHYA",
    "KAMBLA":              "KAMBALA",
    "SHIVBHAG":            "SHIVABAGH",
    "BENDUR":              "BENDOOR",
    "DONGERKERY":          "DONGARAKERY",
    "NAVAYATH":            "BUNDER",
    "CANTONMENT":          "CONTONMENT",
    "MILAGRIS":            "MILAGRESS",
    "JEPPINAMUGER":        "JAPPIMOGAR",
    "ATTAVARA":            "ATHAVARA",
    "ALAPE DAKSHINA":      "ALAPE SOUTH",
    "ALAPE UTTARA":        "ALAPE NORTH",
    "MANNAGUDDA":          "MANNAGDDA",
}

def _csv_ward_name(ward_full_name: str) -> str:
    """Convert WARD_FULL_DATA name → 2023_polled_notpolled Ward field value."""
    upper = ward_full_name.upper().strip()
    return _WARD_FULL_TO_CSV.get(upper, ward_full_name)  # unchanged if no alias


def _get_polled_hmc(db, match_filter: dict) -> dict:
    """
    Query 2023_polled_notpolled collection and return:
    {
      'H': {'polled': n, 'notPolled': n, 'total': n},
      'M': {...},
      'C': {...},
      'total': {'polled': n, 'notPolled': n, 'total': n},
    }
    match_filter: MongoDB $match dict (e.g. {'Ward': 'PADAV-WEST'} or {'Booth No': 44})
    """
    coll = db['2023_polled_notpolled']
    pipeline = [
        {'$match': match_filter},
        {'$group': {
            '_id': {
                'religion':      '$Religion',
                'polling_status': '$Polling status',
            },
            'n': {'$sum': 1}
        }},
    ]
    rows = list(coll.aggregate(pipeline))

    # Religion label → key
    rel_to_key = {'Hindu': 'H', 'Muslim': 'M', 'Christian': 'C'}

    result = {
        'H': {'polled': 0, 'notPolled': 0, 'total': 0},
        'M': {'polled': 0, 'notPolled': 0, 'total': 0},
        'C': {'polled': 0, 'notPolled': 0, 'total': 0},
        'total': {'polled': 0, 'notPolled': 0, 'total': 0},
    }
    for row in rows:
        rel  = row['_id'].get('religion', '')
        stat = row['_id'].get('polling_status', '')
        n    = row['n']
        key  = rel_to_key.get(rel)
        if not key:
            continue
        if stat == 'Polled':
            result[key]['polled'] += n
            result['total']['polled'] += n
        else:
            result[key]['notPolled'] += n
            result['total']['notPolled'] += n

    for k in ('H', 'M', 'C', 'total'):
        result[k]['total'] = result[k]['polled'] + result[k]['notPolled']

    return result
# ═══════════════════════════════════════════════════════════════════════════════

# ── Fuzzy name matching — handles transliteration variants like
#    Vishvanath/Vishwanath, Lakshmi/Laxmi, Srinivas/Sreenivas ─────────────────
try:
    from rapidfuzz import fuzz as _rfuzz, distance as _rfdist
    _RAPIDFUZZ_AVAILABLE = True
except ImportError:
    _RAPIDFUZZ_AVAILABLE = False

# ── 2002 voter list — loaded from local xlsx (backend/2002.xlsx) ──────────────
import os as _os

# Path to the xlsx file — placed in the Django project root (same folder as manage.py)
_XLSX_2002_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    '2002_new_.xlsx'
)

# Column mapping: xlsx header → MongoDB field name stored in SurveyDataBase.2002
# New xlsx columns (2002_new_.xlsx):
#   Serial No | House / Flat No | Voter Name | Relationship
#   Relative Name | Gender | Age | Voter ID / EPIC No
_COL_MAP_2002 = {
    'Serial No':          'Serial No',
    'House / Flat No':    'House / Flat No',   # stored as-is — matched in _flat_2002 / SIR
    'Voter Name':         'Voter Name',         # single English name column
    'Relationship':       'Relationship',
    'Relative Name':      'Relative Name',      # single relative name column
    'Gender':             'Gender',
    'Age':                'Age',
    'Voter ID / EPIC No': 'Voter ID / EPIC No', # stored as-is — matched in _find_voter_in_2002
}


# ─── MongoDB connection pool (module-level singletons) ───────────────────────
#
# MongoClient is thread-safe and manages its own connection pool internally.
# Creating it ONCE at import time means every request reuses warm TLS connections
# instead of doing a fresh 300-800ms Atlas handshake on each call.
#
# Cluster layout:
#   MONGODB_URL        — original cluster  → SurveyDataBase (voter rolls, SIR, 2002/2025)
#                                           → MainB          (CollDB, scheme data)
#   MONGODB_SURVEY_URL — NEW cluster       → SurveyDataBase  (SurveyRecords, FutureVoters, Deceased)

_SURVEY_URL = 'mongodb+srv://vickyhooda799_db_user:LgAvVKcZE7gM0ess@cluster0.kkin5ww.mongodb.net/'

# Lazy-initialised singletons — created on first use, reused forever after
_client_main   = None
_client_survey = None
_client_main1  = None

def _get_main_client():
    global _client_main
    if _client_main is None:
        _client_main = MongoClient(
            settings.MONGODB_URL, tls=True, tlsCAFile=certifi.where(),
            maxPoolSize=10, minPoolSize=2,
            serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
        )
    return _client_main

def _get_survey_client():
    global _client_survey
    if _client_survey is None:
        _client_survey = MongoClient(
            _SURVEY_URL, tls=True, tlsCAFile=certifi.where(),
            maxPoolSize=10, minPoolSize=2,
            serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
        )
    return _client_survey

def _get_main1_client():
    global _client_main1
    if _client_main1 is None:
        _client_main1 = MongoClient(
            settings.MONGODB_URL, tls=True, tlsCAFile=certifi.where(),
            maxPoolSize=5, minPoolSize=1,
            serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
        )
    return _client_main1

def get_db():
    """Original cluster — voter rolls, SIR, 2002/2025, WardReference (pooled)."""
    return _get_main_client().get_database('SurveyDataBase')

def get_survey_db():
    """New cluster — SurveyRecords, FutureVoters, Deceased (pooled)."""
    return _get_survey_client().get_database('SurveyDataBase')

def get_db1():
    """Original cluster — MainB / CollDB (pooled)."""
    return _get_main1_client().get_database('MainB')

JWT_SECRET = 'c0bcbb0e7afbdef8e53f9db603fb9140b1c793cd1e3e6379e3648281474e83f470b201b882b1864b09a0d3a9bb3716829563218e2813c4f89d35053a0141cd29'
JWT_ALG    = 'HS256'


def _user_from_request(request):
    """
    Extract JWT → get email → fetch full profile (role/status/ward/booth) from DB.
    Returns None if token is absent, invalid, or user not found.
    """
    token = request.COOKIES.get('cc_token')
    if not token:
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
    if not token:
        return None
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        email = payload.get('sub')
        if not email:
            return None
        return _get_user_profile(email)   # full profile with role/status/ward/booth
    except pyjwt.PyJWTError:
        return None



# ═══════════════════════════════════════════════════════════════════════════════
# RBAC — Role-Based Access Control
# ───────────────────────────────────────────────────────────────────────────────
# Roles:
#   mla          → SuperUser  (full read/write across all wards & booths)
#   pa           → SuperUser  (full read/write — Office P.A)
#   corporator   → Write own ward only; read all wards (read-only other wards)
#   booth_worker → Write own booth only; read all booths/wards
#
# Status lifecycle:  pending → approved | rejected
# ═══════════════════════════════════════════════════════════════════════════════

ROLES_SUPERUSER  = {'mla', 'pa'}
ROLES_ALL        = {'mla', 'pa', 'corporator', 'booth_worker'}

# Fake/test email domains to reject at registration
_BLOCKED_DOMAINS = {
    'test.com','example.com','mailinator.com','guerrillamail.com',
    'tempmail.com','throwaway.email','yopmail.com','trashmail.com',
    'dispostable.com','maildrop.cc','sharklasers.com','spam4.me',
    'fakeinbox.com','getairmail.com','mailnull.com','spamgourmet.com',
    'trashmail.net','tempinbox.com','tempinbox.co.uk',
}

_EMAIL_RE = re.compile(
    r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
)


def _validate_email(email: str) -> str | None:
    """
    Returns None if email is valid.
    Returns an error string if invalid.
    """
    if not email or len(email) > 254:
        return 'Invalid email address.'
    if not _EMAIL_RE.match(email):
        return 'Invalid email format.'
    domain = email.split('@')[-1].lower()
    if domain in _BLOCKED_DOMAINS:
        return 'Please use a real email address.'
    # Reject domains with no dot after the @ part
    if '.' not in domain:
        return 'Invalid email domain.'
    return None


# ── User profile cache (email → profile, 60s TTL) ───────────────────────────
_USER_PROFILE_CACHE: dict = {}
_UPC_TTL = 60   # seconds


def _get_user_profile(email: str) -> dict | None:
    """Fetch full user profile from UserReg. Cached for 60 s."""
    now = _time.time()
    cached = _USER_PROFILE_CACHE.get(email)
    if cached and (now - cached['ts']) < _UPC_TTL:
        return cached['data']
    user = get_db()['UserReg'].find_one({'Email': email})
    if not user:
        return None
    profile = {
        'username': user.get('Username', ''),
        'email':    email,
        'role':     user.get('role',   'booth_worker'),
        'status':   user.get('status', 'pending'),
        'ward':     str(user.get('ward',  '') or ''),
        'booth':    str(user.get('booth', '') or ''),
    }
    _USER_PROFILE_CACHE[email] = {'data': profile, 'ts': now}
    return profile


def _invalidate_user_cache(email: str):
    _USER_PROFILE_CACHE.pop(email, None)


# ── Access helpers ────────────────────────────────────────────────────────────

def _is_superuser(user: dict) -> bool:
    return bool(user) and user.get('role') in ROLES_SUPERUSER


def _is_approved(user: dict) -> bool:
    return bool(user) and user.get('status') == 'approved'


def _can_write_ward(user: dict, ward) -> bool:
    """True if the user may create/update survey records for this ward."""
    if not user or not _is_approved(user):
        return False
    if _is_superuser(user):
        return True
    role = user.get('role', '')
    if role == 'corporator':
        return str(user.get('ward', '')).upper() == str(ward).upper()
    # booth_worker has no ward-level write
    return False


def _can_write_booth(user: dict, booth) -> bool:
    """True if the user may create/update survey records for this booth."""
    if not user or not _is_approved(user):
        return False
    if _is_superuser(user):
        return True
    role = user.get('role', '')
    if role == 'corporator':
        # Corporator can write to any booth within their ward (ward checked separately)
        return True
    if role == 'booth_worker':
        return str(user.get('booth', '')) == str(booth)
    return False


def _require_approved(view_fn):
    """Decorator: reject unauthenticated or pending/rejected/disabled users."""
    def wrapper(request, *args, **kwargs):
        user = _user_from_request(request)
        if not user:
            return JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401)
        status = user.get('status', 'pending')
        if status == 'disabled':
            return JsonResponse({'success': False, 'message': 'Your account has been disabled. Contact the admin.'}, status=403)
        if not _is_approved(user):
            return JsonResponse({'success': False, 'message': 'Your account is pending admin approval.'}, status=403)
        return view_fn(request, *args, **kwargs)
    wrapper.__name__ = view_fn.__name__
    return wrapper


def _require_superuser(view_fn):
    """Decorator: only MLA / PA may call this endpoint."""
    def wrapper(request, *args, **kwargs):
        user = _user_from_request(request)
        if not user:
            return JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401)
        if not _is_approved(user):
            return JsonResponse({'success': False, 'message': 'Account pending approval.'}, status=403)
        if not _is_superuser(user):
            return JsonResponse({'success': False, 'message': 'Superuser access required.'}, status=403)
        return view_fn(request, *args, **kwargs)
    wrapper.__name__ = view_fn.__name__
    return wrapper



def bson_clean(doc, keep_id=False):
    """
    Recursively convert ObjectId and other non-serialisable types.
    Pass keep_id=True to retain _id as a string (needed for edit operations).
    """
    if isinstance(doc, dict):
        result = {}
        for k, v in doc.items():
            if k == '_id':
                if keep_id:
                    result['_id'] = str(v) if isinstance(v, ObjectId) else v
                # if keep_id=False, skip _id entirely (original behaviour)
            else:
                result[k] = bson_clean(v, keep_id=keep_id)
        return result
    if isinstance(doc, list):
        return [bson_clean(i, keep_id=keep_id) for i in doc]
    if isinstance(doc, ObjectId):
        return str(doc)
    return doc


# ─── CSRF ─────────────────────────────────────────────────────────────────────

@ensure_csrf_cookie
def get_csrf(request):
    """React calls this once on startup to get the CSRF cookie."""
    return JsonResponse({'detail': 'CSRF cookie set'})


# ─── AUTH ─────────────────────────────────────────────────────────────────────

# ── Deprecated: use FastAPI /auth/register instead ──────────────────────────
@csrf_exempt
@require_http_methods(['POST'])
def api_register(request):
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    username = body.get('username', '').strip()
    email    = body.get('email', '').strip().lower()
    password = body.get('password', '').strip()
    role     = body.get('role', '').strip().lower()
    ward     = body.get('ward',  '').strip()    # required for corporator
    booth    = body.get('booth', '').strip()    # required for booth_worker

    # ── Validation ────────────────────────────────────────────────────────────
    if not (username and email and password and role):
        return JsonResponse({'success': False, 'message': 'Username, email, password and role are required.'}, status=400)

    err = _validate_email(email)
    if err:
        return JsonResponse({'success': False, 'message': err}, status=400)

    if role not in ROLES_ALL:
        return JsonResponse({'success': False, 'message': f'Invalid role. Must be one of: {", ".join(sorted(ROLES_ALL))}'}, status=400)

    if role == 'corporator' and not ward:
        return JsonResponse({'success': False, 'message': 'Ward is required for Corporator role.'}, status=400)

    if role == 'booth_worker' and not booth:
        return JsonResponse({'success': False, 'message': 'Booth number is required for Booth Worker role.'}, status=400)

    if len(password) < 8 or not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
        return JsonResponse({'success': False, 'message': 'Password must be 8+ characters with letters and numbers.'}, status=400)

    db = get_db()
    if db['UserReg'].find_one({'Email': email}):
        return JsonResponse({'success': False, 'message': 'Email already registered.'}, status=400)

    db['UserReg'].insert_one({
        'Time_stamp':   datetime.utcnow(),
        'Username':     username,
        'Email':        email,
        'Password':     make_password(password),
        'role':         role,
        'ward':         ward,
        'booth':        booth,
        'status':       'pending',   # all new users require admin approval
        'requestedAt':  datetime.utcnow(),
        'approvedAt':   None,
        'approvedBy':   None,
    })

    return JsonResponse({
        'success': True,
        'message': 'Registration submitted. Your account is pending admin approval.',
        'username': username,
        'email':    email,
        'role':     role,
        'status':   'pending',
    })


# ── Deprecated: use FastAPI /auth/login instead ─────────────────────────────
@csrf_exempt
@require_http_methods(['POST'])
def api_login(request):
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    email    = body.get('email', '').strip()
    password = body.get('password', '').strip()

    if not (email and password):
        return JsonResponse({'success': False, 'message': 'All fields are required.'}, status=400)

    db   = get_db()
    user = db['UserReg'].find_one({'Email': email})

    if not user:
        return JsonResponse({'success': False, 'message': 'Invalid email or password.'}, status=401)

    # Support both hashed and plain passwords (legacy)
    pwd_ok = (check_password(password, user['Password'])
              if user['Password'].startswith('pbkdf2_') or user['Password'].startswith('bcrypt')
              else user['Password'] == password)

    if not pwd_ok:
        return JsonResponse({'success': False, 'message': 'Invalid email or password.'}, status=401)

    # ── Check account status ──────────────────────────────────────────────────
    status = user.get('status', 'pending')
    if status == 'pending':
        return JsonResponse({'success': False, 'message': 'Your account is pending admin approval. Please wait.'}, status=403)
    if status == 'rejected':
        return JsonResponse({'success': False, 'message': 'Your registration has been rejected. Contact the admin.'}, status=403)
    if status == 'disabled':
        return JsonResponse({'success': False, 'message': 'Your account has been disabled. Contact the admin.'}, status=403)

    request.session['username'] = user['Username']
    request.session['email']    = email

    # Fetch dashboard stats
    stats = _registration_analytics(db)
    return JsonResponse({
        'success':  True,
        'username': user['Username'],
        'email':    email,
        'role':     user.get('role',   'booth_worker'),
        'ward':     user.get('ward',   ''),
        'booth':    user.get('booth',  ''),
        'status':   status,
        **stats,
    })


# ── Deprecated: use FastAPI /auth/logout instead ────────────────────────────
@csrf_exempt
@require_http_methods(['POST'])
def api_logout(request):
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    username = body.get('username') or request.session.get('username')
    email    = body.get('email')    or request.session.get('email')

    if username and email:
        get_db()['UserReg'].delete_one({'Email': email, 'Username': username})

    request.session.flush()
    return JsonResponse({'success': True})


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

_dashboard_cache      = {}        # { 'data': {...}, 'ts': float }
DASHBOARD_CACHE_TTL   = 60        # seconds — tune up/down as needed
 
 
def _registration_analytics(db=None):
    """
    Return dashboard statistics dict using aggregation pipelines.
    Results are cached for DASHBOARD_CACHE_TTL seconds.
    """
    global _dashboard_cache
 
    # ── Cache hit ─────────────────────────────────────────────────────────────
    if _dashboard_cache.get('data') and (_time.time() - _dashboard_cache.get('ts', 0)) < DASHBOARD_CACHE_TTL:
        return _dashboard_cache['data']
 
    if db is None:
        db = get_db()

    # SurveyRecords lives on the new survey cluster; voter rolls stay on original cluster
    survey_db   = get_survey_db()
    coll_survey = survey_db['SurveyRecords']
    coll_voter  = db['2025']
    coll_ward   = db['WardReference']

    # Use module-level WARD_NUM_TO_NAME — no local copy needed
 
    # ── Single aggregation pipeline for SurveyRecords ────────────────────────
    # Replaces: count_documents x7 + find(wardNumber) — all in ONE round-trip
    survey_pipeline = [
        {
            '$facet': {
                # Total count
                'total': [{'$count': 'n'}],
 
                # Gender counts
                'genders': [
                    {'$group': {'_id': '$gender', 'n': {'$sum': 1}}}
                ],
 
                # Religion counts
                'religions': [
                    {'$group': {'_id': '$religion', 'n': {'$sum': 1}}}
                ],
 
                # Ward counts (for coverage %)
                'wards': [
                    {'$match': {'wardNumber': {'$exists': True, '$ne': None, '$ne': ''}}},
                    {'$group': {'_id': {'$toString': '$wardNumber'}, 'n': {'$sum': 1}}}
                ],
            }
        }
    ]
 
    # ── Single aggregation pipeline for VoterList ─────────────────────────────
    # Replaces: count_documents x4 + distinct('House No') — all in ONE round-trip
    voter_pipeline = [
        {
            '$facet': {
                'total': [{'$count': 'n'}],
 
                'genders': [
                    {'$group': {'_id': '$Gender', 'n': {'$sum': 1}}}
                ],
 
                'religions': [
                    {'$group': {'_id': '$Religion', 'n': {'$sum': 1}}}
                ],

                # HMC counts from Predicted_Religion_Label field
                'hmc': [
                    {'$match': {'Predicted_Religion_Label': {'$in': ['H', 'M', 'C']}}},
                    {'$group': {'_id': '$Predicted_Religion_Label', 'n': {'$sum': 1}}}
                ],
 
                # Unique house count — cheaper than distinct() on large collections
                'house_count': [
                    {'$match': {'House No': {'$exists': True, '$ne': None}}},
                    {'$group': {'_id': '$House No'}},
                    {'$count': 'n'},
                ],

                # Houses with more than 15 members (constituency-level)
                'large_families': [
                    {'$match': {'House No': {'$exists': True, '$ne': None}}},
                    {'$group': {'_id': '$House No', 'count': {'$sum': 1}}},
                    {'$match': {'count': {'$gt': 15}}},
                    {'$count': 'n'},
                ],
            }
        }
    ]
 
    # Run both pipelines (each is 1 round-trip)
    s_result = list(coll_survey.aggregate(survey_pipeline))[0]
    v_result = list(coll_voter.aggregate(voter_pipeline))[0]
 
    # ── Unpack survey results ─────────────────────────────────────────────────
    total_reg  = s_result['total'][0]['n']  if s_result['total']  else 0
 
    gender_map_s = {g['_id']: g['n'] for g in s_result['genders']}
    reg_male     = gender_map_s.get('Male',   0)
    reg_female   = gender_map_s.get('Female', 0)
 
    religions    = ['Hindu', 'Muslim', 'Christian', 'Jain', 'Buddhist', 'Sikh']
    rel_map_s    = {r['_id']: r['n'] for r in s_result['religions']}
    reg_religion = {r: rel_map_s.get(r, 0) for r in religions}
 
    ward_counts  = {w['_id']: w['n'] for w in s_result['wards']}
 
    # ── Unpack voter results ──────────────────────────────────────────────────
    total_voters  = v_result['total'][0]['n'] if v_result['total'] else 0
    unique_houses = v_result['house_count'][0]['n'] if v_result['house_count'] else 0
    large_family_count = v_result['large_families'][0]['n'] if v_result.get('large_families') else 0
 
    gender_map_v = {g['_id']: g['n'] for g in v_result['genders']}
    # 2025 collection stores Gender as full strings "Male" / "Female" (not 'M'/'F')
    voter_male   = gender_map_v.get('Male',   0)
    voter_female = gender_map_v.get('Female', 0)
    voter_trans  = gender_map_v.get('Other',  0) + gender_map_v.get('Trans', 0)
 
    religion_map   = {'H': 'Hindu', 'M': 'Muslim', 'C': 'Christian', 'J': 'Jain', 'B': 'Buddhist', 'S': 'Sikh'}
    rel_map_v      = {g['_id']: g['n'] for g in v_result['religions']}
    voter_religion = {name: rel_map_v.get(code, 0) for code, name in religion_map.items()}

    # HMC from Predicted_Religion_Label
    hmc_map = {g['_id']: g['n'] for g in v_result.get('hmc', [])}
    voter_hmc = {
        'H': hmc_map.get('H', 0),
        'M': hmc_map.get('M', 0),
        'C': hmc_map.get('C', 0),
        'total': sum(hmc_map.get(k, 0) for k in ('H', 'M', 'C')),
    }

    # ── Polled / NotPolled HMC from 2023_polled_notpolled (constituency = all) ─
    try:
        polled_hmc = _get_polled_hmc(survey_db, {})
    except Exception:
        polled_hmc = None
 
    # ── Ward coverage (uses WardReference + ward_counts from survey) ──────────
    ward_ref   = list(coll_ward.find({}, {'number': 1, 'totalCount': 1}))
    percentages = {}
    for ref in ward_ref:
        wn    = str(ref.get('number', ''))
        total = ref.get('totalCount', 0)
        count = ward_counts.get(wn, 0)
        if total and wn in WARD_NUM_TO_NAME:
            percentages[WARD_NUM_TO_NAME[wn]] = round(count / total * 100, 1)
 
    result = {
        'totalReg':        total_reg,
        'totalVoters':     total_voters,
        'houseCount':      unique_houses,
        'largeFamilyCount': large_family_count,
        'regMale':         reg_male,
        'regFemale':       reg_female,
        'voterMale':       voter_male,
        'voterFemale':     voter_female,
        'voterTrans':      voter_trans,
        'regReligion':     reg_religion,
        'voterReligion':   voter_religion,
        'voterHMC':        voter_hmc,
        'polledHMC':       polled_hmc,
        'wardCoverage':    percentages,
    }
 
    # ── Store in cache ────────────────────────────────────────────────────────
    _dashboard_cache = {'data': result, 'ts': _time.time()}
    return result
 
 
@require_http_methods(['GET'])
def api_dashboard(request):
    db    = get_db()
    stats = _registration_analytics(db)
    return JsonResponse({'success': True, **stats})


# ─── WARD DASHBOARD ───────────────────────────────────────────────────────────
# GET /api/ward-dashboard/?ward=<number>
# Reads WardReference collection directly — totalCount, totalMale, totalFemale,
# totalTrans, totalHindu, totalMuslim, totalChristian, districtId, constituencyId

_ward_dash_cache = {}   # { ward_str: {'data': {...}, 'ts': float} }
_WARD_CACHE_TTL  = 300  # 5 minutes

# ── SIR Preview Cache — MongoDB-backed (survives server restarts/sleep) ────────
# Falls back to an in-process dict when the DB is unreachable.
_SIR_PREVIEW_CACHE     = {}   # in-process fallback
_SIR_PREVIEW_CACHE_TTL = 300  # 5 minutes (raised from 2 min)

def _sir_cache_get(key_tuple):
    """Try MongoDB first, fall back to in-process dict."""
    import time as _t
    cache_id = str(key_tuple)
    # 1. In-process dict (fastest)
    hit = _SIR_PREVIEW_CACHE.get(key_tuple)
    if hit and (_t.time() - hit['ts']) < _SIR_PREVIEW_CACHE_TTL:
        return hit['data']
    # 2. MongoDB persistent cache
    try:
        db = get_survey_db()
        doc = db['SIRPreviewCache'].find_one({'_id': cache_id})
        if doc and (_t.time() - doc.get('ts', 0)) < _SIR_PREVIEW_CACHE_TTL:
            data = doc.get('data')
            # Warm the in-process dict too
            _SIR_PREVIEW_CACHE[key_tuple] = {'data': data, 'ts': doc['ts']}
            return data
    except Exception:
        pass
    return None

def _sir_cache_set(key_tuple, data):
    """Write to both in-process dict and MongoDB."""
    import time as _t
    now = _t.time()
    cache_id = str(key_tuple)
    # In-process
    _SIR_PREVIEW_CACHE[key_tuple] = {'data': data, 'ts': now}
    # Evict oldest entries if in-process dict grows too large
    if len(_SIR_PREVIEW_CACHE) > 500:
        for k in sorted(_SIR_PREVIEW_CACHE, key=lambda k: _SIR_PREVIEW_CACHE[k]['ts'])[:100]:
            _SIR_PREVIEW_CACHE.pop(k, None)
    # MongoDB persistent write (fire-and-forget — never block the response)
    def _write():
        try:
            get_survey_db()['SIRPreviewCache'].replace_one(
                {'_id': cache_id},
                {'_id': cache_id, 'data': data, 'ts': now},
                upsert=True,
            )
        except Exception:
            pass
    threading.Thread(target=_write, daemon=True).start()


@require_http_methods(['GET'])
def api_ward_dashboard(request):
    import time as _t
    ward = request.GET.get('ward', '').strip()
    if not ward:
        return JsonResponse({'success': False, 'message': 'ward parameter required'}, status=400)

    # Cache hit (skip if ?nocache=1 passed for debugging)
    no_cache = request.GET.get('nocache', '0') == '1'
    cached = _ward_dash_cache.get(ward)
    if not no_cache and cached and (_t.time() - cached['ts']) < _WARD_CACHE_TTL:
        return JsonResponse({'success': True, **cached['data']})

    try:
        db       = get_db()
        ward_int = int(ward) if ward.isdigit() else None

        # ── 1. WardReference — primary source of voter demographic totals ────
        ref = db['WardReference'].find_one(
            {'number': ward_int} if ward_int is not None else {'number': ward}
        ) or {}

        # Use module-level WARD_NUM_TO_NAME — no local copy needed
        ward_name    = ref.get('name') or WARD_NUM_TO_NAME.get(ward, WARD_NUM_TO_NAME.get(str(ward), f'Ward {ward}'))
        district_id  = ref.get('districtId')
        const_id     = ref.get('constituencyId')
        total_voters = ref.get('totalCount',    0) or 0
        total_male   = ref.get('totalMale',     0) or 0
        total_female = ref.get('totalFemale',   0) or 0
        total_trans  = ref.get('totalTrans',    0) or 0
        total_hindu  = ref.get('totalHindu',    0) or 0
        total_muslim = ref.get('totalMuslim',   0) or 0
        total_chr    = ref.get('totalChristian',0) or 0

        def _num(v):
            if v is None: return 0
            try: return int(str(v).replace(',','').strip())
            except: return 0

        def _flt(v):
            if v is None: return 0.0
            try: return round(float(str(v).replace('%','').replace(',','').strip()), 2)
            except: return 0.0

        # 2026 mapping stats stored directly in WardReference (after data update)
        ward_ref_2026 = {
            'boothList':      (ref.get('boothList') or '').strip(),
            'boothCount':     _num(ref.get('boothCount')),
            'totalElectors':  _num(ref.get('totalCount')),
            'cutoffElec':     _num(ref.get('cutoffElec')),
            'bloMapped':      _num(ref.get('bloMapped')),
            'totalMapped':    _num(ref.get('totalMapped')),
            'pctBloMapped':   _flt(ref.get('pctBloMapped')),
            'ageCutoff':      _num(ref.get('ageCutoff')),
            'progeny18':      _num(ref.get('progeny18')),
            'pctProgeny':     _flt(ref.get('pctProgeny')),
            'electorsMapped': _num(ref.get('electorsMapped')),
            'pctTotal':       _flt(ref.get('pctTotal')),
        }

        # ── 2. SurveyRecords — how many surveyed for this ward ────────────────
        survey_db    = get_survey_db()
        ward_filters = [{'wardNumber': ward}]
        if ward_int is not None:
            ward_filters.append({'wardNumber': ward_int})

        pipeline = [
            {'$match': {'$or': ward_filters}},
            {'$facet': {
                'total':     [{'$count': 'n'}],
                'genders':   [{'$group': {'_id': '$gender',   'n': {'$sum': 1}}}],
                'religions': [{'$group': {'_id': '$religion', 'n': {'$sum': 1}}}],
                'houses':    [
                    {'$match': {'houseNumber': {'$exists': True, '$ne': None, '$ne': ''}}},
                    {'$group': {'_id': '$houseNumber'}},
                    {'$count': 'n'},
                ],
            }}
        ]
        s_res       = list(survey_db['SurveyRecords'].aggregate(pipeline))[0]
        total_reg   = s_res['total'][0]['n']  if s_res['total']  else 0
        house_count = s_res['houses'][0]['n'] if s_res['houses'] else 0

        gmap        = {g['_id']: g['n'] for g in s_res['genders']}
        reg_male    = gmap.get('Male',   0)
        reg_female  = gmap.get('Female', 0)

        religions   = ['Hindu', 'Muslim', 'Christian', 'Jain', 'Buddhist', 'Sikh']
        rmap        = {r['_id']: r['n'] for r in s_res['religions']}
        reg_religion= {r: rmap.get(r, 0) for r in religions}

        # ── 3. Large families + HMC from 2025 voter list ────────────────────
        # Use module-level WARD_NAME_TO_BOOTHS — no local copy needed
        ward_name_upper  = ward_name.upper().strip()
        ward_booths_list = WARD_NAME_TO_BOOTHS.get(ward_name_upper, [])

        # Include BOTH string and integer forms of each booth number.
        # Part No in the 2025 collection may be stored as int or str — $in is type-strict.
        booth_strs = [str(b) for b in ward_booths_list]
        booth_ints = list(ward_booths_list)   # already ints from WARD_FULL_DATA

        large_family_count = 0
        ward_hmc = {'H': 0, 'M': 0, 'C': 0, 'total': 0}
        if ward_booths_list:
            booth_match = {'Part No': {'$in': booth_strs + booth_ints}}  # str + int forms
            lf_pipeline = [
                {'$match': booth_match},
                {'$facet': {
                    'large_families': [
                        {'$match': {'House No': {'$exists': True, '$ne': None}}},
                        {'$group': {'_id': '$House No', 'count': {'$sum': 1}}},
                        {'$match': {'count': {'$gt': 15}}},
                        {'$count': 'n'},
                    ],
                    'hmc': [
                        {'$match': {'Predicted_Religion_Label': {'$in': ['H', 'M', 'C']}}},
                        {'$group': {'_id': '$Predicted_Religion_Label', 'n': {'$sum': 1}}},
                    ],
                }}
            ]
            lf_result = list(db['2025'].aggregate(lf_pipeline))
            if lf_result:
                r = lf_result[0]
                large_family_count = r['large_families'][0]['n'] if r.get('large_families') else 0
                hmc_map = {g['_id']: g['n'] for g in r.get('hmc', [])}
                ward_hmc = {
                    'H': hmc_map.get('H', 0),
                    'M': hmc_map.get('M', 0),
                    'C': hmc_map.get('C', 0),
                    'total': sum(hmc_map.get(k, 0) for k in ('H', 'M', 'C')),
                }

        # ── 4. Polled/NotPolled HMC from 2023_polled_notpolled for this ward ───
        # FIX 1: 2023_polled_notpolled is on SURVEY cluster (get_survey_db), not main db.
        #         Constituency-level already uses survey_db correctly — ward level must too.
        # FIX 2: Query by Booth No (from WARD_FULL_DATA) instead of old ward name string,
        #         which fails because 2023 collection uses legacy ward names.
        #         Both int + str forms passed because MongoDB $in is type-strict.
        _survey_db_ward = get_survey_db()
        ward_num_key = ward_int if ward_int is not None else (int(ward) if str(ward).isdigit() else None)
        ward_booths_for_polled = WARD_FULL_DATA.get(ward_num_key, {}).get("booths", [])
        try:
            if ward_booths_for_polled:
                booth_vals_polled = list(ward_booths_for_polled) + [str(b) for b in ward_booths_for_polled]
                ward_polled_hmc = _get_polled_hmc(_survey_db_ward, {"Booth No": {"$in": booth_vals_polled}})
            else:
                csv_ward = _csv_ward_name(ward_name)
                ward_polled_hmc = _get_polled_hmc(_survey_db_ward, {"Ward": csv_ward})
        except Exception:
            ward_polled_hmc = None

        # ── 5. Coverage ───────────────────────────────────────────────────────
        denom        = total_voters or 1
        coverage_pct = round(total_reg / denom * 100, 1)

        result = {
            'wardName':         ward_name,
            'wardNumber':       ward,
            'districtId':       district_id,
            'constituencyId':   const_id,
            'totalVoters':      total_voters,
            'totalMale':        total_male,
            'totalFemale':      total_female,
            'totalTrans':       total_trans,
            'totalHindu':       total_hindu,
            'totalMuslim':      total_muslim,
            'totalChristian':   total_chr,
            'voterReligion': {
                'Hindu':     total_hindu,
                'Muslim':    total_muslim,
                'Christian': total_chr,
            },
            'voterHMC':         ward_hmc,
            'polledHMC':        ward_polled_hmc,
            'totalReg':         total_reg,
            'regMale':          reg_male,
            'regFemale':        reg_female,
            'regReligion':      reg_religion,
            'houseCount':       house_count,
            'largeFamilyCount': large_family_count,
            'wardCoverage':     {ward_name: coverage_pct},
            'coveragePct':      coverage_pct,
            'ward2026':         ward_ref_2026,
        }

        _ward_dash_cache[ward] = {'data': result, 'ts': _t.time()}
        return JsonResponse({'success': True, **result})

    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': str(exc)}, status=500)




# ─── BOOTH DASHBOARD ──────────────────────────────────────────────────────────
# GET /api/booth-dashboard/?ward=21&booth=31
# WardBoothWise_2026  → ORIGINAL cluster, SurveyDataBase  (get_db())
# SurveyRecords       → SURVEY cluster,   SurveyDataBase  (get_survey_db())

_booth_dash_cache = {}
_BOOTH_CACHE_TTL  = 300   # 5 minutes

@require_http_methods(['GET'])
def api_booth_dashboard(request):
    import time as _t
    ward  = request.GET.get('ward',  '').strip()
    booth = request.GET.get('booth', '').strip()
    if not ward or not booth:
        return JsonResponse({'success': False, 'message': 'ward and booth parameters required'}, status=400)

    cache_key = f'{ward}_{booth}'
    cached = _booth_dash_cache.get(cache_key)
    if cached and (_t.time() - cached['ts']) < _BOOTH_CACHE_TTL:
        return JsonResponse({'success': True, **cached['data']})

    try:
        # WardBoothWise_2026 is in SurveyDataBase on the ORIGINAL cluster
        main_db   = get_db()           # _get_main_client() → SurveyDataBase
        survey_db = get_survey_db()    # _get_survey_client() → SurveyDataBase
        ward_int  = int(ward)  if ward.isdigit()  else None
        booth_int = int(booth) if booth.isdigit() else None

        # ── 1. WardBoothWise_2026 — booth electors data ───────────────────────
        filt = {}
        if ward_int is not None and booth_int is not None:
            filt = {'$or': [
                {'wardNumber': ward_int,  'boothNumber': booth_int},
                {'wardNumber': str(ward), 'boothNumber': str(booth)},
                {'wardNumber': ward_int,  'boothNumber': str(booth_int)},
            ]}
        booth_doc = main_db['WardBoothWise_2026'].find_one(filt) or {}

        # Fallback: full-collection scan handles any type mismatch
        if not booth_doc:
            for _d in main_db['WardBoothWise_2026'].find():
                if (str(_d.get('wardNumber', '')).strip() == str(ward_int or ward) and
                        str(_d.get('boothNumber', '')).strip() == str(booth_int or booth)):
                    booth_doc = _d
                    break

        def _num(v):
            if v is None: return 0
            try: return int(str(v).replace(',', '').strip())
            except: return 0

        def _flt(v):
            if v is None: return 0.0
            try: return round(float(str(v).replace('%', '').replace(',', '').strip()), 2)
            except: return 0.0

        ward_name = (booth_doc.get('wardName') or '').strip() or WARD_NUM_TO_NAME.get(ward, f'Ward {ward}')

        # ── 2. SurveyRecords — surveyed count for this booth ──────────────────
        booth_filters = [{'boothNo': booth}]
        if booth_int is not None:
            booth_filters.append({'boothNo': booth_int})

        pipeline = [
            {'$match': {'$or': booth_filters}},
            {'$facet': {
                'total':   [{'$count': 'n'}],
                'genders': [{'$group': {'_id': '$gender', 'n': {'$sum': 1}}}],
                'houses':  [
                    {'$match': {'houseNumber': {'$exists': True, '$ne': None, '$ne': ''}}},
                    {'$group': {'_id': '$houseNumber'}},
                    {'$count': 'n'},
                ],
            }}
        ]
        s_res       = list(survey_db['SurveyRecords'].aggregate(pipeline))[0]
        total_reg   = s_res['total'][0]['n']  if s_res['total']  else 0
        house_count = s_res['houses'][0]['n'] if s_res['houses'] else 0
        gmap        = {g['_id']: g['n'] for g in s_res['genders']}

        # ── 3. HMC from 2025 voter list for this booth ────────────────────────
        # IMPORTANT: Part No may be stored as int OR string in MongoDB.
        # $in does strict type matching, so we include BOTH forms to guarantee a hit.
        booth_vals = list({booth, str(booth_int)} if booth_int is not None else {booth})
        if booth_int is not None:
            booth_vals.append(booth_int)   # ← integer form — critical for collections
                                           #   where Part No is stored as int (e.g. 31, not "31")
        booth_voter_pipeline = [
            {'$match': {'Part No': {'$in': booth_vals}}},
            {'$facet': {
                'hmc': [
                    {'$match': {'Predicted_Religion_Label': {'$in': ['H', 'M', 'C']}}},
                    {'$group': {'_id': '$Predicted_Religion_Label', 'n': {'$sum': 1}}},
                ],
                # 2025 stores Gender as full strings: "Male" / "Female"
                'genders': [
                    {'$group': {'_id': '$Gender', 'n': {'$sum': 1}}},
                ],
                'total': [{'$count': 'n'}],
            }}
        ]
        bv_result   = list(main_db['2025'].aggregate(booth_voter_pipeline))
        bv_facet    = bv_result[0] if bv_result else {}

        hmc_map     = {g['_id']: g['n'] for g in bv_facet.get('hmc', [])}
        booth_hmc   = {
            'H': hmc_map.get('H', 0),
            'M': hmc_map.get('M', 0),
            'C': hmc_map.get('C', 0),
            'total': sum(hmc_map.get(k, 0) for k in ('H', 'M', 'C')),
        }

        bgmap              = {g['_id']: g['n'] for g in bv_facet.get('genders', [])}
        booth_voter_male   = bgmap.get('Male',   0)
        booth_voter_female = bgmap.get('Female', 0)
        booth_voter_trans  = bgmap.get('Other',  0) + bgmap.get('Trans', 0)
        booth_total_voters = bv_facet['total'][0]['n'] if bv_facet.get('total') else 0

        total_electors = _num(booth_doc.get('totalElectors'))
        coverage_pct   = round(total_reg / (total_electors or 1) * 100, 1)

        # ── 4. Polled/NotPolled HMC from 2023_polled_notpolled for this booth ──
        # FIX: 2023_polled_notpolled is on the SURVEY cluster, not main db.
        # Include both int + str forms of Booth No — MongoDB $in is type-strict.
        _survey_db_booth = get_survey_db()
        booth_num_int = booth_int or (int(booth) if booth.isdigit() else None)
        try:
            if booth_num_int is not None:
                booth_polled_hmc = _get_polled_hmc(_survey_db_booth, {'Booth No': {'$in': [booth_num_int, str(booth_num_int)]}})
            else:
                booth_polled_hmc = _get_polled_hmc(_survey_db_booth, {'Booth No': {'$in': [booth, str(booth)]}})
        except Exception:
            booth_polled_hmc = None

        result = {
            'wardNumber':        ward,
            'wardName':          ward_name,
            'boothNumber':       booth_int or booth,
            # 2026 electors — from WardBoothWise_2026
            'totalElectors':     total_electors,
            'cutoffElec':        _num(booth_doc.get('cutoffElec')),
            'bloMapped':         _num(booth_doc.get('bloMapped')),
            'totalMapped':       _num(booth_doc.get('totalMapped')),
            'pctBloMapped':      _flt(booth_doc.get('pctBloMapped')),
            'ageCutoff':         _num(booth_doc.get('ageCutoff')),
            'progeny18':         _num(booth_doc.get('progeny18')),
            'pctProgeny':        _flt(booth_doc.get('pctProgeny')),
            'electorsMapped':    _num(booth_doc.get('electorsMapped')),
            'pctElectorsMapped': _flt(booth_doc.get('pctElectorsMapped')),
            'pctTotalCompleted': _flt(booth_doc.get('pctTotalCompleted')),
            # Voter demographics from 2025 roll (booth level)
            'totalVoters':       booth_total_voters,
            'totalMale':         booth_voter_male,
            'totalFemale':       booth_voter_female,
            'totalTrans':        booth_voter_trans,
            # Survey coverage — from SurveyRecords
            'totalReg':          total_reg,
            'regMale':           gmap.get('Male',   0),
            'regFemale':         gmap.get('Female', 0),
            'houseCount':        house_count,
            'coveragePct':       coverage_pct,
            # HMC religion counts from 2025 voter list
            'boothHMC':          booth_hmc,
            # Polled/NotPolled HMC from 2023 election data
            'polledHMC':         booth_polled_hmc,
        }

        _booth_dash_cache[cache_key] = {'data': result, 'ts': _t.time()}
        return JsonResponse({'success': True, **result})

    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': str(exc)}, status=500)


_large_families_cache = {}   # { 'data': [...], 'ts': float }
_LF_CACHE_TTL = 300           # 5 minutes
 
@require_http_methods(['GET'])
def api_large_families(request):
    """
    GET /api/large-families/
    Returns every house with >15 members, grouped by ward.
 
    Response shape:
    {
      "success": true,
      "total": 42,
      "byWard": [
        {
          "wardNumber": "27",
          "wardName": "Boloor",
          "count": 5,
          "houses": [
            { "houseNo": "12A", "memberCount": 18, "booth": "79" },
            ...
          ]
        },
        ...
      ]
    }
    """
    import time as _t
    global _large_families_cache
 
    # ── Cache hit ─────────────────────────────────────────────────────────────
    cached = _large_families_cache.get('data')
    if cached and (_t.time() - _large_families_cache.get('ts', 0)) < _LF_CACHE_TTL:
        return JsonResponse({'success': True, 'total': _large_families_cache['total'], 'byWard': cached})
 
    try:
        db = get_db()
 
        # Use module-level WARD_NUM_TO_NAME and BOOTH_TO_WARD — no local copies needed
 
        # Single aggregation: group by house, keep booth, filter >15 members
        pipeline = [
            {'$match': {'House No': {'$exists': True, '$ne': None, '$ne': ''}}},
            {'$group': {
                '_id': '$House No',
                'count': {'$sum': 1},
                # Grab one Part No per house to determine ward
                'booth': {'$first': '$Part No'},
            }},
            {'$match': {'count': {'$gt': 15}}},
            {'$sort': {'count': -1}},
        ]
 
        raw = list(db['2025'].aggregate(pipeline))
 
        # Group results by ward
        ward_map = {}   # ward_number → { wardName, houses: [] }
        for doc in raw:
            booth = str(doc.get('booth', '') or '')
            ward_no = BOOTH_TO_WARD.get(booth, 'Unknown')
            if ward_no not in ward_map:
                ward_map[ward_no] = {
                    'wardNumber': ward_no,
                    'wardName': WARD_NUM_TO_NAME.get(ward_no, f'Ward {ward_no}'),
                    'houses': [],
                }
            ward_map[ward_no]['houses'].append({
                'houseNo': doc['_id'],
                'memberCount': doc['count'],
                'booth': booth,
            })
 
        by_ward = sorted(
            [{'wardNumber': v['wardNumber'], 'wardName': v['wardName'],
              'count': len(v['houses']), 'houses': v['houses']}
             for v in ward_map.values()],
            key=lambda x: -x['count']
        )
 
        total = sum(w['count'] for w in by_ward)
        _large_families_cache['data'] = by_ward
        _large_families_cache['total'] = total
        _large_families_cache['ts'] = _t.time()
 
        return JsonResponse({'success': True, 'total': total, 'byWard': by_ward})
 
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': str(exc)}, status=500)
 

# ─── SURVEY ───────────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_serial_number(request):
    """
    Returns the next survey serial OR the 2025 voter-roll serial for a specific voter.

    GET /api/serial-number/              → next auto-increment (for SurveyOpt display)
    GET /api/serial-number/?voterid=XYZ  → Serial No from SurveyDataBase.2025 for that voter
                                           Falls back to auto-increment if voter not found.
    """
    voterid = request.GET.get('voterid', '').strip().upper()

    if voterid:
        # Try to find the voter in the 2025 roll and return their Serial No
        voter_2025 = get_db()['2025'].find_one(
            {'Epic NO': voterid},
            {'Serial No': 1, 'Sl No': 1}
        )
        if voter_2025:
            serial = voter_2025.get('Serial No') or voter_2025.get('Sl No')
            if serial:
                try:
                    return JsonResponse({'serialNumber': int(serial), 'source': '2025_roll'})
                except (ValueError, TypeError):
                    pass   # fall through to auto-increment

    # Next serial = total count + 1  (gap-proof: max+1 breaks if any record is deleted)
    db     = get_survey_db()
    count  = db['SurveyRecords'].count_documents({})
    serial = count + 1
    return JsonResponse({'serialNumber': serial, 'source': 'auto'})


@csrf_exempt
@require_http_methods(['POST'])
def api_save_survey(request):
    # ── RBAC gate ─────────────────────────────────────────────────────────────
    _user = _user_from_request(request)
    if not _user:
        return JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401)
    if not _is_approved(_user):
        return JsonResponse({'success': False, 'message': 'Account pending approval.'}, status=403)

    # ── Parse body — supports JSON, multipart, and url-encoded ──────────────
    aadhaar_photo_file = None
    sir_form_photo_file = None
    ct = (request.content_type or '').lower()

    if 'multipart' in ct:
        # Aadhaar photo path: form data is JSON-stringified under the 'data' key
        raw_data = request.POST.get('data', '')
        print(f"[api_save_survey] MULTIPART: data_len={len(raw_data)}, FILES={list(request.FILES.keys())}")
        try:
            body = json.loads(raw_data) if raw_data else {}
        except Exception as _me:
            print(f"[api_save_survey] multipart JSON parse error: {_me}")
            body = {k: v for k, v in request.POST.items()}
        aadhaar_photo_file = request.FILES.get('aadhaar_photo')
        sir_form_photo_file = request.FILES.get('sir_form_photo')

    else:
        # JSON / url-encoded path
        raw_body = request.body
        print(f"[api_save_survey] JSON path: ct={ct!r} len={len(raw_body)}")
        print(f"[api_save_survey] RAW BODY (first 500): {raw_body[:500]!r}")
        try:
            body = json.loads(raw_body)
        except Exception as _e:
            print(f"[api_save_survey] JSON parse failed: {_e}")
            body = {k: v for k, v in request.POST.items()}
            if not body:
                print("[api_save_survey] WARN: body EMPTY after all parse attempts")

    # ── Verbose debug — print ALL received values ─────────────────────────────
    print(f"[api_save_survey] PARSED {len(body)} keys: {list(body.keys())}")
    print(f"[api_save_survey] firstName={body.get('firstName')!r} "
          f"lastName={body.get('lastName')!r} "
          f"dob={body.get('dob')!r} "
          f"gender={body.get('gender')!r} "
          f"voterid={body.get('voterid')!r} "
          f"ward={body.get('wardNumber')!r} "
          f"booth={body.get('boothNo')!r} "
          f"house={body.get('houseNumber')!r} "
          f"religion={body.get('religion')!r} "
          f"schemes={len(body.get('schemes') or [])}")

    # Ward / booth write check (after body is parsed so we have ward/booth)
    _ward_body  = body.get('wardNumber', '')
    _booth_body = body.get('boothNo',    '')
    if not _is_superuser(_user):
        if _user.get('role') == 'corporator':
            if not _can_write_ward(_user, _ward_body):
                return JsonResponse({'success': False, 'message': f'You can only submit surveys for your assigned ward ({_user["ward"]}).'}, status=403)
        elif _user.get('role') == 'booth_worker':
            if not _can_write_booth(_user, _booth_body):
                return JsonResponse({'success': False, 'message': f'You can only submit surveys for your assigned booth ({_user["booth"]}).'}, status=403)

    # ── Helper: return value as-is; use default only when key is truly absent ──
    # Empty strings are stored as None so MongoDB shows null rather than ""
    def _val(k, default=None):
        v = body.get(k)
        if v is None:
            return default
        if isinstance(v, str) and v.strip() == '':
            return default
        return v

    # ── DOB → computed age; fall back to manually typed age ──────────────────
    dob_str = _val('dob')
    age = None
    if dob_str:
        try:
            dob_dt = datetime.strptime(dob_str, '%Y-%m-%d')
            today  = datetime.today()
            age    = today.year - dob_dt.year - ((today.month, today.day) < (dob_dt.month, dob_dt.day))
        except ValueError:
            dob_str = None   # bad format — store None, don't abort the whole save
    if age is None:
        try:
            age = int(body['age']) if body.get('age') not in (None, '') else None
        except (TypeError, ValueError):
            age = None

    is_outstation = body.get('outstationResident') == 'Yes'

    # ── 1. Extract voterid ────────────────────────────────────────────────────
    voterid = (body.get('voterid') or '').strip().upper()

    # ── 2. Assign sequential serial = current count + 1 (gap-proof) ──────────
    survey_db_for_serial = get_survey_db()
    survey_count   = survey_db_for_serial['SurveyRecords'].count_documents({})
    final_serial   = survey_count + 1

    data = {
        # ── Personal ──────────────────────────────────────────────
        'firstName':        _val('firstName'),
        'middleName':       _val('middleName'),
        'lastName':         _val('lastName'),
        'addharNumber':     _val('addharNumber'),
        'contactNumber':    _val('contactNumber'),
        'serialNumber':     final_serial,
        'serialSource':     'manual',
        'serialNo_voterlist': _val('serialNo_voterlist'),
        'dob':              dob_str,
        'age':              age,
        'gender':           _val('gender'),
        'maritalStatus':    _val('maritalStatus'),
        'voterid':          voterid or _val('voterid'),
        'isHeadOfHouse':    _val('isHeadOfHouse', 'No'),

        # ── Aadhaar photo (GCS URL if uploaded, else None) ─────────
        'aadhaarPhotoUrl':  None,

        # ── SIR application form photo (GCS URL if uploaded, else None) ──
        'sirFormPhotoUrl':  None,

        # ── Government schemes used ────────────────────────────────
        'schemesUsed':      body.get('schemes') or [],

        # ── Outstation ────────────────────────────────────────────
        'outstationResident': _val('outstationResident', 'No'),
        'outstationCity':     _val('outstationCity')    if is_outstation else None,
        'outstationState':    _val('outstationState')   if is_outstation else None,
        'outstationAddress':  _val('outstationAddress') if is_outstation else None,

        # ── Current location (only when outstation = Yes) ─────────
        'currentHouseNumber': _val('currentHouseNumber') if is_outstation else None,
        'currentAreaType':    _val('currentAreaType')    if is_outstation else None,
        'currentHomeType':    _val('currentHomeType')    if is_outstation else None,
        'currentAddress':     _val('currentAddress')     if is_outstation else None,

        # ── Registered address ────────────────────────────────────
        'wardNumber':       _val('wardNumber'),
        'boothNo':          _val('boothNo'),
        'houseNumber':      _val('houseNumber'),
        'address':          _val('address'),
        'areaType':         _val('areaType'),
        'homeType':         _val('homeType'),

        # ── Financial ─────────────────────────────────────────────
        'annualIncome':     _val('annualIncome'),
        'familyIncome':     _val('familyIncome'),
        'economicStatus':   _val('economicStatus'),

        # ── Demographics ──────────────────────────────────────────
        'religion':         _val('religion'),
        'community':        _val('community'),
        'subcategory':      _val('subcategory'),
        'education':        _val('education'),
        'educationtype':    _val('educationtype'),
        'minority':         _val('minority', 'No'),
        'student':          _val('student', 'No'),

        # ── Employment ────────────────────────────────────────────
        'employmentStatus': _val('employmentStatus'),
        'employmentType':   _val('employmentType') if body.get('employmentStatus') == 'Employed' else None,

        # ── Health ────────────────────────────────────────────────
        'healthStatus':     _val('healthStatus', 'Healthy'),
        'diseaseType':      _val('diseaseType')  if body.get('healthStatus') == 'Diseased' else None,
        'diseaseName':      _val('diseaseName')  if body.get('healthStatus') == 'Diseased' else None,
        'differentlyAbled': _val('differentlyAbled', 'No'),

        # ── Party Membership ─────────────────────────────────────
        # partyMember: 'Yes' | 'No'
        # partyMembershipId: unique ID string supplied by the surveyor (only when partyMember='Yes')
        # bjpMember: True | False | None
        #   True/False = verified via BJP DB (once connected)
        #   None       = DB not yet connected; ID stored for future verification
        'partyMember':        _val('partyMember', 'No'),
        'partyMembershipId':  _val('partyMembershipId') if body.get('partyMember') == 'Yes' else None,
        'bjpMember':          body.get('bjpMember'),   # True / False / None

        # ── 2025 voter roll prefill fields ────────────────────────
        'relation':             _val('relation'),
        'relationName':         _val('relationName'),
        'partNo':               _val('partNo'),
        'sectionName':          _val('sectionName'),
        'pollingStation':       _val('pollingStation'),
        'pollingStationAddr':   _val('pollingStationAddr'),
        'sourcePdfName':        _val('sourcePdfName'),
        'pageNoOfCard':         _val('pageNoOfCard'),
        'predictedReligion':    _val('predictedReligion'),

        'Time_stamp':       datetime.utcnow(),
    }

    survey_db = get_survey_db()

    # ── 3. Duplicate check ────────────────────────────────────────────────────
    vid_check = data.get('voterid', '') or ''
    if vid_check.strip():
        existing = survey_db['SurveyRecords'].find_one({'voterid': vid_check.strip()}, {'_id': 1})
        if existing:
            return JsonResponse(
                {'success': False, 'message': f'Survey for Voter ID "{vid_check}" already exists.'},
                status=409
            )

    # ── 4. SIR analysis — run synchronously so we can label the record ──────────
    # Reads voter rolls from the main cluster (get_db()).
    # Writes SIR_* collections to the survey cluster (get_survey_db()).
    sir_result   = None
    sir_category = 'UNKNOWN'   # will be stored on the survey record
    try:
        voterid_sir = (data.get('voterid') or '').strip().upper()
        name_sir    = _norm((data.get('firstName', '') + ' ' + data.get('lastName', '')).strip())
        house_sir   = _norm(data.get('houseNumber', ''))
        ward_sir    = data.get('wardNumber', '')
        booth_sir   = str(data.get('boothNo', ''))
        serial_sir  = data.get('serialNumber', '')

        sir_result = _run_sir_analysis(
            read_db  = get_db(),        # voter rolls (2002 / 2025) live here
            write_db = survey_db,       # SIR_* collections live alongside SurveyRecords
            voterid  = voterid_sir,
            name     = name_sir,
            house    = house_sir,
            ward     = ward_sir,
            booth    = booth_sir,
            serial   = serial_sir,
        )

        # Derive the primary category label for the SurveyRecord
        if sir_result and sir_result.get('results'):
            sir_category = sir_result['results'][0]['category']
        elif sir_result and sir_result.get('suspicious'):
            sir_category = 'SUSPICIOUS'

        # If additional suspicious flags were found, append that info
        if sir_result and sir_result.get('suspicious') and sir_category != 'SUSPICIOUS':
            sir_category = sir_category + '+SUSPICIOUS'

        print(f'[SIR] category={sir_category} for {voterid_sir or name_sir}')

    except Exception as _sir_err:
        print(f'[SIR] Inline analysis error: {_sir_err}')
        sir_category = 'SIR_ERROR'

    # Stamp the SIR category on the record before persisting
    data['sir_category']   = sir_category
    data['sir_suspicious'] = bool(sir_result and sir_result.get('suspicious')) if sir_result else False

    # ── 5a. Upload Aadhaar photo to GCS if provided ───────────────────────────
    if aadhaar_photo_file:
        try:
            import uuid as _uuid, os as _os
            first = (body.get('firstName') or 'unknown').replace(' ', '_').lower()
            last  = (body.get('lastName')  or '').replace(' ', '_').lower()
            ext   = _os.path.splitext(aadhaar_photo_file.name)[1].lower() or '.jpg'
            blob_name = f"aadhaar_photos/{first}_{last}_{final_serial}_{_uuid.uuid4().hex[:8]}{ext}"
            photo_url = _upload_to_gcs(aadhaar_photo_file, blob_name)
            data['aadhaarPhotoUrl'] = photo_url
            print(f"[api_save_survey] ✓ Aadhaar photo uploaded to GCS: {photo_url}")
        except Exception as _photo_err:
            # Non-fatal — survey still saves, photo URL stays None
            data['aadhaarPhotoUrl'] = None
            print(f"[api_save_survey] ✗ Aadhaar GCS upload failed: {_photo_err}")

    # ── 5a-ii. Upload SIR form photo to GCS if provided ──────────────────────
    if sir_form_photo_file:
        try:
            import uuid as _uuid, os as _os
            first = (body.get('firstName') or 'unknown').replace(' ', '_').lower()
            last  = (body.get('lastName')  or '').replace(' ', '_').lower()
            ext   = _os.path.splitext(sir_form_photo_file.name)[1].lower() or '.jpg'
            blob_name = f"sir_form_photos/{first}_{last}_{final_serial}_{_uuid.uuid4().hex[:8]}{ext}"
            sir_photo_url = _upload_to_gcs(sir_form_photo_file, blob_name)
            data['sirFormPhotoUrl'] = sir_photo_url
            print(f"[api_save_survey] ✓ SIR form photo uploaded to GCS: {sir_photo_url}")
        except Exception as _sir_photo_err:
            data['sirFormPhotoUrl'] = None
            print(f"[api_save_survey] ✗ SIR form photo GCS upload failed: {_sir_photo_err}")

    # ── 5b. Always save directly to SurveyRecords ────────────────────────────
    survey_db['SurveyRecords'].insert_one(data)
    print(f"[api_save_survey] Saved to SurveyRecords — serial {final_serial}, SIR={sir_category}")

    return JsonResponse({
        'success':        True,
        'message':        'Survey saved successfully.',
        'serialNumber':   final_serial,
        'serialSource':   data['serialSource'],
        'collection':     'SurveyRecords',
        'inVoterRoll':    None,
        'sir':            sir_result,   # ← frontend SIR modal reads this
        'sir_category':   sir_category,
    })


# ─── FUTURE VOTERS (first-time by 2028) ───────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST'])
def api_save_future_voters(request):
    try:
        body = json.loads(request.body)
    except Exception as exc:
        print(f"[api_save_future_voters] JSON parse error: {exc}")
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    future_voters  = body.get('futureVoters', [])
    house_number   = body.get('houseNumber', '')
    ward_number    = body.get('wardNumber', '')
    address        = body.get('address', '')

    if not future_voters:
        return JsonResponse({'success': False, 'message': 'No future voter data provided.'}, status=400)

    records = []
    for v in future_voters:
        if not v.get('name', '').strip():
            continue
        records.append({
            'name':              v.get('name', '').strip(),
            'dob':               v.get('dob', ''),
            'gender':            v.get('gender', ''),
            'classCourse':       v.get('classCourse', ''),
            'yearOfStudy':       v.get('yearOfStudy', ''),
            'headContactNumber': v.get('headContactNumber', ''),
            'houseNumber':       v.get('houseNumber') or house_number,
            'address':           v.get('address')     or address,
            'wardNumber':        ward_number,
            'Time_stamp':        datetime.utcnow(),
        })

    if not records:
        return JsonResponse({'success': False, 'message': 'No valid future voter entries.'}, status=400)

    db  = get_survey_db()
    col = db['FutureVoters']
    saved = 0
    skipped = 0
    for rec in records:
        key = {
            'name':        rec['name'],
            'dob':         rec['dob'],
            'houseNumber': rec['houseNumber'],
        }
        result = col.update_one(key, {'$setOnInsert': rec}, upsert=True)
        if result.upserted_id:
            saved += 1
        else:
            skipped += 1

    print(f"[api_save_future_voters] Saved {saved}, skipped {skipped} duplicate(s).")
    msg = f'{saved} record(s) saved.'
    if skipped:
        msg += f' {skipped} duplicate(s) skipped.'
    return JsonResponse({'success': True, 'saved': saved, 'skipped': skipped, 'message': msg})


# ─── DECEASED ─────────────────────────────────────────────────────────────────

# ── GCS helper — uploads a file-like object, returns public URL ───────────────
# Mirrors the proven pattern from the reference ecom views.py:
#   1. Write the in-memory Django file to a local temp file
#   2. Call upload_from_filename (same as reference code)
#   3. Call blob.make_public() — works on fine-grained ACL buckets
#   4. If make_public() fails (uniform bucket-level access), fall back to
#      constructing the canonical public URL directly.
#
# Env vars required on Render:
#   GCS_BUCKET_NAME                      e.g. "ecom-66993.appspot.com"
#   GOOGLE_APPLICATION_CREDENTIALS_JSON  full service-account key JSON (one line)

def _upload_to_gcs(file_obj, destination_blob_name):
    """
    Upload a Django UploadedFile / InMemoryUploadedFile to GCS.
    Returns the public HTTPS URL, or raises on error.
    """
    import os, json as _json, tempfile as _tmp
    from google.cloud import storage as _gcs
    from google.oauth2 import service_account as _sa

    bucket_name = os.environ.get('GCS_BUCKET_NAME', '')
    creds_json  = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON', '')

    if not bucket_name:
        raise ValueError('GCS_BUCKET_NAME env var is not set')
    if not creds_json:
        raise ValueError('GOOGLE_APPLICATION_CREDENTIALS_JSON env var is not set')

    # Build credentials exactly like the reference code
    # (same scopes that the working ecom project uses)
    creds_dict  = _json.loads(creds_json)
    credentials = _sa.Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            'https://www.googleapis.com/auth/cloud-platform',
            'https://www.googleapis.com/auth/devstorage.full_control',
        ],
    )
    client = _gcs.Client(credentials=credentials, project=creds_dict.get('project_id'))
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(destination_blob_name)

    # ── Write to a temp file then upload_from_filename ────────────────────────
    # This mirrors the reference code exactly and avoids in-memory seek issues.
    ext = os.path.splitext(file_obj.name)[1].lower() or '.tmp'
    content_type = getattr(file_obj, 'content_type', None) or 'application/octet-stream'

    with _tmp.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name
        file_obj.seek(0)
        for chunk in file_obj.chunks() if hasattr(file_obj, 'chunks') else [file_obj.read()]:
            tmp.write(chunk)

    try:
        # upload_from_filename — identical to the reference ecom code
        blob.upload_from_filename(tmp_path, content_type=content_type)

        # make_public() — works on fine-grained ACL buckets (same as reference)
        try:
            blob.make_public()
            public_url = blob.public_url
        except Exception as _acl_err:
            # Uniform bucket-level access: IAM must grant allUsers=Storage Object Viewer
            print(f"[GCS] make_public() skipped ({_acl_err}); falling back to direct URL. "
                  "Grant allUsers=Storage Object Viewer in GCS Console IAM.")
            public_url = f"https://storage.googleapis.com/{bucket_name}/{destination_blob_name}"

        print(f"[GCS] ✓ Uploaded '{file_obj.name}' → gs://{bucket_name}/{destination_blob_name}")
        print(f"[GCS] ✓ Public URL: {public_url}")
        return public_url

    finally:
        # Always clean up the temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@csrf_exempt
@require_http_methods(['POST'])
def api_save_deceased(request):
    try:
        raw      = request.POST.get('deceased') or request.body
        deceased = json.loads(raw) if isinstance(raw, str) else json.loads(raw)
    except Exception as exc:
        print(f"[api_save_deceased] Parse error: {exc}")
        return JsonResponse({'success': False, 'message': 'Invalid data'}, status=400)

    if not deceased:
        return JsonResponse({'success': False, 'message': 'No deceased data provided.'}, status=400)

    import os, uuid

    records = []
    for rec in deceased:
        if not rec.get('name', '').strip():
            continue

        certificate_url  = None   # GCS public URL — stored in Mongo
        certificate_name = None   # original filename — stored for reference

        file_index = rec.get('fileIndex')
        if file_index is not None:
            file_key = f'cert_{file_index}'
            uploaded = request.FILES.get(file_key)
            print(f"[api_save_deceased] file_index={file_index}, file_key={file_key}, found={uploaded is not None}, FILES_keys={list(request.FILES.keys())}")
            if uploaded:
                ext  = os.path.splitext(uploaded.name)[1].lower() or '.jpg'
                uid  = uuid.uuid4().hex
                # GCS path: deceased_certificates/<uid><ext>
                blob_name = f"deceased_certificates/{uid}{ext}"
                try:
                    certificate_url  = _upload_to_gcs(uploaded, blob_name)
                    certificate_name = uploaded.name
                    print(f"[api_save_deceased] ✓ Uploaded to GCS: {certificate_url}")
                except Exception as gcs_err:
                    print(f"[api_save_deceased] ✗ GCS upload failed: {gcs_err}")
                    traceback.print_exc()
                    # Return failure so frontend shows the error clearly
                    return JsonResponse({
                        'success': False,
                        'message': f'GCS certificate upload failed: {str(gcs_err)}. Check GCS_BUCKET_NAME and GOOGLE_APPLICATION_CREDENTIALS_JSON env vars on Render.',
                        'gcs_error': str(gcs_err),
                    }, status=500)
            else:
                print(f"[api_save_deceased] ⚠ file_key '{file_key}' not found in request.FILES — boundary issue or file not attached")

        records.append({
            'name':                rec.get('name', '').strip(),
            'voterid':             rec.get('voterid', ''),
            'gender':              rec.get('gender', ''),
            'ageAtDeath':          rec.get('ageAtDeath', ''),
            'dob':                 rec.get('dob', ''),
            'dateOfDeath':         rec.get('dateOfDeath', ''),
            'deathCertificate':    rec.get('deathCertificate', ''),  # certificate number
            'certificateFileUrl':  certificate_url,    # ← GCS public URL
            'certificateFileName': certificate_name,   # ← original filename
            'houseNumber':         rec.get('houseNumber', ''),
            'address':             rec.get('address', ''),
            'Time_stamp':          datetime.utcnow(),
        })

    if not records:
        return JsonResponse({'success': False, 'message': 'No valid deceased entries.'}, status=400)

    db = get_survey_db()
    db['Deceased'].insert_many(records)
    print(f"[api_save_deceased] Saved {len(records)} deceased record(s).")

    # Return the URLs so the frontend can confirm uploads succeeded
    urls = [r['certificateFileUrl'] for r in records if r['certificateFileUrl']]
    return JsonResponse({'success': True, 'saved': len(records), 'certificateUrls': urls})


# ─── SCHEMES ──────────────────────────────────────────────────────────────────

# ── Ward name → ward number lookup (mirrors WARD_FULL_DATA in frontend) ───────
_WARD_NAME_TO_NUM = {
    'PADAVU': 21, 'DEREBAIL SOUTH': 24, 'DEREBAIL WEST': 25,
    'DEREBAIL SOUTH WEST': 26, 'BOLOOR': 27, 'MANNAGUDDA': 28,
    'KAMBLA': 29, 'KODIALBAIL': 30, 'BEJAI': 31, 'KADRI NORTH': 32,
    'KADRI SOUTH': 33, 'SHIVBHAG': 34, 'PADAVU CENTRAL': 35,
    'PADAVU POORVA': 36, 'MAROLI': 37, 'BENDUR': 38, 'FALNIR': 39,
    'COURT': 40, 'CENTRAL': 41, 'DONGERKERY': 42, 'KUDROLI': 43,
    'NAVAYATH': 44, 'PORT': 45, 'CANTONMENT': 46, 'MILAGRIS': 47,
    'VALENCIA': 48, 'KANKANADY': 49, 'ALAPE DAKSHINA': 50,
    'ALAPE UTTARA': 51, 'KANNUR': 52, 'BAJAL': 53, 'JEPPINAMUGER': 54,
    'ATTAVARA': 55, 'MANGALADEVI': 56, 'HOIGE BAZAR': 57, 'BOLAR': 58,
    'JEPPU': 59, 'BENGRE': 60,
}

# ── Community mapping: MongoDB stored value → Excel scheme sheet value ─────────
# MongoDB stores community as "General" / "OBC" / "SC" / "ST".
# The Excel scheme sheet uses "GC" for General Category.
# Without this mapping, General-category voters match zero schemes.
_COMMUNITY_MAP = {
    'General': 'GC',
    'general': 'GC',
    'GC':      'GC',
    'OBC':     'OBC',
    'SC':      'SC',
    'ST':      'ST',
    # OBC sub-caste codes stored verbatim in some records
    '2A': 'OBC', '2B': 'OBC', '3A': 'OBC', '3B': 'OBC',
}

# ── Excel scheme file path (relative to Django project root) ───────────────────
_SCHEME_XLSX = 'StoreAllSheetData.xlsx'

# ── Scheme DataFrame cache — loaded once, reused for every eligibility check ───
_SCHEME_DF_LOCK = threading.Lock()
_SCHEME_DF      = None   # pd.DataFrame, populated on first call

def _get_scheme_df():
    """Load and cache the scheme Excel file. Thread-safe."""
    global _SCHEME_DF
    if _SCHEME_DF is not None:
        return _SCHEME_DF
    with _SCHEME_DF_LOCK:
        if _SCHEME_DF is not None:
            return _SCHEME_DF
        try:
            _SCHEME_DF = pd.read_excel(_SCHEME_XLSX)
            print(f'[Schemes] Loaded {len(_SCHEME_DF)} schemes from {_SCHEME_XLSX}')
        except Exception as e:
            print(f'[Schemes] Failed to load {_SCHEME_XLSX}: {e}')
            _SCHEME_DF = pd.DataFrame()
        return _SCHEME_DF


def _normalize_voter_for_scheme(voter_data: dict) -> dict:
    """
    Convert a voter dict (as returned by api_scheme_voter_list) into the
    exact field names and values expected by the Excel scheme sheet columns.

    Key transformations applied:
      1. Community  : "General" → "GC"  (and sub-caste codes 2A/2B → "OBC")
      2. PhysicalStatus → DifferentlyAbled  (field rename; value stays Yes/No)
    """
    community_raw = str(voter_data.get('Community', '') or '').strip()
    community     = _COMMUNITY_MAP.get(community_raw, community_raw)

    return {
        'Gender':           str(voter_data.get('Gender',           '') or '').strip(),
        'MaritalStatus':    str(voter_data.get('MaritalStatus',    '') or '').strip(),
        'EconomicStatus':   str(voter_data.get('EconomicStatus',   '') or '').strip(),
        'EmploymentStatus': str(voter_data.get('EmploymentStatus', '') or '').strip(),
        'EmploymentType':   str(voter_data.get('EmploymentType',   '') or '').strip(),
        'Religion':         str(voter_data.get('Religion',         '') or '').strip(),
        'Community':        community,
        'SubCategory':      str(voter_data.get('SubCategory',      '') or '').strip(),
        'Education':        str(voter_data.get('Education',        '') or '').strip(),
        'EducationType':    str(voter_data.get('EducationType',    '') or '').strip(),
        # PhysicalStatus (voter key) → DifferentlyAbled (Excel column name)
        'DifferentlyAbled': str(voter_data.get('PhysicalStatus',  'No') or 'No').strip(),
        'HealthStatus':     str(voter_data.get('HealthStatus',     '') or '').strip(),
        'HomeType':         str(voter_data.get('HomeType',         '') or '').strip(),
        'AGE':              str(voter_data.get('AGE',              '') or '').strip(),
    }


@csrf_exempt
@require_http_methods(['POST'])
def api_scheme_voter_list(request):
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    ward = str(body.get('ward', '')).strip()
    if not ward:
        return JsonResponse({'success': False, 'message': 'Ward is required.'}, status=400)

    # Frontend sends ward number (e.g. "25") — resolve to name ("DEREBAIL WEST")
    ward_name = None
    try:
        ward_num = int(ward)
        for name, num in _WARD_NAME_TO_NUM.items():
            if num == ward_num:
                ward_name = name
                break
    except ValueError:
        ward_name = ward.upper().strip()

    if not ward_name:
        ward_name = ward.upper().strip()

    print(f"[api_scheme_voter_list] ward={ward!r} → ward_name={ward_name!r}")

    # ── Query SurveyRecords on the survey cluster ──────────────────────────────
    try:
        survey_db = get_survey_db()
        docs = list(survey_db['SurveyRecords'].find(
            {'wardNumber': {'$regex': f'^{ward_name}$', '$options': 'i'}},
        ).limit(500))
    except Exception as e:
        print(f"[api_scheme_voter_list] DB error: {e}")
        docs = []

    print(f"[api_scheme_voter_list] {len(docs)} records found for ward_name={ward_name!r}")

    # Normalise SurveyRecords camelCase → PascalCase keys expected by the frontend
    # and by _normalize_voter_for_scheme() during eligibility matching.
    voters = []
    for d in docs:
        d = bson_clean(d)
        voter_name = ' '.join(filter(None, [
            d.get('firstName', ''), d.get('middleName', ''), d.get('lastName', '')
        ])).strip()

        # differentlyAbled → both PhysicalStatus (UI display) and DifferentlyAbled (scheme match)
        differently_abled = 'Yes' if str(d.get('differentlyAbled', '') or '').lower() == 'yes' else 'No'

        voters.append({
            'Voter_Name':       voter_name,
            'VoterID':          d.get('voterid',         ''),
            'House_No':         d.get('houseNumber',      ''),
            'MobileNumber':     d.get('contactNumber',    ''),
            'DOB':              d.get('dob',              ''),
            'AGE':              str(d.get('age',          '')),
            'Gender':           d.get('gender',           ''),
            'Religion':         d.get('religion',         ''),
            # Community stored raw (e.g. "General") — mapping applied in _normalize_voter_for_scheme
            'Community':        d.get('community',        ''),
            'SubCategory':      d.get('subcategory',      ''),
            'EconomicStatus':   d.get('economicStatus',   ''),
            'EmploymentStatus': d.get('employmentStatus', ''),
            'EmploymentType':   d.get('employmentType',   ''),
            'HealthStatus':     d.get('healthStatus',     ''),
            # PhysicalStatus — kept for UI display in modal
            'PhysicalStatus':   differently_abled,
            # DifferentlyAbled — matches the Excel column name; used by scheme matching
            'DifferentlyAbled': differently_abled,
            'HomeType':         d.get('homeType',         ''),
            'MaritalStatus':    d.get('maritalStatus',    ''),
            'Education':        d.get('education',        ''),
            'EducationType':    d.get('educationtype',    ''),
            'AnnualIncome':     d.get('annualIncome',     ''),
            'FamilyIncome':     d.get('familyIncome',     ''),
            'WardNumber':       d.get('wardNumber',       ''),
            'BoothNo':          d.get('boothNo',          ''),
            'Address':          d.get('address',          ''),
            'SchemesUsed':      d.get('schemesUsed',      []),
            'IsHeadOfHouse':    d.get('isHeadOfHouse',    ''),
            'Minority':         d.get('minority',         ''),
            'Student':          d.get('student',          ''),
        })

    return JsonResponse({'success': True, 'voters': voters})


@csrf_exempt
@require_http_methods(['POST'])
def api_view_scheme(request):
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    # Support both { voterData: {...} } (correct) and flat { Gender: ..., AGE: ... } (legacy)
    if 'voterData' in body and isinstance(body['voterData'], dict):
        voter_data = body['voterData']
    else:
        voter_data = body  # flat payload — treat entire body as voter data

    print(f'[api_view_scheme] voter_data keys: {list(voter_data.keys())}')
    print(f'[api_view_scheme] voter_data: {voter_data}')

    # Normalize community + rename PhysicalStatus → DifferentlyAbled to match Excel columns
    normalized = _normalize_voter_for_scheme(voter_data)
    print(f'[api_view_scheme] normalized: {normalized}')

    eligible = []
    try:
        df = _get_scheme_df()
        for _, row in df.iterrows():
            row_d = {k: str(v) for k, v in row.to_dict().items()}
            if _is_eligible(normalized, row_d):
                eligible.append({
                    'Name':        row_d.get('Name',        ''),
                    'Type':        row_d.get('type',        ''),
                    'Link':        row_d.get('Link',        ''),
                    'Ministry':    row_d.get('ministry',    ''),
                    'Description': row_d.get('Description', ''),
                })
    except Exception as e:
        print(f'[api_view_scheme] Error: {e}')
        eligible = []

    return JsonResponse({'success': True, 'schemes': eligible})


def _is_eligible(voter: dict, scheme_row: dict) -> bool:
    """
    Return True if the voter satisfies every non-blank criterion in scheme_row.

    voter     : normalised dict keyed by Excel column names
    scheme_row: one row of the scheme DataFrame as {col: str(value)}

    Fixes applied vs original:
      - Trailing-space tokens: .strip() on every allowed value from the Excel cell
        (some cells contain "Employed, UnEmployed " with trailing space).
      - Empty voter values: skip matching when the voter field is blank/None
        (previously "" was looked up in the allowed list and always failed).
      - AGE range: unchanged logic, just cleaner error handling.
    """
    for key, voter_val in voter.items():
        if key not in scheme_row:
            continue

        scheme_val = str(scheme_row[key]).strip()
        if scheme_val.lower() in ('nan', 'none', ''):
            continue   # scheme has no restriction on this field

        voter_str = str(voter_val).strip()
        if not voter_str:
            continue   # voter field empty — treat as no constraint

        if key == 'AGE':
            try:
                age = int(float(voter_str))
                in_range = False
                for r in scheme_val.split(','):
                    parts = r.strip().split('-')
                    if len(parts) == 2:
                        low  = int(parts[0].strip())
                        high = int(parts[1].strip())
                        if low <= age <= high:
                            in_range = True
                            break
                if not in_range:
                    return False
            except Exception:
                return False
        else:
            # Strip every token — handles trailing-space values in Excel cells
            allowed = [v.strip() for v in scheme_val.split(',')]
            if voter_str not in allowed:
                return False

    return True


# ─── DATA VIEW ────────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_data_view(request):
    try:
        view_type = request.GET.get('view', 'survey')
        page      = max(1, int(request.GET.get('page', 1)))
        search    = request.GET.get('search', '').strip()

        # ── Collection and field setup per view type ──────────────────────────
        if view_type == 'voter':
            per_page = min(int(request.GET.get('per_page', 200)), 200)
            db       = get_db()
            coll     = db['2025']
            PROJ = {
                'Name': 1, 'Epic NO': 1, 'House No': 1,
                'Gender': 1, 'Age': 1, 'Booth No': 1, 'Part No': 1,
                'Relation Name': 1, 'Address': 1,
                'Sl No': 1, 'Serial No': 1,
            }
            if search:
                regex = {'$regex': search.strip(), '$options': 'i'}
                query = {'$or': [
                    {'Name':          regex},
                    {'Epic NO':       regex},
                    {'House No':      regex},
                    {'Relation Name': regex},
                    {'Address':       regex},
                ]}
            else:
                query = {}

        elif view_type == 'future_voters':
            per_page = min(int(request.GET.get('per_page', 100)), 500)
            db       = get_survey_db()
            coll     = db['FutureVoters']
            PROJ     = None
            if search:
                regex = {'$regex': search, '$options': 'i'}
                query = {'$or': [
                    {'name':        regex},
                    {'houseNumber': regex},
                    {'wardNumber':  regex},
                    {'gender':      regex},
                ]}
            else:
                query = {}

        elif view_type == 'deceased':
            per_page = min(int(request.GET.get('per_page', 100)), 500)
            db       = get_survey_db()
            coll     = db['Deceased']
            PROJ     = None
            if search:
                regex = {'$regex': search, '$options': 'i'}
                query = {'$or': [
                    {'name':        regex},
                    {'voterid':     regex},
                    {'houseNumber': regex},
                    {'gender':      regex},
                ]}
            else:
                query = {}

        elif view_type == 'bjp_members':
            # ── BJP Members: SurveyRecords where partyMember = 'Yes' ────────────
            per_page = min(int(request.GET.get('per_page', 100)), 500)
            db       = get_survey_db()
            coll     = db['SurveyRecords']
            PROJ     = None
            base_filter = {'partyMember': 'Yes'}
            if search:
                regex = {'$regex': search, '$options': 'i'}
                query = {'$and': [
                    base_filter,
                    {'$or': [
                        {'firstName':         regex},
                        {'lastName':          regex},
                        {'voterid':           regex},
                        {'partyMembershipId': regex},
                        {'wardNumber':        regex},
                        {'houseNumber':       regex},
                        {'contactNumber':     regex},
                        {'community':         regex},
                    ]}
                ]}
            else:
                query = base_filter

        elif view_type == 'outstation_voters':
            # ── Outstation voters: SurveyRecords where outstationResident = 'Yes' ──
            per_page = min(int(request.GET.get('per_page', 100)), 500)
            db       = get_survey_db()
            coll     = db['SurveyRecords']
            PROJ     = None
            base_filter = {'outstationResident': 'Yes'}
            if search:
                regex = {'$regex': search, '$options': 'i'}
                query = {'$and': [
                    base_filter,
                    {'$or': [
                        {'firstName':      regex},
                        {'lastName':       regex},
                        {'voterid':        regex},
                        {'outstationCity': regex},
                        {'outstationState':regex},
                        {'wardNumber':     regex},
                        {'houseNumber':    regex},
                        {'contactNumber':  regex},
                    ]}
                ]}
            else:
                query = base_filter

        else:  # survey (default)
            per_page = min(int(request.GET.get('per_page', 100)), 500)
            db       = get_survey_db()
            coll     = db['SurveyRecords']
            PROJ     = None
            if search:
                regex = {'$regex': search, '$options': 'i'}
                query = {'$or': [
                    {'firstName':   regex},
                    {'lastName':    regex},
                    {'voterid':     regex},
                    {'houseNumber': regex},
                    {'wardNumber':  regex},
                ]}
            else:
                query = {}

        total  = coll.count_documents(query)
        skip   = (page - 1) * per_page
        cursor = coll.find(query, PROJ) if PROJ else coll.find(query)
        docs   = list(cursor.skip(skip).limit(per_page))

        if view_type == 'voter':
            data = [bson_clean(d) for d in docs]
        else:
            data = [bson_clean(d, keep_id=True) for d in docs]

        all_keys, seen = [], set()
        for d in data:
            for k in d.keys():
                if k not in seen:
                    seen.add(k)
                    all_keys.append(k)

        display_cols = [k for k in all_keys if k != '_id']

        coll_name = {
            'voter':              '2025',
            'survey':             'SurveyRecords',
            'future_voters':      'FutureVoters',
            'deceased':           'Deceased',
            'outstation_voters':  'SurveyRecords',
            'bjp_members':        'SurveyRecords',
        }.get(view_type, view_type)

        return JsonResponse({
            'success':    True,
            'data':       data,
            'columns':    display_cols,
            'total':      total,
            'page':       page,
            'perPage':    per_page,
            'pages':      max(1, (total + per_page - 1) // per_page),
            'collection': coll_name,
            'search':     search,
        })

    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'Data fetch error: {str(exc)}',
            'data': [], 'columns': [], 'total': 0, 'page': 1, 'pages': 1
        }, status=500)

@require_http_methods(['GET'])
def api_voter_search(request):
    q      = request.GET.get('q', '').strip()
    page   = int(request.GET.get('page', 1))
    limit  = 50

    if not q:
        return JsonResponse({'success': True, 'voters': [], 'total': 0})

    db   = get_db()
    coll = db['2025']

    regex = {'$regex': q, '$options': 'i'}
    query = {'$or': [
        {'Name':         regex},
        {'Epic NO':      regex},
        {'House No':     regex},
        {'Relation Name': regex},
        {'Address':      regex},
    ]}

    total = coll.count_documents(query)
    skip  = (page - 1) * limit
    docs  = list(coll.find(query).skip(skip).limit(limit))

    voters = []
    for doc in docs:
        d = bson_clean(doc)
        # Normalise to consistent frontend keys using actual 2025 field names
        voters.append({
            'Voter_Name':    d.get('Name', ''),
            'VoterID':       d.get('Epic NO', ''),
            'House_No':      d.get('House No', ''),
            'Relation_Name': d.get('Relation Name', ''),
            'Booth_No':      str(d.get('Booth No', '')),
            'Age':           d.get('Age', ''),
            'Gender':        d.get('Gender', ''),
            'Address':       d.get('Address', ''),
            'Part_No':       str(d.get('Part No', '')),
            'Section_name':  d.get('Section name', ''),
            'Polling_Station_Name':    d.get('polling Station Name', ''),
            'Polling_Station_Address': d.get('Polling Statuin Address', ''),
            'Source_PDF_Name':         d.get('Source PDF Name', ''),
            'Page_No_of_card':         d.get('Page No of card', ''),
            'Predicted_Religion':      d.get('Predicted_Religion', ''),
            'Predicted_Religion_Label':d.get('Predicted_Religion_Label', ''),
            'Serial_No':     d.get('Serial No', ''),
            'Relation':      d.get('Relation', ''),
        })

    return JsonResponse({'success': True, 'voters': voters, 'total': total, 'page': page})


# ─── VOTER FAMILY ─────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_voter_family(request):
    house_no = request.GET.get('house')
    if not house_no:
        return JsonResponse({'success': True, 'family': []})

    db   = get_db()
    coll = db['2025']
    docs = list(coll.find({'House No': house_no}))
    family = [bson_clean(d) for d in docs]
    return JsonResponse({'success': True, 'family': family})


# ─── HOUSE SEARCH ─────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_house_search(request):
    """
    Optimised: 3 DB queries total regardless of result size.
      Q1 — match search term → collect unique house numbers (projection only)
      Q2 — fetch ALL members for those houses in one $in query
      Q3 — fetch all surveyed voter IDs for those members in one $in query
    """
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'success': True, 'houses': [], 'total_houses': 0})

    db         = get_db()
    voter_col  = db['2025']
    survey_col = get_survey_db()['SurveyRecords']

    exact_voter = voter_col.find_one(
        {'Epic NO': q},
        {'House No': 1}
    )
    if exact_voter:
        hn = str(exact_voter.get('House No', '')).strip()
        house_nos = {hn} if hn else set()
    else:
        regex       = {'$regex': re.escape(q), '$options': 'i'}
        match_query = {'$or': [
            {'Name':          regex},
            {'Epic NO':       regex},
            {'House No':      regex},
            {'Relation Name': regex},
            {'Address':       regex},
        ]}
        matched = voter_col.find(
            match_query,
            {'House No': 1}
        ).limit(100)

        house_nos = set()
        for doc in matched:
            hn = str(doc.get('House No', '')).strip()
            if hn:
                house_nos.add(hn)

    if not house_nos:
        return JsonResponse({'success': True, 'houses': [], 'total_houses': 0})

    hn_list = list(house_nos)
    hn_ints = [int(h) for h in hn_list if h.isdigit()]
    house_query = {'House No': {'$in': hn_list + hn_ints}}
    all_member_docs = list(voter_col.find(house_query))

    house_map = {}
    all_voter_ids = []
    for doc in all_member_docs:
        d  = bson_clean(doc)
        hn = str(d.get('House No', '')).strip()
        if not hn:
            continue
        vid = str(d.get('Epic NO', '')).strip()
        _relation      = str(d.get('Relation',      '')).strip()   # e.g. "Father", "Husband"
        _relation_name = str(d.get('Relation Name', '')).strip()   # e.g. "HARISHCHANDRA"
        member = {
            'name':               str(d.get('Name', '')).strip(),
            'relation':           _relation,
            'relationName':       _relation_name,
            'voterid':            vid,
            'gender':             str(d.get('Gender', '')),
            'age':                d.get('Age', ''),
            'booth':              str(d.get('Booth No', '')),
            'ward':               str(d.get('Part No', '')),
            'house_no':           hn,
            'address':            str(d.get('Address', '')),
            'serial_no':          d.get('Serial No') or d.get('Sl No', ''),
            # ── 2025 voter roll enrichment fields ──────────────────────────
            'partNo':             str(d.get('Part No', '')).strip(),
            'sectionName':        str(d.get('Section name', '')).strip(),
            'pollingStation':     str(d.get('polling Station Name', '')).strip(),
            'pollingStationAddr': str(d.get('Polling Statuin Address', '')).strip(),
            'sourcePdfName':      str(d.get('Source PDF Name', '')).strip(),
            'pageNoOfCard':       str(d.get('Page No of card', '')).strip(),
            'predictedReligion':  str(d.get('Predicted_Religion_Label', '')).strip(),
            'religion':           {'H': 'Hindu', 'M': 'Muslim', 'C': 'Christian', 'J': 'Jain', 'B': 'Buddhist', 'S': 'Sikh'}.get(str(d.get('Predicted_Religion_Label', '')).strip(), ''),
            'surveyed':           False,
        }
        house_map.setdefault(hn, []).append(member)
        if vid:
            all_voter_ids.append(vid)

    surveyed_ids   = set()
    survey_rec_map = {}
    if all_voter_ids:
        for rec in survey_col.find(
            {'voterid': {'$in': all_voter_ids}},
            {
                'voterid': 1, 'houseNumber': 1, 'wardNumber': 1, 'boothNo': 1,
                'address': 1, 'areaType': 1, 'homeType': 1, 'familyIncome': 1,
            }
        ):
            sid = (rec.get('voterid') or '').strip()
            if sid:
                surveyed_ids.add(sid)
                survey_rec_map[sid] = {
                    'houseNumber':  rec.get('houseNumber', ''),
                    'wardNumber':   rec.get('wardNumber', ''),
                    'boothNo':      str(rec.get('boothNo', '')),
                    'address':      rec.get('address', ''),
                    'areaType':     rec.get('areaType', ''),
                    'homeType':     rec.get('homeType', ''),
                    'familyIncome': rec.get('familyIncome', ''),
                }

    houses = []
    for hn in sorted(house_map.keys()):
        members = house_map[hn]
        for m in members:
            m['surveyed'] = m['voterid'] in surveyed_ids

        total    = len(members)
        surveyed = sum(1 for m in members if m['surveyed'])
        sample   = members[0] if members else {}

        house_survey_data = {}
        for m in members:
            if m['surveyed'] and m['voterid'] in survey_rec_map:
                house_survey_data = survey_rec_map[m['voterid']]
                break

        houses.append({
            'house_no':          hn,
            'ward':              sample.get('ward', ''),
            'booth':             sample.get('booth', ''),
            'total_members':     total,
            'surveyed':          surveyed,
            'remaining':         total - surveyed,
            'members':           members,
            'house_survey_data': house_survey_data,
        })

    return JsonResponse({
        'success':      True,
        'houses':       houses,
        'total_houses': len(houses),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SIR — SUMMARY INTENSIVE REVISION
# 2002 voter list → MongoDB  SurveyDataBase.2002
# 2025 voter list → MongoDB  SurveyDataBase.2025
# ═══════════════════════════════════════════════════════════════════════════════

_KA_PREFIXES = {
    'NUX','KAX','KAP','SCX','SXK','JWX','XKA','ZMK','YHX','TFX',
    'KXA','NUK','KAZ','SKA','KAS','AKA','NAX','ZKA',
}


def _norm(v):
    return str(v or '').strip().upper()


# ── 2025 MongoDB normalizer ───────────────────────────────────────────────────
# Fields stored by the upload script:
#   Epic NO, Name, Relation Name, House No, Gender, Age, Booth No, Part No

def _flat_2025(doc):
    if not doc:
        return {}
    return {
        'name':     _norm(doc.get('Name', '')),
        'relation': _norm(doc.get('Relation Name', '')),
        'house':    _norm(doc.get('House No', '')),
        'voterid':  _norm(doc.get('Epic NO', '')),
        'gender':   _norm(doc.get('Gender', '')),
        'age':      str(doc.get('Age', '')).strip(),
        'booth':    str(doc.get('Booth No', '')),
        'ward':     str(doc.get('Part No', '')),
    }


# ── 2002 MongoDB normalizer ───────────────────────────────────────────────────
# New column schema (2002_new_.xlsx uploaded to SurveyDataBase.2002):
#   Voter Name, Relative Name, House / Flat No, Voter ID / EPIC No, Gender, Age

# ── 2002 field name aliases ────────────────────────────────────────────────────
# The collection may contain docs uploaded under the OLD schema (field names from
# the Google Sheets upload) OR the NEW schema (from 2002_new_.xlsx).  Both are
# handled by trying every known alias in priority order.
#
#  Field role   | NEW (2002_new_.xlsx) | OLD (Google Sheets)
#  -------------|----------------------|--------------------
#  Voter name   | "Voter Name"         | "Name"
#  Relative     | "Relative Name"      | "Relation Name"
#  House        | "House / Flat No"    | "House No"
#  EPIC / ID    | "Voter ID / EPIC No" | "Epic NO"

def _get2002(doc, *keys):
    """Return first non-empty value from a list of field name candidates."""
    for k in keys:
        v = doc.get(k)
        if v is not None and str(v).strip() not in ('', 'nan', 'NaN', 'NAN'):
            return str(v)
    return ''

def _flat_2002(doc):
    if not doc:
        return {}
    return {
        'name':     _norm(_get2002(doc, 'Voter Name', 'Name')),
        'relation': _norm(_get2002(doc, 'Relative Name', 'Relation Name')),
        'house':    _norm(_get2002(doc, 'House / Flat No', 'House No')),
        'voterid':  _norm(_get2002(doc, 'Voter ID / EPIC No', 'Epic NO')),
        'gender':   _norm(_get2002(doc, 'Gender')),
        'age':      _get2002(doc, 'Age'),
        'booth':    _get2002(doc, 'Booth No', 'Part No'),
        'ward':     _get2002(doc, 'Ward No', 'Ward'),
    }


# Keep _flat as alias for backward compat with other callers
def _flat(doc):
    return _flat_2025(doc)


# ── Fuzzy similarity helpers ─────────────────────────────────────────────────
#
# Handles Indian name transliteration variants:
#   Vishwanath ↔ Vishvanath   (w/v swap)
#   Lakshmi ↔ Laxmi           (ksh→x)
#   Srinivas ↔ Sreenivas       (i→ee)
#   Chandrashekhar ↔ Chandrashekar
#   Venkataramana ↔ Venkatramana
#
# Strategy (applied in order):
#   1. Phonetic normalization — collapse known variant spellings to a common form
#   2. rapidfuzz scores (token_sort, partial, JaroWinkler) if library available
#   3. Pure-Python Levenshtein fallback — works even without rapidfuzz
#
# ALL THREE layers run independently; the MAX of all scores is used.
# This means either rapidfuzz OR the phonetic norm can salvage a match on its own.

_FUZZY_THRESHOLD     = 78
_FUZZY_THRESHOLD_REL = 72

_PHONETIC_RULES = [
    ('VISHW','VISHV'),('ASHW','ASHV'),('SHWAR','SHVAR'),
    ('THA','TA'),('DHA','DA'),('BHA','BA'),('SHA','SA'),
    ('EE','I'),('AA','A'),('OO','U'),('II','I'),
    ('KSH','X'),('GNE','NE'),('GNA','NA'),
]

# ── Cache phonetic_norm: same name is normalised thousands of times per bulk run
from functools import lru_cache as _lru_cache

@_lru_cache(maxsize=4096)
def _phonetic_norm(s: str) -> str:
    for old, new in _PHONETIC_RULES:
        s = s.replace(old, new)
    return s.rstrip('A')


# ── _gen_prefixes: phonetic-aware prefix variants for candidate fetching ───────
# Problem: "VEDHAVYAS" typed vs "VEDAVYAS" stored — prefix '^VEDHAVYAS' fetches
# zero DB rows so fuzzy scorer never gets to run.
#
# Solution: for a query token, generate ALL plausible prefix variants by applying
# transliteration mutations. Covers:
#   H-insertion/deletion:   VEDH↔VED, SINDH↔SIND, MADH↔MAD
#   W/V swap:               VISHW↔VISHV, ASHW↔ASHV
#   EE/I, AA/A, OO/U:       SREENIVAS↔SRINIVAS, LAXMI↔LAKSHMI
#   TH/T, DH/D, BH/B:       KATHA↔KATA, RADHA↔RADA
#   SH/S:                   SHANKARA↔SANKARA
#   KSH/X:                  LAKSHMI↔LAXMI (already in phonetic rules)
#
# Returns a deduplicated list of prefixes (shortest 3-char prefix last as broadest fallback).

_H_INSERTION_PAIRS = [
    # token fragment → (with_h, without_h)  — we add both directions
    ('DH', 'D'), ('TH', 'T'), ('BH', 'B'), ('GH', 'G'), ('KH', 'K'),
    ('SH', 'S'), ('CH', 'C'), ('JH', 'J'), ('NH', 'N'),
]

@_lru_cache(maxsize=2048)
def _gen_prefixes(token: str) -> tuple:
    """
    Given a normalised first token (e.g. 'VEDHAVYAS'), return a tuple of
    distinct regex-prefix strings to use in MongoDB $regex queries.
    Ordered: most-specific first, broad 3-char fallback last.
    """
    t = token.upper()
    variants = {t}  # always include original

    # 1) Phonetic norm variant
    pn = _phonetic_norm(t)
    if pn and pn != t:
        variants.add(pn)

    # 2) H-insertion/deletion mutations on the full token
    for dg, sg in _H_INSERTION_PAIRS:
        # remove H: VEDH→VED, SINDH→SIND
        if dg in t:
            variants.add(t.replace(dg, sg, 1))
        # insert H: VED→VEDH, SIN→SINH  (first occurrence of single char)
        idx = t.find(sg)
        while idx != -1:
            # only if not already followed by H
            if idx + len(sg) >= len(t) or t[idx + len(sg)] != 'H':
                candidate = t[:idx] + dg + t[idx + len(sg):]
                variants.add(candidate)
            idx = t.find(sg, idx + len(sg))

    # 3) W↔V swap
    if 'W' in t: variants.add(t.replace('W', 'V', 1))
    if 'V' in t: variants.add(t.replace('V', 'W', 1))

    # 4) EE↔I, AA↔A, OO↔U
    for old, new in [('EE','I'),('AA','A'),('OO','U'),('I','EE'),('A','AA')]:
        if old in t:
            variants.add(t.replace(old, new, 1))

    # Build prefix list: use longest feasible prefix per variant (≥4 chars),
    # plus the universal 3-char fallback of the original token.
    prefixes = []
    seen = set()
    for v in sorted(variants, key=lambda x: -len(x)):  # longest first = most specific
        pfx = v  # full token as prefix
        if pfx and len(pfx) >= 3 and pfx not in seen:
            seen.add(pfx)
            prefixes.append(pfx)

    # Always end with original 3-char as broadest fallback
    p3 = t[:3]
    if p3 not in seen and len(p3) == 3:
        prefixes.append(p3)

    return tuple(prefixes)


def _levenshtein_similarity(a: str, b: str) -> float:
    """Normalised Levenshtein (0-100). Only called when rapidfuzz unavailable."""
    if not a or not b: return 0.0
    if a == b: return 100.0
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * lb
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j]+1, curr[j-1]+1, prev[j-1]+(ca!=cb))
        prev = curr
    return round((1 - prev[lb] / max(la, lb)) * 100, 1)


def _partial_levenshtein(short: str, long: str) -> float:
    """Sliding-window Levenshtein. Only called when rapidfuzz unavailable."""
    ls, ll = len(short), len(long)
    if ls == 0 or ll == 0: return 0.0
    if ls > ll: return _partial_levenshtein(long, short)
    best = 0.0
    for start in range(ll - ls + 1):
        best = max(best, _levenshtein_similarity(short, long[start:start+ls]))
        if best >= 97: break   # early-exit
    return best


# ── _name_score: cached + fast path when rapidfuzz is available ───────────────
# With rapidfuzz:   ~0.01 ms per pair  (JaroWinkler + partial_ratio only)
# Without rapidfuzz: ~0.3 ms per pair  (pure-Python Levenshtein)
# lru_cache: repeated queries for same name pair → 0 ms

@_lru_cache(maxsize=8192)
def _name_score(a: str, b: str) -> float:
    if not a or not b: return 0.0
    if a == b: return 100.0

    pa, pb = _phonetic_norm(a), _phonetic_norm(b)
    if pa == pb: return 100.0   # phonetic exact — fastest possible exit

    if _RAPIDFUZZ_AVAILABLE:
        # rapidfuzz is 50-100× faster than pure-Python; skip Levenshtein entirely
        return max(
            _rfuzz.token_sort_ratio(a, b),
            _rfuzz.token_sort_ratio(pa, pb),
            _rfuzz.partial_ratio(a, b),
            _rfdist.JaroWinkler.normalized_similarity(a, b) * 100,
            _rfdist.JaroWinkler.normalized_similarity(pa, pb) * 100,
        )

    # Fallback: pure-Python (no rapidfuzz installed)
    s1 = _levenshtein_similarity(a, b)
    if s1 >= 95: return s1           # early-exit: already excellent
    s2 = _levenshtein_similarity(pa, pb)
    if s2 >= 95: return s2
    return max(s1, s2,
               _partial_levenshtein(a, b),
               _partial_levenshtein(pa, pb))


def _score_candidates(candidates, flat_fn, name, relation):
    """
    Universal candidate scorer — works for any combination of inputs.

    Returns (best_doc, best_score).

    Inputs guaranteed by caller:
      name      — normalised UPPER string, may be empty
      relation  — normalised UPPER string, may be empty
      candidates— list of raw MongoDB docs

    Scoring formula
    ───────────────
    name_score   : rapidfuzz / Levenshtein similarity 0-100
    rel_score    : same, 0-100

    token_coverage_pct : fraction of search-name tokens (≥2 chars) found in
                         the candidate name as substrings.
                         "RAJESH SHETTY" vs "RAJ"  → 1/2 = 50 %  (SHETTY missing)
                         "RAJESH SHETTY" vs "RAJESH SHETTY K" → 2/2 = 100 %

    composite formula (depending on what is available):

      BOTH name + relation provided, candidate HAS relation:
        comp = 0.55*name_score + 0.35*rel_score + 0.10*token_coverage_pct*100
        penalty −30 when rel_score < 40  (hard mismatch)

      BOTH name + relation provided, candidate has NO relation:
        comp = 0.70*name_score + 0.10*token_coverage_pct*100  (−20 penalty for absence)

      name only:
        comp = 0.90*name_score + 0.10*token_coverage_pct*100

      relation only (no name):
        comp = rel_score

      neither (should not happen in practice):
        comp = 0

    Multi-token guard: if the search name has ≥2 tokens and token_coverage_pct < 0.5
    (fewer than half tokens found in the candidate), cap comp at 62.
    This blocks "RAJ" from confirming for "RAJESH SHETTY".

    EPIC / house are NOT considered here — callers already pre-filter candidates
    by house or use EPIC directly (Tier 1).
    """
    name_tokens = [t for t in (name.split() if name else []) if len(t) >= 2]
    n_toks = len(name_tokens)

    best_doc, best_score = None, 0.0
    for doc in candidates:
        flat      = flat_fn(doc)
        cand_name = flat.get('name', '')
        cand_rel  = flat.get('relation', '')

        # ── name score ────────────────────────────────────────────────────────
        n_score = _name_score(name, cand_name) if (name and cand_name) else 0.0

        # ── token coverage ────────────────────────────────────────────────────
        if n_toks and cand_name:
            cand_up      = cand_name.upper()
            matched_toks = sum(1 for t in name_tokens if t in cand_up)
            tok_cov_pct  = matched_toks / n_toks
        else:
            matched_toks = n_toks
            tok_cov_pct  = 1.0   # no tokens to check → no penalty

        # ── relation score ────────────────────────────────────────────────────
        r_score = _name_score(relation, cand_rel) if (relation and cand_rel) else 0.0

        # ── composite ─────────────────────────────────────────────────────────
        if name and relation:
            if cand_rel:
                rel_penalty = -30.0 if r_score < 40 else 0.0
                comp = (0.55 * n_score
                        + 0.35 * r_score
                        + 0.10 * tok_cov_pct * 100
                        + rel_penalty)
            else:
                # candidate has no relation — cannot verify, mild penalty
                comp = 0.70 * n_score + 0.10 * tok_cov_pct * 100 - 20.0
        elif name:
            comp = 0.90 * n_score + 0.10 * tok_cov_pct * 100
        elif relation:
            comp = r_score
        else:
            comp = 0.0

        # ── multi-token guard ─────────────────────────────────────────────────
        # "RAJESH SHETTY" (2 tokens) vs "RAJ" (tok_cov_pct=0.5, SHETTY missing)
        # → cap at 62 so it never crosses confirmation threshold without house/EPIC
        if n_toks >= 2 and tok_cov_pct < 0.5:
            comp = min(comp, 62.0)

        comp = max(comp, 0.0)

        if comp > best_score:
            best_score, best_doc = comp, doc
        if best_score >= 97:
            break   # near-perfect — stop early

    return best_doc, best_score


def _fuzzy_match_from_candidates(candidates, name_field, rel_field,
                                  target_name, target_rel, threshold, rel_threshold):
    """Legacy wrapper — kept for any callers that still use it."""
    best_doc, best_score = None, 0.0
    for doc in candidates:
        cand_name = _norm(str(doc.get(name_field) or ''))
        cand_rel  = _norm(str(doc.get(rel_field)  or ''))
        n_score   = _name_score(target_name, cand_name)
        r_score   = _name_score(target_rel, cand_rel) if (target_rel and cand_rel) else 0.0
        comp      = (0.65 * n_score + 0.35 * r_score) if (target_rel and cand_rel) else n_score
        if comp > best_score:
            best_score, best_doc = comp, doc
        if best_score >= 97: break
    if best_score >= threshold:
        return best_doc, round(best_score, 1)
    return None, round(best_score, 1)


# ── Module-level Excel cache ──────────────────────────────────────────────────
# pd.read_excel on 113k rows takes 2-5 s.  Loading once at startup and
# building a house-number → row-index dict makes each suggestion lookup O(1).

_XLSX_CACHE_LOCK   = threading.Lock()
_XLSX_DF           = None   # pd.DataFrame, set on first load
_XLSX_COLS         = {}     # {role: actual_col_name}
_XLSX_HOUSE_IDX    = {} 

# {house_upper: [row_indices]}
def _get_xlsx():
    """Load and cache the 2002 Excel file. Thread-safe. Returns (df, cols, house_idx)."""
    global _XLSX_DF, _XLSX_COLS, _XLSX_HOUSE_IDX
    if _XLSX_DF is not None:
        return _XLSX_DF, _XLSX_COLS, _XLSX_HOUSE_IDX
    with _XLSX_CACHE_LOCK:
        if _XLSX_DF is not None:
            return _XLSX_DF, _XLSX_COLS, _XLSX_HOUSE_IDX
        import os as _ose
        path = _ose.path.join(
            _ose.path.dirname(_ose.path.dirname(_ose.path.abspath(__file__))),
            '2002_new_.xlsx',
        )
        if not _ose.path.exists(path):
            return None, {}, {}
        try:
            df = pd.read_excel(path, dtype=str, engine='openpyxl').fillna('')
            cols = {
                'name':   next((c for c in ('Voter Name','Name')             if c in df.columns), None),
                'rel':    next((c for c in ('Relative Name','Relation Name') if c in df.columns), None),
                'house':  next((c for c in ('House / Flat No','House No')    if c in df.columns), None),
                'epic':   next((c for c in ('Voter ID / EPIC No','Epic NO')  if c in df.columns), None),
                'gender': 'Gender' if 'Gender' in df.columns else None,
                'age':    'Age'    if 'Age'    in df.columns else None,
            }
            hidx = {}
            if cols['house']:
                for i, v in enumerate(df[cols['house']]):
                    k = str(v).strip().upper()
                    if k:
                        hidx.setdefault(k, []).append(i)
            _XLSX_DF, _XLSX_COLS, _XLSX_HOUSE_IDX = df, cols, hidx
            print(f'[SIR] Excel cached: {len(df):,} rows, {len(hidx):,} houses')
            return df, cols, hidx
        except Exception as e:
            print(f'[SIR] Excel cache error: {e}')
            return None, {}, {}


# ── Pre-load Excel at Django startup — prevents gunicorn timeout on first request
threading.Thread(target=_get_xlsx, daemon=True).start()   # ← ADD THIS LINE
# ── Lookup helpers ────────────────────────────────────────────────────────────

def _find_voter_in_2025(col, voterid, name, house, relation=''):
    """
    Confirmed-match lookup in the 2025 MongoDB voter roll.

    Decision table — fields provided → tiers attempted:
    ┌──────────────────────────────┬──────────────────────────────────────────┐
    │ EPIC                         │ Tier 1: exact index lookup               │
    │ name + house                 │ Tier 2: exact regex, then Tier 3 fuzzy   │
    │ house only  (+ rel optional) │ Tier 3: fuzzy within house               │
    │ name + relation (no house)   │ Tier 4: prefix scan, threshold 88        │
    │ name only   (no house)       │ Tier 4: prefix scan, threshold 90        │
    └──────────────────────────────┴──────────────────────────────────────────┘

    Thresholds
    ──────────
    Tier 2 exact (name+house)  : always return, but validate relation ≥ 35 if given
    Tier 3 fuzzy (house)       : 78  (house already narrows candidates well)
    Tier 4 no-house + relation : 88  (must match BOTH name and relation well)
    Tier 4 no-house, name only : 90  (very high bar without corroborating field)
    """
    _PROJ = {'Name':1,'Relation Name':1,'Epic NO':1,
             'House No':1,'Gender':1,'Age':1,'Booth No':1,'Part No':1}

    # ── Tier 1: EPIC exact ────────────────────────────────────────────────────
    if voterid:
        doc = col.find_one({'Epic NO': voterid}, _PROJ)
        if doc:
            return bson_clean(doc)

    # ── Tier 2: exact name match at exact house ───────────────────────────────
    if name and house:
        doc = col.find_one({'$and': [
            {'Name':     {'$regex': re.escape(name), '$options': 'i'}},
            {'House No': house},
        ]}, _PROJ)
        if doc:
            if relation:
                f = _flat_2025(doc)
                # Only confirm when relation is absent OR similarity >= 35
                if not f['relation'] or _name_score(relation, f['relation']) >= 35:
                    return bson_clean(doc)
                # else: same house, same name, different relative — fall through
            else:
                return bson_clean(doc)

    # ── Tier 3: fuzzy within house ────────────────────────────────────────────
    if house and (name or relation):
        candidates = list(col.find({'House No': house}, _PROJ))
        # Also try house-prefix to handle "2-14-1223" vs stored "2-14-1223/1"
        if not candidates:
            h_pfx = {'$regex': f'^{re.escape(house)}', '$options': 'i'}
            candidates = list(col.find({'House No': h_pfx}, _PROJ).limit(50))
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2025, name, relation)
            if best_doc and best_score >= _FUZZY_THRESHOLD:
                return bson_clean(best_doc)

    # ── Tier 4: name prefix scan (no house) ──────────────────────────────────
    # Only runs when no house was given — house tiers already exhausted above.
    # Threshold is intentionally high to avoid false positives across the whole DB.
    if name and not house:
        first_tok = name.split()[0]
        seen, candidates = set(), []
        for pfx in _gen_prefixes(first_tok):
            for doc in col.find(
                {'Name': {'$regex': f'^{re.escape(pfx)}', '$options': 'i'}}, _PROJ
            ).limit(60):
                oid = str(doc.get('_id', ''))
                if oid not in seen:
                    seen.add(oid)
                    candidates.append(doc)
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2025, name, relation)
            # Higher bar when no house — need strong match on name+relation together
            threshold = 88 if relation else 90
            if best_doc and best_score >= threshold:
                return bson_clean(best_doc)

    return None


def _find_voter_in_2002(col, voterid, name, house, relation=''):
    """
    Confirmed-match lookup in the 2002 MongoDB voter roll.
    Schema-agnostic: handles both old (Name/House No/Epic NO/Relation Name)
    and new (Voter Name/House / Flat No/Voter ID / EPIC No/Relative Name) field names.

    Same decision table as _find_voter_in_2025.
    Tier 3 threshold is 60 (2002 data is noisier, house narrows well).
    Tier 5 (prefix scan, no house) threshold is 88 with relation, 90 without.
    """
    _PROJ = {'Voter Name':1,'Name':1,'Relative Name':1,'Relation Name':1,
             'House / Flat No':1,'House No':1,
             'Voter ID / EPIC No':1,'Epic NO':1,
             'Gender':1,'Age':1,'Booth No':1,'Part No':1,'Serial No':1}

    def _hq(h):
        return {'$or': [{'House / Flat No': h}, {'House No': h}]}

    # ── Tier 1: EPIC exact ────────────────────────────────────────────────────
    if voterid:
        doc = col.find_one(
            {'$or': [{'Voter ID / EPIC No': voterid}, {'Epic NO': voterid}]}, _PROJ)
        if doc:
            return bson_clean(doc)

    # ── Tier 2: exact name + house ────────────────────────────────────────────
    if name and house:
        name_rx = {'$regex': re.escape(name), '$options': 'i'}
        doc = col.find_one({'$and': [
            {'$or': [{'Voter Name': name_rx}, {'Name': name_rx}]},
            _hq(house),
        ]}, _PROJ)
        if doc:
            if relation:
                f = _flat_2002(doc)
                if not f['relation'] or _name_score(relation, f['relation']) >= 35:
                    return bson_clean(doc)
            else:
                return bson_clean(doc)

    # ── Tier 3: fuzzy within house ────────────────────────────────────────────
    if house and (name or relation):
        candidates = list(col.find(_hq(house), _PROJ))
        if not candidates:
            h_pfx = {'$regex': f'^{re.escape(house)}', '$options': 'i'}
            pfx_q = {'$or': [{'House / Flat No': h_pfx}, {'House No': h_pfx}]}
            candidates = list(col.find(pfx_q, _PROJ).limit(50))
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2002, name, relation)
            if best_doc and best_score >= 60:
                return bson_clean(best_doc)

    # ── Tier 4: relation-first scan when name is very different (house required) ──
    # Catches cases where name spelling is completely different but relation matches.
    if relation and house and len(relation) >= 3:
        rpx = {'$regex': f'^{re.escape(relation[:4])}', '$options': 'i'}
        candidates = list(col.find({'$and': [
            _hq(house),
            {'$or': [{'Relative Name': rpx}, {'Relation Name': rpx}]},
        ]}, _PROJ).limit(20))
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2002, name, relation)
            if best_doc and best_score >= 60:
                return bson_clean(best_doc)

    # ── Tier 5: name prefix scan (no house) ──────────────────────────────────
    if name and not house and len(name) >= 3:
        first_tok = name.split()[0]
        seen, candidates = set(), []
        for pfx in _gen_prefixes(first_tok):
            px = {'$regex': f'^{re.escape(pfx)}', '$options': 'i'}
            for doc in col.find(
                {'$or': [{'Voter Name': px}, {'Name': px}]}, _PROJ
            ).limit(60):
                oid = str(doc.get('_id', ''))
                if oid not in seen:
                    seen.add(oid)
                    candidates.append(doc)
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2002, name, relation)
            threshold = 88 if relation else 90
            if best_doc and best_score >= threshold:
                return bson_clean(best_doc)

    return None


def _epic_prefix(vid):
    m = re.match(r'^([A-Z]{2,4})', _norm(vid))
    return m.group(1) if m else ''


def _run_sir_analysis(voterid, name, house, ward, booth, serial, relation='',
                      read_db=None, write_db=None, db=None):
    """
    read_db  — cluster holding 2025 voter roll (main cluster, get_db()).
               2002 voter roll is always read from get_survey_db() (_SURVEY_URL).
    write_db — cluster holding SIR_* collections   (survey cluster, get_survey_db()).

    Legacy callers that pass a positional `db` argument still work:
    both reads and writes go to that same db.
    """
    if db is not None:
        read_db  = db
        write_db = db
    if read_db is None:
        read_db  = get_db()
    if write_db is None:
        write_db = read_db

    col_2025 = read_db['2025']
    col_2002 = get_survey_db()['2002']  # 2002 roll lives on the _SURVEY_URL cluster

    # ── Look up in both rolls — parallel threads ─────────────────────────────────
    _rr = [None, None]
    _tA = threading.Thread(target=lambda: _rr.__setitem__(0, _find_voter_in_2025(col_2025, voterid, name, house, relation)), daemon=True)
    _tB = threading.Thread(target=lambda: _rr.__setitem__(1, _find_voter_in_2002(col_2002, voterid, name, house, relation)), daemon=True)
    _tA.start(); _tB.start(); _tA.join(); _tB.join()
    r25 = _flat_2025(_rr[0])
    r02 = _flat_2002(_rr[1])

    in_2025 = bool(r25)
    in_2002 = bool(r02)
    results = []
    any_stored = False
    ts = datetime.utcnow()

    base = {
        'surveyed_serial': serial,
        'surveyed_at':     ts,
        'ward':            ward,
        'booth':           booth,
        'survey_name':     name,
        'survey_house':    house,
        'survey_voterid':  voterid,
    }
    vid_key = voterid or r25.get('voterid') or r02.get('voterid') or name

    if in_2025 and not in_2002:
        doc = {**base, 'category': 'NEW_ADDITION',
               'name': r25['name'], 'voterid': r25['voterid'],
               'house': r25['house'], 'age_2025': r25['age'],
               'gender': r25['gender'], 'relation': r25['relation'],
               'note': 'In 2025 roll — absent from 2002 roll'}
        write_db['SIR_NewAdditions'].update_one(
            {'survey_voterid': vid_key},
            {'$setOnInsert': doc}, upsert=True)
        results.append({'category': 'NEW_ADDITION', 'label': 'New Addition',
                        'color': '#22d3ee', 'icon': '➕',
                        'detail': 'Voter appears in 2025 but was absent from 2002.'})
        any_stored = True

    elif in_2002 and not in_2025:
        doc = {**base, 'category': 'DELETION',
               'name': r02['name'], 'voterid': r02['voterid'],
               'house': r02['house'], 'age_2002': r02['age'],
               'gender': r02['gender'], 'relation': r02['relation'],
               'note': 'Was in 2002 roll — removed from 2025 roll'}
        write_db['SIR_Deleted'].update_one(
            {'survey_voterid': vid_key},
            {'$setOnInsert': doc}, upsert=True)
        results.append({'category': 'DELETION', 'label': 'Deletion',
                        'color': '#ef4444', 'icon': '🗑️',
                        'detail': 'Voter was in 2002 but removed from 2025.'})
        any_stored = True

    elif in_2025 and in_2002:
        changes = []
        for field, v02, v25 in [
            ('Name',     r02['name'],     r25['name']),
            ('Relation', r02['relation'], r25['relation']),
            ('House No', r02['house'],    r25['house']),
            ('Gender',   r02['gender'],   r25['gender']),
        ]:
            if v02 and v25 and v02 != v25:
                changes.append({'field': field, 'from': v02, 'to': v25})

        try:
            a25, a02 = int(r25['age']), int(r02['age'])
            diff = abs(a25 - (a02 + 23))
            if diff > 5:
                changes.append({'field': 'Age', 'from': str(a02), 'to': str(a25),
                                 'note': f'Expected ~{a02+23} in 2025, got {a25} (Δ{diff} yrs)'})
        except (ValueError, TypeError):
            pass

        if changes:
            doc = {**base, 'category': 'MODIFICATION',
                   'name_2002': r02['name'], 'name_2025': r25['name'],
                   'voterid': r25['voterid'] or r02['voterid'],
                   'house_2002': r02['house'], 'house_2025': r25['house'],
                   'age_2002': r02['age'],    'age_2025': r25['age'],
                   'changes': changes,
                   'note': f'{len(changes)} field(s) changed between rolls'}
            write_db['SIR_Modified'].update_one(
                {'survey_voterid': vid_key},
                {'$setOnInsert': doc}, upsert=True)
            results.append({'category': 'MODIFICATION', 'label': 'Modification',
                            'color': '#f59e0b', 'icon': '✏️',
                            'detail': f'{len(changes)} field(s) changed between the 2002 and 2025 rolls.',
                            'changes': changes})
            any_stored = True
        else:
            ret_doc = {**base, 'category': 'RETAINED',
                       'name': r25['name'], 'voterid': r25['voterid'],
                       'house': r25['house'], 'age_2002': r02['age'],
                       'age_2025': r25['age'], 'gender': r25['gender'],
                       'note': 'Record consistent in both 2002 and 2025 rolls'}
            write_db['SIR_Retained'].update_one(
                {'survey_voterid': vid_key},
                {'$setOnInsert': ret_doc}, upsert=True)
            results.append({'category': 'RETAINED', 'label': 'Retained',
                            'color': '#10b981', 'icon': '\u2713',
                            'detail': 'Record consistent in both 2002 and 2025 rolls.'})
            any_stored = True
    else:
        # NOT_FOUND — absent from BOTH rolls
        not_found_doc = {**base, 'category': 'NOT_FOUND',
                         'name': name, 'voterid': voterid, 'house': house,
                         'note': 'Not traced in 2002 or 2025 roll — data gap, OCR error, or unregistered'}
        write_db['SIR_NotFound'].update_one(
            {'survey_voterid': vid_key},
            {'$setOnInsert': not_found_doc}, upsert=True)
        results.append({'category': 'NOT_FOUND', 'label': 'Unregistered / Not Traced',
                        'color': '#6b7fa0', 'icon': '?',
                        'detail': 'Voter not found in either roll. May be unregistered, recently relocated, or name/ID mismatch.'})
        any_stored = True

    suspicious = []

    if voterid:
        prefix = _epic_prefix(voterid)
        if prefix and prefix not in _KA_PREFIXES:
            suspicious.append({'flag': 'OUT_OF_STATE_EPIC', 'label': 'Out-of-State EPIC',
                                'detail': f'Prefix "{prefix}" is not a Karnataka code.',
                                'value': voterid})
        dup = col_2025.count_documents({'Epic NO': voterid})
        if dup > 1:
            suspicious.append({'flag': 'DUPLICATE_EPIC', 'label': 'Duplicate EPIC',
                                'detail': f'EPIC "{voterid}" appears {dup} times in the 2025 list.',
                                'value': dup})

    if house:
        t25 = col_2025.count_documents({'House No': house})
        t02 = col_2002.count_documents({'House / Flat No': house})  # correct 2002 field
        net = t25 - t02
        if net > 5:
            suspicious.append({'flag': 'HOUSE_FLOOD', 'label': 'House Overcrowding',
                                'detail': f'House {house} gained {net} new entries (2002: {t02} → 2025: {t25}).',
                                'value': net})

    for s in suspicious:
        doc = {**base, 'category': 'SUSPICIOUS',
               'flag_type': s['flag'], 'flag_label': s['label'],
               'flag_detail': s['detail'], 'flag_value': s.get('value', ''),
               'name': name, 'voterid': voterid, 'house': house}
        write_db['SIR_Suspicious'].update_one(
            {'survey_voterid': vid_key, 'flag_type': s['flag']},
            {'$setOnInsert': doc}, upsert=True)
        any_stored = True

    return {
        'results':    results,
        'suspicious': suspicious,
        'stored':     any_stored,
        'in_2025':    in_2025,
        'in_2002':    in_2002,
    }


@csrf_exempt
@require_http_methods(['POST'])
def api_check_sir(request):
    """
    SIR check endpoint.
    store=false (default) → read-only preview, nothing written to DB.
                            Returns full voter data from both rolls for UI comparison.
    store=true            → full analysis + writes to SIR_* collections.

    Accepted fields:
      voterid      — EPIC / Voter ID
      firstName    — first name  (joined with lastName)
      lastName     — last name   (optional, can be empty)
      name         — full name   (alternative to firstName/lastName)
      relationName — relative / father / husband name (used as fallback lookup key)
      houseNumber  — house number (used in lookup + flood check)
      wardNumber, boothNo, serialNumber — metadata only
      store        — bool, default false
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    # ── Parse inputs ──────────────────────────────────────────────────────────
    # Accept either 'name' (from live-check panel) or firstName+lastName (from survey form)
    name = _norm(
        body.get('name', '')
        or (body.get('firstName', '') + ' ' + body.get('lastName', '')).strip()
    )
    voterid  = _norm(body.get('voterid', ''))
    relation = _norm(body.get('relationName', '') or body.get('relation', ''))
    house    = _norm(body.get('houseNumber', ''))
    ward     = body.get('wardNumber', '')
    booth    = str(body.get('boothNo', ''))
    serial   = body.get('serialNumber', '')
    do_store = bool(body.get('store', False))

    db = get_db()

    # Cache check (read-only preview only — not for store=true calls)
    _sir_cache_key = (name, voterid, house, relation)
    if not do_store:
        _cached_data = _sir_cache_get(_sir_cache_key)
        if _cached_data is not None:
            return JsonResponse(_cached_data)

    if do_store:
        sir = _run_sir_analysis(voterid, name, house, ward, booth, serial, relation, db=db)
        return JsonResponse({'success': True, **sir})

    # ── Read-only preview (no DB writes) ──────────────────────────────────────
    col_2025 = db['2025']
    col_2002 = get_survey_db()['2002']  # 2002 roll lives on the _SURVEY_URL cluster

    # ── Pre-compute name tokens and prefix variants ─────────────────────────────────────────
    # Split name into individual tokens used by all 4 parallel phases.
    # Filter out single-char initials (e.g. "A." or "K") from token list since
    # they produce too many false positives in a contains search.
    _name_tokens_list = [t for t in (name.split() if name else []) if len(t) >= 2]
    _name_tok         = _name_tokens_list[0] if _name_tokens_list else ''
    _name_prefixes    = _gen_prefixes(_name_tok) if _name_tok else ()

    _PROJ_25 = {'Name':1,'Relation Name':1,'Epic NO':1,'House No':1,'Gender':1,'Age':1,'Booth No':1,'Part No':1}
    _PROJ_02 = {'Voter Name':1,'Name':1,'Relative Name':1,'Relation Name':1,
                'House / Flat No':1,'House No':1,'Voter ID / EPIC No':1,'Epic NO':1,
                'Gender':1,'Age':1,'Booth No':1,'Part No':1,'Serial No':1}

    # ── Phase 1+2: confirmed-match lookups ────────────────────────────────────
    # Skip confirmed-match lookup when ONLY name is provided (no EPIC, no house,
    # no relation). In that case there are too many candidates to pick one —
    # we return 100 similar records instead and let the user choose.
    _name_only_search     = bool(name     and not voterid and not house and not relation)
    # Relation-only: only relation provided, nothing else — confirmed-match lookups
    # can't pin a single voter, so skip them and rely on similarity scoring instead.
    _relation_only_search = bool(relation and not name   and not voterid and not house)

    _res = [None, None]
    def _t25(): _res[0] = (None if (_name_only_search or _relation_only_search) else _find_voter_in_2025(col_2025, voterid, name, house, relation))
    def _t02(): _res[1] = (None if (_name_only_search or _relation_only_search) else _find_voter_in_2002(col_2002, voterid, name, house, relation))

    # ── Phase 3: fetch ALL 2002 candidates – token-aware contains + intersection ────────
    _raw02 = []
    def _t_sugg02():
        try:
            seen = set()
            def _add(cur):
                for d in cur:
                    oid = str(d.get('_id',''))
                    if oid not in seen: seen.add(oid); _raw02.append(d)

            # a) EPIC exact
            if voterid:
                _add(col_2002.find({'$or':[{'Voter ID / EPIC No':voterid},{'Epic NO':voterid}]}, _PROJ_02).limit(5))

            # b) House exact + prefix
            if house:
                _add(col_2002.find({'$or':[{'House / Flat No':house},{'House No':house}]}, _PROJ_02).limit(60))
                h_pfx = {'$regex':f'^{re.escape(house)}','$options':'i'}
                _add(col_2002.find({'$or':[{'House / Flat No':h_pfx},{'House No':h_pfx}]}, _PROJ_02).limit(60))

            if _name_tokens_list:
                # c) Single-token search: contains each token anywhere in name
                #    This catches "AKSHAYA RAJESH", "B RAJESH BALIGA" etc.
                _tok_lim = 500 if _name_only_search else 200
                for tok in _name_tokens_list:
                    rx = {'$regex': re.escape(tok), '$options': 'i'}
                    _add(col_2002.find({'$or':[{'Voter Name':rx},{'Name':rx}]}, _PROJ_02).limit(_tok_lim))

                # d) Multi-token AND: all tokens must appear somewhere in the name
                #    "RAJESH SHETTY" -> Name contains RAJESH AND Name contains SHETTY
                #    Produces the most relevant results for multi-word queries
                if len(_name_tokens_list) >= 2:
                    and_clauses = []
                    for tok in _name_tokens_list:
                        rx = {'$regex': re.escape(tok), '$options': 'i'}
                        and_clauses.append({'$or':[{'Voter Name':rx},{'Name':rx}]})
                    _add(col_2002.find({'$and': and_clauses}, _PROJ_02).limit(500))

                # e) Phonetic prefix variants (original fallback for transliteration)
                if _name_tok:
                    clauses = []
                    for p in _name_prefixes:
                        rx = {'$regex':f'^{re.escape(p)}','$options':'i'}
                        clauses.append({'Voter Name':rx}); clauses.append({'Name':rx})
                    _add(col_2002.find({'$or':clauses}, _PROJ_02).limit(500))

            # f) Relation prefix — greatly expanded for relation-only searches
            if relation and len(relation) >= 2:
                frt = relation.split()[0]
                rpfx = {'$regex':f'^{re.escape(frt[:min(5,len(frt))])}','$options':'i'}
                _rel_lim = 500 if _relation_only_search else 100
                _add(col_2002.find({'$or':[{'Relative Name':rpfx},{'Relation Name':rpfx}]}, _PROJ_02).limit(_rel_lim))
                # For relation-only: also fetch all tokens of the relation name individually
                if _relation_only_search:
                    for _rtok in relation.split():
                        if len(_rtok) >= 3:
                            _rx = {'$regex': re.escape(_rtok), '$options': 'i'}
                            _add(col_2002.find({'$or':[{'Relative Name':_rx},{'Relation Name':_rx}]}, _PROJ_02).limit(200))
        except Exception:
            pass

    # ── Phase 4: fetch ALL 2025 similar candidates – token-aware contains + intersection ────
    _raw25 = []
    def _t_sim25():
        try:
            seen = set()
            def _add(cur):
                for d in cur:
                    oid = str(d.get('_id',''))
                    if oid not in seen: seen.add(oid); _raw25.append(bson_clean(d))

            if voterid:
                _add(col_2025.find({'Epic NO':voterid}, _PROJ_25).limit(5))

            if house:
                _add(col_2025.find({'House No':house}, _PROJ_25).limit(60))
                h_pfx = {'$regex':f'^{re.escape(house)}','$options':'i'}
                _add(col_2025.find({'House No':h_pfx}, _PROJ_25).limit(60))

            if _name_tokens_list:
                # c) Contains search for each token — catches mid-name occurrences
                _tok_lim25 = 500 if _name_only_search else 200
                for tok in _name_tokens_list:
                    rx = {'$regex': re.escape(tok), '$options': 'i'}
                    _add(col_2025.find({'Name': rx}, _PROJ_25).limit(_tok_lim25))

                # d) Multi-token AND intersection — highest precision for multi-word queries
                if len(_name_tokens_list) >= 2:
                    and_clauses = [{'Name':{'$regex':re.escape(tok),'$options':'i'}} for tok in _name_tokens_list]
                    _add(col_2025.find({'$and': and_clauses}, _PROJ_25).limit(500))

                # e) Phonetic prefix variants fallback
                if _name_tok:
                    clauses = [{'Name':{'$regex':f'^{re.escape(p)}','$options':'i'}} for p in _name_prefixes]
                    _add(col_2025.find({'$or':clauses}, _PROJ_25).limit(500))

            if relation and len(relation) >= 3:
                frt = relation.split()[0]
                rpfx = {'$regex':f'^{re.escape(frt[:min(5,len(frt))])}','$options':'i'}
                _rel_lim25 = 500 if _relation_only_search else 100
                _add(col_2025.find({'Relation Name':rpfx}, _PROJ_25).limit(_rel_lim25))
                # For relation-only: also fetch per-token contains matches
                if _relation_only_search:
                    for _rtok in relation.split():
                        if len(_rtok) >= 3:
                            _rx = {'$regex': re.escape(_rtok), '$options': 'i'}
                            _add(col_2025.find({'Relation Name': _rx}, _PROJ_25).limit(200))
        except Exception:
            pass

    # Launch all 4 phases in parallel
    _ta = threading.Thread(target=_t25,      daemon=True)
    _tb = threading.Thread(target=_t02,      daemon=True)
    _tc = threading.Thread(target=_t_sugg02, daemon=True)
    _td = threading.Thread(target=_t_sim25,  daemon=True)
    _ta.start(); _tb.start(); _tc.start(); _td.start()
    _ta.join();  _tb.join();  _tc.join();  _td.join()

    r25 = _flat_2025(_res[0])
    r02 = _flat_2002(_res[1])

    in_2025 = bool(r25)
    in_2002 = bool(r02)
    results = []
    changes = []

    if in_2025 and not in_2002:
        results.append({'category': 'NEW_ADDITION', 'label': 'New Addition',
                        'color': '#22d3ee', 'icon': '➕',
                        'detail': 'Voter appears in 2025 but was absent from 2002.'})

    elif in_2002 and not in_2025:
        results.append({'category': 'DELETION', 'label': 'Deletion',
                        'color': '#ef4444', 'icon': '🗑️',
                        'detail': 'Voter was in 2002 but removed from 2025.'})

    elif in_2025 and in_2002:
        for field, v02, v25 in [
            ('Name',     r02['name'],     r25['name']),
            ('Relation', r02['relation'], r25['relation']),
            ('House No', r02['house'],    r25['house']),
            ('Gender',   r02['gender'],   r25['gender']),
        ]:
            if v02 and v25 and v02 != v25:
                changes.append({'field': field, 'from': v02, 'to': v25})
        try:
            a25, a02 = int(r25['age']), int(r02['age'])
            diff = abs(a25 - (a02 + 23))
            if diff > 5:
                changes.append({
                    'field': 'Age', 'from': str(a02), 'to': str(a25),
                    'note': 'Expected ~{} in 2025, got {} (Δ{} yrs)'.format(a02 + 23, a25, diff)
                })
        except (ValueError, TypeError):
            pass

        if changes:
            results.append({'category': 'MODIFICATION', 'label': 'Modification',
                            'color': '#f59e0b', 'icon': '✏️',
                            'detail': '{} field(s) changed between rolls.'.format(len(changes)),
                            'changes': changes})
        else:
            results.append({'category': 'RETAINED', 'label': 'Long-term Voter',
                            'color': '#10b981', 'icon': '✓',
                            'detail': 'Voter is consistently registered in both 2002 and 2025 rolls — 23-year continuous voter.'})
    else:
        if _name_only_search:
            results.append({'category': 'NAME_SEARCH', 'label': 'Name Search',
                            'color': '#6366f1', 'icon': '🔍',
                            'detail': 'Showing all records matching this name. Add House No or EPIC for an exact match.'})
        elif _relation_only_search:
            results.append({'category': 'NAME_SEARCH', 'label': 'Relation Search',
                            'color': '#6366f1', 'icon': '🔍',
                            'detail': 'Showing all records with this relative name. Add Voter Name or House No for an exact match.'})
        else:
            results.append({'category': 'NOT_FOUND', 'label': 'Unregistered / Not Traced',
                            'color': '#6b7fa0', 'icon': '?',
                            'detail': 'Voter not found in either roll. May be unregistered, new to the area, or try different spelling.'})

    # ── Anomaly flags ─────────────────────────────────────────────────────────
    suspicious = []
    if voterid:
        prefix = _epic_prefix(voterid)
        if prefix and prefix not in _KA_PREFIXES:
            suspicious.append({
                'flag': 'OUT_OF_STATE_EPIC', 'label': 'Out-of-State EPIC',
                'detail': 'Prefix "{}" is not a recognised Karnataka EPIC code.'.format(prefix),
                'value': voterid,
            })
        dup = col_2025.count_documents({'Epic NO': voterid})
        if dup > 1:
            suspicious.append({
                'flag': 'DUPLICATE_EPIC', 'label': 'Duplicate EPIC',
                'detail': 'EPIC "{}" appears {} times in the 2025 roll.'.format(voterid, dup),
                'value': dup,
            })
    if house:
        t25 = col_2025.count_documents({'House No': house})
        t02 = col_2002.count_documents({'House / Flat No': house})
        net = t25 - t02
        if net > 5:
            suspicious.append({
                'flag': 'HOUSE_FLOOD', 'label': 'House Overcrowding',
                'detail': 'House {}: 2002 had {}, 2025 has {} (+{} entries).'.format(house, t02, t25, net),
                'value': net,
            })

    def _token_coverage(tokens, candidate_name):
        """How many search tokens appear (as substring) in the candidate name."""
        cn = candidate_name.upper()
        return sum(1 for t in tokens if t.upper() in cn)

    # ── Score suggestions_2002 from pre-fetched _raw02 ───────────────────────────
    has_name  = bool(name)
    has_house = bool(house)
    has_rel   = bool(relation)
    has_epic  = bool(voterid)

    suggestions_2002 = []
    _scored02 = []
    for doc in _raw02:
        flat = _flat_2002(doc)
        n_sc = _name_score(name, flat['name'])         if has_name else 0.0
        r_sc = _name_score(relation, flat['relation']) if has_rel  else 0.0
        h_ok = (flat['house'].upper() == house.upper()) if has_house else False
        e_ok = bool(has_epic and flat['voterid'] and flat['voterid'].upper() == voterid.upper())

        # Token coverage: how many search tokens appear in the candidate name
        cov02 = _token_coverage(_name_tokens_list, flat['name']) if (_name_tokens_list and has_name) else 0
        total_toks02 = len(_name_tokens_list)
        full_cov02 = (total_toks02 > 0 and cov02 == total_toks02)
        coverage_bonus02 = 15.0 if (total_toks02 > 1 and full_cov02) else 0.0

        # Composite relevance score
        if has_name and has_house and has_rel:
            comp = 0.55*n_sc + 0.25*r_sc + 0.20*(100.0 if h_ok else 0.0) + coverage_bonus02
        elif has_name and has_house:
            comp = 0.70*n_sc + 0.30*(100.0 if h_ok else 0.0) + coverage_bonus02
        elif has_name and has_rel:
            comp = 0.60*n_sc + 0.40*r_sc + coverage_bonus02
        elif has_name:
            comp = min(100.0, n_sc + coverage_bonus02)
        elif has_house:
            comp = 100.0
        elif has_rel:
            comp = r_sc
        else:
            comp = 100.0 if e_ok else 0.0
        if e_ok: comp = max(comp, 95.0)

        # Gate: must have at least partial token coverage, EPIC match, or house match
        if has_name and n_sc < 20 and cov02 == 0 and not e_ok and not h_ok: continue
        # Relation-only gate: accept anything with even partial relation similarity
        _rel_gate = 20 if _relation_only_search else 30
        if has_rel and not has_name and r_sc < _rel_gate and not e_ok: continue

        matched_by = []
        if e_ok:                                          matched_by.append('voterid')
        if has_name and (n_sc >= 60 or full_cov02):       matched_by.append('name')
        elif has_name and cov02 > 0:                      matched_by.append('partial')
        if has_house and h_ok:                            matched_by.append('house')
        # For relation-only lower the threshold so results surface even for transliteration variants
        _rel_match_threshold = 35 if _relation_only_search else 60
        if has_rel   and r_sc >= _rel_match_threshold:    matched_by.append('relation')

        _scored02.append({
            'comp': comp, 'flat': flat, 'doc': doc,
            'field_scores': {
                'name':     round(n_sc) if has_name  else 0,
                'relation': round(r_sc) if has_rel   else 0,
                'house':    100 if h_ok and has_house else 0,
                'voterid':  100 if e_ok else 0,
            },
            'matched_by': matched_by,
        })

    _scored02.sort(key=lambda x: (-len([f for f in x['matched_by'] if f != 'partial']), -x['comp']))
    _seen_sigs02 = set()
    for item in _scored02[:300]:
        f   = item['flat']
        doc = item['doc']
        sig = (f['name'], f['house'])
        if sig in _seen_sigs02: continue
        _seen_sigs02.add(sig)
        suggestions_2002.append({
            'name':         f['name'],
            'relation':     f['relation'],
            'house':        f['house'],
            'gender':       f['gender'],
            'age':          f['age'],
            'voterid':      f['voterid'],
            'booth':        str(doc.get('Booth No', doc.get('Part No',''))).strip(),
            'serial':       str(doc.get('Serial No','')).strip(),
            'score':        round(item['comp']),
            'source':       'mongodb',
            'field_scores': item['field_scores'],
            'matched_by':   item['matched_by'],
        })

    suggestions_2002.sort(key=lambda x: (-len([f for f in x.get('matched_by',[]) if f != 'partial']), -x['score']))
    suggestions_2002 = suggestions_2002[:300]

    # ── Score similar_2025 from pre-fetched _raw25 ────────────────────────────────────
    similar_2025 = []
    _seen25_epics = {r25.get('voterid','')} if in_2025 else set()
    _conf25_epic  = r25.get('voterid','') if in_2025 else ''

    def _flags25(rn, rr, rh, re_):
        flags = []
        if voterid and re_ and voterid.upper() == re_.upper():
            flags.append('voterid')
        if name and len(name) >= 2:
            full_sc = _name_score(name, rn)
            # Token coverage: every search token found in candidate name
            cov = _token_coverage(_name_tokens_list, rn) if _name_tokens_list else 0
            total_toks = len(_name_tokens_list)
            if full_sc >= 60 or (total_toks > 0 and cov == total_toks):
                # All tokens found OR fuzzy score good: mark as 'name' match
                flags.append('name')
            elif total_toks > 0 and cov > 0:
                # Partial token coverage: at least one token matched
                flags.append('partial')
        if house and rh and (rh.upper() == house.upper() or rh.upper().startswith(house.upper())):
            flags.append('house')
        if relation and len(relation) >= 2:
            # For relation-only searches use a lower threshold (35) so transliteration
            # variants like VAMANA / VAMAN don't fall below the gate entirely.
            _rel_threshold = 35 if _relation_only_search else 60
            if _name_score(relation, rr) >= _rel_threshold:
                flags.append('relation')
        return flags

    _scored25 = []
    for d in _raw25:
        rn  = _norm(d.get('Name',''))
        rr  = _norm(d.get('Relation Name',''))
        rh  = _norm(d.get('House No',''))
        re_ = _norm(d.get('Epic NO',''))
        flags = _flags25(rn, rr, rh, re_)
        if not flags: continue
        n_sc25 = _name_score(name, rn)     if name     else 0.0
        r_sc25 = _name_score(relation, rr) if relation else 0.0
        # Boost score for full token coverage (all search words found in name)
        cov25 = _token_coverage(_name_tokens_list, rn) if _name_tokens_list else 0
        total_toks25 = len(_name_tokens_list)
        coverage_bonus = 15.0 if (total_toks25 > 1 and cov25 == total_toks25) else 0.0
        if name and relation:
            _c25 = 0.60*n_sc25 + 0.40*r_sc25 + coverage_bonus
        elif name:
            _c25 = min(100.0, n_sc25 + coverage_bonus)
        elif relation:
            _c25 = r_sc25
        else:
            _c25 = 100.0
        # Downrank partial matches so clean matches surface first
        if 'name' not in flags and 'partial' in flags:
            _c25 = min(_c25, 55.0)
        _scored25.append((len([f for f in flags if f != 'partial']), _c25, {
            'name': rn, 'relation': rr, 'house': rh, 'voterid': re_,
            'gender': _norm(d.get('Gender','')),
            'age':    str(d.get('Age','')).strip(),
            'booth':  str(d.get('Booth No','')).strip(),
            'part':   str(d.get('Part No','')).strip(),
            'score':  round(min(100.0, _c25)),
            'matched_by': flags,
        }))

    _scored25.sort(key=lambda x: (-x[0], -x[1]))
    for _, _, rec in _scored25:
        epic = rec['voterid']
        if epic and epic in _seen25_epics: continue
        if _conf25_epic and epic == _conf25_epic: continue
        _seen25_epics.add(epic)
        similar_2025.append(rec)
        if len(similar_2025) >= 300: break

    _response_data = {
        'success':    True,
        'results':    results,
        'suspicious': suspicious,
        'changes':    changes,
        'stored':     False,
        'in_2025':    in_2025,
        'in_2002':    in_2002,
        'similar_2025': similar_2025,
        'suggestions_2002': suggestions_2002,
        'record_2002': {
            'name':     r02.get('name',     ''),
            'relation': r02.get('relation', ''),
            'house':    r02.get('house',    ''),
            'gender':   r02.get('gender',   ''),
            'age':      r02.get('age',      ''),
            'voterid':  r02.get('voterid',  ''),
            'booth':    r02.get('booth',    ''),
        } if in_2002 else {},
        'record_2025': {
            'name':     r25.get('name',     ''),
            'relation': r25.get('relation', ''),
            'house':    r25.get('house',    ''),
            'gender':   r25.get('gender',   ''),
            'age':      r25.get('age',      ''),
            'voterid':  r25.get('voterid',  ''),
            'booth':    r25.get('booth',    ''),
            'ward':     r25.get('ward',     ''),
        } if in_2025 else {},
    }
    # Cache the result — persists to MongoDB so it survives server restarts/sleep
    _sir_cache_set(_sir_cache_key, _response_data)
    return JsonResponse(_response_data)


@require_http_methods(['GET'])
def api_sir_records(request):
    db       = get_db()
    category = request.GET.get('category', 'ALL')
    page     = max(1, int(request.GET.get('page', 1)))
    limit, skip = 50, (page - 1) * 50

    col_map = {
        'NEW_ADDITION': 'SIR_NewAdditions',
        'NEW':          'SIR_NewAdditions',
        'DELETION':     'SIR_Deleted',
        'DELETED':      'SIR_Deleted',
        'MODIFICATION': 'SIR_Modified',
        'MODIFIED':     'SIR_Modified',
        'SUSPICIOUS':   'SIR_Suspicious',
        'RETAINED':     'SIR_Retained',
        'NOT_FOUND':    'SIR_NotFound',
    }

    if category in col_map:
        col   = db[col_map[category]]
        total = col.count_documents(base_filter)
        docs  = [bson_clean(d) for d in col.find().skip(skip).limit(limit).sort('surveyed_at', -1)]
        return JsonResponse({'success': True, 'category': category,
                             'records': docs, 'total': total, 'page': page})

    counts  = {k: db[v].count_documents({}) for k, v in col_map.items()}
    samples = {k: [bson_clean(d) for d in db[v].find().limit(5).sort('surveyed_at', -1)]
               for k, v in col_map.items()}
    return JsonResponse({'success': True, 'category': 'ALL',
                         'counts': counts, 'samples': samples,
                         'total': sum(counts.values())})


@csrf_exempt
@require_http_methods(['POST'])
def api_sir_suggest(request):
    """Fuzzy Excel search — uses cached DataFrame + O(1) house index."""
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    q_name    = (body.get('name', '')        or '').strip().upper()
    q_house   = (body.get('houseNumber', '') or '').strip().upper()
    q_rel     = (body.get('relationName', '') or '').strip().upper()
    q_voterid = (body.get('voterid', '')     or '').strip().upper()

    if not q_name and not q_house and not q_voterid:
        return JsonResponse({'success': True, 'suggestions': []})

    df, cx, hidx = _get_xlsx()
    if df is None:
        return JsonResponse({'success': False, 'message': '2002_new_.xlsx not loaded'}, status=503)

    CN, CR = cx.get('name'), cx.get('rel')
    CH, CE = cx.get('house'), cx.get('epic')
    CG, CA = cx.get('gender'), cx.get('age')
    W = {CN: 3.0, CR: 2.0, CH: 1.5}

    # EPIC exact match — O(1) via vectorised compare, no scoring needed
    if q_voterid and CE:
        exact = df[df[CE].str.upper() == q_voterid]
        if not exact.empty:
            r = exact.iloc[0]
            return JsonResponse({'success': True, 'suggestions': [{
                'name': str(r.get(CN,'')), 'relation': str(r.get(CR,'')),
                'house': str(r.get(CH,'')), 'gender': str(r.get(CG,'')) if CG else '',
                'age': str(r.get(CA,'')) if CA else '', 'voterid': str(r.get(CE,'')),
                'score': 100, 'field_scores': {'name':100,'relation':100,'house':100},
            }]})

    # O(1) house lookup via pre-built index
    if q_house and hidx:
        row_indices = hidx.get(q_house, [])
        subset = df.iloc[row_indices] if row_indices else df
    else:
        subset = df

    query_cols = {}
    if q_name  and CN: query_cols[CN] = q_name
    if q_house and CH: query_cols[CH] = q_house
    if q_rel   and CR: query_cols[CR] = q_rel

    rows_scored = []
    for _, row in subset.iterrows():
        fs, tw, ws = {}, 0.0, 0.0
        for col, qv in query_cols.items():
            cell = str(row.get(col, '')).strip().upper()
            w    = W.get(col, 1.0)
            s    = _name_score(qv, cell)
            fs[col] = round(s); tw += w; ws += s * w
        comp = ws / tw if tw else 0.0
        if fs.get(CN, 100) < 40: continue
        rows_scored.append({'_r': row, 'c': comp, 'fs': fs})
        if comp >= 97: break

    rows_scored.sort(key=lambda x: x['c'], reverse=True)
    suggestions = []
    for item in rows_scored[:5]:
        r, fs = item['_r'], item['fs']
        suggestions.append({
            'name':     str(r.get(CN,'')), 'relation': str(r.get(CR,'')),
            'house':    str(r.get(CH,'')), 'gender':   str(r.get(CG,'')) if CG else '',
            'age':      str(r.get(CA,'')) if CA else '', 'voterid': str(r.get(CE,'')) if CE else '',
            'score':    round(item['c']),
            'field_scores': {'name': fs.get(CN,0), 'relation': fs.get(CR,0), 'house': fs.get(CH,0)},
        })
    return JsonResponse({'success': True, 'suggestions': suggestions})

@require_http_methods(['GET'])
def api_sir_stats(request):
    db        = get_db()
    survey_db = get_survey_db()
    voters_2002 = db['2002'].count_documents({})
    voters_2025 = db['2025'].count_documents({})
    return JsonResponse({'success': True,
        'new_additions':  survey_db['SIR_NewAdditions'].count_documents({}),
        'deletions':      survey_db['SIR_Deleted'].count_documents({}),
        'modifications':  survey_db['SIR_Modified'].count_documents({}),
        'suspicious':     survey_db['SIR_Suspicious'].count_documents({}),
        'retained':       survey_db['SIR_Retained'].count_documents({}),
        'not_found':      survey_db['SIR_NotFound'].count_documents({}),
        'voters_2002':    voters_2002,
        'voters_2025':    voters_2025,
        'db_2002_status': 'ok' if voters_2002 > 0 else 'empty — place 2002.xlsx in project root and call /api/sync-2002/',
        'db_2025_status': 'ok' if voters_2025 > 0 else 'empty — upload voter list first',
    })


@require_http_methods(['GET'])
def api_sir_data(request):
    db        = get_db()
    survey_db = get_survey_db()   # SIR_* collections live here
    category = request.GET.get('category', 'ALL').upper()
    page     = max(1, int(request.GET.get('page', 1)))
    limit    = 50
    skip     = (page - 1) * limit
    # Optional filters
    ward_filter  = request.GET.get('ward',  '').strip()
    booth_filter = request.GET.get('booth', '').strip()

    col_map = {
        'NEW':        'SIR_NewAdditions',
        'DELETED':    'SIR_Deleted',
        'MODIFIED':   'SIR_Modified',
        'SUSPICIOUS': 'SIR_Suspicious',
        'RETAINED':   'SIR_Retained',
        'NOT_FOUND':  'SIR_NotFound',
    }

    # Build optional mongo filter for ward/booth
    base_filter = {}
    if ward_filter:
        base_filter['$or'] = [{'ward': ward_filter}, {'ward_number': ward_filter}]
    if booth_filter:
        bf = {'$or': [{'booth': booth_filter}, {'booth_no': booth_filter}]}
        base_filter = {'$and': [base_filter, bf]} if base_filter else bf

    summary = {
        'NEW':        survey_db['SIR_NewAdditions'].count_documents(base_filter),
        'DELETED':    survey_db['SIR_Deleted'].count_documents(base_filter),
        'MODIFIED':   survey_db['SIR_Modified'].count_documents(base_filter),
        'SUSPICIOUS': survey_db['SIR_Suspicious'].count_documents(base_filter),
        'RETAINED':   survey_db['SIR_Retained'].count_documents(base_filter),
        'NOT_FOUND':  survey_db['SIR_NotFound'].count_documents(base_filter),
    }
    summary['TOTAL'] = sum(summary.values())

    if category in col_map:
        col   = survey_db[col_map[category]]
        total = col.count_documents({})
        raw   = col.find(base_filter).sort('surveyed_at', -1).skip(skip).limit(limit)
        records = [_sir_to_frontend(bson_clean(d), category) for d in raw]
        return JsonResponse({'success': True, 'summary': summary,
                             'records': records, 'total': total})

    all_records = []
    for cat, cname in col_map.items():
        for d in survey_db[cname].find(base_filter).sort('surveyed_at', -1).limit(20):
            all_records.append(_sir_to_frontend(bson_clean(d), cat))
    all_records.sort(key=lambda r: r.get('Time_stamp', ''), reverse=True)
    total = sum(summary[k] for k in col_map)
    return JsonResponse({'success': True, 'summary': summary,
                         'records': all_records[:limit], 'total': total})


def _sir_to_frontend(doc, category):
    r25 = doc.get('voter_record_2025') or {}
    r02 = doc.get('voter_record_2002') or {}

    def _g(d, *keys):
        for k in keys:
            if d.get(k):
                return str(d[k])
        return ''

    name    = (doc.get('name')    or doc.get('survey_name')
               or _g(r25, 'Name')
               or _g(r02, 'Voter Name') or '')
    voterid = (doc.get('voterid') or doc.get('survey_voterid')
               or _g(r25, 'Epic NO')
               or _g(r02, 'Voter ID / EPIC No') or '')
    house   = (doc.get('house')   or doc.get('survey_house')
               or _g(r25, 'House No')
               or _g(r02, 'House / Flat No') or '')

    details = doc.get('note') or doc.get('flag_detail') or ''
    changes = doc.get('changes', [])
    if changes:
        details += ' | ' + '; '.join(
            f"{c['field']}: {c['from']} → {c['to']}" + (f" ({c['note']})" if c.get('note') else '')
            for c in changes
        )

    flags = list(doc.get('flags', []))
    if doc.get('flag_label'):
        flags.insert(0, f"{doc['flag_label']}: {doc.get('flag_detail', '')}")

    ts = doc.get('surveyed_at') or doc.get('Time_stamp') or ''
    if hasattr(ts, 'isoformat'):
        ts = ts.isoformat()

    return {
        'category':     category,
        'name':         name,
        'voterid':      voterid,
        'house_no':     house,
        'ward_number':  doc.get('ward') or doc.get('ward_number') or '',
        'booth_no':     doc.get('booth') or doc.get('booth_no') or '',
        'relation':     (doc.get('relation')
                         or _g(r25, 'Relation Name')
                         or _g(r02, 'Relative Name (English)', 'Relative Name (Kannada)') or ''),
        'details':      details,
        'found_2002':   bool(r02 or doc.get('found_2002')),
        'found_2025':   bool(r25 or doc.get('found_2025')),
        'name_2002':     doc.get('name_2002')     or _g(r02, 'Voter Name (English)', 'Voter Name (Kannada)'),
        'age_2002':      doc.get('age_2002')      or _g(r02, 'Age'),
        'house_2002':    doc.get('house_2002')    or _g(r02, 'House No'),
        'relation_2002': doc.get('relation_2002') or _g(r02, 'Relative Name (English)', 'Relative Name (Kannada)'),
        'name_2025':     doc.get('name_2025')     or _g(r25, 'Name'),
        'age_2025':      doc.get('age_2025')      or _g(r25, 'Age'),
        'house_2025':    doc.get('house_2025')    or _g(r25, 'House No'),
        'relation_2025': doc.get('relation_2025') or _g(r25, 'Relation Name'),
        'flags':         flags,
        'changes':       changes,
        'Time_stamp':    ts,
        'voter_record_2025': r25,
        'voter_record_2002': r02,
    }


@csrf_exempt
@require_http_methods(['POST'])
def api_sir_bulk(request):
    """
    Bulk SIR pass over both voter rolls stored in MongoDB.
      Phase 1 — iterate SurveyDataBase.2025  (catches NEW additions, MODIFICATIONS, floods)
      Phase 2 — iterate SurveyDataBase.2002  (catches DELETIONS — in 2002 but gone from 2025)
    Both phases call _run_sir_analysis() which writes to SIR_* collections.
    """
    db        = get_db()
    col_2025  = db['2025']
    col_2002  = get_survey_db()['2002']  # 2002 roll lives on the _SURVEY_URL cluster
    processed = 0
    errors    = 0

    # ── Phase 1: 2025 roll ────────────────────────────────────────────────────
    cursor = col_2025.find({}, {
        'Epic NO':       1,
        'Name':          1,
        'Relation Name': 1,
        'House No':      1,
        'Part No':       1,
        'Booth No':      1,
    }).batch_size(500)

    for doc in cursor:
        try:
            d = _flat_2025(doc)
            _run_sir_analysis(
                voterid = d['voterid'],
                name    = d['name'],
                house   = d['house'],
                ward    = d['ward'],
                booth   = d['booth'],
                serial  = '',
                db      = db,
            )
            processed += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f'[SIR bulk P1] Error: {e}')

    # ── Phase 2: 2002 roll (detect deletions) ─────────────────────────────────
    cursor2 = col_2002.find({}, {
        'Voter ID / EPIC No': 1,
        'Voter Name':         1,
        'Relative Name':      1,
        'House / Flat No':    1,
    }).batch_size(500)

    for doc in cursor2:
        try:
            d = _flat_2002(doc)
            if not d['name'] and not d['voterid']:
                continue   # skip blank docs
            _run_sir_analysis(
                voterid  = d['voterid'],
                name     = d['name'],
                house    = d['house'],
                ward     = '',
                booth    = '',
                serial   = '',
                relation = d['relation'],
                db       = db,
            )
            processed += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f'[SIR bulk P2] Error: {e}')

    return JsonResponse({'success': True, 'processed': processed,
                         'errors': errors, 'total': processed + errors})


# ─── UPDATE VOTER ─────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST', 'PUT', 'PATCH'])
def api_update_voter(request):
    """
    Update any fields of a voter document in MainB.CollDB.

    Body (JSON):
      { "voter_id": "ABC1234567", "Voter Name": "New Name", "Age": "35", ... }
    """
    try:
        body     = json.loads(request.body)
        voter_id = (body.pop('voter_id', '') or '').strip()

        if not voter_id:
            return JsonResponse({'success': False, 'message': 'voter_id is required'}, status=400)

        if not body:
            return JsonResponse({'success': False, 'message': 'No fields to update'}, status=400)

        db   = get_db1()
        coll = db['CollDB']

        result = coll.update_one(
            {'$or': [{'VoterID': voter_id}, {'Voter ID': voter_id}]},
            {'$set': body}
        )

        if result.matched_count == 0:
            return JsonResponse({'success': False, 'message': f'No voter found with ID: {voter_id}'}, status=404)

        return JsonResponse({'success': True, 'updated': result.modified_count})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON body'}, status=400)
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'Update failed: {str(exc)}'}, status=500)


# ─── UPDATE SURVEY ────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST', 'PUT', 'PATCH'])
def api_update_survey(request):
    """
    Update any fields of a survey record in SurveyDataBase.SurveyRecords.

    NOTE: SurveyRecords is a MongoDB time-series collection.
    Time-series collections do NOT support update_one() with $set.
    Strategy: fetch the full doc → merge changed fields → delete old → reinsert merged.

    Body (JSON):
      { "record_id": "64a1b2c3d4e5f6a7b8c9d0e1", "firstName": "Ravi", ... }
    """
    try:
        body      = json.loads(request.body)
        record_id = (body.pop('record_id', '') or '').strip()

        if not record_id:
            return JsonResponse({'success': False, 'message': 'record_id is required'}, status=400)

        if not body:
            return JsonResponse({'success': False, 'message': 'No fields to update'}, status=400)

        # Remove _id from the update payload — it must not be overwritten
        body.pop('_id', None)

        try:
            oid = ObjectId(record_id)
        except Exception:
            return JsonResponse({'success': False, 'message': f'Invalid record_id: {record_id}'}, status=400)

        db   = get_survey_db()
        coll = db['SurveyRecords']

        # ── Step 1: fetch the existing document ───────────────────────────────
        existing = coll.find_one({'_id': oid})
        if not existing:
            return JsonResponse({'success': False, 'message': f'No record found with id: {record_id}'}, status=404)

        # ── Step 2: merge — existing fields + incoming changes ────────────────
        merged = dict(existing)   # full original doc including _id
        for k, v in body.items():
            merged[k] = v         # overwrite only changed fields

        # ── Step 3: delete the old document ───────────────────────────────────
        del_result = coll.delete_one({'_id': oid})
        if del_result.deleted_count == 0:
            return JsonResponse({'success': False, 'message': 'Failed to delete old record during update'}, status=500)

        # ── Step 4: reinsert the merged document ──────────────────────────────
        # Restore original _id so it keeps the same identity
        merged['_id'] = oid
        merged['Time_stamp'] = existing.get('Time_stamp', datetime.utcnow())   # preserve original timestamp

        coll.insert_one(merged)

        return JsonResponse({'success': True, 'updated': 1})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON body'}, status=400)
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': f'Update failed: {str(exc)}'}, status=500)


# ─── WARD INFO ────────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_wards(request):
    # Derived from module-level WARD_FULL_DATA — single source of truth
    wards = sorted(
        [{'name': v['name'].title(), 'number': k, 'booths': v['booths']}
         for k, v in WARD_FULL_DATA.items()],
        key=lambda x: x['number']
    )
    return JsonResponse({'success': True, 'wards': wards})


# ─── VOTER UPLOAD ─────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST', 'OPTIONS'])
def api_upload_voter_list(request):
    if request.method == 'OPTIONS':
        return JsonResponse({})

    try:
        uploaded = request.FILES.get('file')
        if not uploaded:
            return JsonResponse({'success': False, 'message': 'No file uploaded.'}, status=400)

        name = uploaded.name.lower()
        print(f"Reading file: {uploaded.name}, size: {uploaded.size/1024/1024:.1f} MB")

        import io
        file_bytes = uploaded.read()

        if name.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file_bytes), low_memory=False, dtype=str)
        elif name.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str, engine='openpyxl')
        else:
            return JsonResponse({'success': False, 'message': 'Unsupported format. Use CSV or .xlsx'}, status=400)

        if df.empty:
            return JsonResponse({'success': False, 'message': 'File is empty.'}, status=400)

        df = df.where(pd.notnull(df), None)
        records = df.to_dict(orient='records')
        total   = len(records)
        print(f"Total records to insert: {total:,}")

        db         = get_db()
        coll       = db['2025']
        BATCH_SIZE = 5000
        inserted   = 0

        for i in range(0, total, BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            coll.insert_many(batch, ordered=False)
            inserted += len(batch)
            print(f"  Inserted {inserted:,}/{total:,} records...")

        print(f"Upload complete: {inserted:,} records inserted.")
        return JsonResponse({
            'success': True,
            'message': f'Successfully uploaded {inserted:,} records into VoterList.',
            'total':   inserted,
        })

    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'Upload error: {str(exc)}'
        }, status=500)


# ─── 2002 VOTER LIST — XLSX LOADER ───────────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST'])
def api_sync_2002_from_sheet(request):
    """
    Load the 2002 voter list from the local xlsx file (backend/2002.xlsx) and
    upsert every row into SurveyDataBase.2002.
    Safe to call multiple times — uses upsert on Epic NO so duplicates are never created.

    Body (JSON, all optional):
      {
        "clear_first": false,   // if true, drops and rebuilds the collection (re-sync)
        "xlsx_path":   "..."    // override the default path (absolute path on server)
      }

    Returns:
      { "success": true, "inserted": N, "updated": N, "skipped": N, "total": N }
    """
    try:
        body = json.loads(request.body) if request.body else {}
    except Exception:
        body = {}

    clear_first = body.get('clear_first', False)
    xlsx_path   = body.get('xlsx_path', _XLSX_2002_PATH)

    # ── 1. Read xlsx ──────────────────────────────────────────────────────────
    if not _os.path.exists(xlsx_path):
        return JsonResponse({
            'success': False,
            'message': (
                f'2002.xlsx not found at: {xlsx_path}. '
                'Place the file in the Django project root (same folder as manage.py) '
                'and name it "2002.xlsx".'
            )
        }, status=404)

    try:
        df = pd.read_excel(xlsx_path, dtype=str, engine='openpyxl')
        df = df.where(pd.notnull(df), '')   # replace NaN with ''
        print(f'[2002 Load] xlsx has {len(df)} rows, columns: {list(df.columns)}')
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'Failed to read xlsx: {str(exc)}'
        }, status=500)

    if df.empty:
        return JsonResponse({
            'success': False,
            'message': 'xlsx file is empty — no rows to import.'
        }, status=400)

    # ── 2. Map columns → MongoDB field names ──────────────────────────────────
    def _map_row(row_dict):
        doc = {}
        for xlsx_col, mongo_field in _COL_MAP_2002.items():
            val = row_dict.get(xlsx_col, '')
            doc[mongo_field] = str(val).strip() if val not in (None, '') else ''
        return doc

    # ── 3. Connect to MongoDB ─────────────────────────────────────────────────
    db   = get_db()   # SurveyDataBase
    coll = db['2002']

    if clear_first:
        coll.drop()
        print('[2002 Load] Dropped existing 2002 collection — rebuilding from scratch')

    # ── 4. Upsert rows ────────────────────────────────────────────────────────
    # Key = Epic NO.  Rows without an EPIC are keyed by Voter Name (English) + House No.
    inserted = 0
    updated  = 0
    skipped  = 0

    for _, row in df.iterrows():
        doc = _map_row(row.to_dict())

        # Skip entirely blank rows
        if not any(doc.values()):
            skipped += 1
            continue

        # Build upsert filter
        epic = doc.get('Epic NO', '').strip().upper()
        if epic:
            filt = {'Epic NO': epic}
        else:
            name  = doc.get('Voter Name (English)', '').strip()
            house = doc.get('House No', '').strip()
            if not name:
                skipped += 1
                continue
            filt = {'Voter Name (English)': name, 'House No': house}

        # Normalise Epic NO to uppercase
        if epic:
            doc['Epic NO'] = epic

        result = coll.update_one(filt, {'$set': doc}, upsert=True)
        if result.upserted_id:
            inserted += 1
        elif result.modified_count:
            updated += 1
        else:
            skipped += 1  # already identical in DB

    # ── 5. Create indexes for fast SIR lookups ────────────────────────────────
    try:
        coll.create_index('Epic NO',              background=True)
        coll.create_index('Voter Name (English)', background=True)
        coll.create_index('House No',             background=True)
    except Exception:
        pass   # best-effort

    total = inserted + updated + skipped
    msg   = (
        f'Load complete: {inserted} inserted, {updated} updated, '
        f'{skipped} skipped (blank/unchanged). Total rows: {total}.'
    )
    print(f'[2002 Load] {msg}')

    return JsonResponse({
        'success':    True,
        'message':    msg,
        'inserted':   inserted,
        'updated':    updated,
        'skipped':    skipped,
        'total':      total,
        'collection': 'SurveyDataBase.2002',
        'source':     xlsx_path,
    })


@require_http_methods(['GET'])
def api_2002_status(request):
    """
    Quick status check — how many 2002 voters are in MongoDB,
    and a sample record so you can verify the column mapping is correct.
    """
    db   = get_db()
    coll = db['2002']

    count  = coll.count_documents({})
    sample = bson_clean(coll.find_one({})) if count > 0 else None

    # Count records that have a usable Epic NO
    with_epic = coll.count_documents({'Epic NO': {'$ne': ''}})

    return JsonResponse({
        'success':    True,
        'total_docs': count,
        'with_epic':  with_epic,
        'without_epic': count - with_epic,
        'status':     'ok' if count > 0 else 'empty — run /api/sync-2002/ to load from 2002.xlsx',
        'sample_doc': sample,
        'collection': 'SurveyDataBase.2002',
    })



# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN — User approval panel  (MLA / PA only)
# ═══════════════════════════════════════════════════════════════════════════════

@require_http_methods(['GET'])
@_require_superuser
def api_admin_users(request):
    """
    GET /api/admin/users/
    Returns all users grouped by status.
    Query params: ?status=pending|approved|rejected|all (default=all)
    """
    status_filter = request.GET.get('status', 'all').strip().lower()
    query = {} if status_filter == 'all' else {'status': status_filter}

    users = list(get_db()['UserReg'].find(query, {
        'Password': 0,  # never return password
    }).sort('Time_stamp', -1))

    result = []
    for u in users:
        result.append({
            '_id':         str(u['_id']),
            'username':    u.get('Username', ''),
            'email':       u.get('Email', ''),
            'role':        u.get('role',    'booth_worker'),
            'ward':        u.get('ward',    ''),
            'booth':       u.get('booth',   ''),
            'status':      u.get('status',  'pending'),
            'requestedAt': u.get('requestedAt', u.get('Time_stamp', '')).isoformat() if hasattr(u.get('requestedAt', u.get('Time_stamp', '')), 'isoformat') else str(u.get('requestedAt', '')),
            'approvedAt':  u.get('approvedAt', '').isoformat() if hasattr(u.get('approvedAt', ''), 'isoformat') else str(u.get('approvedAt', '') or ''),
            'approvedBy':  u.get('approvedBy', ''),
            'disabledAt':  u.get('disabledAt', '').isoformat() if hasattr(u.get('disabledAt', ''), 'isoformat') else str(u.get('disabledAt', '') or ''),
            'disabledBy':  u.get('disabledBy', ''),
            'disableReason': u.get('disableReason', ''),
        })

    pending  = [u for u in result if u['status'] == 'pending']
    approved = [u for u in result if u['status'] == 'approved']
    rejected = [u for u in result if u['status'] == 'rejected']
    disabled = [u for u in result if u['status'] == 'disabled']
    return JsonResponse({
        'success':  True,
        'pending':  pending,
        'approved': approved,
        'rejected': rejected,
        'disabled': disabled,
        'total':    len(result),
    })


@csrf_exempt
@require_http_methods(['POST'])
@_require_superuser
def api_admin_approve(request):
    """
    POST /api/admin/approve/
    Body: { "email": "user@domain.com" }
    Approves a pending user and optionally updates their role/ward/booth.
    """
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    target_email = body.get('email', '').strip().lower()
    if not target_email:
        return JsonResponse({'success': False, 'message': 'email is required.'}, status=400)

    admin = _user_from_request(request)
    update = {
        'status':     'approved',
        'approvedAt': datetime.utcnow(),
        'approvedBy': admin['email'],
    }
    # Optionally update role/ward/booth at approval time
    if body.get('role')  and body['role']  in ROLES_ALL:  update['role']  = body['role']
    if body.get('ward'):   update['ward']  = body['ward']
    if body.get('booth'):  update['booth'] = body['booth']

    result = get_db()['UserReg'].update_one({'Email': target_email}, {'$set': update})
    if result.matched_count == 0:
        return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

    _invalidate_user_cache(target_email)
    return JsonResponse({'success': True, 'message': f'{target_email} approved.'})


@csrf_exempt
@require_http_methods(['POST'])
@_require_superuser
def api_admin_reject(request):
    """
    POST /api/admin/reject/
    Body: { "email": "user@domain.com", "reason": "..." }
    """
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    target_email = body.get('email', '').strip().lower()
    if not target_email:
        return JsonResponse({'success': False, 'message': 'email is required.'}, status=400)

    admin = _user_from_request(request)
    result = get_db()['UserReg'].update_one({'Email': target_email}, {'$set': {
        'status':     'rejected',
        'rejectedAt': datetime.utcnow(),
        'rejectedBy': admin['email'],
        'rejectReason': body.get('reason', ''),
    }})
    if result.matched_count == 0:
        return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

    _invalidate_user_cache(target_email)
    return JsonResponse({'success': True, 'message': f'{target_email} rejected.'})


@csrf_exempt
@require_http_methods(['POST'])
@_require_superuser
def api_admin_update_role(request):
    """
    POST /api/admin/update-role/
    Body: { "email": "...", "role": "...", "ward": "...", "booth": "..." }
    Update a user's role/ward/booth after approval.
    """
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    target_email = body.get('email', '').strip().lower()
    new_role     = body.get('role', '').strip().lower()
    if not target_email or not new_role:
        return JsonResponse({'success': False, 'message': 'email and role are required.'}, status=400)
    if new_role not in ROLES_ALL:
        return JsonResponse({'success': False, 'message': f'Invalid role.'}, status=400)

    update = {'role': new_role, 'ward': body.get('ward', ''), 'booth': body.get('booth', '')}
    result = get_db()['UserReg'].update_one({'Email': target_email}, {'$set': update})
    if result.matched_count == 0:
        return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

    _invalidate_user_cache(target_email)
    return JsonResponse({'success': True, 'message': f'Role updated for {target_email}.'})


@csrf_exempt
@require_http_methods(['POST'])
@_require_superuser
def api_admin_disable(request):
    """
    POST /api/admin/disable/
    Body: { "email": "user@domain.com", "reason": "..." }
    Immediately suspends an approved user — they cannot log in or call any
    protected endpoint until re-enabled.  Their role/ward/booth are preserved
    so re-enabling is seamless.
    """
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    target_email = body.get('email', '').strip().lower()
    if not target_email:
        return JsonResponse({'success': False, 'message': 'email is required.'}, status=400)

    # Prevent admins from disabling other admins
    target = get_db()['UserReg'].find_one({'Email': target_email}, {'role': 1, 'status': 1})
    if not target:
        return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)
    if target.get('role') in ('mla', 'pa'):
        return JsonResponse({'success': False, 'message': 'Cannot disable an admin account.'}, status=403)
    if target.get('status') == 'disabled':
        return JsonResponse({'success': False, 'message': 'User is already disabled.'}, status=400)

    admin = _user_from_request(request)
    result = get_db()['UserReg'].update_one({'Email': target_email}, {'$set': {
        'status':        'disabled',
        'disabledAt':    datetime.utcnow(),
        'disabledBy':    admin['email'],
        'disableReason': body.get('reason', ''),
    }})

    _invalidate_user_cache(target_email)
    return JsonResponse({'success': True, 'message': f'Access disabled for {target_email}.'})


@csrf_exempt
@require_http_methods(['POST'])
@_require_superuser
def api_admin_enable(request):
    """
    POST /api/admin/enable/
    Body: { "email": "user@domain.com" }
    Restores a previously disabled user back to 'approved' status.
    Their original role/ward/booth are unchanged.
    """
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    target_email = body.get('email', '').strip().lower()
    if not target_email:
        return JsonResponse({'success': False, 'message': 'email is required.'}, status=400)

    target = get_db()['UserReg'].find_one({'Email': target_email}, {'status': 1})
    if not target:
        return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)
    if target.get('status') != 'disabled':
        return JsonResponse({'success': False, 'message': 'User is not currently disabled.'}, status=400)

    admin = _user_from_request(request)
    result = get_db()['UserReg'].update_one({'Email': target_email}, {'$set': {
        'status':      'approved',
        'enabledAt':   datetime.utcnow(),
        'enabledBy':   admin['email'],
        # Clear the disable fields so history is clean
        'disabledAt':  None,
        'disabledBy':  '',
        'disableReason': '',
    }})

    _invalidate_user_cache(target_email)
    return JsonResponse({'success': True, 'message': f'Access restored for {target_email}.'})


# ─── SESSION CHECK ────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_me(request):
    user = _user_from_request(request)
    if user:
        return JsonResponse({
            'loggedIn': True,
            'username': user['username'],
            'email':    user['email'],
            'role':     user.get('role',   'booth_worker'),
            'ward':     user.get('ward',   ''),
            'booth':    user.get('booth',  ''),
            'status':   user.get('status', 'pending'),
        })
    return JsonResponse({'loggedIn': False}, status=401)

# ─────────────────────────────────────────────────────────────────────────────
# ML INTELLIGENCE — NewQueryStack1 endpoints
# Returns all query objects (with predictedContext) for SWOT display in React.
# ─────────────────────────────────────────────────────────────────────────────

CONSTITUENCY_NAME   = "Mangalore South"
CONSTITUENCY_NUMBER = 175
ML_CHUNK_SIZE       = 500   # must match predict_query_stack.py

def _get_ml_db():
    """Return SurveyDataBase from the survey cluster (same cluster as NewQueryStack1)."""
    return _get_survey_client()["SurveyDataBase"]


def _reassemble_chunks(col, filter_q: dict) -> list:
    """Pull all chunks matching filter_q, sort by chunkIndex, return flat list.
    NewQueryStack1 stores rows under 'records'; legacy stacks used 'queries'.
    """
    chunks = list(col.find(filter_q, {"_id": 0}).sort("chunkIndex", 1))
    rows = []
    for chunk in chunks:
        rows.extend(chunk.get("records") or chunk.get("queries") or [])
    return rows


def _sanitise_queries(queries: list) -> list:
    """
    Prepare query objects for JSON serialisation.
    - Remove datetime fields (predictedAt)
    - Keep: routeKey, columns, query, count, percentage, label, labelBand, predictedContext
    """
    out = []
    for q in queries:
        entry = {
            "routeKey":        q.get("routeKey", ""),
            "columns":         q.get("columns", []),
            "query":           q.get("query", {}),
            "count":           q.get("count", 0),
            "percentage":      round(float(q.get("percentage", 0)), 2),
            "label":           q.get("label", ""),
            "labelBand":       q.get("labelBand", ""),
            "predictedContext": {k: str(v) for k, v in
                                 q.get("predictedContext", {}).items()
                                 if not isinstance(v, datetime)},
        }
        out.append(entry)
    return out


@require_http_methods(["GET"])
def api_ml_constituency_swot(request):
    """
    GET /api/ml/constituency-swot/
    Returns all predicted queries for Mangalore South from NewQueryStack1.
    NewQueryStack1 stores all constituency records across chunked documents;
    no constituencyNumber/Name filter — fetch all chunks and return flat list.
    """
    user = _user_from_request(request)
    if not user:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        db      = _get_ml_db()
        col     = db["NewQueryStack1"]
        queries = _reassemble_chunks(col, {})   # no filter — all chunks belong to this constituency
        return JsonResponse({
            "scope":               "constituency",
            "constituencyName":    CONSTITUENCY_NAME,
            "constituencyNumber":  CONSTITUENCY_NUMBER,
            "totalQueries":        len(queries),
            "queries":             _sanitise_queries(queries),
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)




# ─────────────────────────────────────────────────────────────────────────────
# AI INSIGHT ENDPOINTS — Anthropic-powered analysis for SWOT queries
# ─────────────────────────────────────────────────────────────────────────────

_ANTHROPIC_CLIENT = None

def _get_anthropic():
    """Init Anthropic client once and reuse. anthropic is imported at module
    level so it is fully loaded before any request arrives."""
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is None:
        import os
        api_key = (
            getattr(settings, 'ANTHROPIC_API_KEY', None)
            or os.environ.get('ANTHROPIC_API_KEY', '')
            or None
        )
        if not api_key:
            raise RuntimeError(
                'ANTHROPIC_API_KEY is not set. '
                'Add it in your Render dashboard: Environment -> Add Environment Variable -> '
                'Key: ANTHROPIC_API_KEY, Value: your-key'
            )
        _ANTHROPIC_CLIENT = _anthropic_mod.Anthropic(api_key=api_key)
    return _ANTHROPIC_CLIENT


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def api_ai_query_insight(request):
    """
    POST /api/ai/query-insight/
    Body: {
        "query": {...},          # filter dict  e.g. {"economicStatus":"APL"}
        "columns": [...],        # dimension names
        "count": 3950,           # voter count
        "percentage": 51.0,
        "label": "Dominant",
        "routeKey": "...",
        "predictedContext": {...}
    }

    Returns a structured JSON insight from Claude claude-sonnet-4-20250514.
    Response schema:
    {
        "headline": str,
        "summary": str,
        "keyFigures": [...],
        "barChart": {...},
        "swotBreakdown": {...},
        "recommendation": str,
        "riskLevel": str,
        "riskColor": str
    }
    """
    # ── Handle CORS preflight ──────────────────────────────────────────────────
    if request.method == "OPTIONS":
        return _ai_cors(request, JsonResponse({}))

    user = _user_from_request(request)
    if not user:
        return _ai_cors(request, JsonResponse({"error": "Unauthorized"}, status=401))

    try:
        body = json.loads(request.body)
    except Exception:
        return _ai_cors(request, JsonResponse({"error": "Invalid JSON body."}, status=400))

    query_obj    = body.get("query", {})
    columns      = body.get("columns", [])
    count        = body.get("count", 0)
    percentage   = body.get("percentage", 0)
    label        = body.get("label", "")
    route_key    = body.get("routeKey", "")
    pred_ctx     = body.get("predictedContext", {})

    filter_tags = ", ".join(f"{k}: {v}" for k, v in query_obj.items() if v and v != "Unknown")

    user_prompt = (
        f"Voter segment analysis for Mangalore South (Constituency 175, Karnataka):\n"
        f"- Demographic filters: {filter_tags or 'All voters'}\n"
        f"- Segment size: {count:,} voters ({percentage:.1f}% of constituency)\n"
        f"- SWOT classification: {label}\n"
        f"- Column dimensions: {', '.join(columns) or route_key}\n"
        f"- All predicted political contexts: {json.dumps(pred_ctx)}"
    )

    system_prompt = (
        "You are a senior political analyst for Mangalore South constituency (Karnataka, India). "
        "Analyse the given voter segment and return a JSON object ONLY (no markdown, no extra text) with this exact structure:\n"
        '{"headline":"One punchy 8-12 word insight title",'
        '"summary":"2-3 sentence plain-language explanation",'
        '"keyFigures":['
        '{"label":"Segment Size","value":"<X voters>","note":"short context"},'
        '{"label":"Share of Constituency","value":"<X%>","note":"short context"},'
        '{"label":"Political Lean","value":"BJP/INC/Swing","note":"brief reason"},'
        '{"label":"Impact Level","value":"<label>","note":"Dominant/Major/Moderate/Minor"}],'
        '"barChart":{"title":"Estimated Vote Split",'
        '"bars":['
        '{"party":"BJP","pct":<0-100>,"color":"#fb923c"},'
        '{"party":"INC","pct":<0-100>,"color":"#f87171"},'
        '{"party":"Others","pct":<0-100>,"color":"#6b7280"}]},'
        '"swotBreakdown":{"title":"Context-wise SWOT Signal",'
        '"items":['
        '{"ctx":"Economic","signal":"S/W/O/T/N","color":"#10b981","note":"1 line"},'
        '{"ctx":"Health","signal":"S/W/O/T/N","color":"#22d3ee","note":"1 line"},'
        '{"ctx":"Political","signal":"S/W/O/T/N","color":"#f59e0b","note":"1 line"}]},'
        '"suggestedSchemes":['
        '{"name":"Exact scheme name from catalogue","ministry":"Ministry name","relevance":"Why this segment qualifies","impact":"High/Medium/Low","url":"exact myscheme.gov.in URL from catalogue","perBeneficiaryCost":<integer from cost table>,"budgetBreakdown":"e.g. Rs6,000 x 3,956 beneficiaries = Rs23.7 L"}'
        '],'
        '"budgetRequired":{"totalINR":<sum of all perBeneficiaryCost x beneficiary count>,"displayLabel":"RsX.X Cr or RsX.X L","note":"Estimated annual government outlay for this voter segment"},'
        '"recommendation":"One specific actionable recommendation for 2028",'
        '"riskLevel":"Low/Medium/High/Critical",'
        '"riskColor":"#10b981 or #f59e0b or #fb923c or #f87171"}\n\n'

        "SCHEME CATALOGUE — 85 verified schemes from system database. "
        "Pick 2-4 that match the segment filters exactly. Use exact Name + URL below.\n\n"

        "AGRICULTURE/FARMER:\n"
        "Pradhan Mantri Kisan Samman Nidhi | APL+BPL farmers, all religions | perBeneficiaryCost=6000 (Rs2000x3 fixed) | https://www.myscheme.gov.in/schemes/pm-kisan\n"
        "Pradhan Mantri Fasal Bima Yojna | BPL farmers, all religions | perBeneficiaryCost=4500 (avg premium subsidy/farmer/season) | https://www.myscheme.gov.in/schemes/pmfby\n"
        "Krushy Aranya Protsaha Yojane | APL+BPL SC/ST/OBC farmers | perBeneficiaryCost=5000 (agroforestry incentive) | https://www.myscheme.gov.in/schemes/kapy\n"
        "Pradhan Mantri Matsya Sampada Yojana | BPL fisherfolk, all religions | perBeneficiaryCost=20000 (avg subsidy for equipment) | https://www.myscheme.gov.in/schemes/pmmsy\n"
        "Livestock Health and Diseases Control | APL+BPL livestock holders | perBeneficiaryCost=2000 (vaccination+treatment/household/yr) | https://www.myscheme.gov.in/schemes/lhadc\n"
        "Nekar Samman Yojana | BPL weavers, all religions | perBeneficiaryCost=6000 (Rs500/month x 12) | https://www.myscheme.gov.in/schemes/nsy\n\n"

        "HOUSING:\n"
        "Pradhan Mantri Awas Yojana - Urban | BPL only, renting/no own home, all religions | perBeneficiaryCost=150000 (avg central+state subsidy — NOT full cost) | https://www.myscheme.gov.in/schemes/pmay-u\n\n"

        "HEALTH/INSURANCE:\n"
        "Niramaya Health Insurance Scheme | APL+BPL DifferentlyAbled=Yes, Diseased | perBeneficiaryCost=500 (annual premium subsidy) | https://www.myscheme.gov.in/schemes/nhis\n"
        "Pradhan Mantri Jeevan Jyoti Bima Yojana | BPL age 18+, all religions | perBeneficiaryCost=436 (annual premium fully subsidised) | https://www.myscheme.gov.in/schemes/pmjjby\n"
        "Pradhan Mantri Suraksha Bima Yojana | BPL Diseased age 18+, all religions | perBeneficiaryCost=20 (annual premium Rs20 govt bears) | https://www.myscheme.gov.in/schemes/pmsby\n"
        "Pradhan Mantri Garib Kalyan Anna Yojana | APL+BPL Diseased, all religions | perBeneficiaryCost=3600 (5kg grain/month x Rs60 x 12) | https://www.myscheme.gov.in/schemes/pm-gkay\n\n"

        "WOMEN & CHILD:\n"
        "Pradhan Mantri Matru Vandana Yojana | BPL pregnant/lactating women, all religions | perBeneficiaryCost=5000 (one-time maternity benefit fixed) | https://www.myscheme.gov.in/schemes/pmmvy\n"
        "Thayi Bhagya Scheme | BPL women Karnataka | perBeneficiaryCost=5000 (institutional delivery incentive) | https://www.myscheme.gov.in/schemes/thayi-bhagya\n"
        "Bhagyalaxmi Scheme | BPL girl child at birth Karnataka | perBeneficiaryCost=19300 (annualised Rs19,300 bond value) | https://www.myscheme.gov.in/schemes/bys\n"
        "Scheme For Adolescent Girls | BPL girls age 11-18, all religions | perBeneficiaryCost=4500 (nutrition+IFA+health per girl/yr) | https://www.myscheme.gov.in/schemes/sag\n"
        "Indira Gandhi National Widow Pension Scheme | BPL widows, all religions | perBeneficiaryCost=3600 (Rs300/month x 12 central share) | https://www.myscheme.gov.in/schemes/ignwps\n"
        "One Stop Centre | APL+BPL women in distress, all religions | perBeneficiaryCost=2000 (avg service cost/beneficiary) | https://www.myscheme.gov.in/schemes/osc\n"
        "Incentive For The Sc Widow Remarriage | BPL SC widow women, Hindu | perBeneficiaryCost=50000 (one-time on remarriage) | https://www.myscheme.gov.in/schemes/iscwr\n"
        "Incentive For The Simple Marriage | BPL SC Hindu | perBeneficiaryCost=25000 (one-time inter-caste marriage incentive) | https://www.myscheme.gov.in/schemes/iftsm\n\n"

        "EMPLOYMENT/ENTREPRENEURSHIP:\n"
        "PM Street Vendors AtmaNirbhar Nidhi (PM SVANidhi) | BPL urban street vendors, all religions | perBeneficiaryCost=10000 (first tranche working capital) | https://www.myscheme.gov.in/schemes/pm-svanidhi\n"
        "Prime Minister's Employment Generation Programme | APL+BPL unemployed educated, all religions | perBeneficiaryCost=90000 (avg 15-35% subsidy on Rs3L avg project) | https://www.myscheme.gov.in/schemes/pmegp\n"
        "PM Vishwakarma | APL+BPL traditional artisans OBC Hindu | perBeneficiaryCost=15000 (toolkit Rs15,000 + skill stipend) | https://www.myscheme.gov.in/schemes/pmv\n"
        "Self Employment Scheme | APL+BPL Muslim/Christian/Jain/Buddhist/Sikh ONLY | perBeneficiaryCost=50000 (avg loan per minority beneficiary) | https://www.myscheme.gov.in/schemes/ses\n"
        "Udyogini Scheme | BPL women entrepreneurs, all religions | perBeneficiaryCost=30000 (avg subsidy/grant per woman) | https://www.myscheme.gov.in/schemes/us\n"
        "Shrama Shakthi Scheme | APL+BPL employed Muslim/Christian/Jain/Buddhist/Sikh | perBeneficiaryCost=12000 (avg annual welfare benefit/worker) | https://www.myscheme.gov.in/schemes/sss\n"
        "Airavata Scheme | APL+BPL SC/ST Hindu | perBeneficiaryCost=40000 (avg subsidy on vehicle/equipment loan) | https://www.myscheme.gov.in/schemes/airavata\n"
        "Subsidy Scheme For Purchase Of Taxi/Goods Vehicle | APL+BPL ST community | perBeneficiaryCost=50000 (avg vehicle subsidy) | https://www.myscheme.gov.in/schemes/subsidy-scheme-for-taxi\n"
        "Prerana (micro Credit Finance) Scheme | APL+BPL micro-entrepreneurs, all religions | perBeneficiaryCost=25000 (avg micro-credit loan) | https://www.myscheme.gov.in/schemes/prerana\n"
        "Direct Loans For Business Enterprise | APL+BPL Muslim/Christian/Jain/Buddhist/Sikh ONLY | perBeneficiaryCost=100000 (avg loan) | https://www.myscheme.gov.in/schemes/dlbe\n"
        "Samruddhi Scheme | BPL SC/ST educated women | perBeneficiaryCost=20000 (avg grant+training) | https://www.myscheme.gov.in/schemes/samruddhischeme\n"
        "Unnati Scheme | APL+BPL all religions | perBeneficiaryCost=8000 (avg skill training cost) | https://www.myscheme.gov.in/schemes/unnati\n"
        "Ganga Kalyana Scheme | BPL Muslim/Christian/Jain/Buddhist/Sikh farmers ONLY | perBeneficiaryCost=75000 (avg borewell/pump subsidy) | https://www.myscheme.gov.in/schemes/gks\n\n"

        "SKILL DEVELOPMENT:\n"
        "Pradhan Mantri Kaushal Vikas Yojana - Short Term Training | APL+BPL unemployed, all religions | perBeneficiaryCost=8000 (avg govt training cost/candidate) | https://www.myscheme.gov.in/schemes/pmkvy-stt\n"
        "Entrepreneurship and Skill Development Programme | BPL employed/retired, all religions | perBeneficiaryCost=6000 (avg MSME skill training cost) | https://www.myscheme.gov.in/schemes/esdp\n\n"

        "EDUCATION/SCHOLARSHIP:\n"
        "Pre Matric Scholarship For Scheduled Tribe Students | BPL SC/ST students age <18 | perBeneficiaryCost=7000 (avg annual scholarship) | https://www.myscheme.gov.in/schemes/pre-st\n"
        "Post-Matric Scholarship for SC students | BPL SC students, all religions | perBeneficiaryCost=12000 (avg annual scholarship) | https://www.myscheme.gov.in/schemes/pmsfss\n"
        "Centrally Sponsored Scheme of Post-Matric Scholarship for OBC Students | APL+BPL OBC female students | perBeneficiaryCost=10000 (avg annual OBC scholarship) | https://www.myscheme.gov.in/schemes/csspostmsossi\n"
        "Pre Matric Scholarship For Students With Disabilities | APL+BPL DifferentlyAbled=Yes students | perBeneficiaryCost=9000 (avg annual scholarship) | https://www.myscheme.gov.in/schemes/pre-dis\n"
        "Top Class Education For Students With Disabilities | APL+BPL DifferentlyAbled=Yes | perBeneficiaryCost=75000 (fees+allowances top institution) | https://www.myscheme.gov.in/schemes/tce-swd\n"
        "Post Graduate Indira Gandhi Scholarship For Single Girl Child | APL+BPL single girl PG | perBeneficiaryCost=36200 (Rs3,100/month x 12) | https://www.myscheme.gov.in/schemes/pg-igssgc\n"
        "Pragati Scholarship Scheme For Girl Students (Technical Diploma) | APL+BPL girl students tech diploma | perBeneficiaryCost=30000 (Rs30,000/year fixed) | https://www.myscheme.gov.in/schemes/psgs-dip\n"
        "Vidyasiri food And Accommodation Scholarship Scheme | BPL SC/ST/OBC students Hindu | perBeneficiaryCost=18000 (food+accommodation/student/yr) | https://www.myscheme.gov.in/schemes/vfas\n"
        "Free Coaching Scheme for SC and OBC Students | APL+BPL SC/OBC students | perBeneficiaryCost=45000 (avg coaching+stipend/student/yr) | https://www.myscheme.gov.in/schemes/fcssos\n"
        "Padho Pardesh | APL+BPL OBC minority students overseas | perBeneficiaryCost=200000 (avg interest subsidy on education loan) | https://www.myscheme.gov.in/schemes/ppma\n"
        "National Talent Scholarship Undergraduate | BPL merit students, all religions | perBeneficiaryCost=12000 (Rs1,000/month x 12) | https://www.myscheme.gov.in/schemes/nts-ug\n"
        "National Scholarship For Post Graduate Studies | APL ONLY, all religions | perBeneficiaryCost=24000 (Rs2,000/month x 12) | https://www.myscheme.gov.in/schemes/nsfpgs\n"
        "Rajiv Gandhi National Fellowship For Scheduled Caste Candidates | APL+BPL SC research students | perBeneficiaryCost=312000 (JRF Rs31,000/month+HRA avg 2 yrs) | https://www.myscheme.gov.in/schemes/rgnfscc\n"
        "Prabhuddha Overseas Scholarship | APL+BPL SC/ST educated | perBeneficiaryCost=1000000 (overseas tuition+living) | https://www.myscheme.gov.in/schemes/pdos\n"
        "Savitribai Jyotirao Phule Fellowship For Single Girl Child | APL+BPL single girl OBC MPhil/PhD | perBeneficiaryCost=84000 (Rs7,000/month x 12) | https://www.myscheme.gov.in/schemes/sjpfsgc\n"
        "National Scheme Of Incentive To Girls For Secondary Education | BPL girls class 8, all religions | perBeneficiaryCost=3000 (one-time FD at class 8) | https://www.myscheme.gov.in/schemes/nsigse\n"
        "Pre-Matric Scholarships Scheme for Scheduled Castes & Others | APL+BPL SC/OBC students class 9-10 | perBeneficiaryCost=5250 (avg day-scholar scholarship/yr) | https://www.myscheme.gov.in/schemes/pmsssc\n"
        "Education Loan Scheme | APL+BPL OBC/SC/ST students | perBeneficiaryCost=150000 (avg loan — flag as loan) | https://www.myscheme.gov.in/schemes/els\n\n"

        "PENSION/SOCIAL SECURITY:\n"
        "Atal Pension Yojana | BPL unorganised workers educated age 18+, all religions | perBeneficiaryCost=1000 (avg govt co-contribution/yr) | https://www.myscheme.gov.in/schemes/apy\n"
        "Indira Gandhi National Disability Pension Scheme | BPL DifferentlyAbled=Yes, all religions | perBeneficiaryCost=3600 (Rs300/month x 12 central share) | https://www.myscheme.gov.in/schemes/igndps\n"
        "National Family Benefit Scheme | APL+BPL DifferentlyAbled on breadwinner death | perBeneficiaryCost=20000 (one-time lump sum) | https://www.myscheme.gov.in/schemes/nfbs\n"
        "National Pension Scheme For Traders And Self Employed Persons | APL+BPL self-employed SC traders | perBeneficiaryCost=1500 (avg govt co-contribution/yr) | https://www.myscheme.gov.in/schemes/nps-tsep\n\n"

        "DIFFERENTLY ABLED (DifferentlyAbled=Yes ONLY):\n"
        "National Action Plan for Skill Development of Persons with Disabilities | APL+BPL DiffAbled=Yes, all religions | perBeneficiaryCost=10000 (skill training+placement) | https://www.myscheme.gov.in/schemes/nap-sdp\n"
        "Deen Dayal Disabled Rehabilitation Scheme | APL+BPL SC/ST DiffAbled | perBeneficiaryCost=8000 (avg rehab grant/yr) | https://www.myscheme.gov.in/schemes/dddrs\n"
        "Vikaas-Day Care Scheme For Person with Disability Children | APL+BPL OBC/SC DiffAbled children | perBeneficiaryCost=12000 (day-care cost/child/yr) | https://www.myscheme.gov.in/schemes/vdcspds\n\n"

        "ENERGY:\n"
        "PM Surya Ghar: Muft Bijli Yojana | APL+BPL SC community own home | perBeneficiaryCost=78000 (avg central subsidy 2kW rooftop solar) | https://www.myscheme.gov.in/schemes/pmsgmb\n"
        "Pradhan Mantri Ujjwala Yojana | BPL women all religions NEW connection only | perBeneficiaryCost=1600 (one-time cylinder+regulator) | https://www.myscheme.gov.in/schemes/pmuy\n\n"

        "FINANCIAL INCLUSION:\n"
        "Pradhan Mantri Jan Dhan Yojana | APL+BPL ST community | perBeneficiaryCost=2000 (overdraft+RuPay insurance value) | https://www.myscheme.gov.in/schemes/pmjdy\n"
        "Stand-Up India | BPL SC/ST women entrepreneurs | perBeneficiaryCost=1000000 (avg loan Rs10L-1Cr — flag as loan) | https://www.myscheme.gov.in/schemes/sui\n\n"

        "SELECTION RULES — follow strictly:\n"
        "1. Match ALL segment filters before selecting: economicStatus, religion, community, healthStatus, gender, homeType, employmentStatus, differentlyAbled.\n"
        "2. NEVER suggest PMAY-Urban if homeType includes Own (voter already owns home).\n"
        "3. NEVER suggest PM-KISAN unless the segment filters include farmer/agriculture employment.\n"
        "4. NEVER suggest PM SVANidhi unless explicitly urban street vendors.\n"
        "5. NEVER suggest schemes marked Muslim/Christian/Jain/Buddhist/Sikh ONLY for Hindu segments.\n"
        "6. NEVER suggest religion-neutral schemes for segments where the scheme has a religion restriction.\n"
        "7. NEVER suggest disability schemes if DifferentlyAbled=No.\n"
        "8. Select max 4 schemes; prefer highest perBeneficiaryCost that genuinely applies.\n\n"

        "BUDGET FORMAT:\n"
        "budgetBreakdown: 'Rs<cost with commas> x <N> beneficiaries = Rs<total>'\n"
        "  Use RsX.X L for total < 1,00,00,000; RsX.X Cr for total >= 1,00,00,000. Round to 1 decimal.\n"
        "  Example: Rs6,000 x 3,956 beneficiaries = Rs23.7 L\n"
        "budgetRequired.totalINR = exact integer sum of all (perBeneficiaryCost x count).\n"
        "budgetRequired.displayLabel = 'RsX.X Cr' if total >= 1,00,00,000 else 'RsX.X L'.\n"
        "budgetRequired.note = 'Estimated annual government outlay for this voter segment across applicable schemes'."
    )

    try:
        client = _get_anthropic()
        # timeout=25 ensures we fail cleanly before Gunicorn's worker timeout kills the process
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            timeout=35.0,
        )
        raw = "".join(b.text for b in message.content if hasattr(b, "text")).strip()
        # Strip markdown fences if present
        raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
        try:
            insight = json.loads(raw)
        except json.JSONDecodeError:
            insight = {"_raw": raw}
        return _ai_cors(request, JsonResponse({"success": True, "insight": insight}))
    except Exception as exc:
        return _ai_cors(request, JsonResponse({"error": str(exc)}, status=500))


@csrf_exempt
@require_http_methods(["POST"])
def api_ai_birdseye_view(request):
    """
    POST /api/ai/birdseye-view/
    Body: {
        "contextKey": "economic",
        "queries": [... list of sanitised query objects ...],  # from api_ml_constituency_swot
        "totalVoters": 246952   # optional, for context
    }

    Synthesises ALL queries for the selected context into a high-level
    constituency-wide strategic overview with win probability estimate.

    Response schema:
    {
        "headline": str,
        "executiveSummary": str,
        "swotRadar": [...],
        "keyMetrics": [...],
        "trendBars": {...},
        "strategicPillars": [...],
        "winProbability": int,
        "confidenceNote": str
    }
    """
    user = _user_from_request(request)
    if not user:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    ctx_key      = body.get("contextKey", "economic")
    queries      = body.get("queries", [])
    total_voters = body.get("totalVoters", 246952)

    if not queries:
        return JsonResponse({"error": "queries list is required."}, status=400)

    # ── Aggregate stats ─────────────────────────────────────────────────────
    swot_count   = {"Strength": 0, "Weakness": 0, "Opportunity": 0, "Threat": 0, "None": 0}
    label_count  = {}
    filter_freq  = {}

    # Simple label-to-SWOT mapping (mirrors JS ctxToSwot logic)
    _SWOT_MAP = {
        "S": "Strength", "W": "Weakness", "O": "Opportunity", "T": "Threat",
        "Strength": "Strength", "Weakness": "Weakness",
        "Opportunity": "Opportunity", "Threat": "Threat",
    }

    for q in queries:
        raw_ctx = (q.get("predictedContext") or {}).get(ctx_key, "")
        # Extract S/W/O/T tokens from the label string
        found = False
        for token, swot in _SWOT_MAP.items():
            if token in str(raw_ctx):
                swot_count[swot] += 1
                found = True
                break
        if not found:
            swot_count["None"] += 1

        lb = q.get("label", "None")
        label_count[lb] = label_count.get(lb, 0) + 1

        for k, v in (q.get("query") or {}).items():
            if v and v != "Unknown":
                key = f"{k}:{v}"
                filter_freq[key] = filter_freq.get(key, 0) + 1

    top_filters = ", ".join(
        f"{k} ({c}x)" for k, c in
        sorted(filter_freq.items(), key=lambda x: -x[1])[:10]
    )
    total_query_voter_refs = sum(q.get("count", 0) for q in queries)

    user_prompt = (
        f"Mangalore South Constituency (175) — Bird's Eye SWOT Overview\n"
        f"Context analysed: {ctx_key}\n"
        f"Total query groups: {len(queries)}\n"
        f"Total voter-mentions: {total_query_voter_refs:,}\n"
        f"SWOT distribution: Strength={swot_count['Strength']}, "
        f"Weakness={swot_count['Weakness']}, "
        f"Opportunity={swot_count['Opportunity']}, "
        f"Threat={swot_count['Threat']}, "
        f"Unclassified={swot_count['None']}\n"
        f"Impact label distribution: {json.dumps(label_count)}\n"
        f"Most frequent demographic filters: {top_filters}"
    )

    system_prompt = (
        "You are a senior political strategist for Mangalore South constituency. "
        "Provide a comprehensive bird's eye strategic view. "
        "Return ONLY a JSON object (no markdown, no extra text):\n"
        '{"headline":"Strategic overview title (10-15 words)",'
        '"executiveSummary":"3-4 sentence overall picture",'
        '"swotRadar":['
        '{"axis":"Strength","score":<0-100>,"color":"#10b981","note":"1-line reason"},'
        '{"axis":"Weakness","score":<0-100>,"color":"#f87171","note":"1-line reason"},'
        '{"axis":"Opportunity","score":<0-100>,"color":"#22d3ee","note":"1-line reason"},'
        '{"axis":"Threat","score":<0-100>,"color":"#fb923c","note":"1-line reason"}],'
        '"keyMetrics":['
        '{"label":"Dominant Quadrant","value":"...","color":"#10b981"},'
        '{"label":"Query Groups","value":"<N>","color":"#a78bfa"},'
        '{"label":"Voter Reach","value":"<N>","color":"#22d3ee"},'
        '{"label":"Top Risk Factor","value":"short phrase","color":"#f87171"}],'
        '"trendBars":{"title":"SWOT Distribution (% of groups)",'
        '"bars":['
        '{"label":"Strength","pct":<0-100>,"color":"#10b981"},'
        '{"label":"Weakness","pct":<0-100>,"color":"#f87171"},'
        '{"label":"Opportunity","pct":<0-100>,"color":"#22d3ee"},'
        '{"label":"Threat","pct":<0-100>,"color":"#fb923c"}]},'
        '"strategicPillars":['
        '{"title":"Consolidate","body":"What to protect/double down on","color":"#10b981"},'
        '{"title":"Fix","body":"Top weakness to address before 2028","color":"#f87171"},'
        '{"title":"Capitalise","body":"Best opportunity to act on now","color":"#22d3ee"},'
        '{"title":"Neutralise","body":"Most urgent threat to defuse","color":"#fb923c"}],'
        '"winProbability":<0-100>,'
        '"confidenceNote":"1 sentence on data confidence"}'
    )

    try:
        client = _get_anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = "".join(b.text for b in message.content if hasattr(b, "text")).strip()
        raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
        try:
            insight = json.loads(raw)
        except json.JSONDecodeError:
            insight = {"_raw": raw}
        return JsonResponse({"success": True, "insight": insight})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)

    """
    GET /api/ml/ward-swot/?ward=<wardNumber>
    Returns predicted queries for a specific ward from NewQueryStack1.
    Ward-wise is in progress on the frontend; endpoint kept for future use.
    """
    user = _user_from_request(request)
    if not user:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    ward_param = request.GET.get("ward", "").strip()
    if not ward_param:
        return JsonResponse({"error": "ward parameter required"}, status=400)

    try:
        ward_no = int(ward_param)
    except ValueError:
        return JsonResponse({"error": "ward must be an integer"}, status=400)

    try:
        db        = _get_ml_db()
        col       = db["NewQueryStack1"]
        queries   = _reassemble_chunks(col, {"wardNumber": ward_no})
        ward_name = WARD_NUM_TO_NAME.get(ward_no, f"Ward {ward_no}")
        return JsonResponse({
            "scope":        "ward",
            "wardNumber":   ward_no,
            "wardName":     ward_name,
            "totalQueries": len(queries),
            "queries":      _sanitise_queries(queries),
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# ═══════════════════════════════════════════════════════════════════════════════
# SURVEY PROGRESS  — booth-worker progress visible in Admin Panel
# ═══════════════════════════════════════════════════════════════════════════════

@_require_superuser
@require_http_methods(['GET'])
def api_admin_survey_progress(request):
    """
    GET /api/admin/survey-progress/
    Returns per-booth-worker survey completion stats.

    Query params (all optional):
      ?booth=<n>   — filter to a specific booth
      ?ward=<n>    — filter to a specific ward number (returns all workers in that ward)
    """
    db         = get_db()
    survey_db  = get_survey_db()
    survey_col = survey_db['SurveyRecords']
    voter_col  = db['2025']
    user_col   = db['UserReg']

    booth_filter = request.GET.get('booth', '').strip()
    ward_filter  = request.GET.get('ward',  '').strip()

    # ── 1. Fetch all approved booth_workers ──────────────────────────────────
    query = {'role': 'booth_worker', 'status': 'approved'}
    if booth_filter:
        query['booth'] = booth_filter
    if ward_filter:
        try:
            ward_booths = [str(b) for b in WARD_FULL_DATA.get(int(ward_filter), {}).get('booths', [])]
            query['booth'] = {'$in': ward_booths}
        except (ValueError, TypeError):
            pass

    workers = list(user_col.find(query, {'Password': 0}))

    if not workers:
        return JsonResponse({'success': True, 'workers': []})

    # ── 2. Build booth list for aggregation ──────────────────────────────────
    booths_needed = list({str(w.get('booth', '')) for w in workers if w.get('booth')})

    booth_query_vals = []
    for b in booths_needed:
        booth_query_vals.append(b)
        try:
            booth_query_vals.append(int(b))
        except ValueError:
            pass

    # ── 3. Aggregate SurveyRecords per booth ─────────────────────────────────
    survey_pipeline = [
        {'$match': {'boothNumber': {'$in': booth_query_vals}}},
        {'$group': {
            '_id':            {'$toString': '$boothNumber'},
            'votersSurveyed': {'$sum': 1},
            'housesSet':      {'$addToSet': '$houseNumber'},
            'lastSurveyAt':   {'$max': '$Time_stamp'},
        }},
    ]
    survey_stats = {doc['_id']: doc for doc in survey_col.aggregate(survey_pipeline)}

    # ── 4. Aggregate 2025 voter roll per booth ────────────────────────────────
    voter_pipeline = [
        {'$match': {'Part No': {'$in': booth_query_vals}}},
        {'$group': {
            '_id':         {'$toString': '$Part No'},
            'totalVoters': {'$sum': 1},
            'totalHouses': {'$addToSet': '$House No'},
        }},
    ]
    voter_stats = {doc['_id']: doc for doc in voter_col.aggregate(voter_pipeline)}

    # ── 5. Build response ─────────────────────────────────────────────────────
    result = []
    for w in workers:
        booth_str = str(w.get('booth', ''))
        ward_num  = BOOTH_TO_WARD.get(booth_str, '')

        # Look up ward name — try both str and int keys
        ward_name = WARD_NUM_TO_NAME.get(ward_num, '')
        if not ward_name and ward_num.isdigit():
            ward_name = WARD_NUM_TO_NAME.get(int(ward_num), '')

        s = survey_stats.get(booth_str, {})
        v = voter_stats.get(booth_str, {})

        houses_completed = len(s.get('housesSet', []))
        voters_surveyed  = s.get('votersSurveyed', 0)
        total_houses     = len(v.get('totalHouses', []))
        total_voters     = v.get('totalVoters', 0)
        last_at          = s.get('lastSurveyAt')

        houses_pct = round(houses_completed / total_houses * 100, 1) if total_houses else 0
        voters_pct = round(voters_surveyed  / total_voters  * 100, 1) if total_voters  else 0

        result.append({
            'email':           w.get('Email', ''),
            'username':        w.get('Username', ''),
            'boothNumber':     booth_str,
            'wardNumber':      ward_num,
            'wardName':        ward_name,
            'housesCompleted': houses_completed,
            'totalHouses':     total_houses,
            'housesPct':       houses_pct,
            'votersSurveyed':  voters_surveyed,
            'totalVoters':     total_voters,
            'votersPct':       voters_pct,
            'lastSurveyAt':    last_at.isoformat() if hasattr(last_at, 'isoformat') else str(last_at or ''),
        })

    result.sort(key=lambda x: int(x['boothNumber']) if x['boothNumber'].isdigit() else 0)
    return JsonResponse({'success': True, 'workers': result})


# ═══════════════════════════════════════════════════════════════════════════════
# LOCATION TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(['POST'])
def api_location_ping(request):
    """
    POST /api/location/ping/
    Body: { "lat": 12.8762, "lng": 74.8425, "accuracy": 15.0 }
    Stores a location ping in SurveyDataBase.LocationHistory.
    Auth: any approved user.
    """
    user = _user_from_request(request)
    if not user:
        return JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401)
    if not _is_approved(user):
        return JsonResponse({'success': False, 'message': 'Account pending approval.'}, status=403)

    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON.'}, status=400)

    lat      = body.get('lat')
    lng      = body.get('lng')
    accuracy = body.get('accuracy', None)

    if lat is None or lng is None:
        return JsonResponse({'success': False, 'message': 'lat and lng are required.'}, status=400)

    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'lat/lng must be numbers.'}, status=400)

    doc = {
        'email':     user['email'],
        'username':  user['username'],
        'role':      user['role'],
        'booth':     user.get('booth', ''),
        'ward':      user.get('ward',  ''),
        'lat':       lat,
        'lng':       lng,
        'accuracy':  accuracy,
        'timestamp': datetime.utcnow(),
    }

    get_survey_db()['LocationHistory'].insert_one(doc)
    return JsonResponse({'success': True})


@_require_superuser
@require_http_methods(['GET'])
def api_admin_locations(request):
    """
    GET /api/admin/locations/
    Query params:
      ?email=<email>   — filter to one worker
      ?mode=live       — latest ping per worker (default)
      ?mode=history    — all pings for ?email= (requires email)
      ?date=YYYY-MM-DD — filter history to a specific date (UTC)
      ?limit=<n>       — max history records (default 200)
    """
    loc_col  = get_survey_db()['LocationHistory']
    mode     = request.GET.get('mode',  'live').strip().lower()
    email    = request.GET.get('email', '').strip().lower()
    date_str = request.GET.get('date',  '').strip()
    limit    = min(int(request.GET.get('limit', 200)), 1000)

    if mode == 'history':
        if not email:
            return JsonResponse({'success': False, 'message': 'email is required for history mode.'}, status=400)

        match = {'email': email}
        if date_str:
            try:
                day_start = datetime.strptime(date_str, '%Y-%m-%d')
                day_end   = day_start.replace(hour=23, minute=59, second=59)
                match['timestamp'] = {'$gte': day_start, '$lte': day_end}
            except ValueError:
                return JsonResponse({'success': False, 'message': 'date must be YYYY-MM-DD.'}, status=400)

        pings = list(
            loc_col.find(match, {'_id': 0, 'email': 0, 'username': 0, 'role': 0, 'booth': 0, 'ward': 0})
                   .sort('timestamp', -1)
                   .limit(limit)
        )
        pings.reverse()  # oldest first for map path rendering
        for p in pings:
            if hasattr(p.get('timestamp'), 'isoformat'):
                p['timestamp'] = p['timestamp'].isoformat()

        return JsonResponse({'success': True, 'mode': 'history', 'email': email, 'pings': pings})

    # ── Live: latest ping per worker ──────────────────────────────────────────
    match = {'email': email} if email else {}

    pipeline = [
        {'$match': match},
        {'$sort': {'timestamp': -1}},
        {'$group': {
            '_id':       '$email',
            'email':     {'$first': '$email'},
            'username':  {'$first': '$username'},
            'role':      {'$first': '$role'},
            'booth':     {'$first': '$booth'},
            'ward':      {'$first': '$ward'},
            'lat':       {'$first': '$lat'},
            'lng':       {'$first': '$lng'},
            'accuracy':  {'$first': '$accuracy'},
            'timestamp': {'$first': '$timestamp'},
        }},
        {'$sort': {'booth': 1}},
    ]

    workers = list(loc_col.aggregate(pipeline))
    for w in workers:
        w.pop('_id', None)
        if hasattr(w.get('timestamp'), 'isoformat'):
            w['timestamp'] = w['timestamp'].isoformat()

    return JsonResponse({'success': True, 'mode': 'live', 'workers': workers})


@_require_superuser
@require_http_methods(['GET'])
def api_admin_location_dates(request):
    """
    GET /api/admin/location-dates/?email=<email>
    Returns distinct calendar dates on which a worker sent location pings.
    """
    email = request.GET.get('email', '').strip().lower()
    if not email:
        return JsonResponse({'success': False, 'message': 'email is required.'}, status=400)

    loc_col = get_survey_db()['LocationHistory']
    pipeline = [
        {'$match': {'email': email}},
        {'$project': {
            'date': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$timestamp'}}
        }},
        {'$group': {'_id': '$date'}},
        {'$sort': {'_id': -1}},
        {'$limit': 90},
    ]
    dates = [doc['_id'] for doc in loc_col.aggregate(pipeline)]
    return JsonResponse({'success': True, 'dates': dates})


# ═══════════════════════════════════════════════════════════════════════════════
# AI CHAT — Anthropic-powered chat backed by live MongoDB + data folder files
# ═══════════════════════════════════════════════════════════════════════════════
#
# Context budget (claude-sonnet-4-20250514 has 200k token window):
#   MongoDB summaries   : ~15,000 tokens  (always included — 15 collections)
#   Data folder files   : up to ~100,000 tokens via Files API (upload once, reuse)
#   Conversation history: up to 20 turns
#   System prompt text  : ~3,000 tokens
#   AI response         : 4,096 tokens (max_tokens)
#
# File RAG strategy:
#   .xlsx / .xls  — smart chunker: per-sheet metadata headers + clean CSV rows
#                   (replaces flat dump — model knows exactly what each sheet is)
#   .csv          — pandas chunked read, up to _AI_CSV_MAX_ROWS rows
#   .pdf          — PyMuPDF page-by-page, up to _AI_PDF_MAX_PAGES
#   .docx         — python-docx paragraph extraction, full document
#   .txt          — direct read
#
# MongoDB RAG strategy:
#   15 context builders run in PARALLEL via ThreadPoolExecutor
#   Each builder covers one collection with lightweight $facet aggregations
#   Any builder failure is caught and logged — never crashes the request
# ═══════════════════════════════════════════════════════════════════════════════

import io as _io
import os as _os2
import re as _re2
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import fitz as _fitz
    _PYMUPDF_OK = True
except ImportError:
    _PYMUPDF_OK = False

try:
    import docx as _docx_lib
    _DOCX_LIB_OK = True
except ImportError:
    _DOCX_LIB_OK = False

try:
    _AI_BASE_DIR = _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__)))
    _AI_DATA_DIR = _os2.path.join(_AI_BASE_DIR, 'data')
    _os2.makedirs(_AI_DATA_DIR, exist_ok=True)
except Exception:
    _AI_DATA_DIR = '/tmp/ai_data'
    _os2.makedirs(_AI_DATA_DIR, exist_ok=True)

_AI_SUPPORTED_EXTS    = {'.xlsx', '.xls', '.csv', '.pdf', '.docx', '.doc', '.txt'}
_AI_CSV_MAX_ROWS      = 3000
_AI_PDF_MAX_PAGES     = 30
_AI_CHARS_PER_FILE    = 80_000
_AI_TOTAL_CHARS_FILES = 320_000
_AI_MAX_FILES         = 13      # cover all xlsx files in data/

# ── CORS + error helpers ──────────────────────────────────────────────────────

def _ai_cors(request, response):
    origin = request.META.get('HTTP_ORIGIN', '')
    if origin:
        response['Access-Control-Allow-Origin']      = origin
        response['Access-Control-Allow-Credentials'] = 'true'
        response['Access-Control-Allow-Methods']     = 'POST, GET, OPTIONS'
        response['Access-Control-Allow-Headers']     = (
            'Content-Type, Authorization, X-CSRFToken, X-Requested-With'
        )
    return response


def _ai_err(request, msg, status=500):
    print(f'[AI Chat] ERROR {status}: {msg}')
    return _ai_cors(request, JsonResponse({'success': False, 'message': msg}, status=status))


# ── Anthropic client ──────────────────────────────────────────────────────────

def _ai_get_client():
    try:
        api_key = (
            getattr(settings, 'ANTHROPIC_API_KEY', None)
            or _os2.environ.get('ANTHROPIC_API_KEY', '')
        )
        if not api_key:
            return None, 'ANTHROPIC_API_KEY not set in Render environment variables.'
        return _anthropic_mod.Anthropic(api_key=api_key), None
    except Exception as e:
        return None, f'Anthropic client error: {e}'


# ════════════════════════════════════════════════════════════════════════════════
# MONGODB CONTEXT BUILDERS — 15 collections, parallel execution
# ════════════════════════════════════════════════════════════════════════════════

def _safe_count(collection):
    try:
        return collection.estimated_document_count()
    except Exception:
        return 0


# ── Builder 1: 2025 Voter Roll ────────────────────────────────────────────────

def _ai_ctx_voter_roll_summary():
    try:
        db = get_db()
        ward_refs = list(db['WardReference'].find(
            {},
            {'number': 1, 'name': 1, 'totalCount': 1,
             'totalMale': 1, 'totalFemale': 1,
             'totalHindu': 1, 'totalMuslim': 1, 'totalChristian': 1}
        ).sort('number', 1))

        lines = ['=== 2025 Voter Roll — Ward-wise Summary ===',
                 f'Total wards: {len(ward_refs)}', '',
                 f"{'Ward':>4}  {'Name':<22}  {'Total':>7}  {'Male':>6}  "
                 f"{'Female':>7}  {'Hindu':>6}  {'Muslim':>7}  {'Christian':>9}"]

        grand = {'total': 0, 'male': 0, 'female': 0,
                 'hindu': 0, 'muslim': 0, 'christian': 0}
        for w in ward_refs:
            t  = w.get('totalCount',     0) or 0
            m  = w.get('totalMale',      0) or 0
            f  = w.get('totalFemale',    0) or 0
            h  = w.get('totalHindu',     0) or 0
            mu = w.get('totalMuslim',    0) or 0
            c  = w.get('totalChristian', 0) or 0
            lines.append(
                f"{w.get('number', ''):>4}  {w.get('name', ''):.<22}  "
                f"{t:>7,}  {m:>6,}  {f:>7,}  {h:>6,}  {mu:>7,}  {c:>9,}"
            )
            grand['total']    += t; grand['male']    += m; grand['female']    += f
            grand['hindu']    += h; grand['muslim']  += mu; grand['christian'] += c

        lines.append(
            f"{'TOTAL':>4}  {'':.<22}  "
            f"{grand['total']:>7,}  {grand['male']:>6,}  {grand['female']:>7,}  "
            f"{grand['hindu']:>6,}  {grand['muslim']:>7,}  {grand['christian']:>9,}"
        )
        hmc = {r['_id']: r['n'] for r in db['2025'].aggregate([
            {'$match': {'Predicted_Religion_Label': {'$in': ['H', 'M', 'C']}}},
            {'$group': {'_id': '$Predicted_Religion_Label', 'n': {'$sum': 1}}},
        ])}
        lines += ['', 'Predicted Religion Labels (2025 roll):',
                  f"  Hindu (H)    : {hmc.get('H', 0):,}",
                  f"  Muslim (M)   : {hmc.get('M', 0):,}",
                  f"  Christian (C): {hmc.get('C', 0):,}"]
        return '\n'.join(lines)
    except Exception as e:
        return f'[2025 voter roll summary error: {e}]'


# ── Builder 2: Survey Records ─────────────────────────────────────────────────

def _ai_ctx_survey_summary():
    try:
        db  = get_survey_db()
        res = list(db['SurveyRecords'].aggregate([{'$facet': {
            'total'       : [{'$count': 'n'}],
            'by_ward'     : [
                {'$match': {'wardNumber': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': {'$toString': '$wardNumber'}, 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}}, {'$limit': 40},
            ],
            'by_religion' : [{'$group': {'_id': '$religion',        'n': {'$sum': 1}}}, {'$sort': {'n': -1}}],
            'by_gender'   : [{'$group': {'_id': '$gender',          'n': {'$sum': 1}}}],
            'by_economic' : [{'$group': {'_id': '$economicStatus',  'n': {'$sum': 1}}}, {'$sort': {'n': -1}}, {'$limit': 8}],
            'by_community': [{'$group': {'_id': '$community',       'n': {'$sum': 1}}}, {'$sort': {'n': -1}}, {'$limit': 8}],
            'by_employment': [{'$group': {'_id': '$employmentStatus','n': {'$sum': 1}}}, {'$sort': {'n': -1}}],
            'by_health'   : [{'$group': {'_id': '$healthStatus',    'n': {'$sum': 1}}}, {'$sort': {'n': -1}}],
            'by_education': [{'$group': {'_id': '$education',       'n': {'$sum': 1}}}, {'$sort': {'n': -1}}, {'$limit': 10}],
            'outstation'  : [{'$match': {'outstationResident': 'Yes'}}, {'$count': 'n'}],
            'party_members': [{'$match': {'partyMember': 'Yes'}}, {'$count': 'n'}],
            'diff_abled'  : [{'$match': {'differentlyAbled': 'Yes'}}, {'$count': 'n'}],
            'schemes'     : [
                {'$unwind': '$schemesUsed'},
                {'$group': {'_id': '$schemesUsed', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 15},
            ],
        }}]))[0]

        total = res['total'][0]['n'] if res['total'] else 0
        wmap  = {str(k): v['name'] for k, v in WARD_FULL_DATA.items()}
        lines = ['=== Survey Records Summary ===', f'Total surveyed: {total:,}']

        lines.append('\nWard-wise Survey Count:')
        for w in res['by_ward']:
            lines.append(f"  Ward {w['_id']:>3} ({wmap.get(w['_id'], ''):.<22}): {w['count']:,}")

        def _section(title, items, key='_id', val='n'):
            lines.append(f'\n{title}:')
            for r in items:
                if r.get(key):
                    pct = f" ({round(r[val] / total * 100, 1)}%)" if total else ''
                    lines.append(f"  {str(r[key]):<20}: {r[val]:,}{pct}")

        _section('Religion',        res['by_religion'])
        _section('Gender',          res['by_gender'])
        _section('Economic Status', res['by_economic'])
        _section('Community',       res['by_community'])
        _section('Employment',      res['by_employment'])
        _section('Health Status',   res['by_health'])
        _section('Education',       res['by_education'])

        out_n = res['outstation'][0]['n']    if res['outstation']    else 0
        pm_n  = res['party_members'][0]['n'] if res['party_members'] else 0
        da_n  = res['diff_abled'][0]['n']    if res['diff_abled']    else 0
        lines += [f'\nOutstation residents  : {out_n:,}',
                  f'Party members (BJP)   : {pm_n:,}',
                  f'Differently abled     : {da_n:,}']

        if res.get('schemes'):
            lines.append('\nTop Schemes used by surveyed voters:')
            for s in res['schemes']:
                if s['_id']:
                    lines.append(f"  {str(s['_id']):<35}: {s['n']:,}")

        return '\n'.join(lines)
    except Exception as e:
        return f'[SurveyRecords summary error: {e}]'


# ── Builder 3: 2023 Polling Data ──────────────────────────────────────────────

def _ai_ctx_polling_summary():
    try:
        db   = get_survey_db()
        rows = list(db['2023_polled_notpolled'].aggregate([
            {'$group': {
                '_id': {'ward': '$Ward', 'rel': '$Religion', 'status': '$Polling status'},
                'n': {'$sum': 1},
            }},
            {'$sort': {'_id.ward': 1}},
        ]))
        total = db['2023_polled_notpolled'].count_documents({})
        if not rows:
            return '[2023 polling data: empty]'

        rel_map   = {'Hindu': 'H', 'Muslim': 'M', 'Christian': 'C'}
        ward_data = {}
        for r in rows:
            ward = r['_id'].get('ward', 'Unknown')
            rk   = rel_map.get(r['_id'].get('rel', ''))
            if not rk:
                continue
            ward_data.setdefault(ward, {'H': {}, 'M': {}, 'C': {}})
            k = 'polled' if r['_id'].get('status') == 'Polled' else 'notPolled'
            ward_data[ward][rk][k] = ward_data[ward][rk].get(k, 0) + r['n']

        lines = [f'=== 2023 Election Polling Data ({total:,} voters) ===',
                 f"{'Ward':<26}  {'H-Poll':>7}  {'H-No':>6}  "
                 f"{'M-Poll':>7}  {'M-No':>6}  {'C-Poll':>7}  {'C-No':>6}  "
                 f"{'H%':>5}  {'M%':>5}  {'C%':>5}"]

        for ward in sorted(ward_data):
            d    = ward_data[ward]
            hp   = d['H'].get('polled', 0); hn = d['H'].get('notPolled', 0)
            mp   = d['M'].get('polled', 0); mn = d['M'].get('notPolled', 0)
            cp   = d['C'].get('polled', 0); cn = d['C'].get('notPolled', 0)
            hpct = round(hp / (hp + hn) * 100, 1) if (hp + hn) else 0
            mpct = round(mp / (mp + mn) * 100, 1) if (mp + mn) else 0
            cpct = round(cp / (cp + cn) * 100, 1) if (cp + cn) else 0
            lines.append(
                f"{ward:<26}  {hp:>7,}  {hn:>6,}  {mp:>7,}  {mn:>6,}  "
                f"{cp:>7,}  {cn:>6,}  {hpct:>5}  {mpct:>5}  {cpct:>5}"
            )
        return '\n'.join(lines)
    except Exception as e:
        return f'[2023 polling summary error: {e}]'


# ── Builder 4: SIR Analysis ───────────────────────────────────────────────────

def _ai_ctx_sir_summary():
    try:
        db  = get_survey_db()
        db2 = get_db()

        counts = {
            'New Additions': _safe_count(db['SIR_NewAdditions']),
            'Not Found'    : _safe_count(db['SIR_NotFound']),
            'Suspicious'   : _safe_count(db['SIR_Suspicious']),
            'Genuine'      : _safe_count(db['genuine_voters']),
        }
        for optional in ('SIR_Deleted', 'SIR_Modified', 'SIR_Retained'):
            try:
                n = db[optional].estimated_document_count()
                if n:
                    counts[optional.replace('SIR_', '')] = n
            except Exception:
                pass

        v2002 = _safe_count(db['2002'])
        v2025 = _safe_count(db2['2025'])

        lines = ['=== SIR (Summary Intensive Revision) — 2002 vs 2025 ===',
                 f'2002 voter roll size : {v2002:,}',
                 f'2025 voter roll size : {v2025:,}',
                 f'Net change           : {v2025 - v2002:+,}', '']
        for k, v in counts.items():
            lines.append(f'  {k:<18}: {v:,}')

        try:
            wa = list(db['SIR_NewAdditions'].aggregate([
                {'$group': {'_id': '$ward', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 10},
            ]))
            if wa:
                lines.append('\nTop wards by SIR New Additions:')
                for w in wa:
                    lines.append(f"  {str(w['_id']):<30}: {w['n']:,}")
        except Exception:
            pass

        try:
            ws = list(db['SIR_Suspicious'].aggregate([
                {'$group': {'_id': '$ward', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 10},
            ]))
            if ws:
                lines.append('\nTop wards by SIR Suspicious:')
                for w in ws:
                    lines.append(f"  {str(w['_id']):<30}: {w['n']:,}")
        except Exception:
            pass

        return '\n'.join(lines)
    except Exception as e:
        return f'[SIR summary error: {e}]'


# ── Builder 5: Booth-wise Counts ─────────────────────────────────────────────

def _ai_ctx_booth_summary():
    try:
        db     = get_db()
        booths = list(db['2025'].aggregate([
            {'$group': {
                '_id'   : {'$toString': '$Part No'},
                'total' : {'$sum': 1},
                'male'  : {'$sum': {'$cond': [{'$eq': ['$Gender', 'Male']},   1, 0]}},
                'female': {'$sum': {'$cond': [{'$eq': ['$Gender', 'Female']}, 1, 0]}},
                'H'     : {'$sum': {'$cond': [{'$eq': ['$Predicted_Religion_Label', 'H']}, 1, 0]}},
                'M'     : {'$sum': {'$cond': [{'$eq': ['$Predicted_Religion_Label', 'M']}, 1, 0]}},
                'C'     : {'$sum': {'$cond': [{'$eq': ['$Predicted_Religion_Label', 'C']}, 1, 0]}},
            }},
            {'$sort': {'_id': 1}},
        ]))
        if not booths:
            return '[Booth summary: no data]'

        tot   = sum(b['total'] for b in booths)
        lines = [f'=== Booth-wise Voter Counts (2025) — {len(booths)} booths, {tot:,} total ===',
                 f"{'Booth':>5}  {'Ward':>4}  {'Total':>6}  "
                 f"{'Male':>6}  {'Female':>7}  {'H':>6}  {'M':>6}  {'C':>6}"]
        for b in booths:
            bn   = b['_id'] or ''
            ward = BOOTH_TO_WARD.get(bn, BOOTH_TO_WARD.get(
                int(bn) if bn.isdigit() else -1, '?'))
            lines.append(
                f"{bn:>5}  {ward:>4}  {b['total']:>6,}  "
                f"{b['male']:>6,}  {b['female']:>7,}  "
                f"{b['H']:>6,}  {b['M']:>6,}  {b['C']:>6,}"
            )
        return '\n'.join(lines)
    except Exception as e:
        return f'[Booth summary error: {e}]'


# ── Builder 6: Future Voters & Deceased ──────────────────────────────────────

def _ai_ctx_future_deceased():
    try:
        db     = get_survey_db()
        future = _safe_count(db['FutureVoters'])
        dec    = _safe_count(db['Deceased'])

        fv_gen = {r['_id']: r['n'] for r in db['FutureVoters'].aggregate([
            {'$group': {'_id': '$gender', 'n': {'$sum': 1}}}
        ])}

        lines = ['=== Future Voters & Deceased ===',
                 f'Future voters (eligible by 2028): {future:,}',
                 f"  Male  : {fv_gen.get('Male',   fv_gen.get('M', 0)):,}",
                 f"  Female: {fv_gen.get('Female', fv_gen.get('F', 0)):,}",
                 f'Deceased records captured       : {dec:,}']

        try:
            fw = list(db['FutureVoters'].aggregate([
                {'$group': {'_id': '$wardNumber', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 10},
            ]))
            if fw:
                lines.append('\nTop wards by Future Voters:')
                for w in fw:
                    wname = WARD_NUM_TO_NAME.get(str(w['_id']), str(w['_id']))
                    lines.append(f"  Ward {w['_id']} {wname:<22}: {w['n']:,}")
        except Exception:
            pass

        try:
            da = list(db['Deceased'].aggregate([
                {'$group': {'_id': '$gender', 'n': {'$sum': 1}}}
            ]))
            if da:
                lines.append('\nDeceased by gender:')
                for d in da:
                    lines.append(f"  {str(d['_id']):<10}: {d['n']:,}")
        except Exception:
            pass

        return '\n'.join(lines)
    except Exception as e:
        return f'[Future/Deceased summary error: {e}]'


# ── Builder 7: Community / Caste Count 2023 ──────────────────────────────────

def _ai_ctx_caste_count_2023():
    try:
        db   = get_survey_db()
        docs = list(db['Community_caste_based_count_2023'].find(
            {},
            {'_id': 0, 'Community / Caste': 1, 'Broad Category': 1,
             'Polled': 1, 'Non-Polled': 1}
        ).sort('Polled', -1).limit(40))

        if not docs:
            return '[Community_caste_based_count_2023: empty]'

        total_polled = 0
        total_np     = 0
        for d in docs:
            try:
                total_polled += int(str(d.get('Polled', 0)).replace(',', ''))
            except Exception:
                pass
            try:
                total_np += int(str(d.get('Non-Polled', 0)).replace(',', ''))
            except Exception:
                pass

        lines = ['=== Community / Caste-Based Count 2023 ===',
                 f'Grand Polled    : {total_polled:,}',
                 f'Grand Non-Polled: {total_np:,}', '',
                 f"{'Community / Caste':<35}  {'Broad Category':<16}  "
                 f"{'Polled':>9}  {'Non-Polled':>11}"]
        for d in docs:
            comm  = str(d.get('Community / Caste', ''))[:34]
            broad = str(d.get('Broad Category', ''))[:15]
            pol   = str(d.get('Polled', '-'))
            np_   = str(d.get('Non-Polled', '-'))
            lines.append(f"{comm:<35}  {broad:<16}  {pol:>9}  {np_:>11}")

        return '\n'.join(lines)
    except Exception as e:
        return f'[Community_caste_based_count_2023 error: {e}]'


# ── Builder 8: Polled/NotPolled with Caste 2023 ───────────────────────────────

def _ai_ctx_polled_notpolled_caste():
    try:
        db    = get_survey_db()
        total = _safe_count(db['Polled_NotPolled_caste_2023'])

        agg = list(db['Polled_NotPolled_caste_2023'].aggregate([{'$facet': {
            'by_status'  : [{'$group': {'_id': '$Status',            'n': {'$sum': 1}}}, {'$sort': {'n': -1}}],
            'by_category': [{'$group': {'_id': '$Category',          'n': {'$sum': 1}}}, {'$sort': {'n': -1}}, {'$limit': 10}],
            'by_caste'   : [{'$group': {'_id': '$Community / Caste', 'n': {'$sum': 1}}}, {'$sort': {'n': -1}}, {'$limit': 20}],
            'by_booth'   : [{'$group': {'_id': '$Booth',             'n': {'$sum': 1}}}, {'$sort': {'n': -1}}, {'$limit': 15}],
            'by_gender'  : [{'$group': {'_id': '$Gen',               'n': {'$sum': 1}}}],
        }}]))[0]

        lines = ['=== Polled / Not-Polled with Caste (2023) ===',
                 f'Total records: {total:,}', '']

        def _sec(title, items):
            lines.append(f'{title}:')
            for r in items:
                if r.get('_id'):
                    pct = f" ({round(r['n'] / total * 100, 1)}%)" if total else ''
                    lines.append(f"  {str(r['_id']):<30}: {r['n']:,}{pct}")
            lines.append('')

        _sec('Polling Status',             agg['by_status'])
        _sec('Broad Category',             agg['by_category'])
        _sec('Gender (M/F)',               agg['by_gender'])
        _sec('Community / Caste (top 20)', agg['by_caste'])
        _sec('Booth (top 15)',             agg['by_booth'])

        return '\n'.join(lines)
    except Exception as e:
        return f'[Polled_NotPolled_caste_2023 error: {e}]'


# ── Builder 9: Ward Information (ward-booth-2026) ─────────────────────────────

def _ai_ctx_ward_booth_2026():
    try:
        db   = get_survey_db()
        docs = list(db['ward-booth-2026'].find({}).sort('Ward No', 1).limit(50))
        if not docs:
            return '[ward-booth-2026: empty]'

        total_e = sum(d.get('Total Electors (E)', 0) or 0 for d in docs)
        total_m = sum(d.get('Electors Mapped (M)', 0) or 0 for d in docs)

        lines = ['=== Ward Information (2026) ===',
                 f'Total wards loaded: {len(docs)}',
                 f'Total Electors (E): {total_e:,}',
                 f'Total Mapped (M)  : {total_m:,}',
                 f'Overall % Mapped  : {round(total_m / total_e * 100, 2) if total_e else 0}%',
                 '',
                 f"{'Ward':>4}  {'Name':<25}  {'E':>6}  {'D':>6}  "
                 f"{'H':>6}  {'J':>6}  {'K':>6}  {'M':>6}  {'M%':>6}"]

        for d in docs:
            lines.append(
                f"{str(d.get('Ward No', '')):>4}  "
                f"{str(d.get('Ward Name', '')):.<25}  "
                f"{d.get('Total Electors (E)', 0) or 0:>6,}  "
                f"{d.get('Cutoff Elec (D)', 0) or 0:>6,}  "
                f"{d.get('Total Mapped (H)', 0) or 0:>6,}  "
                f"{d.get('AgeoCutoff (J)', 0) or 0:>6,}  "
                f"{d.get('Progeny>18 (K)', 0) or 0:>6,}  "
                f"{d.get('Electors Mapped (M)', 0) or 0:>6,}  "
                f"{str(d.get('% Total (MoE)', '')):>6}"
            )
        lines.append('\nKey: E=Total Electors, D=Cutoff, H=BLO Mapped, J=AgeoCutoff, '
                     'K=Progeny>18, M=Electors Mapped')
        return '\n'.join(lines)
    except Exception as e:
        return f'[ward-booth-2026 error: {e}]'


# ── Builder 10: Booth Details (ward-booth-details) ────────────────────────────

def _ai_ctx_ward_booth_details():
    try:
        db   = get_survey_db()
        docs = list(db['ward-booth-details'].find({}).sort(
            [('Ward', 1), ('Booth (Part)', 1)]).limit(300))
        if not docs:
            return '[ward-booth-details: empty]'

        total_e = sum(d.get('Total Electors (E)', 0) or 0 for d in docs)

        lines = ['=== Booth Details (ward-booth-details) ===',
                 f'Total booth records: {len(docs)}',
                 f'Total Electors     : {total_e:,}', '',
                 f"{'Ward':>4}  {'Ward Name':<22}  {'Booth':>5}  "
                 f"{'Electors':>8}  {'Cutoff':>7}  {'Mapped':>7}  {'I%':>6}  {'N%':>6}"]

        for d in docs:
            lines.append(
                f"{str(d.get('Ward', '')):>4}  "
                f"{str(d.get('Ward Name', '')):.<22}  "
                f"{str(d.get('Booth (Part)', '')):>5}  "
                f"{d.get('Total Electors (E)', 0) or 0:>8,}  "
                f"{d.get('Cutoff (D)', 0) or 0:>7,}  "
                f"{d.get('Total Mapped (H)', 0) or 0:>7,}  "
                f"{str(d.get('I% (orig.)', '')):>6}  "
                f"{str(d.get('N% (orig.)', '')):>6}"
            )
        return '\n'.join(lines)
    except Exception as e:
        return f'[ward-booth-details error: {e}]'


# ── Builder 11: NotFoundRecordSurvey ─────────────────────────────────────────

def _ai_ctx_not_found_survey():
    try:
        db    = get_survey_db()
        total = _safe_count(db['NotFoundRecordSurvey'])

        agg = list(db['NotFoundRecordSurvey'].aggregate([{'$facet': {
            'by_ward'  : [{'$group': {'_id': '$wardNumber', 'n': {'$sum': 1}}},
                          {'$sort': {'n': -1}}, {'$limit': 20}],
            'by_reason': [{'$group': {'_id': '$reason',    'n': {'$sum': 1}}},
                          {'$sort': {'n': -1}}, {'$limit': 10}],
            'by_status': [{'$group': {'_id': '$status',    'n': {'$sum': 1}}},
                          {'$sort': {'n': -1}}],
        }}]))[0]

        lines = ['=== NotFoundRecordSurvey (Non-Located Voters) ===',
                 f'Total not-found records: {total:,}', '']

        if agg['by_ward']:
            lines.append('Ward-wise (top 20):')
            for w in agg['by_ward']:
                wname = WARD_NUM_TO_NAME.get(str(w['_id']), str(w['_id']))
                pct   = round(w['n'] / total * 100, 1) if total else 0
                lines.append(f"  Ward {w['_id']} {wname:<22}: {w['n']:,}  ({pct}%)")

        if agg['by_reason']:
            lines.append('\nReason breakdown:')
            for r in agg['by_reason']:
                if r['_id']:
                    lines.append(f"  {str(r['_id']):<35}: {r['n']:,}")

        if agg['by_status']:
            lines.append('\nStatus breakdown:')
            for s in agg['by_status']:
                if s['_id']:
                    lines.append(f"  {str(s['_id']):<20}: {s['n']:,}")

        return '\n'.join(lines)
    except Exception as e:
        return f'[NotFoundRecordSurvey error: {e}]'


# ── Builder 12: Coastal Karnataka Caste Reference ────────────────────────────

def _ai_ctx_coastal_caste_reference():
    try:
        db    = get_survey_db()
        total = _safe_count(db['coastal_karnataka_all_references_castes'])

        agg = list(db['coastal_karnataka_all_references_castes'].aggregate([{'$facet': {
            'by_caste'    : [{'$group': {'_id': '$Caste',            'n': {'$sum': 1}}}, {'$sort': {'n': -1}}, {'$limit': 20}],
            'by_category' : [{'$group': {'_id': '$Broad Category',   'n': {'$sum': 1}}}, {'$sort': {'n': -1}}],
            'by_region'   : [{'$group': {'_id': '$Region',           'n': {'$sum': 1}}}, {'$sort': {'n': -1}}, {'$limit': 10}],
            'by_assoc_type': [{'$group': {'_id': '$Association Type', 'n': {'$sum': 1}}}, {'$sort': {'n': -1}}],
        }}]))[0]

        lines = ['=== Coastal Karnataka Caste Reference ===',
                 f'Total caste-surname mappings: {total:,}', '']

        def _sec(title, items):
            lines.append(f'{title}:')
            for r in items:
                if r.get('_id'):
                    lines.append(f"  {str(r['_id']):<35}: {r['n']:,} entries")
            lines.append('')

        _sec('Broad Category', agg['by_category'])
        _sec('Region',         agg['by_region'])
        _sec('Association Type', agg['by_assoc_type'])
        _sec('Top Castes',     agg['by_caste'])

        try:
            sample_docs = list(db['coastal_karnataka_all_references_castes'].aggregate([
                {'$group': {'_id': '$Broad Category',
                            'surnames': {'$push': '$Surname'},
                            'castes':   {'$addToSet': '$Caste'}}},
                {'$limit': 8},
            ]))
            if sample_docs:
                lines.append('Sample Surname → Category mappings:')
                for sd in sample_docs:
                    s_list = ', '.join(str(s) for s in sd['surnames'][:5])
                    c_list = ', '.join(str(c) for c in list(sd['castes'])[:3])
                    lines.append(f"  [{sd['_id']}] Castes: {c_list}  |  Surnames: {s_list}")
        except Exception:
            pass

        return '\n'.join(lines)
    except Exception as e:
        return f'[coastal_karnataka_all_references_castes error: {e}]'


# ── Builder 13: NewQueryStack1 (SWOT) ────────────────────────────────────────

def _ai_ctx_swot_stack():
    try:
        db    = get_survey_db()
        total = _safe_count(db['NewQueryStack1'])
        if total == 0:
            return '[NewQueryStack1: empty]'

        lines = ['=== Constituency SWOT / Intelligence Query Stack (NewQueryStack1) ===',
                 f'Total documents: {total:,}']

        sample_doc = db['NewQueryStack1'].find_one({'chunkIndex': 0})
        if sample_doc and 'records' in sample_doc:
            records = sample_doc.get('records', [])
            lines.append(f'Records in chunk 0: {len(records)}')

            label_counts = {}
            field_counts = {}
            for rec in records:
                lbl = rec.get('label', 'Unknown')
                label_counts[lbl] = label_counts.get(lbl, 0) + 1
                cf = rec.get('comparisonField', '')
                if cf:
                    field_counts[cf] = field_counts.get(cf, 0) + 1

            if label_counts:
                lines.append('\nStrength Labels (chunk 0 sample):')
                for lbl, cnt in sorted(label_counts.items(), key=lambda x: -x[1]):
                    lines.append(f"  {lbl:<15}: {cnt} records")

            if field_counts:
                lines.append('\nComparison Fields (chunk 0 sample):')
                for fld, cnt in sorted(field_counts.items(), key=lambda x: -x[1])[:10]:
                    lines.append(f"  {fld:<25}: {cnt} records")

            ctx_sample = next(
                (rec.get('predictedContext', {}) for rec in records if rec.get('predictedContext')),
                {}
            )
            if ctx_sample:
                lines.append('\nSample Predicted Context keys:')
                for k, v in ctx_sample.items():
                    lines.append(f"  {k}: {v}")

        lines.append('\n[Full SWOT records available via api_ai_query_insight / api_ai_birdseye_view]')
        return '\n'.join(lines)
    except Exception as e:
        return f'[NewQueryStack1 error: {e}]'


# ── Builder 14: 2002 Voter Roll ───────────────────────────────────────────────

def _ai_ctx_voter_roll_2002():
    try:
        db    = get_survey_db()
        total = _safe_count(db['2002'])

        agg = list(db['2002'].aggregate([{'$facet': {
            'by_gender': [{'$group': {'_id': '$Gender', 'n': {'$sum': 1}}}],
            'age_stats': [
                {'$match': {'Age': {'$type': ['int', 'long', 'double', 'string']}}},
                {'$project': {'age_num': {'$toInt': {'$toString': '$Age'}}}},
                {'$match': {'age_num': {'$gt': 0, '$lt': 120}}},
                {'$group': {'_id': None,
                            'avg': {'$avg': '$age_num'},
                            'min': {'$min': '$age_num'},
                            'max': {'$max': '$age_num'}}},
            ],
        }}]))[0]

        lines = ['=== 2002 Voter Roll ===', f'Total voters (2002): {total:,}', '']

        if agg.get('by_gender'):
            lines.append('Gender breakdown:')
            for g in agg['by_gender']:
                pct = round(g['n'] / total * 100, 1) if total else 0
                lines.append(f"  {str(g['_id']):<10}: {g['n']:,}  ({pct}%)")

        if agg.get('age_stats') and agg['age_stats']:
            s = agg['age_stats'][0]
            lines.append(f"\nAge stats: Avg={round(s.get('avg', 0), 1)}, "
                         f"Min={s.get('min', '-')}, Max={s.get('max', '-')}")

        lines.append('\n[2002 roll is the baseline for SIR comparison — see SIR Analysis section]')
        return '\n'.join(lines)
    except Exception as e:
        return f'[2002 voter roll summary error: {e}]'


# ── Builder 15: Genuine Voters ────────────────────────────────────────────────

def _ai_ctx_genuine_voters():
    try:
        db    = get_survey_db()
        total = _safe_count(db['genuine_voters'])

        agg = list(db['genuine_voters'].aggregate([{'$facet': {
            'by_ward'    : [{'$group': {'_id': '$ward',     'n': {'$sum': 1}}},
                            {'$sort': {'n': -1}}, {'$limit': 20}],
            'by_booth'   : [{'$group': {'_id': '$booth',    'n': {'$sum': 1}}},
                            {'$sort': {'n': -1}}, {'$limit': 15}],
            'by_category': [{'$group': {'_id': '$category', 'n': {'$sum': 1}}},
                            {'$sort': {'n': -1}}],
        }}]))[0]

        lines = ['=== Genuine Voters (SIR Verified) ===',
                 f'Total genuine voters confirmed: {total:,}', '']

        if agg.get('by_ward'):
            lines.append('Ward-wise (top 20):')
            for w in agg['by_ward']:
                wname = WARD_NUM_TO_NAME.get(str(w['_id']), str(w['_id']))
                lines.append(f"  {str(w['_id']):<5} {wname:<25}: {w['n']:,}")

        if agg.get('by_category'):
            lines.append('\nCategory breakdown:')
            for c in agg['by_category']:
                if c['_id']:
                    lines.append(f"  {str(c['_id']):<25}: {c['n']:,}")

        return '\n'.join(lines)
    except Exception as e:
        return f'[genuine_voters error: {e}]'


# ── Builder 16: Socio-Economic Data (SurveyDataBase.Data) ────────────────────
#
# Document schema (confirmed from sample doc):
#   wardNumber (int), boothNo (str "21-Apr"), houseNumber, address
#   firstName, middleName, lastName, voterid, gender, age, dob, maritalStatus
#   religion, predictedReligion, minority ("Yes"/"No"), community, subcategory
#   economicStatus ("APL"/"BPL"…), annualIncome (int), familyIncome (int)
#   education, educationtype, employmentStatus, employmentType
#   healthStatus, diseaseType, diseaseName, differentlyAbled ("Yes"/"No")
#   homeType, currentHomeType, areaType, currentAreaType
#   schemesUsed (array of str), outstationResident ("Yes"/"No"), outstationCity/State
#   partyMember ("Yes"/"No"), student ("Yes"/"No"), isHeadOfHouse ("Yes"/"No")
#   sir_category (str), sir_suspicious (bool), Time_stamp (date)

def _ai_ctx_socio_economic_data():
    """
    Loads socio-economic household data from the 'Data' collection in
    SurveyDataBase (_SURVEY_URL cluster). Single $facet aggregation covers all
    major dimensions so the AI can answer income/employment/health/housing/
    scheme questions ward-by-ward.
    """
    try:
        db    = get_survey_db()
        coll  = db['Data']
        total = _safe_count(coll)
        if not total:
            return '[Socio-Economic Data: collection empty or not found]'

        agg = list(coll.aggregate([{'$facet': {

            # ── Ward distribution (wardNumber is int) ─────────────────────────
            'by_ward': [
                {'$group': {'_id': '$wardNumber', 'n': {'$sum': 1}}},
                {'$sort': {'_id': 1}},
            ],

            # ── Gender & marital status ───────────────────────────────────────
            'by_gender': [
                {'$group': {'_id': '$gender', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],
            'by_marital': [
                {'$group': {'_id': '$maritalStatus', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],

            # ── Religion & community ──────────────────────────────────────────
            'by_religion': [
                {'$group': {'_id': '$religion', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],
            'by_community': [
                {'$match': {'community': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$community', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 15},
            ],

            # ── Economic status ───────────────────────────────────────────────
            'by_economic': [
                {'$group': {'_id': '$economicStatus', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],

            # ── Income buckets (annualIncome is numeric int/long) ─────────────
            'income_buckets': [
                {'$match': {'annualIncome': {'$type': ['int', 'long', 'double', 'decimal']}}},
                {'$bucket': {
                    'groupBy'   : '$annualIncome',
                    'boundaries': [0, 50000, 100000, 200000, 300000, 500000, 1000000, 9999999999],
                    'default'   : 'Other',
                    'output'    : {'n': {'$sum': 1}, 'avg': {'$avg': '$annualIncome'}},
                }},
            ],
            'avg_income': [
                {'$match': {'annualIncome': {'$type': ['int', 'long', 'double', 'decimal']}}},
                {'$group': {'_id': None, 'avg': {'$avg': '$annualIncome'}}},
            ],

            # ── Employment ───────────────────────────────────────────────────
            'by_employment': [
                {'$group': {'_id': '$employmentStatus', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],
            'by_emp_type': [
                {'$match': {'employmentType': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$employmentType', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 12},
            ],

            # ── Education ────────────────────────────────────────────────────
            'by_education': [
                {'$group': {'_id': '$education', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],
            'by_edu_type': [
                {'$match': {'educationtype': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$educationtype', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 12},
            ],

            # ── Health ───────────────────────────────────────────────────────
            'by_health': [
                {'$group': {'_id': '$healthStatus', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],
            'by_disease_type': [
                {'$match': {'diseaseType': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$diseaseType', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],
            'by_disease_name': [
                {'$match': {'diseaseName': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$diseaseName', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 15},
            ],

            # ── Housing ──────────────────────────────────────────────────────
            'by_home_type': [                        # permanent home ownership
                {'$group': {'_id': '$homeType', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],
            'by_current_home': [                     # current living arrangement
                {'$match': {'currentHomeType': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$currentHomeType', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],
            'by_area_type': [
                {'$group': {'_id': '$areaType', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],

            # ── Special flags (stored as "Yes"/"No" strings) ──────────────────
            'diff_abled'    : [{'$match': {'differentlyAbled'  : 'Yes'}}, {'$count': 'n'}],
            'outstation'    : [{'$match': {'outstationResident': 'Yes'}}, {'$count': 'n'}],
            'party_members' : [{'$match': {'partyMember'       : 'Yes'}}, {'$count': 'n'}],
            'students'      : [{'$match': {'student'           : 'Yes'}}, {'$count': 'n'}],
            'minorities'    : [{'$match': {'minority'          : 'Yes'}}, {'$count': 'n'}],
            'head_of_house' : [{'$match': {'isHeadOfHouse'     : 'Yes'}}, {'$count': 'n'}],
            # sir_suspicious is a boolean true/false
            'sir_suspicious': [{'$match': {'sir_suspicious': True}}, {'$count': 'n'}],

            # ── Top outstation cities ─────────────────────────────────────────
            'outstation_cities': [
                {'$match': {'outstationResident': 'Yes',
                            'outstationCity': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$outstationCity', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 10},
            ],

            # ── SIR categories ────────────────────────────────────────────────
            'by_sir_category': [
                {'$match': {'sir_category': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$sir_category', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}},
            ],

            # ── Schemes used (array field, must $unwind first) ────────────────
            'by_scheme': [
                {'$unwind': '$schemesUsed'},
                {'$group': {'_id': '$schemesUsed', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 20},
            ],

        }}]))[0]

        wmap = {str(k): v['name'] for k, v in WARD_FULL_DATA.items()}
        lines = [
            '=== Socio-Economic Data (SurveyDataBase.Data) ===',
            f'Total records: {total:,}',
        ]

        def _pct(n):
            return f" ({round(n / total * 100, 1)}%)" if total else ''

        def _sec(title, items, key='_id', val='n'):
            if not items:
                return
            lines.append(f'\n{title}:')
            for r in items:
                lbl = str(r.get(key)) if r.get(key) not in (None, '') else 'Unknown'
                lines.append(f"  {lbl:<32}: {r[val]:,}{_pct(r[val])}")

        # Ward breakdown
        lines.append('\nWard-wise Record Count:')
        for w in agg.get('by_ward', []):
            wid   = str(w['_id']) if w['_id'] is not None else '?'
            wname = wmap.get(wid, wid)
            lines.append(f"  Ward {wid:>3} ({wname:<22}): {w['n']:,}")

        _sec('Gender',                    agg.get('by_gender', []))
        _sec('Marital Status',            agg.get('by_marital', []))
        _sec('Religion',                  agg.get('by_religion', []))
        _sec('Community / Category',      agg.get('by_community', []))
        _sec('Economic Status',           agg.get('by_economic', []))

        # Income buckets with ₹ labels
        bucket_labels = {
            0:         '₹0 – 50,000',
            50000:     '₹50k – 1L',
            100000:    '₹1L – 2L',
            200000:    '₹2L – 3L',
            300000:    '₹3L – 5L',
            500000:    '₹5L – 10L',
            1000000:   '₹10L+',
            'Other':   'Non-numeric / missing',
        }
        income_bkts = agg.get('income_buckets', [])
        if income_bkts:
            lines.append('\nAnnual Income Distribution:')
            for b in income_bkts:
                lbl = bucket_labels.get(b['_id'], str(b['_id']))
                avg = f"  (avg ₹{b['avg']:,.0f})" if b.get('avg') else ''
                lines.append(f"  {lbl:<22}: {b['n']:,}{_pct(b['n'])}{avg}")
        if agg.get('avg_income'):
            lines.append(f"  Overall avg annual income: ₹{agg['avg_income'][0].get('avg', 0):,.0f}")

        _sec('Employment Status',         agg.get('by_employment', []))
        _sec('Employment Type',           agg.get('by_emp_type', []))
        _sec('Education Level',           agg.get('by_education', []))
        _sec('Education Type (detail)',   agg.get('by_edu_type', []))
        _sec('Health Status',             agg.get('by_health', []))
        _sec('Disease Type',              agg.get('by_disease_type', []))
        _sec('Disease Name (top 15)',     agg.get('by_disease_name', []))
        _sec('Home Ownership Type',       agg.get('by_home_type', []))
        _sec('Current Living Arrangement',agg.get('by_current_home', []))
        _sec('Permanent Area Type',       agg.get('by_area_type', []))

        # Scalar flags
        da_n  = agg['diff_abled'][0]['n']    if agg.get('diff_abled')    else 0
        out_n = agg['outstation'][0]['n']    if agg.get('outstation')    else 0
        pm_n  = agg['party_members'][0]['n'] if agg.get('party_members') else 0
        st_n  = agg['students'][0]['n']      if agg.get('students')      else 0
        mn_n  = agg['minorities'][0]['n']    if agg.get('minorities')    else 0
        hh_n  = agg['head_of_house'][0]['n'] if agg.get('head_of_house') else 0
        sus_n = agg['sir_suspicious'][0]['n']if agg.get('sir_suspicious')else 0

        lines += [
            '',
            f'Differently Abled      : {da_n:,}{_pct(da_n)}',
            f'Outstation Residents   : {out_n:,}{_pct(out_n)}',
            f'BJP Party Members      : {pm_n:,}{_pct(pm_n)}',
            f'Students               : {st_n:,}{_pct(st_n)}',
            f'Minority (Yes)         : {mn_n:,}{_pct(mn_n)}',
            f'Head of Household      : {hh_n:,}{_pct(hh_n)}',
            f'SIR Suspicious Flag    : {sus_n:,}{_pct(sus_n)}',
        ]

        _sec('Outstation Cities (top 10)', agg.get('outstation_cities', []))
        _sec('SIR Category',               agg.get('by_sir_category', []))

        if agg.get('by_scheme'):
            lines.append('\nTop Government Schemes Used:')
            for s in agg['by_scheme']:
                if s['_id']:
                    lines.append(f"  {str(s['_id']):<45}: {s['n']:,}")

        return '\n'.join(lines)
    except Exception as e:
        return f'[Socio-Economic Data error: {e}]'


# ════════════════════════════════════════════════════════════════════════════════
# PARALLEL MONGO CONTEXT LOADER
# ════════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════════
# RAG — Smart Query-Aware File Chunking
# Each function loads only the relevant portion of a file based on the question.
# ════════════════════════════════════════════════════════════════════════════════

# 2023p.xlsx: ward name → sheet names (current 2023 + comparison 2018)
_2023P_WARD_SHEETS = {
    'ATTAVARA':           ['ATTAVARA',        'ATTAVARA-18'],
    'ALAPE DAKSHINA':     ['ALAPE-S',         'ALAPE-S18'],
    'ALAPE UTTARA':       [' ALAPE-N',        'ALAPE-N18'],
    'BAJAL':              ['BAJAL',           'BAJAL-18'],
    'BEJAI':              ['BEJAI',           'BEJAI-18'],
    'BENDUR':             ['BENDUR',          'BENDR-18'],
    'BENGRE':             ['BENGRE',          'BENGRE-18'],
    'BOLAR':              ['BOLAR',           'BOLAR-18'],
    'BOLOOR':             ['BOLOOR',          'BOLOOR-18'],
    'NAVAYATH':           ['BUNDER',          'BNDER-18'],
    'CENTRAL':            ['CENTRAL',         'CENTRAL-18'],
    'CANTONMENT':         ['CONTONMENT',      'CONTONMENT-18'],
    'COURT':              ['COURT',           'CORT-18'],
    'DEREBAIL SOUTH WEST':['DEREBAIL NAIRTHYA','DEREBAILNAIRTYHYA18'],
    'DEREBAIL SOUTH':     ['DEREBAIL SOUTH',  'DEREBAIL SOTH18'],
    'DEREBAIL WEST':      ['DEREBAIL WEST',   'DEREBAIL WEST18'],
    'DONGERKERY':         ['DONGARAKERI',     'DONGARKERI-18'],
    'FALNIR':             ['FALNIR',          'FALNIR-18'],
    'HOIGE BAZAR':        ['HOIGE BAZAR',     'HOIGE BAZAR-18'],
    'JEPPINAMUGER':       ['JEPPINAMOGAR',    'JEPPINAMOGAR-18'],
    'JEPPU':              ['JEPPU',           'JEPPU-18'],
    'KADRI NORTH':        ['KADRI NORTH',     'KADRI-18'],
    'KADRI SOUTH':        ['KADRI SOUTH',     'KADRI(S)-18'],
    'KAMBLA':             ['KAMBALA',         'KAMBALA-18'],
    'KANKANADY':          ['KANKANADY',       'KANKANADY-18'],
    'KANNUR':             ['KANNUR',          'KANNUR-18'],
    'KODIALBAIL':         ['KODIALBAIL',      'KODIALBAIL-18'],
    'KUDROLI':            ['KUDROLI',         'KUDROLI-18'],
    'MANNAGUDDA':         ['MANNAGUDA',       'MANNAGDA-18'],
    'MAROLI':             ['MAROLI',          'MAROLI-18'],
    'MILAGRIS':           ['MILAGRESS',       'MILAGRESS-18'],
    'PADAVU CENTRAL':     ['PADAV CENTRAL',   'PADAV CENTRAL-18'],
    'PADAVU POORVA':      ['PADAV EAST',      'PADAV EAST-18'],
    'PADAVU':             ['PADAV WEST',      'PADAV WEST-18'],
    'PORT':               ['PORT',            'PORT-18'],
    'SHIVBHAG':           ['SHIVABAGH',       'SHIVABAGH-18'],
    'VALENCIA':           ['VALENCIA',        'VALENCIA-18'],
}

_2023P_CANDIDATE_MARKERS = ['LOBO', 'KAMATH', 'VEDAVYASA', 'SANTHOSH',
                             'DHARMENDRA', 'WINNY', 'K.S.PAI']


def _rag_extract_2023p_ward_sheet(ws) -> str:
    """Extract one ward sheet from 2023p.xlsx into a clean table."""
    from openpyxl import load_workbook as _lw  # already imported at top
    ward_name  = ''
    candidates = []
    data_rows  = []
    total_row  = None
    for row in ws.iter_rows(values_only=True):
        vals = [v for v in row if v is not None]
        if not vals:
            continue
        row_str = str(vals)
        # Candidate name row
        if any(m in row_str for m in _2023P_CANDIDATE_MARKERS):
            candidates = [str(v) for v in row if v is not None]
            continue
        # Data rows: col[1] is booth number (int < 1000)
        if len(row) >= 4 and isinstance(row[1], (int, float)) and row[1] and row[1] < 1000:
            if not ward_name and row[0]:
                ward_name = str(row[0])
            booth  = int(row[1])
            total  = row[2] or 0
            votes  = [row[i] or 0 for i in range(3, min(3 + len(candidates), len(row)))]
            data_rows.append((booth, int(total), votes))
        # Total row: col[1] is None, col[2] is large number
        elif (not row[1] and row[2] and isinstance(row[2], (int, float))
              and row[2] > 500 and data_rows):
            total_row = row

    if not data_rows:
        return ''

    # Shorten candidate names to first 10 chars
    cands_short = [c[:10] for c in (candidates or [])]
    lines = [f'Ward: {ward_name}']
    if cands_short:
        hdr = f"{'Booth':>5}  {'Voters':>6}  " + '  '.join(f'{c:>10}' for c in cands_short)
        lines.append(hdr)
        lines.append('-' * (14 + 13 * len(cands_short)))
    for booth, total, votes in data_rows:
        vstr = '  '.join(f'{v:>10}' for v in votes)
        lines.append(f'{booth:>5}  {total:>6}  {vstr}')
    if total_row:
        tvotes = [total_row[i] or 0 for i in range(3, min(3 + len(candidates), len(total_row)))]
        vstr = '  '.join(f'{v:>10}' for v in tvotes)
        lines.append(f'{"TOTAL":>5}  {int(total_row[2] or 0):>6}  {vstr}')
    return '\n'.join(lines)


def _rag_load_2023p(message: str) -> str:
    """
    Ward-aware extraction from 2023p.xlsx.
    Specific ward mentioned → load those 2 sheets (2023 + 2018 comparison).
    No ward → load MAIN WARD + WARD-BOOTH summary sheets only.
    """
    try:
        from openpyxl import load_workbook as _lw
    except ImportError:
        return '[openpyxl not available]'

    path = _os2.path.join(_AI_DATA_DIR, '2023p.xlsx')
    if not _os2.path.exists(path):
        # fuzzy find
        for f in _os2.listdir(_AI_DATA_DIR):
            if '2023p' in f.lower():
                path = _os2.path.join(_AI_DATA_DIR, f)
                break
        else:
            return '[2023p.xlsx not found]'

    msg_upper     = message.upper()
    matched_wards = []
    for wnum, wdata in WARD_FULL_DATA.items():
        wname = wdata['name'].upper()
        if str(wnum) in message or wname in msg_upper or wname.split()[0] in msg_upper:
            matched_wards.append(wname)

    try:
        wb = _lw(path, read_only=True, data_only=True)
    except Exception as e:
        return f'[2023p.xlsx load error: {e}]'

    sections = []
    if matched_wards:
        for ward_key in matched_wards:
            for sname in _2023P_WARD_SHEETS.get(ward_key, []):
                actual = next((s for s in wb.sheetnames
                               if s.strip().upper() == sname.strip().upper()), None)
                if actual:
                    text = _rag_extract_2023p_ward_sheet(wb[actual])
                    if text:
                        yr = '2018' if actual.strip().endswith('-18') else '2023'
                        sections.append(f'=== 2023p | {ward_key} ({yr}) ===\n{text}')
    else:
        # Summary sheets
        for sname in ['MAIN WARD', 'WARD-BOOTH', 'BOOTHWISE']:
            if sname in wb.sheetnames:
                ws    = wb[sname]
                lines = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    vals = [v for v in row if v is not None]
                    if vals:
                        lines.append(','.join(str(v) for v in row if v is not None))
                    if i > 100:
                        break
                if lines:
                    sections.append(f'=== 2023p | {sname} ===\n' + '\n'.join(lines))

    wb.close()
    result = '\n\n'.join(sections)
    print(f'[RAG File] 2023p: {len(result):,} chars (~{len(result)//4:,} tokens) | '
          f'wards: {matched_wards or "summary"}')
    return result or '[2023p: no matching data]'


def _rag_load_xlsx_smart(fname: str, message: str,
                          priority_sheets: list = None,
                          keyword_sheet_map: dict = None,
                          max_chars: int = 60_000) -> str:
    """
    Generic smart xlsx loader.
    priority_sheets: always load these sheets
    keyword_sheet_map: {keyword: [sheet_names]} — load sheet if keyword in message
    max_chars: hard cap on output
    """
    try:
        from openpyxl import load_workbook as _lw
    except ImportError:
        return '[openpyxl not available]'

    path = _os2.path.join(_AI_DATA_DIR, fname)
    if not _os2.path.exists(path):
        for f in _os2.listdir(_AI_DATA_DIR):
            if fname[:12].upper() in f.upper():
                path = _os2.path.join(_AI_DATA_DIR, f)
                fname = f
                break
        else:
            return f'[{fname}: not found]'

    try:
        wb = _lw(path, read_only=True, data_only=True)
    except Exception as e:
        return f'[{fname} load error: {e}]'

    msg_lower    = message.lower()
    sheets_todo  = list(priority_sheets or [])

    if keyword_sheet_map:
        for kw, snames in keyword_sheet_map.items():
            if kw in msg_lower:
                sheets_todo.extend(snames)

    # Dedupe while preserving order
    seen = set()
    sheets_todo = [s for s in sheets_todo if not (s in seen or seen.add(s))]

    # If nothing matched keywords, load first 3 sheets
    if not sheets_todo:
        sheets_todo = wb.sheetnames[:3]

    # Ward/booth filter from message
    ward_filter = []
    for wnum, wdata in WARD_FULL_DATA.items():
        wname = wdata['name'].upper()
        if str(wnum) in message or wname in message.upper() or wname.split()[0] in message.upper():
            ward_filter.append(wname)

    sections    = []
    total_chars = 0

    for sname in sheets_todo:
        if sname not in wb.sheetnames or total_chars >= max_chars:
            break
        ws    = wb[sname]
        lines = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            vals = [v for v in row if v is not None]
            if not vals:
                continue
            row_str = ','.join(str(v) for v in row if v is not None)
            # Apply ward filter only after header rows
            if ward_filter and i > 5:
                row_upper = row_str.upper()
                if not any(wf in row_upper or wf.split()[0] in row_upper
                           for wf in ward_filter):
                    continue
            lines.append(row_str)
            if len(lines) > 150:
                break
        if len(lines) > 2:
            chunk = f'=== {fname} | {sname} ===\n' + '\n'.join(lines)
            sections.append(chunk)
            total_chars += len(chunk)

    wb.close()
    result = '\n\n'.join(sections)
    print(f'[RAG File] {fname}: {len(result):,} chars | wards: {ward_filter or "all"}')
    return result or f'[{fname}: no data extracted]'


def _rag_load_file(fkey: str, message: str) -> str:
    """
    Dispatch file loading based on file key prefix.
    fkey is a prefix/keyword used to find the file in _AI_DATA_DIR.
    """
    if not _os2.path.isdir(_AI_DATA_DIR):
        return '[data directory not found]'

    fkey_upper = fkey.upper()

    # ── 2023p — ward-aware sheet extraction ──────────────────────────────────
    if '2023P' in fkey_upper:
        return _rag_load_2023p(message)

    # Find actual filename
    fname = next((f for f in _os2.listdir(_AI_DATA_DIR)
                  if fkey_upper in f.upper()), None)
    if not fname:
        return f'[File matching "{fkey}" not found in data/]'

    fup = fname.upper()

    # ── BJP Boothwise ─────────────────────────────────────────────────────────
    if 'BJP_BOOTHWISE' in fup or 'BJP_B' in fup[:10]:
        return _rag_load_xlsx_smart(fname, message,
            priority_sheets=['📍 BOOTHWISE MASTER', '📊 WARD CONSOLIDATED'],
            keyword_sheet_map={
                'caste':      ['🕉 COMMUNITY ANALYSIS', '⚧ RELIGION × GENDER'],
                'religion':   ['🕉 COMMUNITY ANALYSIS', '⚧ RELIGION × GENDER'],
                'priority':   ['🎯 BOOTH PRIORITY LIST', '📈 TURNOUT STRATEGY'],
                'turnout':    ['🎯 BOOTH PRIORITY LIST', '📈 TURNOUT STRATEGY'],
                'strategy':   ['🎯 BOOTH PRIORITY LIST', '📈 TURNOUT STRATEGY'],
            }, max_chars=60_000)

    # ── BJP Political Intelligence ────────────────────────────────────────────
    if 'BJP_POLITICAL' in fup or 'BJP_P' in fup[:10]:
        return _rag_load_xlsx_smart(fname, message,
            priority_sheets=['📊 EXECUTIVE DASHBOARD'],
            keyword_sheet_map={
                'strategy':   ['🎯 STRATEGY GAMEPLAN'],
                'gameplan':   ['🎯 STRATEGY GAMEPLAN'],
                'action':     ['✅ WARD ACTION TRACKER', '📅 CAMPAIGN CALENDAR'],
                'caste':      ['🕉 CASTE-RELIGION MATRIX'],
                'religion':   ['🕉 CASTE-RELIGION MATRIX'],
                'history':    ['📅 HISTORICAL TREND 2013-23'],
                'trend':      ['📅 HISTORICAL TREND 2013-23'],
                'wsi':        ['🏆 WSI SCORE + SUMMARY'],
                'score':      ['🏆 WSI SCORE + SUMMARY'],
                'math':       ['🧮 MATH FORMULA & EQUATIONS'],
                'formula':    ['🧮 MATH FORMULA & EQUATIONS'],
                'manifesto':  ['📋 POLICY & MANIFESTO'],
                'policy':     ['📋 POLICY & MANIFESTO'],
                'weak':       ['🔍 WHY STRONG-MEDIUM-WEAK'],
                'strong':     ['🔍 WHY STRONG-MEDIUM-WEAK'],
            }, max_chars=55_000)

    # ── Mangaluru Election Strategy ───────────────────────────────────────────
    if 'MANGALURU_ELECTION' in fup:
        return _rag_load_xlsx_smart(fname, message,
            priority_sheets=['📊 EXECUTIVE DASHBOARD'],
            keyword_sheet_map={
                'ward':       ['🏛️ WARD DEEP ANALYSIS'],
                'booth':      ['🗳️ BOOTH ANALYSIS (244)'],
                'caste':      ['🕌 CASTE & RELIGION'],
                'religion':   ['🕌 CASTE & RELIGION'],
                'gender':     ['👩 GENDER ANALYSIS'],
                'women':      ['👩 GENDER ANALYSIS'],
                'weak':       ['🔴 WEAK→MEDIUM PLAN'],
                'medium':     ['🟡 MEDIUM→STRONG PLAN'],
                'action':     ['📅 90-DAY ACTION PLAN'],
                '90':         ['📅 90-DAY ACTION PLAN'],
                'intervention':['🚨 BOOTH INTERVENTION LIST'],
                'sir':        ['📋 SIR & VOTER STATUS'],
            }, max_chars=60_000)

    # ── Mangaluru FULLSCALE ───────────────────────────────────────────────────
    if 'MANGALURU_FULLSCALE' in fup or 'FULLSCALE' in fup:
        return _rag_load_xlsx_smart(fname, message,
            priority_sheets=['📊 MASTER DASHBOARD'],
            keyword_sheet_map={
                'ward':       ['🏛️ WARD ANALYSIS (FULL)'],
                'booth':      ['🗳️ BOOTH ANALYSIS (244)'],
                'caste':      ['🕌 CASTE TURNOUT MATRIX'],
                'religion':   ['🕌 CASTE TURNOUT MATRIX'],
                'non polled': ['⚡ NON-POLLED OPPORTUNITY'],
                'nonpolled':  ['⚡ NON-POLLED OPPORTUNITY'],
                'opportunity':['⚡ NON-POLLED OPPORTUNITY'],
                'gender':     ['👩 GENDER ANALYSIS'],
                'flip':       ['🎯 FLIP TARGETS'],
                'target':     ['🎯 FLIP TARGETS'],
                'strong':     ['🟢 STRONG WARD GAMEPLAN'],
                'medium':     ['🟡 MEDIUM→STRONG PLAN'],
                'weak':       ['🔴 WEAK→MEDIUM PLAN'],
                '100':        ['📅 100-DAY GAMEPLAN'],
                'gameplan':   ['📅 100-DAY GAMEPLAN'],
            }, max_chars=60_000)

    # ── Historical election files (2013/2014/2018/2019) ───────────────────────
    if any(yr in fup for yr in ['2013', '2014', '2018', '2019']):
        # Determine priority sheets based on year
        priority = []
        msg_lower = message.lower()
        if '2019' in fup:
            priority = ['Sheet1']
        elif '2018' in fup and '2014' in fup:
            priority = ['2014 AND 2018 SATATISTICAL ANLY', 'BJP WIN OR LOSS']
        elif '2018' in fup:
            priority = ['WARDWISE ANALYISIS', 'BJP WIN OR LOSS']
        elif '2014' in fup:
            priority = ['WARD WISE ANALYSIS', 'BJP WIN OR LOSS']
        elif '2013' in fup:
            priority = ['WARD WISE ANALYSIS', '3 YEAR WARD WISE ANALYSIS', 'BJP WIN OR LOSS']
        return _rag_load_xlsx_smart(fname, message,
            priority_sheets=priority,
            keyword_sheet_map={
                'bjp':        ['BJP', 'BJP WIN OR LOSS'],
                'congress':   ['CONGRESS', 'BJP WIN OR LOSS'],
                'booth':      ['2013 BOOTH WISE', '2013+  BOOTH WISE ANALYSIS',
                               '2014 BOOTH WISE', '2018 BOOTHWISE', 'BOOTH WISE'],
            }, max_chars=55_000)

    # ── Generic fallback ──────────────────────────────────────────────────────
    path = _os2.path.join(_AI_DATA_DIR, fname)
    ext  = _os2.path.splitext(fname)[1].lower()
    try:
        if ext in ('.xlsx', '.xls'):
            raw = _ai_read_excel_stream(path)
        elif ext == '.csv':
            raw = _ai_read_csv_stream(path)
        else:
            with open(path, 'r', encoding='utf-8', errors='ignore') as _f:
                raw = _f.read()
        return raw[:30_000]
    except Exception as e:
        return f'[{fname} read error: {e}]'


# ── Intent map: message keywords → which mongo builders + file keys ───────────
_RAG_INTENT_MAP = {
    'voter_roll': {
        'kw': ['voter', 'elector', 'registered', '2025', '2024', '2002',
               'gender', 'male', 'female', 'total voters'],
        'mongo': ['2025 Voter Roll (Ward Summary)', 'Booth-wise Counts'],
        'files': [],
    },
    'caste_community': {
        'kw': ['caste', 'community', 'bunt', 'billava', 'brahmin', 'muslim',
               'christian', 'hindu', 'minority', 'obc', 'sc', 'st', 'tulu',
               'konkani', 'beary', 'surname', 'religion'],
        'mongo': ['Community/Caste Count 2023', 'Coastal Karnataka Caste Reference'],
        'files': [],
    },
    'polling_2023': {
        'kw': ['2023', 'polled', 'not polled', 'polling', 'turnout', 'voted',
               'non polled', 'election result', 'win', 'lost', 'victory',
               'margin', 'vote share', 'bjp', 'congress', 'inc',
               'lobo', 'kamath', 'candidate'],
        'mongo': ['2023 Polling Data', 'Polled/NotPolled with Caste 2023'],
        'files': ['2023p'],
    },
    'bjp_strategy': {
        'kw': ['bjp strategy', 'booth strategy', 'political intelligence',
               'wsi', 'gameplan', 'manifesto', 'action plan', 'priority booth',
               'strong medium weak', '5 pillar', 'ward action', 'campaign calendar'],
        'mongo': [],
        'files': ['BJP_Boothwise', 'BJP_Political'],
    },
    'ward_booth_info': {
        'kw': ['blo', 'supervisor', 'mapped', 'cutoff', 'progeny',
               'electors mapped', 'ward info', 'booth info', 'booth detail'],
        'mongo': ['Ward Information (2026)', 'Booth Details'],
        'files': [],
    },
    'survey': {
        'kw': ['survey', 'socio', 'economic', 'employment', 'health',
               'education', 'scheme', 'outstation', 'differently abled',
               'family survey', 'not found survey', 'nonpolled survey'],
        'mongo': ['Survey Records', 'NotFoundRecordSurvey', 'Socio-Economic Data (Data collection)'],
        'files': [],
    },
    'sir': {
        'kw': ['sir', 'revision', 'new addition', 'deleted', 'suspicious',
               'not found', 'genuine', 'bogus', 'dead voter', 'ghost voter',
               'phantom', 'duplicate'],
        'mongo': ['SIR Analysis (2002 vs 2025)', 'Genuine Voters (SIR Verified)', '2002 Voter Roll'],
        'files': [],
    },
    'deceased_future': {
        'kw': ['deceased', 'dead', 'death', 'future voter', 'youth',
               'eligible', '2028', 'new voter', 'young voter'],
        'mongo': ['Future Voters & Deceased'],
        'files': [],
    },
    'election_2019': {
        'kw': ['2019'],
        'mongo': [],
        'files': ['2019_full'],
    },
    'election_2018': {
        'kw': ['2018'],
        'mongo': [],
        'files': ['2018_WARD_WISE', '2014_AND_2018'],
    },
    'election_2014': {
        'kw': ['2014'],
        'mongo': [],
        'files': ['2014_STATISTICAL', '2014_AND_2018'],
    },
    'election_2013': {
        'kw': ['2013'],
        'mongo': [],
        'files': ['2013_WARD_WISE', '2013__WARD_WISE', '2013__2013__AND'],
    },
    'history': {
        'kw': ['historical', 'history', 'past election', 'previous election',
               'trend', 'across years', 'all elections', 'compare elections',
               '5 election', 'five election', 'decade', 'decadal'],
        'mongo': [],
        'files': ['2013__2013__AND', '2014_WARD_WISE', '2019_full'],
    },
    'analysis': {
        'kw': ['analyse', 'analysis', 'compare', 'comparison', 'priority ward',
               'strategic', 'report', 'fullscale', 'flip', 'target ward',
               'non polled opportunity', 'weak to medium', 'medium to strong',
               '90 day', '100 day', 'booth intervention', 'deep analysis'],
        'mongo': ['2023 Polling Data'],
        'files': ['Mangaluru_Election', 'Mangaluru_FULLSCALE'],
    },
    'swot': {
        'kw': ['swot', 'strength', 'weakness', 'opportunity', 'threat',
               'strengths', 'weaknesses', 'opportunities', 'threats'],
        'mongo': ['SWOT Query Stack (NewQueryStack1)', '2023 Polling Data'],
        'files': [],
    },
}

# All existing mongo context builder labels → callable map
_RAG_MONGO_ALL = {
    '2025 Voter Roll (Ward Summary)':         _ai_ctx_voter_roll_summary,
    'Survey Records':                          _ai_ctx_survey_summary,
    '2023 Polling Data':                       _ai_ctx_polling_summary,
    'SIR Analysis (2002 vs 2025)':             _ai_ctx_sir_summary,
    'Booth-wise Counts':                       _ai_ctx_booth_summary,
    'Future Voters & Deceased':                _ai_ctx_future_deceased,
    'Community/Caste Count 2023':              _ai_ctx_caste_count_2023,
    'Polled/NotPolled with Caste 2023':        _ai_ctx_polled_notpolled_caste,
    'Ward Information (2026)':                 _ai_ctx_ward_booth_2026,
    'Booth Details':                           _ai_ctx_ward_booth_details,
    'NotFoundRecordSurvey':                    _ai_ctx_not_found_survey,
    'Coastal Karnataka Caste Reference':       _ai_ctx_coastal_caste_reference,
    'SWOT Query Stack (NewQueryStack1)':       _ai_ctx_swot_stack,
    '2002 Voter Roll':                         _ai_ctx_voter_roll_2002,
    'Genuine Voters (SIR Verified)':           _ai_ctx_genuine_voters,
    'Socio-Economic Data (Data collection)':   _ai_ctx_socio_economic_data,
}


def _rag_fetch_context(message: str) -> tuple:
    """
    Main RAG entry point.
    Classifies message → runs only needed MongoDB builders + smart file chunks.
    Returns (context_text, sources_list).
    """
    msg_lower      = message.lower()
    needed_mongo   = []   # ordered, deduped labels
    needed_files   = []   # ordered, deduped file keys
    matched_intents = []

    for intent, cfg in _RAG_INTENT_MAP.items():
        if any(kw in msg_lower for kw in cfg['kw']):
            matched_intents.append(intent)
            for lbl in cfg['mongo']:
                if lbl not in needed_mongo:
                    needed_mongo.append(lbl)
            for fk in cfg['files']:
                if fk not in needed_files:
                    needed_files.append(fk)

    # Default: voter roll + polling for general questions
    if not matched_intents:
        needed_mongo = ['2025 Voter Roll (Ward Summary)', '2023 Polling Data']

    print(f'[RAG] Intents: {matched_intents} | Mongo: {needed_mongo} | Files: {needed_files}')

    sections = []
    sources  = []

    # ── MongoDB (parallel) ────────────────────────────────────────────────────
    mongo_results = {}
    def _run_mongo(label):
        fn = _RAG_MONGO_ALL.get(label)
        if not fn:
            return label, f'[{label}: not found]'
        try:
            return label, fn()
        except Exception as e:
            return label, f'[{label} error: {e}]'

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_run_mongo, lbl): lbl for lbl in needed_mongo}
        for future in as_completed(futures):
            lbl, text = future.result()
            mongo_results[lbl] = text

    # Preserve order
    for lbl in needed_mongo:
        text = mongo_results.get(lbl, '')
        if text:
            sections.append(text)
            sources.append(f'MongoDB:{lbl}')

    # ── Files (smart chunked) ─────────────────────────────────────────────────
    FILE_CHAR_BUDGET = 120_000   # ~30k tokens max across all files
    total_file_chars = 0

    for fkey in needed_files:
        if total_file_chars >= FILE_CHAR_BUDGET:
            print(f'[RAG] File budget reached, skipping: {fkey}')
            break
        try:
            text = _rag_load_file(fkey, message)
            if text and not text.startswith('['):
                remaining = FILE_CHAR_BUDGET - total_file_chars
                text = text[:remaining]
                sections.append(text)
                sources.append(f'File:{fkey}')
                total_file_chars += len(text)
        except Exception as e:
            print(f'[RAG] File load error {fkey}: {e}')

    context_text = '\n\n'.join(sections)
    total_chars  = len(context_text)
    print(f'[RAG] Total: {total_chars:,} chars (~{total_chars//4:,} tokens) | '
          f'Sources: {len(sources)} | {sources}')
    return context_text, sources


def _ai_load_mongo_context():
    """
    Run all 16 MongoDB context builders in parallel.
    Returns (combined_text: str, sources: list[str]).
    Total latency ≈ slowest single builder (~1-2 s), not sum of all.
    """
    builders = [
        ('2025 Voter Roll (Ward Summary)',        _ai_ctx_voter_roll_summary),
        ('Survey Records',                        _ai_ctx_survey_summary),
        ('2023 Polling Data',                     _ai_ctx_polling_summary),
        ('SIR Analysis (2002 vs 2025)',            _ai_ctx_sir_summary),
        ('Booth-wise Counts',                     _ai_ctx_booth_summary),
        ('Future Voters & Deceased',              _ai_ctx_future_deceased),
        ('Community/Caste Count 2023',            _ai_ctx_caste_count_2023),
        ('Polled/NotPolled with Caste 2023',      _ai_ctx_polled_notpolled_caste),
        ('Ward Information (2026)',               _ai_ctx_ward_booth_2026),
        ('Booth Details',                         _ai_ctx_ward_booth_details),
        ('NotFoundRecordSurvey',                  _ai_ctx_not_found_survey),
        ('Coastal Karnataka Caste Reference',     _ai_ctx_coastal_caste_reference),
        ('SWOT Query Stack (NewQueryStack1)',      _ai_ctx_swot_stack),
        ('2002 Voter Roll',                       _ai_ctx_voter_roll_2002),
        ('Genuine Voters (SIR Verified)',         _ai_ctx_genuine_voters),
        ('Socio-Economic Data (Data collection)', _ai_ctx_socio_economic_data),
    ]

    results = [None] * len(builders)
    sources = []

    def _run(idx, label, fn):
        try:
            print(f'[AI Chat RAG] Loading: {label}')
            text = fn()
            return idx, label, text, True
        except Exception as e:
            return idx, label, f'[{label} — error: {e}]', False

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_run, i, lbl, fn): i
                   for i, (lbl, fn) in enumerate(builders)}
        for future in as_completed(futures):
            idx, label, text, ok = future.result()
            results[idx] = text
            if ok:
                sources.append(label)

    combined = '\n\n'.join(r for r in results if r)
    return combined, sources


# ════════════════════════════════════════════════════════════════════════════════
# FILES API — upload-once, reuse-by-ID, smart xlsx chunker
# ════════════════════════════════════════════════════════════════════════════════

import threading as _threading

_AI_FILE_ID_CACHE: dict  = {}
_AI_FILE_CACHE_LOCK      = _threading.Lock()

_FILES_API_MIME = {
    '.pdf' : 'application/pdf',
    '.txt' : 'text/plain',
    '.csv' : 'text/plain',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.doc' : 'application/msword',
    '.md'  : 'text/plain',
}
_FILES_API_CONVERT = {'.xlsx', '.xls'}

# ── Sheet description lookup ──────────────────────────────────────────────────

_SHEET_DESC_MAP = {
    'BOOTHWISE'               : 'Per-booth election results (BJP/INC/JDS%)',
    'BOOTH WISE'              : 'Per-booth election results (BJP/INC/JDS%)',
    'WARD WISE ANALYSIS'      : 'Ward-level statistical analysis (mean, std dev, variance)',
    'WARDWISE ANALYISIS'      : 'Ward-level statistical analysis (2018)',
    '3 YEAR WARD WISE ANALYSIS': '3-year ward comparison (2013, 2013+, 2018)',
    'BJP WIN OR LOSS'         : 'Which booths/wards BJP won or lost',
    'BJP'                     : 'BJP narrow-margin wards ranked by margin',
    'CONGRESS'                : 'Congress narrow-margin wards ranked by margin',
    'WARD-BOOTH'              : 'Ward to booth mapping / ward+booth election summary',
    'MAIN WARD'               : 'Ward-level election summary',
    'EXECUTIVE DASHBOARD'     : 'BJP executive summary: strong/medium/weak wards',
    'WHY STRONG-MEDIUM-WEAK'  : 'Root cause analysis of ward performance',
    'CASTE-RELIGION MATRIX'   : 'Caste × religion × gender voter matrix',
    'HISTORICAL TREND 2013-23': 'BJP electoral trend 2013–2023 by ward',
    'MATH FORMULA'            : 'Political math formulas for vote share projection',
    'STRATEGY GAMEPLAN'       : 'BJP 5-pillar victory strategy',
    'WARD ACTION TRACKER'     : 'Live ward-level operational tracking template',
    'CAMPAIGN CALENDAR'       : 'T-12 to T-0 month campaign calendar',
    'WSI SCORE'               : 'Ward Strength Index (BJP%×35% + Turnout×25% + ...)',
    'BOOTHWISE MASTER'        : '249-booth caste × religion × turnout master table',
    'WARD CONSOLIDATED'       : 'Ward-consolidated caste/religion analysis',
    'COMMUNITY ANALYSIS'      : 'Community-wise turnout rankings',
    'RELIGION'                : 'Religion × gender turnout (male/female split)',
    'BOOTH PRIORITY LIST'     : 'Booth priority ranking by latent BJP votes',
    'TURNOUT STRATEGY'        : 'Mathematical turnout targets by booth',
    'MASTER DASHBOARD'        : 'Full-scale master dashboard: ward+booth overview',
    'WARD ANALYSIS'           : 'Ward-wise full analysis: 2023+2018+caste',
    'BOOTH ANALYSIS'          : '244/249-booth analysis: status, BJP%, margin, poll change',
    'CASTE TURNOUT MATRIX'    : 'Minority/GC/OBC/unclassified turnout by ward',
    'NON-POLLED OPPORTUNITY'  : 'Non-polled voter opportunity by ward and community',
    'GENDER ANALYSIS'         : 'Female-dominant booths, gender mobilization strategy',
    'STRONG WARD'             : 'Protection strategy for strong BJP wards',
    'MEDIUM'                  : 'Upgrade plan for medium wards → strong',
    'WEAK'                    : 'Conversion plan for weak wards → medium',
    'FLIP TARGET'             : 'Wards and booths where BJP can flip Congress seats',
    '100-DAY'                 : '100-day fool-proof campaign gameplan',
    '90-DAY'                  : '90-day master action plan with phases',
    'BOOTH INTERVENTION'      : 'Booth-level intervention sorted by margin (worst first)',
    'SIR'                     : 'BLO mapping %, progeny %, BJP/Congress projections by ward',
    'WARD DEEP'               : 'Multi-dimensional ward analysis with caste + polling',
    'CASTE & RELIGION'        : 'Caste+religion profile: Muslim% → Congress / Hindu → BJP',
    'ATTAVARA'                : 'ATTAVARA ward: 2023 vs 2018 booth-wise results',
    'ALAPE'                   : 'ALAPE ward: 2023 vs 2018 booth-wise results',
    'BAJAL'                   : 'BAJAL ward: 2023 vs 2018 booth-wise results',
    'BEJAI'                   : 'BEJAI ward: 2023 vs 2018 booth-wise results',
    'BENGRE'                  : 'BENGRE ward: 2023 vs 2018 booth-wise results',
    'BOLOOR'                  : 'BOLOOR ward: 2023 vs 2018 booth-wise results',
    'BOLAR'                   : 'BOLAR ward: 2023 vs 2018 booth-wise results',
    'BUNDER'                  : 'BUNDER/NAVAYATH ward: 2023 vs 2018 booth-wise results',
    'CENTRAL'                 : 'CENTRAL ward: 2023 vs 2018 booth-wise results',
    'CONTONMENT'              : 'CANTONMENT ward: 2023 vs 2018 booth-wise results',
    'COURT'                   : 'COURT ward: 2023 vs 2018 booth-wise results',
    'DEREBAIL'                : 'DEREBAIL ward: 2023 vs 2018 booth-wise results',
    'DONGAR'                  : 'DONGERKERY ward: 2023 vs 2018 booth-wise results',
    'FALNIR'                  : 'FALNIR ward: 2023 vs 2018 booth-wise results',
    'HOIGE'                   : 'HOIGE BAZAR ward: 2023 vs 2018 booth-wise results',
    'JEPPINAMOGAR'            : 'JEPPINAMUGER ward: 2023 vs 2018 booth-wise results',
    'JEPPU'                   : 'JEPPU ward: 2023 vs 2018 booth-wise results',
    'KADRI'                   : 'KADRI ward: 2023 vs 2018 booth-wise results',
    'KAMBALA'                 : 'KAMBLA ward: 2023 vs 2018 booth-wise results',
    'KANKANADY'               : 'KANKANADY ward: 2023 vs 2018 booth-wise results',
    'KANNUR'                  : 'KANNUR ward: 2023 vs 2018 booth-wise results',
    'KODIALBAIL'              : 'KODIALBAIL ward: 2023 vs 2018 booth-wise results',
    'KUDROLI'                 : 'KUDROLI ward: 2023 vs 2018 booth-wise results',
    'MANNAGUDA'               : 'MANNAGUDDA ward: 2023 vs 2018 booth-wise results',
    'MAROLI'                  : 'MAROLI ward: 2023 vs 2018 booth-wise results',
    'MILAGRESS'               : 'MILAGRIS ward: 2023 vs 2018 booth-wise results',
    'PADAV'                   : 'PADAVU ward variant: 2023 vs 2018 booth-wise results',
    'PORT'                    : 'PORT ward: 2023 vs 2018 booth-wise results',
    'SHIVABAGH'               : 'SHIVBHAG ward: 2023 vs 2018 booth-wise results',
    'VALENCIA'                : 'VALENCIA ward: 2023 vs 2018 booth-wise results',
}


def _sheet_description(sheet_name: str) -> str:
    clean = _re2.sub(r'[^\x00-\x7F]+', '', sheet_name).strip().upper()
    for key, desc in _SHEET_DESC_MAP.items():
        if key in clean:
            return desc
    return f'Data sheet: {sheet_name}'


# ── Smart xlsx → rich text converter ─────────────────────────────────────────

def _xlsx_to_csv_bytes(path: str) -> bytes:
    """
    Convert xlsx to a rich, RAG-friendly text format.

    Each sheet gets:
      ## SHEET: <name>
      ## DESCRIPTION: <auto-detected meaning>
      ## COLUMNS (N): col1, col2, ...
      ## ROWS: N
      <CSV data rows>

    Multi-row headers (rows 2+3 both containing headers) are merged.
    Title/subtitle rows (row 1 with ≤2 non-empty cells) are skipped.
    Up to 1000 data rows per sheet.
    """
    MAX_ROWS = 1000
    MIN_HDR  = 3      # min non-empty cells to qualify as a header row

    try:
        import openpyxl as _opxl
        # First attempt: normal load.
        # Some xlsx files have corrupt merged-cell ranges that make openpyxl
        # crash deep inside bind_merged_cells(), raising SystemExit via gunicorn's
        # SIGKILL handler — which bypasses a plain `except Exception`.
        # Fallback: read_only=True skips merge-cell processing entirely.
        try:
            wb = _opxl.load_workbook(path, data_only=True)
        except BaseException as _wb_err:
            print(f'[xlsx loader] Normal load failed for {path}: {_wb_err!r} — retrying read_only')
            try:
                wb = _opxl.load_workbook(path, data_only=True, read_only=True)
            except BaseException as _wb_err2:
                raise RuntimeError(f'openpyxl failed (normal + read_only): {_wb_err2}') from _wb_err2
        buf = _io.StringIO()

        fname = path.split('/')[-1]
        buf.write(f'# FILE: {fname}\n')
        buf.write(f'# Sheets ({len(wb.sheetnames)}): {", ".join(wb.sheetnames)}\n\n')

        for sname in wb.sheetnames:
            ws = wb[sname]

            # Collect rows (limit to MAX_ROWS + 10 header rows)
            all_rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= MAX_ROWS + 10:
                    break
                all_rows.append(['' if c is None else str(c).strip() for c in row])

            if not all_rows:
                continue

            # Find header row (first row with ≥ MIN_HDR non-empty cells)
            hdr_idx = 0
            for idx, row in enumerate(all_rows[:6]):
                ne = [c for c in row if c and c not in ('None', 'nan', '')]
                if len(ne) >= MIN_HDR:
                    hdr_idx = idx
                    break

            headers    = all_rows[hdr_idx]
            data_start = hdr_idx + 1

            # Merge two-row headers (e.g. row2+row3 both have partial headers)
            if hdr_idx + 1 < len(all_rows):
                nr  = all_rows[hdr_idx + 1]
                mc  = sum(1 for i, h in enumerate(nr)
                          if h and i < len(headers) and not headers[i])
                if mc >= 2:
                    merged = []
                    for i in range(max(len(headers), len(nr))):
                        h  = headers[i] if i < len(headers) else ''
                        n_ = nr[i]      if i < len(nr)      else ''
                        merged.append((h + ' ' + n_).strip() if h and n_ else (h or n_))
                    headers    = merged
                    data_start = hdr_idx + 2

            # Clean column names
            def _clean(c):
                c = _re2.sub(r'[^\x00-\x7F]+', '', c).strip()
                c = _re2.sub(r'\s+', ' ', c)
                return c or 'col'

            clean_hdrs = [_clean(h) for h in headers]
            while clean_hdrs and clean_hdrs[-1] in ('', 'col'):
                clean_hdrs.pop()

            # Filter blank data rows
            data_rows = [
                r for r in all_rows[data_start: data_start + MAX_ROWS]
                if any(c for c in r if c and c not in ('None', 'nan'))
            ]

            desc = _sheet_description(sname)
            buf.write(f'## SHEET: {sname}\n')
            buf.write(f'## DESCRIPTION: {desc}\n')
            buf.write(f'## COLUMNS ({len(clean_hdrs)}): {", ".join(clean_hdrs[:12])}'
                      f'{"..." if len(clean_hdrs) > 12 else ""}\n')
            buf.write(f'## ROWS: {len(data_rows)}\n\n')

            buf.write(','.join(clean_hdrs) + '\n')
            for row in data_rows:
                padded  = (list(row) + [''] * max(0, len(clean_hdrs) - len(row)))[:len(clean_hdrs)]
                escaped = []
                for cell in padded:
                    cell = str(cell).replace('\n', ' ').replace('\r', '')
                    if ',' in cell or '"' in cell:
                        cell = '"' + cell.replace('"', '""') + '"'
                    escaped.append(cell)
                buf.write(','.join(escaped) + '\n')

            buf.write('\n')

        wb.close()
        return buf.getvalue().encode('utf-8')

    except BaseException as e:
        # BaseException (not just Exception) is required here because openpyxl can
        # trigger gunicorn's signal handler mid-stack, raising SystemExit, which
        # is NOT a subclass of Exception and would otherwise escape this handler.
        return f'[Excel conversion error for {path}: {e}]'.encode('utf-8')


def _get_or_upload_file(client, fname: str, path: str) -> tuple:
    """
    Return (file_id, display_name, mime_type).
    Uploads to Anthropic Files API once; caches by (name, mtime, size).
    Returns (None, fname, None) on failure — caller falls back to inline text.
    """
    try:
        stat      = _os2.stat(path)
        cache_key = (fname, int(stat.st_mtime), stat.st_size)
    except Exception:
        return None, fname, None

    with _AI_FILE_CACHE_LOCK:
        if cache_key in _AI_FILE_ID_CACHE:
            fid = _AI_FILE_ID_CACHE[cache_key]
            print(f'[Files API] Cache hit: {fname} → {fid}')
            return fid, fname, None

    ext = _os2.path.splitext(fname)[1].lower()

    try:
        if ext in _FILES_API_CONVERT:
            try:
                file_bytes = _xlsx_to_csv_bytes(path)   # ← smart chunker
            except BaseException as _conv_err:
                # Corrupt xlsx can raise SystemExit (gunicorn SIGKILL) which
                # escapes a plain `except Exception`. Catch it here so one bad
                # file never brings down the whole request worker.
                print(f'[Files API] xlsx conversion raised {type(_conv_err).__name__} '
                      f'for {fname}: {_conv_err!r} — skipping file')
                return None, fname, None
            upload_name = fname.rsplit('.', 1)[0] + '.txt'
            mime        = 'text/plain'
        elif ext in _FILES_API_MIME:
            with open(path, 'rb') as f:
                file_bytes = f.read()
            upload_name = fname
            mime        = _FILES_API_MIME[ext]
        else:
            with open(path, 'rb') as f:
                file_bytes = f.read()
            upload_name = fname
            mime        = 'text/plain'

        size_mb = len(file_bytes) / (1024 * 1024)
        print(f'[Files API] Uploading: {fname} → {upload_name} ({size_mb:.2f} MB)')

        import io as _io3
        response = client.beta.files.upload(
            file=(upload_name, _io3.BytesIO(file_bytes), mime),
        )
        fid = response.id
        print(f'[Files API] Uploaded: {fname} → {fid}')

        with _AI_FILE_CACHE_LOCK:
            _AI_FILE_ID_CACHE[cache_key] = fid

        return fid, fname, mime

    except BaseException as e:
        print(f'[Files API] Upload failed for {fname}: {e}')
        return None, fname, None


# ── Keyword → file selector ───────────────────────────────────────────────────
# Token budget: 200k - 4096 output - ~40k overhead = ~156k for files
# TIER1 alone = 151,250 tokens → 97.7% of window, safe.
# Extra files only load if a specific keyword is detected AND budget allows.

_TIER1_FILES = {
    '2023p.xlsx',
    'Mangaluru_FULLSCALE_Analysis_v2.xlsx',
    'Mangaluru_Election_Strategy_Report.xlsx',
}

# Remaining token budget after Tier1 = ~4,504 — only tiny files fit
# Add keyword-triggered extras only when budget allows
_KW_FILES = {
    r'2019|lok sabha':          ('2019_full_data4.xlsx',              7938),
    r'strategy|wsi|gameplan|intel': ('BJP_Political_Intelligence_System.xlsx', 12672),
    r'caste|community|turnout': ('BJP_Boothwise_CasteReligion_Turnout_Strategy.xlsx', 19471),
    r'2018':                    ('2018_WARD_WISE_STATISTICAL_ANALYSIS__BOOTHWISE_SEGREGATION_FINAL.xlsx', 29746),
    r'2014':                    ('2014_STATISTICAL_ANALYSIS.xlsx',    21922),
    r'2013':                    ('2013_WARD_WISE_STATISTICAL_ANALYSIS.xlsx', 17397),
}
_FILE_TOKEN_BUDGET = 155_000   # hard ceiling — never exceed this

def _select_files_for_message(message: str) -> list:
    """Return ordered list of filenames to load, respecting token budget."""
    ml      = message.lower() if message else ''
    selected = list(_TIER1_FILES)
    used     = sum(t for kw, (fn, t) in _KW_FILES.items() if fn in _TIER1_FILES)
    # Recalculate tier1 actual tokens
    tier1_tok = 87_570 + 35_037 + 28_643   # 151,250
    used = tier1_tok

    for pattern, (fname, ftok) in _KW_FILES.items():
        if fname in selected:
            continue
        if re.search(pattern, ml) and (used + ftok) <= _FILE_TOKEN_BUDGET:
            selected.append(fname)
            used += ftok

    return selected


def _ai_load_files_api(client, message: str = '') -> tuple:
    """
    Upload files in backend/data/ to Anthropic Files API.
    Only loads files selected by _select_files_for_message() to stay
    within the 200k context window.
    Returns (document_blocks, files_used, fallback_text).
    """
    document_blocks = []
    files_used      = []
    fallback_parts  = []

    if not _os2.path.isdir(_AI_DATA_DIR):
        return [], [], ''

    # Which files to load for this specific message
    wanted   = set(_select_files_for_message(message))
    all_files = sorted(_os2.listdir(_AI_DATA_DIR))

    for fname in all_files:
        if fname not in wanted:
            continue

        ext  = _os2.path.splitext(fname)[1].lower()
        path = _os2.path.join(_AI_DATA_DIR, fname)
        fid, display, mime = _get_or_upload_file(client, fname, path)

        if fid:
            document_blocks.append({
                'type'   : 'document',
                'source' : {'type': 'file', 'file_id': fid},
                'title'  : fname,
                'context': (
                    f'Election/political data file: {fname}. '
                    f'Each section is prefixed with ## SHEET: <name> and '
                    f'## DESCRIPTION: <what the sheet contains>.'
                ),
            })
            files_used.append(fname)
        else:
            # Fallback — inline text extraction
            print(f'[Files API] Falling back to inline text for: {fname}')
            try:
                if ext in ('.xlsx', '.xls'):
                    raw = _xlsx_to_csv_bytes(path).decode('utf-8', errors='ignore')
                elif ext == '.csv':
                    raw = _ai_read_csv_stream(path)
                elif ext == '.pdf':
                    raw = _ai_read_pdf_stream(path)
                elif ext in ('.docx', '.doc'):
                    raw = _ai_read_docx_stream(path)
                else:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        raw = f.read()
                excerpt = raw[:_AI_CHARS_PER_FILE]
                fallback_parts.append(f'===== FILE: {fname} =====\n{excerpt}')
                files_used.append(fname + ' (inline)')
            except BaseException as e:
                print(f'[Files API] Inline fallback also failed for {fname}: {e}')

    fallback_text = '\n\n'.join(fallback_parts)
    print(f'[Files API] Ready: {len(document_blocks)} via Files API, '
          f'{len(fallback_parts)} inline fallbacks '
          f'(wanted: {sorted(wanted)})')
    return document_blocks, files_used, fallback_text


def _ai_read_csv_stream(path):
    try:
        chunks, total_rows = [], 0
        for chunk in pd.read_csv(path, chunksize=1000, encoding='utf-8',
                                  on_bad_lines='skip', low_memory=False):
            chunks.append(chunk.fillna(''))
            total_rows += len(chunk)
            if total_rows >= _AI_CSV_MAX_ROWS:
                break
        if not chunks:
            return '[Empty CSV]'
        df = pd.concat(chunks).head(_AI_CSV_MAX_ROWS)
        return f'({len(df):,} rows)\n{df.to_string(index=False)}'
    except Exception as e:
        return f'[CSV read error: {e}]'


def _ai_read_pdf_stream(path):
    if not _PYMUPDF_OK:
        return '[PyMuPDF not installed]'
    try:
        doc   = _fitz.open(path)
        pages = []
        for i in range(min(_AI_PDF_MAX_PAGES, len(doc))):
            pages.append(f'[Page {i + 1}]\n{doc[i].get_text()}')
        doc.close()
        return '\n'.join(pages)
    except Exception as e:
        return f'[PDF read error: {e}]'


def _ai_read_docx_stream(path):
    if not _DOCX_LIB_OK:
        return '[python-docx not installed]'
    try:
        doc = _docx_lib.Document(path)
        return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return f'[Docx read error: {e}]'


# ════════════════════════════════════════════════════════════════════════════════
# SIMPLE-INTENT DETECTION
# ════════════════════════════════════════════════════════════════════════════════

_SIMPLE_INTENT_RE = _re2.compile(
    r'^\s*('
    r'hi+|hello+|hey+|howdy|'
    r'good\s*(morning|afternoon|evening|night|day)|'
    r'thanks?(\s+you)?|thank\s*you|ty|'
    r'ok(ay)?|sure|yep|yeah|yup|nope|no+|yes+|'
    r'great|cool|awesome|nice|got\s*it|understood|'
    r'bye+|goodbye|see\s*ya|'
    r'what\s+(can|do)\s+you\s+do|'
    r'who\s+are\s+you|'
    r'help'
    r')\s*[!?.]*\s*$',
    _re2.IGNORECASE,
)


def _is_simple_message(msg: str) -> bool:
    return bool(_SIMPLE_INTENT_RE.match(msg.strip()))


# ════════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ════════════════════════════════════════════════════════════════════════════════

_AI_CHAT_SYSTEM = """You are an expert political data analyst and constituency intelligence assistant for the Mangaluru South Assembly Constituency (Constituency 175), Karnataka, India.

**Important behavioural rule**: If the user sends a simple greeting (e.g. "hi", "hello", "thanks", "bye") or a purely conversational message, reply warmly and naturally — do NOT reference data sources, tables, charts, or MongoDB context. Reserve data analysis only for questions that actually require it.

You have access to LIVE data from MongoDB (aggregated summaries in the MONGODB DATA section below) PLUS the full content of data files supplied as document attachments via Anthropic Files API. All data is real and current.

## MongoDB Collections (Live Aggregated Summaries)

| Collection | What it contains |
|---|---|
| 2025 voter roll | Ward & booth totals, gender, religion (H/M/C) |
| 2002 voter roll | Historical roll for SIR comparison |
| SurveyRecords | Field survey: religion, community, economic status, employment, health, schemes, BJP members |
| 2023_polled_notpolled | 2023 polling: polled vs not-polled by ward & religion |
| Community_caste_based_count_2023 | Pre-aggregated community/caste polled totals |
| Polled_NotPolled_caste_2023 | Per-voter caste + polling status |
| ward-booth-2026 | Ward-level electors, cutoff, mapping stats |
| ward-booth-details | Booth-level mapping & completion % |
| Deceased | Deceased voter records |
| FutureVoters | Future voters eligible by 2028 |
| NotFoundRecordSurvey | Not-found voter survey records |
| coastal_karnataka_all_references_castes | Surname → caste/community/region reference |
| NewQueryStack1 | Constituency-level SWOT/intelligence |
| SIR_NewAdditions | SIR: newly added voters |
| SIR_NotFound | SIR: voters not found |
| SIR_Suspicious | SIR: suspicious entries |
| genuine_voters | SIR: confirmed genuine voters |

## Data Files (Anthropic Files API — full content available as attached documents)

Each file is structured with per-sheet headers:
  ## SHEET: <name>  ## DESCRIPTION: <meaning>  ## COLUMNS: ...  ## ROWS: N

| File | Election / Period | Key data |
|---|---|---|
| 2013_WARD_WISE_STATISTICAL_ANALYSIS.xlsx | 2013 Assembly | Booth-wise BJP/INC/JDS%, ward stats (mean/std dev), BJP/Congress win-loss |
| 2013+_WARD_WISE_STATISTICAL_ANALYSIS.xlsx | 2013+ (Alliance) | Same for BJP+ alliance |
| 2013_2013+_AND_2018_WARD_WISE_ANALYSIS.xlsx | 2013 vs 2013+ vs 2018 | 3-year ward comparison |
| 2014_STATISTICAL_ANALYSIS.xlsx | 2014 (Lok Sabha) | Booth-wise BJP/INC/BSP/CPIM/AAP% |
| 2014_WARD_WISE_ANALYSIS.xlsx | 2014 vs 2018 | Ward margin comparison across years |
| 2014_AND_2018_WARD_WISE_STATISTICAL_ANALYSIS.xlsx | 2014 + 2018 | Dual year booth + ward stats |
| 2018_WARD_WISE_STATISTICAL_ANALYSIS.xlsx | 2018 Assembly | Booth: male/female voters, BJP/INC/JDS/CPI% |
| 2019_full_data4.xlsx | 2019 Lok Sabha | Booth: Ward, Total Polled, BJP%, INC%, OTH% |
| 2023p.xlsx | 2023 Assembly | Per-booth candidate votes (Lobo vs Kamath), ward summary, 2023 vs 2018 per-ward sheets |
| BJP_Boothwise_CasteReligion_Turnout_Strategy.xlsx | 2025 strategy | 249 booths × caste × religion × turnout, booth priority, community ranking |
| BJP_Political_Intelligence_System.xlsx | Strategic intel | Ward Strength Index, root cause analysis, historical 2013–2023 trend, 5-pillar strategy, WSI scores |
| Mangaluru_Election_Strategy_Report.xlsx | Campaign strategy | 244 booths STRONG/MEDIUM/WEAK, 2023 vs 2018, 90-day plan, SIR voter status |
| Mangaluru_FULLSCALE_Analysis_v2.xlsx | Full analysis | Caste turnout matrix, non-polled opportunity, gender analysis, flip targets, 100-day plan |

### Query routing — use these files for:
- 2023 election results / candidate votes → **2023p.xlsx** (BOOTHWISE or WARD-BOOTH sheet)
- 2018 results → **2018_WARD_WISE** or ward-specific sheets inside 2023p.xlsx
- 2019 Lok Sabha → **2019_full_data4.xlsx**
- 2014 results → **2014_STATISTICAL_ANALYSIS.xlsx**
- 2013 / 2013+ results → **2013_WARD_WISE** / **2013+_WARD_WISE**
- Historical trend 2013–2023 → **BJP_Political_Intelligence_System.xlsx** (HISTORICAL TREND sheet)
- Booth priority / intervention → **Mangaluru_Election_Strategy_Report.xlsx** (BOOTH INTERVENTION) or **BJP_Boothwise**
- Caste/community turnout → **BJP_Boothwise** (COMMUNITY ANALYSIS) or **Mangaluru_FULLSCALE** (CASTE TURNOUT MATRIX)
- Ward strength (STRONG/MEDIUM/WEAK) → **BJP_Political_Intelligence_System.xlsx** (WSI SCORE) or **Mangaluru_Election_Strategy_Report**
- Non-polled voter mobilization → **Mangaluru_FULLSCALE** (NON-POLLED OPPORTUNITY)
- Gender analysis → **Mangaluru_FULLSCALE** or **Mangaluru_Election_Strategy_Report** (GENDER ANALYSIS)
- 90-day/100-day action plan → **Mangaluru_Election_Strategy_Report** (90-DAY) or **Mangaluru_FULLSCALE** (100-DAY)
- SIR / BLO mapping % → **Mangaluru_Election_Strategy_Report** (SIR & VOTER STATUS sheet)
- Ward Strength Index / WSI → **BJP_Political_Intelligence_System** (WSI SCORE sheet)
- Flip targets → **Mangaluru_FULLSCALE** (FLIP TARGETS sheet)

## Output Formats

### Tables — ALWAYS use GFM markdown pipe tables for tabular/comparative data.
| Ward | BJP% | INC% | Margin | Status |
|------|------|------|--------|--------|
| Padavu | 62.3 | 35.1 | 27.2 | STRONG |

Use for: ward comparisons, election results, caste breakdowns, booth rankings, multi-year comparisons.
NEVER present structured data as plain text without the separator row.

### Charts — include when visual trends add value:
```chartspec
{"type":"bar","title":"...","labels":[...],"datasets":[{"label":"...","data":[...]}]}
```
Supported: bar, line, pie, doughnut, radar, stackedBar

### Exports — when user asks for download:
```exportspec
{"format":"csv","filename":"analysis.csv","columns":["Col1","Col2"],"rows":[{"Col1":"v1","Col2":"v2"}]}
```
Formats: csv, xlsx, pdf

## Ward Reference (21–60)
21=PADAVU, 24=DEREBAIL SOUTH, 25=DEREBAIL WEST, 26=DEREBAIL SOUTH WEST,
27=BOLOOR, 28=MANNAGUDDA, 29=KAMBLA, 30=KODIALBAIL, 31=BEJAI,
32=KADRI NORTH, 33=KADRI SOUTH, 34=SHIVBHAG, 35=PADAVU CENTRAL,
36=PADAVU POORVA, 37=MAROLI, 38=BENDUR, 39=FALNIR, 40=COURT,
41=CENTRAL, 42=DONGERKERY, 43=KUDROLI, 44=NAVAYATH, 45=PORT,
46=CANTONMENT, 47=MILAGRIS, 48=VALENCIA, 49=KANKANADY,
50=ALAPE DAKSHINA, 51=ALAPE UTTARA, 52=KANNUR, 53=BAJAL,
54=JEPPINAMUGER, 55=ATTAVARA, 56=MANGALADEVI, 57=HOIGE BAZAR,
58=BOLAR, 59=JEPPU, 60=BENGRE.
Religion: H=Hindu, M=Muslim, C=Christian.

## LIVE MONGODB DATA:
{MONGO_CONTEXT}
"""


# ════════════════════════════════════════════════════════════════════════════════
# EXPORT HELPER
# ════════════════════════════════════════════════════════════════════════════════

def _ai_make_export(spec, fmt):
    columns = spec.get('columns', [])
    rows    = spec.get('rows', [])
    fname   = spec.get('filename', f'export_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    df      = pd.DataFrame(rows, columns=columns) if columns else pd.DataFrame(rows)

    if fmt == 'csv':
        buf = _io.BytesIO()
        df.to_csv(buf, index=False)
        return buf.getvalue(), 'text/csv', fname if fname.endswith('.csv') else fname + '.csv'

    if fmt in ('xlsx', 'excel'):
        buf = _io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            df.to_excel(w, index=False, sheet_name='Data')
        return (buf.getvalue(),
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                fname if fname.endswith('.xlsx') else fname + '.xlsx')

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib import colors as _rlc
        from reportlab.lib.styles import getSampleStyleSheet
        buf  = _io.BytesIO()
        doc  = SimpleDocTemplate(buf, pagesize=A4)
        data = [columns] + [[str(r.get(c, '')) for c in columns] for r in rows]
        tbl  = Table(data)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), _rlc.HexColor('#1a237e')),
            ('TEXTCOLOR',  (0, 0), (-1, 0), _rlc.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [_rlc.white, _rlc.HexColor('#f5f5f5')]),
            ('GRID', (0, 0), (-1, -1), 0.5, _rlc.grey),
        ]))
        doc.build([Paragraph(fname, getSampleStyleSheet()['Title']), tbl])
        return (buf.getvalue(), 'application/pdf',
                fname if fname.endswith('.pdf') else fname + '.pdf')
    except ImportError:
        buf = _io.BytesIO()
        df.to_csv(buf, index=False)
        return buf.getvalue(), 'text/csv', fname.replace('.pdf', '.csv')


# ════════════════════════════════════════════════════════════════════════════════
# VIEWS
# ════════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def api_swot_overview(request):
    """POST /api/ai/swot-overview/"""
    if request.method == 'OPTIONS':
        return _ai_cors(request, JsonResponse({}))

    try:
        user = _user_from_request(request)
    except Exception as e:
        return _ai_cors(request, JsonResponse({"error": f"Auth error: {e}"}, status=500))
    if not user:
        return _ai_cors(request, JsonResponse({"error": "Unauthorized"}, status=401))

    try:
        body = json.loads(request.body)
    except Exception:
        return _ai_cors(request, JsonResponse({"error": "Invalid JSON"}, status=400))

    tab      = (body.get("tab")     or "swot").strip().lower()
    tab_data = (body.get("tabData") or "").strip()

    if not tab_data:
        return _ai_cors(request, JsonResponse({"error": "tabData is required"}, status=400))

    TAB_TITLES = {
        "swot":        "Political SWOT Analysis",
        "wards":       "Ward Strength Analysis",
        "demographic": "Demographic Analysis",
        "election":    "Previous Election History",
    }

    TAB_FOCUS = {
        "swot": (
            "Analyse the complete Political SWOT for Mangaluru City South. "
            "Focus on: BJP vs Congress ward results, vote shares, narrow wins at risk, "
            "flip opportunities, strongholds, SWOT quadrant insights, and 2028 priorities. "
            "Every insight must cite a real ward name, percentage, or vote count from the data."
        ),
        "wards": (
            "Analyse ward-by-ward electoral strength for Mangaluru City South. "
            "Focus on: strong vs narrow vs lost ward patterns, turnout performance, "
            "which wards are most at risk, which need turnout push, and the overall distribution. "
            "Cite specific ward names, BJP%, turnout figures from the data."
        ),
        "demographic": (
            "Analyse the religion-wise demographic voting patterns for Mangaluru City South. "
            "Focus on: Muslim-dominant booth patterns, Christian-dominant booth swing behaviour, "
            "ward viability by religious composition, minority consolidation vs BJP performance, "
            "and which demographic segments are persuadable. "
            "Cite actual booth numbers, Muslim%, Christian%, BJP% from the data."
        ),
        "election": (
            "Analyse the 5-election historical trend for Mangaluru City South (2013-2023). "
            "Focus on: which wards are structurally BJP vs structurally Congress across elections, "
            "which wards showed dangerous swings, booth flip patterns, "
            "vote leakage via 3rd parties, variance/stability scores, and 2028 outlook. "
            "Cite specific elections, ward names, swing percentages, and booth numbers from the data."
        ),
    }

    system_prompt = (
        "You are a senior political analyst for Mangaluru South constituency (Karnataka, India), "
        "Constituency 175, Mangaluru City Municipal Corporation — 38 wards, 2023 election data.\n\n"
        f"TASK: {TAB_FOCUS.get(tab, TAB_FOCUS['swot'])}\n\n"
        "The user has provided the exact data from the tab they are viewing. "
        "Analyse only what is in the data. Do not invent numbers.\n\n"
        "Return ONLY a valid JSON object — no markdown fences, no preamble, no trailing text.\n"
        "Schema (all fields required, every field must contain real data from the input):\n"
        '{\n'
        '  "headline": "10-15 word headline — must cite a real number or ward name from the data",\n'
        '  "summary": "2-3 sentence strategic summary — must reference specific ward names, %, or vote counts",\n'
        '  "bullets": [\n'
        '    {"icon":"🎯","text":"Key insight with a real ward/booth name and number"},\n'
        '    {"icon":"⚠️","text":"Key risk — cite the specific ward or booth and its margin"},\n'
        '    {"icon":"📈","text":"Key opportunity — cite specific numbers from the data"},\n'
        '    {"icon":"🔑","text":"Single most critical 2028 action — specific and measurable"}\n'
        '  ],\n'
        '  "callout": {\n'
        '    "label": "Bottom-line verdict",\n'
        '    "text": "1 sentence with the single most important takeaway, citing a real number",\n'
        '    "color": "#f59e0b"\n'
        '  }\n'
        '}'
    )

    user_prompt = (
        f"Tab: {TAB_TITLES.get(tab, tab)}\n\n"
        f"=== TAB DATA ===\n{tab_data}"
    )

    try:
        client  = _get_anthropic()
        message = client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = 1500,
            system     = system_prompt,
            messages   = [{"role": "user", "content": user_prompt}],
        )
        raw = "".join(b.text for b in message.content if hasattr(b, "text")).strip()
        raw = _re2.sub(r'^```(?:json)?\s*', '', raw)
        raw = _re2.sub(r'\s*```$', '',          raw)
        raw = raw.strip()
        m   = _re2.search(r'\{[\s\S]*\}', raw)
        if m:
            raw = m.group(0)
        try:
            overview = json.loads(raw)
        except json.JSONDecodeError:
            overview = {
                "headline": f"{TAB_TITLES.get(tab, tab)} — Analysis",
                "summary":  "The AI response could not be parsed. Please regenerate.",
                "bullets":  [],
                "callout":  None,
            }
        return _ai_cors(request, JsonResponse({"success": True, "overview": overview}))
    except Exception as exc:
        traceback.print_exc()
        return _ai_cors(request, JsonResponse({"error": str(exc)}, status=500))


@csrf_exempt
@require_http_methods(['POST', 'GET', 'OPTIONS'])
def api_ai_chat(request):
    """POST /api/ai/chat/"""
    if request.method == 'OPTIONS':
        return _ai_cors(request, JsonResponse({}))

    try:
        user = _user_from_request(request)
    except Exception as e:
        return _ai_err(request, f'Auth error: {e}', 500)
    if not user:
        return _ai_err(request, 'Authentication required.', 401)
    if not _is_approved(user):
        return _ai_err(request, 'Account pending approval.', 403)

    try:
        body = json.loads(request.body)
    except Exception:
        return _ai_err(request, 'Invalid JSON body.', 400)

    message = (body.get('message') or '').strip()
    history = body.get('history', [])
    if not message:
        return _ai_err(request, 'message field is required.', 400)

    client, err = _ai_get_client()
    if not client:
        return _ai_err(request, err, 500)

    # ── Simple / conversational — skip data loading ───────────────────────────
    if _is_simple_message(message):
        _simple_system = (
            "You are a friendly assistant for Mangaluru South Constituency Connect. "
            "Reply naturally and conversationally. Keep it short and warm. "
            "Do not mention data, voter records, or analytics unless the user asks."
        )
        msgs = []
        for h in history[-10:]:
            r, c = h.get('role', 'user'), h.get('content', '')
            if r in ('user', 'assistant') and c:
                msgs.append({'role': r, 'content': c})
        msgs.append({'role': 'user', 'content': message})
        try:
            response   = client.messages.create(
                model='claude-haiku-4-5-20251001', max_tokens=256,
                system=_simple_system, messages=msgs,
            )
            reply_text = ''.join(b.text for b in response.content if hasattr(b, 'text'))
        except Exception as e:
            traceback.print_exc()
            return _ai_err(request, f'Anthropic API error: {e}', 500)
        return _ai_cors(request, JsonResponse({
            'success': True, 'reply': reply_text,
            'chartSpec': None, 'exportSpec': None, 'filesUsed': [],
        }))

    # ── RAG: fetch only relevant context for this message ───────────────────
    all_sources = []
    try:
        rag_context, rag_sources = _rag_fetch_context(message)
        all_sources.extend(rag_sources)
    except Exception as e:
        rag_context = f'[RAG error: {e}]'
        traceback.print_exc()

    system_prompt = _AI_CHAT_SYSTEM.replace('{MONGO_CONTEXT}', rag_context)

    # ── Build messages ────────────────────────────────────────────────────────
    messages = []
    for h in history[-20:]:
        r, c = h.get('role', 'user'), h.get('content', '')
        if r in ('user', 'assistant') and c:
            messages.append({'role': r, 'content': c})
    messages.append({'role': 'user', 'content': message})

    # ── Call Anthropic ────────────────────────────────────────────────────────
    try:
        response = client.messages.create(
            model      = 'claude-sonnet-4-20250514',
            max_tokens = 4096,
            system     = system_prompt,
            messages   = messages,
        )
        reply_text = ''.join(b.text for b in response.content if hasattr(b, 'text'))
    except Exception as e:
        traceback.print_exc()
        return _ai_err(request, f'Anthropic API error: {e}', 500)

    # ── Parse embedded specs ──────────────────────────────────────────────────
    chart_spec = export_spec = None
    try:
        m = _re2.search(r'```chartspec\s*(\{.*?\})\s*```', reply_text, _re2.DOTALL)
        if m:
            chart_spec = json.loads(m.group(1))
    except Exception:
        pass
    try:
        m = _re2.search(r'```exportspec\s*(\{.*?\})\s*```', reply_text, _re2.DOTALL)
        if m:
            export_spec = json.loads(m.group(1))
    except Exception:
        pass

    clean = _re2.sub(r'```(chartspec|exportspec).*?```', '', reply_text,
                     flags=_re2.DOTALL).strip()

    return _ai_cors(request, JsonResponse({
        'success'   : True,
        'reply'     : clean,
        'chartSpec' : chart_spec,
        'exportSpec': export_spec,
        'filesUsed' : all_sources,
    }))


@csrf_exempt
@require_http_methods(['POST', 'OPTIONS'])
def api_ai_chat_export(request):
    """POST /api/ai/chat/export/"""
    if request.method == 'OPTIONS':
        return _ai_cors(request, JsonResponse({}))
    try:
        user = _user_from_request(request)
    except Exception as e:
        return _ai_err(request, f'Auth error: {e}', 500)
    if not user:
        return _ai_err(request, 'Authentication required.', 401)
    if not _is_approved(user):
        return _ai_err(request, 'Account pending approval.', 403)
    try:
        body = json.loads(request.body)
        spec = body.get('exportSpec', {})
        fmt  = spec.get('format', 'csv').lower()
    except Exception:
        return _ai_err(request, 'Invalid request body.', 400)
    try:
        from django.http import HttpResponse as _HR
        fb, mime, fn = _ai_make_export(spec, fmt)
        resp = _HR(fb, content_type=mime)
        resp['Content-Disposition'] = f'attachment; filename="{fn}"'
        return _ai_cors(request, resp)
    except Exception as e:
        traceback.print_exc()
        return _ai_err(request, f'Export failed: {e}', 500)


@csrf_exempt
@require_http_methods(['GET', 'OPTIONS'])
def api_ai_data_files(request):
    """GET /api/ai/data-files/ — list all data sources with counts."""
    if request.method == 'OPTIONS':
        return _ai_cors(request, JsonResponse({}))
    try:
        user = _user_from_request(request)
    except Exception as e:
        return _ai_err(request, f'Auth error: {e}', 500)
    if not user:
        return _ai_err(request, 'Authentication required.', 401)
    if not _is_approved(user):
        return _ai_err(request, 'Account pending approval.', 403)

    # MongoDB collection counts
    mongo_sources = []
    try:
        db1 = get_db()
        db2 = get_survey_db()
        mongo_sources = [
            {'name': '2025 Voter Roll',              'ext': 'mongodb', 'type': 'collection',
             'size': db1['2025'].estimated_document_count()},
            {'name': 'Survey Records',               'ext': 'mongodb', 'type': 'collection',
             'size': db2['SurveyRecords'].estimated_document_count()},
            {'name': '2023 Polling Data',            'ext': 'mongodb', 'type': 'collection',
             'size': db2['2023_polled_notpolled'].estimated_document_count()},
            {'name': '2002 Voter Roll',              'ext': 'mongodb', 'type': 'collection',
             'size': db2['2002'].estimated_document_count()},
            {'name': 'Future Voters',                'ext': 'mongodb', 'type': 'collection',
             'size': db2['FutureVoters'].estimated_document_count()},
            {'name': 'Deceased Records',             'ext': 'mongodb', 'type': 'collection',
             'size': db2['Deceased'].estimated_document_count()},
            {'name': 'Community/Caste Count 2023',   'ext': 'mongodb', 'type': 'collection',
             'size': db2['Community_caste_based_count_2023'].estimated_document_count()},
            {'name': 'Polled/NotPolled Caste 2023',  'ext': 'mongodb', 'type': 'collection',
             'size': db2['Polled_NotPolled_caste_2023'].estimated_document_count()},
            {'name': 'SIR New Additions',            'ext': 'mongodb', 'type': 'collection',
             'size': db2['SIR_NewAdditions'].estimated_document_count()},
            {'name': 'SIR Not Found',                'ext': 'mongodb', 'type': 'collection',
             'size': db2['SIR_NotFound'].estimated_document_count()},
            {'name': 'SIR Suspicious',               'ext': 'mongodb', 'type': 'collection',
             'size': db2['SIR_Suspicious'].estimated_document_count()},
            {'name': 'Genuine Voters',               'ext': 'mongodb', 'type': 'collection',
             'size': db2['genuine_voters'].estimated_document_count()},
            {'name': 'NotFoundRecordSurvey',         'ext': 'mongodb', 'type': 'collection',
             'size': db2['NotFoundRecordSurvey'].estimated_document_count()},
            {'name': 'Coastal Caste Reference',      'ext': 'mongodb', 'type': 'collection',
             'size': db2['coastal_karnataka_all_references_castes'].estimated_document_count()},
            {'name': 'Ward Info 2026',               'ext': 'mongodb', 'type': 'collection',
             'size': db2['ward-booth-2026'].estimated_document_count()},
            {'name': 'Booth Details',                'ext': 'mongodb', 'type': 'collection',
             'size': db2['ward-booth-details'].estimated_document_count()},
        ]
    except Exception as e:
        mongo_sources = [{'name': f'MongoDB error: {e}', 'ext': 'error', 'size': 0, 'type': 'error'}]

    # Local files
    local_files = []
    try:
        if _os2.path.isdir(_AI_DATA_DIR):
            for fname in sorted(_os2.listdir(_AI_DATA_DIR)):
                ext = _os2.path.splitext(fname)[1].lower()
                if ext not in _AI_SUPPORTED_EXTS:
                    continue
                path   = _os2.path.join(_AI_DATA_DIR, fname)
                size_b = _os2.path.getsize(path)
                try:
                    stat      = _os2.stat(path)
                    cache_key = (fname, int(stat.st_mtime), stat.st_size)
                    file_id   = _AI_FILE_ID_CACHE.get(cache_key)
                except Exception:
                    file_id = None
                local_files.append({
                    'name'         : fname,
                    'ext'          : ext.lstrip('.'),
                    'size'         : size_b,
                    'size_mb'      : round(size_b / (1024 * 1024), 1),
                    'type'         : 'file',
                    'file_id'      : file_id,
                    'via_files_api': bool(file_id),
                })
    except Exception as e:
        local_files = [{'name': f'File error: {e}', 'ext': 'error', 'size': 0, 'type': 'error'}]

    cached_count = sum(1 for f in local_files if f.get('via_files_api'))

    return _ai_cors(request, JsonResponse({
        'success'         : True,
        'files'           : mongo_sources + local_files,
        'mongo_count'     : len(mongo_sources),
        'file_count'      : len(local_files),
        'files_api_cached': cached_count,
        'limits'          : {'max_files': _AI_MAX_FILES},
    }))
    
    
_PLACE_ALLOWED_TYPES = {'club', 'temple', 'church', 'mosque'}


def _places_cors(request, response):
    origin = request.META.get('HTTP_ORIGIN', '')
    if origin:
        response['Access-Control-Allow-Origin']      = origin
        response['Access-Control-Allow-Credentials'] = 'true'
        response['Access-Control-Allow-Methods']     = 'GET, POST, DELETE, OPTIONS'
        response['Access-Control-Allow-Headers']     = (
            'Content-Type, Authorization, X-CSRFToken'
        )
    return response


@csrf_exempt
@require_http_methods(['GET', 'POST', 'DELETE', 'OPTIONS'])
def api_ward_places(request):
    """GET/POST/DELETE /api/ward-places/"""

    if request.method == 'OPTIONS':
        return _places_cors(request, JsonResponse({}))

    # ── Auth ─────────────────────────────────────────────────────────────────
    try:
        user = _user_from_request(request)
    except Exception as e:
        return _places_cors(request, JsonResponse({'success': False, 'message': f'Auth error: {e}'}, status=500))
    if not user:
        return _places_cors(request, JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401))
    if not _is_approved(user):
        return _places_cors(request, JsonResponse({'success': False, 'message': 'Account pending approval.'}, status=403))

    coll = get_survey_db()['WardData']

    # ── GET — list all places for a ward ──────────────────────────────────────
    if request.method == 'GET':
        ward = request.GET.get('ward', '').strip()
        if not ward:
            return _places_cors(request, JsonResponse({'success': False, 'message': 'ward param required.'}, status=400))
        try:
            ward_int = int(ward)
        except ValueError:
            return _places_cors(request, JsonResponse({'success': False, 'message': 'ward must be a number.'}, status=400))

        docs = list(coll.find(
            {'ward': ward_int, 'record_type': 'local_place'},
            {'_id': 1, 'type': 1, 'name': 1, 'address': 1, 'createdAt': 1, 'createdBy': 1}
        ).sort('createdAt', 1))

        for d in docs:
            d['_id'] = str(d['_id'])
            if isinstance(d.get('createdAt'), datetime):
                d['createdAt'] = d['createdAt'].isoformat()

        return _places_cors(request, JsonResponse({'success': True, 'places': docs}))

    # ── POST — add a new place ────────────────────────────────────────────────
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
        except Exception:
            return _places_cors(request, JsonResponse({'success': False, 'message': 'Invalid JSON.'}, status=400))

        ward      = body.get('ward')
        ward_name = (body.get('wardName') or '').strip()
        ptype     = (body.get('type') or '').strip().lower()
        name      = (body.get('name') or '').strip()
        address   = (body.get('address') or '').strip()

        if not ward:
            return _places_cors(request, JsonResponse({'success': False, 'message': 'ward is required.'}, status=400))
        if ptype not in _PLACE_ALLOWED_TYPES:
            return _places_cors(request, JsonResponse({'success': False, 'message': f'type must be one of {_PLACE_ALLOWED_TYPES}.'}, status=400))
        if not name:
            return _places_cors(request, JsonResponse({'success': False, 'message': 'name is required.'}, status=400))

        try:
            ward_int = int(ward)
        except (ValueError, TypeError):
            return _places_cors(request, JsonResponse({'success': False, 'message': 'ward must be a number.'}, status=400))

        doc = {
            'record_type': 'local_place',
            'ward':        ward_int,
            'wardName':    ward_name,
            'type':        ptype,
            'name':        name,
            'address':     address,
            'createdAt':   datetime.now(timezone.utc),
            'createdBy':   user.get('username') or user.get('email') or 'unknown',
        }

        try:
            result = coll.insert_one(doc)
        except Exception as e:
            return _places_cors(request, JsonResponse({'success': False, 'message': f'DB error: {e}'}, status=500))

        return _places_cors(request, JsonResponse({
            'success': True,
            'place': {
                '_id':      str(result.inserted_id),
                'type':     ptype,
                'name':     name,
                'address':  address,
                'createdAt': doc['createdAt'].isoformat(),
            },
        }))

    # ── DELETE — remove a place by _id ────────────────────────────────────────
    if request.method == 'DELETE':
        try:
            body     = json.loads(request.body)
            place_id = body.get('id', '').strip()
        except Exception:
            return _places_cors(request, JsonResponse({'success': False, 'message': 'Invalid JSON.'}, status=400))

        if not place_id:
            return _places_cors(request, JsonResponse({'success': False, 'message': 'id is required.'}, status=400))

        try:
            result = coll.delete_one({'_id': ObjectId(place_id), 'record_type': 'local_place'})
        except Exception as e:
            return _places_cors(request, JsonResponse({'success': False, 'message': f'DB error: {e}'}, status=500))

        if result.deleted_count == 0:
            return _places_cors(request, JsonResponse({'success': False, 'message': 'Place not found.'}, status=404))

        return _places_cors(request, JsonResponse({'success': True}))

    return _places_cors(request, JsonResponse({'success': False, 'message': 'Method not allowed.'}, status=405))


@csrf_exempt
@require_http_methods(['GET', 'OPTIONS'])
def api_local_places_summary(request):
    """
    GET /api/local-places-summary/
    Returns constituency-wide counts + full list of all local places,
    grouped by type and ward, for the Dashboard overview panel.

    Response:
    {
      "success": true,
      "total": 42,
      "counts": { "club": 10, "temple": 18, "church": 8, "mosque": 6 },
      "byWard": [
        { "ward": 28, "wardName": "MANNAGUDDA",
          "places": [{"_id":"..","type":"club","name":"..","address":".."},...],
          "counts": { "club":1, "temple":2, "church":0, "mosque":0 } },
        ...
      ]
    }
    """
    if request.method == 'OPTIONS':
        resp = JsonResponse({})
        origin = request.META.get('HTTP_ORIGIN', '')
        if origin:
            resp['Access-Control-Allow-Origin']      = origin
            resp['Access-Control-Allow-Credentials'] = 'true'
            resp['Access-Control-Allow-Methods']     = 'GET, OPTIONS'
            resp['Access-Control-Allow-Headers']     = 'Content-Type, Authorization, X-CSRFToken'
        return resp

    try:
        user = _user_from_request(request)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Auth error: {e}'}, status=500)
    if not user:
        return JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401)
    if not _is_approved(user):
        return JsonResponse({'success': False, 'message': 'Account pending approval.'}, status=403)

    try:
        coll = get_survey_db()['WardData']
        docs = list(coll.find(
            {'record_type': 'local_place'},
            {'_id': 1, 'ward': 1, 'wardName': 1, 'type': 1, 'name': 1, 'address': 1}
        ).sort([('ward', 1), ('type', 1), ('name', 1)]))

        for d in docs:
            d['_id'] = str(d['_id'])

        type_counts = {'club': 0, 'temple': 0, 'church': 0, 'mosque': 0}
        for d in docs:
            t = d.get('type', '')
            if t in type_counts:
                type_counts[t] += 1

        ward_map = {}
        for d in docs:
            ward  = d.get('ward', 0)
            wname = d.get('wardName', f'Ward {ward}')
            if ward not in ward_map:
                ward_map[ward] = {
                    'ward': ward, 'wardName': wname, 'places': [],
                    'counts': {'club': 0, 'temple': 0, 'church': 0, 'mosque': 0},
                }
            ward_map[ward]['places'].append(d)
            t = d.get('type', '')
            if t in ward_map[ward]['counts']:
                ward_map[ward]['counts'][t] += 1

        by_ward = sorted(ward_map.values(), key=lambda w: w['ward'])

        return JsonResponse({
            'success': True, 'total': len(docs),
            'counts': type_counts, 'byWard': by_ward,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ── Beneficiary List for SWOT Query ──────────────────────────────────────────
@csrf_exempt
def api_beneficiary_list(request):
    """
    POST /api/swot/beneficiaries/
    Body: {
        "query":   {"economicStatus": "APL", "religion": "Buddhist", ...},
        "page":    1,        # 1-based
        "limit":   50        # max 100
    }
    Queries the 'Data' collection on _SURVEY_URL and returns matching voters.
    """
    if request.method == "OPTIONS":
        return _ai_cors(request, JsonResponse({}))

    user = _user_from_request(request)
    if not user:
        return _ai_cors(request, JsonResponse({"error": "Unauthorized"}, status=401))

    try:
        body = json.loads(request.body)
    except Exception:
        return _ai_cors(request, JsonResponse({"error": "Invalid JSON"}, status=400))

    raw_query = body.get("query", {})
    page      = max(1, int(body.get("page", 1)))
    limit     = min(100, max(1, int(body.get("limit", 50))))
    skip      = (page - 1) * limit

    # Build MongoDB filter — only include non-empty, non-"Unknown" values
    mongo_filter = {}
    for k, v in raw_query.items():
        if v and v not in ("Unknown", "", None):
            mongo_filter[k] = v

    try:
        coll  = get_survey_db()['Data']
        total = coll.count_documents(mongo_filter)

        projection = {
            '_id': 0,
            'firstName': 1, 'middleName': 1, 'lastName': 1,
            'voterid': 1, 'age': 1, 'gender': 1,
            'wardNumber': 1, 'boothNo': 1, 'houseNumber': 1,
            'address': 1, 'economicStatus': 1, 'religion': 1,
            'education': 1, 'employmentStatus': 1, 'healthStatus': 1,
            'diseaseType': 1, 'diseaseName': 1, 'minority': 1,
            'differentlyAbled': 1, 'annualIncome': 1, 'familyIncome': 1,
            'maritalStatus': 1, 'homeType': 1, 'contactNumber': 1,
            'schemesUsed': 1, 'pollingStation': 1,
        }

        docs = list(coll.find(mongo_filter, projection).skip(skip).limit(limit))

        # Serialize: convert any non-serialisable types
        voters = []
        for d in docs:
            voter = {}
            for k, v in d.items():
                if hasattr(v, 'item'):          # numpy int/float
                    voter[k] = v.item()
                elif isinstance(v, list):
                    voter[k] = [str(i) if not isinstance(i, (str, int, float, bool, type(None))) else i for i in v]
                else:
                    voter[k] = v
            voters.append(voter)

        return _ai_cors(request, JsonResponse({
            'success': True,
            'total':   total,
            'page':    page,
            'limit':   limit,
            'pages':   (total + limit - 1) // limit,
            'voters':  voters,
        }))

    except Exception as e:
        return _ai_cors(request, JsonResponse({'success': False, 'error': str(e)}, status=500))