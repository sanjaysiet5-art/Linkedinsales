"""Regression test: the AI verifier (agent/verifier.py).

Covers the three properties that matter:
  1. A `relevant` verdict KEEPS the post and attaches the 🛡️ signal + service.
  2. An `irrelevant` verdict DROPS the post.
  3. No API key / API error → graceful pass-through (dashboard never goes empty).
  4. Cache hit → same verdict reused, no second API call.

Uses a FAKE Gemini client (monkeypatched in) so the test runs with no API key
and no network. The fake returns canned verdicts so we assert on the wiring,
not on what Gemini happens to say today.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import verifier
from agent.parser import LinkedInPost


# Redirect the verifier cache into a throwaway file so the test never pollutes
# the team's real data/verifier_cache.jsonl.
_tmp = tempfile.mkdtemp(prefix="verifier_test_")
verifier.CACHE_PATH = os.path.join(_tmp, "verifier_cache.jsonl")
verifier._client = None  # reset any cached client between sub-tests


fails = 0


def check(ok, label):
    global fails
    if ok:
        print(f"✓ {label}")
    else:
        fails += 1
        print(f"✗ {label}")


def mk(content, author="Test", etype="brand", url="https://www.linkedin.com/posts/x_a"):
    return LinkedInPost(
        url=url, title=f"{author} on LinkedIn", snippet=content,
        author_name=author, entity_type=etype, company_hint="",
        timestamp_raw="1 hour ago", estimated_posted_at=None,
        author_headline="Marketing Director",
    )


# ─── Fake Gemini client ───────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, payload_obj):
        self.text = json.dumps(payload_obj)


class _FakeModels:
    """Returns a verdict array matching the batch order passed in."""
    def __init__(self, verdicts_by_snippet):
        # verdicts_by_snippet: {snippet_substring: verdict_dict}
        self._map = verdicts_by_snippet
        self.call_count = 0

    def generate_content(self, *, model, contents, config):
        self.call_count += 1
        # Recover the posts from the prompt by counting "--- POST N ---" markers.
        out = []
        # Walk the verdict map in input order by scanning the prompt for each
        # snippet key. We rely on the prompt containing the snippet text.
        for key, verdict in self._map.items():
            entry = {"index": len(out), **verdict}
            out.append(entry)
        return _FakeResp({"verdicts": out})


class _FakeClient:
    def __init__(self, models):
        self.models = models


def _patch_client(verdicts_by_snippet):
    """Install a fake client whose generate_content returns the given verdicts."""
    verifier._client = None  # force re-creation
    fake_models = _FakeModels(verdicts_by_snippet)
    fake_client = _FakeClient(fake_models)

    def _get_client(api_key):
        return fake_client

    verifier._get_client = _get_client
    return fake_models


# ─── Test 1: relevant verdict keeps the post + attaches signal ────────────────
post_relevant = mk("We are looking for a PR agency for our education brand. DM me your portfolio.")
post_irrelevant = mk("Most people miss this about branding. Here are 5 things every brand should know.")

fake = _patch_client({
    "PR agency": {
        "is_relevant": True, "service": "PR & Influencer Marketing",
        "confidence": 92, "intent_type": "seeking",
        "reason": "Brand actively seeking a PR agency.", "budget_mentioned": False,
    },
    "Most people miss": {
        "is_relevant": False, "service": "",
        "confidence": 88, "intent_type": "none",
        "reason": "Thought leadership, not a lead.", "budget_mentioned": False,
    },
})

kept, stats = verifier.verify_posts([post_relevant, post_irrelevant], api_key="fake-key")
check(len(kept) == 1, "only the relevant post is kept")
check(stats["relevant"] == 1 and stats["rejected"] == 1, "stats show 1 relevant · 1 rejected")
check(fake.call_count == 1, "one batched API call for both posts")
if kept:
    p = kept[0]
    sig = p.moment_signals[0]
    check(sig["id"] == "ai_verified" and "PR & Influencer Marketing" in sig["label"],
          f"🛡️ AI-Verified signal attached (got: {sig['label']})")
    check(p.pitch_services == ["PR & Influencer Marketing"],
          f"pitch_services overridden to LLM service (got: {p.pitch_services})")
    check(getattr(p, "ai_verdict", {}).get("confidence") == 92, "confidence stored on ai_verdict")


# ─── Test 2: cache hit → no second API call ───────────────────────────────────
# verifier.verify_posts already wrote both verdicts to the temp cache file in
# test 1. Re-running must reuse them and NOT call the API again.
fake.call_count = 0
post_relevant2 = mk("We are looking for a PR agency for our education brand. DM me your portfolio.",
                    url="https://www.linkedin.com/posts/x_different_url")  # same text, new URL
kept2, stats2 = verifier.verify_posts([post_relevant2], api_key="fake-key")
check(fake.call_count == 0, "cached post is not re-judged (no API call)")
check(stats2["cached"] == 1, "stats report a cache hit")
check(len(kept2) == 1, "cached relevant post is kept")


# ─── Test 3: no API key → graceful pass-through ───────────────────────────────
verifier._client = None
import types as _types
# Restore the real _get_client (which returns None for empty key)
import importlib
real_module = importlib.reload(importlib.import_module("agent.verifier"))
real_module.CACHE_PATH = verifier.CACHE_PATH  # keep temp cache

post = mk("Looking for an SEO agency.")
kept3, stats3 = real_module.verify_posts([post], api_key="")
check(len(kept3) == 1, "no API key → post passes through (not dropped)")
check(stats3["skipped"] == 1 and stats3["errors"] == 0,
      f"no-key skip recorded cleanly (got skipped={stats3['skipped']}, errors={stats3['errors']})")
check(getattr(kept3[0], "ai_verdict", {}).get("skipped") is True,
      "skipped post tagged with skipped=True verdict")


# ─── Test 4: disabled flag → everything passes through ───────────────────────
kept4, stats4 = real_module.verify_posts([post], api_key="fake", enabled=False)
check(len(kept4) == 1, "disabled verifier passes posts through")
check(stats4["skipped"] == 1, "disabled verifier records a skip")


# ─── Test 5: low-confidence relevant verdict → dropped as borderline ─────────
fake2 = _patch_client({
    "SEO agency": {
        "is_relevant": True, "service": "SEO",
        "confidence": 40,  # below default MIN_CONFIDENCE=60
        "intent_type": "seeking", "reason": "Uncertain.", "budget_mentioned": False,
    },
})
post_low = mk("Looking for an SEO agency.", url="https://www.linkedin.com/posts/x_lowconf")
kept5, stats5 = verifier.verify_posts([post_low], api_key="fake-key", min_confidence=60)
check(len(kept5) == 0, "low-confidence relevant verdict is dropped (borderline)")
check(stats5["rejected"] == 1, "low-confidence counted as rejected")


print(f"\n{'ALL TESTS PASSED' if fails == 0 else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
