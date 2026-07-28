"""Regression test: positive/negative triage filters.

Relevant-marked leads must power the positive filter (future posts from the
same author/company bypass the gates with a ⭐ boost) and negative-marked
posts must stay suppressed.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import triage
from agent.parser import LinkedInPost
from agent.filter import apply_smart_filter

# Redirect triage persistence into a throwaway dir so the test never touches
# the team's real data/.
_tmp = tempfile.mkdtemp(prefix="triage_test_")
triage.DATA_DIR = _tmp
triage.SALES_PROSPECTS_PATH = os.path.join(_tmp, "sales_prospects.json")
triage.NEGATIVE_LIST_PATH = os.path.join(_tmp, "negative_list.json")


def mk(content, author="Some Brand", etype="brand", headline="", company="",
       author_url="", url="https://www.linkedin.com/posts/x_activity-1"):
    return LinkedInPost(
        url=url, title=f"{author} on LinkedIn", snippet=content,
        author_name=author, entity_type=etype, company_hint=company,
        timestamp_raw="1 hour ago", estimated_posted_at=None,
        author_headline=headline, author_url=author_url,
    )


fails = 0


def check(ok, label):
    global fails
    if ok:
        print(f"✓ {label}")
    else:
        fails += 1
        print(f"✗ {label}")


# ── 1. Marking relevant feeds the positive signals ────────────────────────────
triage.add_sales_prospect({
    "url": "https://www.linkedin.com/posts/gulf_activity-1",
    "author": "Gulf Retail Ventures",
    "author_url": "https://www.linkedin.com/company/gulf-retail-ventures/",
    "company": "Gulf Retail Ventures",
    "snippet": "Looking for a development partner",
})
triage.add_sales_prospect({
    "url": "https://www.linkedin.com/posts/ritu_activity-2",
    "author": "Ritu Sharma",          # no author_url → name becomes the signal
    "author_url": "",
    "company": "",
    "snippet": "Looking for a PR agency",
})

signals = triage.load_positive_signals()
check("https://www.linkedin.com/company/gulf-retail-ventures" in signals["author_urls"],
      "author_url captured (normalized, no trailing slash)")
check("ritu sharma" in signals["authors"], "author name captured when no author_url")
check("gulf retail ventures" in signals["companies"], "company captured")

# ── 2. is_positive matching ────────────────────────────────────────────────────
by_url = mk("New post", author="GRV Official",
            author_url="https://www.linkedin.com/company/Gulf-Retail-Ventures")
check(triage.is_positive(by_url, signals), "match by author_url (case/slash-insensitive)")

by_name = mk("Another post", author="Ritu Sharma", etype="person")
check(triage.is_positive(by_name, signals), "match by author name fallback")

by_company = mk("Post", author="Someone Else", company="Gulf Retail Ventures")
check(triage.is_positive(by_company, signals), "match by company")

stranger = mk("Post", author="Random Person", etype="person")
check(not triage.is_positive(stranger, signals), "unknown author does not match")

# ── 3. Positive filter in apply_smart_filter ──────────────────────────────────
# A no-intent post from a known-relevant author would normally be dropped at
# the no-intent gate; the positive filter must rescue it at a floor of 6.
no_intent = mk("Excited about our new store opening in Dubai next month!",
               author="Gulf Retail Ventures",
               author_url="https://www.linkedin.com/company/gulf-retail-ventures/")
passed, stats = apply_smart_filter([no_intent], positive=signals)
check(len(passed) == 1 and stats["positive_included"] == 1,
      "no-intent post from relevant author is included")
check(passed and passed[0].intent_score == 6, "no-intent positive post floors at 6")
check(passed and passed[0].moment_signals[0]["id"] == "known_relevant_lead",
      "⭐ Previously Marked Relevant signal attached")
check(passed and getattr(passed[0], "positive_match", False), "positive_match flag set")

# Fresh seeking intent from a known author gets the intent score +1.
with_intent = mk("We are looking for an experienced SEO agency for our marketplace. DM me.",
                 author="Gulf Retail Ventures",
                 author_url="https://www.linkedin.com/company/gulf-retail-ventures/")
passed, _ = apply_smart_filter([with_intent], positive=signals)
check(passed and passed[0].intent_score == 10,
      f"intent post from relevant author boosted (+1) → {passed[0].intent_score if passed else '-'}/10")

# Without positive signals the same no-intent post must still be dropped.
no_intent2 = mk("Excited about our new store opening in Dubai next month!",
                author="Gulf Retail Ventures")
passed, stats = apply_smart_filter([no_intent2])
check(len(passed) == 0, "same post without positive signals is still filtered")

# ── 4. Content benchmark: relevant posts' text drives future inclusion ────────
from agent.benchmark import build_benchmark, similarity

triage.add_sales_prospect({
    "url": "https://www.linkedin.com/posts/marketplace_activity-3",
    "author": "Gulf Retail Ventures",
    "author_url": "https://www.linkedin.com/company/gulf-retail-ventures/",
    "company": "Gulf Retail Ventures",
    "snippet": """Looking for a Development Partner – Multi-Vendor Marketplace.
We are planning to develop a multi-vendor marketplace platform, starting with Dubai,
with future expansion across the UAE and GCC. We are looking for experienced
development companies / agencies / solution providers who can deliver a scalable
marketplace solution. Scope: customer website, vendor panel, admin dashboard,
payment and delivery integrations. Please share your company profile and proposal via DM.""",
})

signals = triage.load_positive_signals()
check(signals["benchmark"] is not None and signals["benchmark"]["doc_count"] >= 1,
      "content benchmark built from relevant-marked snippets")

# A paraphrased repeat from an UNKNOWN author, with no explicit seek verbs
# (classify_intent drops it) — must be rescued on content resemblance alone.
paraphrase = mk("""Multi-Vendor Marketplace Platform — Development Partner Wanted.
We are planning to develop a multi-vendor marketplace platform, starting with Dubai,
with expansion across the UAE and GCC. Scope includes customer website, vendor
seller panel, admin dashboard, payment and delivery integrations, scalable
architecture. Companies with marketplace development experience should share
your company profile and relevant work via DM.""",
                author="Emirates Commerce Group")
passed, stats = apply_smart_filter([paraphrase], positive=signals)
check(len(passed) == 1 and stats["benchmark_rescued"] == 1,
      "benchmark rescues aligned post from unknown author")
check(passed and passed[0].intent_score == 6 and
      passed[0].moment_signals[0]["id"] == "benchmark_match",
      "rescued post floors at 6 with 📈 benchmark signal")

# Unrelated content from an unknown author must NOT be rescued.
unrelated = mk("Proud to announce our Q2 results: revenue grew 40% year over year "
               "thanks to our amazing retail teams across the region.",
               author="Some Retailer")
passed, stats = apply_smart_filter([unrelated], positive=signals)
check(len(passed) == 0 and stats["benchmark_rescued"] == 0,
      "unrelated post is not rescued by benchmark")

# An intent-qualified post resembling the benchmark gets the 📈 boost on top.
similar_intent = mk("We are looking for an experienced development agency to build "
                    "our multi-vendor marketplace platform in Dubai. Scope: customer "
                    "website, vendor panel, admin dashboard, payment integrations. "
                    "Share your company profile via DM.",
                    author="Doha Commerce Hub")
passed, stats = apply_smart_filter([similar_intent], positive=signals)
check(passed and stats["benchmark_boosted"] == 1 and passed[0].intent_score == 10,
      "intent post resembling benchmark gets +1 boost")


# ── 5. Negative filter still suppresses marked posts ──────────────────────────
triage.add_negative({
    "url": "https://www.linkedin.com/posts/spam_activity-9",
    "author": "Spam Poster",
    "snippet": "We are looking for an SEO agency (fake bait post)",
})
negative = triage.load_negative_list()
spam = mk("We are looking for an SEO agency (fake bait post)",
          url="https://www.linkedin.com/posts/spam_activity-9")
survivors, dropped = triage.apply_negative_filter([spam], negative)
check(dropped == 1 and not survivors, "negative-marked URL dropped on next run")

# Same text under a different URL → caught by content hash.
cross = mk("We are looking for an SEO agency (fake bait post)",
           url="https://www.linkedin.com/posts/other_activity-77")
survivors, dropped = triage.apply_negative_filter([cross], negative)
check(dropped == 1 and not survivors, "cross-posted duplicate caught by content hash")

print(f"\n{'ALL TESTS PASSED' if fails == 0 else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
