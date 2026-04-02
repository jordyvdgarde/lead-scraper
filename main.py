"""CLI entry point for the lead scraper."""

import argparse
import logging
import sys

import pandas as pd

from config import SEARCH_QUERY, PROVINCES, CSV_PATH
from scraper import scrape_all, ALL_SOURCES, DEFAULT_SOURCES, _get_serpapi_key
from enricher import enrich_leads
from storage import load_leads, save_leads, merge_leads


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Scrape vacatures voor commercieel medewerker binnendienst",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Voorbeelden:
  python main.py                                  # Scrape via SerpAPI (of HTML fallback)
  python main.py --provincie Zuid-Holland          # Alleen Zuid-Holland
  python main.py --enrich                         # Met contactinfo verrijking
  python main.py --query "sales medewerker"       # Andere zoekterm
  python main.py --bronnen serpapi google          # SerpAPI + Google Search
  python main.py --bronnen nvb werkzoeken randstad # Alleen HTML scrapers

  Stel SERPAPI_KEY in voor de beste resultaten:
    export SERPAPI_KEY=je_key_hier
  Of maak een .env bestand met: SERPAPI_KEY=je_key_hier
        """,
    )
    parser.add_argument(
        "--query", "-q",
        default=SEARCH_QUERY,
        help=f"Zoekterm (standaard: '{SEARCH_QUERY}')",
    )
    parser.add_argument(
        "--provincie", "-p",
        choices=list(PROVINCES.keys()),
        default=None,
        help="Filter op provincie",
    )
    parser.add_argument(
        "--enrich", "-e",
        action="store_true",
        help="Verrijk leads met contactinformatie (telefoon, email, website)",
    )
    parser.add_argument(
        "--output", "-o",
        default=CSV_PATH,
        help=f"Output CSV pad (standaard: {CSV_PATH})",
    )
    parser.add_argument(
        "--max-paginas",
        type=int,
        default=5,
        help="Maximum aantal pagina's per bron (standaard: 5)",
    )
    parser.add_argument(
        "--bronnen",
        nargs="+",
        choices=ALL_SOURCES,
        default=None,
        help=f"Welke bronnen (standaard: serpapi als key beschikbaar, anders nvb+werkzoeken+randstad)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Uitgebreide logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)

    # Auto-detect best sources if not specified
    if args.bronnen is None:
        if _get_serpapi_key():
            args.bronnen = ["serpapi"]
        else:
            args.bronnen = ["nvb", "werkzoeken", "randstad"]
            logger.info(
                "Geen SERPAPI_KEY gevonden — gebruik HTML scrapers als fallback. "
                "Voor betere resultaten: stel SERPAPI_KEY in (gratis op serpapi.com)"
            )

    logger.info("=== Lead Scraper gestart ===")
    logger.info("Zoekterm: %s", args.query)
    if args.provincie:
        logger.info("Provincie filter: %s", args.provincie)
    logger.info("Bronnen: %s", ", ".join(args.bronnen))

    # Scrape
    new_leads = scrape_all(
        query=args.query,
        province=args.provincie,
        max_pages=args.max_paginas,
        sources=args.bronnen,
    )

    if not new_leads:
        logger.warning("Geen vacatures gevonden. Probeer een andere zoekterm of bron.")
        sys.exit(0)

    new_df = pd.DataFrame(new_leads)
    logger.info("%d nieuwe vacatures gevonden", len(new_df))

    # Merge with existing data
    existing_df = load_leads(args.output)
    merged_df = merge_leads(existing_df, new_df)
    logger.info(
        "Totaal na samenvoegen: %d leads (%d bestaand + %d nieuw)",
        len(merged_df), len(existing_df), len(new_df),
    )

    # Optional enrichment
    if args.enrich:
        logger.info("Start verrijking van contactinformatie...")
        merged_df = enrich_leads(merged_df)

    # Save
    save_leads(merged_df, args.output)

    # Summary
    print("\n" + "=" * 50)
    print("SAMENVATTING")
    print("=" * 50)
    print(f"Totaal leads:         {len(merged_df)}")
    print(f"Unieke bedrijven:     {merged_df['bedrijf'].nunique()}")
    if args.provincie:
        print(f"Provincie:            {args.provincie}")
    if args.enrich:
        has_contact = (
            merged_df["telefoon"].notna() | merged_df["email"].notna()
        ).sum()
        print(f"Met contactinfo:      {has_contact}")
    print(f"Opgeslagen in:        {args.output}")
    print("=" * 50)


if __name__ == "__main__":
    main()
