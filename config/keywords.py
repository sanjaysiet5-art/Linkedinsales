"""
Auto-curated keyword library for Grapesworldwide agency sales prospecting.
9 services: Branding & Designing · AI/3D/CGI · Films & Campaigns ·
            Social Media & Content Strategy · Website Design & Dev · SEO ·
            Media Planning & Buying · PR & Influencer Marketing · Events & Activations

Keywords are crafted as phrases a brand's marketing team would ACTUALLY POST on LinkedIn
when they are seeking to hire an external agency — not generic industry content.
"""

GRAPES_KEYWORDS: dict[str, list[str]] = {

    # ── 01 Branding & Designing ──────────────────────────────────────────────
    "Branding & Designing": [
        "looking for agencies branding",
        "looking for agencies design",
        "looking to collaborate with an experienced branding agency",
        "looking to collaborate with an experienced design specialist",
        "Looking for boutique, India-based branding agencies",
        "Looking for boutique, India-based design agencies",
        "recommendations for a branding agency",
        "Can anyone recommend a good creative agency",
        "looking for a strategic creative partner",
        "hiring a creative agency for our launch",
        "inviting pitches from creative agencies",
        "accepting agency credentials for branding",
    ],

    # ── 02 AI/3D/CGI ─────────────────────────────────────────────────────────
    "AI/3D/CGI": [
        "looking for agencies AI",
        "looking for agencies 3D",
        "looking for agencies CGI",
        "looking to collaborate with an experienced AI agency",
        "looking to collaborate with an experienced CGI specialist",
        "Looking for boutique, India-based AI agencies",
        "Looking for boutique, India-based 3D animation agencies",
        "hiring a CGI or 3D production agency",
    ],

    # ── 03 Films & Campaigns ─────────────────────────────────────────────────
    "Films & Campaigns": [
        "looking for agencies video production",
        "looking for agencies ad campaigns",
        "looking to collaborate with an experienced film production agency",
        "looking to collaborate with an experienced campaign specialist",
        "Looking for boutique, India-based creative campaign agencies",
        "Looking for boutique, India-based video production agencies",
        "Can anyone recommend a good production house",
        "looking for agencies for an upcoming campaign pitch",
    ],

    # ── 04 Social Media & Content Strategy ───────────────────────────────────
    "Social Media & Content Strategy": [
        "looking for agencies social media",
        "looking for agencies content strategy",
        "looking to collaborate with an experienced social media agency",
        "looking to collaborate with an experienced content specialist",
        "Looking for boutique, India-based social media agencies",
        "Looking for boutique, India-based content marketing agencies",
        "recommendations for a social media agency",
        "looking for a retainer agency for social media",
        "looking to outsource our social media",
        "outsourcing SMO",
    ],

    # ── 05 Website Design & Development ──────────────────────────────────────
    "Website Design & Development": [
        "looking for agencies website design",
        "looking for agencies web development",
        "looking to collaborate with an experienced website design agency",
        "looking to collaborate with an experienced web development specialist",
        "Looking for boutique, India-based website development agencies",
        "looking to collaborate with a web development agency",
        "looking for an agency to build our website",
        "agency RFP for website redesign",
    ],

    # ── 06 SEO ───────────────────────────────────────────────────────────────
    "SEO": [
        "looking for agencies SEO",
        "looking to collaborate with an experienced SEO agency",
        "looking to collaborate with an experienced SEO specialist",
        "Looking for boutique, India-based SEO agencies",
        "recommendations for an SEO agency",
        "looking to outsource our SEO",
        "inviting pitches from SEO agencies",
    ],

    # ── 07 Media Planning & Buying ───────────────────────────────────────────
    "Media Planning & Buying": [
        "looking for agencies media planning",
        "looking for agencies media buying",
        "looking to collaborate with an experienced media planning agency",
        "looking to collaborate with an experienced performance marketing specialist",
        "Looking for boutique, India-based media buying agencies",
        "looking for recommendations for a performance marketing agency",
        "looking to partner with a growth agency",
        "looking for a digital marketing partner",
        "hiring an agency for performance marketing",
    ],

    # ── 08 PR & Influencer Marketing ─────────────────────────────────────────
    "PR & Influencer Marketing": [
        "looking for agencies PR",
        "looking for agencies influencer marketing",
        "looking to collaborate with an experienced PR agency",
        "looking to collaborate with an experienced influencer marketing specialist",
        "Looking for boutique, India-based PR agencies",
        "Looking for boutique, India-based influencer marketing agencies",
        "looking for an agency to handle our PR",
    ],

    # ── 09 Events & Activations ──────────────────────────────────────────────
    "Events & Activations": [
        "looking for agencies event management",
        "looking for agencies experiential marketing",
        "looking to collaborate with an experienced event activation agency",
        "Looking for boutique, India-based event management agencies",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Cross-service universal high-intent phrases
# These fire regardless of specific service — brand is clearly shopping for agency
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSAL_INTENT_KEYWORDS: list[str] = [
    "looking for digital agency",
    "digital agency recommendation",
    "need marketing agency",
    "agency for our brand",
    "invite agencies to pitch",
    "shortlisting agencies",
    "rfp marketing agency",
    "agency brief",
    "which agency should I hire",
    "recommend good agency",
    "evaluating agencies",
    "changing our agency",
    "new agency partner",
    "agency for our campaign",
    "full service agency",
    "360 degree agency",
    "integrated agency partner",
    "pitching to agencies",
    "agency onboarding",
    "recommendations for a digital agency",
    "Looking for introductions to top digital agencies",
    "looking to partner with a digital agency",
    "seeking a long term digital agency partner",
    "looking to hire a digital marketing agency",
    "floating an RFP for digital marketing",
    "hiring vendor",
    "creative agency RFP",
]

QUICK_SCAN_KEYWORDS: list[str] = [
    "looking for digital agency",
    "looking for digital marketing partner",
    "looking for marketing agency",
    "looking for branding agency",
    "looking for design agency",
    "looking for AI agency",
    "looking for 3D animation agency",
    "looking for CGI agency",
    "looking for video production agency",
    "looking for film production agency",
    "looking for creative campaign agency",
    "looking for social media agency",
    "looking for content marketing agency",
    "looking for website design agency",
    "looking for web development agency",
    "looking for SEO agency",
    "looking for performance marketing agency",
    "looking for media planning agency",
    "looking for media buying agency",
    "looking for PR agency",
    "looking for influencer marketing agency",
    "looking for event management agency",
    "looking for experiential marketing agency",
    "looking to partner with a digital agency",
    "looking to partner with a growth agency",
    "looking to collaborate with a branding agency",
    "looking to collaborate with a social media agency",
    "looking to collaborate with a web development agency",
    "looking for digital agencies",
    "recommendations for a digital agency",
]


def get_all_keywords() -> list[str]:
    """Return all keywords across all services + universal, deduplicated."""
    all_kw = list(UNIVERSAL_INTENT_KEYWORDS)
    for service_kws in GRAPES_KEYWORDS.values():
        all_kw.extend(service_kws)
    # Deduplicate preserving order
    seen = set()
    result = []
    for kw in all_kw:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            result.append(kw)
    return result


def get_keywords_for_service(service_name: str) -> list[str]:
    """Return keywords for a specific Grapesworldwide service."""
    for key, kws in GRAPES_KEYWORDS.items():
        if service_name.lower() in key.lower():
            return kws
    return list(UNIVERSAL_INTENT_KEYWORDS)


def get_service_list() -> list[str]:
    return list(GRAPES_KEYWORDS.keys())


# ─────────────────────────────────────────────────────────────────────────────
# EXCLUSION LISTS — used by the smart filter to strip false positives
# ─────────────────────────────────────────────────────────────────────────────

# Signals that the post is an INDIVIDUAL JOB OPENING — not agency hiring
JOB_POSTING_PHRASES: list[str] = [
    # Application triggers
    "apply now", "apply here", "apply via", "send your cv", "share your cv",
    "send your resume", "share your resume", "cover letter", "drop your cv",
    "dm your cv", "dm your resume", "email your cv", "apply at",
    # Role-based individual hiring
    "we are hiring a", "we're hiring a", "hiring for the role of",
    "job opening", "job opportunity", "career opportunity", "open position",
    "vacancy for", "urgently hiring", "immediate joining", "immediate joiner",
    "joining immediately", "walk-in interview", "walk in interview",
    "interview on", "shortlisting candidates",
    # Compensation indicators (job posts, not agency briefs)
    " lpa", " lakh ctc", "fixed ctc", "best ctc", "salary:", "package:",
    "stipend", "paid internship", "unpaid internship", "internship", "interns",
    # Experience/qualification requirements
    "years of experience required", "years experience required",
    "minimum experience", "bachelor's degree required", "mba required",
    "freshers welcome", "freshers can apply", "0-1 years", "1-2 years",
    "2-3 years experience", "recent graduate", "final-year student", "application link", "hiring intern",
    # Specific individual job titles (hiring individuals, not agencies)
    "social media executive", "social media manager job", "seo analyst job",
    "seo executive job", "content writer job", "graphic designer job",
    "web developer job", "copywriter job", "digital marketing executive",
    "performance marketing executive", "brand manager job",
    "marketing coordinator", "marketing intern",
]

# Signals that the post is POSTED BY AN AGENCY about their own work
# (we want posts FROM brands, not from agencies)
AGENCY_SELF_PROMO_PHRASES: list[str] = [
    "our agency", "at our agency", "join our agency", "we are a digital agency",
    "we are a creative agency", "we are an agency", "our agency delivered",
    "we helped our client", "case study:", "new case study", "our latest campaign",
    "behind the scenes of our work", "proud to have delivered",
    "our team created", "work we did for", "project we delivered",
    "award winning agency", "india's leading agency", "top digital agency",
    "our creative team", "agency of the year", "we build brands",
    "crafting digital experiences", "our campaigns speak",
    "let us help your brand", "reach out to us for", "dm us for a quote",
    "talk to our team", "book a free consultation", "free audit",
    "contact us for branding", "we specialize in", "our offerings",
]
