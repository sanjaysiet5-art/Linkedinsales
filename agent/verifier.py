"""
Semantic lead-verification pass powered by Google Gemini Flash.

Runs AFTER the regex precision gates (agent/filter.py) and BEFORE the dashboard.
Each post that survived the regex gates is judged by an LLM against the 9
services Grapesworldwide actually sells. The LLM is a precision backstop:
the regex gates catch the *shapes* of false positives we already know about,
the verifier catches the ones we haven't seen yet.

Design choices
  • Cheap model (gemini-flash-latest) — this is a short-text classification task.
    We use the "-latest" alias rather than a pinned version (gemini-2.0-flash)
    because per-model-id free-tier quotas can exhaust; the alias always routes
    to an available Flash model.
  • Batched calls (BATCH_SIZE posts per request) to cut latency and cost.
  • On-disk JSONL cache (data/verifier_cache.jsonl) keyed by content hash — a
    post judged once is never re-judged, so re-running the pipeline over a
    rolling week window costs almost nothing after the first run.
  • Graceful fallback: if Gemini is unavailable (no API key, network error,
    quota), the verifier PASSES every post through with a "skipped" signal.
    A verifier outage never blanks the dashboard — the regex gates still stand.
  • Verdict-driven service override: the LLM's `service` field replaces the
    regex-derived pitch_services, because the LLM reads the full post context
    (the regex path can only match keywords).
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime
from typing import Iterable

from pydantic import BaseModel, Field

from agent.parser import LinkedInPost


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CACHE_PATH = os.path.join(DATA_DIR, "verifier_cache.jsonl")

# The 9 services Grapesworldwide offers — pinned into the rubric so the model's
# service output is always one of these exact labels (or "" for non-relevant).
SERVICES = [
    "Branding & Designing",
    "AI/3D/CGI",
    "Films & Campaigns",
    "Social Media & Content Strategy",
    "Website Design & Development",
    "SEO",
    "Media Planning & Buying",
    "PR & Influencer Marketing",
    "Events & Activations",
]


class VerifierVerdict(BaseModel):
    """Strict JSON schema enforced via response_schema on the Gemini call."""
    is_relevant: bool = Field(description="True if the author is ACTIVELY SEEKING TO HIRE an external agency for one of the 9 services. False for anything else.")
    service: str = Field(description="The single best-matching service name from the list, or empty string if is_relevant is false.")
    confidence: int = Field(description="0-100 confidence in the verdict.")
    intent_type: str = Field(description="One of: 'rfp', 'seeking', 'recommendation', 'none'.")
    reason: str = Field(description="One short sentence explaining the verdict (shown on the dashboard card).")
    budget_mentioned: bool = Field(description="True if the post mentions a budget, project value, or compensation amount.")


SYSTEM_PROMPT = f"""You are a precision B2B lead-classification engine for a digital agency called Grapesworldwide.

Your job: decide whether the AUTHOR of a LinkedIn post is ACTIVELY SEEKING TO HIRE an EXTERNAL marketing / creative / digital agency for ONE of these 9 services (and only these):

1. Branding & Designing
2. AI/3D/CGI
3. Films & Campaigns
4. Social Media & Content Strategy
5. Website Design & Development
6. SEO
7. Media Planning & Buying
8. PR & Influencer Marketing
9. Events & Activations

Return is_relevant=true ONLY when ALL of these are true:
  • The author represents a BRAND or COMPANY that would BUY the service (not sell it).
  • The post expresses intent to HIRE / ENGAGE / SOLICIT PROPOSALS from an external agency, freelancer, or specialist for one of the 9 services.
  • Acceptable intent shapes: RFP / "looking for an agency" / "recommend an agency" / "share your credentials" / "DM me your company profile".

GOLDEN EXAMPLES OF RELEVANT LEADS (These should always return is_relevant=true):
  - "I am looking at speaking with some software/website development companies locally to discuss a potential project..." (Service: Website Design & Development)
  - "DramaBox New York Studio is currently looking to collaborate with AI video generation studios and companies..." (Service: AI/3D/CGI or Films & Campaigns)
  - "Looking for recommendations for a Mumbai-based PR agency to handle wealth conversations and earned media..." (Service: PR & Influencer Marketing)
  - "We are looking for a Delhi NCR-based social media agency for managing Haldiram's QSR social media portfolio..." (Service: Social Media & Content Strategy)
  - "Looking for a Media Agency Partner to handle end-to-end marketing - content creation, video production, social media..." (Service: Media Planning & Buying or Social Media & Content Strategy)
  - "Looking for web developer for a project in my team..." (Service: Website Design & Development)

Return is_relevant=false for EVERYTHING ELSE, including:
  • Thought leadership, opinion pieces, educational "here's how…" content, listicles, myths/lessons.
  • Agencies/freelancers/consultants PROMOTING their OWN services ("we help brands…", "I offer…", "our agency").
  • Recruitment / staffing / workforce firms pitching their talent services.
  • NGO / fundraising / grant content (even if it says "funding agencies").
  • Co-founder / tech talent hunts ("looking to connect with developers / engineers / researchers").
  • Software / IT / app development searches that are NOT about marketing/creative/web-design services.
  • Job postings hiring an in-house employee (not an agency).
  • Channel-partner / reseller / affiliate recruitment.
  • War stories / anecdotes about SOMEONE ELSE seeking an agency.
  • Generic "partner with us" / "let's collaborate" with no specific marketing service requested.

If is_relevant is true, set `service` to the single best-matching service name from the 9 above (copy it exactly). Set `intent_type` to 'rfp', 'seeking', or 'recommendation' based on the strongest intent language present. Set `budget_mentioned` true only if a concrete number/value/budget appears.

Be strict. When in doubt, return is_relevant=false — false negatives are recoverable (the team can still see borderline posts), but false positives erode trust in the tool."""


# ─── Content hashing (shares the normalization contract with triage.py) ───────
def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()[:400]


def _hash(text: str) -> str:
    n = _normalize(text)
    return hashlib.sha1(n.encode("utf-8")).hexdigest() if n else ""


# ─── On-disk JSONL cache (append-only; one line per verdict) ──────────────────
def _load_cache() -> dict[str, dict]:
    """Return {content_hash: verdict_dict} from the cache file."""
    cache: dict[str, dict] = {}
    if not os.path.exists(CACHE_PATH):
        return cache
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                h = rec.get("hash")
                if h and rec.get("verdict"):
                    cache[h] = rec["verdict"]
    except OSError:
        pass
    return cache


def _append_cache(records: list[dict]) -> None:
    if not records:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CACHE_PATH, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ─── Gemini client (lazy; created once per pipeline run) ──────────────────────
_client = None


def _get_client(api_key: str | None):
    """Build a genai.Client, or return None if no key / SDK unavailable."""
    global _client
    if _client is not None:
        return _client
    if not api_key:
        return None
    try:
        from google import genai
    except ImportError:
        return None
    _client = genai.Client(api_key=api_key)
    return _client


# ─── Prompt building ──────────────────────────────────────────────────────────
def _post_payload(p: LinkedInPost) -> str:
    """Compact text representation of a post for the model."""
    snippet = (p.snippet or "").strip()
    # Strip the LinkedIn unicode bold hack (𝗦𝗧𝗢𝗣 etc.) — it inflates tokens
    # and the model reads it fine without.
    snippet = re.sub(r"[^\x00-\x7F]+", " ", snippet)
    snippet = re.sub(r"\s+", " ", snippet)[:1500]
    author = (p.author_name or "Unknown").strip()
    headline = (p.author_headline or "").strip()[:160]
    etype = p.entity_type or "person"
    return f"AUTHOR: {author}\nHEADLINE: {headline}\nTYPE: {etype}\nPOST:\n{snippet}"


def _batch_prompt(posts: list[LinkedInPost]) -> str:
    """Build a single prompt that judges BATCH_SIZE posts at once."""
    parts = [
        "Judge each of the following LinkedIn posts independently. Return a JSON "
        "array with one verdict object per post, in the SAME ORDER as the inputs. "
        "Use the post's INDEX (0-based) in the `index` field.",
    ]
    for i, p in enumerate(posts):
        parts.append(f"\n--- POST {i} ---\n{_post_payload(p)}")
    parts.append(
        "\nReturn ONLY a JSON array like: "
        '[{"index":0,"is_relevant":true,"service":"SEO","confidence":92,'
        '"intent_type":"seeking","reason":"Brand seeking an SEO agency.","budget_mentioned":false}]'
    )
    return "\n".join(parts)


class _Indexed(BaseModel):
    """Schema for a single batched verdict (adds the index field)."""
    index: int
    is_relevant: bool
    service: str = ""
    confidence: int = 0
    intent_type: str = "none"
    reason: str = ""
    budget_mentioned: bool = False


# ─── Public API ───────────────────────────────────────────────────────────────
def verify_posts(
    posts: list[LinkedInPost],
    api_key: str | None = None,
    model: str = "gemini-flash-latest",
    batch_size: int = 10,
    min_confidence: int = 60,
    max_posts: int = 100,
    enabled: bool = True,
    progress_callback = None,
) -> tuple[list[LinkedInPost], dict]:
    """
    Verify each post against the 9-service rubric.

    Returns (kept_posts, stats). Posts with is_relevant=False (or confidence
    below min_confidence) are dropped. On any Gemini failure, ALL posts are
    kept with a "skipped" signal so the dashboard never goes empty — the
    regex gates still stand as the baseline.

    stats: {verified, relevant, rejected, skipped, cached, errors, ms_per_post, batches}
    """
    stats = {
        "verified": 0, "relevant": 0, "rejected": 0, "skipped": 0,
        "cached": 0, "errors": 0, "ms_per_post": 0.0, "batches": 0,
    }

    if not posts:
        return posts, stats

    # Feature disabled (config or --no-verify flag) → pass through.
    if not enabled:
        for p in posts:
            _attach_skipped(p, "verifier disabled")
        stats["skipped"] = len(posts)
        return posts, stats

    # Cap the number of posts judged per run (cost ceiling).
    to_verify = posts[:max_posts]
    overflow = posts[max_posts:]
    for p in overflow:
        _attach_skipped(p, "over daily cap — passed through")
        stats["skipped"] += 1

    # Load cache, split into cache-hits vs needs-judging.
    cache = _load_cache()
    verdicts: dict[int, dict] = {}  # original index → verdict
    needs_judging: list[tuple[int, LinkedInPost]] = []

    for idx, p in enumerate(to_verify):
        h = _hash(p.snippet)
        if h and h in cache:
            verdicts[idx] = cache[h]
            stats["cached"] += 1
        else:
            needs_judging.append((idx, p))

    # Judge the uncached posts in batches.
    new_cache_records: list[dict] = []
    client = _get_client(api_key)
    if needs_judging and client is None:
        # No API key / SDK — gracefully pass everything through.
        for idx, p in needs_judging:
            _attach_skipped(p, "no API key — verifier skipped")
            verdicts[idx] = None  # marker: no verdict, keep
            stats["skipped"] += 1
        return _finalize(to_verify, verdicts, overflow, min_confidence, stats)

    start = time.monotonic()
    total_batches = (len(needs_judging) + batch_size - 1) // batch_size
    for i in range(0, len(needs_judging), batch_size):
        batch_i = (i // batch_size) + 1
        if progress_callback:
            try:
                progress_callback(batch_i, total_batches, 0, "verifying")
            except Exception:
                pass
        batch = needs_judging[i:i + batch_size]
        batch_posts = [p for _, p in batch]
        try:
            batch_verdicts = _call_gemini(client, model, batch_posts)
            stats["batches"] += 1
        except Exception as e:  # noqa: BLE001 — any failure must fall back gracefully
            stats["errors"] += 1
            # Mark this whole batch as skipped so the dashboard still shows them.
            batch_verdicts = [None] * len(batch_posts)
            print(f"  [verifier] batch error ({type(e).__name__}: {e}); passing batch through")
            for idx, p in batch:
                _attach_skipped(p, f"verifier error — passed through")
                verdicts[idx] = None

        for (idx, p), v in zip(batch, batch_verdicts):
            if v is None:
                verdicts[idx] = None
                stats["skipped"] += 1
                _attach_skipped(p, "verifier returned no verdict")
                continue
            verdicts[idx] = v
            stats["verified"] += 1
            h = _hash(p.snippet)
            if h:
                new_cache_records.append({
                    "hash": h, "verdict": v, "judged_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                })

    if new_cache_records:
        try:
            _append_cache(new_cache_records)
        except OSError as e:
            print(f"  [verifier] cache write failed: {e}")

    if stats["verified"] + stats["cached"] > 0:
        elapsed = time.monotonic() - start
        judged = stats["verified"]
        stats["ms_per_post"] = round(elapsed * 1000 / judged, 0) if judged else 0.0

    return _finalize(to_verify, verdicts, overflow, min_confidence, stats)


# ─── Internals ────────────────────────────────────────────────────────────────
def _call_gemini(client, model: str, posts: list[LinkedInPost]) -> list[dict | None]:
    """
    Call Gemini with a strict response_schema. Returns one verdict dict per
    post (None for any slot the model skipped). Raises on hard failure so the
    caller can fall back to pass-through.
    """
    from google import genai  # noqa: F401  (ensures import surface for types)
    from pydantic import BaseModel
    from typing import List

    class _BatchVerdicts(BaseModel):
        verdicts: List[_Indexed]

    prompt = _batch_prompt(posts)
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": _BatchVerdicts,
            "system_instruction": SYSTEM_PROMPT,
            "temperature": 0.0,
        },
    )
    raw = resp.text or ""
    try:
        parsed = _BatchVerdicts.model_validate_json(raw)
        by_index = {v.index: v.model_dump() for v in parsed.verdicts}
    except Exception:
        # Schema binding failed — try a lenient JSON parse as a last resort.
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                by_index = {int(v.get("index", i)): v for i, v in enumerate(arr)}
            else:
                by_index = {}
        except (json.JSONDecodeError, ValueError):
            return [None] * len(posts)

    # Order the results to match the input batch; missing index → None.
    out: list[dict | None] = []
    for i in range(len(posts)):
        out.append(by_index.get(i))
    return out


def _finalize(
    to_verify: list[LinkedInPost],
    verdicts: dict[int, dict | None],
    overflow: list[LinkedInPost],
    min_confidence: int,
    stats: dict,
) -> tuple[list[LinkedInPost], dict]:
    """Apply verdicts: drop rejects, attach signals to survivors."""
    kept: list[LinkedInPost] = []
    for idx, p in enumerate(to_verify):
        v = verdicts.get(idx)
        if v is None:
            # Skipped (disabled / no key / error) → keep, signal already attached.
            kept.append(p)
            continue
        if not v.get("is_relevant"):
            stats["rejected"] += 1
            continue
        if int(v.get("confidence", 0)) < min_confidence:
            # Low-confidence relevant → treat as a borderline reject.
            stats["rejected"] += 1
            continue
        stats["relevant"] += 1
        _attach_verified(p, v)
        kept.append(p)

    kept.extend(overflow)
    return kept, stats


def _attach_verified(p: LinkedInPost, verdict: dict) -> None:
    """Attach the 🛡️ AI-Verified signal and override pitch_services."""
    service = (verdict.get("service") or "").strip()
    confidence = int(verdict.get("confidence", 0))
    label = f"AI-Verified · {service} · {confidence}%" if service else f"AI-Verified · {confidence}%"
    signal = {
        "id": "ai_verified",
        "label": label,
        "icon": "🛡️",
        "score": 0,
        "matched_keywords": [],
        "service_tags": [service] if service else [],
    }
    # Put the AI verdict FIRST — it's the most trustworthy signal on the card.
    p.moment_signals = [signal] + [s for s in p.moment_signals if s.get("id") != "ai_verified"]
    if service:
        # The LLM's service is more accurate than the regex keyword match
        # (e.g. a web-dev post that regex tagged "SEO/SEM/SMO/Brand" becomes
        # cleanly "Website Design & Development").
        p.pitch_services = [service]
    p.ai_verdict = {
        "is_relevant": True,
        "service": service,
        "confidence": confidence,
        "intent_type": verdict.get("intent_type", ""),
        "reason": verdict.get("reason", ""),
        "budget_mentioned": bool(verdict.get("budget_mentioned", False)),
    }


def _attach_skipped(p: LinkedInPost, reason: str) -> None:
    p.ai_verdict = {"skipped": True, "reason": reason}
