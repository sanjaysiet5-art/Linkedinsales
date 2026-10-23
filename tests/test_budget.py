"""Regression test: the per-scan Apify budget (config/sources.py SCAN_BUDGET_USD).

Worst case is priced, not sampled: every Apify run is intercepted, and we
assume it returns its FULL hard cap (maxItems) of billable items. That worst
case must stay ≤ the budget for the full 110-keyword all-sources scan.
No network, no Apify spend.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent.collectors as C
from agent.collectors import ScanContext
from agent.collectors import linkedin_jobs, meta_ads, upwork, x_posts, launches
from agent import searcher
from config import sources as S
from config.keywords import get_all_keywords
from config.settings import APIFY_POST_PRICE, QUERIES_PER_RUN

fails = 0


def check(ok, label):
    global fails
    print(f"{'✓' if ok else '✗'} {label}")
    if not ok:
        fails += 1


PRICE = {
    S.LINKEDIN_JOBS["actor"]: S.LINKEDIN_JOBS["cost_per_item"],
    S.META_ADS["actor"]: S.META_ADS["cost_per_item"],
    S.UPWORK["actor"]: S.UPWORK["cost_per_item"],
    S.X_POSTS["actor"]: S.X_POSTS["cost_per_item"],
    S.PRODUCT_HUNT["actor"]: S.PRODUCT_HUNT["cost_per_item"],
}
RUN_FEE = {S.X_POSTS["actor"]: 0.0025, S.FUNDING_NEWS["actor"]: 0.001}
worst: dict[str, float] = {}


def fake_run_actor(actor_id, run_input, token, max_charge_usd=None, max_items=None):
    if actor_id == S.FUNDING_NEWS["actor"]:
        cost = len(run_input["queries"].split("\n")) * run_input["maxPagesPerQuery"] * 0.0045
    else:
        assert max_items, f"{actor_id} started without a maxItems cap"
        cost = max_items * PRICE[actor_id]
    worst[actor_id] = worst.get(actor_id, 0) + cost + RUN_FEE.get(actor_id, 0.00005)
    return []


def fake_many(actor_id, inputs, token, max_workers=6, **kw):
    for inp in inputs:
        fake_run_actor(actor_id, inp, token, **kw)
    return []


for mod in (linkedin_jobs, launches):
    mod.run_actor = fake_run_actor
for mod in (meta_ads, upwork, x_posts):
    mod.run_actor_many = fake_many

budget = 5.0
all_sources = list(S.SOURCES)
budgets = S.source_budgets(all_sources, budget)
ctx = ScanContext(hours=24, service="All Services", apify_token="x", budgets=budgets)
for fn in (linkedin_jobs.collect, meta_ads.collect, upwork.collect, x_posts.collect,
           launches.collect_product_hunt, launches.collect_funding_news):
    fn(ctx)

# LinkedIn posts: intercept the run start and price its maxItems.
keywords = get_all_keywords()
post_items = int(max(budgets["linkedin_post"] - 0.001 * len(keywords), 0) / APIFY_POST_PRICE)
post_caps = []


def fake_start(queries, posted_limit, token, max_items=None, per_query=100):
    post_caps.append(max_items)
    raise searcher.requests.exceptions.RequestException("stop after capturing params")


searcher._start_run = fake_start
try:
    searcher.run_apify_search(keywords, "24h", "x", max_items_total=post_items)
except RuntimeError:
    pass
n_batches = -(-len(keywords) // QUERIES_PER_RUN)
post_worst = (post_items // n_batches) * n_batches * APIFY_POST_PRICE + 0.001 * len(keywords)
worst["linkedin_posts"] = post_worst

total = sum(worst.values())
for k, v in sorted(worst.items(), key=lambda x: -x[1]):
    print(f"    {k:42s} ≤ ${v:.3f}")
print(f"    {'TOTAL worst case':42s} ≤ ${total:.2f}")

check(post_caps and all(post_caps), "LinkedIn post runs carry a maxItems cap")
check(total <= budget, f"worst-case full scan ${total:.2f} ≤ ${budget:.2f} budget")
check(post_items >= 900, f"LinkedIn posts keep the largest allowance ({post_items} posts)")

# Disabled sources' shares are redistributed, never exceeding the budget.
sub = S.source_budgets(["linkedin_post", "linkedin_job"], budget)
check(sum(sub.values()) <= budget and sub["linkedin_post"] > budgets["linkedin_post"],
      "two-source scan gets the freed-up budget, still ≤ $5")
check(S.source_budgets(all_sources, 2.0)["linkedin_post"] < budgets["linkedin_post"],
      "--budget 2 scales every allowance down")

print(f"\n{'ALL TESTS PASSED' if fails == 0 else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
