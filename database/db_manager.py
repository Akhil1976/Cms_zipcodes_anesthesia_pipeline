"""
db_manager.py
-------------
STEP 9 and STEP 10 of the workflow: SQLite schema + insert logic.

Tables:
    zip_mapping        (zip_fee_year, zip_code, mdcr_carrier_id, mdcr_fee_schd_id)
    conversion_factor  (pricing_year, mdcr_carrier_id, mdcr_fee_schd_id, conv_factor_amt)
    cpt_base_units     (year, cpt_code, base_units, description)
    processed_files     -- download history: file_name, year, download_date, status, checksum
    change_log          -- tracks what changed on each run (mirrors the CLFS project design)

Duplicate-safe by design: every data table has a UNIQUE constraint on its
natural key, and inserts use "INSERT OR IGNORE" so re-running the pipeline
on the same year/file never creates duplicate rows.
"""

import sqlite3
import hashlib
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Any, Iterator

from config import settings

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS zip_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zip_fee_year INTEGER NOT NULL,
    zip_code TEXT NOT NULL,
    mdcr_carrier_id TEXT NOT NULL,
    mdcr_fee_schd_id TEXT,
    UNIQUE(zip_fee_year, zip_code, mdcr_carrier_id)
);

CREATE TABLE IF NOT EXISTS conversion_factor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pricing_year INTEGER NOT NULL,
    mdcr_carrier_id TEXT NOT NULL,
    mdcr_fee_schd_id TEXT,
    conv_factor_amt REAL NOT NULL,
    UNIQUE(pricing_year, mdcr_carrier_id, mdcr_fee_schd_id)
);

CREATE TABLE IF NOT EXISTS cpt_base_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    cpt_code TEXT NOT NULL,
    base_units REAL NOT NULL,
    description TEXT,
    UNIQUE(year, cpt_code)
);

CREATE TABLE IF NOT EXISTS processed_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    dataset TEXT NOT NULL,
    year INTEGER NOT NULL,
    download_date TEXT NOT NULL,
    status TEXT NOT NULL,
    checksum TEXT,
    UNIQUE(dataset, year)
);

CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    dataset TEXT NOT NULL,
    year INTEGER NOT NULL,
    rows_inserted INTEGER NOT NULL,
    note TEXT
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't already exist."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    logger.info("Database initialized at %s", settings.DB_PATH)


def year_already_processed(dataset: str, year: int) -> bool:
    """STEP 3: check whether this dataset/year combo is already in SQLite."""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT 1 FROM processed_files WHERE dataset = ? AND year = ? AND status = 'success'",
            (dataset, year),
        )
        return cur.fetchone() is not None


def compute_checksum(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def record_processed_file(file_name: str, dataset: str, year: int, status: str, checksum: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO processed_files (file_name, dataset, year, download_date, status, checksum)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset, year) DO UPDATE SET
                file_name=excluded.file_name,
                download_date=excluded.download_date,
                status=excluded.status,
                checksum=excluded.checksum
            """,
            (file_name, dataset, year, datetime.utcnow().isoformat(), status, checksum),
        )


def _insert_rows(conn: sqlite3.Connection, table: str, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    col_names = ", ".join(columns)
    sql = f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"

    before = conn.total_changes
    conn.executemany(sql, [tuple(row[c] for c in columns) for row in rows])
    after = conn.total_changes
    return after - before


def insert_conversion_factor_data(conversion_factor_rows: List[Dict[str, Any]], year: int) -> int:
    with get_connection() as conn:
        n = _insert_rows(conn, "conversion_factor", conversion_factor_rows)
        conn.execute(
            "INSERT INTO change_log (run_date, dataset, year, rows_inserted, note) VALUES (?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), settings.DATASET_CONVERSION_FACTOR, year, n, "conversion_factor"),
        )
    logger.info("Inserted conversion factor data for %d: %d new rows", year, n)
    return n


def insert_zip_mapping_data(zip_mapping_rows: List[Dict[str, Any]], year: int) -> int:
    """`year` here is just the log/change_log tag for this file/run - each
    row carries its own zip_fee_year (extracted from YEAR/QTR), since a
    single zip-locality file can span multiple years/quarters."""
    with get_connection() as conn:
        n = _insert_rows(conn, "zip_mapping", zip_mapping_rows)
        conn.execute(
            "INSERT INTO change_log (run_date, dataset, year, rows_inserted, note) VALUES (?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), settings.DATASET_ZIP_MAPPING, year, n, "zip_mapping"),
        )
    logger.info("Inserted zip mapping data (tagged year %s): %d new rows", year, n)
    return n


def insert_cpt_base_unit_data(rows: List[Dict[str, Any]], year: int) -> int:
    with get_connection() as conn:
        n = _insert_rows(conn, "cpt_base_units", rows)
        conn.execute(
            "INSERT INTO change_log (run_date, dataset, year, rows_inserted, note) VALUES (?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), settings.DATASET_CPT_BASE_UNITS, year, n, "cpt_base_units"),
        )
    logger.info("Inserted CPT base unit data for %d: %d new rows", year, n)
    return n
