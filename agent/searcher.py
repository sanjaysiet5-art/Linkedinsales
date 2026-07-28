"""
Apify-powered LinkedIn post search.

Uses the harvestapi/linkedin-post-search actor (no cookies required), which
searches LinkedIn posts directly — unlike the old SerpAPI/Google approach:
  • full post text (not truncated Google snippets)
  • exact post timestamps (postedAt.date) instead of regex-parsed "2 days ago"
  • author objects (company vs person) + engagement metrics
  • no 6-12h Google indexing lag

One actor run accepts MANY search queries at once, so a full 110-keyword scan
is a handful of runs instead of 110 API calls.
"""

import time

import requests

from config.settings import (
    APIFY_TOKEN,
    APIFY_ACTOR_ID,
    APIFY_BASE_URL,
    TIMELINE_CONFIG,
    MAX_POSTS_PER_QUERY,
    QUERIES_PER_RUN,
    RUN_POLL_SECONDS,
    RUN_TIMEOUT_SECONDS,
)


def get_posted_limit(timeline: str) -> str:
    cfg = TIMELINE_CONFIG.get(timeline, TIMELINE_CONFIG["1day"])
    return cfg["posted_limit"]


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _start_run(search_queries: list[str], posted_limit: str, token: str) -> str:
    """Start an actor run and return its run ID."""
    url = f"{APIFY_BASE_URL}/acts/{APIFY_ACTOR_ID}/runs"
    payload = {
        "searchQueries": search_queries,
        "maxPosts": MAX_POSTS_PER_QUERY * len(search_queries),
        "postedLimit": posted_limit,
        "sortBy": "date",
    }
    resp = requests.post(url, params={"token": token}, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def _wait_for_run(run_id: str, token: str) -> str:
    """Poll a run until it finishes. Returns the default dataset ID."""
    url = f"{APIFY_BASE_URL}/actor-runs/{run_id}"
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    while True:
        resp = requests.get(url, params={"token": token}, timeout=30)
        resp.raise_for_status()
        data = resp.json()["data"]
        status = data["status"]
        if status == "SUCCEEDED":
            return data["defaultDatasetId"]
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run {run_id} ended with status {status}")
        if time.monotonic() > deadline:
            raise RuntimeError(f"Apify run {run_id} exceeded {RUN_TIMEOUT_SECONDS}s timeout")
        time.sleep(RUN_POLL_SECONDS)


def _fetch_dataset_items(dataset_id: str, token: str) -> list[dict]:
    """Download all items from a dataset, paginating past the 1000-item limit."""
    url = f"{APIFY_BASE_URL}/datasets/{dataset_id}/items"
    items: list[dict] = []
    offset = 0
    limit = 1000
    while True:
        resp = requests.get(
            url,
            params={"token": token, "format": "json", "offset": offset, "limit": limit},
            timeout=60,
        )
        resp.raise_for_status()
        batch = resp.json()
        items.extend(batch)
        if len(batch) < limit:
            return items
        offset += limit


def run_apify_search(search_queries: list[str], posted_limit: str, token: str,
                     progress=None) -> list[dict]:
    """
    Search LinkedIn posts for all queries in batched actor runs.
    Returns raw Apify post items tagged with _keyword / _timeline / _query.
    `progress` is an optional callable(batch_index, total_batches, items_so_far).
    """
    token = token or APIFY_TOKEN
    if not token:
        raise RuntimeError("Apify token missing. Set APIFY_API_TOKEN in .env")

    all_items: list[dict] = []
    batches = _chunk(search_queries, QUERIES_PER_RUN)

    for i, batch in enumerate(batches, 1):
        try:
            run_id = _start_run(batch, posted_limit, token)
            dataset_id = _wait_for_run(run_id, token)
            items = _fetch_dataset_items(dataset_id, token)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Apify request failed for batch {i}/{len(batches)}: {e}") from e

        for item in items:
            if item.get("type") and item["type"] != "post":
                continue
            # The actor tags each item with the query that matched it
            matched_query = (item.get("query") or {}).get("search", "")
            item["_keyword"] = matched_query
            item["_query"] = matched_query
            all_items.append(item)

        if progress:
            progress(i, len(batches), len(all_items))

    return all_items


def search_linkedin_posts(keyword: str, timeline: str, token: str) -> list[dict]:
    """
    Search LinkedIn posts for a single keyword within the given timeline.
    Returns raw Apify post items (deduped by post URL).
    """
    posted_limit = get_posted_limit(timeline)
    items = run_apify_search([keyword], posted_limit, token)

    seen_urls = set()
    results = []
    for item in items:
        url = item.get("linkedinUrl", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            item["_timeline"] = timeline
            results.append(item)
    return results


def search_all_timelines(keywords: list[str], token: str, progress=None) -> list[dict]:
    """
    Single broadest scan (1 week) across all keywords, batched into a few
    actor runs. Results are later bucketed by exact timestamp.
    """
    items = run_apify_search(keywords, "week", token, progress=progress)

    seen_urls: set[str] = set()
    all_results: list[dict] = []
    for item in items:
        url = item.get("linkedinUrl", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            item["_timeline"] = "1week"
            all_results.append(item)
    return all_results
