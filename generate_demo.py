"""Generate demo data for testing the dashboard and pipeline."""

import random
from datetime import datetime, timedelta

import pandas as pd

from config import CSV_COLUMNS, CSV_PATH, get_province_for_location
from storage import save_leads


DEMO_COMPANIES = [
    ("Technip Energies", "Rotterdam", "https://www.technip.com", "010-1234567", "hr@technip.com"),
    ("Quion Groep", "Capelle aan den IJssel", "https://www.quion.nl", "010-2345678", "info@quion.nl"),
    ("Broekman Logistics", "Rotterdam", "https://www.broekmanlogistics.com", "010-3456789", "careers@broekman.nl"),
    ("Damen Shipyards", "Schiedam", "https://www.damen.com", "010-4567890", "jobs@damen.com"),
    ("Lely Industries", "Delft", "https://www.lely.com", "015-1234567", "recruitment@lely.com"),
    ("Fokker Techniek", "Den Haag", "https://www.fokker.com", "070-1234567", "hr@fokker.com"),
    ("Boskalis", "Papendrecht", "https://www.boskalis.com", "078-1234567", "info@boskalis.com"),
    ("Van Oord", "Rotterdam", "https://www.vanoord.com", "010-5678901", "careers@vanoord.com"),
    ("Heerema Marine", "Leiden", "https://www.heerema.com", "071-1234567", "recruitment@heerema.com"),
    ("SHV Holdings", "Den Haag", "https://www.shv.nl", "070-2345678", "info@shv.nl"),
    ("Fugro", "Leidschendam", "https://www.fugro.com", "070-3456789", "hr@fugro.com"),
    ("Vopak", "Rotterdam", "https://www.vopak.com", "010-6789012", "recruitment@vopak.com"),
    ("Aalberts Industries", "Leiden", "https://www.aalberts.com", "071-2345678", None),
    ("Post NL", "Den Haag", "https://www.postnl.nl", "070-4567890", "vacatures@postnl.nl"),
    ("Coolblue", "Rotterdam", "https://www.coolblue.nl", "010-7890123", "jobs@coolblue.nl"),
    ("Kramp Groep", "Gouda", "https://www.kramp.com", "0182-123456", "hr@kramp.com"),
    ("Mammoet", "Schiedam", "https://www.mammoet.com", "010-8901234", None),
    ("Eneco", "Rotterdam", "https://www.eneco.nl", "010-9012345", "werkenbij@eneco.nl"),
    ("Stedin", "Rotterdam", "https://www.stedin.net", "010-0123456", "info@stedin.net"),
    ("Erasmus MC", "Rotterdam", None, None, "vacatures@erasmusmc.nl"),
    ("Gemeente Rotterdam", "Rotterdam", "https://www.rotterdam.nl", "14010", None),
    ("Holland Trading Group", "Dordrecht", "https://www.hollandtrading.nl", "078-2345678", "sales@hollandtrading.nl"),
    ("Unilever", "Rotterdam", "https://www.unilever.nl", "010-1122334", "careers@unilever.com"),
    ("KPN Zakelijk", "Den Haag", "https://www.kpn.com", "070-5678901", None),
    ("Alliander", "Zoetermeer", "https://www.alliander.com", "079-1234567", "werkenbij@alliander.com"),
]

FUNCTIETITELS = [
    "Commercieel Medewerker Binnendienst",
    "Binnendienst Medewerker Sales",
    "Inside Sales Medewerker",
    "Commercieel Binnendienst Medewerker",
    "Medewerker Commerciële Binnendienst",
    "Sales Support Medewerker",
    "Junior Commercieel Medewerker Binnendienst",
    "Senior Binnendienst Medewerker",
]

BRONNEN = [
    "https://nl.indeed.com/viewjob?jk=",
    "https://nl.jooble.org/desc/",
    "https://www.nationalevacaturebank.nl/vacature/",
]


def generate_demo_data():
    """Generate realistic demo leads data."""
    leads = []
    now = datetime.now()

    for i, (company, city, website, phone, email) in enumerate(DEMO_COMPANIES):
        days_ago = random.randint(0, 30)
        date_posted = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        titel = random.choice(FUNCTIETITELS)
        bron = random.choice(BRONNEN)
        link = f"{bron}{random.randint(100000, 999999)}"

        source_names = ["Indeed", "Jooble", "NVB", "Werkzoeken", "Randstad"]
        leads.append({
            "bedrijf": company,
            "functietitel": titel,
            "locatie": city,
            "provincie": get_province_for_location(city),
            "link": link,
            "datum_geplaatst": date_posted,
            "bron": random.choice(source_names),
            "telefoon": phone,
            "email": email,
            "website": website,
            "datum_gescraped": now.strftime("%Y-%m-%d %H:%M"),
        })

    df = pd.DataFrame(leads, columns=CSV_COLUMNS)
    save_leads(df)
    print(f"{len(df)} demo leads gegenereerd en opgeslagen in {CSV_PATH}")
    return df


if __name__ == "__main__":
    generate_demo_data()
