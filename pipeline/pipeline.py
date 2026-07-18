"""
pipeline.py
-----------
STEP 11: Orchestrates the full workflow end to end.

    Website -> Compare with SQLite -> New File?
        No  -> Stop
        Yes -> Download -> Extract -> Parse -> Insert into SQLite -> Send Email
"""

import logging
from datetime import datetime, timezone
from typing import List

from config import settings
from database import db_manager
from scraper.scraper import get_available_files, DiscoveredFile
from scraper.downloader import download_zip, extract_zip, list_usable_files
from parser.cleaner import clean_dataframe
from parser.parser import (
    parse_conversion_factor,
    parse_cpt_base_units,
    parse_zip_mapping,
    CONVERSION_FACTOR_HEADER_HINTS,
    CPT_BASE_UNIT_HEADER_HINTS,
    ZIP_MAPPING_HEADER_HINTS,
)
from notifier.notifier import notify_if_needed

logger = logging.getLogger(__name__)


def _tracking_year(discovered: DiscoveredFile) -> int:
    """
    Year used only to key processed_files/change_log for this file - not
    necessarily the year(s) of the data inside it.

    zip_mapping's "current" file (e.g. "Zip Code to Carrier Locality File")
    has no year in its link text since it's continuously updated in place;
    fall back to the current calendar year so it still gets a stable,
    re-checkable identity instead of being skipped outright.
    """
    if discovered.year is not None:
        return discovered.year
    return datetime.now(timezone.utc).year


def _process_file(discovered: DiscoveredFile) -> bool:
    """
    Handles STEP 4 through STEP 10 for a single discovered file.
    Returns True if new rows were inserted, False otherwise.
    """
    tracking_year = _tracking_year(discovered)

    if db_manager.year_already_processed(discovered.dataset, tracking_year):
        logger.info("%s %d already processed - skipping", discovered.dataset, tracking_year)
        return False

    zip_path = download_zip(discovered.url, discovered.dataset, tracking_year)
    checksum = db_manager.compute_checksum(zip_path)
    extract_dir = extract_zip(zip_path, discovered.dataset, tracking_year)

    usable_files = list_usable_files(extract_dir)
    if not usable_files:
        logger.warning("No usable CSV/Excel files found for %s %s", discovered.dataset, tracking_year)
        db_manager.record_processed_file(zip_path, discovered.dataset, tracking_year, "no_usable_files", checksum)
        return False

    inserted_total = 0
    for file_path in usable_files:
        try:
            if discovered.dataset == settings.DATASET_CONVERSION_FACTOR:
                df = clean_dataframe(file_path, CONVERSION_FACTOR_HEADER_HINTS)
                parsed = parse_conversion_factor(df, tracking_year)
                inserted_total += db_manager.insert_conversion_factor_data(
                    parsed["conversion_factor"], tracking_year
                )
            elif discovered.dataset == settings.DATASET_CPT_BASE_UNITS:
                df = clean_dataframe(file_path, CPT_BASE_UNIT_HEADER_HINTS)
                rows = parse_cpt_base_units(df, tracking_year)
                inserted_total += db_manager.insert_cpt_base_unit_data(rows, tracking_year)
            elif discovered.dataset == settings.DATASET_ZIP_MAPPING:
                df = clean_dataframe(file_path, ZIP_MAPPING_HEADER_HINTS)
                rows = parse_zip_mapping(df)
                inserted_total += db_manager.insert_zip_mapping_data(rows, tracking_year)
        except KeyError:
            # A required standardized column was missing from this file -
            # per project spec, do NOT insert anything from it, log it,
            # and move on to the next usable file in the zip.
            logger.exception(
                "Required column missing in %s (%s, %s) - skipping this file, no insert",
                file_path, discovered.dataset, tracking_year
            )
            continue

    status = "success" if inserted_total > 0 else "success_no_new_rows"
    db_manager.record_processed_file(zip_path, discovered.dataset, tracking_year, status, checksum)

    return inserted_total > 0


def run_pipeline() -> None:
    """Main entry point for a single pipeline run."""
    logger.info("=== Starting CMS Anesthesia pipeline run ===")
    db_manager.init_db()

    discovered_files: List[DiscoveredFile] = get_available_files()
    if not discovered_files:
        logger.info("No conversion factor / CPT base unit / zip mapping files discovered.")
        return

    new_conversion_factor_years = []
    new_cpt_years = []
    new_zip_mapping_years = []

    for discovered in discovered_files:
        try:
            was_new = _process_file(discovered)
        except Exception:
            logger.exception("Failed processing %s (%s, %s)", discovered.url, discovered.dataset, discovered.year)
            continue

        if was_new:
            tracking_year = _tracking_year(discovered)
            if discovered.dataset == settings.DATASET_CONVERSION_FACTOR:
                new_conversion_factor_years.append(tracking_year)
            elif discovered.dataset == settings.DATASET_CPT_BASE_UNITS:
                new_cpt_years.append(tracking_year)
            elif discovered.dataset == settings.DATASET_ZIP_MAPPING:
                new_zip_mapping_years.append(tracking_year)

    sqlite_status = "updated" if (new_conversion_factor_years or new_cpt_years or new_zip_mapping_years) else "no changes"
    notify_if_needed(new_conversion_factor_years, new_cpt_years, new_zip_mapping_years, sqlite_status)

    logger.info("=== Pipeline run complete ===")
