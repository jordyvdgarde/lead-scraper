"""Streamlit web dashboard for viewing and filtering scraped leads."""

import subprocess
import sys

import streamlit as st
import pandas as pd

from config import PROVINCES, CSV_PATH, SEARCH_QUERY
from scraper import ALL_SOURCES
from storage import load_leads


st.set_page_config(
    page_title="Lead Scraper Dashboard",
    page_icon="🔍",
    layout="wide",
)

st.title("Lead Scraper - Vacatures Dashboard")
st.caption("Commercieel medewerker binnendienst in Nederland")


# --- Sidebar: filters & actions ---
st.sidebar.header("Filters")

df = load_leads()

if df.empty:
    st.warning(
        "Nog geen data gevonden. Gebruik de scraper in de sidebar of via de CLI: "
        "`python main.py`"
    )

# Province filter
provincies = ["Alle provincies"] + sorted(PROVINCES.keys())
selected_provincie = st.sidebar.selectbox("Provincie", provincies)

# Company name filter
bedrijf_filter = st.sidebar.text_input("Zoek bedrijf", "")

# Date filter
if not df.empty and "datum_geplaatst" in df.columns:
    df["datum_geplaatst"] = pd.to_datetime(df["datum_geplaatst"], errors="coerce")
    valid_dates = df["datum_geplaatst"].dropna()
    if not valid_dates.empty:
        min_date = valid_dates.min().date()
        max_date = valid_dates.max().date()
        if min_date < max_date:
            date_range = st.sidebar.date_input(
                "Datum range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )
        else:
            date_range = None
    else:
        date_range = None
else:
    date_range = None

# Contact info filter
alleen_met_contact = st.sidebar.checkbox("Alleen met contactinfo", value=False)

# --- Sidebar: scraper controls ---
st.sidebar.markdown("---")
st.sidebar.header("Scraper")

query = st.sidebar.text_input("Zoekterm", SEARCH_QUERY)
scrape_provincie = st.sidebar.selectbox(
    "Scrape provincie",
    ["Alle provincies"] + sorted(PROVINCES.keys()),
    key="scrape_prov",
)
bronnen = st.sidebar.multiselect(
    "Bronnen",
    ALL_SOURCES,
    default=ALL_SOURCES,
)
do_enrich = st.sidebar.checkbox("Verrijk met contactinfo", value=False)

if st.sidebar.button("Start Scraper", type="primary"):
    cmd = [sys.executable, "main.py", "--query", query, "--bronnen"] + bronnen
    if scrape_provincie != "Alle provincies":
        cmd += ["--provincie", scrape_provincie]
    if do_enrich:
        cmd.append("--enrich")

    with st.spinner("Scraper is bezig..."):
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )

    if result.returncode == 0:
        st.sidebar.success("Scraping voltooid!")
        st.rerun()
    else:
        st.sidebar.error("Fout bij scraping")
        with st.sidebar.expander("Foutdetails"):
            st.code(result.stderr or result.stdout)

# --- Apply filters ---
filtered = df.copy()

if not filtered.empty:
    if selected_provincie != "Alle provincies":
        filtered = filtered[filtered["provincie"] == selected_provincie]

    if bedrijf_filter:
        filtered = filtered[
            filtered["bedrijf"]
            .fillna("")
            .str.contains(bedrijf_filter, case=False, na=False)
        ]

    if date_range and isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        mask = filtered["datum_geplaatst"].notna()
        filtered = filtered[
            mask
            & (filtered["datum_geplaatst"].dt.date >= start)
            & (filtered["datum_geplaatst"].dt.date <= end)
        ]

    if alleen_met_contact:
        filtered = filtered[
            filtered["telefoon"].notna() | filtered["email"].notna()
        ]

# --- Stats ---
if not filtered.empty:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Totaal vacatures", len(filtered))
    col2.metric("Unieke bedrijven", filtered["bedrijf"].nunique())
    col3.metric(
        "Met contactinfo",
        (filtered["telefoon"].notna() | filtered["email"].notna()).sum(),
    )
    col4.metric(
        "Provincies",
        filtered["provincie"].dropna().nunique(),
    )

# --- Data table ---
if not filtered.empty:
    st.subheader(f"Vacatures ({len(filtered)})")

    # Format the link column as clickable
    display_df = filtered.copy()
    if "datum_geplaatst" in display_df.columns:
        display_df["datum_geplaatst"] = display_df["datum_geplaatst"].dt.strftime(
            "%Y-%m-%d"
        )

    st.dataframe(
        display_df,
        column_config={
            "link": st.column_config.LinkColumn("Link", display_text="Bekijk"),
            "website": st.column_config.LinkColumn("Website", display_text="Website"),
            "bedrijf": st.column_config.TextColumn("Bedrijf", width="medium"),
            "functietitel": st.column_config.TextColumn("Functie", width="large"),
            "locatie": st.column_config.TextColumn("Locatie", width="medium"),
            "provincie": st.column_config.TextColumn("Provincie", width="medium"),
            "datum_geplaatst": st.column_config.TextColumn("Datum"),
            "telefoon": st.column_config.TextColumn("Telefoon"),
            "email": st.column_config.TextColumn("Email"),
            "datum_gescraped": st.column_config.TextColumn("Gescraped"),
        },
        use_container_width=True,
        hide_index=True,
    )

    # --- Export ---
    st.subheader("Exporteren")
    csv_data = filtered.to_csv(index=False)
    st.download_button(
        label="Download als CSV",
        data=csv_data,
        file_name="leads_export.csv",
        mime="text/csv",
    )
elif not df.empty:
    st.info("Geen resultaten met de huidige filters.")
