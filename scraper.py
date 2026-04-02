"""Job listing scraper for Dutch job sites.

Default sources: Nationale Vacaturebank, Werkzoeken.nl, Randstad.nl
Optional sources: Indeed.nl, Jooble.org (prone to blocking/CAPTCHA)
"""

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

_robots_cache: dict[str, RobotFileParser] = {}


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------
def _is_proxy_error(error: Exception) -> bool:
    err_str = str(error).lower()
    return any(kw in err_str for kw in ["proxy", "tunnel", "403 forbidden", "407"])


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
    """Fetch a page with retry logic, robots.txt compliance, proxy detection."""
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

        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
            if isinstance(e, requests.exceptions.ProxyError) or _is_proxy_error(e):
                logger.error(
                    "Proxy/firewall blokkeert %s — schakel proxy uit of "
                    "gebruik een ander netwerk.", urlparse(url).netloc,
                )
                return None
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** (attempt + 1)
                logger.warning("Verbindingsfout %s, retry in %ds", urlparse(url).netloc, wait)
                time.sleep(wait)
            else:
                logger.error("Kan %s niet bereiken na %d pogingen", urlparse(url).netloc, MAX_RETRIES)

        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** (attempt + 1)
                logger.warning("Fout bij %s: %s, retry in %ds", urlparse(url).netloc, e, wait)
                time.sleep(wait)
            else:
                logger.error("Kan %s niet ophalen na %d pogingen: %s", url, MAX_RETRIES, e)

    return None


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
_DUTCH_MONTHS = {
    "januari": "01", "februari": "02", "maart": "03", "april": "04",
    "mei": "05", "juni": "06", "juli": "07", "augustus": "08",
    "september": "09", "oktober": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mrt": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "okt": "10", "nov": "11", "dec": "12",
}


def _parse_dutch_date(date_str: str) -> str:
    """Parse Dutch date string into YYYY-MM-DD format."""
    if not date_str:
        return ""

    date_str = date_str.strip().lower()
    today = datetime.now()

    if any(w in date_str for w in ("vandaag", "today", "zojuist", "net geplaatst")):
        return today.strftime("%Y-%m-%d")

    if "gisteren" in date_str or "yesterday" in date_str:
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    days_match = re.search(r"(\d+)\s*dag", date_str)
    if days_match:
        return (today - timedelta(days=int(days_match.group(1)))).strftime("%Y-%m-%d")

    hours_match = re.search(r"(\d+)\s*uur", date_str)
    if hours_match:
        return today.strftime("%Y-%m-%d")

    for month_name, month_num in _DUTCH_MONTHS.items():
        if month_name in date_str:
            day_match = re.search(r"(\d{1,2})", date_str)
            year_match = re.search(r"(\d{4})", date_str)
            if day_match:
                day = day_match.group(1).zfill(2)
                year = year_match.group(1) if year_match else str(today.year)
                return f"{year}-{month_num}-{day}"

    for fmt in ("%d-%m-%Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str


def _make_lead(company, title, location, link, date_posted, source):
    """Create a standardized lead dict."""
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


# ===================================================================
# SOURCE: Nationale Vacaturebank (nationalevacaturebank.nl)
# ===================================================================
def scrape_nationalevacaturebank(query, session, max_pages=5):
    """Scrape Nationale Vacaturebank search results."""
    base_url = "https://www.nationalevacaturebank.nl"
    logger.info("Scraping Nationale Vacaturebank voor '%s'...", query)

    for page in range(1, max_pages + 1):
        url = f"{base_url}/vacature/zoeken?query={quote_plus(query)}&page={page}"
        soup = get_page(url, session)
        if not soup:
            break

        # NVB renders job cards as list items or divs with vacancy data
        cards = soup.select('[class*="vacancy-item"], [class*="vacancy-card"], [class*="job-item"], article')
        if not cards:
            cards = soup.find_all("li", attrs={"data-url": True})
        if not cards:
            logger.info("NVB pagina %d: geen resultaten", page)
            break

        logger.info("NVB pagina %d: %d items gevonden", page, len(cards))

        for card in cards:
            try:
                # Title + link
                a = card.find("a", href=True)
                heading = card.find(["h2", "h3", "h4"])
                if heading and heading.find("a"):
                    a = heading.find("a")
                if not a:
                    continue

                title = (heading or a).get_text(strip=True)
                if len(title) < 4:
                    continue
                link = a["href"]
                if link.startswith("/"):
                    link = urljoin(base_url, link)

                # Company
                co = card.find(class_=re.compile(r"company|employer|organis", re.I))
                company = co.get_text(strip=True) if co else ""

                # Location
                loc = card.find(class_=re.compile(r"location|city|plaats", re.I))
                location = loc.get_text(strip=True) if loc else ""

                # Date
                dt = card.find(class_=re.compile(r"date|time|posted", re.I)) or card.find("time")
                raw = (dt.get("datetime", "") or dt.get_text(strip=True)) if dt else ""

                yield _make_lead(company, title, location, link, _parse_dutch_date(raw), "NVB")
            except Exception as e:
                logger.debug("NVB parse error: %s", e)


# ===================================================================
# SOURCE: Werkzoeken.nl
# ===================================================================
def scrape_werkzoeken(query, session, max_pages=5):
    """Scrape werkzoeken.nl search results."""
    base_url = "https://www.werkzoeken.nl"
    logger.info("Scraping Werkzoeken.nl voor '%s'...", query)

    for page in range(1, max_pages + 1):
        url = f"{base_url}/vacatures?zoekterm={quote_plus(query)}&pagina={page}"
        soup = get_page(url, session)
        if not soup:
            break

        cards = soup.select('article, [class*="vacancy-"], [class*="job-"], [class*="result-item"]')
        if not cards:
            cards = soup.find_all("div", class_=re.compile(r"card|item", re.I))
        if not cards:
            logger.info("Werkzoeken pagina %d: geen resultaten", page)
            break

        logger.info("Werkzoeken pagina %d: %d items gevonden", page, len(cards))

        for card in cards:
            try:
                heading = card.find(["h2", "h3", "h4"])
                a = (heading.find("a") if heading else None) or card.find("a", href=True)
                if not a:
                    continue

                title = (heading or a).get_text(strip=True)
                if len(title) < 4:
                    continue
                link = a["href"]
                if link.startswith("/"):
                    link = urljoin(base_url, link)

                co = card.find(class_=re.compile(r"company|employer|bedrijf", re.I))
                company = co.get_text(strip=True) if co else ""

                loc = card.find(class_=re.compile(r"location|city|plaats|locatie", re.I))
                location = loc.get_text(strip=True) if loc else ""

                dt = card.find(class_=re.compile(r"date|datum|time", re.I)) or card.find("time")
                raw = (dt.get("datetime", "") or dt.get_text(strip=True)) if dt else ""

                yield _make_lead(company, title, location, link, _parse_dutch_date(raw), "Werkzoeken")
            except Exception as e:
                logger.debug("Werkzoeken parse error: %s", e)


# ===================================================================
# SOURCE: Randstad.nl
# ===================================================================
def scrape_randstad(query, session, max_pages=5):
    """Scrape Randstad.nl search results."""
    base_url = "https://www.randstad.nl"
    logger.info("Scraping Randstad.nl voor '%s'...", query)

    for page in range(1, max_pages + 1):
        url = f"{base_url}/werkzoekende/vacatures/?searchquery={quote_plus(query)}&page={page}"
        soup = get_page(url, session)
        if not soup:
            break

        cards = soup.select(
            'article[class*="job"], article[class*="card"], '
            '[class*="job-card"], [class*="job-item"], '
            'li[class*="job"], li[class*="vacancy"]'
        )
        if not cards:
            cards = soup.find_all("article")
        if not cards:
            logger.info("Randstad pagina %d: geen resultaten", page)
            break

        logger.info("Randstad pagina %d: %d items gevonden", page, len(cards))

        for card in cards:
            try:
                heading = card.find(["h2", "h3", "h4"])
                a = (heading.find("a") if heading else None) or card.find("a", href=True)
                if not a:
                    continue

                title = (heading or a).get_text(strip=True)
                if len(title) < 4:
                    continue
                link = a["href"]
                if link.startswith("/"):
                    link = urljoin(base_url, link)

                co = card.find(class_=re.compile(r"company|employer|client", re.I))
                company = co.get_text(strip=True) if co else ""

                loc = card.find(class_=re.compile(r"location|city|place|plaats", re.I))
                location = loc.get_text(strip=True) if loc else ""

                dt = card.find(class_=re.compile(r"date|posted|time", re.I)) or card.find("time")
                raw = (dt.get("datetime", "") or dt.get_text(strip=True)) if dt else ""

                yield _make_lead(company, title, location, link, _parse_dutch_date(raw), "Randstad")
            except Exception as e:
                logger.debug("Randstad parse error: %s", e)


# ===================================================================
# SOURCE: Indeed.nl (optional — aggressive anti-scraping)
# ===================================================================
def scrape_indeed(query, session, max_pages=5):
    """Scrape Indeed.nl. Often blocked by CAPTCHA/Cloudflare."""
    base_url = "https://nl.indeed.com"
    logger.info("Scraping Indeed.nl voor '%s'...", query)

    for page in range(max_pages):
        url = f"{base_url}/jobs?q={quote_plus(query)}&l=Nederland&start={page * 10}"
        soup = get_page(url, session)
        if not soup:
            break

        cards = soup.find_all("div", class_=re.compile(r"job_seen_beacon|cardOutline|tapItem"))
        if not cards:
            cards = soup.find_all("li", class_=re.compile(r"result|job"))
        if not cards:
            text = soup.get_text().lower()
            if "captcha" in text or "blocked" in text or "verify" in text:
                logger.warning("Indeed CAPTCHA/block gedetecteerd, stop")
            else:
                logger.info("Indeed pagina %d: geen resultaten", page + 1)
            break

        logger.info("Indeed pagina %d: %d items gevonden", page + 1, len(cards))

        for card in cards:
            try:
                h2 = card.find("h2")
                a = (h2.find("a") if h2 else None) or card.find("a", href=True)
                if not a:
                    continue

                title = (h2 or a).get_text(strip=True)
                link = a["href"]
                if link.startswith("/"):
                    link = urljoin(base_url, link)

                co = (
                    card.find("span", {"data-testid": "company-name"})
                    or card.find(class_=re.compile(r"company", re.I))
                )
                company = co.get_text(strip=True) if co else ""

                loc = (
                    card.find("div", {"data-testid": "text-location"})
                    or card.find(class_=re.compile(r"location", re.I))
                )
                location = loc.get_text(strip=True) if loc else ""

                dt = card.find(class_=re.compile(r"date", re.I))
                raw = dt.get_text(strip=True) if dt else ""

                yield _make_lead(company, title, location, link, _parse_dutch_date(raw), "Indeed")
            except Exception as e:
                logger.debug("Indeed parse error: %s", e)


# ===================================================================
# SOURCE: Jooble.org/nl (optional)
# ===================================================================
def scrape_jooble(query, session, max_pages=5):
    """Scrape Jooble.org NL. May block scrapers."""
    base_url = "https://nl.jooble.org"
    logger.info("Scraping Jooble.org voor '%s'...", query)

    for page in range(1, max_pages + 1):
        url = f"{base_url}/SearchResult?ukw={quote_plus(query)}&lokw=Nederland&p={page}"
        soup = get_page(url, session)
        if not soup:
            break

        cards = soup.find_all("article") or soup.find_all(
            "div", class_=re.compile(r"vacancy|job-item|_card", re.I)
        )
        if not cards:
            logger.info("Jooble pagina %d: geen resultaten", page)
            break

        logger.info("Jooble pagina %d: %d items gevonden", page, len(cards))

        for card in cards:
            try:
                a = card.find("a", class_=re.compile(r"title|header|link", re.I))
                if not a:
                    heading = card.find(["h2", "h3"])
                    a = (heading.find("a") if heading else None) or card.find("a", href=True)
                if not a:
                    continue

                title = a.get_text(strip=True)
                link = a.get("href", "")
                if link.startswith("/"):
                    link = urljoin(base_url, link)
                if not link:
                    continue

                co = card.find(class_=re.compile(r"company|employer", re.I))
                company = co.get_text(strip=True) if co else ""

                loc = card.find(class_=re.compile(r"location|city|place", re.I))
                location = loc.get_text(strip=True) if loc else ""

                dt = card.find(class_=re.compile(r"date|time|posted", re.I)) or card.find("time")
                raw = (dt.get("datetime", "") or dt.get_text(strip=True)) if dt else ""

                yield _make_lead(company, title, location, link, _parse_dutch_date(raw), "Jooble")
            except Exception as e:
                logger.debug("Jooble parse error: %s", e)


# ===================================================================
# Dispatcher
# ===================================================================
SOURCE_MAP = {
    "nvb": scrape_nationalevacaturebank,
    "werkzoeken": scrape_werkzoeken,
    "randstad": scrape_randstad,
    "indeed": scrape_indeed,
    "jooble": scrape_jooble,
}

# Default sources — the ones that reliably allow scraping
DEFAULT_SOURCES = ["nvb", "werkzoeken", "randstad"]
ALL_SOURCES = list(SOURCE_MAP.keys())


def scrape_all(
    query: str | None = None,
    province: str | None = None,
    max_pages: int = 5,
    sources: list[str] | None = None,
) -> list[dict]:
    """Scrape all configured sources and return combined, deduplicated results."""
    query = query or SEARCH_QUERY
    sources = sources or DEFAULT_SOURCES
    session = create_session()
    all_leads = []
    seen_links: set[str] = set()
    failed_sources = []

    for source_name in sources:
        fn = SOURCE_MAP.get(source_name)
        if not fn:
            logger.warning("Onbekende bron: %s (kies uit: %s)", source_name, ", ".join(ALL_SOURCES))
            continue

        try:
            count = 0
            for lead in fn(query, session, max_pages):
                if lead["link"] in seen_links:
                    continue
                seen_links.add(lead["link"])
                if province and lead.get("provincie") != province:
                    continue
                all_leads.append(lead)
                count += 1

            if count > 0:
                logger.info("%s: %d vacatures opgeleverd", source_name, count)
            else:
                failed_sources.append(source_name)

        except Exception as e:
            logger.error("Fout bij %s: %s", source_name, e)
            failed_sources.append(source_name)

    if failed_sources and not all_leads:
        logger.warning(
            "Geen resultaten. Mislukte bronnen: %s. "
            "Oorzaken: proxy/firewall, CAPTCHA, of gewijzigde site-structuur. "
            "Draai het script op een netwerk zonder proxy.",
            ", ".join(failed_sources),
        )

    logger.info("Totaal: %d unieke vacatures gevonden", len(all_leads))
    return all_leads
