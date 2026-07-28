import re

from config.settings import MOMENT_SIGNALS
from agent.parser import LinkedInPost


# ─── Word-boundary matcher for signal keywords ───────────────────────────────
# The old code used `if kw in text`, which let short keywords match as
# SUBSTRINGS: "reel" inside "freelance" (→ Film tag on a web-dev post), "pr"
# inside "improvement"/"proposals", "brand" inside "branding" (harmless).
# We compile each keyword to a word-boundary regex so it only matches when it
# actually appears as a term. Alphanumeric phrases use \b; non-alphanumeric
# (rare here) fall back to literal contains.
_COMPILED_KEYWORDS: dict[str, re.Pattern] = {}


def _kw_pattern(kw: str) -> re.Pattern:
    p = _COMPILED_KEYWORDS.get(kw)
    if p is None:
        kw_l = kw.lower()
        # Use \b only when the keyword begins/ends with a word char so the
        # boundary is meaningful; otherwise it's a literal substring match.
        left = r"(?<!\w)" if kw_l[0:1].isalnum() else ""
        right = r"(?!\w)" if kw_l[-1:].isalnum() else ""
        p = re.compile(rf"{left}{re.escape(kw_l)}{right}", re.IGNORECASE)
        _COMPILED_KEYWORDS[kw] = p
    return p


def _keyword_in_text(kw: str, text: str) -> bool:
    return _kw_pattern(kw).search(text) is not None


def score_post(post: LinkedInPost, competitor_keywords: list[str] = None) -> LinkedInPost:
    """
    Scan post text for agency-prospecting signals, compute intent score (1–10),
    and tag which services to pitch.
    Modifies the post in-place and returns it.
    """
    text = f"{post.title} {post.snippet}".lower()
    signals_found = []
    max_score = 0
    matched_service_tags = set()

    for signal_id, cfg in MOMENT_SIGNALS.items():
        matched_kw = [kw for kw in cfg["keywords"] if _keyword_in_text(kw, text)]
        if matched_kw:
            signals_found.append({
                "id": signal_id,
                "label": cfg["label"],
                "icon": cfg["icon"],
                "score": cfg["score"],
                "matched_keywords": matched_kw,
                "service_tags": cfg.get("service_tags", []),
            })
            if cfg["score"] > max_score:
                max_score = cfg["score"]
            # Track which services' keywords ACTUALLY fired in this signal —
            # not the whole tag list (avoids over-tagging: a "reel" substring
            # match used to attach Film to every freelance post).
            matched_service_tags.update(cfg.get("service_tags", []))

    # Competitor mentions — prospect may be unhappy with current agency/vendor
    if competitor_keywords:
        comp_hits = [c for c in competitor_keywords if c.lower() in text]
        if comp_hits:
            signals_found.append({
                "id": "competitor_mentioned",
                "label": "Competitor Mentioned",
                "icon": "⚔️",
                "score": 6,
                "matched_keywords": comp_hits,
                "service_tags": ["SEO", "SEM", "Brand"],
            })
            max_score = max(max_score, 6)

    # Base score if keyword matched but no signals detected
    if not signals_found:
        max_score = 2

    post.moment_signals = sorted(signals_found, key=lambda x: x["score"], reverse=True)
    post.intent_score = max_score

    # Derive the pitch-services list ONLY from services whose keywords
    # genuinely fired (word-boundary match), preserving a stable priority order.
    # The filter layer's classify_intent may OVERRIDE this with a more accurate
    # LLM-derived service later; this is the regex fallback.
    service_priority = ["SEO", "SEM", "SMO", "PR", "Brand", "Creative", "Media", "Film"]
    post.pitch_services = [s for s in service_priority if s in matched_service_tags]

    return post
