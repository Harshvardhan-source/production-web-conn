"""
connectors/ — one module per data source. Each exposes fetch(keywords) ->
list[dict], returning raw post dicts in a common shape before analysis:

    {
        "external_id": str,          # stable id for de-dup, unique per platform
        "platform": str,             # "youtube" | "news" | "x" | "instagram" | "facebook"
        "source_type": "live" | "mock",
        "post_type": "text" | "video",
        "account_handle": str,
        "account_name": str,
        "account_followers": int,
        "text": str,                 # caption/description/headline; "" if video-only
        "media_url": str,            # video/article URL
        "posted_at": iso8601 str,
        "tagged_accounts": list[str],
    }

Real connectors (youtube, news) only ever read public content via official
APIs. mock_social fabricates clearly-labelled demo posts for platforms
without a practical free public-search API (X, Instagram, Facebook).
"""
