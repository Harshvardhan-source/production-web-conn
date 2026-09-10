"""
views.py — social-intel API endpoints. Plain function-based views returning
JsonResponse, following the exact conventions already used by the AI/SWOT
endpoints in calc/views.py (manual JWT auth, `_ai_cors`/`_ai_err` response
helpers, `bson_clean` for Mongo doc serialisation) rather than introducing a
second framework (no DRF anywhere in this codebase).
"""
import threading
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from calc.views import (
    _ai_cors,
    _ai_err,
    _is_approved,
    _user_from_request,
    bson_clean,
)

from . import db, jobs
from .nlp import analyzer

RECENT_WINDOW_DAYS = 14


def _require_approved(request):
    """Returns (user, error_response). error_response is None on success."""
    user = _user_from_request(request)
    if not user:
        return None, _ai_err(request, 'Unauthorized', status=401)
    if not _is_approved(user):
        return None, _ai_err(request, 'Account pending approval.', status=403)
    return user, None


def _recent_cutoff():
    return datetime.now(timezone.utc) - timedelta(days=RECENT_WINDOW_DAYS)


# ─────────────────────────────────────────────────────────────────────────────
# Overview
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_social_overview(request):
    user, err = _require_approved(request)
    if err:
        return err

    total = db.posts().count_documents({})
    sentiment_split = {
        row['_id']: row['count']
        for row in db.posts().aggregate([{'$group': {'_id': '$sentiment', 'count': {'$sum': 1}}}])
    }
    pending_jobs = db.posts().count_documents({'transcript_status': {'$in': ['pending', 'processing']}})
    outrage_alerts = db.posts().count_documents({'risk_level': 'high'})
    last_synced = {row['source']: row.get('last_synced') for row in db.sync_log().find({})}

    return _ai_cors(request, JsonResponse({
        'success': True,
        'total_posts': total,
        'sentiment_split': sentiment_split,
        'pending_transcription_jobs': pending_jobs,
        'outrage_alerts': outrage_alerts,
        'last_synced': bson_clean(last_synced),
    }))


# ─────────────────────────────────────────────────────────────────────────────
# Feed
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_social_feed(request):
    user, err = _require_approved(request)
    if err:
        return err

    query = {}
    for field in ('platform', 'category', 'sentiment', 'risk_level'):
        value = request.GET.get(field)
        if value:
            query[field] = value
    ward = request.GET.get('ward')
    if ward:
        query['wards'] = ward.upper()
    keyword = request.GET.get('q')
    if keyword:
        query['text'] = {'$regex': keyword, '$options': 'i'}

    try:
        page = max(1, int(request.GET.get('page', 1)))
        limit = min(100, max(1, int(request.GET.get('limit', 25))))
    except ValueError:
        page, limit = 1, 25

    cursor = (
        db.posts().find(query)
        .sort('posted_at', -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    items = [bson_clean(doc, keep_id=True) for doc in cursor]
    total = db.posts().count_documents(query)

    return _ai_cors(request, JsonResponse({
        'success': True,
        'items': items,
        'page': page,
        'limit': limit,
        'total': total,
    }))


@require_http_methods(['GET'])
def api_social_post_detail(request, post_id):
    user, err = _require_approved(request)
    if err:
        return err

    try:
        oid = ObjectId(post_id)
    except (InvalidId, TypeError):
        return _ai_err(request, 'Invalid post id.', status=400)

    doc = db.posts().find_one({'_id': oid})
    if not doc:
        return _ai_err(request, 'Post not found.', status=404)

    return _ai_cors(request, JsonResponse({'success': True, 'post': bson_clean(doc, keep_id=True)}))


# ─────────────────────────────────────────────────────────────────────────────
# SWOT board
# ─────────────────────────────────────────────────────────────────────────────

SWOT_CACHE_MINUTES = 30


@require_http_methods(['GET'])
def api_social_swot(request):
    user, err = _require_approved(request)
    if err:
        return err

    perspective = request.GET.get('perspective', 'political')
    if perspective not in ('political', 'administrative'):
        return _ai_err(request, "perspective must be 'political' or 'administrative'.", status=400)

    cached = db.swot().find_one({'perspective': perspective})
    stale = (
        not cached
        or cached.get('generated_at', datetime.min.replace(tzinfo=timezone.utc))
        < datetime.now(timezone.utc) - timedelta(minutes=SWOT_CACHE_MINUTES)
    )

    if stale:
        recent = list(db.posts().find({'posted_at': {'$gte': _recent_cutoff().isoformat()}}))
        board = analyzer.synthesize_swot(perspective, recent)
        db.swot().update_one(
            {'perspective': perspective},
            {'$set': {'perspective': perspective, 'board': board, 'generated_at': datetime.now(timezone.utc)}},
            upsert=True,
        )
        generated_at = datetime.now(timezone.utc)
    else:
        board = cached['board']
        generated_at = cached['generated_at']

    return _ai_cors(request, JsonResponse({
        'success': True,
        'perspective': perspective,
        'board': board,
        'generated_at': bson_clean(generated_at),
        'is_ai_assessed': True,
    }))


# ─────────────────────────────────────────────────────────────────────────────
# Consolidated report — text + image + video clip, grouped and highlighted
# ─────────────────────────────────────────────────────────────────────────────

REPORT_CACHE_MINUTES = 30


@require_http_methods(['GET'])
def api_social_report(request):
    user, err = _require_approved(request)
    if err:
        return err

    cached = db.get_db()['social_report'].find_one({'_id': 'latest'})
    stale = (
        not cached
        or cached.get('generated_at', datetime.min.replace(tzinfo=timezone.utc))
        < datetime.now(timezone.utc) - timedelta(minutes=REPORT_CACHE_MINUTES)
    )

    if not stale:
        return _ai_cors(request, JsonResponse({
            'success': True,
            'generated_at': bson_clean(cached['generated_at']),
            'groups': cached['groups'],
        }))

    recent = list(db.posts().find({'posted_at': {'$gte': _recent_cutoff().isoformat()}}))
    by_category = {}
    for p in recent:
        by_category.setdefault(p.get('category', 'other'), []).append(p)

    groups = []
    for category, posts in sorted(by_category.items(), key=lambda kv: -len(kv[1])):
        ranked = sorted(posts, key=lambda p: p.get('outrage_score', 0), reverse=True)
        overview = analyzer.summarize_category(category, ranked)
        groups.append({
            'category': category,
            'count': len(posts),
            'overview': overview,
            'highlighted_cases': [bson_clean(p, keep_id=True) for p in ranked[:6]],
        })

    generated_at = datetime.now(timezone.utc)
    db.get_db()['social_report'].update_one(
        {'_id': 'latest'},
        {'$set': {'generated_at': generated_at, 'groups': groups}},
        upsert=True,
    )

    return _ai_cors(request, JsonResponse({
        'success': True,
        'generated_at': bson_clean(generated_at),
        'groups': groups,
        'is_ai_assessed': True,
    }))


# ─────────────────────────────────────────────────────────────────────────────
# Outrage / trending
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_social_outrage(request):
    user, err = _require_approved(request)
    if err:
        return err

    top_posts = list(
        db.posts().find({'outrage_score': {'$gt': 0}})
        .sort('outrage_score', -1)
        .limit(20)
    )

    volume_series = list(db.posts().aggregate([
        {'$addFields': {
            '_day': {'$substrCP': [{'$ifNull': ['$posted_at', '']}, 0, 10]},
        }},
        {'$match': {'_day': {'$ne': ''}}},
        {'$group': {'_id': '_day', 'count': {'$sum': 1}}},
        {'$sort': {'_id': 1}},
        {'$limit': 30},
    ]))

    return _ai_cors(request, JsonResponse({
        'success': True,
        'top_posts': [bson_clean(p, keep_id=True) for p in top_posts],
        'volume_series': [{'date': row['_id'], 'count': row['count']} for row in volume_series],
        'is_ai_assessed': True,
    }))


# ─────────────────────────────────────────────────────────────────────────────
# Job status (background-activity indicator)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_social_jobs_status(request):
    user, err = _require_approved(request)
    if err:
        return err

    counts = {
        row['_id']: row['count']
        for row in db.posts().aggregate([{'$group': {'_id': '$transcript_status', 'count': {'$sum': 1}}}])
    }
    active = counts.get('pending', 0) + counts.get('processing', 0)

    return _ai_cors(request, JsonResponse({
        'success': True,
        'counts': counts,
        'active': active,
    }))


# ─────────────────────────────────────────────────────────────────────────────
# Manual sync trigger
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST', 'OPTIONS'])
def api_social_sync(request):
    if request.method == 'OPTIONS':
        return _ai_cors(request, JsonResponse({}))

    user, err = _require_approved(request)
    if err:
        return err

    thread = threading.Thread(target=jobs.run_ingestion_cycle, daemon=True)
    thread.start()

    return _ai_cors(request, JsonResponse({'success': True, 'message': 'Sync started in the background.'}))


# ─────────────────────────────────────────────────────────────────────────────
# Sources / transparency panel
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(['GET'])
def api_social_sources(request):
    user, err = _require_approved(request)
    if err:
        return err

    youtube_live = bool(getattr(settings, 'YOUTUBE_API_KEY', ''))
    web_search_live = bool(getattr(settings, 'GOOGLE_CSE_API_KEY', '')) and bool(getattr(settings, 'GOOGLE_CSE_CX', ''))
    last_synced = {row['source']: row.get('last_synced') for row in db.sync_log().find({})}

    sources = [
        {'platform': 'youtube', 'source_type': 'live' if youtube_live else 'not_configured',
         'note': 'YouTube Data API v3' if youtube_live else 'Set YOUTUBE_API_KEY to enable.',
         '_sync_key': 'youtube'},
        {'platform': 'news', 'source_type': 'live', 'note': 'Google News RSS (public, no key required).',
         '_sync_key': 'news'},
        {'platform': 'web', 'source_type': 'live' if web_search_live else 'not_configured',
         'note': 'Google Programmable Search (free tier)' if web_search_live else 'Set GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX to enable.',
         '_sync_key': 'web_search'},
        {'platform': 'x', 'source_type': 'mock', 'note': 'Demo data — no practical free public-search API.',
         '_sync_key': 'mock'},
        {'platform': 'instagram', 'source_type': 'mock', 'note': 'Demo data — no practical free public-search API.',
         '_sync_key': 'mock'},
        {'platform': 'facebook', 'source_type': 'mock', 'note': 'Demo data — no practical free public-search API.',
         '_sync_key': 'mock'},
    ]
    for s in sources:
        s['last_synced'] = bson_clean(last_synced.get(s.pop('_sync_key')))

    return _ai_cors(request, JsonResponse({'success': True, 'sources': sources}))
