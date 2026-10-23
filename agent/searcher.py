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


def _start_run(search_queries: list[str], posted_limit: str, token: str,
               max_items: int | None = None, per_query: int = MAX_POSTS_PER_QUERY) -> str:
    """Start an actor run and return its run ID.
    max_items is Apify's hard cap on billable posts for this run (scan budget)."""
    url = f"{APIFY_BASE_URL}/acts/{APIFY_ACTOR_ID}/runs"
    payload = {
        "searchQueries": search_queries,
        "maxPosts": per_query * len(search_queries),
        "postedLimit": posted_limit,
        "sortBy": "date",
    }
    params = {"token": token}
    if max_items:
        params["maxItems"] = max(1, int(max_items))
    resp = requests.post(url, params=params, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def _wait_for_run(run_id: str, token: str, poll_callback=None) -> str:
    """Poll a run until it finishes. Returns the default dataset ID."""
    url = f"{APIFY_BASE_URL}/actor-runs/{run_id}"
    start_time = time.monotonic()
    deadline = start_time + RUN_TIMEOUT_SECONDS
    while True:
        elapsed = int(time.monotonic() - start_time)
        if poll_callback:
            try:
                poll_callback(elapsed)
            except Exception:
                pass
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
                     progress=None, max_items_total: int | None = None) -> list[dict]:
    """
    Search LinkedIn posts for all queries in batched actor runs.
    Returns raw Apify post items tagged with _keyword / _timeline / _query.
    `progress` is an optional callable(batch_index, total_batches, items_so_far, status_note).
    """
    token = token or APIFY_TOKEN
    if not token:
        raise RuntimeError("Apify token missing. Set APIFY_API_TOKEN in .env")

    all_items: list[dict] = []
    batches = _chunk(search_queries, QUERIES_PER_RUN)

    # Budget: split the post allowance evenly across batches (hard maxItems per
    # run). Per-keyword cap is 2× the even share, so quiet keywords' unused
    # share can go to busy ones within the same batch.
    per_batch = per_query = None
    if max_items_total:
        per_batch = max(1, max_items_total // len(batches))
        per_query = min(MAX_POSTS_PER_QUERY,
                        max(10, 2 * max_items_total // max(len(search_queries), 1)))

    for i, batch in enumerate(batches, 1):
        if progress:
            progress(i, len(batches), len(all_items), "starting cloud actor...")
        try:
            run_id = _start_run(batch, posted_limit, token, max_items=per_batch,
                                per_query=per_query or MAX_POSTS_PER_QUERY)

            def _on_poll(elapsed):
                if progress:
                    progress(i, len(batches), len(all_items), f"Apify scanning on cloud ({elapsed}s)")

            dataset_id = _wait_for_run(run_id, token, poll_callback=_on_poll)
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
            progress(i, len(batches), len(all_items), "batch items downloaded")

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


def search_linkedin_posts_batch(keywords: list[str], timeline: str, token: str, progress=None,
                                max_items_total: int | None = None) -> list[dict]:
    """
    Search LinkedIn posts for multiple keywords within a timeline, batched into 
    actor runs of QUERIES_PER_RUN (20 per run) for maximum speed.
    """
    posted_limit = get_posted_limit(timeline)
    items = run_apify_search(keywords, posted_limit, token, progress=progress,
                             max_items_total=max_items_total)

    seen_urls: set[str] = set()
    results: list[dict] = []
    for item in items:
        url = item.get("linkedinUrl", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            item["_timeline"] = timeline
            results.append(item)
    return results


def search_all_timelines(keywords: list[str], token: str, progress=None,
                         max_items_total: int | None = None) -> list[dict]:
    """
    Single broadest scan (1 week) across all keywords, batched into a few
    actor runs. Results are later bucketed by exact timestamp.
    """
    items = run_apify_search(keywords, "week", token, progress=progress,
                             max_items_total=max_items_total)

    seen_urls: set[str] = set()
    all_results: list[dict] = []
    for item in items:
        url = item.get("linkedinUrl", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            item["_timeline"] = "1week"
            all_results.append(item)
    return all_results

