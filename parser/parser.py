"""
parser.py
---------
STEP 8: Turn a cleaned DataFrame into the rows expected by each SQLite
table, for all three datasets:

zip_mapping dataset (Source 2: Fee Schedules - General Information):
    zip_mapping         (zip_fee_year, zip_code, mdcr_carrier_id, mdcr_fee_schd_id)

Conversion Factor dataset (Source 1: Anesthesiologists Information Center):
    conversion_factor   (pricing_year, mdcr_carrier_id, mdcr_fee_schd_id, conv_factor_amt)

CPT dataset (Source 1: Anesthesiologists Information Center):
    cpt_base_units       (year, cpt_code, base_units, description)

Column names in real CMS files vary release to release, so each parser
uses a small alias map to find the right source column regardless of
exact header wording/case.

Per project notes: if a required standardized column can't be found,
we do NOT insert - _find_column raises KeyError, and the caller
(pipeline.py) treats that as a hard failure for that file.
"""

import logging
import re
from typing import List, Dict, Any, Optional
import pandas as pd

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """Lowercase, collapse underscores/multiple spaces so 'ZIP_CODE' and
    'Zip   Code' both normalize the same way as 'zip code'."""
    return " ".join(str(text).lower().replace("_", " ").split())


def _find_column(df: pd.DataFrame, aliases: List[str]) -> str:
    """Return the first dataframe column whose (normalized) name matches
    one of the given aliases, checked in order - so put the most specific
    alias first and the most generic fallback (e.g. "code") last, since
    generic aliases can accidentally match the wrong column otherwise.
    Raises if none found."""
    normalized_cols = {_normalize(c): c for c in df.columns}
    for alias in aliases:
        alias_norm = _normalize(alias)
        for norm_name, original in normalized_cols.items():
            if alias_norm in norm_name:
                return original
    raise KeyError(f"None of the expected columns {aliases} found in {list(df.columns)}")


def _find_column_optional(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    try:
        return _find_column(df, aliases)
    except KeyError:
        return None


# ---------------------------------------------------------------------------
# ZIP Mapping dataset (Source 2)
# ---------------------------------------------------------------------------

ZIP_MAPPING_HEADER_HINTS = ["zip code", "carrier", "locality", "year/qtr"]


def _extract_year_from_year_qtr(raw_value: str) -> Optional[int]:
    """
    YEAR/QTR values are formatted as YYYYQ (year + single quarter digit),
    e.g. 20254 -> year 2025, quarter 4. Extract just the year.
    """
    digits = re.sub(r"\D", "", str(raw_value))
    if len(digits) < 5:
        return None
    year_part = digits[:4]
    try:
        return int(year_part)
    except ValueError:
        return None


def parse_zip_mapping(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Parses the Zip Code to Carrier Locality File into zip_mapping rows.

    Uses only: ZIP CODE, CARRIER, LOCALITY, YEAR/QTR.
    Ignores: STATE, RURAL IND, LAB CB LOCALITY, RURAL IND2, PLUS 4 FLAG,
    PART B DRUG INDICATOR (and anything else present).

    zip_fee_year is taken per-row from YEAR/QTR (not from the file/URL),
    since a single file can span multiple years/quarters.
    """
    col_zip = _find_column(df, ["zip code", "zip"])
    col_carrier = _find_column(df, ["carrier"])
    col_locality = _find_column(df, ["locality"])
    col_year_qtr = _find_column(df, ["year/qtr", "year qtr", "yr qtr"])

    rows = []
    skipped_bad_year = 0

    for _, row in df.iterrows():
        zip_code = str(row.get(col_zip, "")).strip()
        carrier_id = str(row.get(col_carrier, "")).strip()
        fee_schd_id = str(row.get(col_locality, "")).strip()
        year_qtr_raw = str(row.get(col_year_qtr, "")).strip()

        if not zip_code or not carrier_id:
            continue

        zip_fee_year = _extract_year_from_year_qtr(year_qtr_raw)
        if zip_fee_year is None:
            skipped_bad_year += 1
            continue

        rows.append({
            "zip_fee_year": zip_fee_year,
            "zip_code": zip_code,
            "mdcr_carrier_id": carrier_id,
            "mdcr_fee_schd_id": fee_schd_id,
        })

    if skipped_bad_year:
        logger.warning("Skipped %d zip_mapping rows with unparseable YEAR/QTR", skipped_bad_year)

    logger.info("Parsed zip mapping file: %d zip_mapping rows", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Conversion Factor dataset (Source 1)
# ---------------------------------------------------------------------------

CONVERSION_FACTOR_HEADER_HINTS = ["contractor", "locality", "anes cf"]


def _find_conversion_factor_column(df: pd.DataFrame) -> str:
    """
    Conversion factor column selection rule:
      - If BOTH "Non-Qualifying APM National Anes CF" and
        "Qualifying APM National Anes CF" columns exist, use ONLY the
        Non-Qualifying one.
      - Otherwise, if a single generic conversion-factor column exists
        (e.g. "National Anes CF"), use it directly.
    """
    non_qualifying = _find_column_optional(
        df, ["non-qualifying apm national anes cf", "non qualifying apm national anes cf"]
    )
    qualifying = _find_column_optional(df, ["qualifying apm national anes cf"])

    if non_qualifying and qualifying:
        logger.info("Both Non-Qualifying and Qualifying APM CF columns present - using Non-Qualifying only")
        return non_qualifying
    if non_qualifying:
        return non_qualifying

    # Fall back to a single generic conversion-factor column.
    return _find_column(df, ["national anes cf", "conversion factor", "conv factor", "conv_factor", "anes cf", "cf"])


def parse_conversion_factor(df: pd.DataFrame, year: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    Returns a dict with the conversion_factor row-list ready for insertion:
        {"conversion_factor": [...]}

    Uses only: Contractor, Locality, and the applicable conversion-factor
    column. Ignores: Work GPCI, PE GPCI, MP GPCI, Locality Name.
    """
    col_carrier = _find_column(df, ["contractor"])
    # Match the bare "Locality" column, not "Locality Name" - "locality"
    # alone is a substring of "locality name" too, so if a file only has
    # "Locality Name" and no plain "Locality" column this will (correctly)
    # fall through to matching "Locality Name" as a last resort. Real CMS
    # anesthesia CF files always have a plain "Locality" column though.
    col_locality = _find_column(df, ["locality"])
    col_conv_factor = _find_conversion_factor_column(df)

    conversion_factor_rows = []
    seen_carrier_locality = set()

    for _, row in df.iterrows():
        carrier_id = str(row.get(col_carrier, "")).strip()
        fee_schd_id = str(row.get(col_locality, "")).strip()
        conv_factor_raw = str(row.get(col_conv_factor, "")).strip()

        if not carrier_id:
            continue

        key = (carrier_id, fee_schd_id)
        if key in seen_carrier_locality or not conv_factor_raw:
            continue

        try:
            conv_factor_amt = float(conv_factor_raw.replace("$", "").replace(",", ""))
        except ValueError:
            continue

        conversion_factor_rows.append({
            "pricing_year": year,
            "mdcr_carrier_id": carrier_id,
            "mdcr_fee_schd_id": fee_schd_id,
            "conv_factor_amt": conv_factor_amt,
        })
        seen_carrier_locality.add(key)

    logger.info(
        "Parsed conversion factor file for %d: %d conversion_factor rows",
        year, len(conversion_factor_rows)
    )
    return {"conversion_factor": conversion_factor_rows}


# ---------------------------------------------------------------------------
# CPT Base Unit dataset (Source 1)
# ---------------------------------------------------------------------------

CPT_BASE_UNIT_HEADER_HINTS = ["code", "base", "unit"]


def parse_cpt_base_units(df: pd.DataFrame, year: int) -> List[Dict[str, Any]]:
    """
    Uses only: CODE, BASE UNIT(S). DESCRIPTION is optional.

    NOTE: cleaner.clean_dataframe() already merges the 3-row split
    CODE/BASE/UNIT header into single columns named "CODE" and
    "BASE_UNIT" for the files that use that layout, so the aliases below
    match both that merged layout and any file with a normal single-row
    "base units"/"base unit" header.
    """
    col_cpt = _find_column(df, ["code", "cpt code", "cpt"])
    col_base_units = _find_column(df, ["base_unit", "base units", "base unit"])
    col_description = _find_column_optional(df, ["long description", "description", "procedure"])

    rows = []
    for _, row in df.iterrows():
        cpt_code = str(row.get(col_cpt, "")).strip()
        base_units_raw = str(row.get(col_base_units, "")).strip()
        description = str(row.get(col_description, "")).strip() if col_description else ""

        if not cpt_code or not base_units_raw:
            continue

        try:
            base_units = float(base_units_raw)
        except ValueError:
            continue

        rows.append({
            "year": year,
            "cpt_code": cpt_code,
            "base_units": base_units,
            "description": description,
        })

    logger.info("Parsed CPT base unit file for %d: %d rows", year, len(rows))
    return rows
