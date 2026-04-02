"""Job listing scraper using SerpAPI (Google Jobs) as primary source.

SerpAPI provides structured JSON from Google Jobs — no HTML parsing,
no CAPTCHA blocks, no robots.txt issues. Requires a free API key from
serpapi.com (100 searches/month free).

Fallback HTML scrapers for NVB, Werkzoeken, and Randstad are kept
for use without an API key.
"""

import logging
import os
import re
import time
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


# ===================================================================
# Shared helpers
# ===================================================================
def _is_proxy_error(error: Exception) -> bool:
    err_str = str(error).lower()
    return any(kw in err_str for kw in ["proxy", "tunnel", "403 forbidden", "407"])


def check_robots_txt(url: str, user_agent: str = "*") -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(f"{base}/robots.txt")
        try:
            rp.read()
        except Exception:
            return True
        _robots_cache[base] = rp
    return _robots_cache[base].can_fetch(user_agent, url)


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def get_page(url: str, session: requests.Session) -> BeautifulSoup | None:
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
                logger.error("Proxy/firewall blokkeert %s", urlparse(url).netloc)
                return None
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF ** (attempt + 1))
            else:
                logger.error("Kan %s niet bereiken", urlparse(url).netloc)
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF ** (attempt + 1))
            else:
                logger.error("Kan %s niet ophalen: %s", url, e)
    return None


# ===================================================================
# Date parsing
# ===================================================================
_DUTCH_MONTHS = {
    "januari": "01", "februari": "02", "maart": "03", "april": "04",
    "mei": "05", "juni": "06", "juli": "07", "augustus": "08",
    "september": "09", "oktober": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mrt": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "okt": "10", "nov": "11", "dec": "12",
}


def _parse_dutch_date(date_str: str) -> str:
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

    hours_match = re.search(r"(\d+)\s*(uur|hour)", date_str)
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


def _parse_serpapi_date(date_str: str) -> str:
    """Parse date strings from SerpAPI (e.g. '3 days ago', 'Posted 1 day ago')."""
    if not date_str:
        return ""
    date_str = date_str.strip().lower()
    today = datetime.now()

    if "just" in date_str or "today" in date_str:
        return today.strftime("%Y-%m-%d")

    days = re.search(r"(\d+)\s*day", date_str)
    if days:
        return (today - timedelta(days=int(days.group(1)))).strftime("%Y-%m-%d")

    hours = re.search(r"(\d+)\s*hour", date_str)
    if hours:
        return today.strftime("%Y-%m-%d")

    # Try Dutch parsing as fallback
    return _parse_dutch_date(date_str)


def _make_lead(company, title, location, link, date_posted, source):
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


def _get_serpapi_key() -> str | None:
    """Get SerpAPI key from environment or .env file."""
    key = os.environ.get("SERPAPI_KEY") or os.environ.get("SERPAPI_API_KEY")
    if key:
        return key

    # Try .env file
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k in ("SERPAPI_KEY", "SERPAPI_API_KEY"):
                    return v
    return None


# ===================================================================
# PRIMARY SOURCE: SerpAPI — Google Jobs
# ===================================================================
def scrape_serpapi(query: str, session: requests.Session, max_pages: int = 5):
    """
    Fetch job listings via SerpAPI's Google Jobs engine.

    This is the most reliable source — it queries Google Jobs and returns
    structured JSON. No HTML parsing needed.

    Free tier: 100 searches/month at serpapi.com
    """
    api_key = _get_serpapi_key()
    if not api_key:
        logger.error(
            "Geen SerpAPI key gevonden. "
            "Stel SERPAPI_KEY in als environment variable of in .env bestand. "
            "Gratis key aanmaken op: https://serpapi.com (100 zoekacties/maand gratis)"
        )
        return

    base_url = "https://serpapi.com/search.json"
    logger.info("Scraping via SerpAPI (Google Jobs) voor '%s'...", query)

    start = 0
    for page in range(max_pages):
        params = {
            "engine": "google_jobs",
            "q": query,
            "location": "Netherlands",
            "hl": "nl",
            "gl": "nl",
            "api_key": api_key,
        }
        if start > 0:
            params["start"] = start

        try:
            time.sleep(1)  # SerpAPI has its own rate limits
            resp = session.get(base_url, params=params, timeout=30)

            if resp.status_code == 401:
                logger.error("Ongeldige SerpAPI key. Check je key op serpapi.com")
                return
            if resp.status_code == 429:
                logger.warning("SerpAPI rate limit bereikt. Probeer later opnieuw.")
                return

            resp.raise_for_status()
            data = resp.json()

        except requests.exceptions.RequestException as e:
            logger.error("SerpAPI request mislukt: %s", e)
            return

        jobs = data.get("jobs_results", [])
        if not jobs:
            logger.info("SerpAPI pagina %d: geen resultaten meer", page + 1)
            break

        logger.info("SerpAPI pagina %d: %d vacatures gevonden", page + 1, len(jobs))

        for job in jobs:
            company = job.get("company_name", "")
            title = job.get("title", "")
            location = job.get("location", "")

            # Get the best available link
            link = ""
            apply_options = job.get("apply_options", [])
            if apply_options:
                link = apply_options[0].get("link", "")
            if not link:
                # Use the share link or detected extensions
                extensions = job.get("detected_extensions", {})
                link = job.get("share_link", "") or job.get("job_id", "")

            # Date
            date_str = job.get("detected_extensions", {}).get("posted_at", "")
            date_posted = _parse_serpapi_date(date_str)

            if title and company:
                yield _make_lead(company, title, location, link, date_posted, "Google Jobs")

        # Check if there are more pages
        if "serpapi_pagination" in data and "next" in data["serpapi_pagination"]:
            start += 10
        else:
            break


# ===================================================================
# SECONDARY SOURCE: SerpAPI — Google Search (organic results)
# ===================================================================
def scrape_serpapi_search(query: str, session: requests.Session, max_pages: int = 3):
    """
    Search Google via SerpAPI for job listings on Dutch job sites.
    Parses organic search results for job postings.
    """
    api_key = _get_serpapi_key()
    if not api_key:
        logger.error("Geen SerpAPI key — sla Google Search over")
        return

    base_url = "https://serpapi.com/search.json"
    search_query = f"{query} vacature Nederland"
    logger.info("Scraping via SerpAPI (Google Search) voor '%s'...", search_query)

    for page in range(max_pages):
        params = {
            "engine": "google",
            "q": search_query,
            "location": "Netherlands",
            "hl": "nl",
            "gl": "nl",
            "num": 20,
            "start": page * 20,
            "api_key": api_key,
        }

        try:
            time.sleep(1)
            resp = session.get(base_url, params=params, timeout=30)
            if resp.status_code != 200:
                logger.warning("SerpAPI Google Search fout: %s", resp.status_code)
                return
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error("SerpAPI Google Search mislukt: %s", e)
            return

        results = data.get("organic_results", [])
        if not results:
            break

        logger.info("Google Search pagina %d: %d resultaten", page + 1, len(results))

        # Job sites we recognize
        job_domains = {
            "indeed", "nationalevacaturebank", "randstad", "werkzoeken",
            "jooble", "jobbird", "monsterboard", "linkedin", "glassdoor",
            "hays", "brunel", "yacht", "tempo-team", "unique",
        }

        for result in results:
            link = result.get("link", "")
            domain = urlparse(link).netloc.lower()

            # Only process results from job sites
            if not any(jd in domain for jd in job_domains):
                continue

            title = result.get("title", "")
            snippet = result.get("snippet", "")

            # Try to extract company from title (often "Functie - Bedrijf")
            company = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                company = parts[1].strip()
            elif " | " in title:
                parts = title.rsplit(" | ", 1)
                title = parts[0].strip()
                company = parts[1].strip()

            # Try to extract location from snippet
            location = ""
            loc_match = re.search(
                r"(?:in|te|locatie:?)\s+([A-Z][a-z]+(?:\s+[a-z]+)*(?:\s+[A-Z][a-z]+)*)",
                snippet,
            )
            if loc_match:
                location = loc_match.group(1)

            # Date from result
            date_str = result.get("date", "")
            date_posted = _parse_serpapi_date(date_str) or _parse_dutch_date(date_str)

            if title:
                source_name = "Google"
                for jd in job_domains:
                    if jd in domain:
                        source_name = jd.capitalize()
                        break

                yield _make_lead(company, title, location, link, date_posted, source_name)


# ===================================================================
# FALLBACK: HTML scrapers (used when no API key is available)
# ===================================================================
def scrape_nationalevacaturebank(query, session, max_pages=5):
    base_url = "https://www.nationalevacaturebank.nl"
    logger.info("Scraping Nationale Vacaturebank voor '%s'...", query)
    for page in range(1, max_pages + 1):
        url = f"{base_url}/vacature/zoeken?query={quote_plus(query)}&page={page}"
        soup = get_page(url, session)
        if not soup:
            break
        cards = soup.select('[class*="vacancy-item"], [class*="vacancy-card"], [class*="job-item"], article')
        if not cards:
            cards = soup.find_all("li", attrs={"data-url": True})
        if not cards:
            logger.info("NVB pagina %d: geen resultaten", page)
            break
        logger.info("NVB pagina %d: %d items", page, len(cards))
        for card in cards:
            try:
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
                co = card.find(class_=re.compile(r"company|employer|organis", re.I))
                company = co.get_text(strip=True) if co else ""
                loc = card.find(class_=re.compile(r"location|city|plaats", re.I))
                location = loc.get_text(strip=True) if loc else ""
                dt = card.find(class_=re.compile(r"date|time|posted", re.I)) or card.find("time")
                raw = (dt.get("datetime", "") or dt.get_text(strip=True)) if dt else ""
                yield _make_lead(company, title, location, link, _parse_dutch_date(raw), "NVB")
            except Exception as e:
                logger.debug("NVB parse error: %s", e)


def scrape_werkzoeken(query, session, max_pages=5):
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
        logger.info("Werkzoeken pagina %d: %d items", page, len(cards))
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


def scrape_randstad(query, session, max_pages=5):
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
        logger.info("Randstad pagina %d: %d items", page, len(cards))
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
# Dispatcher
# ===================================================================
SOURCE_MAP = {
    "serpapi": scrape_serpapi,
    "google": scrape_serpapi_search,
    "nvb": scrape_nationalevacaturebank,
    "werkzoeken": scrape_werkzoeken,
    "randstad": scrape_randstad,
}

# SerpAPI first, then fall back to HTML scrapers
DEFAULT_SOURCES = ["serpapi"]
ALL_SOURCES = list(SOURCE_MAP.keys())


def scrape_all(
    query: str | None = None,
    province: str | None = None,
    max_pages: int = 5,
    sources: list[str] | None = None,
) -> list[dict]:
    """Scrape all configured sources, deduplicate, and filter by province."""
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
            "Controleer je SERPAPI_KEY of probeer --bronnen nvb werkzoeken randstad",
            ", ".join(failed_sources),
        )

    logger.info("Totaal: %d unieke vacatures gevonden", len(all_leads))
    return all_leads
