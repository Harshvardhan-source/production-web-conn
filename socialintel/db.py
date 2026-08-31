"""
db.py — MongoDB access for the social-intel module.

Follows the same pattern as calc/views.py's get_db()/get_db1(): a single
MongoClient created once at import time and reused across requests, pointed
at settings.MONGODB_URL (same cluster the rest of the app already uses), but
its own database ("SocialIntelDB") so this module never touches the voter
roll / survey collections.
"""
import logging

import certifi
from django.conf import settings
from pymongo import ASCENDING, DESCENDING, MongoClient

logger = logging.getLogger('socialintel')

_MONGO_OPTS = dict(
    tls=True,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    socketTimeoutMS=30000,
    tz_aware=True,   # so datetimes read back compare cleanly against datetime.now(timezone.utc)
)

try:
    _client = MongoClient(settings.MONGODB_URL, maxPoolSize=10, minPoolSize=1, **_MONGO_OPTS)
except Exception as exc:
    logger.error('[socialintel.db] MongoClient failed to initialise: %s', exc)
    _client = None


def get_db():
    if _client is None:
        raise RuntimeError('Social-intel MongoDB client not initialised. Check MONGODB_URL.')
    return _client.get_database('SocialIntelDB')


def posts():
    return get_db()['social_posts']


def accounts():
    return get_db()['social_accounts']


def swot():
    return get_db()['social_swot']


def jobs_col():
    return get_db()['social_jobs']


def sync_log():
    return get_db()['social_sync_log']


def ensure_indexes():
    """Call once at startup; safe to call repeatedly (create_index is idempotent)."""
    try:
        posts().create_index([('external_id', ASCENDING)], unique=True, sparse=True)
        posts().create_index([('posted_at', DESCENDING)])
        posts().create_index([('platform', ASCENDING)])
        posts().create_index([('category', ASCENDING)])
        posts().create_index([('risk_level', ASCENDING)])
        posts().create_index([('transcript_status', ASCENDING)])
        jobs_col().create_index([('post_id', ASCENDING)])
        jobs_col().create_index([('status', ASCENDING)])
        sync_log().create_index([('source', ASCENDING)], unique=True)
    except Exception as exc:
        logger.warning('[socialintel.db] ensure_indexes failed (non-fatal): %s', exc)
