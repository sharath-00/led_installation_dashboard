from __future__ import annotations

import unittest
from datetime import date

from src.analytics import (
    ParsedSheet,
    analyze_led_sheets,
    build_parsed_sheets_from_raw,
    parse_led_matrix_grid,
    parse_raw_lamp_sheet,
)
from src.config import BASE_DIR, EmailConfig, ReportConfig
from src.email_renderer import render_email_html, render_email_plain_text
from src.mailer import format_subject
from src.sheets_client import (
    auto_pick_raw_tab,
    auto_pick_tabs,
    extract_spreadsheet_id,
    filter_daily_tabs_upto,
    find_all_daily_tabs,
    get_sample_grids,
    get_service_account_email,
    xlsx_bytes_to_grid,
)


class TestLedMatrixMailDashboard(unittest.TestCase):
    def test_service_account_email_loaded(self) -> None:
        sa_path = BASE_DIR / "service_account.json"
        if not sa_path.exists():
            self.skipTest("service_account.json not present")
        email = get_service_account_email(sa_path)
        self.assertIsNotNone(email)
        assert email is not None
        self.assertIn("@", email)

    def test_auto_pick_tabs_and_sheet_id(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/1AbCDefGhIjKlMnOpQrStUvWxYz1234567890/edit#gid=0"
        self.assertEqual(extract_spreadsheet_id(url), "1AbCDefGhIjKlMnOpQrStUvWxYz1234567890")
        tabs = ["Overall till - 11.11.2026", "Overall till - 12.11.2026", "10.11.26- Lamp Installed", "11.11.26- Lamp Installed", "12.11.26- Lamp Installed", "Sheet2"]
        ov, dy = auto_pick_tabs(tabs, reference_today=date(2026, 11, 12))
        self.assertEqual(ov, "Overall till - 12.11.2026")
        self.assertEqual(dy, "11.11.26- Lamp Installed")
        self.assertEqual(
            filter_daily_tabs_upto(find_all_daily_tabs(tabs, ov), cutoff_date=date(2026, 11, 11)),
            ["10.11.26- Lamp Installed", "11.11.26- Lamp Installed"],
        )
        self.assertEqual(auto_pick_raw_tab(tabs, ov, dy), "Sheet2")
        self.assertEqual(
            auto_pick_raw_tab(
                ["Overall till - 11.11.2026", "11.11.26- Lamp Installed", "Lamp Report 11.11.2026"],
                "Overall till - 11.11.2026",
                "11.11.26- Lamp Installed",
            ),
            "Lamp Report 11.11.2026",
        )

    def test_exact_daily_screenshot_parsing_and_no_double_counting(self) -> None:
        grids = get_sample_grids()
        daily = parse_led_matrix_grid(grids["11.11.26- Lamp Installed"], "11.11.26- Lamp Installed")
        self.assertEqual(daily.report_date, "11/11/2026")
        self.assertEqual(daily.wattages, [34, 56, 104])
        self.assertEqual(daily.sheet_grand_total, 21)
        self.assertEqual(daily.parsed_total, 21)
        self.assertTrue(daily.reconciled_ok)
        self.assertEqual(len(daily.ward_df), 13)
        self.assertEqual(set(daily.ward_df["Corporation"]), {"South", "North", "Central"})

        corp_totals = daily.ward_df.groupby("Corporation")["Total Lamps"].sum().to_dict()
        self.assertEqual(corp_totals, {"South": 9, "North": 9, "Central": 3})

    def test_overall_and_daily_combined_analysis_and_reference_email(self) -> None:
        grids = get_sample_grids()
        overall = parse_led_matrix_grid(grids["Overall till - 11.11.2026"], "Overall till - 11.11.2026")
        daily = parse_led_matrix_grid(grids["11.11.26- Lamp Installed"], "11.11.26- Lamp Installed")

        self.assertTrue(overall.reconciled_ok)
        self.assertEqual(overall.parsed_total, 54493)
        self.assertEqual(overall.wattages, [34, 56, 78, 104, 173])

        analysis = analyze_led_sheets(overall, daily, top_wards_limit=10)
        k = analysis.kpis
        self.assertEqual(k.overall_total, 54493)
        self.assertEqual(k.daily_total, 21)
        self.assertEqual(k.daily_date, "11/11/2026")
        self.assertEqual(k.corporations_count, 3)
        self.assertEqual(k.constituencies_count, 4)
        self.assertEqual(k.wards_count, 34)
        self.assertEqual(k.top_wattage, "34 W")
        self.assertGreater(analysis.ward_stats.median_lamps, 0)

        cfg = ReportConfig()
        html = render_email_html(
            analysis,
            cfg,
            sheet_title="BBMP LED Sheet",
            overall_tab=overall.tab_name,
            daily_tab=daily.tab_name,
        )
        plain = render_email_plain_text(
            analysis,
            cfg,
            sheet_title="BBMP LED Sheet",
            overall_tab=overall.tab_name,
            daily_tab=daily.tab_name,
        )
        subject = format_subject(
            "[LED] {overall_total} Lamps | +{daily_total} on {daily_date}",
            analysis,
        )

        self.assertIn("54,493", html)
        self.assertIn("Yesterday by Constituency", html)
        self.assertIn("Cumulative by Constituency", html)
        self.assertIn("Lamp Wattage Mix (Cumulative)", html)
        self.assertIn("Top 8 Wards (Cumulative)", html)
        self.assertIn("Yesterday&#x27;s Installations by Ward", html)
        self.assertIn("Corporation Summary Matrix", html)
        self.assertIn("BMH-W202", html)
        self.assertNotIn("today", html.lower())
        self.assertNotIn("today", plain.lower())
        for removed in (
            "Pole, Connection",
            "Constituencies &middot; Wards",
            "Key Analytical Highlights",
            "Constituency Summary Matrix",
            "Daily Ward-level Detail",
        ):
            self.assertNotIn(removed, html)
        self.assertNotIn("Connected load", html)
        self.assertNotIn("Connected Load", html)
        self.assertNotIn(" kW", html)
        self.assertNotIn(" kW", plain)
        self.assertIn("CORPORATION SUMMARY", plain)
        self.assertNotIn("KEY HIGHLIGHTS", plain)
        self.assertIn("54,493", subject)
        self.assertIn("+21", subject)

        html_no_wards = render_email_html(
            analysis,
            cfg,
            sheet_title="BBMP LED Sheet",
            overall_tab=overall.tab_name,
            daily_tab=daily.tab_name,
            include_top_wards=False,
        )
        self.assertIn("Yesterday by Corporation", html_no_wards)
        self.assertNotIn("today", html_no_wards.lower())

    def test_multi_day_history_trend_unlocks_14_day_card(self) -> None:
        grids = get_sample_grids()
        overall = parse_led_matrix_grid(grids["Overall till - 11.11.2026"], "Overall till - 11.11.2026")
        daily_11 = parse_led_matrix_grid(grids["11.11.26- Lamp Installed"], "11.11.26- Lamp Installed")
        daily_10 = ParsedSheet(
            tab_name="10.11.26- Lamp Installed",
            report_date="10/11/2026",
            wattages=[34, 56],
            ward_df=daily_11.ward_df.head(5).copy(),
            sheet_grand_total=int(daily_11.ward_df.head(5)["Total Lamps"].sum()),
            parsed_total=int(daily_11.ward_df.head(5)["Total Lamps"].sum()),
            reconciled_ok=True,
            source_table_type="corporation_constituency",
        )
        analysis = analyze_led_sheets(
            overall,
            daily_11,
            historical_daily_sheets=[daily_10, daily_11],
        )
        self.assertTrue(analysis.kpis.has_history)
        self.assertEqual(len(analysis.daily_history), 2)
        html = render_email_html(
            analysis,
            ReportConfig(),
            sheet_title="BBMP LED Sheet",
            overall_tab=overall.tab_name,
            daily_tab=daily_11.tab_name,
        )
        self.assertIn("Last 7 days", html)
        self.assertIn("Daily Installations", html)

    def test_sheet2_installed_by_and_infrastructure_analytics(self) -> None:
        grids = get_sample_grids()
        overall = parse_led_matrix_grid(grids["Overall till - 11.11.2026"], "Overall till - 11.11.2026")
        daily = parse_led_matrix_grid(grids["11.11.26- Lamp Installed"], "11.11.26- Lamp Installed")
        raw_data = parse_raw_lamp_sheet(grids["Sheet2"], "Sheet2")

        self.assertIsNotNone(raw_data)
        assert raw_data is not None
        self.assertTrue(raw_data.has_installed_by)
        self.assertTrue(raw_data.has_dates)
        self.assertEqual(raw_data.total_rows, 32)

        analysis = analyze_led_sheets(overall, daily, raw_lamp_data=raw_data)
        self.assertTrue(analysis.kpis.has_installers)
        self.assertEqual(analysis.kpis.total_installers, 8)
        self.assertEqual(analysis.kpis.active_installers_today, 8)
        self.assertTrue(analysis.kpis.has_history)

        inst = analysis.installer_analysis
        self.assertIsNotNone(inst)
        assert inst is not None
        self.assertEqual(int(inst.top_installers_cumulative["Total Lamps"].sum()), 32)
        self.assertEqual(int(inst.today_by_installer["Yesterday"].sum()), 21)
        self.assertFalse(inst.monthly_history.empty)
        self.assertFalse(inst.pole_type_summary.empty)
        self.assertFalse(inst.connection_type_summary.empty)
        self.assertFalse(inst.lamp_type_summary.empty)
        self.assertEqual(inst.photo_missing_count, 2)
        self.assertGreater(inst.replaced_count, 0)

        html = render_email_html(
            analysis,
            ReportConfig(),
            sheet_title="BBMP LED Sheet",
            overall_tab=overall.tab_name,
            daily_tab=daily.tab_name,
            raw_tab="Sheet2",
        )
        plain = render_email_plain_text(
            analysis,
            ReportConfig(),
            sheet_title="BBMP LED Sheet",
            overall_tab=overall.tab_name,
            daily_tab=daily.tab_name,
            raw_tab="Sheet2",
        )

        for expected in (
            "Installed date (Yesterday): 11/11/2026",
            "Yesterday: 11/11/2026",
            "Installed yesterday",
            "Active installers yesterday",
            "Top Installers (Cumulative)",
            "Yesterday by Installer",
            "Yesterday&#x27;s Installations by Ward",
            "Monthly Installations",
            "Cumulative by Corporation &amp; Zone",
            "Top 8 Wards (Cumulative)",
            "Corporation Summary Matrix",
            "shridurga ent.",
            "nithyaelectrical",
        ):
            self.assertIn(expected, html)

        default_subj = format_subject(EmailConfig().subject_template, analysis)
        self.assertEqual(
            default_subj,
            "[LED Installation Report] 54,493 Lamps Installed | Yesterday +21 (11/11/2026)",
        )

        self.assertNotIn("Installed By Performance Summary", html)
        self.assertNotIn("today", html.lower())
        self.assertNotIn("today", plain.lower())

        for removed in (
            "Pole, Connection",
            "Constituencies &middot; Wards",
            "Key Analytical Highlights",
            "Constituency Summary Matrix",
            "Daily Ward-level Detail",
        ):
            self.assertNotIn(removed, html)

        self.assertIn("TOP INSTALLERS (INSTALLED BY)", plain)
        self.assertNotIn("KEY HIGHLIGHTS", plain)
        self.assertNotIn("Ward Spread", plain)
        self.assertNotIn("&amp;ndash;", html)
        self.assertNotIn("&amp;bull;", html)
        self.assertNotIn(" kW", html)
        self.assertNotIn("Connected load", html)
        self.assertNotIn("Connected Load", html)
        self.assertNotIn(" kW", plain)
        # Verify distinct Yesterday (Amber) vs Cumulative (Blue) color tokens & visual polish
        self.assertIn("#d97706", html)
        self.assertIn("#fef3c7", html)
        self.assertIn("#2563eb", html)
        self.assertIn("#dbeafe", html)
        self.assertIn("All Corporations Total", html)
        self.assertIn("table-layout:fixed", html)

    def test_sheet2_truncated_headers_and_standalone_fallback(self) -> None:
        grids = get_sample_grids()
        truncated_grid = [list(r) for r in grids["Sheet2"]]
        # Replace exact headers with visually truncated ones like "Installe..." / "Installed I..."
        truncated_grid[0][16] = "Installe..."
        truncated_grid[0][17] = "Installed I..."

        raw_data = parse_raw_lamp_sheet(truncated_grid, "Sheet2")
        self.assertIsNotNone(raw_data)
        assert raw_data is not None
        self.assertTrue(raw_data.has_installed_by)
        self.assertTrue(raw_data.has_dates)

        ov_ps, dy_ps = build_parsed_sheets_from_raw(raw_data, reference_today=date(2026, 11, 12))
        self.assertEqual(ov_ps.source_table_type, "raw_log")
        self.assertEqual(ov_ps.parsed_total, 32)
        self.assertIsNotNone(dy_ps)
        assert dy_ps is not None
        self.assertEqual(dy_ps.report_date, "11/11/2026")
        self.assertEqual(dy_ps.parsed_total, 21)

        # Even if Sheet2 has partial entries logged for today (12-11-2026), report sent today targets yesterday (11-11-2026)
        with_today_grid = [list(r) for r in grids["Sheet2"]]
        today_extra = list(grids["Sheet2"][1])
        today_extra[17] = "12-11-2026"
        with_today_grid.append(today_extra)
        raw_with_today = parse_raw_lamp_sheet(with_today_grid, "Sheet2")
        assert raw_with_today is not None
        _, dy_only_yesterday = build_parsed_sheets_from_raw(raw_with_today, reference_today=date(2026, 11, 12))
        assert dy_only_yesterday is not None
        self.assertEqual(dy_only_yesterday.report_date, "11/11/2026")
        self.assertEqual(dy_only_yesterday.parsed_total, 21)

    def test_xlsx_float_and_datetime_serialization(self) -> None:
        import io
        from datetime import datetime
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "11.11.26- Lamp Installed"
        ws.append(["", "", "Installed On", datetime(2026, 11, 11)])
        ws.append(["", "", "Corporation", "Constituency", 34.0, 56.0, "Grand Total"])
        ws.append(["", "", "South", "Bommanahali - Z1", 7.0, 1.0, 8.0])
        ws.append(["", "", "", "BMH-W202", 7.0, 1.0, 8.0])
        ws.append(["", "", "", "Grand Total", 7.0, 1.0, 8.0])

        ws2 = wb.create_sheet("Sheet2")
        ws2.append(["Region", "Zone", "Ward", "Pole Type", "Connection Type", "Type", "Wattage", "Installed By", "Installed On"])
        ws2.append(["South", "Bommanahali - Z1", "BMH-W202", "RCC", "ABC", "SL LED", 56.0, "installer1", datetime(2026, 11, 11)])

        buf = io.BytesIO()
        wb.save(buf)
        raw_grid_dy, resolved, tabs = xlsx_bytes_to_grid(buf.getvalue(), "11.11.26- Lamp Installed")
        self.assertEqual(resolved, "11.11.26- Lamp Installed")
        self.assertEqual(tabs, ["11.11.26- Lamp Installed", "Sheet2"])

        parsed_dy = parse_led_matrix_grid(raw_grid_dy, resolved)
        self.assertEqual(parsed_dy.report_date, "11/11/2026")
        self.assertEqual(parsed_dy.wattages, [34, 56])
        self.assertEqual(parsed_dy.parsed_total, 8)
        self.assertTrue(parsed_dy.reconciled_ok)

        raw_grid_s2, _, _ = xlsx_bytes_to_grid(buf.getvalue(), "Sheet2")
        raw_s2 = parse_raw_lamp_sheet(raw_grid_s2, "Sheet2")
        self.assertIsNotNone(raw_s2)
        assert raw_s2 is not None
        self.assertEqual(int(raw_s2.df["wattage"].iloc[0]), 56)
        self.assertEqual(raw_s2.df["install_dt"].iloc[0].strftime("%d/%m/%Y"), "11/11/2026")


if __name__ == "__main__":
    unittest.main()
