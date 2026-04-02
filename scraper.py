"""Job listing scraper for Dutch job sites."""

import logging
import time
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, quote_plus, urlparse
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


def _is_proxy_error(error: Exception) -> bool:
    """Detect if an error is caused by a proxy blocking the request."""
    err_str = str(error).lower()
    return any(
        kw in err_str
        for kw in ["proxy", "tunnel", "403 forbidden", "407"]
    )


def check_robots_txt(url: str, user_agent: str = "*") -> bool:
    """Check if a URL is allowed by the site's robots.txt."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    if base not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(f"{base}/robots.txt")
        try:
            rp.read()
        except Exception:
            logger.debug("Kon robots.txt niet laden voor %s, sta toe", base)
            return True
        _robots_cache[base] = rp

    return _robots_cache[base].can_fetch(user_agent, url)


def create_session() -> requests.Session:
    """Create a requests session with realistic browser headers."""
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

        except requests.exceptions.ProxyError as e:
            logger.error(
                "Proxy blokkeert verbinding naar %s. "
                "Controleer je proxy-instellingen of schakel de proxy uit.",
                urlparse(url).netloc,
            )
            return None

        except requests.exceptions.ConnectionError as e:
            if _is_proxy_error(e):
                logger.error(
                    "Proxy blokkeert verbinding naar %s. "
                    "Controleer je proxy-instellingen of schakel de proxy uit.",
                    urlparse(url).netloc,
                )
                return None
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** (attempt + 1)
                logger.warning(
                    "Verbindingsfout %s: %s, retry in %ds",
                    url, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Kan %s niet bereiken na %d pogingen: %s",
                    url, MAX_RETRIES, e,
                )

        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** (attempt + 1)
                logger.warning(
                    "Fout bij ophalen %s: %s, retry in %ds", url, e, wait
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Kan %s niet ophalen na %d pogingen: %s",
                    url, MAX_RETRIES, e,
                )
    return None


def _parse_dutch_date(date_str: str) -> str:
    """Try to parse a Dutch date string into YYYY-MM-DD format."""
    if not date_str:
        return ""

    date_str = date_str.strip().lower()

    if "vandaag" in date_str or "today" in date_str or "zojuist" in date_str:
        return datetime.now().strftime("%Y-%m-%d")

    if "gisteren" in date_str or "yesterday" in date_str:
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # "X dagen geleden" / "X days ago"
    days_match = re.search(r"(\d+)\s*dag", date_str)
    if days_match:
        days = int(days_match.group(1))
        return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # "X uur geleden"
    hours_match = re.search(r"(\d+)\s*uur", date_str)
    if hours_match:
        return datetime.now().strftime("%Y-%m-%d")

    # Dutch month names
    dutch_months = {
        "januari": "01", "februari": "02", "maart": "03", "april": "04",
        "mei": "05", "juni": "06", "juli": "07", "augustus": "08",
        "september": "09", "oktober": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mrt": "03", "apr": "04",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09",
        "okt": "10", "nov": "11", "dec": "12",
    }
    for month_name, month_num in dutch_months.items():
        if month_name in date_str:
            day_match = re.search(r"(\d{1,2})", date_str)
            year_match = re.search(r"(\d{4})", date_str)
            if day_match:
                day = day_match.group(1).zfill(2)
                year = year_match.group(1) if year_match else str(datetime.now().year)
                return f"{year}-{month_num}-{day}"

    # Try standard date formats
    for fmt in ("%d-%m-%Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str


def _make_lead(
    company: str,
    title: str,
    location: str,
    link: str,
    date_posted: str,
    source: str,
) -> dict:
    """Create a standardized lead dictionary."""
    return {
        "bedrijf": company,
        "functietitel": title,
        "locatie": location,
        "provincie": get_province_for_location(location),
        "link": link,
        "datum_geplaatst": date_posted,
        "bron": source,
        "telefoon": None,
        "email": None,
        "website": None,
        "datum_gescraped": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ---------------------------------------------------------------------------
# Indeed.nl
# ---------------------------------------------------------------------------
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
        job_cards = soup.find_all(
            "div", class_=re.compile(r"job_seen_beacon|cardOutline|result|tapItem")
        )
        if not job_cards:
            job_cards = soup.find_all("li", class_=re.compile(r"result|job"))
        if not job_cards:
            # Check if we got a CAPTCHA or block page
            page_text = soup.get_text().lower()
            if "captcha" in page_text or "blocked" in page_text:
                logger.warning("Indeed CAPTCHA/block gedetecteerd, stop")
                break
            logger.info("Geen resultaten meer op Indeed pagina %d", page + 1)
            break

        logger.info(
            "Indeed pagina %d: %d vacatures gevonden", page + 1, len(job_cards)
        )

        for card in job_cards:
            try:
                # Title and link
                title_elem = (
                    card.find("h2", class_=re.compile(r"title|Title"))
                    or card.find("h2")
                    or card.find("a", class_=re.compile(r"Title|title"))
                )
                if not title_elem:
                    continue

                link_elem = (
                    title_elem.find("a") if title_elem.name != "a" else title_elem
                )
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
                    or card.find("span", class_=re.compile(r"company", re.I))
                    or card.find("a", {"data-tn-element": "companyName"})
                )
                company = company_elem.get_text(strip=True) if company_elem else ""

                # Location
                location_elem = (
                    card.find("div", {"data-testid": "text-location"})
                    or card.find("div", class_=re.compile(r"location", re.I))
                    or card.find("span", class_=re.compile(r"location", re.I))
                )
                location = location_elem.get_text(strip=True) if location_elem else ""

                # Date
                date_elem = (
                    card.find("span", class_=re.compile(r"date", re.I))
                    or card.find("span", {"data-testid": re.compile(r"date")})
                )
                date_posted = _parse_dutch_date(
                    date_elem.get_text(strip=True) if date_elem else ""
                )

                yield _make_lead(company, title, location, link, date_posted, "Indeed")

            except Exception as e:
                logger.debug("Fout bij parsen Indeed vacature: %s", e)
                continue


# ---------------------------------------------------------------------------
# Jooble.org (NL)
# ---------------------------------------------------------------------------
def scrape_jooble(query: str, session: requests.Session, max_pages: int = 5):
    """Scrape job listings from Jooble.org (Dutch version)."""
    base_url = "https://nl.jooble.org"
    logger.info("Start scraping Jooble.org voor '%s'...", query)

    for page in range(1, max_pages + 1):
        search_url = (
            f"{base_url}/SearchResult"
            f"?ukw={quote_plus(query)}&lokw=Nederland&p={page}"
        )

        soup = get_page(search_url, session)
        if not soup:
            logger.warning("Jooble pagina %d kon niet geladen worden", page)
            break

        job_cards = soup.find_all("article") or soup.find_all(
            "div", class_=re.compile(r"vacancy|job-item|_card", re.I)
        )

        if not job_cards:
            logger.info("Geen resultaten meer op Jooble pagina %d", page)
            break

        logger.info(
            "Jooble pagina %d: %d vacatures gevonden", page, len(job_cards)
        )

        for card in job_cards:
            try:
                title_elem = card.find(
                    "a", class_=re.compile(r"title|header|link", re.I)
                )
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
                    class_=re.compile(r"company|employer", re.I)
                )
                company = company_elem.get_text(strip=True) if company_elem else ""

                location_elem = card.find(
                    class_=re.compile(r"location|city|place", re.I)
                )
                location = (
                    location_elem.get_text(strip=True) if location_elem else ""
                )

                date_elem = card.find(
                    class_=re.compile(r"date|time|posted", re.I)
                ) or card.find("time")
                raw_date = ""
                if date_elem:
                    raw_date = (
                        date_elem.get("datetime", "")
                        or date_elem.get_text(strip=True)
                    )

                yield _make_lead(
                    company, title, location, link,
                    _parse_dutch_date(raw_date), "Jooble",
                )

            except Exception as e:
                logger.debug("Fout bij parsen Jooble vacature: %s", e)
                continue


# ---------------------------------------------------------------------------
# Nationale Vacaturebank
# ---------------------------------------------------------------------------
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

        logger.info(
            "NVB pagina %d: %d vacatures gevonden", page, len(job_cards)
        )

        for card in job_cards:
            try:
                title_elem = card.find(
                    "a", class_=re.compile(r"title|link", re.I)
                )
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
                location = (
                    location_elem.get_text(strip=True) if location_elem else ""
                )

                date_elem = card.find(class_=re.compile(r"date|time", re.I))
                raw_date = ""
                if date_elem:
                    raw_date = (
                        date_elem.get("datetime", "")
                        or date_elem.get_text(strip=True)
                    )

                yield _make_lead(
                    company, title, location, link,
                    _parse_dutch_date(raw_date), "NVB",
                )

            except Exception as e:
                logger.debug("Fout bij parsen NVB vacature: %s", e)
                continue


# ---------------------------------------------------------------------------
# Werkzoeken.nl
# ---------------------------------------------------------------------------
def scrape_werkzoeken(
    query: str, session: requests.Session, max_pages: int = 5
):
    """Scrape job listings from werkzoeken.nl."""
    base_url = "https://www.werkzoeken.nl"
    logger.info("Start scraping Werkzoeken.nl voor '%s'...", query)

    for page in range(1, max_pages + 1):
        search_url = (
            f"{base_url}/vacatures"
            f"?zoekterm={quote_plus(query)}&pagina={page}"
        )

        soup = get_page(search_url, session)
        if not soup:
            logger.warning("Werkzoeken pagina %d kon niet geladen worden", page)
            break

        job_cards = soup.find_all(
            "div", class_=re.compile(r"vacancy|job|result|card", re.I)
        ) or soup.find_all("article") or soup.find_all("li", class_=re.compile(r"vacancy|result", re.I))

        if not job_cards:
            logger.info("Geen resultaten meer op Werkzoeken pagina %d", page)
            break

        logger.info(
            "Werkzoeken pagina %d: %d vacatures gevonden", page, len(job_cards)
        )

        for card in job_cards:
            try:
                title_elem = card.find("a", href=True)
                if not title_elem:
                    heading = card.find("h2") or card.find("h3")
                    if heading:
                        title_elem = heading.find("a") or heading
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                if len(title) < 5:
                    continue

                link = title_elem.get("href", "")
                if link.startswith("/"):
                    link = urljoin(base_url, link)
                if not link:
                    continue

                company_elem = card.find(
                    class_=re.compile(r"company|employer|bedrijf", re.I)
                )
                company = company_elem.get_text(strip=True) if company_elem else ""

                location_elem = card.find(
                    class_=re.compile(r"location|city|plaats|locatie", re.I)
                )
                location = (
                    location_elem.get_text(strip=True) if location_elem else ""
                )

                date_elem = card.find(
                    class_=re.compile(r"date|datum|time", re.I)
                )
                raw_date = ""
                if date_elem:
                    raw_date = (
                        date_elem.get("datetime", "")
                        or date_elem.get_text(strip=True)
                    )

                yield _make_lead(
                    company, title, location, link,
                    _parse_dutch_date(raw_date), "Werkzoeken",
                )

            except Exception as e:
                logger.debug("Fout bij parsen Werkzoeken vacature: %s", e)
                continue


# ---------------------------------------------------------------------------
# Randstad.nl
# ---------------------------------------------------------------------------
def scrape_randstad(
    query: str, session: requests.Session, max_pages: int = 5
):
    """Scrape job listings from Randstad.nl."""
    base_url = "https://www.randstad.nl"
    logger.info("Start scraping Randstad.nl voor '%s'...", query)

    for page in range(1, max_pages + 1):
        search_url = (
            f"{base_url}/werkzoekende/vacatures/"
            f"?searchquery={quote_plus(query)}&page={page}"
        )

        soup = get_page(search_url, session)
        if not soup:
            logger.warning("Randstad pagina %d kon niet geladen worden", page)
            break

        # Randstad uses structured job cards
        job_cards = soup.find_all(
            "article", class_=re.compile(r"job|vacancy|card", re.I)
        ) or soup.find_all(
            "div", class_=re.compile(r"job-card|vacancy-card|search-result", re.I)
        ) or soup.find_all("li", class_=re.compile(r"job|vacancy", re.I))

        if not job_cards:
            logger.info("Geen resultaten meer op Randstad pagina %d", page)
            break

        logger.info(
            "Randstad pagina %d: %d vacatures gevonden", page, len(job_cards)
        )

        for card in job_cards:
            try:
                title_elem = card.find("a", href=True)
                if not title_elem:
                    heading = card.find("h2") or card.find("h3")
                    if heading:
                        title_elem = heading.find("a") or heading
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                if len(title) < 5:
                    continue

                link = title_elem.get("href", "")
                if link.startswith("/"):
                    link = urljoin(base_url, link)
                if not link:
                    continue

                company_elem = card.find(
                    class_=re.compile(r"company|employer|client", re.I)
                )
                company = company_elem.get_text(strip=True) if company_elem else "Randstad"

                location_elem = card.find(
                    class_=re.compile(r"location|city|place", re.I)
                )
                location = (
                    location_elem.get_text(strip=True) if location_elem else ""
                )

                date_elem = card.find(
                    class_=re.compile(r"date|posted|time", re.I)
                )
                raw_date = ""
                if date_elem:
                    raw_date = (
                        date_elem.get("datetime", "")
                        or date_elem.get_text(strip=True)
                    )

                yield _make_lead(
                    company, title, location, link,
                    _parse_dutch_date(raw_date), "Randstad",
                )

            except Exception as e:
                logger.debug("Fout bij parsen Randstad vacature: %s", e)
                continue


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
SOURCE_MAP = {
    "indeed": scrape_indeed,
    "jooble": scrape_jooble,
    "nvb": scrape_nationalevacaturebank,
    "werkzoeken": scrape_werkzoeken,
    "randstad": scrape_randstad,
}

ALL_SOURCES = list(SOURCE_MAP.keys())


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
        sources: List of source keys (see ALL_SOURCES)
    """
    query = query or SEARCH_QUERY
    sources = sources or ALL_SOURCES
    session = create_session()
    all_leads = []
    seen_links = set()
    failed_sources = []

    for source_name in sources:
        scraper_fn = SOURCE_MAP.get(source_name)
        if not scraper_fn:
            logger.warning("Onbekende bron: %s", source_name)
            continue

        try:
            source_count = 0
            for lead in scraper_fn(query, session, max_pages):
                if lead["link"] in seen_links:
                    continue
                seen_links.add(lead["link"])

                if province and lead.get("provincie") != province:
                    continue

                all_leads.append(lead)
                source_count += 1

            if source_count > 0:
                logger.info(
                    "%s: %d vacatures opgeleverd", source_name, source_count
                )
            else:
                failed_sources.append(source_name)

        except Exception as e:
            logger.error("Fout bij scrapen van %s: %s", source_name, e)
            failed_sources.append(source_name)
            continue

    if failed_sources and not all_leads:
        logger.warning(
            "Geen resultaten van bronnen: %s. "
            "Mogelijke oorzaken: proxy/firewall blokkade, CAPTCHA, of site-wijziging. "
            "Probeer het script op een andere machine of netwerk.",
            ", ".join(failed_sources),
        )

    logger.info("Totaal: %d unieke vacatures gevonden", len(all_leads))
    return all_leads
