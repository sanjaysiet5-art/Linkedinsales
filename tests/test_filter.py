"""Regression test: ideal RFP posts must PASS, noise must FAIL."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.parser import LinkedInPost
from agent.scorer import score_post
from agent.filter import apply_smart_filter


def mk(content, author="Some Brand", etype="brand", headline="", url="https://www.linkedin.com/posts/x_activity-1"):
    return LinkedInPost(
        url=url, title=f"{author} on LinkedIn", snippet=content,
        author_name=author, entity_type=etype, company_hint="",
        timestamp_raw="1 hour ago", estimated_posted_at=None,
        author_headline=headline,
    )


IDEAL = [
    mk("""Looking for Recommendations! 🚀
I'm looking to connect with a PR agency that has strong experience working with education brands, universities, or higher education institutions.
If you've worked with an agency that delivers quality media relations, thought leadership, and strategic PR in the education sector, I'd love to hear your recommendations.
Please drop a DM me with your suggestions. Thank you in advance! 🙌""",
       author="Ritu Sharma", etype="person", headline="Head of Admissions at EduGrow University"),

    mk("""🚀 Looking for a Development Partner – Multi-Vendor Marketplace
We are planning to develop a multi-vendor marketplace platform, starting with Dubai, with future expansion across the UAE and GCC.
We are looking for experienced development companies / agencies / solution providers who can deliver a scalable and high-quality marketplace solution.
🔍 Scope Includes: Customer website (mobile responsive), Vendor (seller) panel, Admin dashboard, Payment & delivery integrations, Scalable architecture
🧩 Who Should Reach Out: Companies with experience in marketplace development, Providers offering custom or white-label solutions
📩 Get in Touch: Please share your company profile, relevant work, and basic proposal via DM. Looking forward to connecting with the right partners 🤝""",
       author="Gulf Retail Ventures", etype="brand"),

    mk("""A nonprofit organization is looking for a web design and development agency to redesign and modernize its website with improved functionality, integrations, and user experience.
Estimated Project Value: USD $18,000
Details available on Project Wire""",
       author="Project Wire", etype="brand"),

    mk("""Looking for SEO experts !
We're looking to collaborate with an experienced SEO agency/specialist to help strengthen Shop Culture's website visibility and organic growth.
If you have expertise in: ✔ E-commerce website SEO strategy ✔ Technical SEO audits ✔ Keyword research & search optimisation ✔ Content-led organic growth ✔ Conversion-focused website improvements
We'd love to connect and explore working together. Please reach out or drop your recommendations in the comments.
#SEO #SEOAgency #DigitalMarketing #OrganicGrowth""",
       author="Shop Culture", etype="brand"),

    # Real Project Wire lead
    mk("A global public health organization is looking for a web development and digital marketing agency to provide website hosting, maintenance, SEO, analytics",
       author="Project Wire", etype="brand"),

    # Example 5: Looking for Google Ads freelancer or agency
    mk("""Looking for recommendations! ✨ 

We're looking for an experienced Google Ads freelancer or agency to support our paid search activity for Connect Frontline

Ideally, someone with experience working with B2B/SaaS businesses who can act as an extension of our marketing team.

If you've worked with someone you'd highly recommend (or if this sounds like you), please drop a comment below or send me a message!""",
       author="Connect Frontline", etype="brand"),

    # Example 8 & 9: Looking for boutique, India-based social media agencies
    mk("""Looking for boutique, India-based social media agencies for a B2B AI SaaS startup.
Must have experience in scaling tech brands on LinkedIn and Twitter. Drop your credentials or DM.""",
       author="SaaS Founder", etype="person", headline="Founder @ TechAI"),

    # NEW IDEAL: RFP that names "funding agencies" in a legitimate marketing
    # context. Guards against the service-gate over-rejecting — this post IS a
    # brand seeking a marketing agency, and happens to mention funding.
    mk("""We just closed our Series B and are looking for a full-service branding and digital marketing agency.
Our investors and funding agencies expect aggressive growth this year, so we need an experienced agency partner
for brand strategy, performance marketing, and content. Please share your credentials and case studies via DM.
Budget allocated. RFP attached.""",
       author="Nimbus Fintech", etype="brand"),

    # NEW IDEAL: Events & Activations RFP (service #09 had no test coverage).
    mk("""Looking for an event management agency to plan and execute our annual flagship conference in Mumbai.
Scope: venue, production, experiential activations, and on-ground coordination for ~2000 attendees.
Please share your agency profile and relevant event case studies. DM to connect.""",
       author="Horizon Tech", etype="brand"),
]

NOISE = [
    # Job post — individual hire
    mk("We are hiring! Looking for a Social Media Manager to join our team in Mumbai. 2-3 years experience. Apply now, send your CV to hr@acme.com",
       author="Acme Foods", etype="brand"),
    # Job post — expert to join team
    mk("Looking for a digital marketing expert to join our growing in-house team. Full-time role, immediate joining.",
       author="Zesty Retail", etype="brand"),
    # Agency informational content (agency author name)
    mk("Local SEO services are critical for hotels looking to maximize direct bookings, improve search visibility on Google Maps and the Local 3-Pack.",
       author="Hotel SEO Agency", etype="brand"),
    # Agency self-promo / case study
    mk("New case study: We helped our client achieve 300% ROI in 90 days. Our agency delivered a full-funnel strategy. Book a free consultation today!",
       author="BrightLeap", etype="brand"),
    # Freelancer/consultant author (person seller)
    mk("Want more organic traffic? I offer complete SEO packages for small businesses. DM to collaborate.",
       author="Mehwish Ijaz", etype="person", headline="SEO Backlinks Expert | Guest Posting"),
    # Individual thought leadership
    mk("Most people miss this about branding. Here are the 5 things every brand should know about SEO in 2026. Follow for more insights!",
       author="Rahul Verma", etype="person", headline="CMO at FooCorp"),
    # Informational brand post, no intent
    mk("We just launched our new festive campaign across India. Proud of the team for pulling this off! #marketing",
       author="Nimbus Foods", etype="brand"),
    # Agency fishing with seek-bait (agency author)
    mk("We are looking for brands that need a marketing agency! DM us to grow 10x.",
       author="GrowthMax Digital Marketing", etype="brand"),
    # Recommendation-style but topical only, no provider ask
    mk("Google ads costs are rising. ROAS is down across the board this quarter for most D2C brands.",
       author="Kirti Bansal", etype="person", headline="Growth Lead at D2C brand"),
    # SEO founder telling a war story about a brand looking for an agency
    mk("A supplement brand doing $700K-$1M a month on Amazon just told me something that should worry every SEO. They said they are looking for an SEO agency that understands AI search.",
       author="Fahad Hassan Awan", etype="person",
       headline="Founder at RanksInn | Turning Organic Traffic Into High-Ticket Revenue | SEO, GEO"),
    # Fractional CMO vendor blog promo mentioning agency search / RFPs
    mk("Agency relationships don't suddenly fail. They slowly erode over time. In his new blog, Why a Fractional CMO Should Lead Your Next Agency Search, Tom explains how to run RFPs the right way.",
       author="TechCXO", etype="brand"),
    # Job post: PM to join a team, mentions RFPs in duties
    mk("Remote Opportunity | LATAM. We're looking for Project Manager to join a fast-growing team supporting top U.S. companies. You will manage RFPs and client deliverables. Apply today.",
       author="WeTalent", etype="brand"),
    # Design studio owner bragging about inbound lead
    mk("An Indian kitchen appliance brand got in touch last week for a full brand and marketing overhaul, the kind of brief with multiple tracks and an RFP attached.",
       author="Aman V.", etype="person",
       headline="India's Best Multi Disciplinary Design Studio IBDA '25 /// Helping Indian Agencies"),
    # Procurement thought leadership, hypothetical CMO scenario
    mk("THE REQUEST IS NOT THE REQUIREMENT. You are the Category Manager for Marketing. On Monday morning, an email arrives from the CMO: We need to issue an RFP for a new agency.",
       author="Richard Beaumont", etype="person",
       headline="FCIPS | Procurement Capability Partner | Board-ready decisions under pressure"),
    # Lead-gen seller flexing revenue numbers
    mk("We have generated $1.5M in revenue for 23+ clients across 12+ industries in 9 countries using LinkedIn. Here is that idea in motion: DevShop Founder wins 3 RFPs a month.",
       author="Ranjana Jha", etype="person",
       headline="Founder & CEO @ The Entropy | curious | problem solver | ex-atlassian"),
    # New-job announcement mentioning an agency
    mk("Excited to share that I've joined Full Send Agency as a Junior Marketer. Full Send is an Out-Of-House creative agency in Los Angeles working with startups. First task: helping with an RFP response.",
       author="Haroun Mansour", etype="person", headline="--"),
    # Agency self-promo with rhetorical seek-hook (user-reported false positive)
    mk("""Looking for an SEO agency that actually gets results? 🚀
We help your website climb higher, rank better, and convert smarter.
Because being on Google isn't enough, you need to be on TOP.
Ready to grow? Let's make it happen.
📞 +1 (807) 699 0669""",
       author="TopClimb", etype="brand"),
    # SaaS recruiting channel partners/resellers (user-reported false positive)
    mk("""🤝 Partner With FlowUpAI – Let's Build the Future of AI Together
At FlowUpAI, we're building an AI-first platform that helps businesses automate their entire sales and growth process—from finding leads to closing deals.
We're looking for strategic partners, agencies, consultants, resellers, and businesses who want to grow with us and leverage AI to deliver better results for their clients.
🤝 Who Can Partner With Us? Digital Marketing Agencies, Sales & Lead Generation Agencies, SaaS Resellers, Business Consultants
🌟 Why Partner with FlowUpAI? ✅ Revenue Sharing Opportunities ✅ Long-Term Strategic Partnership ✅ White-label & Enterprise Solutions ✅ Co-Marketing Opportunities
📧 Email: contact@flowupai.in 🌐 Website: https://flowupai.in 📞 Contact: +91 62050 77620
Let's build smarter businesses with AI—together. 🚀""",
       author="FlowUpAI", etype="brand"),
    # Guest-post/link-building seller with rhetorical hook (user-reported false positive)
    mk("""🚀 Looking for High-Quality Guest Post Opportunities?
I help SEO agencies, businesses, and marketers build strong backlinks through high-quality guest posting.
✅ Guest Posts in Multiple Niches
✅ High DR Websites
✅ Fast Turnaround
✅ Permanent Do-Follow Links
✅ Affordable Pricing
If you're looking for reliable guest post placements or link-building support, feel free to send me a message.
Let's grow your website's authority together!
hashtag#SEO hashtag#GuestPosting hashtag#LinkBuilding hashtag#Backlinks hashtag#DigitalMarketing hashtag#OffPageSE""",
       author="Arslan Ahmed", etype="person", headline="--"),
    # Freelancer advertising own availability (user-reported false positive)
    mk("""🚀 Looking for Remote UX/UI Design Projects & Collaboration Opportunities
Hello everyone,
I'm a UX/UI Designer who is actively looking for remote freelance projects and collaboration opportunities with startups, agencies, and businesses worldwide.
I enjoy designing intuitive, user-centered digital experiences and am looking to contribute to real products while building long-term professional relationships.
My areas of expertise and interest include: UX Research, User Flows & Information Architecture, Wireframing & Prototyping, Mobile App & Web UI Design, Design Systems, Usability Testing, Figma
Whether you're building a new product, improving an existing one, or need support with your design team, I'd be excited to help transform your ideas into clean, functional, and engaging user experiences.
I'm open to: Remote freelance projects, Startup collaborations, Agency partnerships, Contract-based UX/UI design work, Long-term remote opportunities
If you or someone in your network is looking for a dedicated UX/UI Designer, I'd love to connect and discuss how I can contribute to your project.
Feel free to send me a message or leave a comment.
Thank you, and I look forward to connecting with you! 🚀
Telegram: @PetrusPhan
WhatApp: +84 (0) 937 39 56 79
Email: petrusphan@gmail.com""",
       author="Petrus Phan", etype="person", headline="--"),
    # Product-marketing think piece mentioning "the agency brief" (user-reported false positive)
    mk("""Most companies that say they have product marketing don't. They have marketing of the product. Different function. Different outcome. The confusion has a real cost.
Marketing of the product is a coordinator role. It owns the landing page, the launch deck, the sales enablement doc, the agency brief. The output is assets. The success metric is whether the assets shipped on time and looked good.
Product marketing is a strategy function. It owns positioning, audience definition, the messaging architecture that everything downstream inherits. It decides what we're selling, to whom, and why they should care — before the campaign team makes anything.
Most companies hire for the first while writing JDs for the second. They tell the candidate they'll own strategy. Then they hand them a launch calendar and an agency roster. Six months later, everyone is confused about why "product marketing" isn't moving anything upstream.""",
       author="Priya Nair", etype="person", headline="Product Marketing Leader"),
    # Exclude 1: Agency pitching their own services (Third Eye Blind Productions)
    mk("""As we move further into the second half of 2026, this is the time when many brands begin planning, scaling, and executing campaigns for the months ahead.

The opportunities are diverse from product launches and brand awareness to creator-led storytelling, social-first content, and integrated digital campaigns.

At Third Eye Blind Productions, we partner with brands and agencies to bring these campaigns to life through:
• Influencer Marketing
• Exclusive Talent Management
• End-to-End Production
• Social Media Marketing
• YouTube Brand Integrations (Official YouTube Partner)
• Creator & Celebrity Collaborations
With experience across lifestyle, fashion, beauty, jewellery, automotive, real estate, FMCG, tech, and more, we focus on finding the right creators and delivering campaigns that align with each brand's objectives.

Whether you're a brand looking for a strategic Influencer Marketing Partner or an Agency seeking reliable Execution and access to Exclusive creators, we'd love to collaborate.
Let's create campaigns that deliver meaningful impact.""",
       author="Third Eye Blind", etype="brand"),
    # Exclude 2: Thought leadership / agency owner pitch (Amazon partner)
    mk("""Most people think running an Amazon agency is about ads, keywords, and rankings.

After working with 100+ brands across the UAE and KSA, I've learned it's really about something else:

Trust under pressure.

When a brand gives us access to their Amazon account, they're not just handing over a marketplace channel.

They're trusting us with:

💰 Revenue

📈 Growth targets

⭐ Brand reputation

🤝 Customer experience

That's a responsibility we take seriously.

Because the reality is that not every week brings great news.

Some weeks we're celebrating record sales.

Other weeks we're explaining what went wrong and exactly how we're going to fix it.

Over the years, we've built a few principles that guide every client relationship:

Tell the truth quickly

Especially when it's uncomfortable.

Problems don't get smaller by waiting.

Focus on outcomes, not vanity metrics
Impressions are nice.

Clicks are nice.

But clients don't pay invoices with impressions.

We care about:

✅ Sales

✅ Profitability

✅ Sustainable growth

Treat the budget like it's our own

Every dirham spent should have a purpose.

Efficiency matters.

Fix the fundamentals first

Before chasing the newest tactic, trend, or Amazon feature.

The biggest wins usually come from improving the basics.

Make clients smarter

Not more dependent.

The best partnerships happen when clients understand what's happening and why.

Amazon changes constantly.

Algorithms evolve.

Advertising tools change.

Competition increases.

The tactics we use today may not be the tactics we use a year from now.

But the thing that keeps clients with us isn't a tactic.

It's trust.

Trust that we'll tell them the truth.

Trust that we'll protect their interests.

Trust that we'll always focus on what creates long-term results.

That's the part of this business no software can automate.

And it's the part I'm most proud of.

If you're looking for an Amazon partner who will give you the real picture—not just the comfortable one—

DM "𝐑𝐄𝐀𝐋" and let's talk.""",
       author="John Doe", etype="person", headline="Entrepreneur"),
    # Exclude 3: Internship opportunity at leading agency
    mk("""📍 WINDHOEK OPPORTUNITY 

Amazing Social Media Internship opportunity at a leading agency in Windhoek. 

If you're a current final-year student or recent graduate in Marketing, Advertising, Communications or a related field looking for real agency experience, this is a great opportunity to get your foot in the door. if you have a passion for all things social and digital, this is for you. 

This is a paid, 3-month internship designed to provide practical industry experience. 

If this sounds like the right fit for you, or someone you know, you'll find the application link in the comments.""",
       author="Windhoek Retail", etype="brand"),
    # Exclude 4: Self promotional agency pitching (BlueNetvista)
    mk("""A website is no longer just an online brochure. It’s your first salesperson, your brand ambassador, and often the deciding factor in whether a customer chooses you or your competitor.

At BlueNetvista, we’ve spent more than 17 years helping businesses transform their digital presence through thoughtful strategy, modern design, and measurable marketing.

Our expertise includes:

✅ Custom Website Design & Development
✅ E-commerce Solutions
✅ Search Engine Optimization (SEO)
✅ Digital Marketing
✅ Web Hosting & Server Management
✅ Business Automation & Custom Web Applications

We’ve had the privilege of delivering over 1,500 projects for more than 500 clients across India, the United States, Australia, the United Kingdom, and beyond.

Our philosophy is simple: build digital solutions that create real business growth, not just beautiful websites.

If you’re planning a new website, looking to improve your Google rankings, or need a technology partner who understands both business and digital strategy, we’d love to connect.""",
       author="BlueNetvista Client Partner", etype="brand"),
    # Exclude 5: Aggregator RFP tweet/post without seek keywords
    mk("State Agency in CA issues #RFP for #VideoProduction Services. More at #RFPalooza #RFP #RFQ #Video #Marketing #Media #DigitalMedia https://buff.ly/x",
       author="RFPalooza", etype="brand"),
    # Exclude 6: Digital marketing practitioner / agency partner headline (Tim Hübler)
    mk("""If you think your agency is too smart to get scammed, I have a story for you that happened last week... An inbound lead slid into my LinkedIn DMs looking for an agency to optimise a Google Ads account for a US-based luxury furniture brand, followed by a European Go-To-Market strategy. It matched our exact wheelhouse: transatlantic e-commerce, with a senior team fluent in English, German, Italian,...""",
       author="Tim Hübler", etype="person", headline="Paid Media Director | PPC, Paid Social & Programmatic for Ecommerce, D2C Lead Gen & B2B | Partner at"),
    # NEW NOISE: fundsforNGOs — fundraising myth thought-leadership. Leaked
    # because "funding agencies" matched the bare agency noun. The author's
    # headline ("Helping Nonprofits Discover Funding") + the absence of a
    # marketing service must now reject it.
    mk("""STOP Believing This Fundraising Myth. It Could Be Costing Your NGO Millions.
Myth: Small NGOs can't win large grants. Reality: Donors fund the best-aligned proposals.
Many funding agencies actively seek grassroots organizations. The size of your NGO doesn't
determine your funding potential — your strategy, evidence of impact, and proposal quality do.
Join our LinkedIn community to discover funding opportunities and grant writing tips.
Tell us in the comments: What's the biggest fundraising myth you've heard?""",
       author="fundsforNGOs Digital Outreach", etype="person",
       headline="Helping Nonprofits Discover Funding Opportunities & Donor Insights at fundsforNGOs"),
    # NEW NOISE: Justin Gordon — tech co-founder hunt dressed as "looking to
    # connect with partners". Leaked via bare seek verb + "DM me". Has no
    # marketing service at all (only AI/cybersecurity/software).
    mk("""Calling Innovators, Engineers, and Visionaries: Let's Redefine AI Intervention.
I am actively looking to connect with potential partners and collaborators who are ready to push
the boundaries of AI Intervention. We need AI-driven solutions that actively intervene to secure
your personal web experience. If you are a developer, AI researcher, cybersecurity expert, or a
forward-thinking strategist who shares this vision, I want to hear from you. Send me a DM or drop
a comment below, and let's start building.""",
       author="Justin Gordon", etype="person", headline="CEO at Gxrdxn Technologies LLC"),
    # NEW NOISE: Raju Rai — staffing/recruitment firm SELLING workforce
    # services. Leaked because "looking for a reliable workforce partner"
    # matched the seek verb + agency noun. Author headline must reject him.
    mk("""If your organization is expanding, launching a new project, entering a new market,
or looking for a reliable workforce partner, we would be honored to collaborate with you.
At Royal International Staffing, we support businesses with end-to-end workforce solutions
across Engineering, Manufacturing, IT, Oil & Gas, Infrastructure, and Executive Search.
Feel free to connect with me or send a direct message to discuss your workforce requirements.""",
       author="Raju Rai", etype="person",
       headline="Chairman & Managing Director, Global Engineering, Technology & Workforce Solutions"),
]

fails = 0
for i, p in enumerate(IDEAL, 1):
    score_post(p)
    passed, stats = apply_smart_filter([p])
    ok = len(passed) == 1
    if not ok:
        fails += 1
        reason = [k for k, v in stats.items() if v and k not in ("total_in", "passed")]
        print(f"✗ IDEAL {i} was FILTERED OUT ({reason})")
    else:
        sig = passed[0].moment_signals[0]
        print(f"✓ IDEAL {i} passed — score {passed[0].intent_score}/10 · {sig['label']} {sig['matched_keywords']}")

for i, p in enumerate(NOISE, 1):
    score_post(p)
    passed, stats = apply_smart_filter([p])
    ok = len(passed) == 0
    if not ok:
        fails += 1
        print(f"✗ NOISE {i} PASSED (should be filtered): {p.snippet[:70]}")
    else:
        reason = [k for k, v in stats.items() if v and k not in ("total_in", "passed")][0]
        print(f"✓ NOISE {i} filtered ({reason})")

print(f"\n{'ALL TESTS PASSED' if fails == 0 else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
