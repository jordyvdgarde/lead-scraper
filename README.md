# Lead Scraper - Vacatures voor Commercieel Medewerker Binnendienst

Python-applicatie die vacatures scrapt voor "commercieel medewerker binnendienst" in Nederland en de bijbehorende bedrijfscontactgegevens probeert te vinden.

## Wat doet het?

- **Scrapt vacatures** van Indeed.nl, Jooble.org en Nationale Vacaturebank
- **Verzamelt per vacature**: bedrijfsnaam, functietitel, locatie, link, datum geplaatst
- **Verrijkt met contactinfo**: zoekt telefoonnummer, e-mailadres en website van het bedrijf via openbare bronnen
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

## Gebruik

### Via de command line

```bash
# Scrape alle bronnen, alle provincies
python main.py

# Filter op provincie
python main.py --provincie Noord-Holland

# Met contactinfo verrijking (duurt langer)
python main.py --enrich

# Andere zoekterm gebruiken
python main.py --query "sales medewerker"

# Alleen specifieke bronnen
python main.py --bronnen indeed jooble

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

## Beschikbare provincies

Drenthe, Flevoland, Friesland, Gelderland, Groningen, Limburg, Noord-Brabant, Noord-Holland, Overijssel, Utrecht, Zeeland, Zuid-Holland

## Projectstructuur

```
lead-scraper/
├── main.py          # CLI entry point
├── app.py           # Streamlit webdashboard
├── scraper.py       # Vacature scraping logica
├── enricher.py      # Bedrijfscontactinfo verrijking
├── storage.py       # CSV opslag helpers
├── config.py        # Configuratie en constanten
├── requirements.txt # Python dependencies
└── data/
    └── leads.csv    # Output bestand (wordt automatisch aangemaakt)
```

## Bronnen

| Bron | CLI naam | URL |
|------|----------|-----|
| Indeed Nederland | `indeed` | nl.indeed.com |
| Jooble Nederland | `jooble` | nl.jooble.org |
| Nationale Vacaturebank | `nvb` | nationalevacaturebank.nl |

## Verantwoord gebruik

- De scraper respecteert `robots.txt` van elke website
- Er zit een vertraging van 2 seconden tussen requests
- Bij rate limiting (HTTP 429) wordt automatisch langer gewacht
- Nette browser headers worden gebruikt

**Disclaimer**: Deze tool is bedoeld voor persoonlijk gebruik en onderzoek. Gebruik de verzamelde gegevens op een verantwoorde manier en respecteer de privacywetgeving (AVG/GDPR). De nauwkeurigheid van de verzamelde gegevens wordt niet gegarandeerd. Controleer altijd de voorwaarden van de websites die je scrapt.

## Troubleshooting

- **Geen resultaten?** Websites veranderen regelmatig hun HTML-structuur. Check of de CSS-selectors in `scraper.py` nog kloppen.
- **Geblokkeerd?** Verhoog `REQUEST_DELAY` in `config.py` of probeer een andere bron.
- **Import errors?** Zorg dat je `pip install -r requirements.txt` hebt gedraaid in je virtual environment.
