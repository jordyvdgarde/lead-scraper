"""Tests for scraper parsing logic using realistic HTML samples.

These tests verify that the parsers correctly extract job data from HTML
that mirrors the real structure of each source, without needing network access.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from scraper import (
    _parse_dutch_date,
    _parse_serpapi_date,
    _make_lead,
    scrape_serpapi,
    scrape_serpapi_search,
    scrape_nationalevacaturebank,
    scrape_werkzoeken,
    scrape_randstad,
    scrape_all,
)


# ---------------------------------------------------------------------------
# Sample HTML snippets that mirror real site structures
# ---------------------------------------------------------------------------
NVB_HTML = """
<html><body>
<div class="search-results">
  <div class="vacancy-item">
    <h2><a href="/vacature/12345/commercieel-medewerker-binnendienst">
      Commercieel Medewerker Binnendienst
    </a></h2>
    <span class="company-name">Vopak</span>
    <span class="location">Rotterdam</span>
    <span class="date">2 dagen geleden</span>
  </div>
  <div class="vacancy-item">
    <h2><a href="/vacature/12346/inside-sales-medewerker">
      Inside Sales Medewerker
    </a></h2>
    <span class="company-name">Eneco</span>
    <span class="location">Den Haag</span>
    <time datetime="2026-03-28">28 maart 2026</time>
  </div>
  <div class="vacancy-item">
    <h3><a href="/vacature/12347/sales-binnendienst">
      Sales Binnendienst
    </a></h3>
    <span class="employer">Coolblue</span>
    <span class="city">Delft</span>
    <span class="posted-date">vandaag</span>
  </div>
</div>
</body></html>
"""

WERKZOEKEN_HTML = """
<html><body>
<div class="results">
  <article class="vacancy-card">
    <h2><a href="/vacature/sales-support-rotterdam-78901">
      Sales Support Medewerker
    </a></h2>
    <div class="company">Broekman Logistics</div>
    <div class="locatie">Rotterdam</div>
    <div class="datum">gisteren</div>
  </article>
  <article class="vacancy-card">
    <h3><a href="/vacature/commercieel-mdw-gouda-78902">
      Commercieel Medewerker
    </a></h3>
    <div class="bedrijf">Kramp Groep</div>
    <div class="plaats">Gouda</div>
    <div class="date">13 maart 2026</div>
  </article>
</div>
</body></html>
"""

RANDSTAD_HTML = """
<html><body>
<div class="search-results">
  <article class="job-card">
    <h2><a href="/werkzoekende/vacature/binnendienst-leiden-456">
      Binnendienst Medewerker
    </a></h2>
    <span class="company-name">Heerema Marine</span>
    <span class="location">Leiden</span>
    <time datetime="2026-03-30">30 maart</time>
  </article>
  <article class="job-card">
    <h3><a href="/werkzoekende/vacature/sales-schiedam-457">
      Junior Sales Medewerker
    </a></h3>
    <span class="client-name">Damen Shipyards</span>
    <span class="place">Schiedam</span>
    <span class="posted-time">5 dagen geleden</span>
  </article>
</div>
</body></html>
"""


# Sample SerpAPI Google Jobs JSON response
SERPAPI_JOBS_RESPONSE = {
    "jobs_results": [
        {
            "title": "Commercieel Medewerker Binnendienst",
            "company_name": "Vopak",
            "location": "Rotterdam, Zuid-Holland",
            "detected_extensions": {"posted_at": "3 days ago"},
            "apply_options": [{"link": "https://www.vopak.com/careers/job-12345"}],
        },
        {
            "title": "Inside Sales Medewerker",
            "company_name": "Eneco",
            "location": "Den Haag, Zuid-Holland",
            "detected_extensions": {"posted_at": "1 day ago"},
            "apply_options": [{"link": "https://www.eneco.nl/vacature/67890"}],
        },
        {
            "title": "Sales Support",
            "company_name": "Coolblue",
            "location": "Rotterdam, Zuid-Holland",
            "detected_extensions": {"posted_at": "Just posted"},
            "apply_options": [{"link": "https://www.coolblue.nl/jobs/11111"}],
        },
    ],
}

SERPAPI_JOBS_EMPTY = {"jobs_results": []}

SERPAPI_SEARCH_RESPONSE = {
    "organic_results": [
        {
            "title": "Commercieel Medewerker - Fugro",
            "link": "https://www.indeed.nl/viewjob?jk=abc123",
            "snippet": "Fugro zoekt een commercieel medewerker binnendienst in Leidschendam.",
            "date": "2 days ago",
        },
        {
            "title": "Sales Medewerker Binnendienst | Kramp Groep",
            "link": "https://www.nationalevacaturebank.nl/vacature/99999",
            "snippet": "Werken bij Kramp Groep in Gouda als sales medewerker.",
            "date": "5 days ago",
        },
        {
            "title": "Some random blog post",
            "link": "https://www.example.com/blog/post",
            "snippet": "Not a job site at all",
        },
    ],
}


class TestDateParsing(unittest.TestCase):
    """Test Dutch date string parsing."""

    def test_vandaag(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(_parse_dutch_date("vandaag"), today)
        self.assertEqual(_parse_dutch_date("Vandaag"), today)
        self.assertEqual(_parse_dutch_date("zojuist"), today)
        self.assertEqual(_parse_dutch_date("net geplaatst"), today)

    def test_gisteren(self):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(_parse_dutch_date("gisteren"), yesterday)

    def test_dagen_geleden(self):
        expected = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        self.assertEqual(_parse_dutch_date("3 dagen geleden"), expected)

    def test_uur_geleden(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(_parse_dutch_date("5 uur geleden"), today)

    def test_dutch_month(self):
        self.assertEqual(_parse_dutch_date("13 maart 2026"), "2026-03-13")
        self.assertEqual(_parse_dutch_date("28 januari 2026"), "2026-01-28")
        self.assertEqual(_parse_dutch_date("1 december 2025"), "2025-12-01")

    def test_standard_format(self):
        self.assertEqual(_parse_dutch_date("15-03-2026"), "2026-03-15")
        self.assertEqual(_parse_dutch_date("2026-03-15"), "2026-03-15")

    def test_empty(self):
        self.assertEqual(_parse_dutch_date(""), "")
        self.assertEqual(_parse_dutch_date(None), "")


def _mock_get_page(html):
    """Create a mock for get_page that returns parsed HTML."""
    def side_effect(url, session):
        return BeautifulSoup(html, "lxml")
    return side_effect


class TestNVBParser(unittest.TestCase):
    """Test Nationale Vacaturebank parsing."""

    @patch("scraper.get_page")
    def test_parse_nvb_results(self, mock_gp):
        mock_gp.side_effect = [
            BeautifulSoup(NVB_HTML, "lxml"),
            None,  # stop pagination
        ]
        session = MagicMock()
        results = list(scrape_nationalevacaturebank("test", session, max_pages=2))

        self.assertEqual(len(results), 3)

        self.assertEqual(results[0]["bedrijf"], "Vopak")
        self.assertEqual(results[0]["functietitel"], "Commercieel Medewerker Binnendienst")
        self.assertEqual(results[0]["locatie"], "Rotterdam")
        self.assertEqual(results[0]["provincie"], "Zuid-Holland")
        self.assertIn("/vacature/12345", results[0]["link"])
        self.assertEqual(results[0]["bron"], "NVB")

        self.assertEqual(results[1]["bedrijf"], "Eneco")
        self.assertEqual(results[1]["locatie"], "Den Haag")
        self.assertEqual(results[1]["datum_geplaatst"], "2026-03-28")

        self.assertEqual(results[2]["bedrijf"], "Coolblue")
        self.assertEqual(results[2]["locatie"], "Delft")
        self.assertEqual(results[2]["datum_geplaatst"], datetime.now().strftime("%Y-%m-%d"))


class TestWerkzoekenParser(unittest.TestCase):
    """Test Werkzoeken.nl parsing."""

    @patch("scraper.get_page")
    def test_parse_werkzoeken_results(self, mock_gp):
        mock_gp.side_effect = [
            BeautifulSoup(WERKZOEKEN_HTML, "lxml"),
            None,
        ]
        session = MagicMock()
        results = list(scrape_werkzoeken("test", session, max_pages=2))

        self.assertEqual(len(results), 2)

        self.assertEqual(results[0]["bedrijf"], "Broekman Logistics")
        self.assertEqual(results[0]["functietitel"], "Sales Support Medewerker")
        self.assertEqual(results[0]["locatie"], "Rotterdam")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(results[0]["datum_geplaatst"], yesterday)
        self.assertEqual(results[0]["bron"], "Werkzoeken")

        self.assertEqual(results[1]["bedrijf"], "Kramp Groep")
        self.assertEqual(results[1]["locatie"], "Gouda")
        self.assertEqual(results[1]["datum_geplaatst"], "2026-03-13")


class TestRandstadParser(unittest.TestCase):
    """Test Randstad.nl parsing."""

    @patch("scraper.get_page")
    def test_parse_randstad_results(self, mock_gp):
        mock_gp.side_effect = [
            BeautifulSoup(RANDSTAD_HTML, "lxml"),
            None,
        ]
        session = MagicMock()
        results = list(scrape_randstad("test", session, max_pages=2))

        self.assertEqual(len(results), 2)

        self.assertEqual(results[0]["bedrijf"], "Heerema Marine")
        self.assertEqual(results[0]["locatie"], "Leiden")
        self.assertEqual(results[0]["provincie"], "Zuid-Holland")
        self.assertEqual(results[0]["datum_geplaatst"], "2026-03-30")
        self.assertEqual(results[0]["bron"], "Randstad")

        self.assertEqual(results[1]["functietitel"], "Junior Sales Medewerker")
        self.assertEqual(results[1]["locatie"], "Schiedam")
        five_days = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        self.assertEqual(results[1]["datum_geplaatst"], five_days)


class TestSerpAPIDateParsing(unittest.TestCase):
    """Test SerpAPI date string parsing."""

    def test_just_posted(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(_parse_serpapi_date("Just posted"), today)

    def test_days_ago(self):
        expected = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        self.assertEqual(_parse_serpapi_date("3 days ago"), expected)

    def test_hours_ago(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(_parse_serpapi_date("5 hours ago"), today)

    def test_empty(self):
        self.assertEqual(_parse_serpapi_date(""), "")


class TestSerpAPIParser(unittest.TestCase):
    """Test SerpAPI Google Jobs parsing."""

    @patch("scraper._get_serpapi_key", return_value="test_key")
    def test_parse_serpapi_jobs(self, _mock_key):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SERPAPI_JOBS_RESPONSE
        mock_session.get.return_value = mock_resp

        results = list(scrape_serpapi("test", mock_session, max_pages=1))

        self.assertEqual(len(results), 3)

        self.assertEqual(results[0]["bedrijf"], "Vopak")
        self.assertEqual(results[0]["functietitel"], "Commercieel Medewerker Binnendienst")
        self.assertIn("Rotterdam", results[0]["locatie"])
        self.assertEqual(results[0]["link"], "https://www.vopak.com/careers/job-12345")
        self.assertEqual(results[0]["bron"], "Google Jobs")

        self.assertEqual(results[1]["bedrijf"], "Eneco")
        self.assertEqual(results[2]["bedrijf"], "Coolblue")

        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(results[2]["datum_geplaatst"], today)

    @patch("scraper._get_serpapi_key", return_value=None)
    def test_no_api_key(self, _mock_key):
        session = MagicMock()
        results = list(scrape_serpapi("test", session))
        self.assertEqual(len(results), 0)

    @patch("scraper._get_serpapi_key", return_value="test_key")
    def test_empty_results(self, _mock_key):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SERPAPI_JOBS_EMPTY
        mock_session.get.return_value = mock_resp

        results = list(scrape_serpapi("test", mock_session, max_pages=1))
        self.assertEqual(len(results), 0)


class TestSerpAPISearchParser(unittest.TestCase):
    """Test SerpAPI Google Search organic results parsing."""

    @patch("scraper._get_serpapi_key", return_value="test_key")
    def test_parse_search_results(self, _mock_key):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SERPAPI_SEARCH_RESPONSE
        mock_session.get.return_value = mock_resp

        results = list(scrape_serpapi_search("test", mock_session, max_pages=1))

        # Should skip the non-job-site result (example.com)
        self.assertEqual(len(results), 2)

        # First result: "Commercieel Medewerker - Fugro"
        self.assertEqual(results[0]["bedrijf"], "Fugro")
        self.assertEqual(results[0]["functietitel"], "Commercieel Medewerker")
        self.assertIn("indeed", results[0]["link"])

        # Second result: "Sales Medewerker Binnendienst | Kramp Groep"
        self.assertEqual(results[1]["bedrijf"], "Kramp Groep")
        self.assertIn("nationalevacaturebank", results[1]["link"])


class TestScrapeAll(unittest.TestCase):
    """Test the dispatcher with province filtering."""

    @patch("scraper.get_page")
    def test_province_filter(self, mock_gp):
        mock_gp.side_effect = [
            BeautifulSoup(NVB_HTML, "lxml"),
            None,  # NVB pagination stop
            None,  # werkzoeken fails
            None,  # randstad fails
        ]
        session_mock = MagicMock()

        with patch("scraper.create_session", return_value=session_mock):
            results = scrape_all(
                query="test",
                province="Zuid-Holland",
                max_pages=1,
                sources=["nvb", "werkzoeken", "randstad"],
            )

        # All 3 NVB results are in Zuid-Holland
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertEqual(r["provincie"], "Zuid-Holland")

    @patch("scraper.get_page")
    def test_deduplication(self, mock_gp):
        # Same HTML twice = should deduplicate by link
        mock_gp.side_effect = [
            BeautifulSoup(NVB_HTML, "lxml"),
            None,
            BeautifulSoup(NVB_HTML, "lxml"),
            None,
            None,
        ]
        session_mock = MagicMock()

        with patch("scraper.create_session", return_value=session_mock):
            results = scrape_all(
                query="test", max_pages=1,
                sources=["nvb", "werkzoeken", "randstad"],
            )

        self.assertEqual(len(results), 3)  # not 6

    @patch("scraper._get_serpapi_key", return_value="test_key")
    def test_serpapi_with_province_filter(self, _mock_key):
        """Test SerpAPI source with province filtering via scrape_all."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SERPAPI_JOBS_RESPONSE
        mock_session.get.return_value = mock_resp

        with patch("scraper.create_session", return_value=mock_session):
            results = scrape_all(
                query="test",
                province="Zuid-Holland",
                max_pages=1,
                sources=["serpapi"],
            )

        # All 3 jobs have Rotterdam/Den Haag = Zuid-Holland
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertEqual(r["provincie"], "Zuid-Holland")


class TestMakeLead(unittest.TestCase):
    """Test lead dict creation."""

    def test_make_lead_structure(self):
        lead = _make_lead("Acme", "Sales", "Rotterdam", "http://x.com/1", "2026-01-01", "Test")
        self.assertEqual(lead["bedrijf"], "Acme")
        self.assertEqual(lead["functietitel"], "Sales")
        self.assertEqual(lead["locatie"], "Rotterdam")
        self.assertEqual(lead["provincie"], "Zuid-Holland")
        self.assertEqual(lead["bron"], "Test")
        self.assertIsNone(lead["telefoon"])
        self.assertIsNone(lead["email"])
        self.assertIsNone(lead["website"])

    def test_province_detection(self):
        lead = _make_lead("X", "Y", "Amsterdam", "http://x.com/2", "", "T")
        self.assertEqual(lead["provincie"], "Noord-Holland")

        lead = _make_lead("X", "Y", "Onbekend", "http://x.com/3", "", "T")
        self.assertIsNone(lead["provincie"])


if __name__ == "__main__":
    unittest.main()
