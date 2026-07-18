"""
Central configuration for the CMS Anesthesiology Data Automation project.
Keep secrets (email password, SMTP creds) in environment variables, never hardcoded.
"""

import os
from dotenv import load_dotenv

# Load variables from a local .env file (if present) into the process
# environment, BEFORE anything below reads os.environ.get(...). This makes
# .env work for local/manual runs. In production (cron, systemd, Docker),
# you can skip .env entirely and export real environment variables instead -
# load_dotenv() silently does nothing if no .env file is found, and it
# never overrides a variable that's already set in the real environment.
load_dotenv()

# ---------------------------------------------------------------------------
# Source websites
# ---------------------------------------------------------------------------
# Source 1: Anesthesiologists Information Center -> conversion_factor, cpt_base_units
CMS_ANESTHESIA_URL = "https://www.cms.gov/anesthesiologists-information-center"

# Source 2: Fee Schedules - General Information -> zip_mapping
# (the "Zip Code to Carrier Locality File" and its "End of Year" archives)
CMS_ZIP_LOCALITY_URL = "https://www.cms.gov/medicare/payment/fee-schedules"

# ---------------------------------------------------------------------------
# Local paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
EXTRACT_DIR = os.path.join(DOWNLOAD_DIR, "extracted")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(BASE_DIR, "cms_anesthesia.db")

# ---------------------------------------------------------------------------
# Dataset identifiers (used to tag which parser/table a downloaded file maps to)
# ---------------------------------------------------------------------------
DATASET_CONVERSION_FACTOR = "conversion_factor"
DATASET_CPT_BASE_UNITS = "cpt_base_units"
DATASET_ZIP_MAPPING = "zip_mapping"

# Keywords used to detect which dataset a link on the page belongs to.
# NOTE: "zip code" / "locality" were removed from CONVERSION_FACTOR_KEYWORDS -
# those words describe the *separate* zip_mapping file (Source 2), not the
# anesthesia conversion factor file (Source 1), which is keyed by
# Contractor/Locality, never ZIP code.
CONVERSION_FACTOR_KEYWORDS = ["conversion factor", "locality adjusted", "anesthesia cf"]
CPT_BASE_UNIT_KEYWORDS = ["cpt", "base unit", "anesthesia base unit"]
ZIP_MAPPING_KEYWORDS = ["zip code to carrier locality", "end of year zip code", "zip code carrier locality"]

# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------
ALLOWED_DATA_EXTENSIONS = [".csv", ".xlsx", ".xls"]
IGNORED_NAMES = ["__MACOSX", ".DS_Store"]
IGNORED_EXTENSIONS = [".txt"]

# ---------------------------------------------------------------------------
# Email notification settings (pull from environment variables)
# ---------------------------------------------------------------------------
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USERNAME)
EMAIL_TO = os.environ.get("EMAIL_TO", "")  # comma-separated list allowed

EMAIL_SUBJECT = "CMS Anesthesia Data Updated"

# ---------------------------------------------------------------------------
# HTTP settings
# ---------------------------------------------------------------------------
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 30  # seconds

# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
# Cron-style schedule is preferred in production (see scheduler.py notes).
# This is only used for the in-process fallback scheduler.
RUN_INTERVAL_HOURS = 72