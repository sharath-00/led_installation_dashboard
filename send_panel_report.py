from __future__ import annotations

import argparse
import time
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

import schedule

from src.analytics import analyze_panel_data, parse_panel_sheet
from src.config import BASE_DIR, load_config
from src.excel_exporter import build_panel_standalone_excel_bytes
from src.mailer import AttachmentPayload, send_dashboard_email
from src.panel_email_renderer import render_panel_email_html, render_panel_email_plain_text
from src.sheets_client import (
    auto_pick_panel_tab,
    extract_spreadsheet_id,
    fetch_raw_grid,
    get_sample_grids,
    list_worksheets,
)


def run_once(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.sheet:
        cfg.google_sheet.spreadsheet_id_or_url = args.sheet
    if args.to:
        cfg.email.recipients = [x.strip() for x in args.to.split(",") if x.strip()]
    if getattr(args, "cc", None):
        cfg.email.cc = [x.strip() for x in args.cc.split(",") if x.strip()]

    target_date_obj: date | None = None
    if getattr(args, "target_date", None):
        import re
        td_str = str(args.target_date).strip()
        m = re.match(r"^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})$", td_str)
        if m:
            p1, p2, p3 = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if p1 > 1000:
                target_date_obj = date(p1, p2, p3)
            else:
                y = p3 if p3 > 1000 else (2000 + p3 if p3 < 100 else p3)
                target_date_obj = date(y, p2, p1)

    raw_panel_data = None
    resolved_tab_name = ""
    sheet_title = "Google Sheet"

    # Offline / Sample Mode: try local high-fidelity cache first, else built-in sample
    if args.sample:
        cached_csv = BASE_DIR / "scratch" / "panel_report_raw.csv"
        if cached_csv.exists():
            import pandas as pd
            df_cache = pd.read_csv(cached_csv, dtype=str).fillna("")
            grid = [list(df_cache.columns)] + df_cache.values.tolist()
            resolved_tab_name = "PANEL REPORT"
            sheet_title = "Cached CCMS Panel Report Snapshot"
            raw_panel_data = parse_panel_sheet(grid, resolved_tab_name)
        else:
            sample = get_sample_grids()
            if "PANEL REPORT" in sample:
                resolved_tab_name = "PANEL REPORT"
                sheet_title = "Sample CCMS Panel Installation Snapshot"
                raw_panel_data = parse_panel_sheet(sample["PANEL REPORT"], resolved_tab_name)
    else:
        # Production Mode: fetch directly from Google Sheet
        sa_path = cfg.google_sheet.resolved_service_account_path()
        all_tabs = list_worksheets(sa_path, cfg.google_sheet.spreadsheet_id_or_url)
        target_tab = (
            (args.tab.strip() if getattr(args, "tab", None) else "")
            or cfg.google_sheet.panel_worksheet.strip()
            or auto_pick_panel_tab(all_tabs)
        )
        if not target_tab or target_tab not in all_tabs:
            raise ValueError(
                f"Could not locate a CCMS Panel worksheet in tabs: {all_tabs}. "
                f"Specify the tab explicitly using --tab '<name>'."
            )

        grid, sheet_title, resolved_tab_name, _ = fetch_raw_grid(
            sa_path,
            cfg.google_sheet.spreadsheet_id_or_url,
            target_tab,
        )
        raw_panel_data = parse_panel_sheet(grid, resolved_tab_name)

    if raw_panel_data is None or raw_panel_data.df.empty:
        raise ValueError(f"Failed to parse any CCMS panel data from worksheet '{resolved_tab_name}'.")

    # Run comprehensive panel analytics
    analysis = analyze_panel_data(raw_panel_data, target_date=target_date_obj)
    pk = analysis.kpis

    # Render HTML and Plain Text Dashboard
    html_body = render_panel_email_html(
        analysis,
        cfg.report,
        sheet_title=sheet_title,
        panel_tab=resolved_tab_name,
        custom_note=args.note,
    )
    plain_body = render_panel_email_plain_text(
        analysis,
        cfg.report,
        sheet_title=sheet_title,
        panel_tab=resolved_tab_name,
    )

    report_date_label = pk.daily_date if pk.has_daily else (pk.latest_date_label or datetime.now().strftime("%d/%m/%Y"))
    daily_delta_str = f" (+{pk.daily_panels:,} Panels)" if pk.has_daily else ""
    subject = f"[CCMS Panel Installation Report] Daily Infrastructure Dashboard - {report_date_label}{daily_delta_str} | {pk.total_panels:,} Cumulative"

    if args.out:
        out_path = Path(args.out)
    elif args.sample:
        out_path = BASE_DIR / "output" / "sample_panel_mail_dashboard.html"
    else:
        out_path = BASE_DIR / "output" / "latest_panel_mail_dashboard.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_body, encoding="utf-8")

    # Terminal summary output
    print("=" * 60)
    print("CCMS PANEL INSTALLATION MAIL DASHBOARD")
    print("=" * 60)
    print(f"Saved HTML dashboard preview to: {out_path}")
    print(f"Subject: {subject}")
    print(
        f"Cumulative Infrastructure: {pk.total_panels:,} panels across "
        f"{pk.zones_count} Zones, {pk.wards_count} Wards"
    )
    if pk.has_daily:
        print(f"Daily Deployment ({pk.daily_date}): +{pk.daily_panels:,} panels across {pk.daily_wards_count} Wards")
    if pk.last_7_days_total > 0:
        print(f"7-Day Run Rate: {pk.last_7_days_total:,} panels (avg {pk.avg_7d_installed:.1f}/day)")
    print(
        f"Switch Points Mapped: {pk.switch_points_mapped:,} / {pk.total_panels:,} ({pk.switch_points_mapped_pct:.1f}%) "
        f"| Pending: {max(0, pk.total_panels - pk.switch_points_mapped):,}"
    )
    print(
        f"Photo Audit Compliance: Outer Enclosure {pk.panel_photo_pct:.1f}% | "
        f"Controller/SC {pk.controller_photo_pct:.1f}% | Earthing Pit {pk.earthing_photo_pct:.1f}%"
    )

    # Attachments
    attachments: list[tuple[str, AttachmentPayload]] = []

    # Standalone CCMS Panels Multi-Tab Excel Workbook
    if not args.no_attach_excel:
        excel_name, excel_bytes, tab_counts = build_panel_standalone_excel_bytes(
            raw_panel_data,
            analysis,
            target_date=target_date_obj,
        )
        save_excel_name = f"sample_{excel_name}" if args.sample else excel_name
        excel_out_path = BASE_DIR / "output" / save_excel_name
        excel_out_path.write_bytes(excel_bytes)
        tab_summary = ", ".join(f"{t}: {c:,}" for t, c in tab_counts.items())
        print(
            f"Saved Excel workbook to: {excel_out_path} "
            f"({len(excel_bytes) / (1024 * 1024):.2f} MB | {len(tab_counts)} tabs -> {tab_summary})"
        )
        attachments.append((excel_name, excel_bytes))

    # CSV Attachments
    if args.attach_csv:
        if not analysis.zone_summary.empty:
            attachments.append(("panel_zone_summary.csv", analysis.zone_summary))
        if not analysis.ward_summary.empty:
            attachments.append(("panel_ward_summary.csv", analysis.ward_summary))
        if not analysis.installer_summary.empty:
            attachments.append(("panel_contractor_summary.csv", analysis.installer_summary))
        if not analysis.quality_summary.empty:
            attachments.append(("panel_quality_audit.csv", analysis.quality_summary))

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())

    if args.dry_run:
        print("\nDry-run mode enabled; email was not sent.")
        return 0

    thread_key = (
        "sample_panel"
        if args.sample
        else f"panel_{extract_spreadsheet_id(cfg.google_sheet.spreadsheet_id_or_url)}"
    )
    send_dashboard_email(
        cfg.email,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        attachments=attachments or None,
        thread_key=thread_key,
    )
    cc_info = f" (CC: {', '.join(cfg.email.cc)})" if cfg.email.cc else ""
    print(f"\nEmail successfully sent to: {', '.join(cfg.email.recipients)}{cc_info}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CCMS Panel Installation Mail Dashboard: fetch Google Sheet PANEL REPORT tab, build HTML dashboard, and send via SMTP."
    )
    parser.add_argument("--sheet", help="Override Google Sheet URL or ID")
    parser.add_argument("--tab", default="PANEL REPORT", help="Override CCMS Panel Report worksheet tab name (defaults to 'PANEL REPORT')")
    parser.add_argument("--target-date", help="Optional target date (DD-MM-YYYY or YYYY-MM-DD) to run the report for (defaults to yesterday / latest date)")
    parser.add_argument("--note", default="", help="Optional coordinator note to include at the top of the mail")
    parser.add_argument("--sample", action="store_true", help="Use cached / sample panel data instead of querying live Google Sheets")
    parser.add_argument("--dry-run", action="store_true", help="Generate HTML dashboard locally without sending email")
    parser.add_argument("--open", action="store_true", help="Open generated HTML mail dashboard in your browser")
    parser.add_argument("--attach-csv", action="store_true", help="Attach Zone, Ward, Contractor & Quality CSV summaries")
    parser.add_argument("--no-attach-excel", action="store_true", help="Skip attaching the multi-tab CCMS Panel Excel workbook")
    parser.add_argument("--to", help="Override recipient email address(es), comma-separated")
    parser.add_argument("--cc", help="Override CC email address(es), comma-separated")
    parser.add_argument(
        "--daily-at",
        help="Optional 24-hour time (HH:MM, e.g. 19:30) to run continuously and send daily",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Path to save rendered HTML mail dashboard (defaults to output/latest_panel_mail_dashboard.html, or output/sample_panel_mail_dashboard.html with --sample)",
    )
    args = parser.parse_args()

    if args.daily_at:
        print(f"Scheduled CCMS Panel Mail Dashboard daily at {args.daily_at}. Press Ctrl+C to stop.")
        schedule.every().day.at(args.daily_at).do(run_once, args)
        while True:
            schedule.run_pending()
            time.sleep(30)

    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
