"""
cleaner.py
----------
STEP 7 of the workflow: generic cleanup applied to any raw CMS
CSV/Excel file before it is parsed into dataset-specific columns.

    - Remove blank rows
    - Remove metadata / notes rows above the real header
    - Remove duplicate/junk rows
    - Detect the real header row and start reading from there
"""

import logging
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


def _row_stats(row: pd.Series, expected_keywords: list) -> tuple:
    """
    Returns (num_nonblank_cells, keyword_hit_count) for a row.

    keyword_hit_count counts each expected keyword only once, and only
    matches it against individual cell values (not the whole row joined
    together) - this avoids a document title like "CMS Conversion Factor
    File" being mistaken for the real header just because the phrase
    "conversion factor" appears somewhere in it.
    """
    cells = [str(cell).strip().lower() for cell in row if pd.notna(cell) and str(cell).strip() != ""]
    num_nonblank = len(cells)

    hits = 0
    for keyword in expected_keywords:
        kw = keyword.lower()
        if any(kw in cell for cell in cells):
            hits += 1

    return num_nonblank, hits


def find_header_row(raw_df: pd.DataFrame, expected_keywords: list, max_scan_rows: int = 25,
                     min_keyword_hits: int = 2, min_populated_cells: int = 3) -> int:
    """
    Scan the first `max_scan_rows` rows of a headerless raw read for the
    row that looks like the real column header.

    A row only qualifies as the header if it BOTH:
      - matches at least `min_keyword_hits` distinct expected keywords, AND
      - has at least `min_populated_cells` non-blank cells

    This filters out title rows (usually one long string in a single cell)
    and stray notes, which is what was causing row 0 to be picked as the
    header before. Returns the row index to use as header, or the
    best-scoring row if nothing clears the threshold, or 0 as a last resort.
    """
    scan_limit = min(max_scan_rows, len(raw_df))
    best_idx = None
    best_hits = -1

    for idx in range(scan_limit):
        num_nonblank, hits = _row_stats(raw_df.iloc[idx], expected_keywords)

        if hits >= min_keyword_hits and num_nonblank >= min_populated_cells:
            logger.info("Detected header row at index %d (%d keyword hits, %d populated cells)",
                        idx, hits, num_nonblank)
            return idx

        if hits > best_hits:
            best_hits = hits
            best_idx = idx

    if best_idx is not None and best_hits > 0:
        logger.warning(
            "No row cleared the strict header threshold; falling back to best partial "
            "match at row %d (%d keyword hits)", best_idx, best_hits
        )
        return best_idx

    logger.warning("No header row matched expected keywords; defaulting to row 0")
    return 0


def load_raw(file_path: str) -> pd.DataFrame:
    """Load a CSV or Excel file with no header assumption (header=None).
    Old .xls files need the xlrd engine; .xlsx needs openpyxl - pandas
    usually auto-detects this, but we set it explicitly to avoid
    "missing optional dependency" errors on older CMS files."""
    lower_path = file_path.lower()
    if lower_path.endswith(".csv"):
        return pd.read_csv(file_path, header=None, dtype=str)
    if lower_path.endswith(".xls"):
        return pd.read_excel(file_path, header=None, dtype=str, engine="xlrd")
    return pd.read_excel(file_path, header=None, dtype=str, engine="openpyxl")


def _try_merge_split_header(raw_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    The CPT Base Unit files (every year, 2010-present) don't use a single
    header row. They spread the header across 3 rows, e.g.:

        CODE, 2013
        (blank), BASE
        (blank), UNIT

    i.e. column 0's header is "CODE" (row 0 only) and column 1's header is
    "BASE UNIT" (spelled out across rows 0-2, with row 0 holding the year
    instead of a real header, and rows 1-2 holding "BASE"/"UNIT").

    Detects that exact pattern and, if found, returns a DataFrame with
    proper single-row headers ["CODE", "BASE_UNIT"] and data starting at
    row 3. Returns None if the file doesn't match this pattern, so the
    caller can fall back to normal single-row header detection.
    """
    if raw_df.shape[0] < 4 or raw_df.shape[1] < 2:
        return None

    row0 = [str(c).strip().lower() for c in raw_df.iloc[0]]
    row1 = [str(c).strip().lower() for c in raw_df.iloc[1]]
    row2 = [str(c).strip().lower() for c in raw_df.iloc[2]]

    looks_like_split_header = (
        row0[0] == "code"
        and row1[1] == "base"
        and row2[1] == "unit"
    )
    if not looks_like_split_header:
        return None

    logger.info("Detected split 3-row CPT header (CODE / BASE / UNIT) - merging into CODE, BASE_UNIT")
    data = raw_df.iloc[3:].copy()
    new_columns = ["CODE", "BASE_UNIT"] + [f"col_{i}" for i in range(2, raw_df.shape[1])]
    data.columns = new_columns
    return data


def clean_dataframe(file_path: str, expected_header_keywords: list) -> pd.DataFrame:
    """
    Full cleaning pipeline for one file:
      1. Load raw with no header
      2. Locate real header row (or merge a split multi-row header, e.g.
         the CPT Base Unit files' CODE/BASE/UNIT layout)
      3. Slice from there, promote header
      4. Drop fully blank rows
      5. Drop exact duplicate rows
    """
    raw_df = load_raw(file_path)

    data = _try_merge_split_header(raw_df)
    if data is None:
        header_idx = find_header_row(raw_df, expected_header_keywords)
        header = raw_df.iloc[header_idx]
        data = raw_df.iloc[header_idx + 1:].copy()
        data.columns = [str(c).strip() for c in header]

    # Remove fully blank rows
    data = data.dropna(how="all")

    # Remove rows that are blank in every meaningful column
    data = data.replace(r"^\s*$", pd.NA, regex=True)
    data = data.dropna(how="all")

    # Remove exact duplicate rows (junk repeated rows)
    data = data.drop_duplicates()

    data = data.reset_index(drop=True)
    logger.info("Cleaned %s -> %d usable rows", file_path, len(data))
    return data