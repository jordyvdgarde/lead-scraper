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
    _make_lead,
    scrape_nationalevacaturebank,
    scrape_werkzoeken,
    scrape_randstad,
    scrape_indeed,
    scrape_jooble,
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

INDEED_HTML = """
<html><body>
<div id="mosaic-provider-jobcards">
  <div class="job_seen_beacon">
    <h2 class="jobTitle">
      <a href="/viewjob?jk=abc123" class="jcs-JobTitle">
        Commercieel Medewerker Binnendienst
      </a>
    </h2>
    <span data-testid="company-name">Fugro</span>
    <div data-testid="text-location">Leidschendam</div>
    <span class="date">3 dagen geleden</span>
  </div>
  <div class="job_seen_beacon">
    <h2 class="jobTitle">
      <a href="/viewjob?jk=def456">
        Senior Inside Sales
      </a>
    </h2>
    <span data-testid="company-name">KPN</span>
    <div data-testid="text-location">Den Haag</div>
    <span class="date">vandaag</span>
  </div>
</div>
</body></html>
"""

JOOBLE_HTML = """
<html><body>
<div class="results">
  <article>
    <a class="title-link" href="/desc/commercieel-medewerker-99001">
      Commercieel Binnendienst Medewerker
    </a>
    <span class="company-name">SHV Holdings</span>
    <span class="location">Den Haag</span>
    <span class="date">4 dagen geleden</span>
  </article>
  <article>
    <h2><a href="/desc/sales-support-99002">Sales Support</a></h2>
    <span class="employer">Post NL</span>
    <span class="city">Den Haag</span>
    <time datetime="2026-03-25">25 maart 2026</time>
  </article>
</div>
</body></html>
"""


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


class TestIndeedParser(unittest.TestCase):
    """Test Indeed.nl parsing."""

    @patch("scraper.get_page")
    def test_parse_indeed_results(self, mock_gp):
        mock_gp.side_effect = [
            BeautifulSoup(INDEED_HTML, "lxml"),
            None,
        ]
        session = MagicMock()
        results = list(scrape_indeed("test", session, max_pages=2))

        self.assertEqual(len(results), 2)

        self.assertEqual(results[0]["bedrijf"], "Fugro")
        self.assertEqual(results[0]["locatie"], "Leidschendam")
        self.assertEqual(results[0]["provincie"], "Zuid-Holland")
        self.assertEqual(results[0]["bron"], "Indeed")

        self.assertEqual(results[1]["bedrijf"], "KPN")
        self.assertEqual(results[1]["datum_geplaatst"], datetime.now().strftime("%Y-%m-%d"))


class TestJoobleParser(unittest.TestCase):
    """Test Jooble.org parsing."""

    @patch("scraper.get_page")
    def test_parse_jooble_results(self, mock_gp):
        mock_gp.side_effect = [
            BeautifulSoup(JOOBLE_HTML, "lxml"),
            None,
        ]
        session = MagicMock()
        results = list(scrape_jooble("test", session, max_pages=2))

        self.assertEqual(len(results), 2)

        self.assertEqual(results[0]["bedrijf"], "SHV Holdings")
        self.assertEqual(results[0]["locatie"], "Den Haag")
        self.assertEqual(results[0]["bron"], "Jooble")

        self.assertEqual(results[1]["bedrijf"], "Post NL")
        self.assertEqual(results[1]["datum_geplaatst"], "2026-03-25")


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
            results = scrape_all(query="test", max_pages=1)

        self.assertEqual(len(results), 3)  # not 6


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
