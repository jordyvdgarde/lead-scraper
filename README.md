# Lead Scraper - Vacatures voor Commercieel Medewerker Binnendienst

Python-applicatie die vacatures scrapt voor "commercieel medewerker binnendienst" in Nederland en de bijbehorende bedrijfscontactgegevens probeert te vinden.

## Wat doet het?

- **Zoekt vacatures via SerpAPI** (Google Jobs) — betrouwbaar, geen blocks, gestructureerde data
- **HTML scrapers als fallback** voor Nationale Vacaturebank, Werkzoeken.nl en Randstad.nl
- **Verzamelt per vacature**: bedrijfsnaam, functietitel, locatie, link, datum geplaatst
- **Verrijkt met contactinfo**: zoekt telefoonnummer, e-mailadres en website van het bedrijf
- **Slaat op in CSV** voor eenvoudig gebruik in Excel of Google Sheets
- **Filtert op provincie** zodat je specifieke regio's kunt doorzoeken
- **Webdashboard** (Streamlit) om resultaten te bekijken, filteren en exporteren
- **Respecteert robots.txt** en gebruikt nette request headers

## Installatie

```bash
# Clone de repository
git clone https://github.com/jordyvdgarde/lead-scraper.git
cd lead-scraper

# Maak een virtual environment aan (aanbevolen)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# of: venv\Scripts\activate  # Windows

# Installeer dependencies
pip install -r requirements.txt
```

## SerpAPI instellen (aanbevolen)

De scraper gebruikt **SerpAPI** als primaire bron. Dit geeft de beste resultaten via Google Jobs.

1. Maak een gratis account aan op [serpapi.com](https://serpapi.com) (100 zoekacties/maand gratis)
2. Stel je API key in:

```bash
# Optie 1: Environment variable
export SERPAPI_KEY=je_api_key_hier

# Optie 2: .env bestand in de project root
echo "SERPAPI_KEY=je_api_key_hier" > .env
```

Zonder API key valt de scraper automatisch terug op HTML scrapers (NVB, Werkzoeken, Randstad).

## Gebruik

### Via de command line

```bash
# Scrape via SerpAPI (standaard als key beschikbaar)
python main.py

# Filter op provincie
python main.py --provincie Zuid-Holland

# Met contactinfo verrijking (duurt langer)
python main.py --enrich

# Andere zoekterm gebruiken
python main.py --query "sales medewerker"

# Gebruik SerpAPI + Google Search
python main.py --bronnen serpapi google

# Gebruik alleen HTML scrapers (geen API key nodig)
python main.py --bronnen nvb werkzoeken randstad

# Combinatie van opties
python main.py --provincie Zuid-Holland --enrich --max-paginas 3

# Alle opties bekijken
python main.py --help
```

### Via het webdashboard

```bash
streamlit run app.py
```

Dit opent een dashboard in je browser waar je:
- Resultaten kunt bekijken in een overzichtelijke tabel
- Kunt filteren op provincie, bedrijfsnaam en datum
- Alleen leads met contactinfo kunt tonen
- De scraper direct vanuit het dashboard kunt starten
- Gefilterde resultaten kunt exporteren als CSV

### Demo data genereren (voor testen)

```bash
python generate_demo.py
```

## Beschikbare provincies

Drenthe, Flevoland, Friesland, Gelderland, Groningen, Limburg, Noord-Brabant, Noord-Holland, Overijssel, Utrecht, Zeeland, Zuid-Holland

## Projectstructuur

```
lead-scraper/
├── main.py           # CLI entry point
├── app.py            # Streamlit webdashboard
├── scraper.py        # SerpAPI + HTML scraping logica
├── enricher.py       # Bedrijfscontactinfo verrijking
├── storage.py        # CSV opslag helpers
├── config.py         # Configuratie en constanten
├── generate_demo.py  # Demo data generator
├── test_scraper.py   # Test suite (23 tests)
├── requirements.txt  # Python dependencies
├── .env              # SerpAPI key (zelf aanmaken)
└── data/
    └── leads.csv     # Output bestand (automatisch aangemaakt)
```

## Bronnen

| Bron | CLI naam | Type | Opmerkingen |
|------|----------|------|-------------|
| Google Jobs (SerpAPI) | `serpapi` | API | Aanbevolen, gratis tier beschikbaar |
| Google Search (SerpAPI) | `google` | API | Zoekt vacatures op job-sites via Google |
| Nationale Vacaturebank | `nvb` | HTML | Fallback, kan geblokkeerd worden |
| Werkzoeken.nl | `werkzoeken` | HTML | Fallback |
| Randstad.nl | `randstad` | HTML | Fallback |

## Tests draaien

```bash
python -m unittest test_scraper -v
```

23 tests die alle parsers, datumparsing, provincie-filtering en deduplicatie valideren — allemaal zonder netwerktoegang.

## Verantwoord gebruik

- SerpAPI respecteert Google's voorwaarden
- HTML scrapers respecteren `robots.txt`
- Er zit een vertraging van 2 seconden tussen requests
- Bij rate limiting (HTTP 429) wordt automatisch langer gewacht

**Disclaimer**: Deze tool is bedoeld voor persoonlijk gebruik en onderzoek. Gebruik de verzamelde gegevens op een verantwoorde manier en respecteer de privacywetgeving (AVG/GDPR). De nauwkeurigheid van de verzamelde gegevens wordt niet gegarandeerd.

## Troubleshooting

- **Geen resultaten met SerpAPI?** Check of je `SERPAPI_KEY` correct is ingesteld.
- **Geen resultaten met HTML scrapers?** Sites veranderen regelmatig hun HTML. Check de CSS-selectors in `scraper.py`.
- **Proxy/firewall errors?** Probeer op een ander netwerk of schakel je proxy uit.
- **Import errors?** Draai `pip install -r requirements.txt` in je virtual environment.
