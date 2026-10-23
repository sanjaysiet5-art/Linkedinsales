"""
Source-aware outreach drafts for a single lead card (dashboard "✉️ Draft Outreach").

For any card (LinkedIn post / job, Upwork, Freelancer, funding news, Product
Hunt, Meta ads, X) this writes:
  • a personalised email — two variants for LinkedIn jobs (agency partner vs
    FTE contract staffing), one otherwise;
  • a direct response to post on the platform itself (LinkedIn comment,
    Upwork proposal, Product Hunt comment ...), per config/outreach.py.

Design choices
  • The model only writes the personalised body. The links block and the
    signature are appended here, so they're always exact.
  • Grapes facts come from config/outreach.py only; the prompt forbids any
    other client names or numbers.
  • The recipient's first name is resolved here (decision-maker → author →
    Product Hunt maker), never guessed by the model. Unknown → "[First name]"
    so the user fills it in rather than sending "Hi Anta International".
"""

import os
import re

from pydantic import BaseModel

from config.outreach import (
    COMPANY_FACTS, DEFAULT_SOURCE, JOB_PITCHES, LINKS, SENDER, SERVICE_FACTS, SOURCE_RULES,
)
from config.sources import SOURCES

MODEL = os.getenv("OUTREACH_MODEL", "gemini-flash-latest")
# Tried when MODEL is overloaded (503) or rate-limited — Flash 503s under peak demand.
FALLBACK_MODEL = os.getenv("OUTREACH_FALLBACK_MODEL", "gemini-flash-lite-latest")
NAME_PLACEHOLDER = "[First name]"

# Regex-derived pitch tags (agent/filter.py) → the 9 service labels.
_SERVICE_ALIASES = {
    "seo": "SEO",
    "sem": "Media Planning & Buying",
    "smo": "Social Media & Content Strategy",
    "brand": "Branding & Designing",
    "creative": "Films & Campaigns",
}

# Author strings that are a marketplace placeholder, not a person's name.
_GENERIC_AUTHOR = re.compile(r"freelancer\.com client|^unknown$|^client$", re.I)


class _Email(BaseModel):
    """Parts of one email; assemble() lays them out in the house structure."""
    angle: str
    subject: str
    context: str          # how we found them + their need
    about: str            # Grapes intro, relevant to the need
    capabilities: list[str]
    fit: str              # why the approach fits their situation
    outcomes: list[str]   # copied verbatim from the proof points given
    cta: str


class _Drafts(BaseModel):
    emails: list[_Email]
    response: str


# ─── Lead → prompt ────────────────────────────────────────────────────────────
def lead_services(lead: dict) -> list[str]:
    """Up to two of the 9 service labels for this lead ([] = let the model pick)."""
    out: list[str] = []
    for s in lead.get("pitch_services") or []:
        label = s if s in SERVICE_FACTS else _SERVICE_ALIASES.get(str(s).lower())
        if label and label not in out:
            out.append(label)
    return out[:2]


# Selected key contact (dashboard "👥 Key Contacts") → what that reader cares about.
ROLE_ANGLES = {
    "CEO": "They run the company: lead with business growth, brand and revenue impact; keep it short and strategic, no channel jargon.",
    "COO": "They own operations: lead with execution speed, cost efficiency and one accountable partner across functions (AI-enabled delivery through Raisin and Three Zinc).",
    "CMO": "They own marketing: be specific about channels, creative and measurable growth; name the services that fit their need.",
    "Head of Marketing": "They run marketing day to day: be concrete about the work, timelines and the team they'd get; name the services that fit their need.",
}


def recipient_first_name(lead: dict) -> str:
    """Best first name to greet, or "" when no real person is known."""
    picked = (lead.get("recipient") or {}).get("name") or ""
    if picked.strip():
        return picked.strip().split()[0]
    for dm in lead.get("decision_makers") or []:
        name = (dm.get("name") or "").strip()
        if name:
            return name.split()[0]
    source = lead.get("source") or DEFAULT_SOURCE
    author = (lead.get("author") or "").strip()
    if source == "product_hunt":
        for h in lead.get("hooks") or []:
            if h.lower().startswith("makers:"):
                first_maker = h.split(":", 1)[1].split(",")[0].strip()
                return first_maker.split()[0] if first_maker else ""
        return ""
    if source in ("linkedin_post", "x_post", "upwork"):
        if lead.get("entity_type") == "company" or _GENERIC_AUTHOR.search(author):
            return ""
        # "Simona (Upwork client)" → "Simona"; "@handle" X authors stay blank.
        first = re.sub(r"\(.*?\)", "", author).strip().split()
        if first and not first[0].startswith("@"):
            return first[0]
    return ""


def build_prompt(lead: dict) -> tuple[str, str]:
    """(system_instruction, user_prompt) for one lead."""
    source = lead.get("source") or DEFAULT_SOURCE
    rules = SOURCE_RULES.get(source, SOURCE_RULES[DEFAULT_SOURCE])
    services = lead_services(lead)
    name = recipient_first_name(lead) or NAME_PLACEHOLDER

    if services:
        service_block = "\n".join(
            f"{s}\n  Capabilities: " + "; ".join(SERVICE_FACTS[s]["capabilities"])
            + "\n  Proof points: " + "; ".join(SERVICE_FACTS[s]["proof"])
            for s in services
        )
        service_line = f"Lead services: {', '.join(services)}"
    else:
        service_block = "\n".join(
            f"{s}\n  Capabilities: " + "; ".join(v["capabilities"])
            + "\n  Proof points: " + "; ".join(v["proof"])
            for s, v in SERVICE_FACTS.items()
        )
        service_line = "Lead services: not tagged. Pick the ONE or TWO services that best fit what the lead needs and use only those."

    if source == "linkedin_job":
        email_spec = (
            "Write EXACTLY TWO emails, in this order, each a complete standalone email:\n"
            + "\n".join(f'{i + 1}. angle="{p["angle"]}": {p["brief"]}' for i, p in enumerate(JOB_PITCHES))
        )
    else:
        email_spec = 'Write EXACTLY ONE email. Set angle to a 2-4 word label for the pitch.'

    system = f"""You write cold outreach for Grapes Worldwide, an Indian creative, digital and AI agency. The user sends these emails under their own name, so they must read like a sharp account director wrote them by hand after actually reading the lead, not like a template.

EMAIL PARTS (the greeting, "Hope you're doing well.", headings, sign-off and links are added automatically, so never write them):
- context: 1-2 sentences that reference the lead's source specifically (see HOW WE FOUND THEM) and restate their need using 1-2 concrete details from the lead (their words, role title, budget, product, round, offer).
- about: 1-2 sentences introducing Grapes Worldwide, relevant to their need.
- capabilities: 3-5 short items that match THEIR need only (from the capabilities given, lightly reworded is fine).
- fit: 1-2 sentences on why the approach fits their specific situation.
- outcomes: 2-3 items copied EXACTLY, word for word, from the proof points given. Never reword, merge or add to them.
- cta: one low-friction ask (a 15-minute call this week, or sharing relevant case studies).

STYLE:
- The whole email should land at 150-230 words. Plain text.
- Warm, confident, specific. Indian-English business tone is fine.
- Vary sentence length. Contractions are fine.
- Subject line: 4-8 words, specific to the lead, no emojis, no clickbait, no "Re:".
- Never use: em dashes, "I hope this email finds you well", "I wanted to reach out", "delve", "leverage", "synergy", "elevate", "unlock", "game-changer", "cutting-edge", "seamless", "robust", "in today's fast-paced", "look no further", "tailored solutions", exclamation marks.

FACTS (hard rules):
- Use ONLY the Grapes facts, capabilities and proof points provided. Never invent clients, numbers, awards or years.
- Never invent facts about the lead. If a detail isn't in the lead, don't state it. Only say they are looking for an agency/partner if the lead text says so.
- The recipient is addressed as "{name}". Never address a company name as if it were a person. In the direct response, if the name is "{NAME_PLACEHOLDER}", start without a name (e.g. "Hi there" or no greeting).

GRAPES FACTS:
{COMPANY_FACTS}"""

    hooks = "; ".join(lead.get("hooks") or [])
    rcpt = lead.get("recipient") or {}
    recipient_block = ""
    if rcpt.get("name"):
        recipient_block = (f"\nRECIPIENT (write the email to this person)\n"
                           f"Name: {rcpt['name']}\nTitle: {rcpt.get('title') or ''}\n"
                           f"Angle: {ROLE_ANGLES.get(rcpt.get('role') or '', 'Match the pitch to their title.')}\n"
                           "They may not be the person who wrote the post or job listing; "
                           "reference the company's signal, not 'your post', unless they are the author.\n")
    user = f"""SOURCE: {SOURCES.get(source, {}).get('label', source)}
HOW WE FOUND THEM: {rules['opener']}

LEAD
Name/Author: {lead.get('author') or ''}
Headline/Context: {lead.get('author_headline') or ''}
Company: {lead.get('company') or ''}
Company domain: {lead.get('company_domain') or ''}
Company size: {lead.get('company_size') or ''}
Region: {lead.get('region') or ''}
Signals: {hooks}
Post / listing text:
{(lead.get('snippet') or '')[:2500]}
{recipient_block}
{service_line}
{service_block}

EMAIL
{email_spec}

DIRECT RESPONSE ({rules['response_label']})
{rules['response']}
Put it in the `response` field. Same fact rules and banned phrases apply."""
    return system, user


# ─── Assembly ────────────────────────────────────────────────────────────────
def _clean(text: str) -> str:
    """Strip the em/en dashes and exclamation marks models slip in despite the instruction."""
    text = re.sub(r"\s*[—–]\s*", ", ", text or "")
    text = text.replace("!", ".")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _footer() -> str:
    links = "\n".join(f"- {label}: {url}" for label, url in LINKS)
    sig = "\n".join([v for v in (SENDER["name"], SENDER["title"]) if v]
                    + [f"{label}: {SENDER[k]}" for label, k in (("Mobile", "phone"), ("Email", "email"))
                       if SENDER[k]])
    return f"A bit more on our work, if useful:\n{links}\n\nBest regards,\n{sig}"


def _allowed_proof(lead: dict) -> list[str]:
    services = lead_services(lead) or list(SERVICE_FACTS)
    return [pr for sv in services for pr in SERVICE_FACTS[sv]["proof"]]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _outcomes(lead: dict, picked: list[str]) -> list[str]:
    """Keep only proof points that exist in config; the model may not invent claims."""
    allowed = _allowed_proof(lead)
    by_norm = {_norm(pr): pr for pr in allowed}
    kept = [by_norm[_norm(o)] for o in picked if _norm(o) in by_norm]
    kept = list(dict.fromkeys(kept))[:3]
    return kept or allowed[:2]


def _email_body(lead: dict, e: _Email) -> str:
    name = recipient_first_name(lead) or NAME_PLACEHOLDER
    bullets = lambda items: "\n".join(f"- {_clean(i).lstrip('-• ').rstrip('.')}" for i in items)
    return "\n\n".join([
        f"Hi {name},",
        "Hope you're doing well.",
        _clean(e.context),
        _clean(e.about),
        "Our capabilities include:\n" + bullets(e.capabilities[:5]),
        _clean(e.fit),
        "A few relevant outcomes:\n" + bullets(_outcomes(lead, e.outcomes)),
        _clean(e.cta),
        _footer(),
    ])


def assemble(lead: dict, drafts: _Drafts) -> dict:
    source = lead.get("source") or DEFAULT_SOURCE
    rules = SOURCE_RULES.get(source, SOURCE_RULES[DEFAULT_SOURCE])
    emails = drafts.emails[:2] if source == "linkedin_job" else drafts.emails[:1]
    return {
        "source": source,
        "source_label": SOURCES.get(source, {}).get("label", source),
        "recipient": recipient_first_name(lead),
        "to": (lead.get("recipient") or {}).get("email") or lead.get("contact_email") or "",
        "emails": [
            {"angle": _clean(e.angle), "subject": _clean(e.subject).rstrip("."),
             "body": _email_body(lead, e)}
            for e in emails
        ],
        "response": {"label": rules["response_label"], "text": _clean(drafts.response)},
    }


# ─── Public API ───────────────────────────────────────────────────────────────
def draft_outreach(lead: dict, api_key: str, model: str = MODEL, client=None) -> dict:
    """Generate the email(s) + direct response for one lead dict (card payload)."""
    if client is None:
        from google import genai
        from google.genai import types
        # No default timeout in the SDK: one stalled request would hang the card forever.
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60_000))
    system, user = build_prompt(lead)
    models = [model] + ([FALLBACK_MODEL] if FALLBACK_MODEL and FALLBACK_MODEL != model else [])
    for i, m in enumerate(models):
        try:
            resp = client.models.generate_content(
                model=m,
                contents=user,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": _Drafts,
                    "system_instruction": system,
                    "temperature": 0.8,   # variety reads human; facts are pinned by the prompt
                },
            )
            break
        except Exception as e:  # noqa: BLE001
            busy = any(c in str(e) for c in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                                            "504", "DEADLINE_EXCEEDED"))
            if not busy:
                raise
            if i == len(models) - 1:
                raise RuntimeError("Gemini is overloaded right now, try again in a minute.") from e
    drafts = _Drafts.model_validate_json(resp.text or "{}")
    if not drafts.emails:
        raise ValueError("model returned no email")
    return assemble(lead, drafts)
