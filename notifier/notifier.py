"""
notifier.py
-----------
STEP 12: Send an email after every pipeline run - whether or not new data
was found - so there's always a confirmation the run happened.

Subject: "CMS Anesthesia Data Updated" when new rows were inserted,
"CMS Anesthesia Data - No New Data" otherwise.
Body includes: new Conversion Factor year(s), new CPT Base Unit year(s),
new Zip Mapping file(s), and the SQLite update status.
"""

import smtplib
import logging
from email.mime.text import MIMEText
from typing import List

from config import settings

logger = logging.getLogger(__name__)

EMAIL_SUBJECT_UPDATED = "CMS Anesthesia Data Updated"
EMAIL_SUBJECT_NO_CHANGE = "CMS Anesthesia Data - No New Data"


def build_email_body(new_conversion_factor_years: List[int],
                      new_cpt_years: List[int],
                      new_zip_mapping_years: List[int],
                      sqlite_status: str) -> str:
    lines = ["CMS Anesthesia Data Automation - Run Summary", ""]

    if new_conversion_factor_years:
        lines.append(f"New Conversion Factor year(s): {', '.join(map(str, sorted(new_conversion_factor_years)))}")
    else:
        lines.append("New Conversion Factor year(s): none")

    if new_cpt_years:
        lines.append(f"New CPT Base Unit year(s): {', '.join(map(str, sorted(new_cpt_years)))}")
    else:
        lines.append("New CPT Base Unit year(s): none")

    if new_zip_mapping_years:
        lines.append(f"New Zip Mapping file(s) processed (tag year): {', '.join(map(str, sorted(new_zip_mapping_years)))}")
    else:
        lines.append("New Zip Mapping file(s): none")

    lines.append(f"SQLite update status: {sqlite_status}")

    if not new_conversion_factor_years and not new_cpt_years and not new_zip_mapping_years:
        lines.append("")
        lines.append("No new data was found on the CMS site this run - database unchanged.")

    return "\n".join(lines)


def send_email(body: str, subject: str = EMAIL_SUBJECT_UPDATED) -> None:
    if not settings.EMAIL_TO or not settings.SMTP_USERNAME:
        logger.warning("Email not configured (EMAIL_TO / SMTP_USERNAME missing) - skipping send.")
        logger.info("Would have sent:\n%s", body)
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = settings.EMAIL_TO

    recipients = [addr.strip() for addr in settings.EMAIL_TO.split(",") if addr.strip()]

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.EMAIL_FROM, recipients, msg.as_string())

    logger.info("Notification email sent to %s (subject: %s)", recipients, subject)


def notify_if_needed(new_conversion_factor_years: List[int],
                      new_cpt_years: List[int],
                      new_zip_mapping_years: List[int],
                      sqlite_status: str) -> None:
    """
    Always sends a run-summary email - whether or not anything new was
    found - so every pipeline run gets a confirmation email either way.
    The subject line and body both make clear whether there was new data.
    """
    has_new_data = bool(new_conversion_factor_years or new_cpt_years or new_zip_mapping_years)
    subject = EMAIL_SUBJECT_UPDATED if has_new_data else EMAIL_SUBJECT_NO_CHANGE

    body = build_email_body(new_conversion_factor_years, new_cpt_years, new_zip_mapping_years, sqlite_status)
    send_email(body, subject=subject)