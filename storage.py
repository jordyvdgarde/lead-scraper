"""CSV storage helpers for leads data."""

import os
import logging
from datetime import datetime

import pandas as pd

from config import CSV_PATH, CSV_COLUMNS

logger = logging.getLogger(__name__)


def ensure_data_dir():
    """Create the data directory if it doesn't exist."""
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)


def load_leads(path: str | None = None) -> pd.DataFrame:
    """Load leads from CSV. Returns empty DataFrame if file doesn't exist."""
    path = path or CSV_PATH
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, dtype=str)
            # Ensure all expected columns exist
            for col in CSV_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            return df
        except Exception as e:
            logger.warning("Kon CSV niet laden (%s), start met lege dataset", e)
            # Back up corrupted file
            backup = path + f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.rename(path, backup)
            logger.info("Backup gemaakt: %s", backup)
    return pd.DataFrame(columns=CSV_COLUMNS)


def save_leads(df: pd.DataFrame, path: str | None = None):
    """Save leads DataFrame to CSV."""
    path = path or CSV_PATH
    ensure_data_dir()
    df.to_csv(path, index=False)
    logger.info("Opgeslagen: %d leads naar %s", len(df), path)


def merge_leads(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Merge new leads into existing, deduplicating on link."""
    if existing.empty:
        return new
    if new.empty:
        return existing
    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=["link"], keep="last")
    return combined.reset_index(drop=True)
