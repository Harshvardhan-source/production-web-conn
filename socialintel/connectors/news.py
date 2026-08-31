"""
news.py — real connector. Pulls public news coverage mentioning the
constituency via Google News' public RSS search feed (no API key required).
"""
import hashlib
import logging
from urllib.parse import quote

import feedparser

logger = logging.getLogger('socialintel.news')

RSS_URL = 'https://news.google.com/rss/search'
REQUEST_TIMEOUT = 10


def fetch(keywords, max_results=15):
    query = ' OR '.join(f'"{kw}"' for kw in keywords)
    url = f'{RSS_URL}?q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en'

    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        logger.warning('[news] RSS fetch failed: %s', exc)
        return []

    posts = []
    for entry in feed.entries[:max_results]:
        link = entry.get('link', '')
        if not link:
            continue
        external_id = f'news:{hashlib.sha1(link.encode()).hexdigest()[:16]}'
        source_title = getattr(entry, 'source', {}).get('title', 'Unknown outlet') if hasattr(entry, 'source') else 'Unknown outlet'
        posts.append({
            'external_id': external_id,
            'platform': 'news',
            'source_type': 'live',
            'post_type': 'text',
            'account_handle': source_title,
            'account_name': source_title,
            'account_followers': 0,
            'text': entry.get('title', ''),
            'media_url': link,
            'posted_at': entry.get('published', None),
            'tagged_accounts': [],
        })
    return posts
