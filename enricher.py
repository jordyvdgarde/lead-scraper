"""Company contact information enrichment via public sources."""

import re
import logging
import time
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import pandas as pd

from config import REQUEST_DELAY, HEADERS

logger = logging.getLogger(__name__)

# Regex patterns for Dutch contact info
PHONE_PATTERN = re.compile(
    r"(?:(?:\+31|0031|0)[\s\-.]?"
    r"(?:[1-9]\d{0,2})[\s\-.]?"
    r"\d{2,4}[\s\-.]?\d{2,4}[\s\-.]?\d{0,4})"
)

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Filter out common non-company emails
EXCLUDED_EMAIL_DOMAINS = {
    "example.com", "gmail.com", "hotmail.com", "outlook.com",
    "yahoo.com", "live.nl", "live.com", "googlemail.com",
}


def _is_valid_phone(phone: str) -> bool:
    """Check if a phone number looks like a real Dutch number."""
    digits = re.sub(r"\D", "", phone)
    return 9 <= len(digits) <= 12


def _is_valid_email(email: str) -> bool:
    """Check if an email looks like a company email."""
    domain = email.split("@")[-1].lower()
    return domain not in EXCLUDED_EMAIL_DOMAINS


def _clean_phone(phone: str) -> str:
    """Normalize a phone number."""
    return re.sub(r"\s+", " ", phone.strip())


def search_company_website(company: str, session: requests.Session) -> str | None:
    """Try to find a company's website via DuckDuckGo HTML search."""
    search_url = (
        f"https://html.duckduckgo.com/html/"
        f"?q={quote_plus(company + ' nederland website')}"
    )
    try:
        time.sleep(REQUEST_DELAY)
        resp = session.get(search_url, timeout=10)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        results = soup.find_all("a", class_="result__a")

        for result in results[:5]:
            href = result.get("href", "")
            # DuckDuckGo wraps URLs; try to extract the actual URL
            if "uddg=" in href:
                from urllib.parse import parse_qs, urlparse as _urlparse
                parsed = _urlparse(href)
                qs = parse_qs(parsed.query)
                if "uddg" in qs:
                    href = qs["uddg"][0]

            if not href or "duckduckgo" in href:
                continue

            parsed = urlparse(href)
            # Skip job sites, social media, etc.
            skip_domains = {
                "indeed", "linkedin", "facebook", "twitter",
                "instagram", "youtube", "wikipedia", "kvk.nl",
                "jooble", "glassdoor", "nationalevacaturebank",
            }
            if any(d in parsed.netloc.lower() for d in skip_domains):
                continue

            return f"{parsed.scheme}://{parsed.netloc}"

    except requests.exceptions.RequestException as e:
        logger.debug("Fout bij zoeken website voor %s: %s", company, e)

    return None


def scrape_contact_from_website(
    url: str, session: requests.Session
) -> dict[str, str | None]:
    """Scrape phone and email from a company's website homepage."""
    result = {"telefoon": None, "email": None}

    try:
        time.sleep(REQUEST_DELAY)
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            return result

        text = resp.text

        # Find emails
        emails = EMAIL_PATTERN.findall(text)
        for email in emails:
            if _is_valid_email(email):
                result["email"] = email.lower()
                break

        # Find phone numbers
        phones = PHONE_PATTERN.findall(text)
        for phone in phones:
            if _is_valid_phone(phone):
                result["telefoon"] = _clean_phone(phone)
                break

        # Also check common contact page URLs
        if not result["email"] or not result["telefoon"]:
            for contact_path in ["/contact", "/over-ons", "/about"]:
                contact_url = urljoin(url, contact_path)
                try:
                    time.sleep(REQUEST_DELAY)
                    resp = session.get(contact_url, timeout=10)
                    if resp.status_code == 200:
                        contact_text = resp.text
                        if not result["email"]:
                            for email in EMAIL_PATTERN.findall(contact_text):
                                if _is_valid_email(email):
                                    result["email"] = email.lower()
                                    break
                        if not result["telefoon"]:
                            for phone in PHONE_PATTERN.findall(contact_text):
                                if _is_valid_phone(phone):
                                    result["telefoon"] = _clean_phone(phone)
                                    break
                    if result["email"] and result["telefoon"]:
                        break
                except requests.exceptions.RequestException:
                    continue

    except requests.exceptions.RequestException as e:
        logger.debug("Fout bij scrapen contactinfo van %s: %s", url, e)

    return result


def enrich_leads(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich leads DataFrame with company contact information.

    Only processes companies that don't already have contact info.
    """
    if df.empty:
        logger.info("Geen leads om te verrijken")
        return df

    session = requests.Session()
    session.headers.update(HEADERS)

    # Get unique companies that need enrichment
    needs_enrichment = df[
        df["website"].isna() | (df["website"] == "")
    ]["bedrijf"].dropna().unique()

    logger.info(
        "%d unieke bedrijven om te verrijken", len(needs_enrichment)
    )

    # Cache results per company
    company_info: dict[str, dict] = {}

    for i, company in enumerate(needs_enrichment):
        if not company.strip():
            continue

        logger.info(
            "[%d/%d] Zoek contactinfo voor: %s",
            i + 1, len(needs_enrichment), company,
        )

        info = {"website": None, "telefoon": None, "email": None}

        # Find website
        website = search_company_website(company, session)
        if website:
            info["website"] = website
            logger.info("  Website gevonden: %s", website)

            # Scrape contact info from website
            contact = scrape_contact_from_website(website, session)
            info.update({k: v for k, v in contact.items() if v})

            if info["telefoon"]:
                logger.info("  Telefoon: %s", info["telefoon"])
            if info["email"]:
                logger.info("  Email: %s", info["email"])

        company_info[company] = info

    # Apply enrichment to DataFrame
    for company, info in company_info.items():
        mask = df["bedrijf"] == company
        for field in ["website", "telefoon", "email"]:
            if info.get(field):
                # Only fill where currently empty
                empty_mask = mask & (df[field].isna() | (df[field] == ""))
                df.loc[empty_mask, field] = info[field]

    enriched_count = df["website"].notna().sum()
    logger.info(
        "Verrijking compleet: %d/%d leads hebben nu contactinfo",
        enriched_count, len(df),
    )

    return df
