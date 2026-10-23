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

    def match_person_by_name(self, first, last, domain, webhook_url=None, linkedin_url=None):
        self.reveals.append(("name", f"{first} {last}", webhook_url))
        return self.person


GOOGLE_CALLS = []


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(contacts, "CACHE_PATH", str(tmp_path / "contacts_cache.json"))
    GOOGLE_CALLS.clear()
    monkeypatch.setattr(contacts, "_google_pages", lambda qs, token: GOOGLE_CALLS.append(qs) or [])
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
    assert res["sources"][:2] == ["apollo", "apify"]
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



def page(query, *results):
    return {"searchQuery": {"term": query},
            "organicResults": [{"url": u, "title": t, "description": d} for u, t, d in results]}


def test_linkedin_profile_found_for_masked_apollo_contact(monkeypatch):
    # Real Google results captured 2026-10-23 for suffescom.com.
    def google(qs, token):
        GOOGLE_CALLS.append(qs)
        return [page(qs[0],
                     ("https://in.linkedin.com/in/rakesh-kumar-gupta-8618b5171", "Rakesh kumar Gupta - Software Engineer", "Suffescom"),
                     ("https://in.linkedin.com/in/gurpreet-singh-walia", "Gurpreet Singh W. - CEO at Suffescom Solutions Pvt. Ltd.", "")),
                page(qs[1],
                     ("https://in.linkedin.com/in/sushil-x", "Sushil Kumar - COO at Acme", "Acme"),
                     ("https://in.linkedin.com/in/sushmachandel?trk=x", "Sush C. - Suffescom Solutions Inc", ""))]
    monkeypatch.setattr(contacts, "_google_pages", google)
    fake = FakeApollo({"CEO": [{"id": "1", "first_name": "Gurpreet", "last_name_obfuscated": "Si***h",
                                "title": "Chief Executive Officer", "has_email": True}],
                       "COO": [{"id": "2", "first_name": "Sush", "last_name_obfuscated": "Ch***l",
                                "title": "Chief Operating Officer", "has_email": True}]})
    res = contacts.find_key_contacts({"company_domain": "suffescom.com", "company": "Suffescom Solutions Inc"},
                                     apollo=fake, apify_token="t")
    links = {c["first_name"]: c["linkedin_url"] for c in res["contacts"]}
    assert links == {"Gurpreet": "https://www.linkedin.com/in/gurpreet-singh-walia",
                     "Sush": "https://www.linkedin.com/in/sushmachandel"}
    assert len(GOOGLE_CALLS) == 1 and len(GOOGLE_CALLS[0]) == 2     # one run per company
    assert GOOGLE_CALLS[0][0].startswith('site:linkedin.com/in "Gurpreet" "Suffescom Solutions Inc"')

    contacts.find_key_contacts({"company_domain": "suffescom.com"}, apollo=fake, apify_token="t")
    assert len(GOOGLE_CALLS) == 1                                    # cached, not re-searched


def test_no_match_falls_back_to_linkedin_search_link(monkeypatch):
    monkeypatch.setattr(contacts, "_google_pages", lambda qs, token: [
        page(qs[0], ("https://in.linkedin.com/in/other", "Arushi Mehta - Founder at Different Co", ""))])
    fake = FakeApollo({"CEO": [ap("1", "Arushi", "Founder & CEO")]})
    c = contacts.find_key_contacts({"company_domain": "emori.in", "company": "Emori"},
                                   apollo=fake, apify_token="t")["contacts"][0]
    assert c["linkedin_url"] == ""
    assert c["linkedin_search_url"] == "https://www.linkedin.com/search/results/people/?keywords=Arushi%20Emori"


def test_apify_internal_id_is_upgraded_to_public_profile(monkeypatch):
    monkeypatch.setattr(contacts, "_from_apify", lambda url, token: [
        {"role": "CMO", "title": "CMO", "source": "apify", "first_name": "Aakash", "last_name": "Goel",
         "masked": False, "apollo_id": "", "has_email": True, "has_phone": False,
         "linkedin_url": "https://www.linkedin.com/in/ACwAABHFooYB"}])
    monkeypatch.setattr(contacts, "_google_pages", lambda qs, token: [
        page(qs[0], ("http://www.linkedin.com/in/aakash-goel-146a3183", "Aakash Goel - CMO - Zomato", ""))])
    fake = FakeApollo(person={"id": "9", "first_name": "Aakash", "last_name": "Goel", "email": "a@z.com"})
    res = contacts.find_key_contacts({"company_domain": "zomato.com", "company": "Zomato"},
                                     apollo=fake, apify_token="t")
    c = res["contacts"][0]
    assert c["linkedin_url"] == "https://www.linkedin.com/in/aakash-goel-146a3183"
    assert c["internal_linkedin_url"].endswith("ACwAABHFooYB")


def test_old_cache_entries_get_links_once(monkeypatch):
    fake = FakeApollo({"CEO": [ap("1", "Shradha", "CEO")]})
    contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="")
    cache = contacts._load()
    for c in cache["companies"]["acme.com"]["contacts"]:
        c.pop("linkedin_checked", None)                               # as cached before this feature
    contacts._save(cache)
    contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="t")
    contacts.find_key_contacts({"company_domain": "acme.com"}, apollo=fake, apify_token="t")
    assert len(GOOGLE_CALLS) == 1


def test_last_name_prefix_must_agree():
    c = {"first_name": "Ahmed", "last_name": "Ay***b", "role": "COO"}
    words = {"tradershub", "traders", "hub"}
    wrong = [{"url": "https://www.linkedin.com/in/ahmed-alkatheeri", "title": "Ahmed Alkatheeri - COO", "description": "Traders Hub"}]
    right = [{"url": "https://ae.linkedin.com/in/ahmed-ayoub", "title": "Ahmed Ayoub - COO at Traders' Hub", "description": ""}]
    initial = [{"url": "https://ae.linkedin.com/in/ahmed-a", "title": "Ahmed A. - Traders Hub", "description": ""}]
    assert contacts._match_profile(c, wrong, words) == ""
    assert contacts._match_profile(c, right, words) == "https://www.linkedin.com/in/ahmed-ayoub"
    assert contacts._match_profile(c, initial, words) == "https://www.linkedin.com/in/ahmed-a"
    middle = {"first_name": "Gurpreet", "last_name": "Si***h", "role": "CEO"}
    assert contacts._match_profile(middle, [{"url": "https://in.linkedin.com/in/gurpreet-singh-walia",
        "title": "Gurpreet Singh W. - CEO at Suffescom", "description": ""}], {"suffescom"})
