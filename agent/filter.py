"""
Precision filter for Grapesworldwide agency prospecting.

Goal: keep ONLY posts where a brand/company is ACTIVELY seeking to hire an
external agency/partner (RFP-style posts). Everything else — job posts,
agency self-promo, informational/thought-leadership content — is stripped.

Six-stage gate — a post must clear ALL stages to qualify:
  0. Agency-author gate   — reject posts AUTHORED BY agencies / freelancers /
                            service-sellers (uses Apify author name + headline)
  1. Article strip        — remove LinkedIn Pulse / article URLs
  2. Job posting check    — strip individual hiring posts
  3. Agency content check — strip agency self-promo / portfolio / industry advice
  4. Thought leadership   — strip educational/opinion posts by individuals
  5. Active-seeking gate  — the core intent detector. Requires one of:
       • RFP language          ("rfp", "request for proposal", "submit proposals")
       • Seek verb + provider  ("looking for … agency", "seeking … SEO experts",
                                "looking to collaborate with … agency/specialist")
       • Recommendation ask    ("agency recommendations", "recommend a … agency")
     Loose topical mentions ("we improved our SEO") no longer qualify.

Qualified posts are re-scored by intent strength:
  10  RFP / proposals invited
   9  Actively seeking agency/partner
   8  Asking for agency recommendations
  +1  direct CTA ("DM me", "share your company profile", "drop recommendations")
  +1  budget / project value mentioned                          (capped at 10)
"""

import re
from agent.parser import LinkedInPost
from agent.triage import is_positive, make_positive_signal
from agent.benchmark import similarity, make_benchmark_signal
from config.keywords import JOB_POSTING_PHRASES, AGENCY_SELF_PROMO_PHRASES

# Content-benchmark thresholds (cosine similarity vs relevant-marked posts).
# Calibrated against the IDEAL/NOISE corpus in tests/test_filter.py, where
# genuinely-matching posts score 0.11-0.22 and noise averages 0.06 (max 0.17):
#   BOOST  — post already passed the intent gates and reads like the benchmark;
#            low-risk (+1 score only), so it sits just above the noise mean
#   RESCUE — post cleared every rejection gate but had no explicit intent;
#            it can enter on resemblance alone, so the bar sits well above
#            the highest noise similarity ever observed.
# RESCUE was raised 0.30 → 0.40 after the marketing-service gate was added to
# classify_intent: the gate now rejects vague seekers, so the benchmark must be
# extra-confident before it overrides that verdict on resemblance alone.
BENCHMARK_BOOST_SIM = 0.12
BENCHMARK_RESCUE_SIM = 0.40


# ─── Gate 0: posts AUTHORED BY agencies / service-sellers ─────────────────────
# Company authors whose NAME identifies them as a marketing-service provider.
_AGENCY_AUTHOR_NAME = re.compile(
    r"\b(?:agency|agencies|marketing|seo|smm|ppc|branding|advertis\w*|creative|"
    r"design|studio|media|digital|web\s*design|web\s*dev\w*|link\s*build\w*|"
    r"lead\s*gen\w*|growth\s*hack\w*|communications)\b",
    re.IGNORECASE,
)

# Person authors whose HEADLINE identifies them as a freelancer/consultant/seller.
# A "Founder | SEO, growth, traffic" headline is a service-seller; a brand-side
# marketer ("Marketing Head at Nykaa") is not.
#
# Includes non-marketing service-sellers too: recruitment/staffing/workforce
# firms (Raju Rai — "Workforce Solutions"), NGO/funding publishers (fundsforNGOs
# — "Helping Nonprofits Discover Funding Opportunities"). A brand "looking for a
# partner" sounds like a lead, but a staffing firm or grant publisher posting
# that is selling their OWN service, not buying ours.
_PERSON_SELLER_HEADLINE = re.compile(
    r"(?:freelanc\w+|i\s+help\b|helping\s+(?:indian\s+)?(?:brands|businesses|companies|founders|agencies|"
    r"nonprofits|ngos|foundations|donors|organizations|organisations)|"
    r"helping\s+\w+\s+(?:discover|find|connect|navigate|unlock|grow)|"
    r"\bexperts?\b|\bspecialists?\b|\bconsultants?\b|\bcoach\b|\bfractional\b|"
    r"\bagenc(?:y|ies)\b|\bstudio\b|"
    r"(?:founder|co-founder|owner|ceo|partner)\b[^.]*?\b(?:seo|smm|ppc|branding|advertis\w*|"
    r"growth|traffic|leads?\s+gen\w*|leads?\b|revenue|web\s*design|marketing|paid\s+media|paid\s+social|programmatic)|"
    r"\b(?:ppc|paid\s+social|programmatic|paid\s+media|paid\s+search)\b|"
    r"\bseo\s+services\b|\blink\s+building\b|\bguest\s+post\w*|"
    # Recruitment / staffing / workforce sellers
    r"\bstaffing\b|\brecruit(?:er|ing|ment)\b|\bworkforce\s+solutions?\b|"
    r"\btalent\s+(?:solutions?|partner|agency)\b|\bexecutive\s+search\b|"
    r"\bmanpower\b|\bplacement\s+(?:agency|services?)\b|"
    r"dm\s+(?:me\s+)?(?:for|to)\s+collab\w*|open\s+for\s+projects?)",
    re.IGNORECASE,
)


def is_agency_author(post: LinkedInPost) -> bool:
    """A service-seller can't be a prospect, no matter what they post."""
    if post.entity_type == "brand":
        return bool(_AGENCY_AUTHOR_NAME.search(post.author_name or ""))
    ident = f"{post.author_name or ''} {post.author_headline or ''}"
    return bool(_PERSON_SELLER_HEADLINE.search(ident))


# ─── Gate 5 building blocks: active-seeking detection ─────────────────────────
_SEEK_VERBS = (
    r"(?:looking\s+for|looking\s+to\s+(?:connect|collaborate|work|partner|team\s+up)(?:\s+with)?|"
    r"looking\s+to\s+(?:hire|engage|onboard|appoint)|"
    r"seeking|in\s+search\s+of|searching\s+for|scouting\s+for|on\s+the\s+hunt\s+for|"
    r"we\s+need|need\s+(?:a|an)|want\s+to\s+(?:hire|engage|onboard)|"
    r"open\s+to\s+(?:proposals|pitches)|inviting|shortlisting|evaluating)"
)

_AGENCY_NOUNS = r"(?:agenc(?:y|ies)|firms?|studios?|vendors?|providers?|partners?)"

_SERVICE_TERMS = (
    r"(?:seo|sem|smm|ppc|marketing|branding|brand|design|development|dev|web|website|"
    r"digital|creative|media|pr|public\s+relations|advertising|social\s+media|content|"
    r"video|film|production|e-?commerce|ui|ux|app|performance|influencer|"
    r"communications?|marketplace|software|it|event|google\s+ads|ads|adwords)"
)

_SERVICE_TERMS_RE = re.compile(rf"\b{_SERVICE_TERMS}\b", re.IGNORECASE)

# ─── Marketing-service gate (the precision fix) ───────────────────────────────
# _SERVICE_TERMS above is deliberately BROAD (includes "software", "it", "app",
# "digital" alone) so the loose scorer can tag topical signals. But the INTENT
# gate must only fire on a real marketing/creative/digital service — the 9 lines
# Grapesworldwide actually sells. Without this gate, "looking for ... partner"
# matches (fundsforNGOs: "looking for ... the right partner"), "looking to connect
# with ... partners" matches (Justin Gordon's co-founder hunt), and "looking for
# a workforce partner" matches (Raju Rai's staffing pitch).
#
# "digital" alone is excluded — it fires on "digital landscape", "digital
# footprint", "digital security". It only counts as the compound "digital
# marketing" / "digital agency".
_MARKETING_SERVICE_TERMS = (
    r"(?:seo|sem|smm|ppc|branding|brand|rebrand|design|"
    r"web\s*site|web\s*design|web\s*dev\w*|website|development|"
    r"social\s*media|content\s*marketing|content\s*strategy|"
    r"influencer|pr\b|public\s+relations|press|"
    r"media\s+planning|media\s+buying|performance\s+marketing|paid\s+search|paid\s+social|"
    r"google\s+ads|meta\s+ads|adwords|advertis\w*|ad\s+film|tvc|"
    r"video\s+production|film\s+production|3d|cgi|animation|"
    r"event\s+management|experiential|activations?|"
    r"digital\s+marketing|digital\s+agency|marketing\s+agency|creative\s+agency)"
)

_MARKETING_SERVICE_RE = re.compile(rf"\b{_MARKETING_SERVICE_TERMS}\b", re.IGNORECASE)

_GENERIC_PROVIDER_NOUNS = (
    r"(?:compan(?:y|ies)|teams?|experts?|specialists?|freelancers?|consultants?|"
    r"professionals?|solution\s+providers?|service\s+providers?|development\s+partners?)"
)

# Token separator that CANNOT cross a sentence boundary — otherwise
# "Looking for guest posts? I help SEO agencies…" matches "looking for … agencies"
_SEP = r"[^\w\n.!?]+"

# "looking for … agency" with a MARKETING SERVICE co-occurring in the same window.
# The service term may appear BEFORE or AFTER the agency noun. This gate is what
# stops "looking for funding agencies", "looking for a workforce partner", and
# "looking to connect with partners" (tech co-founder hunt) from matching — none
# of those carry a marketing-service term in the seek clause.
# Pattern A: service then noun — "looking for an SEO agency"
# Pattern B: noun then service — "looking for an agency for our SEO"
_SEEK_AGENCY_SERVICE = re.compile(
    rf"(?:"
    rf"{_SEEK_VERBS}{_SEP}(?:[\w/&'’-]+{_SEP}){{0,8}}?{_MARKETING_SERVICE_TERMS}{_SEP}(?:[\w/&'’-]+{_SEP}){{0,6}}?{_AGENCY_NOUNS}"
    rf"|"
    rf"{_SEEK_VERBS}{_SEP}(?:[\w/&'’-]+{_SEP}){{0,6}}?{_AGENCY_NOUNS}(?:{_SEP}[\w/&'’-]+){{0,6}}?{_SEP}{_MARKETING_SERVICE_TERMS}"
    rf")",
    re.IGNORECASE)

# Legacy fallback — a bare agency noun WITH NO service term. Kept ONLY as a
# secondary signal: it must co-occur with a strong RFP/CTA/budget cue in the
# same post (checked in classify_intent, not here). On its own it matches far
# too much ("funding agencies", "government agencies", "recruitment agency").
_SEEK_AGENCY = re.compile(
    rf"{_SEEK_VERBS}{_SEP}(?:[\w/&'’-]+{_SEP}){{0,10}}?{_AGENCY_NOUNS}", re.IGNORECASE)

# "looking for … SEO experts / development companies" — service term + generic provider noun
_SEEK_SERVICE_PROVIDER = re.compile(
    rf"{_SEEK_VERBS}{_SEP}(?:[\w/&'’-]+{_SEP}){{0,10}}?{_SERVICE_TERMS}{_SEP}{_GENERIC_PROVIDER_NOUNS}",
    re.IGNORECASE)

# "recommend a good SEO agency" / "agency recommendations" (both directions)
_RECOMMEND_ASK = re.compile(
    rf"(?:recommend\w*{_SEP}(?:[\w/&'’-]+{_SEP}){{0,10}}?(?:{_AGENCY_NOUNS}|{_SERVICE_TERMS}{_SEP}{_GENERIC_PROVIDER_NOUNS})|"
    rf"(?:{_AGENCY_NOUNS}|{_SERVICE_TERMS}){_SEP}recommendations?|"
    r"drop\s+(?:your\s+)?recommendations?|any\s+recommendations?)",
    re.IGNORECASE)

# RFP must be in ISSUING context. A bare "rfp" token also matches advice and
# war stories ("how to win RFPs", "an RFP landed on my desk") — those are noise.
_RFP = re.compile(
    r"(?:issu(?:es?|ed|ing)\s+(?:an?\s+)?#?rfp|releas(?:es?|ed|ing)\s+(?:an?\s+)?#?rfp|"
    r"#?rfp\s+(?:is\s+)?(?:out|live|open)\b|#?rfps?\s+for\s+#?\w|"
    r"(?:our|we\s+have\s+an?|we\s+issued\s+an?|we\s+are\s+issuing\s+an?|we['’]?re\s+issuing\s+an?)\s+rfp|"
    r"rfp\s+attached|see\s+(?:the\s+)?rfp|respond\s+to\s+(?:our|this)\s+rfp|"
    r"request\s+for\s+proposals?|call\s+for\s+proposals?|"
    r"invit\w+\s+(?:proposals?|agencies\s+to\s+pitch)|submit\s+(?:your\s+)?proposals?|"
    r"share\s+your\s+(?:proposal|quotation|quote)|expression\s+of\s+interest|"
    # bare "agency brief" also appears in think pieces ("it owns the agency brief")
    r"(?:our|sharing\s+the|share\s+the|download\s+the)\s+agency\s+brief|"
    r"agency\s+brief\s+(?:attached|below|is\s+(?:out|live|ready))|"
    r"vendor\s+(?:shortlist|evaluation|empanelment)|empanelment\s+of\s+agencies)",
    re.IGNORECASE)

_CTA = re.compile(
    r"(?:dm\s+me|drop\s+(?:a\s+|me\s+a\s+)?dm|dm\s+us|send\s+(?:me|us)\b|"
    r"share\s+your\s+(?:company\s+profile|portfolio|proposal|work|credentials|deck|profile)|"
    r"reach\s+out|get\s+in\s+touch|drop\s+your\s+recommendations?|in\s+the\s+comments)",
    re.IGNORECASE)

_BUDGET = re.compile(
    r"(?:[$₹€£]\s?\d|usd|inr|aed|budget|project\s+value|estimated\s+(?:project\s+)?value)",
    re.IGNORECASE)

# Seller voice: the post SELLS a service to the reader ("Looking for an SEO
# agency? WE help your website climb…"). A rhetorical seek-hook followed by
# second-person pitching. 2+ hits → agency content.
_SELLER_VOICE = re.compile(
    r"(?:we\s+help\s+(?:you|your)\b|\bi\s+help\b|\bi\s+offer\b|"
    r"your\s+(?:website|brand|business)\s+(?:climb|grow|rank|scale)|"
    r"grow\s+your\s+(?:website|brand|business|authority)|"
    r"let['’]?s\s+grow\s+your|let['’]?s\s+make\s+it\s+happen|ready\s+to\s+(?:grow|scale|rank|dominate)|"
    r"book\s+a\s+(?:call|demo|free)|call\s+us|dm\s+us|contact\s+us|send\s+me\s+a\s+message|"
    r"our\s+(?:services|packages|pricing|portfolio)|we\s+(?:offer|provide|deliver)\b|"
    r"affordable\s+pric\w+|fast\s+turnaround|money-?back\s+guarantee|"
    r"guest\s+post\w*|do-?follow\s+links?|high\s+dr\b|niche\s+edits?|"
    r"telegram\s*:|whats?app\s*:|"
    r"you\s+need\s+to\s+be\s+on\s+top|📞|☎|\+\d{1,3}\s?\(?\d{1,})",
    re.IGNORECASE)

# Partner/reseller recruitment: a company recruiting agencies as CHANNEL
# PARTNERS for its own product — the reverse of a brand hiring an agency.
# 2+ hits → agency content. (A single "white-label" mention stays allowed:
# genuine RFPs describe wanted solutions that way.)
_PARTNER_RECRUITMENT = re.compile(
    r"(?:partner\s+with\s+us|why\s+partner\s+with|who\s+can\s+partner|"
    r"revenue\s+shar\w+|referral\s+partners?|channel\s+partners?|\bresellers?\b|"
    r"affiliate\s+program|grow\s+with\s+us|earn\s+commissions?|"
    r"co-?marketing|white-?label\s+(?:&|and)\s+enterprise|"
    r"for\s+(?:your|their)\s+clients)",
    re.IGNORECASE)

# A seek match that is actually an individual job hire ("…expert to join our team")
_JOB_CONTEXT = re.compile(
    r"(?:to\s+join\s+(?:a|our|the)\b|join\s+our\s+team|full[\s-]?time|part[\s-]?time|in[\s-]?house|"
    r"work\s+from\s+office|on[\s-]?site\s+role|this\s+(?:position|role)|open\s+(?:position|role)|"
    r"remote\s+opportunit(?:y|ies)|hybrid\s+opportunit(?:y|ies)|job\s+alert|we\s?['’]?a?re\s+hiring|"
    r"candidates?|apply\b|send\s+(?:your\s+)?(?:cv|resume)|internship\b|interns?\b|graduates?\b|students?\b)",
    re.IGNORECASE)

# Freelancers/job-seekers advertising their OWN availability — the supply side
# of the market ("I'm a UX/UI Designer actively looking for remote freelance
# projects"). One strong hit, or two weak ones, marks the post.
_FREELANCER_STRONG = re.compile(
    r"(?:(?:actively\s+)?looking\s+for\s+(?:remote\s+|freelance\s+|contract[\s-]*(?:based\s+)?|new\s+)*"
    r"(?:freelance|contract)[\s-]*(?:projects?|work|gigs?|opportunities|roles?)|"
    r"available\s+for\s+(?:freelance|hire|new\s+projects?)|open\s+to\s+work\b|"
    r"i['’]?m\s+open\s+to\s+(?:remote|freelance|contract)|"
    r"seeking\s+(?:remote\s+)?(?:freelance|contract)\s+(?:work|projects?|opportunities))",
    re.IGNORECASE)

_FREELANCER_WEAK = re.compile(
    r"(?:i['’]?m\s+an?\s+(?:[\w/&-]+\s+){0,3}?(?:designer|developer|writer|copywriter|marketer|"
    r"editor|animator|videographer|photographer|freelancer|virtual\s+assistant)|"
    r"my\s+(?:areas\s+of\s+)?expertise|collaboration\s+opportunities|"
    r"how\s+i\s+can\s+contribute|long-?term\s+remote|"
    r"(?:check\s+out\s+)?my\s+portfolio|telegram\s*:|whats?app\s*:)",
    re.IGNORECASE)

# Rhetorical hooks used by service sellers: "If you're looking for...", "Are you looking to hire..."
_RHETORICAL_SEEK = re.compile(
    r"(?:if\s+you['’]?re|whether\s+you['’]?re|are\s+you)\s+[^\n.!?]{0,60}?(?:looking\s+for|seeking|searching|scouting|hunting|in\s+need\s+of|looking\s+to)\b",
    re.IGNORECASE
)

# Co-founder / talent hunts dressed up as "looking to connect with partners".
# These name engineers/researchers/developers, not marketing services — a tech
# founder recruiting collaborators is the opposite of a brand buying agency work.
# (Justin Gordon: "looking to connect with potential partners … developers, AI
# researchers, cybersecurity experts, strategists".)
_COFOUNDER_HUNT = re.compile(
    r"(?:looking\s+to\s+(?:connect|collaborate)[^\n.!?]{0,60}?"
    r"(?:co[-\s]?found\w+|developers?|engineers?|researchers?|scientists?|"
    r"cybersecurity|strategists?|coders?|programmers?|designers?|product\s+managers?|"
    r"visionaries|innovators|builders|hackers)"
    rf"|{_SEP}(?:developers?|engineers?|researchers?|scientists?|cybersecurity|strategists?|"
    r"visionaries|innovators|builders)[^\n.!?]{{0,80}}?looking\s+to\s+(?:connect|collaborate))",
    re.IGNORECASE,
)

# First-person war stories about OTHER people's agency hunts ("a brand just told
# me they're looking for an SEO agency…") — content marketing, not a lead.
_STORY_CONTEXT = re.compile(
    r"(?:told\s+(?:me|us)|asked\s+me|reached\s+out\s+to\s+(?:me|us)\b|"
    r"got\s+in\s+touch\s+(?:with\s+(?:me|us)\s+)?last|messaged\s+me|dm['’]?e?d\s+me|"
    r"in\s+(?:his|her|their)\s+new\s+blog|you\s+are\s+the\s+\w+\s+manager|imagine\s+you)",
    re.IGNORECASE)


def classify_intent(post: LinkedInPost) -> dict | None:
    """
    Detect active brand-seeking-agency intent. Returns a moment-signal dict
    with the computed intent score, or None if the post has no such intent.

    Two match paths, in priority order:
      PRIMARY  — service-gated seek: a seek verb + an agency/provider noun +
                 a MARKETING service term all in the same clause. This is the
                 precision path; it requires the post to actually name a
                 service Grapesworldwide sells.
      SECONDARY — bare agency seek + a strong RFP/CTA/budget cue elsewhere in
                 the post. Genuine RFPs occasionally name no service ("we're
                 issuing an RFP for our marketing, see attached brief") and
                 must still be caught — but only when a strong cue co-occurs.

    Definitive Match Targets (Always capture via PRIMARY):
      i) "looking for agencies <services>"
     ii) "looking to collaborate with an experienced <services> agency/specialist"
    iii) "Looking to partner with <service> agencies"
    """
    text = _text(post)

    if _RHETORICAL_SEEK.search(text):
        # Rhetorical seek-hook from a seller (e.g. "If you're looking for...")
        return None

    if _COFOUNDER_HUNT.search(text):
        # "looking to connect with … developers/researchers" — tech co-founder hunt
        return None

    if _JOB_CONTEXT.search(text):
        # "…expert to join our team", "apply now" — an individual hire, not an RFP
        return None
    if _STORY_CONTEXT.search(text):
        # First-person anecdote about someone ELSE seeking an agency
        return None

    # The broad service-term check stays (topical pre-filter), but the PRIMARY
    # path below requires a marketing-specific term — the precision gate.
    if not _SERVICE_TERMS_RE.search(text):
        return None

    # Justin Gordon leak fix: a tech-founder "looking to connect with partners"
    # post mentions digital/software/AI but NO marketing service. Require at
    # least one marketing-service term anywhere in the post for either path.
    if not _MARKETING_SERVICE_RE.search(text):
        return None

    primary = bool(_SEEK_AGENCY_SERVICE.search(text) or _SEEK_SERVICE_PROVIDER.search(text))
    secondary = False
    if not primary:
        # Bare agency noun is only trustworthy when a strong RFP cue backs it
        # up — not a generic "DM me" CTA (which any pitch post contains).
        if _SEEK_AGENCY.search(text) and (_RFP.search(text) or _BUDGET.search(text)):
            secondary = True

    # TERTIARY — "can anyone recommend a good SEO agency" / "agency
    # recommendations". Scored 8 per the module docstring; the marketing-service
    # gate above has already run, so "recommend a staffing agency" can't fire.
    recommend = not (primary or secondary) and bool(_RECOMMEND_ASK.search(text))

    if not (primary or secondary or recommend):
        return None

    if _RFP.search(text):
        base, label, icon = 10, "RFP / Proposals Invited", "📋"
    elif recommend:
        base, label, icon = 8, "Asking for Agency Recommendations", "🙋"
    else:
        base, label, icon = 9, "Actively Seeking Agency Partner", "🚨"

    matched = []
    if _CTA.search(text):
        base += 1
        matched.append("direct CTA")
    if _BUDGET.search(text):
        base += 1
        matched.append("budget mentioned")

    return {
        "id": "active_agency_seek",
        "label": label,
        "icon": icon,
        "score": min(base, 10),
        "matched_keywords": matched,
        "service_tags": [],
    }


# ─── Legacy phrase lists still used by gates 3-4 ──────────────────────────────
# Person posts can be rescued from the thought-leadership gate if they
# explicitly speak for their brand.
PERSON_BRAND_INTENT: list[str] = [
    "we are looking", "we're looking", "we are seeking", "we're seeking",
    "we need a", "we need an", "our company needs", "our brand needs",
    "our business needs", "my company is looking", "my company needs",
    "our team is looking", "we are evaluating", "we're evaluating",
    "our brand is seeking", "for our company", "for our brand",
    "our upcoming campaign", "for our launch", "our agency search",
    "we're changing", "we are changing our agency", "recommend for our",
    "we're onboarding a new agency",
    "we have an rfp", "we issued an rfp", "our rfp", "we've issued",
    "our company has an rfp", "we are issuing", "we're issuing",
]

# ─── Agency portfolio / completed-work showcase phrases (Gate 3, 1-hit) ────────
AGENCY_PORTFOLIO_PHRASES: list[str] = [
    "our work for",
    "we helped bring",
    "read more about our work",
    "proud to share this project",
    "proud to share our work",
    "excited to share this project",
    "as part of the rebrand, we",
    "as part of the project, we",
    "we translated the identity",
    "we designed for",
    "we created for",
    "we built for",
    "we delivered for",
    "for our client,",
    "congrats to our client",
    "congratulations to our client",
    "on the launch of their new brand",
    "on the launch of their brand",
    "on their new brand launch",
    "on this rebrand",
    "view our case study",
    "see our case study",
    "full case study",
    "project showcase",
    "work showcase",
    "portfolio piece",
]

# ─── Agency-industry thought leadership (Gate 3, 1-hit) ──────────────────────
AGENCY_THOUGHT_LEADERSHIP: list[str] = [
    "every agency should", "agencies should", "agency should",
    "agency owners", "for agency owners", "agency founders",
    "tips for agencies", "agency tips", "agency best practices",
    "how agencies", "what agencies", "why agencies",
    "agency growth", "grow your agency", "run your agency",
    "agency model", "agency pricing", "agency process",
    "agency retention", "client retention for agencies",
    "agency onboarding",
    "things every agency", "things agencies",
    "agency playbook", "agency framework",
    "things to look for when hiring",
    "what to look for in an agency",
    "how to choose an agency",
    "before hiring an agency",
    "questions to ask your agency",
    "questions to ask before hiring",
    "red flags when choosing", "red flags in an agency",
    "guide to hiring an agency", "checklist for hiring",
    "how to evaluate an agency", "how to vet an agency",
    "signs of a bad agency", "when choosing a marketing agency",
    "state of digital marketing", "future of agencies",
]

# ─── Individual thought leadership / educational content (Gate 4, person-only) ─
INDIVIDUAL_THOUGHT_LEADERSHIP: list[str] = [
    # Educational opener phrases
    "here's how it", "here's what it", "here's why it",
    "here's the mechanism", "here's the process", "here's the truth",
    "here's a breakdown", "here's a thread", "here's what most",
    "here's how most", "here's the thing most",
    "in plain terms", "in simple terms", "in plain english",
    "let me break down", "let me explain", "allow me to explain",
    "breaking it down", "a quick breakdown",
    # "Most people X" — hallmark of thought leadership
    "most people miss", "most people don't know", "most people think",
    "most people get", "most people never", "most people overlook",
    "most people fail", "most people are wrong", "most people don't realize",
    "the bridge most people", "what most people miss",
    "most companies that", "most companies hire", "most companies don't",
    "most brands that", "most brands don't", "most founders",
    # Consultant / advisor self-identification
    "i help companies", "i help businesses", "i help brands",
    "helping businesses get", "helping companies get", "helping brands get",
    "helping business owners", "i work with businesses",
    "my clients often", "my clients ask", "in my experience working",
    "in my years of", "after working with",
    # Personal story / experience framing
    "i've sat in", "i've been in", "i've worked in",
    "i've seen this", "i've watched", "i remember when",
    "in my last", "in my previous role",
    # Pattern-observation storytelling
    "i keep finding", "i keep seeing", "i keep hearing",
    "i keep noticing", "i keep running into",
    "i asked a", "i asked her", "i asked him",
    "she said no", "he said no", "they said no",
    "then we pulled", "then i pulled",
    "a digital marketing agency owner", "a marketing agency owner",
    "an agency owner i", "agency owner i talked",
    "government procurement", "naics codes", "naics code",
    "solicitation data", "open rfps", "rfps landed",
    "the companies that qualify", "the vocabulary is the gap",
    # Brand consultant / strategist content
    "i build brand", "i build brands", "brand operating system",
    "brand strategy for", "brand clarity", "brand audit",
    # Free tool / giveaway framing
    "so you don't have to pay", "save yourself", "for free",
    "minute brand audit", "quick brand audit", "free brand",
    "free seo", "free marketing", "free audit",
    "answer these questions", "answer these", "yes or no only",
    # Newsletter / personal brand promotion
    "view my newsletter", "get my newsletter", "subscribe to my",
    "ps. get tips", "ps: get tips", "my newsletter",
    "follow for more", "like and share", "repost if you agree",
    "save this post", "save this for later",
    # Opinion / hot-take framing
    "unpopular opinion", "hot take:", "controversial take",
    "i'm generous", "generous like that",
    "truth about seo", "truth about marketing", "truth about digital",
    "myth about seo", "myth about marketing",
    "nobody talks about this", "most marketers don't",
    # Explainer content
    "it's called rag", "retrieval-augmented generation",
    "here's how rag", "here's how ai",
    # Listicle from individual
    "here are the", "here are some", "here are my",
    # Personal story framing
    "i've been flown", "i was flown",
    "rebrands fail", "rebrand fails", "rebrands don't",
]

# Regex patterns
_INDIVIDUAL_ROLE_PATTERN = re.compile(
    r"(?:looking for|hiring|need)\s+(?:a|an)\s+"
    r"(?:senior\s+|junior\s+|experienced\s+)?"
    r"(?:social media|seo|content|graphic|web|ui|ux|performance|digital marketing|"
    r"brand|marketing|pr|copywriter|designer|developer|analyst|executive|manager|"
    r"coordinator|intern|specialist|strategist)\s*"
    r"(?:executive|manager|analyst|specialist|coordinator|intern|officer|associate|"
    r"head|lead|expert|professional|person|individual|consultant)?",
    re.IGNORECASE,
)

_SALARY_PATTERN = re.compile(
    r"\b(?:\d+[\s\-]+\d*\s*lpa|\d+\s*lakh|\d+k\s*(?:per|\/)\s*month|"
    r"salary\s*:\s*|\bctc\b|fixed\s+salary|gross\s+salary)\b",
    re.IGNORECASE,
)

_ARTICLE_URL_PATTERN = re.compile(r"linkedin\.com/pulse/", re.IGNORECASE)


def _text(post: LinkedInPost) -> str:
    return f"{post.title} {post.snippet}".lower()


# ─── Gate 1 ───────────────────────────────────────────────────────────────────
def is_article(post: LinkedInPost) -> bool:
    return bool(_ARTICLE_URL_PATTERN.search(post.url)) or post.entity_type == "article"


# ─── Gate 2 ───────────────────────────────────────────────────────────────────
def is_job_posting(post: LinkedInPost) -> bool:
    text = _text(post)
    for phrase in JOB_POSTING_PHRASES:
        if phrase in text:
            return True
    if _SALARY_PATTERN.search(text):
        return True
    # Freelancer/job-seeker advertising their own availability
    if _FREELANCER_STRONG.search(text) or len(_FREELANCER_WEAK.findall(text)) >= 2:
        return True
    if _INDIVIDUAL_ROLE_PATTERN.search(text):
        # Rescue only if the post also actively seeks an agency/provider
        if _SEEK_AGENCY.search(text) or _SEEK_SERVICE_PROVIDER.search(text) or _RFP.search(text):
            return False
        return True
    return False


# ─── Gate 3 ───────────────────────────────────────────────────────────────────
def is_agency_content(post: LinkedInPost) -> bool:
    text = _text(post)

    # a) Self-promo: 2+ generic hits (avoids false positives)
    promo_hits = sum(1 for phrase in AGENCY_SELF_PROMO_PHRASES if phrase in text)
    if promo_hits >= 2:
        return True

    # b) Portfolio / case study showcase: 1 hit is unambiguous
    for phrase in AGENCY_PORTFOLIO_PHRASES:
        if phrase in text:
            return True

    # c) Agency-industry thought leadership: 1 hit
    for phrase in AGENCY_THOUGHT_LEADERSHIP:
        if phrase in text:
            return True

    # d) Seller voice: pitches the reader ("we help your website climb…")
    if len(_SELLER_VOICE.findall(text)) >= 2:
        return True

    # e) Partner/reseller recruitment ("partner with us", "revenue sharing")
    if len(_PARTNER_RECRUITMENT.findall(text)) >= 2:
        return True

    return False


# ─── Gate 4 ───────────────────────────────────────────────────────────────────
def is_individual_thought_leadership(post: LinkedInPost) -> bool:
    if post.entity_type != "person":
        return False
    text = _text(post)
    for phrase in INDIVIDUAL_THOUGHT_LEADERSHIP:
        if phrase in text:
            # Rescue only if the post carries explicit seeking intent
            if any(strong in text for strong in PERSON_BRAND_INTENT):
                return False
            if _RFP.search(text) or _SEEK_AGENCY.search(text):
                return False
            return True
    return False


# ─── Master filter ─────────────────────────────────────────────────────────────
def apply_smart_filter(posts: list[LinkedInPost],
                       positive: dict | None = None) -> tuple[list[LinkedInPost], dict]:
    """
    Six-gate precision filter (see module docstring).

    positive — optional signals from triage.load_positive_signals(). Posts whose
    author/company was previously marked relevant by the NBD team bypass all
    rejection gates: with fresh seeking intent they score intent+1 (capped 10);
    without, they still qualify at a floor of 6 so the team sees repeat activity
    from known-good leads. Such posts carry post.positive_match = True and a
    ⭐ "Previously Marked Relevant" signal.

    positive["benchmark"] additionally scores every candidate's CONTENT against
    the text of relevant-marked posts (agent/benchmark.py):
      • sim ≥ BENCHMARK_BOOST_SIM on an intent-qualified post → +1 score + 📈 signal
      • sim ≥ BENCHMARK_RESCUE_SIM on a post that cleared all rejection gates but
        had no explicit intent → included at a floor of 6 with the 📈 signal
        (and positive_match = True, exempting it from the min-score cut).
    """
    benchmark = (positive or {}).get("benchmark")
    stats = {
        "total_in":           len(posts),
        "agency_authors":     0,
        "articles":           0,
        "job_posts":          0,
        "agency_content":     0,
        "thought_leadership": 0,
        "no_intent":          0,
        "positive_included":  0,
        "benchmark_boosted":  0,
        "benchmark_rescued":  0,
        "passed":             0,
    }
    qualified = []

    for post in posts:
        # Positive filter: the NBD team's judgment outranks the regex gates.
        if positive and is_positive(post, positive):
            intent = classify_intent(post)
            if intent:
                post.intent_score = min(intent["score"] + 1, 10)
                post.moment_signals = [intent, make_positive_signal()] + post.moment_signals
            else:
                post.intent_score = max(post.intent_score, 6)
                post.moment_signals = [make_positive_signal()] + post.moment_signals
            post.positive_match = True
            stats["positive_included"] += 1
            qualified.append(post)
            continue

        if is_agency_author(post):
            stats["agency_authors"] += 1
            continue
        if is_article(post):
            stats["articles"] += 1
            continue
        if is_job_posting(post):
            stats["job_posts"] += 1
            continue
        if is_agency_content(post):
            stats["agency_content"] += 1
            continue
        if is_individual_thought_leadership(post):
            stats["thought_leadership"] += 1
            continue

        intent = classify_intent(post)
        sim = similarity(_text(post), benchmark) if benchmark else 0.0

        if intent is None:
            # Content-benchmark rescue: no explicit seeking language, but the
            # post strongly resembles ones the team already marked relevant.
            if sim >= BENCHMARK_RESCUE_SIM:
                post.intent_score = max(post.intent_score, 6)
                post.benchmark_similarity = round(sim, 3)
                post.positive_match = True
                post.moment_signals = [make_benchmark_signal(sim)] + post.moment_signals
                stats["benchmark_rescued"] += 1
                qualified.append(post)
                continue
            stats["no_intent"] += 1
            continue

        # Intent strength drives the final score; topical signals stay for pitch tags
        post.intent_score = intent["score"]
        new_signals = [intent]
        if sim >= BENCHMARK_BOOST_SIM:
            post.intent_score = min(post.intent_score + 1, 10)
            post.benchmark_similarity = round(sim, 3)
            new_signals.append(make_benchmark_signal(sim))
            stats["benchmark_boosted"] += 1
        post.moment_signals = new_signals + post.moment_signals
        qualified.append(post)

    stats["passed"] = len(qualified)
    return qualified, stats
