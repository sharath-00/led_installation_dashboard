from __future__ import annotations

import io
import re
import zipfile
from datetime import date
from xml.sax.saxutils import escape as xml_escape

import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.analytics import RawLampData, _pick_yesterday_target_dt


_INVALID_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]+")
_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
_HEADER_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
_HEADER_ALIGN = Alignment(vertical="center")


def _safe_sheet_title(name: str, used: set[str]) -> str:
    cleaned = _INVALID_SHEET_CHARS.sub("-", (name or "").strip()).strip("' ")
    if not cleaned:
        cleaned = "Sheet"
    base = cleaned[:31]
    candidate = base
    idx = 2
    while candidate.lower() in used:
        suffix = f"_{idx}"
        candidate = f"{base[: 31 - len(suffix)]}{suffix}"
        idx += 1
    used.add(candidate.lower())
    return candidate


def _clean_xml_text(val: object) -> str:
    if val is None:
        return ""
    s = str(val)
    if s and _ILLEGAL_XML_CHARS.search(s):
        s = _ILLEGAL_XML_CHARS.sub("", s)
    return s


def _build_shared_strings_xlsx(
    sheets: list[tuple[str, list[str], pd.DataFrame]],
) -> bytes:
    """Write multi-sheet .xlsx using sharedStrings.xml + max ZIP compression (~40% smaller for email attachments)."""
    tmpl = openpyxl.Workbook()
    try:
        first_title, _, _ = sheets[0]
        tmpl.active.title = first_title
        hdr_cell = tmpl.active["A1"]
        hdr_cell.value = "hdr"
        hdr_cell.font = _HEADER_FONT
        hdr_cell.fill = _HEADER_FILL
        hdr_cell.alignment = _HEADER_ALIGN
        hdr_style_id = hdr_cell.style_id

        for title, _, _ in sheets[1:]:
            ws = tmpl.create_sheet(title)
            ws["A1"] = "hdr"

        tmpl_buf = io.BytesIO()
        tmpl.save(tmpl_buf)
    finally:
        tmpl.close()

    sst_map: dict[str, int] = {}
    sst_list: list[str] = []
    sst_ref_count = 0

    def _intern(val: str) -> int:
        nonlocal sst_ref_count
        sst_ref_count += 1
        idx = sst_map.get(val)
        if idx is None:
            idx = len(sst_list)
            sst_map[val] = idx
            sst_list.append(val)
        return idx

    max_cols = max((len(hdrs) for _, hdrs, _ in sheets), default=1)
    col_letters = [get_column_letter(i + 1) for i in range(max_cols)]

    out_buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(tmpl_buf.getvalue()), "r") as zin,
        zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout,
    ):
        sheet_map = {f"xl/worksheets/sheet{i + 1}.xml": i for i in range(len(sheets))}

        for item in zin.infolist():
            if item.filename in sheet_map:
                _, hdrs, df = sheets[sheet_map[item.filename]]
                parts: list[str] = [
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetViews><sheetView workbookViewId="0">'
                    '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                    "</sheetView></sheetViews>"
                    "<sheetData>"
                ]

                # Header row (row 1)
                hdr_cells = [f'<row r="1">']
                for c_idx, h in enumerate(hdrs):
                    idx = _intern(_clean_xml_text(h))
                    hdr_cells.append(
                        f'<c r="{col_letters[c_idx]}1" s="{hdr_style_id}" t="s"><v>{idx}</v></c>'
                    )
                hdr_cells.append("</row>")
                parts.append("".join(hdr_cells))

                # Data rows (rows 2..N)
                if not df.empty:
                    for r_num, row in enumerate(df.itertuples(index=False, name=None), start=2):
                        row_cells = [f'<row r="{r_num}">']
                        for c_idx, raw_val in enumerate(row):
                            sval = _clean_xml_text(raw_val)
                            if sval == "":
                                continue
                            idx = _intern(sval)
                            row_cells.append(f'<c r="{col_letters[c_idx]}{r_num}" t="s"><v>{idx}</v></c>')
                        row_cells.append("</row>")
                        parts.append("".join(row_cells))

                parts.append("</sheetData></worksheet>")
                zout.writestr(item.filename, "".join(parts).encode("utf-8"))

            elif item.filename == "xl/_rels/workbook.xml.rels":
                rels_xml = zin.read(item.filename).decode("utf-8")
                if "sharedStrings.xml" not in rels_xml:
                    existing_ids = {int(m) for m in re.findall(r'Id="rId(\d+)"', rels_xml)}
                    next_id = max(existing_ids, default=0) + 1
                    rels_xml = rels_xml.replace(
                        "</Relationships>",
                        f'<Relationship Id="rId{next_id}" '
                        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
                        'Target="sharedStrings.xml"/></Relationships>',
                    )
                zout.writestr(item.filename, rels_xml.encode("utf-8"))

            elif item.filename == "[Content_Types].xml":
                ct_xml = zin.read(item.filename).decode("utf-8")
                if "sharedStrings.xml" not in ct_xml:
                    ct_xml = ct_xml.replace(
                        "</Types>",
                        '<Override PartName="/xl/sharedStrings.xml" '
                        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
                    )
                zout.writestr(item.filename, ct_xml.encode("utf-8"))

            else:
                zout.writestr(item.filename, zin.read(item.filename))

        sst_parts: list[str] = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="{sst_ref_count}" uniqueCount="{len(sst_list)}">'
        ]
        for s in sst_list:
            esc = xml_escape(s)
            if s != s.strip():
                sst_parts.append(f'<si><t xml:space="preserve">{esc}</t></si>')
            else:
                sst_parts.append(f"<si><t>{esc}</t></si>")
        sst_parts.append("</sst>")
        zout.writestr("xl/sharedStrings.xml", "".join(sst_parts).encode("utf-8"))

    return out_buf.getvalue()


def build_sheet2_excel_bytes(
    raw_data: RawLampData,
    *,
    reference_today: date | None = None,
    target_date: date | None = None,
) -> tuple[str, bytes, dict[str, int]]:
    """Build an .xlsx workbook from Sheet2: Tab 1 Overall Data, Tab 2 Yesterday, Tabs 3..N one per Constituency."""
    if raw_data is None or raw_data.df.empty:
        raise ValueError("Cannot build Excel workbook: Sheet2 data is empty.")

    meta_df = raw_data.df
    full_df = raw_data.full_df if not raw_data.full_df.empty else meta_df
    headers = list(full_df.columns) if not full_df.empty else list(raw_data.raw_headers)

    if target_date is not None:
        target_dt = pd.Timestamp(target_date)
    else:
        target_dt = (
            _pick_yesterday_target_dt(meta_df["install_dt"], reference_today=reference_today)
            if raw_data.has_dates
            else pd.NaT
        )

    if pd.notna(target_dt):
        dt_norm = meta_df["install_dt"].dt.normalize()
        upto_mask = dt_norm.isna() | (dt_norm <= target_dt.normalize())
        yesterday_mask = dt_norm == target_dt.normalize()
        date_tag = target_dt.strftime("%d-%m-%Y")
        yest_title_raw = f"Yesterday ({date_tag})"
        filename = f"LED_Installations_{date_tag}.xlsx"
    else:
        upto_mask = pd.Series(True, index=meta_df.index)
        yesterday_mask = pd.Series(False, index=meta_df.index)
        yest_title_raw = "Yesterday Installed"
        filename = "LED_Installations_Details.xlsx"

    used_names: set[str] = set()
    tab_counts: dict[str, int] = {}
    sheets: list[tuple[str, list[str], pd.DataFrame]] = []

    cum_meta = meta_df.loc[upto_mask]
    cum_full = full_df.loc[upto_mask]

    # Tab 1: Overall Data (all cumulative Sheet2 rows with all columns)
    overall_title = _safe_sheet_title("Overall Data", used_names)
    sheets.append((overall_title, headers, cum_full))
    tab_counts[overall_title] = int(len(cum_full))

    # Tab 2: Yesterday's installed lamp details
    yest_title = _safe_sheet_title(yest_title_raw, used_names)
    yest_df = full_df.loc[yesterday_mask]
    sheets.append((yest_title, headers, yest_df))
    tab_counts[yest_title] = int(len(yest_df))

    # Tabs 3..N: Every Constituency's full lamp details in its own separate tab
    const_order = (
        cum_meta["zone"]
        .value_counts(sort=True, ascending=False)
        .index.tolist()
    )
    for const in const_order:
        c_mask = cum_meta["zone"] == const
        c_df = cum_full.loc[c_mask]
        c_title = _safe_sheet_title(str(const), used_names)
        sheets.append((c_title, headers, c_df))
        tab_counts[c_title] = int(len(c_df))

    xlsx_bytes = _build_shared_strings_xlsx(sheets)
    return filename, xlsx_bytes, tab_counts
