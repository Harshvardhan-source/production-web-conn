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
from datetime import datetime
from bson import ObjectId
import ast
import jwt as pyjwt
import threading

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
    """Extract & validate JWT from httpOnly cookie or Authorization header."""
    token = request.COOKIES.get('cc_token')
    if not token:
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
    if not token:
        return None
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return {'username': payload.get('username'), 'email': payload.get('sub')}
    except pyjwt.PyJWTError:
        return None


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
    email    = body.get('email', '').strip()
    password = body.get('password', '').strip()

    if not (username and email and password):
        return JsonResponse({'success': False, 'message': 'All fields are required.'}, status=400)

    if len(password) < 8 or not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
        return JsonResponse({'success': False, 'message': 'Password must be 8+ chars with letters and numbers.'}, status=400)

    db = get_db()
    if db['UserReg'].find_one({'Email': email}):
        return JsonResponse({'success': False, 'message': 'Email already registered.'}, status=400)

    db['UserReg'].insert_one({
        'Time_stamp': datetime.utcnow(),
        'Username': username,
        'Email': email,
        'Password': make_password(password),
    })

    request.session['username'] = username
    request.session['email'] = email
    return JsonResponse({'success': True, 'username': username, 'email': email})


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

    request.session['username'] = user['Username']
    request.session['email']    = email

    # Fetch dashboard stats
    stats = _registration_analytics(db)
    return JsonResponse({'success': True, 'username': user['Username'], 'email': email, **stats})


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
    voter_male   = gender_map_v.get('M', 0)
    voter_female = gender_map_v.get('F', 0)
 
    religion_map   = {'H': 'Hindu', 'M': 'Muslim', 'C': 'Christian', 'J': 'Jain', 'B': 'Buddhist', 'S': 'Sikh'}
    rel_map_v      = {g['_id']: g['n'] for g in v_result['religions']}
    voter_religion = {name: rel_map_v.get(code, 0) for code, name in religion_map.items()}
 
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
        'regReligion':     reg_religion,
        'voterReligion':   voter_religion,
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


@require_http_methods(['GET'])
def api_ward_dashboard(request):
    import time as _t
    ward = request.GET.get('ward', '').strip()
    if not ward:
        return JsonResponse({'success': False, 'message': 'ward parameter required'}, status=400)

    # Cache hit
    cached = _ward_dash_cache.get(ward)
    if cached and (_t.time() - cached['ts']) < _WARD_CACHE_TTL:
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

        # ── 3. Large families in this ward from 2025 voter list ──────────────
        # Use module-level WARD_NAME_TO_BOOTHS — no local copy needed
        ward_name_upper  = ward_name.upper().strip()
        ward_booths_list = WARD_NAME_TO_BOOTHS.get(ward_name_upper, [])

        # Convert booth ints to strings for matching (2025 list may store as string)
        booth_strs = [str(b) for b in ward_booths_list]
        booth_ints = ward_booths_list

        large_family_count = 0
        if ward_booths_list:
            lf_pipeline = [
                {'$match': {'Part No': {'$in': booth_strs + [str(b) for b in booth_ints]}}},
                {'$match': {'House No': {'$exists': True, '$ne': None}}},
                {'$group': {'_id': '$House No', 'count': {'$sum': 1}}},
                {'$match': {'count': {'$gt': 15}}},
                {'$count': 'n'},
            ]
            lf_result = list(db['2025'].aggregate(lf_pipeline))
            large_family_count = lf_result[0]['n'] if lf_result else 0

        # ── 4. Coverage ───────────────────────────────────────────────────────
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
            'totalReg':         total_reg,
            'regMale':          reg_male,
            'regFemale':        reg_female,
            'regReligion':      reg_religion,
            'houseCount':       house_count,
            'largeFamilyCount': large_family_count,
            'wardCoverage':     {ward_name: coverage_pct},
            'coveragePct':      coverage_pct,
        }

        _ward_dash_cache[ward] = {'data': result, 'ts': _t.time()}
        return JsonResponse({'success': True, **result})

    except Exception as exc:
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': str(exc)}, status=500)


# ─── BOOTH DASHBOARD ──────────────────────────────────────────────────────────
# GET /api/booth-dashboard/?ward=21&booth=31
# Reads WardBoothWise_2026 (ward-booth-details) on survey cluster for 2026 stats.
# Also queries SurveyRecords for survey coverage at booth level.

_booth_dash_cache = {}   # { 'ward_booth': {'data': {...}, 'ts': float} }
_BOOTH_CACHE_TTL  = 300  # 5 minutes

@require_http_methods(['GET'])
def api_booth_dashboard(request):
    import time as _t, re as _re
    ward  = request.GET.get('ward',  '').strip()
    booth = request.GET.get('booth', '').strip()
    if not ward or not booth:
        return JsonResponse({'success': False, 'message': 'ward and booth parameters required'}, status=400)

    cache_key = f'{ward}_{booth}'
    cached = _booth_dash_cache.get(cache_key)
    if cached and (_t.time() - cached['ts']) < _BOOTH_CACHE_TTL:
        return JsonResponse({'success': True, **cached['data']})

    try:
        survey_db = get_db1()
        ward_int  = int(ward)  if ward.isdigit()  else None
        booth_int = int(booth) if booth.isdigit() else None

        # ── 1. WardBoothWise_2026 — booth-level 2026 electors data ───────────
        filt = {}
        if ward_int is not None and booth_int is not None:
            filt = {'$or': [
                {'wardNumber': ward_int,  'boothNumber': booth_int},
                {'wardNumber': str(ward), 'boothNumber': booth},
            ]}
        booth_doc = survey_db['WardBoothWise_2026'].find_one(filt) or {}

        # Fallback: full scan if type mismatch
        if not booth_doc and ward_int is not None and booth_int is not None:
            for _d in survey_db['WardBoothWise_2026'].find():
                if (str(_d.get('wardNumber','')).strip() == str(ward_int) and
                    str(_d.get('boothNumber','')).strip() == str(booth_int)):
                    booth_doc = _d
                    break

        def _num(v):
            if v is None: return 0
            try: return int(str(v).replace(',','').strip())
            except: return 0

        def _flt(v):
            if v is None: return 0.0
            try: return round(float(str(v).replace('%','').replace(',','').strip()), 2)
            except: return 0.0

        ward_name   = (booth_doc.get('wardName') or '').strip() or WARD_NUM_TO_NAME.get(ward, f'Ward {ward}')
        booth_electors = _num(booth_doc.get('totalElectors'))

        # ── 2. SurveyRecords — how many surveyed for this booth ───────────────
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
        reg_male    = gmap.get('Male',   0)
        reg_female  = gmap.get('Female', 0)

        # ── 3. Coverage ───────────────────────────────────────────────────────
        denom        = booth_electors or 1
        coverage_pct = round(total_reg / denom * 100, 1)

        result = {
            'wardNumber':       ward,
            'wardName':         ward_name,
            'boothNumber':      booth_int or booth,
            # 2026 electors data
            'totalElectors':    booth_electors,
            'cutoffElec':       _num(booth_doc.get('cutoffElec')),
            'bloMapped':        _num(booth_doc.get('bloMapped')),
            'totalMapped':      _num(booth_doc.get('totalMapped')),
            'pctBloMapped':     _flt(booth_doc.get('pctBloMapped')),
            'ageCutoff':        _num(booth_doc.get('ageCutoff')),
            'progeny18':        _num(booth_doc.get('progeny18')),
            'pctProgeny':       _flt(booth_doc.get('pctProgeny')),
            'electorsMapped':   _num(booth_doc.get('electorsMapped')),
            'pctElectorsMapped':_flt(booth_doc.get('pctElectorsMapped')),
            'pctTotalCompleted':_flt(booth_doc.get('pctTotalCompleted')),
            # Survey coverage
            'totalReg':         total_reg,
            'regMale':          reg_male,
            'regFemale':        reg_female,
            'houseCount':       house_count,
            'coveragePct':      coverage_pct,
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

    # Default: next auto-increment from SurveyRecords
    db     = get_survey_db()
    latest = db['SurveyRecords'].find_one(sort=[('serialNumber', -1)])
    serial = (int(latest['serialNumber']) + 1) if latest else 1
    return JsonResponse({'serialNumber': serial, 'source': 'auto'})


@csrf_exempt
@require_http_methods(['POST'])
def api_save_survey(request):
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()

    dob_str = body.get('dob')
    age = None
    if dob_str:
        try:
            dob = datetime.strptime(dob_str, '%Y-%m-%d')
            today = datetime.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid DOB format.'}, status=400)

    is_outstation = body.get('outstationResident') == 'Yes'

    # ── 1. Look up voter in 2025 roll ─────────────────────────────────────────
    voterid     = (body.get('voterid') or '').strip().upper()
    col_2025    = get_db()['2025']
    voter_2025  = None

    if voterid:
        voter_2025 = col_2025.find_one(
            {'Epic NO': voterid},
            {'Serial No': 1, 'Sl No': 1, 'Name': 1, 'House No': 1, 'Booth No': 1}
        )

    # If no voterid, try name + house match as fallback
    if not voter_2025:
        first = (body.get('firstName') or '').strip()
        last  = (body.get('lastName')  or '').strip()
        house = (body.get('houseNumber') or '').strip()
        full_name = f"{first} {last}".strip()
        if full_name and house:
            voter_2025 = col_2025.find_one(
                {'Name': {'$regex': f'^{re.escape(full_name)}$', '$options': 'i'}, 'House No': house},
                {'Serial No': 1, 'Sl No': 1, 'Name': 1, 'House No': 1, 'Booth No': 1}
            )

    # ── 2. Use 2025 Serial No if found, else keep the submitted serial ────────
    serial_from_2025 = None
    if voter_2025:
        raw_serial = voter_2025.get('Serial No') or voter_2025.get('Sl No')
        try:
            serial_from_2025 = int(raw_serial)
        except (ValueError, TypeError):
            pass

    final_serial = serial_from_2025 if serial_from_2025 is not None else int(body.get('serialNumber') or 1)

    data = {
        # ── Personal ──────────────────────────────────────────────
        'firstName':        body.get('firstName'),
        'middleName':       body.get('middleName'),
        'lastName':         body.get('lastName'),
        'addharNumber':     body.get('addharNumber'),
        'contactNumber':    body.get('contactNumber'),
        'serialNumber':     final_serial,           # ← from 2025 roll when available
        'serialSource':     '2025_roll' if serial_from_2025 is not None else 'manual',
        'dob':              dob_str,
        'age':              age,
        'gender':           body.get('gender'),
        'maritalStatus':    body.get('maritalStatus'),
        'voterid':          voterid or body.get('voterid'),

        # ── Outstation ────────────────────────────────────────────
        'outstationResident': body.get('outstationResident', 'No'),
        'outstationCity':     body.get('outstationCity')    if is_outstation else None,
        'outstationState':    body.get('outstationState')   if is_outstation else None,
        'outstationAddress':  body.get('outstationAddress') if is_outstation else None,

        # ── Current location (only saved when outstation = Yes) ───
        'currentHouseNumber': body.get('currentHouseNumber') if is_outstation else None,
        'currentAreaType':    body.get('currentAreaType')    if is_outstation else None,
        'currentHomeType':    body.get('currentHomeType')    if is_outstation else None,
        'currentAddress':     body.get('currentAddress')     if is_outstation else None,

        # ── Registered address ────────────────────────────────────
        'wardNumber':       body.get('wardNumber'),
        'houseNumber':      body.get('houseNumber'),
        'address':          body.get('address'),
        'areaType':         body.get('areaType'),
        'homeType':         body.get('homeType'),

        # ── Financial ─────────────────────────────────────────────
        'annualIncome':     body.get('annualIncome'),
        'familyIncome':     body.get('familyIncome'),
        'economicStatus':   body.get('economicStatus'),

        # ── Demographics ──────────────────────────────────────────
        'religion':         body.get('religion'),
        'community':        body.get('community'),
        'subcategory':      body.get('subcategory'),
        'education':        body.get('education'),
        'educationtype':    body.get('educationtype'),
        'minority':         body.get('minority'),
        'student':          body.get('student'),

        # ── Employment ────────────────────────────────────────────
        'employmentStatus': body.get('employmentStatus'),
        'employmentType':   body.get('employmentType') if body.get('employmentStatus') == 'Employed' else None,

        # ── Health ────────────────────────────────────────────────
        'healthStatus':     body.get('healthStatus'),
        'diseaseType':      body.get('diseaseType')  if body.get('healthStatus') == 'Diseased' else None,
        'diseaseName':      body.get('diseaseName')  if body.get('healthStatus') == 'Diseased' else None,
        'differentlyAbled': body.get('differentlyAbled'),

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

    # ── 4. Save to correct collection ────────────────────────────────────────
    # voter_2025 is None  →  not in 2025 voter roll → NotFoundRecordSurvey
    # voter_2025 found    →  normal path             → SurveyRecords
    if voter_2025 is None:
        # Mark the reason and save to the "not found" collection
        data['notFoundReason'] = (
            'Voter ID not in 2025 roll' if voterid
            else 'Name + house not matched in 2025 roll'
        )
        survey_db['NotFoundRecordSurvey'].insert_one(data)
        print(f"[api_save_survey] Voter NOT in 2025 roll — saved to NotFoundRecordSurvey: {voterid or data.get('firstName')}")
        collection_used = 'NotFoundRecordSurvey'
    else:
        survey_db['SurveyRecords'].insert_one(data)
        print(f"[api_save_survey] Saved to SurveyRecords — serial {final_serial} (from 2025 roll)")
        collection_used = 'SurveyRecords'

    # ── 5. Background SIR analysis ────────────────────────────────────────────
    def _sir_bg():
        try:
            voterid_sir = data.get('voterid', '').strip().upper() if data.get('voterid') else ''
            name_sir    = _norm((data.get('firstName', '') + ' ' + data.get('lastName', '')).strip())
            house_sir   = _norm(data.get('houseNumber', ''))
            ward_sir    = data.get('wardNumber', '')
            booth_sir   = str(data.get('boothNo', ''))
            serial_sir  = data.get('serialNumber', '')
            _run_sir_analysis(
                get_db(), voterid_sir, name_sir, house_sir,
                ward_sir, booth_sir, serial_sir
            )
        except Exception as e:
            print(f'[SIR] Background check error: {e}')

    threading.Thread(target=_sir_bg, daemon=True).start()

    return JsonResponse({
        'success':        True,
        'message':        'Survey saved successfully.',
        'serialNumber':   final_serial,
        'serialSource':   data['serialSource'],
        'collection':     collection_used,
        'inVoterRoll':    voter_2025 is not None,
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
# Reads credentials from env vars set on Render:
#   GCS_BUCKET_NAME          e.g. "your-project.appspot.com"
#   GOOGLE_APPLICATION_CREDENTIALS_JSON  — full JSON of the service account key
#                                           (paste the entire JSON as one line)

def _upload_to_gcs(file_obj, destination_blob_name):
    """
    Upload a Django UploadedFile / InMemoryUploadedFile to GCS.
    Returns the public HTTPS URL, or raises on error.
    """
    import os, json as _json
    from google.cloud import storage as _gcs
    from google.oauth2 import service_account as _sa

    bucket_name = os.environ.get('GCS_BUCKET_NAME', '')
    creds_json  = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON', '')

    if not bucket_name:
        raise ValueError('GCS_BUCKET_NAME env var is not set')
    if not creds_json:
        raise ValueError('GOOGLE_APPLICATION_CREDENTIALS_JSON env var is not set')

    creds_dict  = _json.loads(creds_json)
    credentials = _sa.Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/cloud-platform'],
    )
    client = _gcs.Client(credentials=credentials)
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(destination_blob_name)

    # Reset read position in case Django already read part of the file
    file_obj.seek(0)
    blob.upload_from_file(file_obj, content_type=file_obj.content_type or 'application/octet-stream')
    blob.make_public()
    print(f"[GCS] Uploaded '{file_obj.name}' to '{destination_blob_name}', public URL: {blob.public_url}")
    return blob.public_url


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

@csrf_exempt
@require_http_methods(['POST'])
def api_scheme_voter_list(request):
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST.dict()
    print("Received ward for scheme lookup:", body.get('ward'))
    ward = body.get('ward')
    if not ward:
        return JsonResponse({'success': False, 'message': 'Ward is required.'}, status=400)

    db   = get_db1()
    coll = db.get_collection('CollDB', codec_options=None)

    try:
        from pymongo import MongoClient as MC
        client2 = MC(settings.MONGODB_URL, tls=True, tlsCAFile=certifi.where())
        coll = client2['MainB']['CollDB']
        docs = list(coll.find({'WARD_NO': int(ward)}).limit(200))
    except Exception:
        docs = []

    voters = [bson_clean(d) for d in docs]
    return JsonResponse({'success': True, 'voters': voters})


@csrf_exempt
@require_http_methods(['POST'])
def api_view_scheme(request):
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    voter_data = body.get('voterData', {})

    analysing_cols = {
        'Gender', 'MaritalStatus', 'EconomicStatus', 'EmploymentStatus',
        'EmploymentType', 'Religion', 'Community', 'SubCategory', 'Education',
        'EducationType', 'PhysicalStatus', 'HealthStatus', 'HomeType', 'AGE'
    }

    filtered = {k: str(v) for k, v in voter_data.items() if k in analysing_cols and v is not None}

    eligible = []
    try:
        df = pd.read_excel('StoreAllSheetData.xlsx')
        for _, row in df.iterrows():
            row_d = {k: str(v) for k, v in row.to_dict().items()}
            if _is_eligible(filtered, row_d):
                eligible.append({
                    'Name':        row_d.get('Name', ''),
                    'Type':        row_d.get('type', ''),
                    'Link':        row_d.get('Link', ''),
                    'Ministry':    row_d.get('ministry', ''),
                    'Description': row_d.get('Description', ''),
                })
    except FileNotFoundError:
        eligible = []
    except Exception:
        eligible = []

    return JsonResponse({'success': True, 'schemes': eligible})


def _is_eligible(voter, scheme_row):
    for key, voter_val in voter.items():
        if key not in scheme_row:
            continue
        scheme_val = scheme_row[key]
        if str(scheme_val).lower() in ('nan', 'none', ''):
            continue
        if key == 'AGE':
            try:
                age = int(float(voter_val))
                in_range = False
                for r in scheme_val.split(','):
                    parts = r.strip().split('-')
                    if len(parts) == 2:
                        low, high = int(parts[0].strip()), int(parts[1].strip())
                        if low <= age <= high:
                            in_range = True
                            break
                if not in_range:
                    return False
            except Exception:
                return False
        else:
            allowed = [v.strip() for v in scheme_val.split(',')]
            if voter_val not in allowed:
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
            'voter':         '2025',
            'survey':        'SurveyRecords',
            'future_voters': 'FutureVoters',
            'deceased':      'Deceased',
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
        member = {
            'name':      str(d.get('Name', '')).strip(),
            'relation':  str(d.get('Relation Name', '')).strip(),
            'voterid':   vid,
            'gender':    str(d.get('Gender', '')),
            'age':       d.get('Age', ''),
            'booth':     str(d.get('Booth No', '')),
            'ward':      str(d.get('Part No', '')),
            'house_no':  hn,
            'address':   str(d.get('Address', '')),            # voter's own address from 2025 DB
            'serial_no': d.get('Serial No') or d.get('Sl No', ''),  # voter's serial from 2025 roll
            'surveyed':  False,
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
        'booth':    '',
        'ward':     '',
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
    Score a list of MongoDB docs against (name, relation).
    Returns (best_doc, best_score). Stops early at score ≥ 97.
    flat_fn is either _flat_2025 or _flat_2002.
    """
    best_doc, best_score = None, 0.0
    for doc in candidates:
        flat    = flat_fn(doc)
        n_score = _name_score(name, flat['name'])
        r_score = _name_score(relation, flat['relation']) if (relation and flat['relation']) else 0.0
        comp    = (0.65 * n_score + 0.35 * r_score) if (relation and flat['relation']) else n_score
        if comp > best_score:
            best_score, best_doc = comp, doc
        if best_score >= 97: break   # near-perfect — stop looking
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
    Look up a voter in the MongoDB 2025 collection.

    Tier 1 — EPIC No       (exact, indexed — O(1))
    Tier 2 — Exact regex   (name + house — fast, catches clean data)
    Tier 3 — Fuzzy match   (all voters in same house → score each → best ≥ 80)
                           handles: Vishvanath/Vishwanath, Lakshmi/Laxmi, etc.
    Tier 4 — Fuzzy name-only (no house available — top-3 candidates across DB)
    """
    # Tier 1: EPIC No exact
    if voterid:
        doc = col.find_one({'Epic NO': voterid})
        if doc:
            return bson_clean(doc)

    # Tier 2: exact regex name + house
    if name and house:
        doc = col.find_one({'$and': [
            {'Name':     {'$regex': re.escape(name), '$options': 'i'}},
            {'House No': house},
        ]})
        if doc:
            return bson_clean(doc)

    _PROJ_25 = {'Name':1,'Relation Name':1,'Epic NO':1,'House No':1,'Gender':1,'Age':1,'Booth No':1,'Part No':1}

    # Tier 3: fuzzy — all voters at same house (projection → less network transfer)
    if house and (name or relation):
        candidates = list(col.find({'House No': house}, _PROJ_25))
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2025, name, relation)
            if best_doc and best_score >= _FUZZY_THRESHOLD:
                return bson_clean(best_doc)

    # Tier 4: prefix → fuzzy, capped at 30 with projection
    if name:
        candidates = list(col.find(
            {'Name': {'$regex': f'^{re.escape(name[:3])}', '$options': 'i'}}, _PROJ_25
        ).limit(30))
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2025, name, relation)
            if best_doc and best_score >= _FUZZY_THRESHOLD:
                return bson_clean(best_doc)

    return None


def _find_voter_in_2002(col, voterid, name, house, relation=''):
    """
    Look up a voter in MongoDB SurveyDataBase.2002.

    Schema-agnostic: handles BOTH old field names (Name / House No / Epic NO /
    Relation Name) and new field names (Voter Name / House / Flat No /
    Voter ID / EPIC No / Relative Name).  Docs from either upload will be found.

    Tier 1 — EPIC exact      (tries both old and new EPIC field names)
    Tier 2 — Exact regex     (name + house, tries all field name combinations)
    Tier 3 — Fuzzy/house     (fetch all docs at same house via $or, score each)
    Tier 4 — Fuzzy prefix    (prefix filter across both name fields, top 50)
    """
    # Common house $or query (works regardless of which schema doc was stored in)
    def _house_query(h):
        return {'$or': [{'House / Flat No': h}, {'House No': h}]}

    def _name_regex_query(n, h):
        name_rx = {'$regex': re.escape(n), '$options': 'i'}
        return {'$and': [
            {'$or': [{'Voter Name': name_rx}, {'Name': name_rx}]},
            _house_query(h),
        ]}

    # Tier 1: EPIC exact — try both field names
    if voterid:
        doc = col.find_one({'$or': [
            {'Voter ID / EPIC No': voterid},
            {'Epic NO': voterid},
        ]})
        if doc:
            return bson_clean(doc)

    # Tier 2: exact regex name + house (schema-agnostic)
    if name and house:
        doc = col.find_one(_name_regex_query(name, house))
        if doc:
            return bson_clean(doc)

    _PROJ_02 = {'Voter Name':1,'Name':1,'Relative Name':1,'Relation Name':1,
                'House / Flat No':1,'House No':1,'Voter ID / EPIC No':1,'Epic NO':1,'Gender':1,'Age':1}

    # Tier 3: all voters at same house via $or, fuzzy score with early-exit
    if house and (name or relation):
        candidates = list(col.find(_house_query(house), _PROJ_02))
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2002, name, relation)
            if best_doc and best_score >= _FUZZY_THRESHOLD:
                return bson_clean(best_doc)

    # Tier 4: prefix → fuzzy, capped at 30 with projection
    if name:
        px = {'$regex': f'^{re.escape(name[:3])}', '$options': 'i'}
        candidates = list(col.find(
            {'$or': [{'Voter Name': px}, {'Name': px}]}, _PROJ_02
        ).limit(30))
        if candidates:
            best_doc, best_score = _score_candidates(candidates, _flat_2002, name, relation)
            if best_doc and best_score >= _FUZZY_THRESHOLD:
                return bson_clean(best_doc)

    return None


def _epic_prefix(vid):
    m = re.match(r'^([A-Z]{2,4})', _norm(vid))
    return m.group(1) if m else ''


def _run_sir_analysis(db, voterid, name, house, ward, booth, serial, relation=''):
    col_2025 = db['2025']
    col_2002 = db['2002']   # ← MongoDB, uploaded from Google Sheet

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
        db['SIR_NewAdditions'].update_one(
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
        db['SIR_Deletions'].update_one(
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
            db['SIR_Modifications'].update_one(
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
            db['SIR_Retained'].update_one(
                {'survey_voterid': vid_key},
                {'$setOnInsert': ret_doc}, upsert=True)
            results.append({'category': 'RETAINED', 'label': 'Retained',
                            'color': '#10b981', 'icon': '\u2713',
                            'detail': 'Record consistent in both 2002 and 2025 rolls.'})
            any_stored = True
    else:
        results.append({'category': 'NOT_FOUND', 'label': 'Unregistered / Not Traced',
                        'color': '#6b7fa0', 'icon': '?',
                        'detail': 'Voter not found in either roll. May be unregistered, recently relocated, or name/ID mismatch.'})

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
        db['SIR_Suspicious'].update_one(
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

    if do_store:
        sir = _run_sir_analysis(db, voterid, name, house, ward, booth, serial, relation)
        return JsonResponse({'success': True, **sir})

    # ── Read-only preview (no DB writes) ──────────────────────────────────────
    col_2025 = db['2025']
    col_2002 = db['2002']

    # Run 2025 and 2002 lookups in parallel threads — each is an independent query
    _res = [None, None]
    def _t25(): _res[0] = _find_voter_in_2025(col_2025, voterid, name, house, relation)
    def _t02(): _res[1] = _find_voter_in_2002(col_2002, voterid, name, house, relation)
    _ta = threading.Thread(target=_t25, daemon=True)
    _tb = threading.Thread(target=_t02, daemon=True)
    _ta.start(); _tb.start(); _ta.join(); _tb.join()
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

    # ── Return full voter data so frontend comparison panel can display it ────
    # When 2002 record is missing, also run Excel fuzzy suggest automatically
    suggestions_2002 = []
    if not in_2002 and (name or house):
        # Use cached DataFrame + pre-built house index — no disk I/O after first load
        try:
            df_x, cx, hidx = _get_xlsx()
            if df_x is not None:
                CN, CR = cx.get('name'), cx.get('rel')
                CH, CE = cx.get('house'), cx.get('epic')
                CG, CA = cx.get('gender'), cx.get('age')
                W = {CN: 3.0, CR: 2.0, CH: 1.5}

                # ── Build candidate pool from THREE sources ────────────────────────────
                # 1. Exact house index   — O(1), most precise
                # 2. Name prefix rows   — catches name matches in different houses
                # 3. Relation prefix rows — catches relatives in different houses
                # Deduplicate by row index before scoring.

                candidate_indices = set()

                # Source 1: house index (O(1))
                if house and hidx:
                    for idx in hidx.get(house.strip().upper(), []):
                        candidate_indices.add(idx)

                # Source 2: name prefix rows (up to 200 candidates)
                if name and CN:
                    pfx = name[:3].upper()
                    col_upper = df_x[CN].str.upper()
                    name_matches = df_x.index[col_upper.str.startswith(pfx, na=False)].tolist()
                    for idx in name_matches[:200]:
                        candidate_indices.add(idx)

                # Source 3: relation prefix rows (up to 100 candidates)
                if relation and CR:
                    rpfx = relation[:3].upper()
                    rel_upper = df_x[CR].str.upper()
                    rel_matches = df_x.index[rel_upper.str.startswith(rpfx, na=False)].tolist()
                    for idx in rel_matches[:100]:
                        candidate_indices.add(idx)

                # Fallback: if still empty, score entire DataFrame
                if not candidate_indices:
                    subset = df_x
                else:
                    subset = df_x.iloc[sorted(candidate_indices)]

                query_cols = {}
                if name     and CN: query_cols[CN] = name
                if house    and CH: query_cols[CH] = house
                if relation and CR: query_cols[CR] = relation

                rows_s = []
                for _, row in subset.iterrows():
                    fs, tw, ws = {}, 0.0, 0.0
                    for col, qv in query_cols.items():
                        cell = str(row.get(col, '')).strip().upper()
                        w    = W.get(col, 1.0)
                        s    = _name_score(qv.upper(), cell)
                        fs[col] = round(s); tw += w; ws += s * w
                    comp = ws / tw if tw else 0
                    # Require name score ≥ 40 OR relation score ≥ 60 to avoid noise
                    name_s = fs.get(CN, 0) if CN else 0
                    rel_s  = fs.get(CR, 0) if CR else 0
                    if name_s < 40 and rel_s < 60: continue
                    rows_s.append({'_r': row, 'c': comp, 'fs': fs})
                    if comp >= 97: break   # early-exit on near-perfect match

                rows_s.sort(key=lambda x: x['c'], reverse=True)
                for item in rows_s[:5]:
                    r = item['_r']
                    suggestions_2002.append({
                        'name':     str(r.get(CN,'')),
                        'relation': str(r.get(CR,'')),
                        'house':    str(r.get(CH,'')),
                        'gender':   str(r.get(CG,'')) if CG else '',
                        'age':      str(r.get(CA,'')) if CA else '',
                        'voterid':  str(r.get(CE,'')) if CE else '',
                        'score':    round(item['c']),
                        'field_scores': {
                            'name':     item['fs'].get(CN, 0),
                            'relation': item['fs'].get(CR, 0),
                            'house':    item['fs'].get(CH, 0),
                        },
                    })
        except Exception:
            pass   # suggestions are best-effort

    # ── Similar 2025 records (same house or same name prefix, up to 8) ─────────
    similar_2025 = []
    _PROJ_SLIM = {'Name':1,'Relation Name':1,'Epic NO':1,'House No':1,'Gender':1,'Age':1}
    _seen_epics = {r25.get('voterid','')} if in_2025 else set()

    if house:
        for doc in col_2025.find({'House No': house}, _PROJ_SLIM).limit(12):
            d = bson_clean(doc)
            epic = str(d.get('Epic NO','')).strip()
            if epic in _seen_epics: continue
            _seen_epics.add(epic)
            similar_2025.append({
                'name':     str(d.get('Name','')).strip(),
                'relation': str(d.get('Relation Name','')).strip(),
                'house':    str(d.get('House No','')).strip(),
                'voterid':  epic,
                'gender':   str(d.get('Gender','')).strip(),
                'age':      str(d.get('Age','')).strip(),
            })
    elif name and len(name) >= 3:
        px = {'$regex': f'^{re.escape(name[:3])}', '$options': 'i'}
        for doc in col_2025.find({'Name': px}, _PROJ_SLIM).limit(12):
            d = bson_clean(doc)
            epic = str(d.get('Epic NO','')).strip()
            if epic in _seen_epics: continue
            _seen_epics.add(epic)
            similar_2025.append({
                'name':     str(d.get('Name','')).strip(),
                'relation': str(d.get('Relation Name','')).strip(),
                'house':    str(d.get('House No','')).strip(),
                'voterid':  epic,
                'gender':   str(d.get('Gender','')).strip(),
                'age':      str(d.get('Age','')).strip(),
            })
    similar_2025 = similar_2025[:8]

    return JsonResponse({
        'success':    True,
        'results':    results,
        'suspicious': suspicious,
        'changes':    changes,
        'stored':     False,
        'in_2025':    in_2025,
        'in_2002':    in_2002,
        'similar_2025': similar_2025,
        'suggestions_2002': suggestions_2002,   # ← fuzzy suggestions when 2002 not found
        # Full 2002 voter record
        'record_2002': {
            'name':     r02.get('name',     ''),
            'relation': r02.get('relation', ''),
            'house':    r02.get('house',    ''),
            'gender':   r02.get('gender',   ''),
            'age':      r02.get('age',      ''),
            'voterid':  r02.get('voterid',  ''),
        } if in_2002 else {},
        # Full 2025 voter record
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
    })


@require_http_methods(['GET'])
def api_sir_records(request):
    db       = get_db()
    category = request.GET.get('category', 'ALL')
    page     = max(1, int(request.GET.get('page', 1)))
    limit, skip = 50, (page - 1) * 50

    col_map = {
        'NEW_ADDITION': 'SIR_NewAdditions',
        'DELETION':     'SIR_Deletions',
        'MODIFICATION': 'SIR_Modifications',
        'SUSPICIOUS':   'SIR_Suspicious',
        'RETAINED':     'SIR_Retained',
    }

    if category in col_map:
        col   = db[col_map[category]]
        total = col.count_documents({})
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
    db = get_db()
    voters_2002 = db['2002'].count_documents({})
    voters_2025 = db['2025'].count_documents({})
    return JsonResponse({'success': True,
        'new_additions':  db['SIR_NewAdditions'].count_documents({}),
        'deletions':      db['SIR_Deletions'].count_documents({}),
        'modifications':  db['SIR_Modifications'].count_documents({}),
        'suspicious':     db['SIR_Suspicious'].count_documents({}),
        'retained':       db['SIR_Retained'].count_documents({}),
        'voters_2002':    voters_2002,
        'voters_2025':    voters_2025,
        'db_2002_status': 'ok' if voters_2002 > 0 else 'empty — place 2002.xlsx in project root and call /api/sync-2002/',
        'db_2025_status': 'ok' if voters_2025 > 0 else 'empty — upload voter list first',
    })


@require_http_methods(['GET'])
def api_sir_data(request):
    db       = get_db()
    category = request.GET.get('category', 'ALL').upper()
    page     = max(1, int(request.GET.get('page', 1)))
    limit    = 50
    skip     = (page - 1) * limit

    col_map = {
        'NEW':        'SIR_NewAdditions',
        'DELETED':    'SIR_Deletions',
        'MODIFIED':   'SIR_Modifications',
        'SUSPICIOUS': 'SIR_Suspicious',
        'RETAINED':   'SIR_Retained',
    }

    summary = {
        'NEW':        db['SIR_NewAdditions'].count_documents({}),
        'DELETED':    db['SIR_Deletions'].count_documents({}),
        'MODIFIED':   db['SIR_Modifications'].count_documents({}),
        'SUSPICIOUS': db['SIR_Suspicious'].count_documents({}),
        'RETAINED':   db['SIR_Retained'].count_documents({}),
    }
    summary['TOTAL'] = sum(summary.values())

    if category in col_map:
        col   = db[col_map[category]]
        total = col.count_documents({})
        raw   = col.find({}).sort('surveyed_at', -1).skip(skip).limit(limit)
        records = [_sir_to_frontend(bson_clean(d), category) for d in raw]
        return JsonResponse({'success': True, 'summary': summary,
                             'records': records, 'total': total})

    all_records = []
    for cat, cname in col_map.items():
        for d in db[cname].find({}).sort('surveyed_at', -1).limit(20):
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
    col_2002  = db['2002']
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
                db,
                voterid = d['voterid'],
                name    = d['name'],
                house   = d['house'],
                ward    = d['ward'],
                booth   = d['booth'],
                serial  = '',
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
                db,
                voterid  = d['voterid'],
                name     = d['name'],
                house    = d['house'],
                ward     = '',
                booth    = '',
                serial   = '',
                relation = d['relation'],
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


# ─── SESSION CHECK ────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_me(request):
    user = _user_from_request(request)
    if user:
        return JsonResponse({'loggedIn': True, 'username': user['username'], 'email': user['email']})
    return JsonResponse({'loggedIn': False}, status=401)