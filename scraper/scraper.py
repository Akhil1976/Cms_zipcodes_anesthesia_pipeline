"""
scraper.py
----------
Responsible for STEP 1 and STEP 2 of the workflow:
    - Load the CMS Anesthesiologists Information Center page
    - Parse the Billing & Payment section with BeautifulSoup
    - Identify the Conversion Factor (.zip) and CPT Base Unit (.zip) links
    - Extract the "year" associated with each file from its link text

NOTE ON THE 403 ISSUE (carried over from the CLFS project):
CMS pages are sometimes served behind bot-protection that blocks plain
`requests` calls with a 403 Forbidden. If that happens here too, swap
`fetch_page()`'s requests call for a Selenium/Playwright-rendered fetch,
exactly like we planned for the CLFS pipeline. The rest of the pipeline
(parsing/db/email) does not need to change - only how the raw HTML is
retrieved.
"""

import re
import logging
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredFile:
    """Represents one downloadable file found on the CMS page."""
    dataset: str        # settings.DATASET_CONVERSION_FACTOR or DATASET_CPT_BASE_UNITS
    year: Optional[int]
    url: str
    link_text: str


def fetch_page(url: str = settings.CMS_ANESTHESIA_URL) -> str:
    """
    Fetch raw HTML for the CMS Anesthesiologists Information Center page.

    Raises requests.HTTPError on non-200 responses (including the 403 case,
    which the caller / operator should notice in logs and escalate to the
    Selenium/Playwright fallback).
    """
    logger.info("Fetching CMS Anesthesiology page: %s", url)
    response = requests.get(
        url,
        headers=settings.REQUEST_HEADERS,
        timeout=settings.REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.text


def _detect_dataset(link_text: str) -> Optional[str]:
    text = link_text.lower()
    if any(k in text for k in settings.ZIP_MAPPING_KEYWORDS):
        return settings.DATASET_ZIP_MAPPING
    if any(k in text for k in settings.CONVERSION_FACTOR_KEYWORDS):
        return settings.DATASET_CONVERSION_FACTOR
    if any(k in text for k in settings.CPT_BASE_UNIT_KEYWORDS):
        return settings.DATASET_CPT_BASE_UNITS
    return None


def _extract_year(text: str) -> Optional[int]:
    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None


def find_data_links(html: str, base_url: str, allowed_datasets: Optional[List[str]] = None) -> List[DiscoveredFile]:
    """
    Parse a CMS page and return every .zip link that matches one of the
    known datasets (conversion_factor / cpt_base_units / zip_mapping).

    `allowed_datasets` restricts matches to only the datasets expected from
    this particular page, so a stray keyword match on the wrong page can't
    smuggle in a file tagged with the wrong dataset.
    """
    soup = BeautifulSoup(html, "html.parser")
    discovered: List[DiscoveredFile] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not href.lower().endswith(".zip"):
            continue

        link_text = anchor.get_text(strip=True)
        dataset = _detect_dataset(link_text) or _detect_dataset(href)
        if dataset is None:
            continue
        if allowed_datasets is not None and dataset not in allowed_datasets:
            continue

        year = _extract_year(link_text) or _extract_year(href)
        full_url = urljoin(base_url, href)

        discovered.append(
            DiscoveredFile(dataset=dataset, year=year, url=full_url, link_text=link_text)
        )

    logger.info("Discovered %d candidate data files from %s", len(discovered), base_url)
    return discovered


def get_anesthesia_files() -> List[DiscoveredFile]:
    """Source 1: Anesthesiologists Information Center -> conversion_factor, cpt_base_units."""
    html = fetch_page(settings.CMS_ANESTHESIA_URL)
    return find_data_links(
        html,
        base_url=settings.CMS_ANESTHESIA_URL,
        allowed_datasets=[settings.DATASET_CONVERSION_FACTOR, settings.DATASET_CPT_BASE_UNITS],
    )


def get_zip_mapping_files() -> List[DiscoveredFile]:
    """Source 2: Fee Schedules - General Information -> zip_mapping."""
    html = fetch_page(settings.CMS_ZIP_LOCALITY_URL)
    return find_data_links(
        html,
        base_url=settings.CMS_ZIP_LOCALITY_URL,
        allowed_datasets=[settings.DATASET_ZIP_MAPPING],
    )


def get_available_files() -> List[DiscoveredFile]:
    """Convenience wrapper: fetch both CMS source pages and return all discovered files."""
    return get_anesthesia_files() + get_zip_mapping_files()
