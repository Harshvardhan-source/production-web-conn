"""
web_search.py — real connector. Uses the Google Programmable Search Engine
(Custom Search JSON API) — a free-tier (100 queries/day), official, ToS-
compliant API — to find public web pages (news, blogs, forums, social-post
mirrors indexed by Google) mentioning the constituency/candidate/party. This
is the legitimate substitute for "search everywhere it's mentioned": it
covers far more of the public web than the News RSS connector alone, and
returns a thumbnail image per result where the page has one, which the News
and mock connectors can't provide.

Needs GOOGLE_CSE_API_KEY (free, Google Cloud Console) and GOOGLE_CSE_CX (a
Programmable Search Engine ID configured to search the whole web, free at
https://programmablesearchengine.google.com/). Returns [] gracefully if
either is unset.
"""
import hashlib
import logging

import requests
from django.conf import settings

logger = logging.getLogger('socialintel.web_search')

SEARCH_URL = 'https://www.googleapis.com/customsearch/v1'
REQUEST_TIMEOUT = 10


def _configured():
    return bool(getattr(settings, 'GOOGLE_CSE_API_KEY', '')) and bool(getattr(settings, 'GOOGLE_CSE_CX', ''))


def fetch(keywords, max_results=10):
    if not _configured():
        logger.info('[web_search] GOOGLE_CSE_API_KEY/GOOGLE_CSE_CX not set — skipping.')
        return []

    query = ' OR '.join(f'"{kw}"' for kw in keywords)
    try:
        resp = requests.get(
            SEARCH_URL,
            params={
                'key': settings.GOOGLE_CSE_API_KEY,
                'cx': settings.GOOGLE_CSE_CX,
                'q': query,
                'num': min(max_results, 10),   # API max per request
                'sort': 'date',
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get('items', [])
    except Exception as exc:
        logger.warning('[web_search] search failed: %s', exc)
        return []

    posts = []
    for it in items:
        link = it.get('link', '')
        if not link:
            continue
        image_url = ''
        pagemap = it.get('pagemap', {})
        cse_images = pagemap.get('cse_image') or pagemap.get('cse_thumbnail')
        if cse_images:
            image_url = cse_images[0].get('src', '')

        posts.append({
            'external_id': f'web:{hashlib.sha1(link.encode()).hexdigest()[:16]}',
            'platform': 'web',
            'source_type': 'live',
            'post_type': 'text',
            'account_handle': it.get('displayLink', 'unknown site'),
            'account_name': it.get('displayLink', 'Unknown site'),
            'account_followers': 0,
            'text': f"{it.get('title', '')}\n{it.get('snippet', '')}".strip(),
            'media_url': link,
            'image_url': image_url,
            'posted_at': None,   # CSE doesn't reliably expose publish dates
            'tagged_accounts': [],
        })
    return posts
