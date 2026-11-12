from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.yaml"
DEFAULT_ENV_PATH = BASE_DIR / ".env"


@dataclass
class GoogleSheetConfig:
    service_account_file: str = "service_account.json"
    spreadsheet_id_or_url: str = ""
    overall_worksheet: str = ""
    daily_worksheet: str = ""
    raw_worksheet: str = ""

    def resolved_service_account_path(self) -> Path:
        p = Path(self.service_account_file)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p


@dataclass
class ReportConfig:
    title: str = "LED Lamp Installation Mail Dashboard"
    subtitle: str = "Corporation, Constituency, Ward & Wattage Analytics"
    top_wards_limit: int = 10


@dataclass
class EmailConfig:
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    use_tls: bool = True
    sender_name: str = "LED Installation Analytics"
    sender_email: str = ""
    smtp_password: str = ""
    recipients: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    subject_template: str = (
        "[LED Installation Report] {overall_total} Lamps Installed | Yesterday +{yesterday_total} ({yesterday_date})"
    )


@dataclass
class AppConfig:
    google_sheet: GoogleSheetConfig = field(default_factory=GoogleSheetConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    email: EmailConfig = field(default_factory=EmailConfig)


def _split_csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_or(key: str, default: Any) -> Any:
    val = os.getenv(key)
    if val is not None and val.strip() != "":
        return val.strip()
    return default


def load_config(config_path: Path | None = None) -> AppConfig:
    if DEFAULT_ENV_PATH.exists():
        load_dotenv(DEFAULT_ENV_PATH, override=True)

    path = config_path or DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    gs_raw = raw.get("google_sheet", {}) or {}
    rep_raw = raw.get("report", {}) or {}
    em_raw = raw.get("email", {}) or {}

    google_sheet = GoogleSheetConfig(
        service_account_file=_env_or(
            "GOOGLE_SERVICE_ACCOUNT_FILE",
            gs_raw.get("service_account_file", "service_account.json"),
        ),
        spreadsheet_id_or_url=_env_or(
            "GOOGLE_SHEET_URL_OR_ID",
            gs_raw.get("spreadsheet_id_or_url", ""),
        ),
        overall_worksheet=_env_or(
            "GOOGLE_OVERALL_WORKSHEET",
            gs_raw.get("overall_worksheet", gs_raw.get("worksheet_name", "")),
        ),
        daily_worksheet=_env_or(
            "GOOGLE_DAILY_WORKSHEET",
            gs_raw.get("daily_worksheet", ""),
        ),
        raw_worksheet=_env_or(
            "GOOGLE_RAW_WORKSHEET",
            gs_raw.get("raw_worksheet", ""),
        ),
    )

    report = ReportConfig(
        title=rep_raw.get("title", "LED Lamp Installation Mail Dashboard"),
        subtitle=rep_raw.get(
            "subtitle", "Corporation, Constituency, Ward & Wattage Analytics"
        ),
        top_wards_limit=int(rep_raw.get("top_wards_limit", 10)),
    )

    env_recipients = _split_csv_list(os.getenv("EMAIL_RECIPIENTS"))
    env_cc = _split_csv_list(os.getenv("EMAIL_CC"))
    use_tls_env = _env_or("SMTP_USE_TLS", None)
    use_tls = (
        str(use_tls_env).strip().lower() in {"1", "true", "yes"}
        if use_tls_env is not None
        else bool(em_raw.get("use_tls", True))
    )

    smtp_host = _env_or(
        "SMTP_HOST",
        _env_or("SMTP_SERVER", em_raw.get("smtp_host", "smtp.gmail.com")),
    )
    raw_pw = str(_env_or("SMTP_PASSWORD", ""))
    smtp_password = raw_pw.replace(" ", "") if "gmail" in str(smtp_host).lower() else raw_pw

    email = EmailConfig(
        smtp_host=smtp_host,
        smtp_port=int(_env_or("SMTP_PORT", em_raw.get("smtp_port", 587))),
        use_tls=use_tls,
        sender_name=_env_or(
            "SMTP_SENDER_NAME",
            em_raw.get("sender_name", "LED Installation Analytics"),
        ),
        sender_email=_env_or(
            "SMTP_SENDER_EMAIL",
            _env_or(
                "SENDER_EMAIL",
                _env_or("SMTP_USERNAME", em_raw.get("sender_email", "")),
            ),
        ),
        smtp_password=smtp_password,
        recipients=env_recipients or list(em_raw.get("recipients", []) or []),
        cc=env_cc or list(em_raw.get("cc", []) or []),
        subject_template=_env_or(
            "EMAIL_SUBJECT_TEMPLATE",
            em_raw.get(
                "subject_template",
                "[LED Installation Report] {overall_total} Lamps Installed | Yesterday +{yesterday_total} ({yesterday_date})",
            ),
        ),
    )

    return AppConfig(
        google_sheet=google_sheet,
        report=report,
        email=email,
    )


def save_config(cfg: AppConfig, config_path: Path | None = None) -> None:
    path = config_path or DEFAULT_CONFIG_PATH
    data = {
        "google_sheet": {
            "service_account_file": cfg.google_sheet.service_account_file,
            "spreadsheet_id_or_url": cfg.google_sheet.spreadsheet_id_or_url,
            "overall_worksheet": cfg.google_sheet.overall_worksheet,
            "daily_worksheet": cfg.google_sheet.daily_worksheet,
            "raw_worksheet": cfg.google_sheet.raw_worksheet,
        },
        "report": {
            "title": cfg.report.title,
            "subtitle": cfg.report.subtitle,
            "top_wards_limit": cfg.report.top_wards_limit,
        },
        "email": {
            "smtp_host": cfg.email.smtp_host,
            "smtp_port": cfg.email.smtp_port,
            "use_tls": cfg.email.use_tls,
            "sender_name": cfg.email.sender_name,
            "sender_email": cfg.email.sender_email,
            "recipients": cfg.email.recipients,
            "cc": cfg.email.cc,
            "subject_template": cfg.email.subject_template,
        },
    }
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
