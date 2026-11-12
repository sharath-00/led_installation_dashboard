from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

import pandas as pd

from src.analytics import LedAnalysis
from src.config import ReportConfig


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
    default_bar_color: str = "#2563eb",
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


def _render_detailed_matrix_table(
    title: str,
    df: pd.DataFrame,
    dim_cols: list[str],
    wattages: list[int],
    *,
    has_daily: bool = False,
    accent_bg: str = "#f8fafc",
) -> str:
    if df is None or df.empty:
        return ""

    watt_cols = [f"{w}W" for w in wattages if f"{w}W" in df.columns]
    dim_ths = "".join(
        f'<th style="padding:9px 12px;text-align:left;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">{escape(c)}</th>'
        for c in dim_cols
    )
    watt_ths = "".join(
        f'<th style="padding:9px 8px;text-align:right;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">{escape(wc)}</th>'
        for wc in watt_cols
    )
    daily_th = (
        f'<th style="padding:9px 8px;text-align:right;font-size:10px;text-transform:uppercase;color:{YESTERDAY_THEME["badge_text"]};background-color:{YESTERDAY_THEME["badge_bg"]};border-bottom:2px solid {YESTERDAY_THEME["bar"]};">Yesterday</th>'
        if has_daily and "Daily Installed" in df.columns
        else ""
    )

    rows_html = []
    for idx, r in df.iterrows():
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"
        dim_tds = "".join(
            f'<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;font-size:11px;font-weight:{"700" if i == len(dim_cols)-1 else "500"};color:#0f172a;">{escape(str(r[c]))}</td>'
            for i, c in enumerate(dim_cols)
        )
        watt_tds = "".join(
            f'<td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;color:#334155;">{int(r[wc]):,}</td>'
            if int(r[wc]) > 0
            else '<td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;color:#cbd5e1;">-</td>'
            for wc in watt_cols
        )
        daily_td = ""
        if has_daily and "Daily Installed" in df.columns:
            dv = int(r["Daily Installed"])
            daily_td = (
                f'<td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;font-weight:700;color:{YESTERDAY_THEME["value"]};background-color:{YESTERDAY_THEME["cell_bg"]};">+{dv:,}</td>'
                if dv > 0
                else f'<td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;color:#94a3b8;background-color:{YESTERDAY_THEME["cell_bg"]};">0</td>'
            )
        rows_html.append(
            f'<tr style="background-color:{bg};">'
            f"{dim_tds}{watt_tds}"
            f'<td style="padding:8px 8px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;font-weight:700;color:{CUMULATIVE_THEME["value"]};background-color:{CUMULATIVE_THEME["cell_bg"]};">{int(r["Total Lamps"]):,}</td>'
            f"{daily_td}"
            f'<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:11px;font-weight:600;color:#0f172a;">{float(r["Share %"]):.1f}%</td>'
            "</tr>"
        )

    total_lamps_sum = int(df["Total Lamps"].sum())
    watt_totals = {wc: int(df[wc].sum()) for wc in watt_cols}
    total_watt_tds = "".join(
        f'<td style="padding:9px 8px;text-align:right;font-size:11px;font-weight:700;color:#0f172a;background-color:#f1f5f9;border-top:2px solid #cbd5e1;">{watt_totals[wc]:,}</td>'
        if watt_totals[wc] > 0
        else '<td style="padding:9px 8px;text-align:right;font-size:11px;color:#cbd5e1;background-color:#f1f5f9;border-top:2px solid #cbd5e1;">-</td>'
        for wc in watt_cols
    )
    total_daily_td = ""
    if has_daily and "Daily Installed" in df.columns:
        daily_sum = int(df["Daily Installed"].sum())
        total_daily_td = (
            f'<td style="padding:9px 8px;text-align:right;font-size:11px;font-weight:800;color:{YESTERDAY_THEME["badge_text"]};background-color:{YESTERDAY_THEME["badge_bg"]};border-top:2px solid {YESTERDAY_THEME["bar"]};">+{daily_sum:,}</td>'
        )
    summary_row_html = (
        f'<tr style="background-color:#f1f5f9;">'
        f'<td colspan="{len(dim_cols)}" style="padding:9px 12px;font-size:11px;font-weight:800;color:#0f172a;border-top:2px solid #cbd5e1;">All Corporations Total</td>'
        f'{total_watt_tds}'
        f'<td style="padding:9px 8px;text-align:right;font-size:11px;font-weight:800;color:{CUMULATIVE_THEME["badge_text"]};background-color:{CUMULATIVE_THEME["badge_bg"]};border-top:2px solid {CUMULATIVE_THEME["bar"]};">{total_lamps_sum:,}</td>'
        f'{total_daily_td}'
        f'<td style="padding:9px 12px;text-align:right;font-size:11px;font-weight:800;color:#0f172a;background-color:#f1f5f9;border-top:2px solid #cbd5e1;">100.0%</td>'
        f'</tr>'
    )

    legend_badges = _scope_badge("cumulative", "Cumulative Total")
    if has_daily and "Daily Installed" in df.columns:
        legend_badges += f' &nbsp;{_scope_badge("yesterday", "Yesterday")}'

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#ffffff;border:1px solid #cbd5e1;border-radius:12px;overflow:hidden;border-collapse:separate;">
      <tr>
        <td style="height:3px;background-color:#334155;font-size:1px;line-height:1px;">&nbsp;</td>
      </tr>
      <tr>
        <td style="background-color:{accent_bg};padding:11px 18px;border-bottom:1px solid #e2e8f0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td valign="middle">
                <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#334155;">{escape(title)}</span>
              </td>
              <td align="right" valign="middle" style="white-space:nowrap;">
                {legend_badges}
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
                {dim_ths}{watt_ths}
                <th style="padding:9px 8px;text-align:right;font-size:10px;text-transform:uppercase;color:{CUMULATIVE_THEME["badge_text"]};background-color:{CUMULATIVE_THEME["badge_bg"]};border-bottom:2px solid {CUMULATIVE_THEME["bar"]};">Total</th>
                {daily_th}
                <th style="padding:9px 12px;text-align:right;font-size:10px;text-transform:uppercase;color:#475569;border-bottom:2px solid #cbd5e1;">Share</th>
              </tr>
            </thead>
            <tbody>{''.join(rows_html)}{summary_row_html}</tbody>
          </table>
        </td>
      </tr>
    </table>
    """


def render_email_html(
    analysis: LedAnalysis,
    report_cfg: ReportConfig,
    *,
    sheet_title: str = "Google Sheet",
    overall_tab: str = "",
    daily_tab: str = "",
    raw_tab: str = "",
    custom_note: str = "",
    include_top_wards: bool = True,
) -> str:
    k = analysis.kpis
    ws = analysis.ward_stats
    inst = analysis.installer_analysis
    sent_now = datetime.now()
    sent_date_short = sent_now.strftime("%d %b %Y")
    generated_at = sent_now.strftime("%d %b %Y, %I:%M %p")
    default_yesterday = (sent_now - timedelta(days=1)).strftime("%d/%m/%Y")
    tab_parts = [t for t in (overall_tab, daily_tab, raw_tab) if t]
    tabs_label = " + ".join(tab_parts)
    yesterday_date_label = k.daily_date if k.has_daily else (k.overall_date or default_yesterday)

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

    # 4-Card KPI Strip (Installed yesterday, Last 7 days, Cumulative installed, Active installers yesterday)
    if k.has_daily:
        if k.has_history:
            delta_arrow = "&#9650;" if k.daily_vs_avg_pct >= 0 else "&#9660;"
            card1_sub = f"{delta_arrow} vs {len(analysis.daily_history)}-day avg {k.avg_daily_installed:.1f}"
        else:
            card1_sub = f"{k.daily_wards_count} wards active yesterday"
        card1_val = f"{k.daily_total:,}"
        card1_title = "Installed yesterday"
        card1_scope = "yesterday"
        card1_badge = "Yesterday"
    else:
        card1_title = "Cumulative installed"
        card1_val = f"{k.overall_total:,}"
        card1_sub = f"Till {escape(k.overall_date)}"
        card1_scope = "cumulative"
        card1_badge = "Cumulative"

    if k.has_history:
        card2_title = "Last 7 days"
        card2_val = f"{k.last_7_days_total:,}"
        avg_7 = k.avg_7d_installed if k.avg_7d_installed > 0 else k.avg_daily_installed
        card2_sub = f"{avg_7:.1f}/day average"
        card2_scope = "neutral"
        card2_badge = "7-Day Window"
    elif k.has_daily:
        card2_title = "Corporations &middot; Zones"
        card2_val = f"{k.corporations_count} &middot; {k.zones_count}"
        card2_sub = f"{k.daily_corps_count} corps active yesterday"
        card2_scope = "cumulative"
        card2_badge = "Cumulative"
    else:
        card2_title = "Corporations &middot; Zones"
        card2_val = f"{k.corporations_count} &middot; {k.zones_count}"
        card2_sub = "Active regions"
        card2_scope = "cumulative"
        card2_badge = "Cumulative"

    if k.has_daily:
        card3_title = "Cumulative installed"
        card3_val = f"{k.overall_total:,}"
        card3_sub = (
            f"since {escape(k.earliest_month_label)}"
            if k.earliest_month_label
            else f"Till {escape(k.overall_date)}"
        )
        card3_scope = "cumulative"
        card3_badge = "Cumulative"
    else:
        card3_title = "Avg lamps / ward"
        card3_val = f"{ws.mean_lamps:,.0f}"
        card3_sub = f"Median {ws.median_lamps:,}"
        card3_scope = "cumulative"
        card3_badge = "Cumulative"

    if k.has_installers:
        card4_title = "Active installers yesterday"
        card4_val = f"{k.active_installers_today:,}"
        card4_sub = f"{k.total_installers:,} installer IDs overall"
        card4_scope = "yesterday"
        card4_badge = "Yesterday"
    else:
        card4_title = "Top wattage"
        card4_val = escape(k.top_wattage)
        card4_sub = f"{k.top_wattage_pct:.1f}% of total lamps"
        card4_scope = "cumulative"
        card4_badge = "Cumulative"

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

    # Row 1: Daily 14-day Trend (or Yesterday by Wattage) + Yesterday by Constituency
    if k.has_history and not analysis.daily_history.empty:
        hist_bars = [
            (str(r["Label"]), float(r["Installed"]), f"{int(r['Installed']):,}", bool(r["Is Latest"]))
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
    elif k.has_daily:
        today_w_bars = [
            (str(r["Wattage"]), float(r.get("Daily Installed", 0)), f"{int(r.get('Daily Installed', 0)):,}", True)
            for _, r in analysis.wattage_summary.iterrows()
            if int(r.get("Daily Installed", 0)) > 0
        ]
        corp_split_txt = (
            "By Corporation: "
            + " | ".join(f"{r['Corporation']}: {int(r['Total Lamps'])}" for _, r in analysis.daily_corporation_summary.iterrows())
            if not analysis.daily_corporation_summary.empty
            else ""
        )
        row1_left = _card_inner(
            f"Yesterday by Wattage ({k.daily_date})",
            _vertical_bars_html(
                today_w_bars,
                bar_width=40,
                default_bar_color=YESTERDAY_THEME["bar"],
                highlight_bar_color=YESTERDAY_THEME["bar"],
                highlight_text_color=YESTERDAY_THEME["value"],
                footer_note=corp_split_txt,
            ),
            scope="yesterday",
        )
        row1_left_scope = "yesterday"
    else:
        ov_w_bars = [
            (str(r["Wattage"]), float(r["Overall Lamps"]), f"{int(r['Overall Lamps']):,}", False)
            for _, r in analysis.wattage_summary.iterrows()
        ]
        row1_left = _card_inner(
            "Cumulative Lamps by Wattage",
            _vertical_bars_html(ov_w_bars, bar_width=36, default_bar_color=CUMULATIVE_THEME["bar"]),
            scope="cumulative",
        )
        row1_left_scope = "cumulative"

    if k.has_daily and not analysis.daily_constituency_summary.empty:
        today_const_items = [
            (str(r["Constituency"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), str(r["Corporation"]))
            for _, r in analysis.daily_constituency_summary.iterrows()
        ]
        row1_right = _card_inner(
            f"Yesterday by Constituency ({k.daily_date})",
            _pill_bars_html(
                today_const_items,
                bar_color=YESTERDAY_THEME["bar"],
                track_color=YESTERDAY_THEME["track"],
                value_color=YESTERDAY_THEME["value"],
            ),
            scope="yesterday",
        )
        row1_right_scope = "yesterday"
    else:
        corp_items = [
            (str(r["Corporation"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), f"{r['Share %']:.1f}%")
            for _, r in analysis.corporation_summary.iterrows()
        ]
        row1_right = _card_inner(
            "Cumulative by Corporation",
            _pill_bars_html(
                corp_items,
                bar_color=CUMULATIVE_THEME["bar"],
                track_color=CUMULATIVE_THEME["track"],
                value_color=CUMULATIVE_THEME["value"],
            ),
            scope="cumulative",
        )
        row1_right_scope = "cumulative"

    # Row 2: Cumulative by Constituency + Lamp Wattage Mix (Cumulative)
    cum_const_items = [
        (str(r["Constituency"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), f"{r['Share %']:.1f}%")
        for _, r in analysis.constituency_summary.iterrows()
    ]
    row2_left = _card_inner(
        "Cumulative by Constituency",
        _pill_bars_html(
            cum_const_items,
            bar_color=CUMULATIVE_THEME["bar"],
            track_color=CUMULATIVE_THEME["track"],
            value_color=CUMULATIVE_THEME["value"],
        ),
        scope="cumulative",
    )

    watt_items = [
        (str(r["Wattage"]), f"{int(r['Overall Lamps']):,}", int(r["Overall Lamps"]), f"{r['Lamp Share %']:.1f}%")
        for _, r in analysis.wattage_summary.iterrows()
    ]
    row2_right = _card_inner(
        "Lamp Wattage Mix (Cumulative)",
        _pill_bars_html(
            watt_items,
            bar_color=CUMULATIVE_THEME["bar"],
            track_color=CUMULATIVE_THEME["track"],
            value_color=CUMULATIVE_THEME["value"],
            ranked=False,
        ),
        scope="cumulative",
    )

    # Row 3 & Row 4: When Sheet2 / Installers exist -> Monthly + Top Installers, Yesterday by Installer + Ward
    extra_rows_html = ""
    if inst is not None and k.has_installers:
        if not inst.monthly_history.empty:
            m_bars = [
                (str(r["Label"]), float(r["Installed"]), f"{int(r['Installed']):,}", False)
                for _, r in inst.monthly_history.iterrows()
            ]
            m_note = (
                f"Earlier months ({inst.earlier_months_label}): {inst.earlier_months_total:,} lamps, not shown"
                if inst.earlier_months_total > 0
                else ""
            )
            r3_left = _card_inner(
                "Monthly Installations",
                _vertical_bars_html(
                    m_bars,
                    bar_width=20,
                    default_bar_color=CUMULATIVE_THEME["bar"],
                    footer_note=m_note,
                ),
                scope="cumulative",
            )
        else:
            corp_items_all = [
                (str(r["Corporation"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), f"{r['Share %']:.1f}%")
                for _, r in analysis.corporation_summary.iterrows()
            ]
            r3_left = _card_inner(
                "Cumulative by Corporation",
                _pill_bars_html(
                    corp_items_all,
                    bar_color=CUMULATIVE_THEME["bar"],
                    track_color=CUMULATIVE_THEME["track"],
                    value_color=CUMULATIVE_THEME["value"],
                ),
                scope="cumulative",
            )

        top_inst_items = [
            (str(r["Installed By"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), f"{r['Share %']:.1f}%")
            for _, r in inst.top_installers_cumulative.head(8).iterrows()
        ]
        r3_right = _card_inner(
            "Top Installers (Cumulative)",
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

        today_inst_items = [
            (str(r["Installed By"]), f"{int(r['Yesterday']):,}", int(r["Yesterday"]), f"{int(r['Wards'])}w")
            for _, r in inst.today_by_installer.head(8).iterrows()
        ]
        r4_left = _card_inner(
            f"Yesterday by Installer ({inst.today_date_label or k.daily_date})",
            _pill_bars_html(
                today_inst_items,
                bar_color=YESTERDAY_THEME["bar"],
                track_color=YESTERDAY_THEME["track"],
                value_color=YESTERDAY_THEME["value"],
                empty_msg=f"No Sheet2 records dated {inst.today_date_label or k.daily_date}.",
            ),
            scope="yesterday",
        )
        if k.has_daily and not analysis.daily_ward_summary.empty:
            today_ward_items = [
                (str(r["Ward"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), str(r["Constituency"]))
                for _, r in analysis.daily_ward_summary.head(8).iterrows()
            ]
            r4_right = _card_inner(
                f"Yesterday's Installations by Ward ({k.daily_date})",
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
            r4_right = _card_inner(
                "Cumulative by Corporation",
                _pill_bars_html(
                    [
                        (str(r["Corporation"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), f"{r['Share %']:.1f}%")
                        for _, r in analysis.corporation_summary.iterrows()
                    ],
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

    # Row 5: Cumulative by Corporation & Zone + Top Wards (or Yesterday by Corporation)
    corp_items_all = [
        (str(r["Corporation"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), f"{r['Share %']:.1f}% \u2022 {int(r['Wards'])}w")
        for _, r in analysis.corporation_summary.iterrows()
    ]
    zone_sub_html = ""
    if not analysis.zone_summary.empty:
        zone_items = [
            (str(r["Zone"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), f"{r['Share %']:.1f}%")
            for _, r in analysis.zone_summary.iterrows()
        ]
        zone_sub_html = (
            '<div style="font-size:10px;font-weight:700;text-transform:uppercase;color:#64748b;margin:14px 0 6px 0;padding-top:12px;border-top:1px solid #e2e8f0;">By Zone</div>'
            + _pill_bars_html(
                zone_items,
                bar_color="#3b82f6",
                track_color=CUMULATIVE_THEME["track"],
                value_color=CUMULATIVE_THEME["value"],
                ranked=False,
            )
        )
    geo_card = _card_inner(
        "Cumulative by Corporation & Zone",
        _pill_bars_html(
            corp_items_all,
            bar_color=CUMULATIVE_THEME["bar"],
            track_color=CUMULATIVE_THEME["track"],
            value_color=CUMULATIVE_THEME["value"],
            ranked=False,
        ) + zone_sub_html,
        scope="cumulative",
    )

    if include_top_wards and not analysis.top_wards.empty:
        top_ward_items = [
            (str(r["Ward"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), str(r["Constituency"]))
            for _, r in analysis.top_wards.head(8).iterrows()
        ]
        right_geo_card = _card_inner(
            f"Top {len(top_ward_items)} Wards (Cumulative)",
            _pill_bars_html(
                top_ward_items,
                bar_color=CUMULATIVE_THEME["bar"],
                track_color=CUMULATIVE_THEME["track"],
                value_color=CUMULATIVE_THEME["value"],
            ),
            scope="cumulative",
        )
        right_geo_scope = "cumulative"
    elif k.has_daily and not analysis.daily_corporation_summary.empty:
        daily_corp_bars = [
            (str(r["Corporation"]), float(r["Total Lamps"]), f"{int(r['Total Lamps']):,}", True)
            for _, r in analysis.daily_corporation_summary.iterrows()
        ]
        right_geo_card = _card_inner(
            f"Yesterday by Corporation ({k.daily_date})",
            _vertical_bars_html(
                daily_corp_bars,
                bar_width=38,
                default_bar_color=YESTERDAY_THEME["bar"],
                highlight_bar_color=YESTERDAY_THEME["bar"],
                highlight_text_color=YESTERDAY_THEME["value"],
            ),
            scope="yesterday",
        )
        right_geo_scope = "yesterday"
    else:
        right_geo_card = _card_inner(
            "Average Lamps per Ward by Constituency",
            _pill_bars_html(
                [
                    (str(r["Constituency"]), f"{int(r['Avg / Ward']):,}/ward", int(r["Avg / Ward"]), f"{int(r['Wards'])}w")
                    for _, r in analysis.constituency_summary.iterrows()
                ],
                bar_color=CUMULATIVE_THEME["bar"],
                track_color=CUMULATIVE_THEME["track"],
                value_color=CUMULATIVE_THEME["value"],
            ),
            scope="cumulative",
        )
        right_geo_scope = "cumulative"

    extra_rows_html += _two_card_row(
        geo_card,
        right_geo_card,
        left_scope="cumulative",
        right_scope=right_geo_scope,
    )

    if not (inst is not None and k.has_installers) and k.has_daily and not analysis.daily_ward_summary.empty:
        today_ward_items = [
            (str(r["Ward"]), f"{int(r['Total Lamps']):,}", int(r["Total Lamps"]), str(r["Constituency"]))
            for _, r in analysis.daily_ward_summary.head(8).iterrows()
        ]
        today_wards_card = _card_inner(
            f"Yesterday's Installations by Ward ({k.daily_date})",
            _pill_bars_html(
                today_ward_items,
                bar_color=YESTERDAY_THEME["bar"],
                track_color=YESTERDAY_THEME["track"],
                value_color=YESTERDAY_THEME["value"],
            ),
            scope="yesterday",
        )
        extra_rows_html += _single_card_row(today_wards_card, scope="yesterday")

    corp_matrix_html = _render_detailed_matrix_table(
        "Corporation Summary Matrix",
        analysis.corporation_summary,
        ["Corporation"],
        analysis.wattages,
        has_daily=k.has_daily,
    )
    corp_matrix_row = f'<tr><td style="padding-top:16px;">{corp_matrix_html}</td></tr>' if corp_matrix_html else ""

    recon_note = (
        f"Reconciled ({k.overall_sheet_grand_total:,})"
        if k.overall_reconciled
        else f"Parsed {k.overall_total:,} vs Sheet {k.overall_sheet_grand_total:,}"
    )

    header_right_summary = (
        f"{k.overall_total:,} Total Lamps \u2022 +{k.daily_total:,} Yesterday"
        if k.has_daily
        else f"{k.overall_total:,} Total Lamps"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escape(report_cfg.title)}</title>
</head>
<body style="margin:0;padding:0;background-color:#eef2f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="840" cellpadding="0" cellspacing="0" border="0" style="max-width:840px;width:100%;">
          <tr>
            <td style="padding-bottom:16px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#ffffff;border:1px solid #cbd5e1;border-radius:12px;overflow:hidden;border-collapse:separate;">
                <tr>
                  <td style="height:4px;background-color:#1e3a8a;font-size:1px;line-height:1px;">&nbsp;</td>
                </tr>
                <tr>
                  <td style="padding:16px 20px 14px 20px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td valign="top">
                          <h1 style="margin:0;font-size:21px;line-height:1.25;font-weight:800;color:#0f172a;">{escape(report_cfg.title)}</h1>
                          <div style="font-size:12px;color:#64748b;margin-top:5px;">
                            Installed date (Yesterday): {escape(yesterday_date_label)} &bull; Sent: {escape(sent_date_short)} &bull; Source: {escape(sheet_title)} ({escape(tabs_label)}, {k.overall_total:,} lamps)
                          </div>
                        </td>
                        <td align="right" valign="top" style="white-space:nowrap;padding-left:12px;">
                          <span style="display:inline-block;padding:6px 11px;border-radius:8px;background-color:{YESTERDAY_THEME["badge_bg"]};border:1px solid {YESTERDAY_THEME["card_border"]};font-size:11px;font-weight:700;color:{YESTERDAY_THEME["badge_text"]};"><span style="color:{YESTERDAY_THEME["bar"]};">&#9679;</span> Yesterday: {escape(yesterday_date_label)}</span>
                          <span style="display:inline-block;padding:6px 11px;border-radius:8px;background-color:#f8fafc;border:1px solid #cbd5e1;font-size:11px;font-weight:600;color:#334155;margin-left:6px;">All Corporations</span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="background-color:#f8fafc;border-top:1px solid #e2e8f0;padding:8px 20px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td valign="middle" style="font-size:11px;color:#475569;">
                          <span style="font-weight:700;color:{YESTERDAY_THEME["badge_text"]};"><span style="color:{YESTERDAY_THEME["bar"]};">&#9679;</span> Amber = Yesterday ({escape(yesterday_date_label)})</span>
                          &nbsp;&nbsp;&bull;&nbsp;&nbsp;
                          <span style="font-weight:700;color:{CUMULATIVE_THEME["badge_text"]};"><span style="color:{CUMULATIVE_THEME["bar"]};">&#9679;</span> Blue = Cumulative Overall</span>
                          &nbsp;&nbsp;&bull;&nbsp;&nbsp;
                          <span style="font-weight:600;color:#475569;"><span style="color:#64748b;">&#9679;</span> Slate = Rolling 7-Day Window</span>
                        </td>
                        <td align="right" valign="middle" style="font-size:11px;font-weight:600;color:#64748b;white-space:nowrap;">
                          {escape(header_right_summary)}
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          {note_row}

          <!-- 4-Card KPI Strip -->
          <tr>
            <td>
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

          {_two_card_row(row1_left, row1_right, left_scope=row1_left_scope, right_scope=row1_right_scope)}

          {_two_card_row(row2_left, row2_right, left_scope="cumulative", right_scope="cumulative")}

          {extra_rows_html}

          {corp_matrix_row}

          <tr>
            <td style="padding:18px 4px 4px 4px;text-align:center;">
              <div style="font-size:11px;color:#64748b;">
                LED Installation Mail Dashboard &bull; Data for Yesterday ({escape(yesterday_date_label)}) &bull; Sent {escape(generated_at)} &bull; {escape(recon_note)}
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


def render_email_plain_text(
    analysis: LedAnalysis,
    report_cfg: ReportConfig,
    *,
    sheet_title: str = "Google Sheet",
    overall_tab: str = "",
    daily_tab: str = "",
    raw_tab: str = "",
) -> str:
    k = analysis.kpis
    inst = analysis.installer_analysis
    sent_now = datetime.now()
    default_yesterday = (sent_now - timedelta(days=1)).strftime("%d/%m/%Y")
    yesterday_date_label = k.daily_date if k.has_daily else (k.overall_date or default_yesterday)
    tabs = " + ".join([t for t in (overall_tab, daily_tab, raw_tab) if t])
    lines = [
        f"{report_cfg.title}",
        f"Installed Date (Yesterday): {yesterday_date_label}",
        f"Source: {sheet_title} | Tabs: {tabs}",
        f"Sent: {sent_now.strftime('%d %b %Y %I:%M %p')}",
        "",
        "KPI SUMMARY",
        f"- Cumulative Installed: {k.overall_total:,} lamps",
        f"- Top Wattage:          {k.top_wattage} ({k.top_wattage_pct:.1f}%)",
    ]
    if k.has_daily:
        lines.append(f"- Installed Yesterday ({k.daily_date}): +{k.daily_total:,} lamps")
    if k.has_history:
        lines.append(f"- Last 7 Days:          {k.last_7_days_total:,} lamps")
    if inst and k.has_installers:
        lines.append(
            f"- Active Installers:    {k.active_installers_today} yesterday / {k.total_installers} overall"
        )

    if inst and not inst.top_installers_cumulative.empty:
        lines.extend(["", "TOP INSTALLERS (INSTALLED BY)"])
        for _, r in inst.top_installers_cumulative.head(10).iterrows():
            lines.append(
                f"- {r['Installed By']}: {int(r['Total Lamps']):,} lamps ({r['Share %']}%), Yesterday +{int(r['Yesterday'])}, 7d {int(r['Last 7 Days']):,}"
            )

    if not analysis.corporation_summary.empty:
        lines.extend(["", "CORPORATION SUMMARY"])
        for _, r in analysis.corporation_summary.iterrows():
            daily_part = f", Yesterday +{int(r['Daily Installed'])}" if k.has_daily else ""
            lines.append(
                f"- {r['Corporation']}: {int(r['Total Lamps']):,} lamps ({r['Share %']}%){daily_part}"
            )
    return "\n".join(lines)
