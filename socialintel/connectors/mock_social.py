"""
mock_social.py — clearly-labelled demo data for platforms whose free public
search APIs are no longer practically available (X/Twitter, Instagram,
Facebook). Every post from this module carries source_type="mock" and a
placeholder handle that can never be confused with a real citizen's account,
so a fabricated statement is never mistaken for something a real person
actually said. This is filler for the dashboard, not a claim about any real
account or event.
"""
import hashlib
import random
from datetime import datetime, timedelta, timezone

PLATFORMS = ['x', 'instagram', 'facebook']

# Template statements per category. {ward} is filled with a real locality
# name from WARD_FULL_DATA so the demo feed reads as constituency-relevant,
# but the handle/account below it is always synthetic.
TEMPLATES = {
    'political_statement': [
        "The MLA's office needs to answer for the delay on the {ward} flyover project.",
        "Great turnout at today's public meeting in {ward} — people want real answers, not promises.",
        "Why hasn't the {ward} ward development fund been utilised this quarter?",
    ],
    'project_statement': [
        "Road resurfacing work has finally started near {ward} junction. About time.",
        "New streetlights installed across {ward} this week — small win for residents.",
        "The {ward} drainage project is 60% complete according to the ward office.",
    ],
    'protest': [
        "Residents of {ward} gathered outside the ward office over the water shortage.",
        "Fish market vendors in {ward} staged a protest against the relocation notice.",
        "Auto drivers' union held a demonstration near {ward} demanding fare revision.",
    ],
    'administrative': [
        "Ward office in {ward} extended working hours for property tax collection this week.",
        "BBMP-style waste segregation drive launched in {ward} starting Monday.",
        "New water tanker schedule published for {ward} residents.",
    ],
    'single_statement': [
        "Traffic near {ward} circle has gotten worse this month, someone needs to look into it.",
        "Good to see the {ward} park finally getting maintained again.",
        "Power cuts in {ward} area three times this week, is anyone tracking this?",
    ],
}

_HANDLE_ADJECTIVES = ['local', 'concerned', 'active', 'daily', 'ward', 'civic', 'resident']
_HANDLE_NOUNS = ['voice', 'watch', 'update', 'citizen', 'observer', 'tracker']


def _synthetic_handle(seed):
    rng = random.Random(seed)
    adj = rng.choice(_HANDLE_ADJECTIVES)
    noun = rng.choice(_HANDLE_NOUNS)
    num = rng.randint(100, 999)
    return f'demo_{adj}_{noun}_{num}'


def fetch(ward_names, count=12):
    """Generate `count` clearly-labelled mock posts spread across categories
    and platforms, referencing real ward names for local flavour."""
    if not ward_names:
        ward_names = ['Mangalore South']

    rng = random.Random()
    posts = []
    now = datetime.now(timezone.utc)

    for _ in range(count):
        category = rng.choice(list(TEMPLATES.keys()))
        template = rng.choice(TEMPLATES[category])
        ward = rng.choice(ward_names)
        text = template.format(ward=ward.title())
        platform = rng.choice(PLATFORMS)
        seed = f'{platform}:{text}:{rng.random()}'
        handle = _synthetic_handle(seed)
        followers = rng.choice([120, 480, 2100, 8600, 45000, 210000])
        posted_at = now - timedelta(minutes=rng.randint(5, 60 * 24 * 3))
        external_id = f'mock:{hashlib.sha1(seed.encode()).hexdigest()[:16]}'

        posts.append({
            'external_id': external_id,
            'platform': platform,
            'source_type': 'mock',
            'post_type': 'text',
            'account_handle': handle,
            'account_name': f'Demo account ({platform})',
            'account_followers': followers,
            'text': text,
            'media_url': '',
            'posted_at': posted_at.isoformat(),
            'tagged_accounts': [],
            '_category_hint': category,   # analyzer may use this as a strong prior
        })
    return posts
