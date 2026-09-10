"""
analyzer.py — Claude-based per-post classification.

Reuses the existing Anthropic integration (calc.views._get_anthropic) and the
same "instruct JSON-only, strip ```json fences, json.loads with a graceful
fallback" pattern already used by api_ai_query_insight / api_swot_overview,
so this module doesn't introduce a second way of talking to Claude.

All labels are explicitly framed as AI-assessed, not ground truth about any
individual — the frontend must surface them as such.
"""
import json
import logging

from calc.views import CONSTITUENCY_NAME, _get_anthropic

logger = logging.getLogger('socialintel.analyzer')

MODEL = 'claude-haiku-4-5-20251001'   # same tier already used for api_swot_overview

SYSTEM_PROMPT = (
    f"You are an AI analyst assisting with PUBLIC social-media and news monitoring for "
    f"{CONSTITUENCY_NAME} constituency (Karnataka, India). You are given ONE public post, "
    "video caption, or news headline. Classify it and return a JSON object ONLY "
    "(no markdown, no extra text) with this exact structure:\n"
    '{"category":"political_statement|project_statement|protest|administrative|single_statement|other",'
    '"sentiment":"positive|neutral|negative",'
    '"risk_level":"low|medium|high",'
    '"outrage_score":<integer 0-100, how much public anger/virality this content signals>,'
    '"swot_quadrant":"strength|weakness|opportunity|threat|none",'
    '"swot_perspective":"political|administrative|none",'
    '"summary":"one plain-language sentence, under 20 words"}\n\n'
    "Guidance: this is AI-assisted triage, not a factual judgement about any person. "
    "Be conservative with risk_level=high — reserve it for content suggesting real "
    "unrest, safety concerns, or reputational escalation, not routine complaints."
)


def _fallback_result():
    return {
        'category': 'other',
        'sentiment': 'neutral',
        'risk_level': 'low',
        'outrage_score': 0,
        'swot_quadrant': 'none',
        'swot_perspective': 'none',
        'summary': '',
        '_analysis_error': True,
    }


def analyze_post(text, category_hint=None):
    """Classify a single post's text (or transcript). Never raises — on any
    failure it returns a safe fallback so ingestion keeps moving."""
    if not text or not text.strip():
        return _fallback_result()

    user_prompt = f"Post text:\n{text.strip()[:4000]}"
    if category_hint:
        user_prompt += f"\n\n(Hint: this was generated as a demo '{category_hint}' example.)"

    try:
        client = _get_anthropic()
        message = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': user_prompt}],
            timeout=20.0,
        )
        raw = ''.join(b.text for b in message.content if hasattr(b, 'text')).strip()
        raw = raw.lstrip('```json').lstrip('```').rstrip('```').strip()
        result = json.loads(raw)
        # Clamp/validate so bad model output can't corrupt downstream filters.
        result['outrage_score'] = max(0, min(100, int(result.get('outrage_score', 0) or 0)))
        result.setdefault('category', 'other')
        result.setdefault('sentiment', 'neutral')
        result.setdefault('risk_level', 'low')
        result.setdefault('swot_quadrant', 'none')
        result.setdefault('swot_perspective', 'none')
        result.setdefault('summary', '')
        return result
    except Exception as exc:
        logger.warning('[analyzer] classification failed, using fallback: %s', exc)
        return _fallback_result()


def summarize_category(category, posts):
    """One-paragraph AI overview of what's happening in one category, for the
    consolidated report. `posts` should already be classified documents."""
    if not posts:
        return ''

    bullets = '\n'.join(f"- {p.get('summary') or (p.get('text') or '')[:140]}" for p in posts[:25])
    system_prompt = (
        f"You are drafting one section of a consolidated public-monitoring briefing for "
        f"{CONSTITUENCY_NAME} constituency, covering the '{category}' category. Given the "
        "bullet points below (already-classified public posts/news), write ONE plain-language "
        "paragraph (3-5 sentences) summarising the overall pattern — what's happening, how "
        "serious it looks, and whether it's escalating. This is AI-assisted triage for a "
        "campaign/administrative team, not a factual verdict on any individual. Return plain "
        "text only, no markdown, no JSON."
    )
    try:
        client = _get_anthropic()
        message = client.messages.create(
            model=MODEL,
            max_tokens=220,
            system=system_prompt,
            messages=[{'role': 'user', 'content': bullets}],
            timeout=20.0,
        )
        return ''.join(b.text for b in message.content if hasattr(b, 'text')).strip()
    except Exception as exc:
        logger.warning('[analyzer] category summary failed for %s: %s', category, exc)
        return ''


def synthesize_swot(perspective, classified_posts):
    """Roll up recent classified posts into a 2x2 SWOT board for one
    perspective ("political" or "administrative") using Claude."""
    relevant = [
        p for p in classified_posts
        if p.get('swot_perspective') == perspective and p.get('swot_quadrant') != 'none'
    ]
    if not relevant:
        return {q: [] for q in ('strength', 'weakness', 'opportunity', 'threat')}

    bullets = '\n'.join(
        f"- [{p['swot_quadrant']}] {p.get('summary') or p.get('text', '')[:120]}"
        for p in relevant[:60]
    )
    system_prompt = (
        f"You are synthesising a {perspective}-perspective SWOT board for {CONSTITUENCY_NAME} "
        "constituency from a list of already-classified public social/news items below. "
        "Merge duplicates/near-duplicates into single bullet points. Return JSON ONLY:\n"
        '{"strength":["..."],"weakness":["..."],"opportunity":["..."],"threat":["..."]}\n'
        'Max 6 bullets per quadrant, each under 18 words. Omit any quadrant with no signal '
        '(use an empty list).'
    )
    try:
        client = _get_anthropic()
        message = client.messages.create(
            model=MODEL,
            max_tokens=700,
            system=system_prompt,
            messages=[{'role': 'user', 'content': bullets}],
            timeout=25.0,
        )
        raw = ''.join(b.text for b in message.content if hasattr(b, 'text')).strip()
        raw = raw.lstrip('```json').lstrip('```').rstrip('```').strip()
        board = json.loads(raw)
        for q in ('strength', 'weakness', 'opportunity', 'threat'):
            board.setdefault(q, [])
        return board
    except Exception as exc:
        logger.warning('[analyzer] SWOT synthesis failed: %s', exc)
        return {q: [] for q in ('strength', 'weakness', 'opportunity', 'threat')}
