"""
Key-contact finder for a lead's company (dashboard "👥 Key Contacts").

  1. find_key_contacts(domain): CEO/Founder, COO, CMO and Head of Marketing.
       • Apollo People API Search first — free, but names come back masked.
       • Apify LinkedIn employees scraper (harvestapi) when Apollo finds fewer
         than MIN_APOLLO_HITS key people — ~$0.003/profile, full names.
  2. reveal_contact(contact): Apollo people/match → verified email (sync,
     1 credit). Mobile numbers only arrive later at the phone webhook, and
     only when PUBLIC_BASE_URL (or Render's RENDER_EXTERNAL_URL) is set.

Everything is cached in data/contacts_cache.json so re-opening a card or a
second teammate clicking the same company never re-spends credits.
"""

import json
import os
import re
import secrets
import threading
from datetime import datetime
from urllib.parse import quote

from agent.apollo import ApolloClient

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "contacts_cache.json")
APIFY_ACTOR = os.getenv("CONTACTS_APIFY_ACTOR", "harvestapi~linkedin-company-employees")
APIFY_MAX_PROFILES = int(os.getenv("CONTACTS_APIFY_MAX_PROFILES", "15"))
# Google results for site:linkedin.com/in — finds the public profile of each contact
# (Apollo's free search has no LinkedIn field; Apify gives internal /in/ACwAA… ids).
GOOGLE_ACTOR = "apify~google-search-scraper"
MIN_APOLLO_HITS = 2
PER_ROLE = 2

# role → (Apollo/LinkedIn title filters, regex the returned title must match)
ROLES = {
    "CEO": (["ceo", "chief executive officer", "founder", "co-founder", "managing director"],
            re.compile(r"\b(ceo|chief executive|founder|managing director)\b", re.I)),
    "COO": (["coo", "chief operating officer"],
            re.compile(r"\b(coo|chief operating)\b", re.I)),
    "CMO": (["cmo", "chief marketing officer"],
            re.compile(r"\b(cmo|chief marketing)\b", re.I)),
    "Head of Marketing": (["head of marketing", "vp marketing", "vice president marketing",
                           "director of marketing", "marketing director", "marketing head"],
                          re.compile(r"marketing.*\b(head|vp|vice president|director)\b|"
                                     r"\b(head|vp|vice president|director)\b.*marketing", re.I)),
}
# "City COO", "COO - Logistics (Karnataka)" … are not the company-level person.
_SUB_ROLE = re.compile(r"\b(city|cluster|regional|zonal|zone|area|state|logs?|logistics|supply|"
                       r"assistant|associate|deputy|office of|to the)\b|\s[-–|,(]\s*\w", re.I)

_lock = threading.Lock()


# ─── Cache ────────────────────────────────────────────────────────────────────
def _load() -> dict:
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("companies", {})
    data.setdefault("people", {})
    data.setdefault("phones", {})
    return data


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, CACHE_PATH)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── Roles ────────────────────────────────────────────────────────────────────
def role_of(title: str) -> str:
    """Bucket a job title into one of ROLES, or "" when it's none of them."""
    for role, (_, rx) in ROLES.items():
        if rx.search(title or ""):
            return role
    return ""


def _rank(c: dict) -> tuple:
    # Company-level titles first, then shorter (less qualified) titles.
    title = c.get("title") or ""
    return (bool(_SUB_ROLE.search(title)), len(title))


def _pick(candidates: list[dict]) -> list[dict]:
    """Up to PER_ROLE per role, deduped by name, in ROLES order."""
    out, seen = [], set()
    for role in ROLES:
        group = sorted((c for c in candidates if c["role"] == role), key=_rank)
        kept = 0
        for c in group:
            key = (c["first_name"].lower(), (c.get("last_name") or "")[:2].lower())
            if key in seen or kept >= PER_ROLE:
                continue
            seen.add(key)
            out.append(c)
            kept += 1
    return out


def _contact_key(c: dict, domain: str) -> str:
    if c.get("apollo_id"):
        return "apollo:" + c["apollo_id"]
    return f"name:{c['first_name']} {c.get('last_name', '')}@{domain}".lower()


# ─── Sources ──────────────────────────────────────────────────────────────────
def _from_apollo(apollo: ApolloClient, domain: str) -> list[dict]:
    out = []
    for role, (titles, _) in ROLES.items():
        for p in apollo.search_people(domain, titles, per_page=10):
            title = p.get("title") or ""
            if role_of(title) != role:
                continue
            out.append({
                "role": role, "title": title, "source": "apollo",
                "first_name": p.get("first_name") or "",
                "last_name": p.get("last_name_obfuscated") or p.get("last_name") or "",
                "masked": bool(p.get("last_name_obfuscated")),
                "apollo_id": p.get("id") or "",
                "has_email": bool(p.get("has_email")),
                "has_phone": str(p.get("has_direct_phone") or "").lower().startswith(("yes", "maybe")),
                "linkedin_url": "",
            })
    return out


def _apify_title(item: dict) -> str:
    for pos in item.get("currentPositions") or item.get("experience") or []:
        if pos.get("current", True) and pos.get("title"):
            return pos["title"]
    return item.get("headline") or item.get("position") or ""


def _from_apify(company_linkedin_url: str, token: str) -> list[dict]:
    from agent.collectors import run_actor
    titles = [t for ts, _ in ROLES.values() for t in ts]
    items = run_actor(APIFY_ACTOR, {
        "companies": [company_linkedin_url],
        "jobTitles": titles,
        "profileScraperMode": "Short ($4 per 1k)",
        "maxItems": APIFY_MAX_PROFILES,
        "takePages": 1,
    }, token, max_items=APIFY_MAX_PROFILES)
    out = []
    for it in items:
        title = _apify_title(it)
        role = role_of(title)
        if not role or not it.get("firstName"):
            continue
        out.append({
            "role": role, "title": title, "source": "apify",
            "first_name": it.get("firstName") or "", "last_name": it.get("lastName") or "",
            "masked": False, "apollo_id": "", "has_email": True, "has_phone": False,
            # Short mode gives internal /in/ACwAA… URLs; still clickable on LinkedIn.
            "linkedin_url": it.get("linkedinUrl") or "",
        })
    return out


def _is_company_page(c: dict, lead: dict, domain: str) -> bool:
    """LinkedIn profiles named after the company ("Reelotek Metals", Founder) aren't people."""
    name = f"{c['first_name']} {c.get('last_name', '')}".lower()
    words = {domain.split(".")[0]} | set(re.findall(r"[a-z]{4,}", (lead.get("company") or "").lower()))
    return any(w and w in name for w in words)


def company_linkedin_url(lead: dict, apollo: ApolloClient) -> str:
    """LinkedIn company page for the lead: from the card, else Apollo org enrich."""
    for k in ("company_linkedin_url", "author_url", "url"):
        u = lead.get(k) or ""
        if "linkedin.com/company/" in u:
            return u.split("?")[0]
    org = apollo.enrich_organization(domain=lead.get("company_domain"), name=lead.get("company")) or {}
    return org.get("linkedin_url") or ""


# ─── LinkedIn profiles ────────────────────────────────────────────────────────
_ROLE_QUERY = {"CEO": '(CEO OR Founder OR "Managing Director")', "COO": '(COO OR "Chief Operating")',
               "CMO": '(CMO OR "Chief Marketing")', "Head of Marketing": "Marketing"}


def _company_words(lead: dict, domain: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]{3,}", (lead.get("company") or "").lower()))
    words -= {"inc", "ltd", "llc", "pvt", "private", "limited", "the", "and", "solutions",
              "technologies", "group", "company", "india", "global", "international"}
    return words | {domain.split(".")[0]}


def public_linkedin(url: str) -> str:
    """https://www.linkedin.com/in/<slug>, or "" for anything else (incl. ACwAA… ids)."""
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url or "")
    if not m or m.group(1).startswith("ACwAA"):
        return ""
    return f"https://www.linkedin.com/in/{m.group(1)}"


def _linkedin_query(c: dict, lead: dict, domain: str) -> str:
    company = lead.get("company") or domain.split(".")[0]
    return f'site:linkedin.com/in "{c["first_name"]}" "{company}" {_ROLE_QUERY.get(c["role"], "")}'.strip()


def _match_profile(c: dict, results: list[dict], words: set[str]) -> str:
    """First result that is this person: first name leads the title, last-name
    initial(s) agree, and the company appears in the title or snippet."""
    first = c["first_name"].lower()
    last = re.split(r"\*", c.get("last_name") or "")[0].lower()   # "Si***h" → "si"
    for r in results:
        url = public_linkedin(r.get("url") or "")
        title = (r.get("title") or "").lower()
        text = title + " " + (r.get("description") or "").lower()
        if not url or not title.startswith(first):
            continue
        rest = title[len(first):].split(" - ")[0].replace(",", " ").split()
        if last and not any(t.startswith(last) or (len(t.rstrip(".")) == 1 and t[0] == last[0])
                            for t in rest):
            continue
        if any(w in text for w in words):
            return url
    return ""


def _google_pages(queries: list[str], token: str) -> list[dict]:
    from agent.collectors import run_actor
    return run_actor(GOOGLE_ACTOR, {"queries": "\n".join(queries), "maxPagesPerQuery": 1,
                                    "resultsPerPage": 10}, token, max_charge_usd=0.5)


def resolve_linkedin(contacts: list[dict], lead: dict, domain: str, token: str) -> str:
    """Fill linkedin_url (public profile) on contacts that lack one; one Apify run per company.
    Every contact also gets a LinkedIn people-search link as a fallback. Returns a status note."""
    company = lead.get("company") or domain.split(".")[0]
    for c in contacts:
        kw = f"{c['first_name']} {'' if c.get('masked') else c.get('last_name', '')} {company}"
        c["linkedin_search_url"] = ("https://www.linkedin.com/search/results/people/?keywords="
                                    + quote(" ".join(kw.split())))
        if public_linkedin(c.get("linkedin_url", "")):
            c["linkedin_url"] = public_linkedin(c["linkedin_url"])
            c["linkedin_checked"] = True
    todo = [c for c in contacts if not c.get("linkedin_checked")]
    if not todo:
        return ""
    if not token:
        return "linkedin lookup skipped: APIFY_API_TOKEN not set"
    queries = {_linkedin_query(c, lead, domain): c for c in todo}
    try:
        pages = _google_pages(list(queries), token)
    except Exception as e:  # noqa: BLE001 — contacts are still useful without links
        return f"linkedin lookup failed: {str(e)[:120]}"
    words = _company_words(lead, domain)
    for page in pages:
        c = queries.get(((page.get("searchQuery") or {}).get("term") or "").strip())
        if c is None:
            continue
        found = _match_profile(c, page.get("organicResults") or [], words)
        if found:
            c["internal_linkedin_url"] = c.get("linkedin_url", "")
            c["linkedin_url"] = found
    for c in todo:          # searched once, found or not: never pay for the same search twice
        c["linkedin_checked"] = True
    return "google→linkedin"


# ─── Public API ───────────────────────────────────────────────────────────────
def find_key_contacts(lead: dict, refresh: bool = False, apollo: ApolloClient | None = None,
                      apify_token: str | None = None) -> dict:
    """{"domain", "contacts": [...], "sources": [...], "cached"} for one lead's company."""
    domain = (lead.get("company_domain") or "").lower().removeprefix("www.").strip("/")
    if not domain:
        raise ValueError("This lead has no company domain, so contacts can't be looked up.")
    apollo = apollo or ApolloClient()
    with _lock:
        cache = _load()
        hit = cache["companies"].get(domain)
    token = apify_token if apify_token is not None else os.getenv("APIFY_API_TOKEN", "")
    if hit and not refresh:
        hit["contacts"] = [c for c in hit["contacts"] if not _is_company_page(c, lead, domain)]
        # Entries cached before LinkedIn lookup existed get their links filled in once.
        if any(not c.get("linkedin_checked") for c in hit["contacts"]):
            note = resolve_linkedin(hit["contacts"], {"company": hit.get("company"), **lead}, domain, token)
            if note and note not in hit["sources"]:
                hit["sources"].append(note)
            with _lock:
                cache = _load()
                cache["companies"][domain] = hit
                _save(cache)
        return {**hit, "contacts": [_with_reveal(c, cache) for c in hit["contacts"]], "cached": True}

    sources, candidates = [], []
    if apollo.is_enabled():
        candidates = _from_apollo(apollo, domain)
        sources.append("apollo")
    if len(_pick(candidates)) < MIN_APOLLO_HITS and token:
        li = company_linkedin_url(lead, apollo)
        if li:
            try:
                candidates += _from_apify(li, token)
                sources.append("apify")
            except Exception as e:  # noqa: BLE001 — Apollo results still useful
                sources.append(f"apify failed: {str(e)[:120]}")

    contacts = _pick([c for c in candidates if not _is_company_page(c, lead, domain)])
    for c in contacts:
        c["key"] = _contact_key(c, domain)
    note = resolve_linkedin(contacts, lead, domain, token)
    if note:
        sources.append(note)
    entry = {"domain": domain, "company": lead.get("company") or "", "contacts": contacts,
             "sources": sources, "found_at": _now()}
    with _lock:
        cache = _load()
        cache["companies"][domain] = entry
        _save(cache)
        return {**entry, "contacts": [_with_reveal(c, cache) for c in contacts], "cached": False}


def _with_reveal(c: dict, cache: dict) -> dict:
    """Overlay what has already been revealed (email, full name, phone)."""
    rev = cache["people"].get(c["key"])
    if not rev:
        return c
    out = {**c, **rev}
    out["linkedin_url"] = public_linkedin(rev.get("linkedin_url") or "") or c.get("linkedin_url", "")
    phone = cache["phones"].get(rev.get("apollo_id") or "")
    if phone:
        out["mobile"] = phone["number"]
        out["phone_status"] = "found"
    return out


def phone_webhook_url() -> str:
    """Public URL Apollo can POST mobile numbers to, or "" when we're only on localhost."""
    base = (os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not base:
        return ""
    with _lock:
        cache = _load()
        token = cache.setdefault("webhook_token", secrets.token_urlsafe(16))
        _save(cache)
    return f"{base}/api/apollo/phone-webhook?token={token}"


def reveal_contact(domain: str, key: str, apollo: ApolloClient | None = None) -> dict:
    """Spend one Apollo credit to unmask a contact; result is cached by key."""
    apollo = apollo or ApolloClient()
    if not apollo.is_enabled():
        raise RuntimeError("APOLLO_API_KEY is not set in .env")
    with _lock:
        cache = _load()
    entry = cache["companies"].get(domain) or {}
    c = next((x for x in entry.get("contacts", []) if x.get("key") == key), None)
    if c is None:
        raise KeyError("Contact not found; reload Key Contacts.")
    if key in cache["people"]:
        return _with_reveal(c, cache)

    webhook = phone_webhook_url()
    if c.get("apollo_id"):
        person = apollo.reveal_person(c["apollo_id"], webhook_url=webhook)
    else:
        person = apollo.match_person_by_name(c["first_name"], c.get("last_name", ""), domain,
                                             webhook_url=webhook,
                                             linkedin_url=public_linkedin(c.get("linkedin_url", "")))
    if not person:
        raise LookupError("Apollo has no record for this person.")

    rev = {
        "first_name": person.get("first_name") or c["first_name"],
        "last_name": person.get("last_name") or c.get("last_name", ""),
        "masked": False,
        "title": person.get("title") or c.get("title", ""),
        "email": person.get("email") or "",
        "email_status": person.get("email_status") or "",
        "linkedin_url": public_linkedin(person.get("linkedin_url") or "") or c.get("linkedin_url", ""),
        "apollo_id": person.get("id") or c.get("apollo_id", ""),
        # Apollo may already know a number from an earlier reveal on this account.
        "mobile": next((n.get("sanitized_number") or n.get("raw_number")
                        for n in person.get("phone_numbers") or []
                        if n.get("sanitized_number") or n.get("raw_number")), ""),
        "revealed_at": _now(),
    }
    rev["phone_status"] = "found" if rev["mobile"] else ("pending" if webhook else "needs_public_url")
    with _lock:
        cache = _load()
        cache["people"][key] = rev
        _save(cache)
        return _with_reveal(c, cache)


def record_phone_webhook(payload, token: str) -> int:
    """Store numbers Apollo delivered. Returns how many people got a number."""
    with _lock:
        cache = _load()
        if not token or token != cache.get("webhook_token"):
            raise PermissionError("bad webhook token")
        found = 0
        for person in _iter_people(payload):
            nums = [n.get("sanitized_number") or n.get("raw_number")
                    for n in person.get("phone_numbers") or []]
            nums = [n for n in nums if n]
            if person.get("id") and nums:
                cache["phones"][person["id"]] = {"number": nums[0], "all": nums, "at": _now()}
                found += 1
        # People whose reveal finished without a number: stop showing "pending".
        for person in _iter_people(payload):
            pid = person.get("id")
            if pid and pid not in cache["phones"]:
                for rev in cache["people"].values():
                    if rev.get("apollo_id") == pid and rev.get("phone_status") == "pending":
                        rev["phone_status"] = "not_found"
        _save(cache)
        return found


def _iter_people(obj):
    """Apollo's webhook body nests people under varying keys; find every dict with an id."""
    if isinstance(obj, dict):
        if obj.get("id") and "phone_numbers" in obj:
            yield obj
        for v in obj.values():
            yield from _iter_people(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_people(v)
