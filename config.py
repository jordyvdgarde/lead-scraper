"""Configuration constants for the lead scraper."""

SEARCH_QUERY = "commercieel medewerker binnendienst"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

REQUEST_DELAY = 2  # seconds between requests
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # exponential backoff multiplier

CSV_PATH = "data/leads.csv"

CSV_COLUMNS = [
    "bedrijf",
    "functietitel",
    "locatie",
    "provincie",
    "link",
    "datum_geplaatst",
    "telefoon",
    "email",
    "website",
    "datum_gescraped",
]

# Dutch provinces mapped to their major cities
PROVINCES = {
    "Drenthe": [
        "Assen", "Emmen", "Hoogeveen", "Meppel", "Coevorden",
        "Beilen", "Roden", "Zuidlaren",
    ],
    "Flevoland": [
        "Almere", "Lelystad", "Dronten", "Emmeloord", "Zeewolde",
        "Urk", "Swifterbant",
    ],
    "Friesland": [
        "Leeuwarden", "Drachten", "Heerenveen", "Sneek", "Harlingen",
        "Franeker", "Dokkum", "Joure", "Bolsward", "Wolvega",
    ],
    "Gelderland": [
        "Arnhem", "Nijmegen", "Apeldoorn", "Ede", "Doetinchem",
        "Zutphen", "Tiel", "Harderwijk", "Barneveld", "Wageningen",
        "Zevenaar", "Winterswijk", "Elst", "Veenendaal", "Ermelo",
        "Putten", "Nunspeet", "Epe", "Culemborg", "Bemmel",
    ],
    "Groningen": [
        "Groningen", "Veendam", "Stadskanaal", "Winschoten",
        "Hoogezand", "Delfzijl", "Appingedam", "Leek",
    ],
    "Limburg": [
        "Maastricht", "Venlo", "Heerlen", "Sittard", "Roermond",
        "Weert", "Kerkrade", "Geleen", "Venray", "Brunssum",
        "Landgraaf", "Stein", "Tegelen",
    ],
    "Noord-Brabant": [
        "Eindhoven", "Tilburg", "Breda", "'s-Hertogenbosch",
        "Den Bosch", "Helmond", "Roosendaal", "Oss", "Bergen op Zoom",
        "Waalwijk", "Uden", "Veghel", "Boxtel", "Best", "Valkenswaard",
        "Dongen", "Oosterhout", "Etten-Leur", "Cuijk",
    ],
    "Noord-Holland": [
        "Amsterdam", "Haarlem", "Zaandam", "Hilversum", "Alkmaar",
        "Hoofddorp", "Amstelveen", "Purmerend", "Hoorn", "Den Helder",
        "Heerhugowaard", "Schiphol", "Beverwijk", "IJmuiden",
        "Bussum", "Naarden", "Weesp", "Enkhuizen", "Diemen",
    ],
    "Overijssel": [
        "Zwolle", "Enschede", "Deventer", "Hengelo", "Almelo",
        "Kampen", "Hardenberg", "Raalte", "Oldenzaal", "Rijssen",
        "Ommen", "Steenwijk", "Vriezenveen",
    ],
    "Utrecht": [
        "Utrecht", "Amersfoort", "Nieuwegein", "Zeist", "Veenendaal",
        "Houten", "IJsselstein", "Woerden", "Maarssen", "Bilthoven",
        "Driebergen", "Bunnik", "De Bilt", "Soest", "Baarn",
        "Breukelen", "Leidsche Rijn", "Vianen",
    ],
    "Zeeland": [
        "Middelburg", "Vlissingen", "Goes", "Terneuzen", "Zierikzee",
        "Hulst", "Kapelle", "Tholen",
    ],
    "Zuid-Holland": [
        "Rotterdam", "Den Haag", "'s-Gravenhage", "Leiden", "Dordrecht",
        "Zoetermeer", "Delft", "Schiedam", "Vlaardingen", "Gouda",
        "Alphen aan den Rijn", "Capelle aan den IJssel", "Spijkenisse",
        "Ridderkerk", "Leidschendam", "Voorburg", "Rijswijk",
        "Katwijk", "Maassluis", "Barendrecht", "Papendrecht",
    ],
}


def get_province_for_location(location: str) -> str | None:
    """Determine the province for a given location string."""
    if not location:
        return None
    location_lower = location.lower()
    for province, cities in PROVINCES.items():
        for city in cities:
            if city.lower() in location_lower:
                return province
    return None
