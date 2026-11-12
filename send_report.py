from __future__ import annotations

import argparse
import time
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

import schedule

from src.analytics import (
    analyze_led_sheets,
    build_parsed_sheets_from_raw,
    parse_date_sort_key,
    parse_led_matrix_grid,
    parse_raw_lamp_sheet,
)
from src.config import BASE_DIR, load_config
from src.email_renderer import render_email_html, render_email_plain_text
from src.mailer import format_subject, send_dashboard_email
from src.sheets_client import (
    auto_pick_raw_tab,
    auto_pick_tabs,
    extract_spreadsheet_id,
    fetch_raw_grid,
    filter_daily_tabs_upto,
    find_all_daily_tabs,
    get_sample_grids,
)


def run_once(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.sheet:
        cfg.google_sheet.spreadsheet_id_or_url = args.sheet
    if args.to:
        cfg.email.recipients = [x.strip() for x in args.to.split(",") if x.strip()]
    if args.overall_tab:
        cfg.google_sheet.overall_worksheet = args.overall_tab
    if args.daily_tab is not None:
        cfg.google_sheet.daily_worksheet = "" if args.daily_tab.lower() == "none" else args.daily_tab
    if args.raw_tab is not None:
        cfg.google_sheet.raw_worksheet = "" if args.raw_tab.lower() == "none" else args.raw_tab

    daily_parsed = None
    historical_daily_sheets = []
    raw_lamp_data = None
    raw_tab_name = ""

    if args.sample:
        sample = get_sample_grids()
        ov_tab = "Overall till - 11.11.2026"
        dy_tab = "11.11.26- Lamp Installed"
        sheet_title = "Sample LED Installation Snapshot"
        overall_parsed = parse_led_matrix_grid(sample[ov_tab], ov_tab)
        if args.daily_tab is None or args.daily_tab.lower() != "none":
            daily_parsed = parse_led_matrix_grid(sample[dy_tab], dy_tab)
        if args.raw_tab is None or args.raw_tab.lower() != "none":
            raw_tab_name = "Sheet2"
            raw_lamp_data = parse_raw_lamp_sheet(sample["Sheet2"], raw_tab_name)
    else:
        sa_path = cfg.google_sheet.resolved_service_account_path()
        ov_grid, sheet_title, resolved_ov_tab, all_tabs = fetch_raw_grid(
            sa_path,
            cfg.google_sheet.spreadsheet_id_or_url,
            cfg.google_sheet.overall_worksheet,
        )

        # Support case where overall_worksheet points directly to Sheet2 (raw log)
        try:
            overall_parsed = parse_led_matrix_grid(ov_grid, resolved_ov_tab)
        except ValueError:
            raw_lamp_data = parse_raw_lamp_sheet(ov_grid, resolved_ov_tab)
            if raw_lamp_data is None:
                raise
            raw_tab_name = resolved_ov_tab
            overall_parsed, daily_parsed = build_parsed_sheets_from_raw(raw_lamp_data)

        dy_tab_name = cfg.google_sheet.daily_worksheet
        if args.daily_tab is None and not dy_tab_name:
            _, auto_dy = auto_pick_tabs(all_tabs)
            if auto_dy and auto_dy != resolved_ov_tab:
                dy_tab_name = auto_dy

        if dy_tab_name and dy_tab_name != resolved_ov_tab and overall_parsed.source_table_type != "raw_log":
            dy_grid, _, resolved_dy_tab, _ = fetch_raw_grid(
                sa_path,
                cfg.google_sheet.spreadsheet_id_or_url,
                dy_tab_name,
            )
            daily_parsed = parse_led_matrix_grid(dy_grid, resolved_dy_tab)

        cutoff_dt = date.today() - timedelta(days=1)
        if daily_parsed:
            parsed_d = parse_date_sort_key(daily_parsed.report_date)
            if parsed_d != datetime.min:
                cutoff_dt = parsed_d.date()

        hist_tab_names = filter_daily_tabs_upto(
            find_all_daily_tabs(all_tabs, resolved_ov_tab),
            cutoff_date=cutoff_dt,
        )[-14:]
        if len(hist_tab_names) > 1 and overall_parsed.source_table_type != "raw_log":
            for ht in hist_tab_names:
                if daily_parsed and ht == daily_parsed.tab_name:
                    historical_daily_sheets.append(daily_parsed)
                else:
                    try:
                        h_grid, _, h_resolved, _ = fetch_raw_grid(
                            sa_path,
                            cfg.google_sheet.spreadsheet_id_or_url,
                            ht,
                        )
                        historical_daily_sheets.append(parse_led_matrix_grid(h_grid, h_resolved))
                    except Exception:
                        pass

        # Fetch raw Sheet2 tab for Installed By + monthly/14d + pole/connection analytics
        if raw_lamp_data is None and (args.raw_tab is None or args.raw_tab.lower() != "none"):
            candidate_raw = cfg.google_sheet.raw_worksheet or auto_pick_raw_tab(
                all_tabs,
                resolved_ov_tab,
                daily_parsed.tab_name if daily_parsed else dy_tab_name,
            )
            if candidate_raw and candidate_raw not in {resolved_ov_tab, daily_parsed.tab_name if daily_parsed else ""}:
                try:
                    raw_grid, _, resolved_raw_tab, _ = fetch_raw_grid(
                        sa_path,
                        cfg.google_sheet.spreadsheet_id_or_url,
                        candidate_raw,
                    )
                    parsed_raw = parse_raw_lamp_sheet(raw_grid, resolved_raw_tab)
                    if parsed_raw is not None:
                        raw_lamp_data = parsed_raw
                        raw_tab_name = resolved_raw_tab
                except Exception as exc:
                    print(f"Warning: Could not parse raw tab '{candidate_raw}': {exc}")

    analysis = analyze_led_sheets(
        overall_parsed,
        daily_parsed,
        historical_daily_sheets=historical_daily_sheets,
        raw_lamp_data=raw_lamp_data,
        top_wards_limit=cfg.report.top_wards_limit,
    )
    html_body = render_email_html(
        analysis,
        cfg.report,
        sheet_title=sheet_title,
        overall_tab=overall_parsed.tab_name,
        daily_tab=daily_parsed.tab_name if daily_parsed else "",
        raw_tab=raw_tab_name,
        custom_note=args.note,
        include_top_wards=not args.no_top_wards,
    )
    plain_body = render_email_plain_text(
        analysis,
        cfg.report,
        sheet_title=sheet_title,
        overall_tab=overall_parsed.tab_name,
        daily_tab=daily_parsed.tab_name if daily_parsed else "",
        raw_tab=raw_tab_name,
    )
    subject = format_subject(cfg.email.subject_template, analysis, sheet_title=sheet_title)

    if args.out:
        out_path = Path(args.out)
    elif args.sample:
        out_path = BASE_DIR / "output" / "sample_mail_dashboard.html"
    else:
        out_path = BASE_DIR / "output" / "latest_mail_dashboard.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_body, encoding="utf-8")

    k = analysis.kpis
    print(f"Saved HTML mail dashboard preview to: {out_path}")
    print(f"Subject: {subject}")
    print(
        f"Overall: {k.overall_total:,} lamps across "
        f"{k.corporations_count} Corporations, {k.constituencies_count} Constituencies, {k.wards_count} Wards "
        f"| Reconciled: {k.overall_reconciled}"
    )
    if k.has_daily:
        print(f"Yesterday ({k.daily_date}): +{k.daily_total:,} lamps across {k.daily_wards_count} Wards")
    if k.has_installers:
        print(f"Installers (Installed By): {k.active_installers_today} active yesterday / {k.total_installers} overall")

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())

    if args.dry_run:
        print("Dry-run mode enabled; email was not sent.")
        return 0

    attachments = []
    if args.attach_csv:
        if analysis.installer_analysis and not analysis.installer_analysis.top_installers_cumulative.empty:
            attachments.append(("installer_summary.csv", analysis.installer_analysis.top_installers_cumulative))
        attachments.extend([
            ("corporation_summary.csv", analysis.corporation_summary),
            ("constituency_summary.csv", analysis.constituency_summary),
            ("ward_summary.csv", analysis.ward_summary),
        ])

    thread_key = (
        "sample"
        if args.sample
        else extract_spreadsheet_id(cfg.google_sheet.spreadsheet_id_or_url)
    )
    send_dashboard_email(
        cfg.email,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        attachments=attachments or None,
        thread_key=thread_key,
    )
    print(f"Email successfully sent to: {', '.join(cfg.email.recipients)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LED Lamp Installation Mail Dashboard: fetch Google Sheet tabs, build HTML dashboard, and send via SMTP."
    )
    parser.add_argument("--sheet", help="Override Google Sheet URL or ID")
    parser.add_argument("--overall-tab", help="Override Overall cumulative worksheet tab name")
    parser.add_argument("--daily-tab", help="Override Daily installed worksheet tab name (pass 'none' to skip)")
    parser.add_argument("--raw-tab", help="Override Sheet2 raw log tab name for Installed By analytics (pass 'none' to skip)")
    parser.add_argument("--note", default="", help="Optional coordinator note to include at the top of the mail")
    parser.add_argument("--sample", action="store_true", help="Use built-in sample LED snapshot instead of Google Sheets")
    parser.add_argument("--dry-run", action="store_true", help="Generate HTML dashboard locally without sending email")
    parser.add_argument("--open", action="store_true", help="Open generated HTML mail dashboard in your browser")
    parser.add_argument("--attach-csv", action="store_true", help="Attach Installer, Corporation, Constituency & Ward CSV summaries")
    parser.add_argument("--no-top-wards", action="store_true", help="Exclude Top Wards card")
    parser.add_argument("--to", help="Override recipient email address(es), comma-separated")
    parser.add_argument(
        "--daily-at",
        help="Optional 24-hour time (HH:MM, e.g. 19:00) to run continuously and send daily",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Path to save rendered HTML mail dashboard (defaults to output/latest_mail_dashboard.html, or output/sample_mail_dashboard.html with --sample)",
    )
    args = parser.parse_args()

    if args.daily_at:
        print(f"Scheduled Mail Dashboard daily at {args.daily_at}. Press Ctrl+C to stop.")
        schedule.every().day.at(args.daily_at).do(run_once, args)
        while True:
            schedule.run_pending()
            time.sleep(30)

    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
