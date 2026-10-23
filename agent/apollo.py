import os
import requests
import logging

logger = logging.getLogger("LinkedInPipeline.Apollo")

class ApolloClient:
    def __init__(self):
        self.api_key = os.getenv("APOLLO_API_KEY")
        self.headers = {
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key
        }
        self.base_url = "https://api.apollo.io/api/v1"

    def is_enabled(self):
        return bool(self.api_key)

    def match_person(self, name, linkedin_url, company_name=None):
        """Find person contact details (email, phone, etc) using Apollo match API."""
        if not self.is_enabled():
            return None
        payload = {
            "name": name,
            "linkedin_url": linkedin_url
        }
        if company_name:
            payload["organization_name"] = company_name

        try:
            r = requests.post(f"{self.base_url}/people/match", json=payload, headers=self.headers, timeout=10)
            if r.status_code == 200:
                return r.json().get("person")
            else:
                logger.warning(f"Apollo match_person failed: {r.status_code} - {r.text}")
        except Exception as e:
            logger.error(f"Apollo match_person error: {e}")
        return None

    def match_person_by_name(self, first_name, last_name, domain, webhook_url=None):
        """people/match by name + company domain (for Apify-found people with no Apollo id)."""
        if not self.is_enabled():
            return None
        payload = {"first_name": first_name, "last_name": last_name, "domain": domain,
                   "reveal_personal_emails": False}
        if webhook_url:
            payload["reveal_phone_number"] = True
            payload["webhook_url"] = webhook_url
        try:
            r = requests.post(f"{self.base_url}/people/match", json=payload, headers=self.headers, timeout=20)
            if r.status_code == 200:
                return r.json().get("person")
            else:
                logger.warning(f"Apollo match_person_by_name failed: {r.status_code} - {r.text[:300]}")
        except Exception as e:
            logger.error(f"Apollo match_person_by_name error: {e}")
        return None

    def enrich_organization(self, domain=None, name=None):
        """Get company firmographics and tech stack."""
        if not self.is_enabled():
            return None
        payload = {}
        if domain:
            payload["domain"] = domain
        elif name:
            payload["name"] = name
        else:
            return None

        try:
            r = requests.post(f"{self.base_url}/organizations/enrich", json=payload, headers=self.headers, timeout=10)
            if r.status_code == 200:
                return r.json().get("organization")
            else:
                logger.warning(f"Apollo enrich_organization failed: {r.status_code} - {r.text}")
        except Exception as e:
            logger.error(f"Apollo enrich_organization error: {e}")
        return None

    def search_people(self, domain, titles, per_page=10):
        """People API Search at one domain. No credits; names come back masked
        (last_name_obfuscated) and without email/phone; reveal_person() unmasks."""
        if not self.is_enabled() or not domain:
            return []
        payload = {
            "q_organization_domains_list": [domain],
            "person_titles": titles,
            "per_page": per_page,
        }
        try:
            r = requests.post(f"{self.base_url}/mixed_people/api_search", json=payload, headers=self.headers, timeout=15)
            if r.status_code == 200:
                return r.json().get("people", [])
            else:
                logger.warning(f"Apollo search_people failed: {r.status_code} - {r.text[:300]}")
        except Exception as e:
            logger.error(f"Apollo search_people error: {e}")
        return []

    def search_decision_makers(self, domain, titles=None):
        """Find decision-makers at a given domain (kept for callers that want one flat search)."""
        if titles is None:
            titles = ["cmo", "head of marketing", "director of marketing", "ceo", "founder", "coo"]
        return self.search_people(domain, titles, per_page=5)

    def reveal_person(self, person_id, webhook_url=None):
        """Unmask one person by Apollo id: full name, verified work email (sync, 1 credit).

        Mobile numbers are only delivered asynchronously to `webhook_url`
        (Apollo rejects reveal_phone_number without one), so they arrive later
        at /api/apollo/phone-webhook.
        """
        if not self.is_enabled() or not person_id:
            return None
        payload = {"id": person_id, "reveal_personal_emails": False}
        if webhook_url:
            payload["reveal_phone_number"] = True
            payload["webhook_url"] = webhook_url
        try:
            r = requests.post(f"{self.base_url}/people/match", json=payload, headers=self.headers, timeout=20)
            if r.status_code == 200:
                return r.json().get("person")
            else:
                logger.warning(f"Apollo reveal_person failed: {r.status_code} - {r.text[:300]}")
        except Exception as e:
            logger.error(f"Apollo reveal_person error: {e}")
        return None

    def get_sequences(self):
        """List sequences in the Apollo account (Apollo calls them emailer campaigns)."""
        if not self.is_enabled():
            return []
        try:
            r = requests.post(f"{self.base_url}/emailer_campaigns/search", json={"per_page": 100},
                              headers=self.headers, timeout=10)
            if r.status_code == 200:
                return r.json().get("emailer_campaigns", [])
            else:
                logger.warning(f"Apollo get_sequences failed: {r.status_code} - {r.text[:300]}")
        except Exception as e:
            logger.error(f"Apollo get_sequences error: {e}")
        return []

    def create_contact(self, first_name, last_name, email, title=None, company_name=None, linkedin_url=None):
        """Create a contact in Apollo to get a contact ID."""
        if not self.is_enabled():
            return None
        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email
        }
        if title:
            payload["title"] = title
        if company_name:
            payload["organization_name"] = company_name
        if linkedin_url:
            payload["linkedin_url"] = linkedin_url

        try:
            r = requests.post(f"{self.base_url}/contacts", json=payload, headers=self.headers, timeout=10)
            if r.status_code == 200:
                return r.json().get("contact")
            else:
                logger.warning(f"Apollo create_contact failed: {r.status_code} - {r.text}")
        except Exception as e:
            logger.error(f"Apollo create_contact error: {e}")
        return None

    def enroll_in_sequence(self, contact_id, sequence_id):
        """Enroll contact ID into a specific sequence ID."""
        if not self.is_enabled():
            return False
        payload = {
            "contact_ids": [contact_id]
        }
        try:
            r = requests.post(f"{self.base_url}/emailer_campaigns/{sequence_id}/add_contact_ids", json=payload, headers=self.headers, timeout=10)
            if r.status_code == 200:
                return True
            else:
                logger.warning(f"Apollo enroll_in_sequence failed: {r.status_code} - {r.text}")
        except Exception as e:
            logger.error(f"Apollo enroll_in_sequence error: {e}")
        return False
