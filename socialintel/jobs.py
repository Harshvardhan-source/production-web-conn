"""
jobs.py — background execution, deliberately without Celery/Redis (this repo
has no queue infrastructure anywhere; adding one just for this module would
be a lot of new infra for a single-dyno deployment). Instead:

  * one long-lived daemon thread per process runs the ingestion cycle on a
    timer, guarded by a Mongo lock document so multiple gunicorn workers
    don't all run it at once
  * each video post that needs transcription gets its own short-lived daemon
    thread, with progress tracked directly on the post document
    (transcript_status: pending -> processing -> done|failed) so the
    frontend can poll and show "still working" state without blocking on it
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from . import db
from .connectors import mock_social, news, web_search, youtube
from .nlp import analyzer, transcribe

logger = logging.getLogger('socialintel.jobs')

INGESTION_INTERVAL_SECONDS = 15 * 60
_LOCK_ID = 'ingestion_scheduler'
_scheduler_thread_started = False
_scheduler_lock = threading.Lock()

# Constituency + party + candidate-surname coverage. "Kamath" and "BJP" are
# kept as surname/party-only (not a fabricated full name) — tighten this to
# the exact candidate name whenever you have it confirmed.
KEYWORDS = [
    'Mangalore South constituency', 'Mangaluru South MLA', 'Mangaluru South ward',
    'Mangaluru South BJP', 'Mangaluru South Kamath',
]


def _ward_names():
    from calc.views import WARD_FULL_DATA
    return [w['name'] for w in WARD_FULL_DATA.values()]


def _tag_wards(text):
    """Best-effort: which wards (if any) does this text mention by name."""
    if not text:
        return []
    from calc.views import WARD_NAME_TO_BOOTHS
    upper = text.upper()
    return [name for name in WARD_NAME_TO_BOOTHS if name in upper]


def start_scheduler_once():
    """Idempotent within a process; call from AppConfig.ready()."""
    global _scheduler_thread_started
    with _scheduler_lock:
        if _scheduler_thread_started:
            return
        _scheduler_thread_started = True
    thread = threading.Thread(target=_scheduler_loop, name='socialintel-scheduler', daemon=True)
    thread.start()
    logger.info('[socialintel] ingestion scheduler thread started (interval=%ss)', INGESTION_INTERVAL_SECONDS)


def _scheduler_loop():
    db.ensure_indexes()
    while True:
        try:
            if _try_acquire_cycle_lock():
                run_ingestion_cycle()
        except Exception:
            logger.exception('[socialintel] ingestion cycle failed')
        time.sleep(INGESTION_INTERVAL_SECONDS)


def _try_acquire_cycle_lock():
    """Best-effort cross-process guard: only proceed if no other process
    claimed a cycle in the last INGESTION_INTERVAL_SECONDS. Not a hard
    distributed lock — fine for this deployment's scale.

    When the lock is currently held, the filter below matches nothing, so
    upsert=True tries to *insert* a document with _id=_LOCK_ID — which
    collides with the doc that's already there and raises DuplicateKeyError.
    That collision is itself the signal "someone else holds the lock", so we
    catch it rather than treating it as a real error.
    """
    now = datetime.now(timezone.utc)
    try:
        db.jobs_col().find_one_and_update(
            {
                '_id': _LOCK_ID,
                '$or': [
                    {'locked_until': {'$lt': now}},
                    {'locked_until': {'$exists': False}},
                ],
            },
            {'$set': {'locked_until': now + timedelta(seconds=INGESTION_INTERVAL_SECONDS - 30)}},
            upsert=True,
        )
        return True
    except DuplicateKeyError:
        return False


def run_ingestion_cycle():
    """Fetch from every connector, insert new posts, classify them, and kick
    off transcription for anything video-shaped."""
    ward_names = _ward_names()
    raw_posts = []
    raw_posts += _safe_fetch('youtube', lambda: youtube.fetch(KEYWORDS))
    raw_posts += _safe_fetch('news', lambda: news.fetch(KEYWORDS))
    raw_posts += _safe_fetch('web_search', lambda: web_search.fetch(KEYWORDS))
    raw_posts += _safe_fetch('mock', lambda: mock_social.fetch(ward_names))

    inserted = 0
    for raw in raw_posts:
        if _insert_new_post(raw):
            inserted += 1
    logger.info('[socialintel] ingestion cycle: %d new posts (of %d fetched)', inserted, len(raw_posts))


def _safe_fetch(name, fn):
    try:
        results = fn()
        db.sync_log().update_one(
            {'source': name},
            {'$set': {'source': name, 'last_synced': datetime.now(timezone.utc), 'last_count': len(results)}},
            upsert=True,
        )
        return results
    except Exception:
        logger.exception('[socialintel] connector %s failed', name)
        return []


def _insert_new_post(raw):
    existing = db.posts().find_one({'external_id': raw['external_id']})
    if existing:
        return False

    category_hint = raw.pop('_category_hint', None)
    analysis = analyzer.analyze_post(raw.get('text', ''), category_hint=category_hint)

    doc = {
        **raw,
        **analysis,
        'wards': _tag_wards(raw.get('text', '')),
        'transcript': '',
        'transcript_status': 'not_applicable',
        'fetched_at': datetime.now(timezone.utc),
    }
    try:
        result = db.posts().insert_one(doc)
    except DuplicateKeyError:
        # Another process/thread inserted the same external_id between our
        # find_one check and this insert — the unique index is exactly the
        # safety net for that race, so just treat it as "already exists".
        return False
    post_id = result.inserted_id

    if doc.get('post_type') == 'video' and doc.get('platform') == 'youtube':
        db.posts().update_one({'_id': post_id}, {'$set': {'transcript_status': 'pending'}})
        enqueue_transcription(post_id)

    return True


def enqueue_transcription(post_id):
    thread = threading.Thread(target=_run_transcription, args=(post_id,), daemon=True)
    thread.start()


def _run_transcription(post_id):
    db.posts().update_one({'_id': post_id}, {'$set': {'transcript_status': 'processing'}})
    post = db.posts().find_one({'_id': post_id})
    if not post:
        return
    try:
        text = transcribe.transcribe_video_url(post['media_url'])
        # Re-classify using the transcript now that we have real spoken content.
        combined_text = f"{post.get('text', '')}\n\nTranscript: {text}".strip()
        analysis = analyzer.analyze_post(combined_text)
        db.posts().update_one(
            {'_id': post_id},
            {'$set': {
                'transcript': text,
                'transcript_status': 'done',
                **analysis,
            }},
        )
    except Exception as exc:
        logger.warning('[socialintel] transcription failed for %s: %s', post_id, exc)
        db.posts().update_one(
            {'_id': post_id},
            {'$set': {'transcript_status': 'failed', 'transcript_error': str(exc)}},
        )
