"""Key-contact finder (agent/contacts.py): roles, ranking, Apify fallback, reveal, phone webhook.

Apollo/Apify responses are shaped like real ones captured 2026-10-23
(zomato.com, grapesworldwide.com). No network.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import contacts
from agent.outreach import build_prompt, recipient_first_name


def ap(pid, first, title, has_phone="Yes"):
    return {"id": pid, "first_name": first, "last_name_obfuscated": first[:2] + "***x",
            "title": title, "has_email": True, "has_direct_phone": has_phone}


class FakeApollo:
    def __init__(self, people_by_role=None, person=None):
        self.people_by_role, self.person = people_by_role or {}, person
        self.reveals, self.searches = [], 0

    def is_enabled(self):
        return True

    def search_people(self, domain, titles, per_page=10):
        self.searches += 1
        for role, (ts, _) in contacts.ROLES.items():
            if ts == titles:
                return self.people_by_role.get(role, [])
        return []

    def enrich_organization(self, domain=None, name=None):
        return {"linkedin_url": "http://www.linkedin.com/company/acme"}

    def reveal_person(self, pid, webhook_url=None):
        self.reveals.append(("id", pid, webhook_url))
        return self.person

    def match_person_by_name(self, first, last, domain, webhook_url=None):
        self.reveals.append(("name", f"{first} {last}", webhook_url))
        return self.person


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(contacts, "CACHE_PATH", str(tmp_path / "contacts_cache.json"))
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)


def test_role_buckets():
    assert contacts.role_of("Co-Founder & Global CEO") == "CEO"
    assert contacts.role_of("Founder & COO") == "CEO"          # founder outranks
    assert contacts.role_of("Chief Operating Officer") == "COO"
    assert contacts.role_of("CMO") == "CMO"
    assert contacts.role_of("Head of Brand Marketing") == "Head of Marketing"
    assert contacts.role_of("VP, Marketing") == "Head of Marketing"
    assert contacts.role_of("Marketing Manager") == ""
    assert contacts.role_of("Software Engineer") == ""


def test_company_level_title_beats_city_coo():
    people = {"COO": [ap("1", "Rahul", "City COO"), ap("2", "Sai", "COO - Logistics (Karnataka)"),
                      ap("3", "Parveen", "COO")]}
    res = contacts.find_key_contacts({"company_domain": "zomato.com"}, apollo=FakeApollo(people),
                                     apify_token="")
    coos = [c["first_name"] for c in res["contacts"] if c["role"] == "COO"]
    assert coos[0] == "Parveen"
    assert len(coos) == contacts.PER_ROLE


def test_apify_fallback_only_when_apollo_is_thin(monkeypatch):
    calls = []
    monkeypatch.setattr(contacts, "_from_apify", lambda url, token: calls.append(url) or [
        {"role": "CMO", "title": "Chief Marketing Officer", "source": "apify", "first_name": "Aakash",
         "last_name": "Goel", "masked": False, "apollo_id": "", "has_email": True, "has_phone": False,
         "linkedin_url": "https://www.linkedin.com/in/ACwAAB"}])
    thin = FakeApollo({"CEO": [ap("1", "Shradha", "Co-Founder & Global CEO")]})
    res = contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=thin, apify_token="t")
    assert calls == ["http://www.linkedin.com/company/acme"]
    assert res["sources"] == ["apollo", "apify"]
    assert {c["role"] for c in res["contacts"]} == {"CEO", "CMO"}

    calls.clear()
    rich = FakeApollo({"CEO": [ap("1", "Shradha", "CEO")], "CMO": [ap("2", "Nia", "CMO")]})
    contacts.find_key_contacts({"company_domain": "rich.com"}, apollo=rich, apify_token="t")
    assert calls == []


def test_cached_search_is_not_repeated():
    fake = FakeApollo({"CEO": [ap("1", "Shradha", "CEO")], "CMO": [ap("2", "Nia", "CMO")]})
    contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="")
    n = fake.searches
    res = contacts.find_key_contacts({"company_domain": "www.acme.com"}, apollo=fake, apify_token="")
    assert res["cached"] and fake.searches == n


def test_no_domain_is_a_clear_error():
    with pytest.raises(ValueError):
        contacts.find_key_contacts({"company": "Anon"}, apollo=FakeApollo(), apify_token="")


def test_reveal_email_and_phone_needs_public_url():
    person = {"id": "1", "first_name": "Shradha", "last_name": "Agarwal", "title": "Global CEO",
              "email": "shradha@acme.com", "email_status": "verified", "phone_numbers": []}
    fake = FakeApollo({"CEO": [ap("1", "Shradha", "CEO")]}, person=person)
    res = contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="")
    key = res["contacts"][0]["key"]

    c = contacts.reveal_contact("acme.com", key, apollo=fake)
    assert c["email"] == "shradha@acme.com" and c["last_name"] == "Agarwal"
    assert c["phone_status"] == "needs_public_url"
    assert fake.reveals == [("id", "1", "")]

    contacts.reveal_contact("acme.com", key, apollo=fake)          # cached: no second credit
    assert len(fake.reveals) == 1
    again = contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="")
    assert again["contacts"][0]["email"] == "shradha@acme.com"


def test_apify_contact_revealed_by_name(monkeypatch):
    monkeypatch.setattr(contacts, "_from_apify", lambda url, token: [
        {"role": "CMO", "title": "CMO", "source": "apify", "first_name": "Aakash", "last_name": "Goel",
         "masked": False, "apollo_id": "", "has_email": True, "has_phone": False, "linkedin_url": ""}])
    fake = FakeApollo(person={"id": "9", "first_name": "Aakash", "last_name": "Goel",
                              "email": "a@acme.com"})
    res = contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="t")
    contacts.reveal_contact("acme.com", res["contacts"][0]["key"], apollo=fake)
    assert fake.reveals[0][:2] == ("name", "Aakash Goel")


def test_phone_webhook_round_trip(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://sales.example.com/")
    person = {"id": "1", "first_name": "Shradha", "last_name": "Agarwal", "email": "s@acme.com"}
    fake = FakeApollo({"CEO": [ap("1", "Shradha", "CEO")]}, person=person)
    res = contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="")
    c = contacts.reveal_contact("acme.com", res["contacts"][0]["key"], apollo=fake)
    hook = fake.reveals[0][2]
    assert hook.startswith("https://sales.example.com/api/apollo/phone-webhook?token=")
    assert c["phone_status"] == "pending"

    token = hook.split("token=")[1]
    body = {"status": "success", "people": [{"id": "1", "phone_numbers": [
        {"raw_number": "+91 98100 00000", "sanitized_number": "+919810000000"}]}]}
    with pytest.raises(PermissionError):
        contacts.record_phone_webhook(body, "wrong")
    assert contacts.record_phone_webhook(body, token) == 1
    res = contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="")
    assert res["contacts"][0]["mobile"] == "+919810000000"


def test_selected_recipient_drives_the_draft():
    lead = {"source": "linkedin_job", "author": "Anta International", "company": "Anta International",
            "entity_type": "company", "snippet": "Anta International is hiring a Brand Manager",
            "recipient": {"name": "Priya Mehta", "title": "Chief Marketing Officer", "role": "CMO",
                          "email": "priya@anta.com"}}
    assert recipient_first_name(lead) == "Priya"
    system, user = build_prompt(lead)
    assert '"Priya"' in system
    assert "Title: Chief Marketing Officer" in user and "They own marketing" in user


def test_profile_named_after_company_is_dropped(monkeypatch):
    monkeypatch.setattr(contacts, "_from_apify", lambda url, token: [
        {"role": "CEO", "title": "Founder", "source": "apify", "first_name": "Reelotek",
         "last_name": "Metals", "masked": False, "apollo_id": "", "has_email": True,
         "has_phone": False, "linkedin_url": ""}])
    fake = FakeApollo({"CEO": [ap("1", "Manav", "Founder")]})
    res = contacts.find_key_contacts({"company_domain": "reelotek.com", "company": "Reelotek"},
                                     apollo=fake, apify_token="t")
    assert [c["first_name"] for c in res["contacts"]] == ["Manav"]
