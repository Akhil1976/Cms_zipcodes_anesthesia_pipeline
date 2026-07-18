"""
downloader.py
-------------
STEP 4 and STEP 5 of the workflow:
    - Download the ZIP file for a discovered dataset/year
    - Extract it into a per-year folder
    - Skip junk entries (__MACOSX, hidden files, .txt files)
"""

import os
import logging
import zipfile
from typing import List

import requests

from config import settings

logger = logging.getLogger(__name__)


def download_zip(url: str, dataset: str, year: int) -> str:
    """
    Download a zip file to downloads/<dataset>_<year>.zip
    Returns the local file path.
    """
    os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
    filename = f"{dataset}_{year}.zip"
    local_path = os.path.join(settings.DOWNLOAD_DIR, filename)

    logger.info("Downloading %s -> %s", url, local_path)
    with requests.get(
        url, headers=settings.REQUEST_HEADERS, timeout=settings.REQUEST_TIMEOUT, stream=True
    ) as response:
        response.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    return local_path


def extract_zip(zip_path: str, dataset: str, year: int) -> str:
    """
    Extract a zip file into downloads/extracted/<dataset>_<year>/
    Returns the extraction directory path.
    """
    extract_to = os.path.join(settings.EXTRACT_DIR, f"{dataset}_{year}")
    os.makedirs(extract_to, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_to)

    logger.info("Extracted %s -> %s", zip_path, extract_to)
    return extract_to


def list_usable_files(extract_dir: str) -> List[str]:
    """
    Walk the extraction directory and return files worth reading,
    in priority order: CSV first, then Excel, ignoring TXT/__MACOSX/hidden files.
    """
    csv_files = []
    excel_files = []

    for root, dirs, files in os.walk(extract_dir):
        dirs[:] = [d for d in dirs if d not in settings.IGNORED_NAMES and not d.startswith(".")]
        for name in files:
            if name.startswith(".") or name in settings.IGNORED_NAMES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in settings.IGNORED_EXTENSIONS:
                continue

            full_path = os.path.join(root, name)
            if ext == ".csv":
                csv_files.append(full_path)
            elif ext in (".xlsx", ".xls"):
                excel_files.append(full_path)

    # CSV takes priority over Excel, per STEP 6
    return csv_files if csv_files else excel_files
