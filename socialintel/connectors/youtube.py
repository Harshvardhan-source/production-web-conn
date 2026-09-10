"""
youtube.py — real connector. Searches public YouTube videos mentioning the
constituency via the official YouTube Data API v3 REST endpoints (plain
`requests`, no SDK dependency). Returns [] with a logged warning if
YOUTUBE_API_KEY isn't configured, so the rest of the pipeline degrades
gracefully rather than failing.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger('socialintel.youtube')

SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
VIDEOS_URL = 'https://www.googleapis.com/youtube/v3/videos'
CHANNELS_URL = 'https://www.googleapis.com/youtube/v3/channels'

REQUEST_TIMEOUT = 10


def _api_key():
    return getattr(settings, 'YOUTUBE_API_KEY', '') or ''


def fetch(keywords, max_results=15):
    api_key = _api_key()
    if not api_key:
        logger.info('[youtube] YOUTUBE_API_KEY not set — skipping live YouTube ingestion.')
        return []

    query = ' OR '.join(keywords)
    try:
        resp = requests.get(
            SEARCH_URL,
            params={
                'key': api_key,
                'part': 'snippet',
                'q': query,
                'type': 'video',
                'order': 'date',
                'maxResults': max_results,
                'relevanceLanguage': 'en',
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get('items', [])
    except Exception as exc:
        logger.warning('[youtube] search failed: %s', exc)
        return []

    video_ids = [it['id']['videoId'] for it in items if it.get('id', {}).get('videoId')]
    if not video_ids:
        return []

    stats_by_id = _fetch_video_stats(video_ids, api_key)

    posts = []
    for it in items:
        vid = it.get('id', {}).get('videoId')
        if not vid:
            continue
        snippet = it.get('snippet', {})
        stats = stats_by_id.get(vid, {})
        posts.append({
            'external_id': f'youtube:{vid}',
            'platform': 'youtube',
            'source_type': 'live',
            'post_type': 'video',
            'account_handle': snippet.get('channelTitle', 'unknown'),
            'account_name': snippet.get('channelTitle', 'Unknown channel'),
            'account_followers': stats.get('subscriberCount', 0),
            'text': f"{snippet.get('title', '')}\n{snippet.get('description', '')}".strip(),
            'media_url': f'https://www.youtube.com/watch?v={vid}',
            'image_url': (snippet.get('thumbnails', {}).get('high') or snippet.get('thumbnails', {}).get('default') or {}).get('url', ''),
            'posted_at': snippet.get('publishedAt'),
            'tagged_accounts': [],
        })
    return posts


def _fetch_video_stats(video_ids, api_key):
    """Best-effort channel subscriber counts, used for the 'tagged by a big
    account' virality signal. Failures here must never break ingestion."""
    try:
        resp = requests.get(
            VIDEOS_URL,
            params={'key': api_key, 'part': 'snippet', 'id': ','.join(video_ids)},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get('items', [])
        channel_ids = list({it['snippet']['channelId'] for it in items if it.get('snippet', {}).get('channelId')})
        if not channel_ids:
            return {}

        chan_resp = requests.get(
            CHANNELS_URL,
            params={'key': api_key, 'part': 'statistics', 'id': ','.join(channel_ids)},
            timeout=REQUEST_TIMEOUT,
        )
        chan_resp.raise_for_status()
        subs_by_channel = {
            c['id']: int(c.get('statistics', {}).get('subscriberCount', 0) or 0)
            for c in chan_resp.json().get('items', [])
        }
        return {
            it['id']: {'subscriberCount': subs_by_channel.get(it['snippet']['channelId'], 0)}
            for it in items
        }
    except Exception as exc:
        logger.warning('[youtube] stats lookup failed (non-fatal): %s', exc)
        return {}


def download_audio(video_url, out_dir):
    """Pull an audio-only stream for transcription when no captions exist.
    Imports yt-dlp lazily so the rest of the app works even before it's
    installed/deployed."""
    import os
    import uuid

    from yt_dlp import YoutubeDL

    out_path = os.path.join(out_dir, f'{uuid.uuid4().hex}.mp3')
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': out_path.replace('.mp3', '.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'quiet': True,
        'noprogress': True,
        'no_warnings': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    return out_path
