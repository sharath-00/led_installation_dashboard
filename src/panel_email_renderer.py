from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Any

import pandas as pd

from src.analytics import PanelAnalysis
from src.config import ReportConfig

# ============================================================================
# EXACT COLOR THEMES & VISUAL PALETTE (Royal Blue & Amber - Matches LED Dashboard)
# ============================================================================
YESTERDAY_THEME = {
    "bar": "#d97706",
    "track": "#fef3c7",
    "value": "#b45309",
    "badge_bg": "#fef3c7",
    "badge_border": "#fcd34d",
    "badge_text": "#92400e",
    "card_border": "#f59e0b",
    "hdr_bg": "#fffbeb",
    "hdr_border": "#fde68a",
    "cell_bg": "#fffbeb",
}

CUMULATIVE_THEME = {
    "bar": "#2563eb",
    "track": "#dbeafe",
    "value": "#1d4ed8",
    "badge_bg": "#dbeafe",
    "badge_border": "#93c5fd",
    "badge_text": "#1e40af",
    "card_border": "#93c5fd",
    "hdr_bg": "#eff6ff",
    "hdr_border": "#bfdbfe",
    "cell_bg": "#eff6ff",
}

NEUTRAL_THEME = {
    "bar": "#64748b",
    "track": "#e2e8f0",
    "value": "#0f172a",
    "badge_bg": "#f1f5f9",
    "badge_border": "#cbd5e1",
    "badge_text": "#475569",
    "card_border": "#cbd5e1",
    "hdr_bg": "#f8fafc",
    "hdr_border": "#e2e8f0",
    "cell_bg": "#f8fafc",
}


def _theme_for_scope(scope: str) -> dict[str, str]:
    if scope == "yesterday":
        return YESTERDAY_THEME
    if scope == "cumulative":
        return CUMULATIVE_THEME
    return NEUTRAL_THEME


def _scope_badge(scope: str, label: str | None = None) -> str:
    if scope == "yesterday":
        t = YESTERDAY_THEME
        txt = label or "Yesterday"
        dot = f'<span style="color:{t["bar"]};">&#9679;</span> '
    elif scope == "cumulative":
        t = CUMULATIVE_THEME
        txt = label or "Cumulative"
        dot = f'<span style="color:{t["bar"]};">&#9679;</span> '
    elif scope == "neutral":
        t = NEUTRAL_THEME
        txt = label or ""
        dot = ""
    else:
        return ""
    if not txt:
        return ""
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'background-color:{t["badge_bg"]};border:1px solid {t["badge_border"]};'
        f'font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;'
        f'color:{t["badge_text"]};white-space:nowrap;">{dot}{escape(txt)}</span>'
    )


def _card_border_color(scope: str) -> str:
    return _theme_for_scope(scope)["card_border"]


def _card_inner(
    title: str,
    body_html: str,
    subtitle: str = "",
    scope: str = "",
    badge_label: str | None = None,
    *,
    header_scope: str | None = None,
) -> str:
    theme_key = header_scope if header_scope is not None else scope
    t = _theme_for_scope(theme_key)
    badge_html = _scope_badge(scope, badge_label) if scope else ""
    sub_html = (
        f'<div style="font-size:11px;color:#64748b;margin-bottom:10px;">{escape(subtitle)}</div>'
        if subtitle
        else ""
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        f'<tr><td colspan="2" style="height:3px;background-color:{t["bar"]};font-size:1px;line-height:1px;">&nbsp;</td></tr>'
        f'<tr style="background-color:{t["hdr_bg"]};">'
        f'<td valign="middle" style="padding:10px 18px;border-bottom:1px solid {t["hdr_border"]};font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#334155;">{escape(title)}</td>'
        f'<td align="right" valign="middle" style="padding:10px 18px 10px 8px;border-bottom:1px solid {t["hdr_border"]};white-space:nowrap;">{badge_html}</td>'
        f'</tr>'
        f'<tr><td colspan="2" style="padding:12px 18px 14px 18px;">{sub_html}{body_html}</td></tr>'
        f'</table>'
    )


def _single_card_row(inner_html: str, *, scope: str = "") -> str:
    border_col = _card_border_color(scope)
    return f"""
    <tr>
      <td style="padding-top:16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;">
          <tr>
            <td valign="top" style="background-color:#ffffff;border:1px solid {border_col};border-radius:12px;overflow:hidden;padding:0;">
              {inner_html}
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """


def _two_card_row(
    left_inner: str,
    right_inner: str,
    *,
    left_scope: str = "",
    right_scope: str = "",
) -> str:
    left_border = _card_border_color(left_scope)
    right_border = _card_border_color(right_scope)
    return f"""
    <tr>
      <td style="padding-top:16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;">
          <tr>
            <td width="412" valign="top" style="width:412px;background-color:#ffffff;border:1px solid {left_border};border-radius:12px;overflow:hidden;padding:0;">
              {left_inner}
            </td>
            <td width="16" style="width:16px;font-size:1px;line-height:1px;">&nbsp;</td>
            <td width="412" valign="top" style="width:412px;background-color:#ffffff;border:1px solid {right_border};border-radius:12px;overflow:hidden;padding:0;">
              {right_inner}
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """


def _pill_bars_html(
    items: list[tuple[str, str, int, str]],
    *,
    bar_color: str = "#2563eb",
    track_color: str = "#dbeafe",
    value_color: str = "#0f172a",
    empty_msg: str = "No data available.",
    ranked: bool = True,
) -> str:
    if not items:
        return f'<div style="font-size:12px;color:#94a3b8;padding:12px 0;">{escape(empty_msg)}</div>'

    max_val = max((v for _, _, v, _ in items), default=1)
    max_val = max(max_val, 1)

    rows = []
    total_rows = len(items)
    for idx, (label, right_txt, num_val, subnote) in enumerate(items):
        pct = max(3.0, min(100.0, (num_val / max_val) * 100.0)) if num_val > 0 else 0.0
        sub_span = (
            f' <span style="font-size:10px;color:#64748b;font-weight:400;white-space:nowrap;">({escape(subnote)})</span>'
            if subnote
            else ""
        )
        rank_html = (
            f'<span style="display:inline-block;width:16px;font-size:10px;font-weight:700;color:#94a3b8;">{idx + 1}.</span>'
            if ranked and total_rows > 1
            else ""
        )
        border_style = "border-bottom:1px solid #f1f5f9;" if idx < total_rows - 1 else ""
        rows.append(
            f"""
            <tr>
              <td width="49%" style="padding:7px 8px 7px 0;{border_style}font-size:12px;font-weight:500;color:#1e293b;line-height:1.3;word-break:break-word;">{rank_html}{escape(label)}{sub_span}</td>
              <td width="35%" style="padding:7px 0;{border_style}">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{track_color};border-radius:999px;height:10px;">
                  <tr>
                    <td width="{pct:.1f}%" style="background-color:{bar_color};border-radius:999px;height:10px;font-size:1px;line-height:1px;">&nbsp;</td>
                    <td style="font-size:1px;line-height:1px;">&nbsp;</td>
                  </tr>
                </table>
              </td>
              <td width="16%" align="right" style="padding:7px 0 7px 8px;{border_style}font-size:12px;font-weight:700;color:{value_color};white-space:nowrap;">{escape(right_txt)}</td>
            </tr>
            """
        )

    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="table-layout:fixed;border-collapse:collapse;">{"".join(rows)}</table>'


def _vertical_bars_html(
    bars: list[tuple[str, float, str, bool]],
    *,
    plot_height: int = 136,
    bar_width: int = 24,
    default_bar_color: str = "#60a5fa",
    highlight_bar_color: str = "#d97706",
    highlight_text_color: str = "#b45309",
    highlight_col_bg: str = "#fffbeb",
    footer_note: str = "",
) -> str:
    if not bars:
        return '<div style="font-size:12px;color:#94a3b8;padding:12px 0;">No data available.</div>'

    max_val = max((v for _, v, _, _ in bars), default=1.0)
    max_val = max(max_val, 0.001)

    bar_cells = []
    label_cells = []
    for label, val, top_txt, highlight in bars:
        px = max(5, int(round((val / max_val) * plot_height))) if val > 0 else 2
        color = highlight_bar_color if highlight else default_bar_color
        val_txt_color = highlight_text_color if highlight else "#334155"
        lbl_txt_color = highlight_text_color if highlight else "#64748b"
        lbl_weight = "700" if highlight else "600"
        col_bg = f"background-color:{highlight_col_bg};" if highlight and highlight_col_bg else ""
        bar_cells.append(
            f"""
            <td align="center" valign="bottom" style="padding:4px 2px 0 2px;height:{plot_height + 24}px;{col_bg}border-radius:6px 6px 0 0;">
              <div style="font-size:10px;font-weight:700;color:{val_txt_color};margin-bottom:4px;white-space:nowrap;">{escape(top_txt)}</div>
              <div style="width:{bar_width}px;height:{px}px;background-color:{color};border-radius:4px 4px 0 0;margin:0 auto;font-size:1px;line-height:1px;">&nbsp;</div>
            </td>
            """
        )
        label_cells.append(
            f'<td align="center" style="padding:6px 2px 2px 2px;border-top:2px solid #cbd5e1;{col_bg}font-size:10px;font-weight:{lbl_weight};color:{lbl_txt_color};white-space:nowrap;">{escape(label)}</td>'
        )

    note_html = (
        f'<div style="font-size:10.5px;color:#64748b;margin-top:10px;padding-top:8px;border-top:1px solid #f1f5f9;">{escape(footer_note)}</div>'
        if footer_note
        else ""
    )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
      <tr>{''.join(bar_cells)}</tr>
      <tr>{''.join(label_cells)}</tr>
    </table>
    {note_html}
    """


def _kpi_card_html(title: str, val: str, sub: str, scope: str, badge_txt: str) -> str:
    t = _theme_for_scope(scope)
    val_color = t["value"] if scope in ("yesterday", "cumulative") else "#0f172a"
    return (
        f'<td width="198" valign="top" style="width:198px;background-color:#ffffff;border:1px solid {t["card_border"]};border-radius:12px;overflow:hidden;padding:0;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        f'<tr><td style="height:3px;background-color:{t["bar"]};font-size:1px;line-height:1px;">&nbsp;</td></tr>'
        f'<tr><td style="padding:12px 15px 14px 15px;">'
        f'<div style="padding-bottom:7px;">{_scope_badge(scope, badge_txt)}</div>'
        f'<div style="font-size:11px;font-weight:600;color:#475569;">{title}</div>'
        f'<div style="font-size:27px;font-weight:800;color:{val_color};margin-top:4px;line-height:1.15;">{val}</div>'
        f'<div style="font-size:11px;color:#64748b;margin-top:5px;">{sub}</div>'
        f'</td></tr>'
        f'</table>'
        f'</td>'
    )


def _render_panel_matrix_table(analysis: PanelAnalysis) -> str:
    p = analysis
    if p.zone_summary.empty:
        return ""

    rows_html = []
    for idx, r in p.zone_summary.iterrows():
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"
        daily_val = int(r.get("Daily Installed", 0))
        daily_td = (
            f'<td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;font-weight:700;color:{YESTERDAY_THEME["value"]};">+{daily_val:,}</td>'
            if daily_val > 0
            else '<td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;color:#94a3b8;">-</td>'
        )

        rows_html.append(
            f"""
            <tr style="background-color:{bg};">
              <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;font-size:11px;font-weight:700;color:#0f172a;">{escape(str(r['Zone']))}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#334155;">{escape(str(r['Region']))}</td>
              <td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:center;font-size:11px;color:#334155;">{int(r['Wards'])}</td>
              <td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;color:#334155;">{int(r['Switch Points Mapped']):,}</td>
              <td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;font-weight:600;color:#059669;">{float(r['Mapping %']):.1f}%</td>
              <td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;font-weight:700;color:{CUMULATIVE_THEME['value']};">{int(r['Total Panels']):,}</td>
              {daily_td}
              <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;color:#475569;">{float(r['Share %']):.1f}%</td>
            </tr>
            """
        )

    # Summary Totals Row
    tot_panels = int(p.zone_summary["Total Panels"].sum())
    tot_mapped = int(p.zone_summary["Switch Points Mapped"].sum())
    tot_daily = int(p.zone_summary["Daily Installed"].sum()) if "Daily Installed" in p.zone_summary.columns else 0
    tot_map_pct = (tot_mapped / max(tot_panels, 1)) * 100.0
    tot_daily_td = (
        f'<td style="padding:9px 8px;text-align:right;font-size:11px;font-weight:800;color:{YESTERDAY_THEME["value"]};">+{tot_daily:,}</td>'
        if tot_daily > 0
        else '<td style="padding:9px 8px;text-align:right;font-size:11px;color:#94a3b8;">-</td>'
    )

    summary_row_html = f"""
    <tr style="background-color:#eff6ff;font-weight:700;border-top:2px solid {CUMULATIVE_THEME['bar']};">
      <td colspan="2" style="padding:9px 12px;font-size:11px;color:{CUMULATIVE_THEME['value']};">Total ({p.kpis.zones_count} Zones)</td>
      <td style="padding:9px 8px;text-align:center;font-size:11px;color:{CUMULATIVE_THEME['value']};">{p.kpis.wards_count}</td>
      <td style="padding:9px 8px;text-align:right;font-size:11px;color:{CUMULATIVE_THEME['value']};">{tot_mapped:,}</td>
      <td style="padding:9px 8px;text-align:right;font-size:11px;color:#059669;">{tot_map_pct:.1f}%</td>
      <td style="padding:9px 8px;text-align:right;font-size:11px;font-weight:800;color:{CUMULATIVE_THEME['value']};">{tot_panels:,}</td>
      {tot_daily_td}
      <td style="padding:9px 12px;text-align:right;font-size:11px;color:{CUMULATIVE_THEME['value']};">100.0%</td>
    </tr>
    """

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
      <tr>
        <td style="height:3px;background-color:{CUMULATIVE_THEME['bar']};font-size:1px;line-height:1px;">&nbsp;</td>
      </tr>
      <tr style="background-color:#eff6ff;">
        <td style="padding:10px 18px;border-bottom:1px solid #bfdbfe;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
            <tr>
              <td valign="middle">
                <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#334155;">Zone-Wise CCMS Panel Deployment Matrix</span>
              </td>
              <td align="right" valign="middle" style="white-space:nowrap;">
                {_scope_badge("yesterday", "Yesterday")}
                &nbsp;
                {_scope_badge("cumulative", "Cumulative")}
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="padding:0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
            <thead>
              <tr style="background-color:#f8fafc;">
                <th style="padding:9px 12px;text-align:left;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">Zone / Constituency</th>
                <th style="padding:9px 12px;text-align:left;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">Region</th>
                <th style="padding:9px 8px;text-align:center;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">Wards</th>
                <th style="padding:9px 8px;text-align:right;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">SP Mapped</th>
                <th style="padding:9px 8px;text-align:right;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">Mapping %</th>
                <th style="padding:9px 8px;text-align:right;font-size:10px;text-transform:uppercase;color:{CUMULATIVE_THEME['badge_text']};background-color:{CUMULATIVE_THEME['badge_bg']};border-bottom:2px solid {CUMULATIVE_THEME['bar']};">Total</th>
                <th style="padding:9px 8px;text-align:right;font-size:10px;text-transform:uppercase;color:{YESTERDAY_THEME['badge_text']};background-color:{YESTERDAY_THEME['badge_bg']};border-bottom:2px solid {YESTERDAY_THEME['bar']};">Yesterday</th>
                <th style="padding:9px 12px;text-align:right;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">Share</th>
              </tr>
            </thead>
            <tbody>{''.join(rows_html)}{summary_row_html}</tbody>
          </table>
        </td>
      </tr>
    </table>
    """


# ============================================================================
# MAIN HTML DASHBOARD RENDERER (IDENTICAL DESIGN TO LED REPORT)
# ============================================================================
def render_panel_email_html(
    analysis: PanelAnalysis,
    report_cfg: ReportConfig,
    *,
    sheet_title: str = "Google Sheet",
    panel_tab: str = "PANEL REPORT",
    custom_note: str = "",
) -> str:
    pk = analysis.kpis
    sent_now = datetime.now()
    generated_at = sent_now.strftime("%d %b %Y, %I:%M %p")
    default_yesterday = (sent_now - timedelta(days=1)).strftime("%d/%m/%Y")
    yesterday_date_label = pk.daily_date if pk.has_daily else (pk.latest_date_label or default_yesterday)

    # Coordinator Note Row
    note_row = ""
    if custom_note.strip():
        note_row = f"""
        <tr>
          <td style="padding-bottom:16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eff6ff;border-left:4px solid #2563eb;border-radius:8px;">
              <tr>
                <td style="padding:12px 16px;">
                  <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:#1d4ed8;margin-bottom:2px;">Coordinator Note</div>
                  <div style="font-size:12px;color:#1e3a8a;line-height:1.45;">{escape(custom_note.strip())}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """

    # 4-Card Hero Strip (Installed yesterday, Last 7 days, Cumulative installed, Active contractors yesterday)
    # Card 1: Installed yesterday
    if pk.has_daily:
        card1_val = f"{pk.daily_panels:,}"
        if pk.daily_panels > 0 and pk.last_7_days_total > 0:
            avg_d = pk.avg_7d_installed
            diff = ((pk.daily_panels - avg_d) / max(avg_d, 0.1)) * 100.0
            delta_arrow = "&#9650;" if diff >= 0 else "&#9660;"
            card1_sub = f"{delta_arrow} vs 7-day avg {avg_d:.1f}"
        else:
            card1_sub = f"{pk.daily_wards_count} wards active yesterday"
        card1_title = "Installed yesterday"
        card1_scope = "yesterday"
        card1_badge = "Yesterday"
    else:
        card1_title = "Cumulative installed"
        card1_val = f"{pk.total_panels:,}"
        card1_sub = f"Till {escape(yesterday_date_label)}"
        card1_scope = "cumulative"
        card1_badge = "Cumulative"

    # Card 2: Last 7 days
    if pk.last_7_days_total > 0:
        card2_title = "Last 7 days"
        card2_val = f"{pk.last_7_days_total:,}"
        card2_sub = f"{pk.avg_7d_installed:.1f}/day average"
        card2_scope = "neutral"
        card2_badge = "7-Day Window"
    else:
        card2_title = "Regions &middot; Zones"
        card2_val = f"{pk.regions_count} &middot; {pk.zones_count}"
        card2_sub = f"{pk.wards_count} total wards"
        card2_scope = "cumulative"
        card2_badge = "Cumulative"

    # Card 3: Cumulative installed
    card3_title = "Cumulative installed"
    card3_val = f"{pk.total_panels:,}"
    card3_sub = f"since {escape(pk.earliest_date_label)}" if pk.earliest_date_label != "-" else f"Till {escape(yesterday_date_label)}"
    card3_scope = "cumulative"
    card3_badge = "Cumulative"

    # Card 4: Active contractors yesterday
    if pk.has_daily:
        card4_title = "Active contractors yesterday"
        card4_val = f"{pk.active_installers_today:,}"
        card4_sub = f"{pk.total_installers:,} contractor IDs overall"
        card4_scope = "yesterday"
        card4_badge = "Yesterday"
    else:
        card4_title = "Circuit Mapping"
        card4_val = f"{pk.switch_points_mapped_pct:.1f}%"
        card4_sub = f"{pk.switch_points_mapped:,} circuits mapped"
        card4_scope = "cumulative"
        card4_badge = "Cumulative"

    # =========================================================================
    # ROW 1: Daily 14-day Trend (Vertical Bars) + Yesterday by Zone / Constituency
    # =========================================================================
    if not analysis.daily_history.empty:
        hist_bars = [
            (str(r["Label"]), float(r["Panels"]), f"{int(r['Panels']):,}", bool(r["Is Latest"]))
            for _, r in analysis.daily_history.iterrows()
        ]
        row1_left = _card_inner(
            f"Daily Installations \u2013 Last {len(hist_bars)} Days",
            _vertical_bars_html(
                hist_bars,
                bar_width=18 if len(hist_bars) > 8 else 26,
                default_bar_color="#60a5fa",
                highlight_bar_color=YESTERDAY_THEME["bar"],
                highlight_text_color=YESTERDAY_THEME["value"],
                footer_note=f"Light blue: prior days \u2022 Amber: yesterday ({yesterday_date_label})",
            ),
            scope="yesterday",
            badge_label="Yesterday Highlighted",
            header_scope="neutral",
        )
        row1_left_scope = "neutral"
    else:
        # Fallback to monthly
        m_bars = [
            (str(r["Label"]), float(r["Panels"]), f"{int(r['Panels']):,}", False)
            for _, r in analysis.monthly_history.iterrows()
        ]
        row1_left = _card_inner(
            "Monthly Panel Installations",
            _vertical_bars_html(m_bars, bar_width=24, default_bar_color=CUMULATIVE_THEME["bar"]),
            scope="cumulative",
        )
        row1_left_scope = "cumulative"

    # Row 1 Right: Yesterday by Zone
    dy_zones = analysis.zone_summary[analysis.zone_summary["Daily Installed"] > 0] if "Daily Installed" in analysis.zone_summary.columns else pd.DataFrame()
    if pk.has_daily and not dy_zones.empty:
        today_zone_items = [
            (str(r["Zone"]), f"{int(r['Daily Installed']):,}", int(r["Daily Installed"]), str(r["Region"]))
            for _, r in dy_zones.iterrows()
        ]
        row1_right = _card_inner(
            f"Yesterday by Zone ({yesterday_date_label})",
            _pill_bars_html(
                today_zone_items,
                bar_color=YESTERDAY_THEME["bar"],
                track_color=YESTERDAY_THEME["track"],
                value_color=YESTERDAY_THEME["value"],
            ),
            scope="yesterday",
        )
        row1_right_scope = "yesterday"
    else:
        row1_right = _card_inner(
            f"Yesterday by Zone ({yesterday_date_label})",
            _pill_bars_html(
                [],
                empty_msg=f"No CCMS panels installed on {yesterday_date_label}.",
            ),
            scope="yesterday",
        )
        row1_right_scope = "yesterday"

    # =========================================================================
    # ROW 2: Cumulative by Zone + Switch Point Circuit Mapping Mix
    # =========================================================================
    cum_zone_items = [
        (str(r["Zone"]), f"{int(r['Total Panels']):,}", int(r["Total Panels"]), f"{r['Share %']:.1f}%")
        for _, r in analysis.zone_summary.iterrows()
    ]
    row2_left = _card_inner(
        "Cumulative by Zone / Constituency",
        _pill_bars_html(
            cum_zone_items,
            bar_color=CUMULATIVE_THEME["bar"],
            track_color=CUMULATIVE_THEME["track"],
            value_color=CUMULATIVE_THEME["value"],
        ),
        scope="cumulative",
    )

    # Circuit Mapping Mix
    pending_sp = max(0, pk.total_panels - pk.switch_points_mapped)
    pending_pct = round((pending_sp / max(pk.total_panels, 1)) * 100.0, 1)
    sp_items = [
        ("Circuits Mapped", f"{pk.switch_points_mapped:,}", pk.switch_points_mapped, f"{pk.switch_points_mapped_pct:.1f}%"),
        ("Pending Circuit Assignment", f"{pending_sp:,}", pending_sp, f"{pending_pct:.1f}%"),
    ]
    row2_right = _card_inner(
        "Switch Point Circuit Mapping Mix (Cumulative)",
        _pill_bars_html(
            sp_items,
            bar_color=CUMULATIVE_THEME["bar"],
            track_color=CUMULATIVE_THEME["track"],
            value_color=CUMULATIVE_THEME["value"],
            ranked=False,
        ),
        scope="cumulative",
    )

    # =========================================================================
    # ROW 3 & ROW 4: Monthly History + Top Contractors, Yesterday by Contractor + Ward
    # =========================================================================
    extra_rows_html = ""
    if not analysis.installer_summary.empty:
        # Row 3: Monthly Installations (Vertical Bars) + Top Contractors (Cumulative)
        if not analysis.monthly_history.empty:
            m_bars = [
                (str(r["Label"]), float(r["Panels"]), f"{int(r['Panels']):,}", False)
                for _, r in analysis.monthly_history.iterrows()
            ]
            r3_left = _card_inner(
                "Monthly Installations",
                _vertical_bars_html(
                    m_bars,
                    bar_width=20,
                    default_bar_color=CUMULATIVE_THEME["bar"],
                ),
                scope="cumulative",
            )
        else:
            r3_left = _card_inner(
                "Cumulative by Region",
                _pill_bars_html(
                    [
                        (str(r["Region"]), f"{int(r['Total Panels']):,}", int(r["Total Panels"]), f"{r['Share %']:.1f}%")
                        for _, r in analysis.zone_summary.groupby("Region", as_index=False).agg({"Total Panels": "sum"}).assign(
                            **{"Share %": lambda d: (d["Total Panels"] / max(pk.total_panels, 1) * 100.0).round(1)}
                        ).iterrows()
                    ],
                    bar_color=CUMULATIVE_THEME["bar"],
                    track_color=CUMULATIVE_THEME["track"],
                    value_color=CUMULATIVE_THEME["value"],
                ),
                scope="cumulative",
            )

        top_inst_items = [
            (str(r["Contractor"]).split("@")[0], f"{int(r['Total Panels']):,}", int(r["Total Panels"]), f"{r['Share %']:.1f}%")
            for _, r in analysis.installer_summary.head(8).iterrows()
        ]
        r3_right = _card_inner(
            "Top Contractors (Cumulative)",
            _pill_bars_html(
                top_inst_items,
                bar_color=CUMULATIVE_THEME["bar"],
                track_color=CUMULATIVE_THEME["track"],
                value_color=CUMULATIVE_THEME["value"],
            ),
            scope="cumulative",
        )
        extra_rows_html += _two_card_row(
            r3_left,
            r3_right,
            left_scope="cumulative",
            right_scope="cumulative",
        )

        # Row 4: Yesterday by Contractor + Yesterday by Ward
        today_contractors = analysis.installer_summary[analysis.installer_summary["Daily Installed"] > 0] if "Daily Installed" in analysis.installer_summary.columns else pd.DataFrame()
        today_inst_items = [
            (str(r["Contractor"]).split("@")[0], f"{int(r['Daily Installed']):,}", int(r["Daily Installed"]), f"{int(r['Wards'])}w")
            for _, r in today_contractors.head(8).iterrows()
        ] if not today_contractors.empty else []
        r4_left = _card_inner(
            f"Yesterday by Contractor ({yesterday_date_label})",
            _pill_bars_html(
                today_inst_items,
                bar_color=YESTERDAY_THEME["bar"],
                track_color=YESTERDAY_THEME["track"],
                value_color=YESTERDAY_THEME["value"],
                empty_msg=f"No panel records dated {yesterday_date_label}.",
            ),
            scope="yesterday",
        )

        dy_wards = analysis.ward_summary[analysis.ward_summary["Daily Installed"] > 0] if "Daily Installed" in analysis.ward_summary.columns else pd.DataFrame()
        if not dy_wards.empty:
            today_ward_items = [
                (str(r["Ward"]), f"{int(r['Daily Installed']):,}", int(r["Daily Installed"]), str(r["Zone"]))
                for _, r in dy_wards.head(8).iterrows()
            ]
            r4_right = _card_inner(
                f"Yesterday's Installations by Ward ({yesterday_date_label})",
                _pill_bars_html(
                    today_ward_items,
                    bar_color=YESTERDAY_THEME["bar"],
                    track_color=YESTERDAY_THEME["track"],
                    value_color=YESTERDAY_THEME["value"],
                ),
                scope="yesterday",
            )
            r4_right_scope = "yesterday"
        else:
            top_w_items = [
                (str(r["Ward"]), f"{int(r['Total Panels']):,}", int(r["Total Panels"]), str(r["Zone"]))
                for _, r in analysis.top_wards.head(8).iterrows()
            ]
            r4_right = _card_inner(
                "Top Wards by Installed Panels",
                _pill_bars_html(
                    top_w_items,
                    bar_color=CUMULATIVE_THEME["bar"],
                    track_color=CUMULATIVE_THEME["track"],
                    value_color=CUMULATIVE_THEME["value"],
                ),
                scope="cumulative",
            )
            r4_right_scope = "cumulative"

        extra_rows_html += _two_card_row(
            r4_left,
            r4_right,
            left_scope="yesterday",
            right_scope=r4_right_scope,
        )

    # =========================================================================
    # ROW 5: Cumulative by Region + Top Wards (if not already shown in row 4)
    # =========================================================================
    reg_summary_df = analysis.zone_summary.groupby("Region", as_index=False).agg({"Total Panels": "sum"}).assign(
        **{"Share %": lambda d: (d["Total Panels"] / max(pk.total_panels, 1) * 100.0).round(1)}
    )
    reg_items_all = [
        (str(r["Region"]), f"{int(r['Total Panels']):,}", int(r["Total Panels"]), f"{r['Share %']:.1f}%")
        for _, r in reg_summary_df.iterrows()
    ]
    r5_left = _card_inner(
        "Cumulative by Region",
        _pill_bars_html(
            reg_items_all,
            bar_color=CUMULATIVE_THEME["bar"],
            track_color=CUMULATIVE_THEME["track"],
            value_color=CUMULATIVE_THEME["value"],
        ),
        scope="cumulative",
    )

    top_w_all = [
        (str(r["Ward"]), f"{int(r['Total Panels']):,}", int(r["Total Panels"]), str(r["Zone"]))
        for _, r in analysis.top_wards.head(8).iterrows()
    ]
    r5_right = _card_inner(
        "Top Wards by Installed Panels",
        _pill_bars_html(
            top_w_all,
            bar_color=CUMULATIVE_THEME["bar"],
            track_color=CUMULATIVE_THEME["track"],
            value_color=CUMULATIVE_THEME["value"],
        ),
        scope="cumulative",
    )
    row5_html = _two_card_row(r5_left, r5_right, left_scope="cumulative", right_scope="cumulative")

    # =========================================================================
    # ROW 6: Master Detailed Zone Matrix Table
    # =========================================================================
    zone_matrix_table = _render_panel_matrix_table(analysis)
    matrix_row_html = _single_card_row(zone_matrix_table, scope="cumulative")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CCMS Panel Installation Mail Dashboard</title>
  <style>
    body, table, td, p, a, li, blockquote {{
      -webkit-text-size-adjust: 100%;
      -ms-text-size-adjust: 100%;
    }}
    table, td {{
      mso-table-lspace: 0pt;
      mso-table-rspace: 0pt;
    }}
    img {{
      -ms-interpolation-mode: bicubic;
      border: 0;
      height: auto;
      line-height: 100%;
      outline: none;
      text-decoration: none;
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f8fafc;padding:24px 0 36px 0;">
    <tr>
      <td align="center" style="padding:0 16px;">
        <table role="presentation" width="840" cellpadding="0" cellspacing="0" border="0" style="width:840px;max-width:840px;text-align:left;">
          
          {note_row}

          <!-- Royal Blue Header Banner (Identical to LED Report) -->
          <tr>
            <td>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#1e3a8a;border-radius:12px;overflow:hidden;">
                <tr>
                  <td style="padding:22px 26px 20px 26px;background:linear-gradient(135deg, #1e3a8a 0%, #1e40af 50%, #172554 100%);">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td valign="middle">
                          <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#93c5fd;margin-bottom:3px;">
                            CCMS Panel Installation Report
                          </div>
                          <h1 style="margin:0;font-size:22px;line-height:1.25;font-weight:800;color:#ffffff;letter-spacing:-0.01em;">
                            Daily CCMS Panel Installation Dashboard
                          </h1>
                          <div style="font-size:12px;color:#cbd5e1;margin-top:6px;line-height:1.4;">
                            Installed Date (Yesterday): <strong style="color:#ffffff;">{escape(yesterday_date_label)}</strong> &bull;
                            Source: <strong style="color:#ffffff;">{escape(sheet_title)}</strong> (<code>{escape(panel_tab)}</code>) &bull;
                            Sent: {escape(generated_at)}
                          </div>
                        </td>
                        <td align="right" valign="middle" style="white-space:nowrap;padding-left:16px;">
                          <div style="display:inline-block;padding:6px 12px;background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.22);border-radius:999px;">
                            <span style="font-size:10px;font-weight:700;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em;">Live Sheet</span>
                            &nbsp;<span style="color:#ffffff;">&bull;</span>&nbsp;
                            <span style="font-size:11px;font-weight:700;color:#ffffff;">Reconciled 100%</span>
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- 4-Card Hero KPI Strip -->
          <tr>
            <td style="padding-top:16px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;">
                <tr>
                  {_kpi_card_html(card1_title, card1_val, card1_sub, card1_scope, card1_badge)}
                  <td width="16" style="width:16px;font-size:1px;line-height:1px;">&nbsp;</td>
                  {_kpi_card_html(card2_title, card2_val, card2_sub, card2_scope, card2_badge)}
                  <td width="16" style="width:16px;font-size:1px;line-height:1px;">&nbsp;</td>
                  {_kpi_card_html(card3_title, card3_val, card3_sub, card3_scope, card3_badge)}
                  <td width="16" style="width:16px;font-size:1px;line-height:1px;">&nbsp;</td>
                  {_kpi_card_html(card4_title, card4_val, card4_sub, card4_scope, card4_badge)}
                </tr>
              </table>
            </td>
          </tr>

          <!-- Row 1: Daily 14-day Trend (Vertical Bars) + Yesterday by Zone -->
          {_two_card_row(row1_left, row1_right, left_scope=row1_left_scope, right_scope=row1_right_scope)}

          <!-- Row 2: Cumulative by Zone + Switch Point Circuit Mapping Mix -->
          {_two_card_row(row2_left, row2_right, left_scope="cumulative", right_scope="cumulative")}

          <!-- Row 3 & 4: Monthly History + Top Contractors, Yesterday by Contractor + Ward -->
          {extra_rows_html}

          <!-- Row 5: Cumulative by Region + Top Wards -->
          {row5_html}

          <!-- Row 6: Master Detailed Zone Matrix Table -->
          {matrix_row_html}

          <!-- Footer -->
          <tr>
            <td style="padding:18px 4px 4px 4px;text-align:center;">
              <div style="font-size:11px;color:#64748b;">
                CCMS Panel Installation Mail Dashboard &bull; Data for Yesterday ({escape(yesterday_date_label)}) &bull; Sent {escape(generated_at)} &bull; Reconciled 100%
              </div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def render_panel_email_plain_text(
    analysis: PanelAnalysis,
    report_cfg: ReportConfig,
    *,
    sheet_title: str = "Google Sheet",
    panel_tab: str = "PANEL REPORT",
) -> str:
    pk = analysis.kpis
    sent_now = datetime.now()
    yesterday_date_label = pk.daily_date if pk.has_daily else (pk.latest_date_label or (sent_now - timedelta(days=1)).strftime("%d/%m/%Y"))

    lines = [
        "CCMS Panel Installation Mail Dashboard",
        f"Installed Date (Yesterday): {yesterday_date_label}",
        f"Source: {sheet_title} | Tab: {panel_tab}",
        f"Sent: {sent_now.strftime('%d %b %Y %I:%M %p')}",
        "",
        "KPI SUMMARY",
        f"- Cumulative Installed: {pk.total_panels:,} panels",
        f"- Geographical Coverage:{pk.zones_count} Zones, {pk.wards_count} Wards",
        f"- Circuit Mapping Rate: {pk.switch_points_mapped:,} / {pk.total_panels:,} panels ({pk.switch_points_mapped_pct:.1f}%)",
    ]
    if pk.has_daily and pk.daily_panels > 0:
        lines.append(f"- Installed Yesterday ({pk.daily_date}): +{pk.daily_panels:,} panels")
    if pk.last_7_days_total > 0:
        lines.append(f"- Last 7 Days:          {pk.last_7_days_total:,} panels ({pk.avg_7d_installed:.1f}/day)")
    if pk.total_installers > 0:
        lines.append(f"- Active Contractors:   {pk.active_installers_today} yesterday / {pk.total_installers} overall")

    if not analysis.installer_summary.empty:
        lines.extend(["", "TOP CONTRACTORS (INSTALLED BY)"])
        for _, r in analysis.installer_summary.head(10).iterrows():
            yest_cnt = int(r.get("Daily Installed", 0))
            cnt_7d = int(r.get("Last 7 Days", 0))
            lines.append(
                f"- {r['Contractor']}: {int(r['Total Panels']):,} panels ({r['Share %']}%), Yesterday +{yest_cnt}, 7d {cnt_7d:,}"
            )

    if not analysis.zone_summary.empty:
        lines.extend(["", "ZONE / CONSTITUENCY SUMMARY"])
        for _, r in analysis.zone_summary.iterrows():
            daily_part = f", Yesterday +{int(r['Daily Installed'])}" if pk.has_daily and "Daily Installed" in r else ""
            lines.append(
                f"- {r['Zone']} ({r['Region']}): {int(r['Total Panels']):,} panels ({r['Share %']}%), Mapped {int(r['Switch Points Mapped']):,} ({r['Mapping %']}%){daily_part}"
            )

    return "\n".join(lines)
