"""
Lightweight region detection for sales-pipeline leads.

The Apify `harvestapi/linkedin-post-search` actor returns NO author location
field and offers no country search filter, so we infer the region client-side
from the post text + author headline (e.g. "PAN India Hiring" → india,
"based in Dubai" → uae, "£" → uk).

Region is detection-only here — it never filters posts out of the pipeline.
The HTML dashboard uses `data-region` to let the user filter visually, and any
lead with no detectable region lands in the "Unmapped" bucket.
"""

import re
from agent.parser import LinkedInPost


# ─── Region definitions ──────────────────────────────────────────────────────
# Each entry: key → (label, flag, [matcher tokens])
#
# Matchers are intentionally a mix of country names, major cities, currency
# markers and locale tokens. Detection is word-boundary safe (see below), so
# "us" alone is deliberately omitted — it matches too many English words.
# Generic currency symbols ($ € £) are treated as WEAK signals and only
# consulted if no stronger geographic token fires (handled by the priority
# order in detect_region).
REGIONS: list[dict] = [
    {
        "key": "uae",
        "label": "Dubai / UAE",
        "flag": "🇦🇪",
        "tokens": [
            "dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah",
            "fujairah", "uae", "u.a.e", "united arab emirates", "emirates",
            "dirham", "aed",
        ],
    },
    {
        "key": "saudi",
        "label": "Saudi Arabia",
        "flag": "🇸🇦",
        "tokens": [
            "saudi arabia", "saudi", "riyadh", "jeddah", "dammam", "mecca",
            "medina", "khobar", "ksa", "saudi riyal", "sar",
        ],
    },
    {
        "key": "india",
        "label": "India",
        "flag": "🇮🇳",
        "tokens": [
            "india", "indian", "mumbai", "delhi", "new delhi", "noida",
            "gurgaon", "gurugram", "bangalore", "bengaluru", "hyderabad",
            "pune", "chennai", "kolkata", "ahmedabad", "jaipur", "kochi",
            "coimbatore", "indore", "chandigarh", "pan india", "pan-india",
            "tamil nadu", "karnataka", "maharashtra", "gujarat", "₹", "inr",
            "rupees",
        ],
    },
    {
        "key": "uk",
        "label": "United Kingdom",
        "flag": "🇬🇧",
        "tokens": [
            "united kingdom", "uk", "u.k", "london", "manchester", "birmingham",
            "leeds", "bristol", "liverpool", "glasgow", "edinburgh", "england",
            "scotland", "wales", "northern ireland", "british", "britain",
            "£", "gbp", "pound sterling",
        ],
    },
    {
        "key": "us",
        "label": "United States",
        "flag": "🇺🇸",
        "tokens": [
            "united states", "usa", "u.s.a", "america", "american",
            "new york", "nyc", "los angeles", "chicago", "houston", "phoenix",
            "san francisco", "san jose", "seattle", "boston", "austin",
            "dallas", "atlanta", "denver", "miami", "washington dc",
            "silicon valley", "bay area", "california", "texas", "florida",
            "illinois", "new jersey", "usd", "us$",
        ],
    },
    {
        "key": "europe",
        "label": "Europe",
        "flag": "🇪🇺",
        "tokens": [
            "europe", "european", "germany", "berlin", "munich", "frankfurt",
            "france", "paris", "lyon", "netherlands", "amsterdam",
            "spain", "madrid", "barcelona", "italy", "milan", "rome",
            "sweden", "stockholm", "norway", "oslo", "denmark", "copenhagen",
            "finland", "helsinki", "switzerland", "zurich", "geneva",
            "austria", "vienna", "belgium", "brussels", "poland", "warsaw",
            "portugal", "lisbon", "greece", "athens", "ireland", "dublin",
            "czech", "prague", "euro", "€", "eur",
        ],
    },
]

# Pre-compiled: token → regex (word-boundary safe). Currency symbols don't use
# \b (they're not word chars), so they're matched literally instead.
_COMPILED: list[tuple[str, str, re.Pattern]] = []
for _r in REGIONS:
    for _tok in _r["tokens"]:
        if _tok[0].isalpha():
            _pat = re.compile(rf"\b{re.escape(_tok)}\b", re.IGNORECASE)
        else:
            _pat = re.compile(re.escape(_tok), re.IGNORECASE)
        _COMPILED.append((_r["key"], _tok, _pat))

# Weak currency-only signals — only consulted if no strong token matched.
# NOTE: bare "$" is deliberately excluded — it's ambiguous (USD/CAD/AUD/SGD/HKD
# all use "$"). Regions rely on explicit "usd"/"us$" or geographic tokens.
# Bare "₹", "£", "€", "aed" etc. are unambiguous and stay in the weak set.
_WEAK_TOKENS = {"₹", "inr", "rupees", "£", "gbp", "pound sterling",
                "€", "euro", "eur", "aed", "dirham", "sar", "saudi riyal"}

# Stable lookup for label/flag from a region key (used by the reporter).
_BY_KEY: dict[str, dict] = {r["key"]: r for r in REGIONS}


def detect_region(post: LinkedInPost) -> str:
    """
    Return the region key for a post, or "" when no region can be detected.

    Scans snippet + author headline (the two text fields LinkedIn gives us).
    The first STRONG geographic token wins (priority order in REGIONS); if
    only a currency symbol fires, that still counts but is checked last.
    """
    text = f"{post.snippet or ''} {post.author_headline or ''}".lower()

    # Pass 1 — strong geographic tokens (cities / country names).
    for _key, _tok, _pat in _COMPILED:
        if _tok in _WEAK_TOKENS:
            continue
        if _pat.search(text):
            return _key

    # Pass 2 — weak currency-only signals, same priority order.
    for _key, _tok, _pat in _COMPILED:
        if _tok not in _WEAK_TOKENS:
            continue
        if _pat.search(text):
            return _key

    return ""


def region_label(key: str) -> str:
    """Human label for a region key (e.g. 'india' → 'India')."""
    return _BY_KEY.get(key, {}).get("label", "Unmapped")


def region_flag(key: str) -> str:
    """Flag emoji for a region key (e.g. 'india' → '🇮🇳'). Unknown → '❓'."""
    return _BY_KEY.get(key, {}).get("flag", "❓")
