"""Outreach drafter (agent/outreach.py): prompt, name resolution, assembly.

Leads are shaped like real dashboard card payloads from
outputs/pipeline_20260925_144828.json. No network: Gemini is a fake client.
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.outreach import (
    NAME_PLACEHOLDER, build_prompt, draft_outreach, lead_services, recipient_first_name,
    subject_company,
)
from config.outreach import SENDER

JOB = {
    "source": "linkedin_job", "author": "Anta International", "company": "Anta International",
    "entity_type": "company",
    "snippet": "Anta International is hiring: 2 marketing roles (E-commerce Operations Supervisor (Amazon)) — Dubai",
    "hooks": ["Hiring E-commerce Operations Supervisor (Amazon)", "195 applicants so far"],
    "pitch_services": [],
}
UPWORK = {
    "source": "upwork", "author": "Simona (Upwork client)", "entity_type": "person",
    "snippet": "Senior DTC Graphic Designer for a health & wellness e-commerce brand, Meta ads.",
    "hooks": ["Budget: $3,500.00"], "pitch_services": [],
}
FREELANCER = {"source": "freelancer", "author": "Freelancer.com client · USD", "snippet": "Logo design"}
PRODUCT_HUNT = {
    "source": "product_hunt", "author": "Scholé Learn by Building", "snippet": "Just launched",
    "hooks": ["402 upvotes", "Makers: Aleksandar Blazhev, Güneş Ozgün"],
    "pitch_services": ["Branding & Designing", "Social Media & Content Strategy"],
}
POST = {
    "source": "linkedin_post", "author": "Abhishek Sharma", "entity_type": "person",
    "snippet": "Looking for an SEO partner to grow branded search for our D2C brand. 90-day plan.",
    "pitch_services": ["SEO", "SEM", "SMO"],
}


def email(angle="a", subject="s", context="ctx", outcomes=()):
    return {"angle": angle, "subject": subject, "context": context, "about": "about",
            "capabilities": ["cap one", "cap two", "cap three"], "fit": "fit",
            "outcomes": list(outcomes), "cta": "cta"}


class FakeClient:
    """Returns a canned JSON reply and records the request."""
    def __init__(self, reply: dict):
        self.reply, self.calls = reply, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append({"contents": contents, "config": config})
        return SimpleNamespace(text=json.dumps(self.reply))


def test_recipient_names_per_source():
    assert recipient_first_name(POST) == "Abhishek"
    assert recipient_first_name(UPWORK) == "Simona"
    assert recipient_first_name(PRODUCT_HUNT) == "Aleksandar"
    assert recipient_first_name(JOB) == ""          # company, not a person
    assert recipient_first_name(FREELANCER) == ""   # marketplace placeholder
    # An Apollo decision-maker beats everything.
    assert recipient_first_name({**JOB, "decision_makers": [{"name": "Priya Nair"}]}) == "Priya"


def test_services_map_regex_tags_and_cap_at_two():
    assert lead_services(POST) == ["SEO", "Media Planning & Buying"]
    assert lead_services(JOB) == []


def test_job_prompt_asks_for_both_pitches_and_usp():
    system, user = build_prompt(JOB)
    assert "Agency partner (full-spectrum)" in user and "FTE contract staffing" in user
    assert "EXACTLY TWO emails" in user
    assert "Three Zinc AI capabilities" in user
    assert f'addressed as "{NAME_PLACEHOLDER}"' in system


def test_source_decides_the_direct_response():
    assert "Upwork proposal" in build_prompt(UPWORK)[1]
    assert "LinkedIn comment" in build_prompt(POST)[1]
    assert "Product Hunt comment" in build_prompt(PRODUCT_HUNT)[1]
    assert "EXACTLY ONE email" in build_prompt(POST)[1]


def test_assembly_enforces_greeting_signature_and_real_outcomes():
    reply = {
        "emails": [
            email("Agency partner", "Your Amazon ops hire.", "We can help — fast!",
                  outcomes=["Worked with brands like Manforce, Dabur, Pay10, Flipkart and Unicharm Group",
                            "Handled media buying for Flipkart"]),          # invented → dropped
            email("FTE staffing", "Contract support"),
            email("extra"),
        ],
        "response": "Happy to support — either model works!",
    }
    out = draft_outreach(JOB, api_key="x", client=FakeClient(reply))
    assert len(out["emails"]) == 2                       # third email dropped
    assert out["emails"][0]["subject"] == "Grapes Worldwide × Anta International | Your Amazon ops hire"
    body = out["emails"][0]["body"]
    assert body.startswith(f"Hi {NAME_PLACEHOLDER},\n\nHope you're doing well.")
    assert "We can help, fast." in body and "—" not in body and "!" not in body
    assert "Worked with brands like Manforce" in body and "Handled media buying" not in body
    assert body.rstrip().endswith(SENDER["email"])
    assert "https://www.grapesworldwide.com/case-study" in body
    # No valid outcome picked → falls back to configured proof, never empty.
    assert "A few relevant outcomes:\n- " in out["emails"][1]["body"]
    assert out["response"] == {"label": "LinkedIn DM / connection note",
                               "text": "Happy to support, either model works."}


def test_non_job_sources_keep_one_email():
    reply = {"emails": [email(), email()], "response": "r"}
    out = draft_outreach(POST, api_key="x", client=FakeClient(reply))
    assert len(out["emails"]) == 1
    assert out["emails"][0]["body"].startswith("Hi Abhishek,")


def test_falls_back_when_primary_model_is_overloaded():
    class BusyThenOk(FakeClient):
        def generate_content(self, model, contents, config):
            if not self.calls:
                self.calls.append(model)
                raise RuntimeError("503 UNAVAILABLE. high demand")
            self.calls.append(model)
            return SimpleNamespace(text=json.dumps(self.reply))

    client = BusyThenOk({"emails": [email()], "response": "r"})
    out = draft_outreach(POST, api_key="x", model="primary", client=client)
    assert client.calls[0] == "primary" and client.calls[1] != "primary"
    assert out["emails"][0]["subject"] == "Grapes Worldwide × [Company] | s"


def test_subject_uses_house_pattern():
    reply = {"emails": [email(subject="Grapes Worldwide × MN Infotech | White-Label Web & eCommerce Partnership.")],
             "response": "r"}
    lead = {**POST, "company": "MN Infotech Pvt. Ltd."}
    out = draft_outreach(lead, api_key="x", client=FakeClient(reply))
    assert out["emails"][0]["subject"] == "Grapes Worldwide × MN Infotech | White-Label Web & eCommerce Partnership"
    assert subject_company({"company": "Suffescom Solutions Inc"}) == "Suffescom Solutions"
    assert subject_company({"company": "Traders' Hub FZE"}) == "Traders' Hub"
    assert subject_company({"author": "Scholé (Product Hunt)", "source": "product_hunt"}) == "Scholé"
    assert subject_company({"company_domain": "www.emori.in"}) == "Emori"
    assert subject_company({"author": "Abhishek Sharma", "entity_type": "person"}) == "[Company]"
