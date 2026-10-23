"""
Outreach drafting config (agent/outreach.py) — the facts the drafter may use.

The model writes the personalised part of each email; it is only allowed to
cite proof points listed here, so it can't invent clients or numbers. Edit
this file to add case studies, change the signature, or add deck links.
Facts are taken from the team's sample outreach email (Sep 2026).
"""

import os

# ─── Sender (signature block appended to every email, never AI-written) ──────
SENDER = {
    "name":  os.getenv("OUTREACH_SENDER_NAME", "Sanjay Kumar"),
    "title": os.getenv("OUTREACH_SENDER_TITLE", "Director - Growth & AI"),
    "phone": os.getenv("OUTREACH_SENDER_PHONE", ""),    # blank = no Mobile line
    "email": os.getenv("OUTREACH_SENDER_EMAIL", "sanjay.kumar@grapesworldwide.com"),
}

# Links appended under the email body. Only real URLs — add the credentials
# deck / SEO case-study deck links here once they have shareable URLs.
LINKS = [
    ("Case studies", "https://www.grapesworldwide.com/case-study"),
    ("Three Zinc Studios", "https://threezinc.com/"),
]

# ─── Company facts (every email may use these) ────────────────────────────────
COMPANY_FACTS = """\
- Grapes Worldwide: creative, digital and AI agency, over 13 years in business.
- 250+ experts across Delhi, Mumbai, Bengaluru, London, Dubai, New Jersey and Australia.
- Philosophy "Genius Together": strategy with spark, creativity with commerce, human imagination with AI.
- 100% AI-enabled: every function (creative, social intelligence, SEO, tech, PR, media planning and buying) runs on the in-house AI lab "Raisin".
- Three Zinc: our AI studio (threezinc.com) for AI-led content, CGI and production at speed.
- Sectors: FMCG, Lifestyle, Beauty, Auto, Pharma, B2B, D2C.
- Brands worked with: Manforce, Dabur, Sujata Appliances, Vital Drinks (endorsed by Harry Kane), Louis Vuitton, Pay10, Unicharm Group, Flipkart, Jordan Oral Health, Acnestar, VIS School, Vibhor Cooking Oils.
"""

# ─── Per-service capabilities + proof points (pick by the card's service) ────
SERVICE_FACTS = {
    "SEO": {
        "capabilities": [
            "Branded search and search demand growth",
            "Technical SEO and e-commerce SEO",
            "Brand, product and category keyword growth",
            "Content strategy, digital PR and authority building",
            "AEO & GEO: visibility across ChatGPT, Google AI Overviews, Gemini, Claude and Perplexity",
            "Organic traffic, conversion and search growth tracking",
        ],
        "proof": [
            "250% organic traffic growth for Panasonic",
            "Built enterprise-level search authority for a niche B2B technology brand from scratch",
            "Authority-focused SEO for an FMCG brand in a competitive category",
        ],
    },
    "Social Media & Content Strategy": {
        "capabilities": [
            "Social strategy and always-on content calendars",
            "Shoot-based reels, UGC-led and creator content",
            "Community management and social listening (AI-driven social intelligence)",
            "Performance creatives for Meta and YouTube",
        ],
        "proof": [
            "Catch Foods Mother's Day film that went viral",
            "Manforce April Fools campaign",
            "Dabur Gulabari #SayItWithARose Valentine's Day film",
        ],
    },
    "Media Planning & Buying": {
        "capabilities": [
            "Paid media planning and buying across Meta, Google, YouTube and programmatic",
            "Performance marketing and lead generation",
            "Creative testing and ROAS optimisation",
            "Business-impact tracking and reporting",
        ],
        "proof": [
            "Worked with brands like Manforce, Dabur, Pay10, Flipkart and Unicharm Group",
        ],
    },
    "Branding & Designing": {
        "capabilities": [
            "Brand strategy, positioning and identity",
            "Packaging and communication design",
            "Brand films and launch campaigns",
            "Brand guidelines and design systems",
        ],
        "proof": [
            "Hindware #BrokenNotWaste outdoor innovation (Abby nominee)",
            "MamyPoko Pants 'Happy Bum' animated poem",
            "Built brand ecosystems for MamyPoko Extra Absorb, Acnestar and Della Townships",
        ],
    },
    "Website Design & Development": {
        "capabilities": [
            "Website and e-commerce storefront design and development",
            "UX/UI, landing pages and conversion optimisation",
            "Microsites and interactive experiences",
            "SEO-ready builds with analytics set up from day one",
        ],
        "proof": [
            "Relaxo Sparx e-commerce storefront",
            "DS Group AI x NFT microsite experience",
            "Digital ecosystems for MamyPoko Extra Absorb, Three Zinc, Simple MDG, Acnestar and Della Townships",
        ],
    },
    "Films & Campaigns": {
        "capabilities": [
            "Campaign ideas and integrated launches",
            "Brand films, digital films and ad films",
            "AI-assisted production through Three Zinc for faster, lower-cost output",
            "Shoot-based and UGC content at scale",
        ],
        "proof": [
            "Catch Foods Mother's Day film that went viral",
            "Manforce April Fools campaign",
            "WION Deepfake AI news campaign (Abby winner)",
        ],
    },
    "AI/3D/CGI": {
        "capabilities": [
            "AI-generated films and content through Three Zinc",
            "3D, CGI and product visualisation",
            "AI x Web3 microsites and interactive experiences",
            "AI content pipelines that personalise creative at scale",
        ],
        "proof": [
            "WION Deepfake AI news campaign (Abby winner)",
            "DS Group AI x NFT microsite experience",
        ],
    },
    "PR & Influencer Marketing": {
        "capabilities": [
            "Earned media and digital PR",
            "Influencer and creator programmes",
            "Reputation and launch PR",
            "Authority building that also lifts search and AI visibility",
        ],
        "proof": [
            "WION Deepfake AI news campaign (Abby winner)",
            "Manforce April Fools campaign",
        ],
    },
    "Events & Activations": {
        "capabilities": [
            "On-ground brand activations and experiential",
            "Launch events and trade presence",
            "Outdoor innovation and ambient ideas",
            "Content capture from events for social",
        ],
        "proof": [
            "Campari Aperol activation",
            "Hindware outdoor innovation (Abby nominee)",
        ],
    },
}

# ─── LinkedIn Job posts: two pitches ──────────────────────────────────────────
# A company hiring a marketing role can either outsource the work (agency) or
# get the person through us on contract (staffing). Both share one USP.
JOB_PITCH_USP = (
    "In both models the team gets access to world-class experts with multi-faceted "
    "experience across industries, plus our Three Zinc AI capabilities."
)
JOB_PITCHES = [
    {
        "angle": "Agency partner (full-spectrum)",
        "brief": (
            "Instead of (or alongside) the hire, Grapes Worldwide can take the work on as an "
            "agency: the full spectrum of SEO, Creative, Tech and Media services under one roof. "
            + JOB_PITCH_USP
        ),
    },
    {
        "angle": "FTE contract staffing",
        "brief": (
            "Grapes Worldwide can provide the role on an FTE-based contract staffing model: a "
            "dedicated resource working as part of their team, backed by our wider bench. "
            + JOB_PITCH_USP
        ),
    },
]

# ─── Per-source framing: how we found them + what the direct response is ─────
# `opener` tells the model how to reference the source; `response` describes
# the short direct reply the user posts on the platform itself.
SOURCE_RULES = {
    "linkedin_post": {
        "opener": "They posted on LinkedIn asking for an agency/partner. Open with something like 'I came across your post about ...' and restate their exact ask in natural words (don't paste their sentence).",
        "response_label": "LinkedIn comment",
        "response": "A public comment under their LinkedIn post, 35-60 words. Answer their ask directly, name one relevant proof point, say you've sent a note to their inbox or invite a DM. No links, no hashtags, no sales jargon.",
    },
    "linkedin_job": {
        "opener": "The company is hiring for a marketing role on LinkedIn. Open with 'I noticed you're hiring for <role>' and connect the role to the work Grapes can do.",
        "response_label": "LinkedIn DM / connection note",
        "response": "A LinkedIn connection note or DM to the hiring manager, under 300 characters. Mention the role they're hiring for and that we can support it either as an agency or on an FTE contract basis.",
    },
    "upwork": {
        "opener": "The client posted a paid project on Upwork. Open by restating their project in your own words and show you read the details.",
        "response_label": "Upwork proposal",
        "response": "An Upwork proposal cover letter, 90-140 words. First line must address their specific project (Upwork shows only the first two lines in the list). Mention one relevant proof point, a quick approach in 2-3 short lines, and one smart question about the project. No 'Dear Hiring Manager'.",
    },
    "freelancer": {
        "opener": "The client posted a paid project on Freelancer.com. Open by restating their project in your own words and show you read the details.",
        "response_label": "Freelancer.com bid proposal",
        "response": "A Freelancer.com bid proposal, 80-130 words. Start with their project, not with us. One relevant proof point, a short approach, one question about the brief.",
    },
    "funding_news": {
        "opener": "The company just raised funding (news). Open by congratulating them on the specific round and connect fresh capital to growth/brand/marketing needs. Do not claim they are looking for an agency.",
        "response_label": "LinkedIn comment on the funding post",
        "response": "A warm congratulatory LinkedIn comment on the funding announcement, 25-45 words. Congratulate on the specific milestone and what the company does. No pitch, no links; at most a light 'happy to help as you scale'.",
    },
    "product_hunt": {
        "opener": "They just launched on Product Hunt. Open by congratulating them on the launch and referencing what the product does. Do not claim they are looking for an agency.",
        "response_label": "Product Hunt comment",
        "response": "A Product Hunt launch comment, 25-50 words. Genuine congratulations plus one specific observation about the product. No pitch, no links.",
    },
    "meta_ads": {
        "opener": "The brand is running Meta (Facebook/Instagram) ads. Open by referencing their live ads (product/offer) and give one specific, respectful observation. Do not claim they are looking for an agency.",
        "response_label": "Instagram / LinkedIn DM",
        "response": "A short DM to the brand or its marketing head, 40-70 words. Reference their current ads, one idea to improve them, and ask if they're open to a quick chat.",
    },
    "x_post": {
        "opener": "They posted on X asking for an agency recommendation. Open with 'I saw your post on X about ...' and restate their ask.",
        "response_label": "X reply",
        "response": "A reply to their X post, under 260 characters. Direct and helpful, invite a DM. No hashtags.",
    },
}
DEFAULT_SOURCE = "linkedin_post"
