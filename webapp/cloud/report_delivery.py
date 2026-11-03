"""Private storage and email delivery helpers for generated reports."""
from __future__ import annotations

import html
import os

import requests


def email_report(recipient, project_name, links):
    key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("REPORT_EMAIL_FROM", "").strip()
    if not key or not sender:
        return False
    rows = "".join(
        f'<li><a href="{html.escape(url, quote=True)}">Download {html.escape(label)}</a></li>'
        for label, url in links.items()
    )
    response = requests.post(
        "https://api.resend.com/emails", timeout=30,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json={
            "from": sender, "to": [recipient],
            "subject": "MKA site visit report - " + project_name,
            "html": (
                "<p>Your MKA site visit report is ready.</p><ul>" + rows +
                "</ul><p>These secure links expire in seven days. The files remain available "
                "inside MKA Site Visit Buddy.</p><p>Draft - engineer review required.</p>"
            ),
        },
    )
    response.raise_for_status()
    return True
