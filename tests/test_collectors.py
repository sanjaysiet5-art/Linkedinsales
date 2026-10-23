"""Regression test: multi-source collectors (agent/collectors/).

Fixtures in tests/fixtures/collector_samples.json are trimmed REAL outputs of
each Apify actor (captured 2026-09-25), so the normalizers are tested against
the shapes the actors actually return. No network, no Apify spend.

Covers:
  1. Each normalizer turns raw items into scored, source-tagged leads.
  2. Source-specific qualification (agency industries, tiny budgets, app-install
     ads, roundup articles, stale tweets) drops what it should.
  3. Cross-source account merge folds one company's signals into one lead.
  4. The verifier judges signal leads with the SIGNAL rubric, in separate batches.
  5. run_pipeline end-to-end with fake collectors: signal leads skip the
     LinkedIn seeking-gate, explicit asks still go through it, agencies drop.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.collectors import (
    linkedin_jobs, meta_ads, upwork, freelancer, x_posts, launches,
    merge_accounts, make_post, CollectorResult,
)

FIX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "collector_samples.json")))
fails = 0


def check(ok, label):
    global fails
    print(f"{'✓' if ok else '✗'} {label}")
    if not ok:
        fails += 1


# ─── 1. LinkedIn Jobs ─────────────────────────────────────────────────────────
jobs = linkedin_jobs.normalize(FIX["linkedin_jobs"])
check(len(jobs) >= 5, f"jobs: real sample → {len(jobs)} company leads")
check(all(p.source == "linkedin_job" and p.intent_mode == "signal" for p in jobs), "jobs tagged source/intent_mode")
splash = next((p for p in jobs if p.author_name == "Splashjet Ink"), None)
check(splash is not None and splash.intent_score == 7 and splash.company_domain == "splashjet-ink.com"
      and splash.company_size == "135" and splash.region == "india",
      "jobs: 135-employee company → score 7, domain/size/region filled from the job")
acc = next((p for p in jobs if p.author_name.startswith("Accenture")), None)
check(acc is not None and acc.intent_score <= 6, "jobs: 80k-employee enterprise scores lower")
agency_job = dict(FIX["linkedin_jobs"][0], companyName="Brandwagon Media", industries="Advertising Services")
check(linkedin_jobs.normalize([agency_job]) == [], "jobs: advertising-services company rejected")
two_roles = [dict(FIX["linkedin_jobs"][0], title="SEO Executive"), FIX["linkedin_jobs"][0]]
g = linkedin_jobs.normalize(two_roles)
check(len(g) == 1 and "2 marketing roles" in g[0].snippet, "jobs: two roles at one company → one lead")

# ─── 2. Meta Ads ──────────────────────────────────────────────────────────────
ads = meta_ads.normalize(FIX["meta_ads"])
names = {p.author_name for p in ads}
check("TikTok - US" not in names, "ads: app-install ad (no brand site) dropped")
derma = next((p for p in ads if p.company_domain == "dermatouch.com"), None)
check(derma is not None and "Running 4" in derma.hooks[0], "ads: 3 Dermatouch pages grouped by domain into one lead")
check(all(p.region == "india" for p in ads), "ads: region from Ad Library country")

# ─── 3. Upwork ────────────────────────────────────────────────────────────────
up = upwork.normalize(FIX["upwork"])
titles = " ".join(p.snippet for p in up)
check("research task" not in titles, "upwork: $30 fixed / unverified micro-task dropped")
check(any(p.intent_score >= 7 for p in up), "upwork: client with $5k+ spend scores higher")
check(all(p.company_hint == "" for p in up), "upwork: client first name is not used as a company")

# ─── 4. Freelancer.com (synthetic — live API has no fixture) ─────────────────
fl = freelancer.normalize([
    {"id": 1, "title": "Brand identity for D2C tea brand", "description": "Need logo + packaging",
     "budget": {"minimum": 30000, "maximum": 60000}, "currency": {"code": "INR", "sign": "₹", "exchange_rate": 0.0104},
     "bid_stats": {"bid_count": 4}, "jobs": [{"name": "Branding"}], "time_submitted": 1790342568, "seo_url": "x/1"},
    {"id": 2, "title": "Logo", "budget": {"minimum": 10, "maximum": 30}, "currency": {"code": "USD", "exchange_rate": 1}},
    {"id": 3, "title": "Commission-Based Client Acquisition Partner", "budget": {"minimum": 600, "maximum": 1500},
     "currency": {"code": "USD", "exchange_rate": 1}},
])
check(len(fl) == 1 and fl[0].region == "india", "freelancer: ₹60k project kept (region from INR); $30 + commission-only dropped")

# ─── 5. X ─────────────────────────────────────────────────────────────────────
check(x_posts.normalize(FIX["x_posts"], hours=24) == [], "x: 2025 tweet dropped from a 24h scan")
xs = x_posts.normalize(FIX["x_posts"], hours=24 * 900)
check(len(xs) >= 1 and xs[0].intent_mode == "explicit", "x: in-window tweet kept as an explicit ask")

# ─── 6. Launches / funding ────────────────────────────────────────────────────
ph = launches.normalize_product_hunt(FIX["product_hunt"])
check(len(ph) == 5 and ph[0].company_domain, "product hunt: 5 launches with website domains")
fund = launches.normalize_funding(FIX["funding_news"])
check([p.author_name for p in fund] == ["Protein Pantry"], "funding: company extracted, roundups/guides dropped")
check(launches.guess_company("Mumbai-based Snitch raises $40 Mn in Series B") == "Snitch", "funding: 'X-based Co raises' parsed")

# ─── 7. Cross-source merge ────────────────────────────────────────────────────
a = make_post(source="linkedin_job", intent_mode="signal", url="u1", author_name="Acme Foods Pvt Ltd",
              company="Acme Foods Pvt Ltd", snippet="hiring", score=7, signal_label="Hiring", domain="acme.com",
              hooks=["Hiring SEO Executive"])
b = make_post(source="meta_ads", intent_mode="signal", url="u2", author_name="Acme Foods", company="Acme Foods",
              snippet="ads", score=6, signal_label="Running 5 ads", domain="acme.com", hooks=["Running 5 ads"])
c = make_post(source="x_post", intent_mode="explicit", url="u3", author_name="Acme Foods", snippet="?", score=9,
              signal_label="x")
merged, n = merge_accounts([a, b, c])
check(n == 1 and len(merged) == 2, "merge: job + ads for same domain → one lead; explicit ask untouched")
lead = next(p for p in merged if p.source == "linkedin_job")
check(lead.intent_score == 8 and "Running 5 ads" in lead.hooks and len(lead.moment_signals) == 2,
      "merge: +1 score, hooks and signals folded in")

# ─── 8. Verifier uses the signal rubric for signal leads ─────────────────────
from agent import verifier
verifier.CACHE_PATH = os.path.join(tempfile.mkdtemp(), "cache.jsonl")
prompts_seen = []


class _Models:
    def generate_content(self, *, model, contents, config):
        prompts_seen.append(config["system_instruction"])
        n = contents.count("--- POST ")
        signal = config["system_instruction"] is verifier.SIGNAL_SYSTEM_PROMPT
        out = [{"index": i, "is_relevant": True, "service": "SEO", "confidence": 90,
                "intent_type": "signal" if signal else "seeking", "reason": "ok",
                "company": "Protein Pantry Foods" if signal else ""} for i in range(n)]

        class R:
            text = json.dumps({"verdicts": out})
        return R()


class _Client:
    models = _Models()


verifier._get_client = lambda key: _Client()
sig = launches.normalize_funding(FIX["funding_news"])[0]
sig.company_hint = ""
exp = xs[0]
kept, st = verifier.verify_posts([exp, sig], api_key="fake")
check(len(prompts_seen) == 2 and verifier.SIGNAL_SYSTEM_PROMPT in prompts_seen and verifier.SYSTEM_PROMPT in prompts_seen,
      "verifier: explicit and signal leads judged in separate batches with their own rubric")
check(sig.company_hint == "Protein Pantry Foods", "verifier: signal verdict fills the company name")

# ─── 8b. Daily-quota exhaustion: stop calling Gemini, pass the rest through ──
calls = {"n": 0}


class _QuotaModels:
    def generate_content(self, *, model, contents, config):
        calls["n"] += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier")


class _QuotaClient:
    models = _QuotaModels()


verifier._get_client = lambda key: _QuotaClient()
many = [make_post(source="meta_ads", intent_mode="signal", url=f"q{i}", author_name=f"Brand {i}",
                  snippet=f"Brand {i} runs ads {i}", score=6, signal_label="ads") for i in range(45)]
kept_q, st_q = verifier.verify_posts(many, api_key="fake", batch_size=20)
check(calls["n"] == 1 and len(kept_q) == 45 and st_q.get("quota_exhausted"),
      "verifier: daily quota hit once → no more calls, all 45 leads passed through")

# ─── 9. run_pipeline end-to-end with fake collectors ─────────────────────────
import main
import agent.collectors as C

agency_ads = make_post(source="meta_ads", intent_mode="signal", url="https://ads/1", author_name="Pixel Digital Marketing Agency",
                       company="Pixel Digital Marketing Agency", snippet="Running 3 Meta ads", score=7,
                       signal_label="Running 3 ads", domain="pixeldigital.in")
brand_ads = make_post(source="meta_ads", intent_mode="signal", url="https://ads/2", author_name="Chai Point",
                      company="Chai Point", snippet="Chai Point is running 6 active Meta ads in IN", score=7,
                      signal_label="Running 6 ads", domain="chaipoint.com", region="india")
x_ask = make_post(source="x_post", intent_mode="explicit", url="https://x.com/1", author_name="Priya",
                  entity_type="person", snippet="Can anyone recommend a good SEO agency in Mumbai for our D2C brand? DM me.",
                  score=0, signal_label="Asked on X")
x_noise = make_post(source="x_post", intent_mode="explicit", url="https://x.com/2", author_name="Ravi",
                    entity_type="person", snippet="5 lessons I learned about SEO this year.", score=0, signal_label="x")
for p in (x_ask, x_noise):
    p.estimated_posted_at = None

C.run_collectors = lambda sources, ctx, log=print: [
    CollectorResult(source="meta_ads", posts=[agency_ads, brand_ads], raw_count=40, cost_usd=0.23),
    CollectorResult(source="x_post", posts=[x_ask, x_noise], raw_count=12, cost_usd=0.01),
]
os.environ.pop("APOLLO_API_KEY", None)
out_dir = tempfile.mkdtemp()
result = main.run_pipeline(keywords=["seo agency"], timeline="1day", api_key="fake", output_dir=out_dir,
                           export_formats=["json"], verify=False, sources=["meta_ads", "x_post"])
urls = {p.url for p in result}
check("https://ads/2" in urls, "pipeline: brand running ads kept (signal skips the seeking-gate)")
check("https://ads/1" not in urls, "pipeline: agency running ads removed by agency-author gate")
check("https://x.com/1" in urls and "https://x.com/2" not in urls,
      "pipeline: explicit X ask kept, X thought-leadership dropped by the regex gates")
data = json.load(open(next(os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".json"))))
check(data["metadata"]["sources"]["meta_ads"]["qualified"] == 1 and
      {p["source"] for p in data["posts"]} == {"meta_ads", "x_post"},
      "pipeline: JSON export carries per-source stats and source tags")

print(f"\n{'ALL TESTS PASSED' if fails == 0 else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
