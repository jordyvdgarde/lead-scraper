"""Job listing scraper for Dutch job sites."""

import logging
import time
import re
from datetime import datetime
from urllib.parse import urljoin, quote_plus
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from config import (
    HEADERS,
    REQUEST_DELAY,
    MAX_RETRIES,
    RETRY_BACKOFF,
    SEARCH_QUERY,
    get_province_for_location,
)

logger = logging.getLogger(__name__)

# Cache for robots.txt parsers
_robots_cache: dict[str, RobotFileParser] = {}


def check_robots_txt(url: str, user_agent: str = "*") -> bool:
    """Check if a URL is allowed by the site's robots.txt."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    if base not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(f"{base}/robots.txt")
        try:
            rp.read()
        except Exception:
            logger.debug("Kon robots.txt niet laden voor %s, ga door", base)
            return True
        _robots_cache[base] = rp

    return _robots_cache[base].can_fetch(user_agent, url)


def create_session() -> requests.Session:
    """Create a requests session with proper headers."""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def get_page(url: str, session: requests.Session) -> BeautifulSoup | None:
    """Fetch a page with retry logic and robots.txt compliance."""
    if not check_robots_txt(url):
        logger.warning("Geblokkeerd door robots.txt: %s", url)
        return None

    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_DELAY)
            response = session.get(url, timeout=15)

            if response.status_code == 429:
                wait = RETRY_BACKOFF ** (attempt + 1)
                logger.warning("Rate limited (429), wacht %ds...", wait)
                time.sleep(wait)
                continue

            if response.status_code == 403:
                logger.warning("Toegang geweigerd (403): %s", url)
                return None

            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")

        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** (attempt + 1)
                logger.warning("Fout bij ophalen %s: %s, retry in %ds", url, e, wait)
                time.sleep(wait)
            else:
                logger.error("Kan %s niet ophalen na %d pogingen: %s", url, MAX_RETRIES, e)
    return None


def _parse_dutch_date(date_str: str) -> str:
    """Try to parse a Dutch date string into YYYY-MM-DD format."""
    if not date_str:
        return ""

    date_str = date_str.strip().lower()

    # "vandaag" / "today"
    if "vandaag" in date_str or "today" in date_str:
        return datetime.now().strftime("%Y-%m-%d")

    # "gisteren" / "yesterday"
    if "gisteren" in date_str or "yesterday" in date_str:
        from datetime import timedelta
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # "X dagen geleden" / "X days ago"
    days_match = re.search(r"(\d+)\s*dag", date_str)
    if days_match:
        from datetime import timedelta
        days = int(days_match.group(1))
        return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Try direct date parsing
    for fmt in ("%d-%m-%Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str


def scrape_indeed(query: str, session: requests.Session, max_pages: int = 5):
    """Scrape job listings from Indeed.nl."""
    base_url = "https://nl.indeed.com"
    logger.info("Start scraping Indeed.nl voor '%s'...", query)

    for page in range(max_pages):
        start = page * 10
        search_url = (
            f"{base_url}/jobs?q={quote_plus(query)}"
            f"&l=Nederland&start={start}"
        )

        soup = get_page(search_url, session)
        if not soup:
            logger.warning("Indeed pagina %d kon niet geladen worden", page + 1)
            break

        # Indeed uses various class patterns for job cards
        job_cards = soup.find_all("div", class_=re.compile(r"job_seen_beacon|cardOutline|result"))
        if not job_cards:
            # Try alternative selectors
            job_cards = soup.find_all("a", class_=re.compile(r"tapItem|jcs-JobTitle"))

        if not job_cards:
            logger.info("Geen resultaten meer op Indeed pagina %d", page + 1)
            break

        logger.info("Indeed pagina %d: %d vacatures gevonden", page + 1, len(job_cards))

        for card in job_cards:
            try:
                # Title and link
                title_elem = card.find("h2") or card.find("a", class_=re.compile(r"Title|title"))
                if not title_elem:
                    continue

                link_elem = title_elem.find("a") if title_elem.name != "a" else title_elem
                if not link_elem or not link_elem.get("href"):
                    link_elem = card.find("a", href=True)

                if not link_elem:
                    continue

                title = title_elem.get_text(strip=True)
                link = link_elem["href"]
                if link.startswith("/"):
                    link = urljoin(base_url, link)

                # Company
                company_elem = (
                    card.find("span", {"data-testid": "company-name"})
                    or card.find("span", class_=re.compile(r"company"))
                    or card.find("a", class_=re.compile(r"company"))
                )
                company = company_elem.get_text(strip=True) if company_elem else ""

                # Location
                location_elem = (
                    card.find("div", {"data-testid": "text-location"})
                    or card.find("div", class_=re.compile(r"location"))
                    or card.find("span", class_=re.compile(r"location"))
                )
                location = location_elem.get_text(strip=True) if location_elem else ""

                # Date
                date_elem = (
                    card.find("span", class_=re.compile(r"date"))
                    or card.find("span", {"data-testid": re.compile(r"date")})
                )
                date_posted = _parse_dutch_date(
                    date_elem.get_text(strip=True) if date_elem else ""
                )

                yield {
                    "bedrijf": company,
                    "functietitel": title,
                    "locatie": location,
                    "provincie": get_province_for_location(location),
                    "link": link,
                    "datum_geplaatst": date_posted,
                    "telefoon": None,
                    "email": None,
                    "website": None,
                    "datum_gescraped": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            except Exception as e:
                logger.debug("Fout bij parsen Indeed vacature: %s", e)
                continue


def scrape_jooble(query: str, session: requests.Session, max_pages: int = 5):
    """Scrape job listings from Jooble.org (Dutch version)."""
    base_url = "https://nl.jooble.org"
    logger.info("Start scraping Jooble.org voor '%s'...", query)

    for page in range(1, max_pages + 1):
        search_url = f"{base_url}/SearchResult?ukw={quote_plus(query)}&lokw=Nederland&p={page}"

        soup = get_page(search_url, session)
        if not soup:
            logger.warning("Jooble pagina %d kon niet geladen worden", page)
            break

        # Jooble job cards
        job_cards = soup.find_all("article") or soup.find_all(
            "div", class_=re.compile(r"vacancy|job-item|_card", re.I)
        )

        if not job_cards:
            logger.info("Geen resultaten meer op Jooble pagina %d", page)
            break

        logger.info("Jooble pagina %d: %d vacatures gevonden", page, len(job_cards))

        for card in job_cards:
            try:
                # Title and link
                title_elem = card.find("a", class_=re.compile(r"title|header|link", re.I))
                if not title_elem:
                    title_elem = card.find("h2") or card.find("h3")
                    if title_elem:
                        link_tag = title_elem.find("a")
                        if link_tag:
                            title_elem = link_tag

                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
                if link.startswith("/"):
                    link = urljoin(base_url, link)
                if not link:
                    continue

                # Company
                company_elem = card.find(
                    "span", class_=re.compile(r"company|employer", re.I)
                ) or card.find("p", class_=re.compile(r"company|employer", re.I))
                company = company_elem.get_text(strip=True) if company_elem else ""

                # Location
                location_elem = card.find(
                    "span", class_=re.compile(r"location|city|place", re.I)
                ) or card.find("div", class_=re.compile(r"location|city", re.I))
                location = location_elem.get_text(strip=True) if location_elem else ""

                # Date
                date_elem = card.find(
                    "span", class_=re.compile(r"date|time|posted", re.I)
                ) or card.find("time")
                raw_date = ""
                if date_elem:
                    raw_date = date_elem.get("datetime", "") or date_elem.get_text(strip=True)
                date_posted = _parse_dutch_date(raw_date)

                yield {
                    "bedrijf": company,
                    "functietitel": title,
                    "locatie": location,
                    "provincie": get_province_for_location(location),
                    "link": link,
                    "datum_geplaatst": date_posted,
                    "telefoon": None,
                    "email": None,
                    "website": None,
                    "datum_gescraped": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            except Exception as e:
                logger.debug("Fout bij parsen Jooble vacature: %s", e)
                continue


def scrape_nationalevacaturebank(
    query: str, session: requests.Session, max_pages: int = 5
):
    """Scrape job listings from Nationale Vacaturebank."""
    base_url = "https://www.nationalevacaturebank.nl"
    logger.info("Start scraping Nationale Vacaturebank voor '%s'...", query)

    for page in range(1, max_pages + 1):
        search_url = (
            f"{base_url}/vacature/zoeken"
            f"?query={quote_plus(query)}&page={page}"
        )

        soup = get_page(search_url, session)
        if not soup:
            logger.warning("NVB pagina %d kon niet geladen worden", page)
            break

        job_cards = soup.find_all(
            "div", class_=re.compile(r"vacancy|job|result-item", re.I)
        ) or soup.find_all("article")

        if not job_cards:
            logger.info("Geen resultaten meer op NVB pagina %d", page)
            break

        logger.info("NVB pagina %d: %d vacatures gevonden", page, len(job_cards))

        for card in job_cards:
            try:
                title_elem = card.find("a", class_=re.compile(r"title|link", re.I))
                if not title_elem:
                    heading = card.find("h2") or card.find("h3")
                    if heading:
                        title_elem = heading.find("a") or heading

                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
                if link.startswith("/"):
                    link = urljoin(base_url, link)
                if not link:
                    continue

                company_elem = card.find(
                    class_=re.compile(r"company|employer|organization", re.I)
                )
                company = company_elem.get_text(strip=True) if company_elem else ""

                location_elem = card.find(
                    class_=re.compile(r"location|city|place", re.I)
                )
                location = location_elem.get_text(strip=True) if location_elem else ""

                date_elem = card.find(class_=re.compile(r"date|time", re.I))
                raw_date = ""
                if date_elem:
                    raw_date = date_elem.get("datetime", "") or date_elem.get_text(strip=True)
                date_posted = _parse_dutch_date(raw_date)

                yield {
                    "bedrijf": company,
                    "functietitel": title,
                    "locatie": location,
                    "provincie": get_province_for_location(location),
                    "link": link,
                    "datum_geplaatst": date_posted,
                    "telefoon": None,
                    "email": None,
                    "website": None,
                    "datum_gescraped": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            except Exception as e:
                logger.debug("Fout bij parsen NVB vacature: %s", e)
                continue


def scrape_all(
    query: str | None = None,
    province: str | None = None,
    max_pages: int = 5,
    sources: list[str] | None = None,
) -> list[dict]:
    """
    Scrape all configured sources and return combined results.

    Args:
        query: Search query (defaults to SEARCH_QUERY from config)
        province: Optional province filter
        max_pages: Maximum pages per source
        sources: List of sources to use ('indeed', 'jooble', 'nvb')
    """
    query = query or SEARCH_QUERY
    sources = sources or ["indeed", "jooble", "nvb"]
    session = create_session()
    all_leads = []
    seen_links = set()

    source_map = {
        "indeed": scrape_indeed,
        "jooble": scrape_jooble,
        "nvb": scrape_nationalevacaturebank,
    }

    for source_name in sources:
        scraper_fn = source_map.get(source_name)
        if not scraper_fn:
            logger.warning("Onbekende bron: %s", source_name)
            continue

        try:
            for lead in scraper_fn(query, session, max_pages):
                # Deduplicate by link
                if lead["link"] in seen_links:
                    continue
                seen_links.add(lead["link"])

                # Province filter
                if province and lead.get("provincie") != province:
                    continue

                all_leads.append(lead)
        except Exception as e:
            logger.error("Fout bij scrapen van %s: %s", source_name, e)
            continue

    logger.info("Totaal: %d unieke vacatures gevonden", len(all_leads))
    return all_leads
