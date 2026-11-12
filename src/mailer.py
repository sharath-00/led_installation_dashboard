from __future__ import annotations

import re
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import pandas as pd

from src.analytics import LedAnalysis
from src.config import EmailConfig


def _sender_domain(sender_email: str) -> str:
    if "@" in sender_email:
        dom = sender_email.split("@", 1)[1].strip().lower()
        if dom:
            return dom
    return "led-dashboard.local"


def _normalize_thread_id(raw_id: str, sender_email: str, thread_key: str = "") -> str:
    val = (raw_id or "").strip()
    if val:
        if not val.startswith("<"):
            val = f"<{val}"
        if not val.endswith(">"):
            val = f"{val}>"
        return val
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", (thread_key or "").strip()).strip("-")
    local_part = f"led-dashboard-{slug}" if slug else "led-dashboard-thread"
    return f"<{local_part}@{_sender_domain(sender_email)}>"


def build_dashboard_email_message(
    email_cfg: EmailConfig,
    subject: str,
    html_body: str,
    plain_body: str,
    *,
    attachments: list[tuple[str, pd.DataFrame]] | None = None,
    thread_key: str = "",
) -> EmailMessage:
    if not email_cfg.sender_email:
        raise ValueError("Sender email is required.")
    if not email_cfg.recipients:
        raise ValueError("At least one recipient email address is required.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((email_cfg.sender_name, email_cfg.sender_email))
    msg["To"] = ", ".join(email_cfg.recipients)
    if email_cfg.cc:
        msg["Cc"] = ", ".join(email_cfg.cc)

    domain = _sender_domain(email_cfg.sender_email)
    msg["Message-ID"] = make_msgid(domain=domain)

    if email_cfg.thread_enabled:
        root_id = _normalize_thread_id(email_cfg.thread_id, email_cfg.sender_email, thread_key=thread_key)
        msg["In-Reply-To"] = root_id
        msg["References"] = root_id
        topic = re.sub(r"^(?:(?:Re|Fwd|Fw)\s*:\s*)+", "", subject.strip(), flags=re.IGNORECASE).strip()
        if topic:
            msg["Thread-Topic"] = topic

    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")

    if attachments:
        for filename, df in attachments:
            if df is not None and not df.empty:
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                msg.add_attachment(
                    csv_bytes,
                    maintype="text",
                    subtype="csv",
                    filename=filename,
                )

    return msg


def format_subject(
    template: str,
    analysis: LedAnalysis,
    sheet_title: str = "LED Sheet",
) -> str:
    k = analysis.kpis
    yesterday_fallback = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
    yesterday_date_val = k.daily_date or yesterday_fallback
    safe_vars = {
        "overall_total": f"{k.overall_total:,}",
        "daily_total": f"{k.daily_total:,}",
        "yesterday_total": f"{k.daily_total:,}",
        "daily_date": yesterday_date_val,
        "yesterday_date": yesterday_date_val,
        "overall_date": k.overall_date or yesterday_fallback,
        "wards_count": f"{k.wards_count:,}",
        "constituencies_count": f"{k.constituencies_count:,}",
        "top_wattage": k.top_wattage,
        "date": datetime.now().strftime("%d %b %Y"),
        "sheet_title": sheet_title,
    }
    if not k.has_daily and ("{daily_total}" in template or "{yesterday_total}" in template):
        return (
            f"[LED Installation Report] {k.overall_total:,} Lamps Installed "
            f"- {safe_vars['overall_date']}"
        )
    try:
        return template.format(**safe_vars)
    except Exception:
        return (
            f"[LED Installation Report] {k.overall_total:,} Lamps Installed "
            f"- {safe_vars['date']}"
        )


def send_dashboard_email(
    email_cfg: EmailConfig,
    subject: str,
    html_body: str,
    plain_body: str,
    *,
    attachments: list[tuple[str, pd.DataFrame]] | None = None,
    thread_key: str = "",
) -> None:
    if not email_cfg.sender_email:
        raise ValueError("Sender email is required.")
    if not email_cfg.smtp_password:
        raise ValueError("SMTP password / Gmail App Password is required.")
    if not email_cfg.recipients:
        raise ValueError("At least one recipient email address is required.")

    msg = build_dashboard_email_message(
        email_cfg,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        attachments=attachments,
        thread_key=thread_key,
    )

    all_recipients = list(dict.fromkeys(email_cfg.recipients + email_cfg.cc))

    if email_cfg.smtp_port == 465 and not email_cfg.use_tls:
        with smtplib.SMTP_SSL(email_cfg.smtp_host, email_cfg.smtp_port, timeout=30) as server:
            server.login(email_cfg.sender_email, email_cfg.smtp_password)
            server.send_message(msg, to_addrs=all_recipients)
    else:
        with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port, timeout=30) as server:
            server.ehlo()
            if email_cfg.use_tls:
                server.starttls()
                server.ehlo()
            server.login(email_cfg.sender_email, email_cfg.smtp_password)
            server.send_message(msg, to_addrs=all_recipients)
