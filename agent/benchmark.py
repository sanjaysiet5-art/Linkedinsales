"""
Content benchmark learned from relevant-marked leads.

Every post the NBD team marks ✅ Relevant contributes its text to a benchmark
profile (data/sales_prospects.json snippets). On subsequent runs, each new
post is scored 0..1 for similarity against that profile, and the filter
inclusion engine uses the score two ways (see agent/filter.py):

  • BOOST   — a post that already passed the intent gates and looks like the
              benchmark gets +1 intent score and a 📈 signal.
  • RESCUE  — a post that cleared every rejection gate but showed no explicit
              seeking intent is still included when it strongly resembles
              posts the team previously marked relevant.

Model: nearest-neighbor cosine similarity — the post's term-frequency vector
is compared against EACH relevant-marked post and the best match wins. A
centroid would dilute as the team marks diverse posts (a marketplace RFP
averaged with a PR ask matches neither); nearest-neighbor asks the right
question: "does this resemble ANY post the team marked relevant?" Terms are
stopword-filtered unigrams + bigrams, so phrases like "looking for",
"seo agency", "submit proposals" carry the weight they deserve.
Stdlib only — no external dependencies.
"""

import math
import re
from collections import Counter

# Minimal English stopword list — enough to stop function words from
# dominating short LinkedIn posts without eating domain terms.
_STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been
before being below between both but by can could did do does doing down
during each few for from further had has have having he her here hers him
his how i if in into is it its itself just me more most my myself no nor
not now of off on once only or other our ours out over own same she should
so some such than that the their theirs them then there these they this
those through to too under until up very was we were what when where which
while who whom why will with would you your yours
""".split())

_WORD_RE = re.compile(r"[a-z][a-z0-9'&-]*")


def _tokens(text: str) -> list[str]:
    """Stopword-filtered unigrams + adjacent bigrams of the lowercased text."""
    words = [w for w in _WORD_RE.findall((text or "").lower())
             if len(w) > 1 and w not in _STOPWORDS]
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]


def _vectorize(text: str) -> tuple[dict, float]:
    """Normalized TF vector + its L2 norm for one document."""
    tf = Counter(_tokens(text or ""))
    if not tf:
        return {}, 0.0
    total = sum(tf.values())
    vector = {term: count / total for term, count in tf.items()}
    norm = math.sqrt(sum(w * w for w in vector.values()))
    return vector, norm


# A benchmark doc must have this many content words: trivially short snippets
# ("Looking for a PR agency") anchor loose matches against everything and
# carry no real content expectation.
_MIN_DOC_WORDS = 12


def build_benchmark(snippets: list[str]) -> dict | None:
    """
    Build a benchmark profile from relevant-marked post texts.

    Returns {"docs": [(vector, norm), ...], "doc_count": int} — one TF vector
    per marked post, compared individually at scoring time (nearest-neighbor).
    None when there is nothing to learn from yet.
    """
    docs = []
    for s in snippets:
        words = [t for t in _tokens(s or "") if " " not in t]
        if len(words) < _MIN_DOC_WORDS:
            continue
        vector, norm = _vectorize(s)
        if norm:
            docs.append((vector, norm))
    if not docs:
        return None
    return {"docs": docs, "doc_count": len(docs)}


def similarity(text: str, benchmark: dict | None) -> float:
    """
    Best cosine similarity (0..1) between a post's text and any single
    relevant-marked post in the benchmark.
    """
    if not benchmark or not benchmark.get("docs"):
        return 0.0
    vector, norm = _vectorize(text)
    if not norm:
        return 0.0
    best = 0.0
    for bench_vec, bench_norm in benchmark["docs"]:
        dot = sum(w * bench_vec.get(term, 0.0) for term, w in vector.items())
        sim = dot / (norm * bench_norm)
        if sim > best:
            best = sim
    return best


def make_benchmark_signal(sim: float) -> dict:
    """Moment-signal dict shown on dashboard cards for benchmark matches."""
    return {
        "id": "benchmark_match",
        "label": f"Matches Relevant Benchmark ({round(sim * 100)}%)",
        "icon": "📈",
        "score": 0,
        "matched_keywords": [],
        "service_tags": [],
    }
