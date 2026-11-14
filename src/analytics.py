from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd


WARD_CODE_RE = re.compile(r"(?:[-_\s]W\d+\b|^W-?\d+\b|^Ward[\s_-]*\d+\b)", re.IGNORECASE)
DATE_IN_TEXT_RE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")


def _clean_str(val: Any) -> str:
    return re.sub(r"\s+", " ", str(val or "").strip())


def _parse_int(val: Any) -> int:
    s = str(val or "").strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(round(float(s)))
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return int(round(float(m.group(0)))) if m else 0


def _parse_wattage_header(val: Any) -> int | None:
    s = _clean_str(val)
    if not s:
        return None
    m = re.fullmatch(r"(\d+)(?:\.0+)?\s*W?", s, flags=re.IGNORECASE)
    if not m:
        return None
    w = int(m.group(1))
    if 1 <= w <= 2000:
        return w
    return None


def _is_ward_label(label: str) -> bool:
    return bool(WARD_CODE_RE.search(label.strip()))


def parse_date_sort_key(date_str: str) -> datetime:
    for fmt in (
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d.%m.%y",
        "%d-%m-%y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return datetime.min


@dataclass
class ParsedSheet:
    tab_name: str
    report_date: str
    wattages: list[int]
    ward_df: pd.DataFrame
    sheet_grand_total: int
    parsed_total: int
    reconciled_ok: bool
    source_table_type: str  # "corporation_constituency" | "pivot_row_labels" | "raw_log"


def _find_table_origin(grid: list[list[str]]) -> tuple[int, int | None, int, str]:
    for r_idx, row in enumerate(grid):
        norm_cells = [_clean_str(c).lower() for c in row]
        if "corporation" in norm_cells and "constituency" in norm_cells:
            corp_col = norm_cells.index("corporation")
            const_col = norm_cells.index("constituency")
            return r_idx, corp_col, const_col, "corporation_constituency"

    for r_idx, row in enumerate(grid):
        norm_cells = [_clean_str(c).lower() for c in row]
        if "row labels" in norm_cells:
            return r_idx, None, norm_cells.index("row labels"), "pivot_row_labels"

    raise ValueError(
        "Could not locate a 'Corporation' / 'Constituency' table or 'Row Labels' pivot table in this worksheet."
    )


def _extract_report_date(grid: list[list[str]], header_row: int, tab_name: str) -> str:
    for r in range(min(header_row, len(grid))):
        row = grid[r]
        for c, cell in enumerate(row):
            if "installed on" in _clean_str(cell).lower() or _clean_str(cell).lower() in {"date", "report date"}:
                for nxt in range(c + 1, min(c + 4, len(row))):
                    candidate = _clean_str(row[nxt])
                    if candidate:
                        return candidate
    m = DATE_IN_TEXT_RE.search(tab_name or "")
    if m:
        return m.group(1)
    return tab_name or "Current Snapshot"


def parse_led_matrix_grid(grid: list[list[str]], tab_name: str = "") -> ParsedSheet:
    if not grid:
        raise ValueError(f"Worksheet '{tab_name}' is empty.")

    header_row, corp_col, label_col, table_type = _find_table_origin(grid)
    report_date = _extract_report_date(grid, header_row, tab_name)

    headers = grid[header_row]
    watt_cols: list[tuple[int, int]] = []
    total_col: int | None = None

    for c in range(label_col + 1, len(headers)):
        cell = _clean_str(headers[c])
        low = cell.lower()
        if low in {"grand total", "total", "total lamps"}:
            total_col = c
            break
        w = _parse_wattage_header(cell)
        if w is not None:
            watt_cols.append((c, w))
        elif cell == "" and watt_cols:
            break

    if not watt_cols and total_col is None:
        raise ValueError(f"No wattage columns or Grand Total column found in '{tab_name}'.")

    wattages = sorted([w for _, w in watt_cols])

    @dataclass
    class RawRow:
        corp: str
        label: str
        counts: dict[int, int]
        total: int

    raw_rows: list[RawRow] = []
    sheet_grand_total = 0

    for r in range(header_row + 1, len(grid)):
        row = grid[r]
        corp_val = _clean_str(row[corp_col]) if (corp_col is not None and corp_col < len(row)) else ""
        label_val = _clean_str(row[label_col]) if label_col < len(row) else ""

        counts: dict[int, int] = {}
        for col_idx, watt in watt_cols:
            counts[watt] = _parse_int(row[col_idx]) if col_idx < len(row) else 0

        row_total = (
            _parse_int(row[total_col])
            if (total_col is not None and total_col < len(row) and _clean_str(row[total_col]) != "")
            else sum(counts.values())
        )

        if not label_val and row_total == 0:
            continue

        if label_val.lower() in {"grand total", "total"}:
            sheet_grand_total = row_total
            break

        if label_val:
            raw_rows.append(RawRow(corp=corp_val, label=label_val, counts=counts, total=row_total))

    n = len(raw_rows)
    row_kind: list[str] = [""] * n

    for i, rr in enumerate(raw_rows):
        if _is_ward_label(rr.label):
            row_kind[i] = "WARD"
            continue

        if rr.corp:
            row_kind[i] = "CONSTITUENCY"
            continue

        if i + 1 < n and raw_rows[i + 1].corp and not _is_ward_label(raw_rows[i + 1].label):
            row_kind[i] = "ZONE"
            continue

        ward_sum = 0
        has_child_ward = False
        for j in range(i + 1, n):
            if _is_ward_label(raw_rows[j].label):
                has_child_ward = True
                ward_sum += raw_rows[j].total
                if ward_sum >= rr.total:
                    break
            else:
                break

        if has_child_ward and ward_sum == rr.total:
            row_kind[i] = "CONSTITUENCY"
            continue

        if table_type == "pivot_row_labels":
            if i + 1 < n and not _is_ward_label(raw_rows[i + 1].label):
                row_kind[i] = "ZONE"
                continue
            row_kind[i] = "CONSTITUENCY" if has_child_ward else "WARD"
            continue

        next_is_parent = i + 1 < n and not _is_ward_label(raw_rows[i + 1].label)
        next_has_wards = i + 2 < n and _is_ward_label(raw_rows[i + 2].label)
        if next_is_parent and (rr.total > raw_rows[i + 1].total or next_has_wards):
            row_kind[i] = "ZONE"
        else:
            row_kind[i] = "WARD"

    records: list[dict[str, Any]] = []
    current_zone = "All Zones"
    current_corp = "Unspecified"
    current_const = "Unspecified"
    const_has_wards = False
    last_const_row: RawRow | None = None
    last_const_ctx: tuple[str, str, str] | None = None

    def _flush_childless_const() -> None:
        if last_const_row is not None and not const_has_wards and last_const_ctx is not None:
            z, c, cn = last_const_ctx
            rec: dict[str, Any] = {
                "Zone": z,
                "Corporation": c,
                "Constituency": cn,
                "Ward": cn,
            }
            for w in wattages:
                rec[f"{w}W"] = last_const_row.counts.get(w, 0)
            rec["Total Lamps"] = last_const_row.total
            records.append(rec)

    for i, rr in enumerate(raw_rows):
        kind = row_kind[i]
        if kind == "ZONE":
            _flush_childless_const()
            last_const_row = None
            const_has_wards = False
            current_zone = rr.label
            if i + 1 < n and raw_rows[i + 1].corp:
                current_corp = raw_rows[i + 1].corp
        elif kind == "CONSTITUENCY":
            _flush_childless_const()
            if rr.corp:
                current_corp = rr.corp
            current_const = rr.label
            last_const_row = rr
            last_const_ctx = (current_zone, current_corp, current_const)
            const_has_wards = False
        else:
            if rr.corp:
                current_corp = rr.corp
            const_has_wards = True
            rec = {
                "Zone": current_zone,
                "Corporation": current_corp,
                "Constituency": current_const,
                "Ward": rr.label,
            }
            for w in wattages:
                rec[f"{w}W"] = rr.counts.get(w, 0)
            rec["Total Lamps"] = rr.total
            records.append(rec)

    _flush_childless_const()

    watt_col_names = [f"{w}W" for w in wattages]
    cols = ["Corporation", "Zone", "Constituency", "Ward", *watt_col_names, "Total Lamps"]
    ward_df = pd.DataFrame(records, columns=cols) if records else pd.DataFrame(columns=cols)

    parsed_total = int(ward_df["Total Lamps"].sum()) if not ward_df.empty else 0
    if sheet_grand_total == 0:
        sheet_grand_total = parsed_total
    reconciled_ok = parsed_total == sheet_grand_total

    return ParsedSheet(
        tab_name=tab_name,
        report_date=report_date,
        wattages=wattages,
        ward_df=ward_df,
        sheet_grand_total=sheet_grand_total,
        parsed_total=parsed_total,
        reconciled_ok=reconciled_ok,
        source_table_type=table_type,
    )


@dataclass
class RawLampData:
    tab_name: str
    df: pd.DataFrame  # Normalized columns: region, zone, ward, wattage, installed_by, install_dt, pole_type, connection_type, lamp_type, photo, replaced
    total_rows: int
    has_installed_by: bool
    has_dates: bool
    full_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_headers: list[str] = field(default_factory=list)


_EMPTY_CELL_TOKENS = {
    "",
    "nan",
    "none",
    "null",
    "#n/a",
    "n/a",
    "na",
    "#ref!",
    "#value!",
    "#name?",
    "#error!",
    "#div/0!",
    "-",
}

_CONSTITUENCY_TO_CORP_ZONE: dict[str, tuple[str, str]] = {
    "cvramannagar": ("Central", "East"),
    "shanthinagar": ("Central", "East"),
    "shivajinagar": ("Central", "East"),
    "hebbal": ("North", "East"),
    "pulakeshinagar": ("North", "East"),
    "sarvagnanagar": ("North", "East"),
    "bommanahaliz1": ("South", "Bommanahali"),
    "bommanahalliz1": ("South", "Bommanahali"),
    "bommanahali": ("South", "Bommanahali"),
    "bommanahalli": ("South", "Bommanahali"),
}


def _norm_geo_key(val: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (val or "").lower())


def _resolve_corp_and_zone(region: str, constituency: str) -> tuple[str, str]:
    key = _norm_geo_key(constituency)
    if key in _CONSTITUENCY_TO_CORP_ZONE:
        return _CONSTITUENCY_TO_CORP_ZONE[key]
    reg_clean = (region or "").strip() or "Unspecified"
    return reg_clean, reg_clean


def parse_smart_install_date(series: pd.Series) -> pd.Series:
    """Robust parser for mixed date formats in Sheet2.

    Handles:
    - Hyphenated dates: 'DD-MM-YYYY' (e.g. 13-11-2026, 30-01-2026) or 'YYYY-MM-DD'
    - Slashed dates:
      * If part 1 > 12: 'DD/MM/YYYY' (day=part1, month=part2)
      * If part 2 > 12: 'MM/DD/YYYY' (month=part1, day=part2)
      * If both <= 12: standard spreadsheet slashed format is 'MM/DD/YYYY' (e.g. 11/12/2026 -> 12 Nov 2026)
    - Timestamps, NaN, empty strings, and pd.Timestamp objects
    """
    def _parse(val: object):
        if val is None or pd.isna(val):
            return pd.NaT
        if isinstance(val, (pd.Timestamp, pd.DatetimeIndex)):
            return pd.Timestamp(val)
        v = str(val).strip()
        if not v or v.lower() in ("", "nan", "none", "null", "nat", "-"):
            return pd.NaT

        date_part = v.split()[0]

        # Hyphenated: DD-MM-YYYY or YYYY-MM-DD
        m_hy = re.match(r"^(\d{1,4})-(\d{1,2})-(\d{1,4})$", date_part)
        if m_hy:
            p1, p2, p3 = int(m_hy.group(1)), int(m_hy.group(2)), int(m_hy.group(3))
            if p1 > 1000:
                try:
                    return pd.Timestamp(year=p1, month=p2, day=p3)
                except ValueError:
                    return pd.NaT
            y = p3 if p3 > 1000 else (2000 + p3 if p3 < 100 else p3)
            try:
                return pd.Timestamp(year=y, month=p2, day=p1)
            except ValueError:
                return pd.NaT

        # Slashed: DD/MM/YYYY or MM/DD/YYYY
        m_sl = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", date_part)
        if m_sl:
            p1, p2, p3 = int(m_sl.group(1)), int(m_sl.group(2)), int(m_sl.group(3))
            y = p3 if p3 > 1000 else (2000 + p3 if p3 < 100 else p3)
            if p1 > 12:
                try:
                    return pd.Timestamp(year=y, month=p2, day=p1)
                except ValueError:
                    return pd.NaT
            if p2 > 12:
                try:
                    return pd.Timestamp(year=y, month=p1, day=p2)
                except ValueError:
                    return pd.NaT
            # Ambiguous (both <= 12): in Excel/Sheets, slashed format is MM/DD/YYYY
            try:
                return pd.Timestamp(year=y, month=p1, day=p2)
            except ValueError:
                return pd.NaT

        return pd.to_datetime(v, dayfirst=False, errors="coerce")

    return series.apply(_parse)


def parse_raw_lamp_sheet(grid: list[list[str]], tab_name: str = "Sheet2") -> RawLampData | None:
    """Parse row-level Sheet2 lamp log (Region, Zone, Ward, Pole Type, Connection, Lamp ID, Photo, Type, Wattage, Installed By, Installed On, Replaced...)."""
    if not grid or len(grid) < 2:
        return None

    header_idx = None
    for idx in range(min(5, len(grid))):
        lows = [_clean_str(c).lower() for c in grid[idx]]
        hits = sum(
            1
            for token in ("pole id", "lamp id", "wattage", "installed", "ward", "zone", "region")
            if any(token in cell for cell in lows)
        )
        if hits >= 3:
            header_idx = idx
            break

    if header_idx is None:
        return None

    raw_headers = [_clean_str(h) for h in grid[header_idx]]
    data_rows = [r for r in grid[header_idx + 1 :] if any(_clean_str(c) for c in r)]
    if not data_rows:
        return None

    max_len = len(raw_headers)
    padded_rows = [list(r) + [""] * max(0, max_len - len(r)) for r in data_rows]
    padded_rows = [r[:max_len] for r in padded_rows]

    # Deduplicate blank header columns cleanly; expand merged "Photo", "", "" into Photo 1, Photo 2, Photo 3
    export_headers: list[str] = list(raw_headers)
    idx_h = 0
    while idx_h < len(export_headers):
        h_val = export_headers[idx_h]
        if h_val.lower() == "photo" and idx_h + 1 < len(export_headers) and export_headers[idx_h + 1] == "":
            span = 1
            while idx_h + span < len(export_headers) and export_headers[idx_h + span] == "":
                span += 1
            for k in range(span):
                export_headers[idx_h + k] = f"Photo {k + 1}"
            idx_h += span
            continue
        idx_h += 1

    headers: list[str] = []
    seen: dict[str, int] = {}
    for i, h in enumerate(export_headers):
        name = h if h else f"Col_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        headers.append(name)

    raw_df = pd.DataFrame(padded_rows, columns=headers)

    def _find_col(exact_candidates: tuple[str, ...], prefix_candidates: tuple[str, ...] = ()) -> str | None:
        for col in headers:
            if col.lower() in exact_candidates:
                return col
        for col in headers:
            cl = col.lower()
            if any(cl.startswith(p) for p in prefix_candidates):
                return col
        return None

    col_region = _find_col(("region", "corporation", "division"), ("reg", "corp"))
    if not col_region and len(headers) > 0:
        first_col = headers[0]
        sample_vals = raw_df[first_col].astype(str).str.strip().str.lower()
        if sample_vals.isin({"east", "bommanahali", "bommanahalli", "north", "south", "central"}).mean() >= 0.5:
            col_region = first_col
    col_zone = _find_col(("zone", "constituency"), ("zon", "constit"))
    col_ward = _find_col(("ward",), ("ward",))
    col_pole_type = _find_col(("pole type", "pole_type", "pole ty"), ("pole ty", "pole_ty"))
    col_pole_id = _find_col(("pole id", "pole_id", "pole"), ("pole id", "pole_id", "pole"))
    col_location = _find_col(("location", "address"), ("loc", "addr"))
    col_lamp_id = _find_col(("lamp id", "lamp_id", "lamp"), ("lamp id", "lamp_id", "lamp"))
    col_conn = _find_col(("connection type", "connection", "conn"), ("connect",))
    col_lamp_type = _find_col(("type", "lamp type"), ("lamp ty",))
    col_watt = _find_col(("wattage", "watt", "watts"), ("wattag",))
    col_photo = _find_col(("photo", "photo 1", "image 1"), ("photo",))
    col_replaced = _find_col(("replaced", "replaced lamp"), ("replac",))

    # Smart disambiguation of "Installed By" vs "Installed On / Date" (handles truncated headers like "Installe...")
    col_installed_by: str | None = None
    col_installed_on: str | None = None

    install_cols = [
        c for c in headers
        if any(k in c.lower() for k in ("install", "contractor", "vendor", "technician", "date"))
    ]
    for col in install_cols:
        cl = col.lower()
        if any(k in cl for k in ("by", "installer", "contractor", "vendor", "technician", "team")):
            col_installed_by = col_installed_by or col
            continue
        if any(k in cl for k in ("on", "date")):
            # Verify sample values look like dates rather than contractor names
            sample = raw_df[col].astype(str).str.strip()
            sample = sample[sample != ""].head(50)
            if not sample.empty:
                parsed_sample = parse_smart_install_date(sample)
                if parsed_sample.notna().mean() >= 0.5:
                    col_installed_on = col_installed_on or col
                    continue
            else:
                col_installed_on = col_installed_on or col
                continue
        # Ambiguous header (e.g., "Installed..." / "Installe..."): check sample values
        sample = raw_df[col].astype(str).str.strip()
        sample = sample[sample != ""].head(50)
        if not sample.empty:
            parsed_sample = parse_smart_install_date(sample)
            if parsed_sample.notna().mean() >= 0.5:
                col_installed_on = col_installed_on or col
            else:
                col_installed_by = col_installed_by or col

    out = pd.DataFrame(index=raw_df.index)
    out["region"] = raw_df[col_region].astype(str).str.strip() if col_region else "Unspecified"
    out["zone"] = raw_df[col_zone].astype(str).str.strip() if col_zone else "Unspecified"
    out["ward"] = raw_df[col_ward].astype(str).str.strip() if col_ward else "Unspecified"
    out["wattage"] = (
        pd.to_numeric(raw_df[col_watt].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce")
        .round(0)
        .fillna(0)
        .astype(int)
        if col_watt
        else 0
    )
    out["installed_by"] = raw_df[col_installed_by].astype(str).str.strip() if col_installed_by else ""
    out["pole_type"] = raw_df[col_pole_type].astype(str).str.strip() if col_pole_type else ""
    out["connection_type"] = raw_df[col_conn].astype(str).str.strip() if col_conn else ""
    out["lamp_type"] = raw_df[col_lamp_type].astype(str).str.strip() if col_lamp_type else ""
    out["photo"] = raw_df[col_photo].astype(str).str.strip() if col_photo else ""
    out["replaced"] = raw_df[col_replaced].astype(str).str.strip() if col_replaced else ""

    if col_installed_on:
        out["install_dt"] = parse_smart_install_date(raw_df[col_installed_on])
    else:
        out["install_dt"] = pd.NaT

    # Heal missing/empty zone, ward, and region if Location or Pole ID has hints
    empty_zone_mask = out["zone"].astype(str).str.strip().str.lower().isin(_EMPTY_CELL_TOKENS)
    if empty_zone_mask.any():
        for idx in out[empty_zone_mask].index:
            loc = str(raw_df.at[idx, col_location]).lower() if col_location else ""
            pole = str(raw_df.at[idx, col_pole_id]).lower() if col_pole_id else ""
            if "shivaji" in loc or "svjr" in pole:
                out.at[idx, "zone"] = "ShivajiNagar"
                out.at[idx, "region"] = "East"
                if "119" in pole or "119" in loc:
                    out.at[idx, "ward"] = "SVJR-W119"
            elif "sarvagna" in loc or "sn-" in pole:
                out.at[idx, "zone"] = "SarvagnaNagar"
                out.at[idx, "region"] = "East"
            elif "pulakeshi" in loc or "pn-" in pole:
                out.at[idx, "zone"] = "PulakeshiNagar"
                out.at[idx, "region"] = "East"
            elif "hebbal" in loc or "hbl" in pole:
                out.at[idx, "zone"] = "Hebbal"
                out.at[idx, "region"] = "East"
            elif "shanthi" in loc or "snr" in pole:
                out.at[idx, "zone"] = "ShanthiNagar"
                out.at[idx, "region"] = "East"
            elif "raman" in loc or "cvr" in pole:
                out.at[idx, "zone"] = "CVRamanNagar"
                out.at[idx, "region"] = "East"
            elif "bommanahali" in loc or "bmh" in pole:
                out.at[idx, "zone"] = "Bommanahali - Z1"
                out.at[idx, "region"] = "Bommanahali"

    valid_mask = pd.Series(True, index=out.index)
    if col_region:
        valid_mask &= ~out["region"].str.strip().str.lower().isin(_EMPTY_CELL_TOKENS)
    if col_zone:
        valid_mask &= ~out["zone"].str.strip().str.lower().isin(_EMPTY_CELL_TOKENS)
    if col_ward:
        valid_mask &= ~out["ward"].str.strip().str.lower().isin(_EMPTY_CELL_TOKENS)
    out = out[valid_mask].reset_index(drop=True)
    if out.empty:
        return None
    full_df = raw_df.loc[valid_mask].reset_index(drop=True)

    has_installed_by = bool(col_installed_by and (out["installed_by"] != "").any())
    has_dates = bool(out["install_dt"].notna().any())

    return RawLampData(
        tab_name=tab_name,
        df=out,
        total_rows=len(out),
        has_installed_by=has_installed_by,
        has_dates=has_dates,
        full_df=full_df,
        raw_headers=headers,
    )


def _pick_yesterday_target_dt(
    install_dates: pd.Series,
    *,
    reference_today: date | None = None,
) -> pd.Timestamp:
    """Pick yesterday's timestamp if present, else the latest available date <= yesterday."""
    valid = install_dates.dropna().dt.normalize()
    if valid.empty:
        return pd.NaT
    yesterday = pd.Timestamp((reference_today or date.today()) - timedelta(days=1))
    upto = valid[valid <= yesterday]
    if not upto.empty:
        if (upto == yesterday).any():
            return yesterday
        return upto.max()
    return valid.max()


def build_parsed_sheets_from_raw(
    raw_data: RawLampData,
    *,
    reference_today: date | None = None,
    target_date: date | None = None,
) -> tuple[ParsedSheet, ParsedSheet | None]:
    """Synthesize Overall and Yesterday ParsedSheet objects directly from Sheet2 when summary tabs aren't used."""
    df = raw_data.df.copy()
    wattages = sorted(int(w) for w in df["wattage"].unique() if w > 0)

    def _to_ward_df(sub: pd.DataFrame) -> pd.DataFrame:
        if sub.empty:
            cols = ["Corporation", "Zone", "Constituency", "Ward", *[f"{w}W" for w in wattages], "Total Lamps"]
            return pd.DataFrame(columns=cols)
        piv = (
            sub.assign(_cnt=1)
            .pivot_table(
                index=["region", "zone", "ward"],
                columns="wattage",
                values="_cnt",
                aggfunc="sum",
                fill_value=0,
            )
            .reset_index()
        )
        resolved = [
            _resolve_corp_and_zone(str(reg), str(const))
            for reg, const in zip(piv["region"], piv["zone"])
        ]
        piv["Corporation"] = [c for c, _ in resolved]
        piv["Zone"] = [z for _, z in resolved]
        piv = piv.rename(columns={"zone": "Constituency", "ward": "Ward"})
        for w in wattages:
            if w in piv.columns:
                piv[f"{w}W"] = piv[w].astype(int)
            else:
                piv[f"{w}W"] = 0
        w_cols = [f"{w}W" for w in wattages]
        piv["Total Lamps"] = piv[w_cols].sum(axis=1).astype(int)
        return piv[["Corporation", "Zone", "Constituency", "Ward", *w_cols, "Total Lamps"]]

    if target_date is not None:
        latest_dt = pd.Timestamp(target_date)
    else:
        latest_dt = _pick_yesterday_target_dt(df["install_dt"], reference_today=reference_today) if raw_data.has_dates else pd.NaT
    if pd.notna(latest_dt):
        ov_sub = df[df["install_dt"].isna() | (df["install_dt"].dt.normalize() <= latest_dt.normalize())]
    else:
        ov_sub = df
    ov_ward = _to_ward_df(ov_sub)
    ov_total = int(ov_ward["Total Lamps"].sum()) if not ov_ward.empty else 0
    date_label = latest_dt.strftime("%d/%m/%Y") if pd.notna(latest_dt) else raw_data.tab_name

    overall_ps = ParsedSheet(
        tab_name=raw_data.tab_name,
        report_date=date_label,
        wattages=wattages,
        ward_df=ov_ward,
        sheet_grand_total=ov_total,
        parsed_total=ov_total,
        reconciled_ok=True,
        source_table_type="raw_log",
    )

    daily_ps = None
    if pd.notna(latest_dt):
        dy_sub = df[df["install_dt"].dt.normalize() == latest_dt.normalize()]
        dy_ward = _to_ward_df(dy_sub)
        dy_total = int(dy_ward["Total Lamps"].sum()) if not dy_ward.empty else 0
        daily_ps = ParsedSheet(
            tab_name=raw_data.tab_name,
            report_date=latest_dt.strftime("%d/%m/%Y"),
            wattages=sorted(int(w) for w in dy_sub["wattage"].unique() if w > 0),
            ward_df=dy_ward,
            sheet_grand_total=dy_total,
            parsed_total=dy_total,
            reconciled_ok=True,
            source_table_type="raw_log",
        )

    return overall_ps, daily_ps


@dataclass
class InstallerAnalysis:
    total_installers: int = 0
    active_installers_today: int = 0
    active_installers_7d: int = 0
    today_date_label: str = ""
    top_installers_cumulative: pd.DataFrame = field(default_factory=pd.DataFrame)
    today_by_installer: pd.DataFrame = field(default_factory=pd.DataFrame)
    monthly_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    earlier_months_total: int = 0
    earlier_months_label: str = ""
    earliest_month_label: str = ""
    daily_history_from_raw: pd.DataFrame = field(default_factory=pd.DataFrame)
    lamp_type_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    pole_type_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    connection_type_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    photo_missing_count: int = 0
    photo_missing_pct: float = 0.0
    connection_blank_count: int = 0
    replaced_count: int = 0


def analyze_raw_installers(
    raw_data: RawLampData,
    *,
    reference_date_str: str = "",
    reference_today: date | None = None,
) -> InstallerAnalysis:
    df = raw_data.df.copy()
    if df.empty:
        return InstallerAnalysis()

    # Determine target "yesterday" date aligned with daily_tab if possible, else yesterday / latest <= yesterday in Sheet2
    target_dt = pd.NaT
    if reference_date_str:
        parsed_ref = parse_date_sort_key(reference_date_str)
        if parsed_ref != datetime.min:
            target_dt = pd.Timestamp(parsed_ref.date())
    if pd.isna(target_dt) and raw_data.has_dates:
        target_dt = _pick_yesterday_target_dt(df["install_dt"], reference_today=reference_today)

    today_date_label = target_dt.strftime("%d/%m/%Y") if pd.notna(target_dt) else ""

    # Clean installed_by (cap dated rows to target_dt = yesterday so today's partial entries don't skew yesterday's report)
    df_inst = df[df["installed_by"] != ""].copy()
    if pd.notna(target_dt) and raw_data.has_dates:
        inst_day = df_inst["install_dt"].dt.normalize()
        df_inst = df_inst[inst_day.isna() | (inst_day <= target_dt)].copy()
    total_installers = int(df_inst["installed_by"].nunique()) if not df_inst.empty else 0

    if pd.notna(target_dt) and raw_data.has_dates:
        dt_norm = df_inst["install_dt"].dt.normalize()
        today_mask = dt_norm == target_dt
        start_7d = target_dt - timedelta(days=6)
        mask_7d = (dt_norm >= start_7d) & (dt_norm <= target_dt)
    else:
        today_mask = pd.Series(False, index=df_inst.index)
        mask_7d = pd.Series(False, index=df_inst.index)

    active_installers_today = int(df_inst.loc[today_mask, "installed_by"].nunique()) if today_mask.any() else 0
    active_installers_7d = int(df_inst.loc[mask_7d, "installed_by"].nunique()) if mask_7d.any() else 0

    # Cumulative Installer Leaderboard (vectorized for 80k+ rows)
    top_installers = pd.DataFrame()
    if not df_inst.empty:
        df_inst["_is_today"] = today_mask.astype(int)
        df_inst["_is_7d"] = mask_7d.astype(int)

        agg_inst = (
            df_inst.groupby("installed_by", as_index=False)
            .agg(
                **{
                    "Total Lamps": ("installed_by", "size"),
                    "Yesterday": ("_is_today", "sum"),
                    "Last 7 Days": ("_is_7d", "sum"),
                    "Zones": ("zone", "nunique"),
                    "Wards": ("ward", "nunique"),
                    "Last Active": ("install_dt", "max"),
                }
            )
            .rename(columns={"installed_by": "Installed By"})
        )

        # Dominant wattage per installer via crosstab
        if (df_inst["wattage"] > 0).any():
            ct = pd.crosstab(df_inst["installed_by"], df_inst["wattage"])
            top_w_series = ct.idxmax(axis=1).astype(str) + "W"
            top_w_map = top_w_series.to_dict()
            agg_inst["Top Wattage"] = agg_inst["Installed By"].map(top_w_map).fillna("-")
        else:
            agg_inst["Top Wattage"] = "-"

        total_inst_lamps = max(int(agg_inst["Total Lamps"].sum()), 1)
        agg_inst["Share %"] = (agg_inst["Total Lamps"] / total_inst_lamps * 100.0).round(1)
        agg_inst["Last Active"] = agg_inst["Last Active"].dt.strftime("%d-%m-%Y").fillna("-")
        agg_inst = agg_inst.sort_values(
            by=["Total Lamps", "Yesterday", "Installed By"],
            ascending=[False, False, True],
        ).reset_index(drop=True)

        cols_order = [
            "Installed By",
            "Total Lamps",
            "Share %",
            "Yesterday",
            "Last 7 Days",
            "Zones",
            "Wards",
            "Top Wattage",
            "Last Active",
        ]
        top_installers = agg_inst[cols_order]

    # Yesterday by Installer breakdown
    today_by_installer = pd.DataFrame()
    if today_mask.any():
        today_df = df_inst.loc[today_mask].copy()
        t_grp = (
            today_df.groupby("installed_by", as_index=False)
            .agg(
                Yesterday=("installed_by", "size"),
                Zones=("zone", "nunique"),
                Wards=("ward", "nunique"),
            )
            .rename(columns={"installed_by": "Installed By"})
            .sort_values(by=["Yesterday", "Installed By"], ascending=[False, True])
            .reset_index(drop=True)
        )
        t_denom = max(int(t_grp["Yesterday"].sum()), 1)
        t_grp["Share %"] = (t_grp["Yesterday"] / t_denom * 100.0).round(1)
        today_by_installer = t_grp

    # Daily 14-day & Monthly history from raw dates
    daily_history_from_raw = pd.DataFrame()
    monthly_history = pd.DataFrame()
    earlier_months_total = 0
    earlier_months_label = ""
    earliest_month_label = ""

    if raw_data.has_dates:
        dated = df[df["install_dt"].notna()].copy()
        dated["_day"] = dated["install_dt"].dt.normalize()
        if pd.notna(target_dt):
            dated_upto = dated[dated["_day"] <= target_dt].copy()
            if dated_upto.empty:
                dated_upto = dated
        else:
            dated_upto = dated

        # Last 14 calendar days up to end_d
        if not dated_upto.empty:
            end_d = target_dt if pd.notna(target_dt) else dated_upto["_day"].max()
            start_14 = end_d - timedelta(days=13)
            last_14 = dated_upto[(dated_upto["_day"] >= start_14) & (dated_upto["_day"] <= end_d)]
            if not last_14.empty:
                d_grp = (
                    last_14.groupby("_day", as_index=False)
                    .agg(
                        Installed=("_day", "size"),
                        **{
                            "Active Wards": ("ward", "nunique"),
                            "Active Installers": ("installed_by", lambda s: s[s != ""].nunique()),
                        },
                    )
                    .sort_values("_day")
                )
                # Fill calendar day gaps between first day in window and end_d so tail(7) = true last 7 calendar days
                min_d = max(start_14, d_grp["_day"].min())
                full_days = pd.date_range(min_d, end_d, freq="D")
                d_grp = (
                    d_grp.set_index("_day")
                    .reindex(full_days, fill_value=0)
                    .rename_axis("_day")
                    .reset_index()
                )
                d_grp["Date"] = d_grp["_day"].dt.strftime("%d/%m/%Y")
                d_grp["Label"] = d_grp["_day"].dt.strftime("%d %b")
                d_grp["Is Latest"] = d_grp["_day"] == d_grp["_day"].max()
                daily_history_from_raw = d_grp[
                    ["Date", "Label", "Installed", "Active Wards", "Active Installers", "Is Latest"]
                ].reset_index(drop=True)

            # Monthly Installations (last 12 months)
            dated_upto["_ym"] = dated_upto["install_dt"].dt.to_period("M")
            m_grp = (
                dated_upto.groupby("_ym", as_index=False)
                .agg(
                    Installed=("_ym", "size"),
                    **{"Installers Active": ("installed_by", lambda s: s[s != ""].nunique())},
                )
                .sort_values("_ym")
                .reset_index(drop=True)
            )
            if not m_grp.empty:
                earliest_month_label = m_grp.iloc[0]["_ym"].strftime("%b %Y")
                if len(m_grp) > 12:
                    earlier = m_grp.iloc[:-12]
                    earlier_months_total = int(earlier["Installed"].sum())
                    earlier_months_label = (
                        f"{earlier.iloc[0]['_ym'].strftime('%b %Y')}–{earlier.iloc[-1]['_ym'].strftime('%b %Y')}"
                        if len(earlier) > 1
                        else earlier.iloc[0]["_ym"].strftime("%b %Y")
                    )
                    m_grp = m_grp.iloc[-12:].reset_index(drop=True)
                m_grp["Month"] = m_grp["_ym"].astype(str)
                m_grp["Label"] = m_grp["_ym"].dt.strftime("%b %y")
                monthly_history = m_grp[["Month", "Label", "Installed", "Installers Active"]]

    _empty_tokens = {"", "nan", "none", "null"}

    def _cat_breakdown(col_name: str, label: str, top_n: int = 5) -> pd.DataFrame:
        s = df[col_name].astype(str).str.strip()
        s = s[~s.str.lower().isin(_empty_tokens | {"-", "na", "n/a"})]
        if s.empty:
            return pd.DataFrame()
        vc = s.value_counts().reset_index()
        vc.columns = [label, "Lamps"]
        if len(vc) > top_n:
            head_df = vc.iloc[:top_n].copy()
            other_lamps = int(vc.iloc[top_n:]["Lamps"].sum())
            if other_lamps > 0:
                other_row = pd.DataFrame([{label: f"Other ({len(vc) - top_n})", "Lamps": other_lamps}])
                vc = pd.concat([head_df, other_row], ignore_index=True)
            else:
                vc = head_df
        vc["Share %"] = (vc["Lamps"] / max(len(df), 1) * 100.0).round(1)
        return vc

    lamp_type_summary = _cat_breakdown("lamp_type", "Lamp Type", top_n=4)
    pole_type_summary = _cat_breakdown("pole_type", "Pole Type", top_n=5)
    connection_type_summary = _cat_breakdown("connection_type", "Connection Type", top_n=4)

    photo_missing = (
        int(df["photo"].astype(str).str.strip().str.lower().isin(_empty_tokens).sum())
        if "photo" in df.columns
        else 0
    )
    conn_blank = (
        int(df["connection_type"].astype(str).str.strip().str.lower().isin(_empty_tokens | {"missing", "-"}).sum())
        if "connection_type" in df.columns
        else 0
    )
    replaced_cnt = (
        int((~df["replaced"].astype(str).str.strip().str.lower().isin(_empty_tokens | {"-", "none"})).sum())
        if "replaced" in df.columns
        else 0
    )

    return InstallerAnalysis(
        total_installers=total_installers,
        active_installers_today=active_installers_today,
        active_installers_7d=active_installers_7d,
        today_date_label=today_date_label,
        top_installers_cumulative=top_installers,
        today_by_installer=today_by_installer,
        monthly_history=monthly_history,
        earlier_months_total=earlier_months_total,
        earlier_months_label=earlier_months_label,
        earliest_month_label=earliest_month_label,
        daily_history_from_raw=daily_history_from_raw,
        lamp_type_summary=lamp_type_summary,
        pole_type_summary=pole_type_summary,
        connection_type_summary=connection_type_summary,
        photo_missing_count=photo_missing,
        photo_missing_pct=round((photo_missing / max(len(df), 1)) * 100.0, 1),
        connection_blank_count=conn_blank,
        replaced_count=replaced_cnt,
    )


@dataclass
class WardDistributionStats:
    min_lamps: int = 0
    median_lamps: int = 0
    mean_lamps: float = 0.0
    max_lamps: int = 0
    min_ward: str = "-"
    max_ward: str = "-"
    active_wards_pct: float = 0.0
    active_consts_today: int = 0


@dataclass
class LedKPIs:
    overall_total: int = 0
    daily_total: int = 0
    daily_date: str = ""
    overall_date: str = ""
    has_daily: bool = False
    has_history: bool = False
    last_7_days_total: int = 0
    avg_7d_installed: float = 0.0
    avg_daily_installed: float = 0.0
    daily_vs_avg_pct: float = 0.0
    corporations_count: int = 0
    zones_count: int = 0
    constituencies_count: int = 0
    wards_count: int = 0
    daily_wards_count: int = 0
    daily_corps_count: int = 0
    daily_consts_count: int = 0
    top_wattage: str = "-"
    top_wattage_pct: float = 0.0
    overall_reconciled: bool = True
    overall_sheet_grand_total: int = 0
    daily_reconciled: bool = True
    daily_sheet_grand_total: int = 0
    has_installers: bool = False
    active_installers_today: int = 0
    total_installers: int = 0
    earliest_month_label: str = ""


@dataclass
class LedAnalysis:
    kpis: LedKPIs
    wattages: list[int]
    wattage_summary: pd.DataFrame
    corporation_summary: pd.DataFrame
    zone_summary: pd.DataFrame
    constituency_summary: pd.DataFrame
    ward_summary: pd.DataFrame
    daily_corporation_summary: pd.DataFrame
    daily_constituency_summary: pd.DataFrame
    daily_ward_summary: pd.DataFrame
    daily_history: pd.DataFrame
    top_wards: pd.DataFrame
    bottom_wards: pd.DataFrame
    ward_stats: WardDistributionStats
    installer_analysis: InstallerAnalysis | None = None
    insights: list[str] = field(default_factory=list)


def _aggregate_level(
    overall_df: pd.DataFrame,
    daily_df: pd.DataFrame | None,
    group_cols: list[str],
    wattages: list[int],
    include_counts: bool = False,
) -> pd.DataFrame:
    watt_cols = [f"{w}W" for w in wattages]
    if overall_df.empty:
        return pd.DataFrame()

    for wc in watt_cols:
        if wc not in overall_df.columns:
            overall_df[wc] = 0

    agg_spec: dict[str, Any] = {wc: "sum" for wc in watt_cols}
    agg_spec["Total Lamps"] = "sum"

    grp = overall_df.groupby(group_cols, dropna=False, as_index=False).agg(agg_spec)

    if include_counts:
        if "Constituency" not in group_cols and "Constituency" in overall_df.columns:
            c_cnt = overall_df.groupby(group_cols, dropna=False)["Constituency"].nunique().reset_index(name="Constituencies")
            grp = grp.merge(c_cnt, on=group_cols, how="left")
        if "Ward" not in group_cols and "Ward" in overall_df.columns:
            w_cnt = overall_df.groupby(group_cols, dropna=False)["Ward"].nunique().reset_index(name="Wards")
            grp = grp.merge(w_cnt, on=group_cols, how="left")

    grand_total = max(int(grp["Total Lamps"].sum()), 1)
    grp["Share %"] = (grp["Total Lamps"] / grand_total * 100.0).round(1)

    if "Wards" in grp.columns:
        grp["Avg / Ward"] = (grp["Total Lamps"] / grp["Wards"].clip(lower=1)).round(0).astype(int)

    if daily_df is not None and not daily_df.empty:
        d_grp = (
            daily_df.groupby(group_cols, dropna=False, as_index=False)["Total Lamps"]
            .sum()
            .rename(columns={"Total Lamps": "Daily Installed"})
        )
        grp = grp.merge(d_grp, on=group_cols, how="left")
        grp["Daily Installed"] = grp["Daily Installed"].fillna(0).astype(int)
    elif daily_df is not None:
        grp["Daily Installed"] = 0

    grp = grp.sort_values(by=["Total Lamps", *group_cols], ascending=[False] + [True] * len(group_cols)).reset_index(drop=True)
    return grp


def analyze_led_sheets(
    overall_parsed: ParsedSheet,
    daily_parsed: ParsedSheet | None = None,
    *,
    historical_daily_sheets: list[ParsedSheet] | None = None,
    raw_lamp_data: RawLampData | None = None,
    top_wards_limit: int = 10,
    reference_today: date | None = None,
) -> LedAnalysis:
    ov_df = overall_parsed.ward_df.copy()
    has_daily = daily_parsed is not None
    dy_df = daily_parsed.ward_df.copy() if daily_parsed is not None else None

    all_wattages = sorted(
        set(overall_parsed.wattages) | (set(daily_parsed.wattages) if daily_parsed else set())
    )

    overall_total = int(ov_df["Total Lamps"].sum()) if not ov_df.empty else 0
    daily_total = int(dy_df["Total Lamps"].sum()) if (dy_df is not None and not dy_df.empty) else 0
    daily_wards_count = int(dy_df["Ward"].nunique()) if (dy_df is not None and not dy_df.empty) else 0
    daily_corps_count = int(dy_df["Corporation"].nunique()) if (dy_df is not None and not dy_df.empty) else 0
    daily_consts_count = int(dy_df["Constituency"].nunique()) if (dy_df is not None and not dy_df.empty) else 0

    watt_rows: list[dict[str, Any]] = []
    ov_denom = max(overall_total, 1)
    dy_denom = max(daily_total, 1)
    for w in all_wattages:
        col = f"{w}W"
        ov_cnt = int(ov_df[col].sum()) if col in ov_df.columns else 0
        row_d: dict[str, Any] = {
            "Wattage": f"{w} W",
            "Rating (W)": w,
            "Overall Lamps": ov_cnt,
            "Lamp Share %": round((ov_cnt / ov_denom) * 100.0, 1),
        }
        if has_daily:
            dy_cnt = int(dy_df[col].sum()) if (dy_df is not None and col in dy_df.columns) else 0
            row_d["Daily Installed"] = dy_cnt
            row_d["Daily Share %"] = round((dy_cnt / dy_denom) * 100.0, 1) if daily_total > 0 else 0.0
        watt_rows.append(row_d)

    wattage_summary = pd.DataFrame(watt_rows)
    top_wattage = "-"
    top_wattage_pct = 0.0
    if not wattage_summary.empty and overall_total > 0:
        top_w_row = wattage_summary.sort_values("Overall Lamps", ascending=False).iloc[0]
        top_wattage = str(top_w_row["Wattage"])
        top_wattage_pct = float(top_w_row["Lamp Share %"])

    corp_summary = _aggregate_level(ov_df, dy_df, ["Corporation"], all_wattages, include_counts=True)
    zone_summary = _aggregate_level(ov_df, dy_df, ["Zone"], all_wattages, include_counts=True)
    const_summary = _aggregate_level(
        ov_df, dy_df, ["Corporation", "Zone", "Constituency"], all_wattages, include_counts=True
    )
    ward_summary = _aggregate_level(ov_df, dy_df, ["Corporation", "Zone", "Constituency", "Ward"], all_wattages)

    daily_corp_summary = pd.DataFrame()
    daily_const_summary = pd.DataFrame()
    daily_ward_summary = pd.DataFrame()
    if daily_parsed is not None and not daily_parsed.ward_df.empty:
        dy_w = daily_parsed.wattages
        daily_corp_summary = _aggregate_level(daily_parsed.ward_df.copy(), None, ["Corporation"], dy_w, include_counts=True)
        daily_const_summary = _aggregate_level(
            daily_parsed.ward_df.copy(), None, ["Corporation", "Zone", "Constituency"], dy_w, include_counts=True
        )
        daily_ward_summary = _aggregate_level(
            daily_parsed.ward_df.copy(), None, ["Corporation", "Zone", "Constituency", "Ward"], dy_w
        )

    installer_analysis: InstallerAnalysis | None = None
    if raw_lamp_data is not None:
        installer_analysis = analyze_raw_installers(
            raw_lamp_data,
            reference_date_str=daily_parsed.report_date if daily_parsed else "",
            reference_today=reference_today,
        )

    daily_history = pd.DataFrame(columns=["Date", "Label", "Installed", "Active Wards", "Is Latest"])
    has_history = False
    last_7_days_total = 0
    avg_7d_installed = 0.0
    avg_daily_installed = 0.0
    daily_vs_avg_pct = 0.0

    if historical_daily_sheets and len(historical_daily_sheets) > 1:
        hist_rows = []
        sorted_hist = sorted(historical_daily_sheets, key=lambda s: parse_date_sort_key(s.report_date))
        for idx, ps in enumerate(sorted_hist[-14:]):
            dt = parse_date_sort_key(ps.report_date)
            short_lbl = dt.strftime("%d %b") if dt != datetime.min else ps.report_date
            hist_rows.append(
                {
                    "Date": ps.report_date,
                    "Label": short_lbl,
                    "Installed": ps.parsed_total,
                    "Active Wards": int(ps.ward_df["Ward"].nunique()) if not ps.ward_df.empty else 0,
                    "Is Latest": idx == len(sorted_hist[-14:]) - 1,
                }
            )
        daily_history = pd.DataFrame(hist_rows)
        has_history = len(daily_history) > 1
    elif installer_analysis is not None and len(installer_analysis.daily_history_from_raw) > 1:
        daily_history = installer_analysis.daily_history_from_raw.copy()
        has_history = True

    if has_history and not daily_history.empty:
        tail_7 = daily_history.tail(7)
        last_7_days_total = int(tail_7["Installed"].sum())
        avg_7d_installed = round(float(tail_7["Installed"].mean()), 1)
        avg_daily_installed = round(float(daily_history["Installed"].mean()), 1)
        if avg_daily_installed > 0:
            daily_vs_avg_pct = round(((daily_total - avg_daily_installed) / avg_daily_installed) * 100.0, 1)

    top_wards = ward_summary.head(top_wards_limit).reset_index(drop=True)
    bottom_wards = (
        ward_summary.sort_values(by=["Total Lamps", "Ward"], ascending=[True, True])
        .head(top_wards_limit)
        .reset_index(drop=True)
    )

    ward_stats = WardDistributionStats()
    if not ward_summary.empty:
        s = ward_summary["Total Lamps"]
        ward_stats = WardDistributionStats(
            min_lamps=int(s.min()),
            median_lamps=int(round(float(s.median()))),
            mean_lamps=round(float(s.mean()), 1),
            max_lamps=int(s.max()),
            min_ward=f"{ward_summary.loc[s.idxmin(), 'Ward']} ({int(s.min()):,})",
            max_ward=f"{ward_summary.loc[s.idxmax(), 'Ward']} ({int(s.max()):,})",
            active_wards_pct=round((daily_wards_count / max(len(ward_summary), 1)) * 100.0, 1),
            active_consts_today=daily_consts_count,
        )

    kpis = LedKPIs(
        overall_total=overall_total,
        daily_total=daily_total,
        daily_date=daily_parsed.report_date if daily_parsed else "",
        overall_date=overall_parsed.report_date,
        has_daily=has_daily,
        has_history=has_history,
        last_7_days_total=last_7_days_total,
        avg_7d_installed=avg_7d_installed,
        avg_daily_installed=avg_daily_installed,
        daily_vs_avg_pct=daily_vs_avg_pct,
        corporations_count=int(ov_df["Corporation"].nunique()) if not ov_df.empty else 0,
        zones_count=int(ov_df["Zone"].nunique()) if not ov_df.empty else 0,
        constituencies_count=int(ov_df["Constituency"].nunique()) if not ov_df.empty else 0,
        wards_count=int(ov_df["Ward"].nunique()) if not ov_df.empty else 0,
        daily_wards_count=daily_wards_count,
        daily_corps_count=daily_corps_count,
        daily_consts_count=daily_consts_count,
        top_wattage=top_wattage,
        top_wattage_pct=top_wattage_pct,
        overall_reconciled=overall_parsed.reconciled_ok,
        overall_sheet_grand_total=overall_parsed.sheet_grand_total,
        daily_reconciled=daily_parsed.reconciled_ok if daily_parsed else True,
        daily_sheet_grand_total=daily_parsed.sheet_grand_total if daily_parsed else 0,
        has_installers=bool(installer_analysis and installer_analysis.total_installers > 0),
        active_installers_today=installer_analysis.active_installers_today if installer_analysis else 0,
        total_installers=installer_analysis.total_installers if installer_analysis else 0,
        earliest_month_label=installer_analysis.earliest_month_label if installer_analysis else "",
    )

    insights: list[str] = []
    insights.append(
        f"Cumulative installations total {overall_total:,} LED lamps across {kpis.corporations_count} Corporations, "
        f"{kpis.zones_count} Zones, {kpis.constituencies_count} Constituencies, and {kpis.wards_count} Wards."
    )
    if has_daily and daily_parsed is not None:
        if daily_total > 0 and not daily_corp_summary.empty:
            corp_parts = ", ".join(
                f"{r['Corporation']}: {int(r['Total Lamps']):,}"
                for _, r in daily_corp_summary.iterrows()
            )
            insights.append(
                f"Daily snapshot ({daily_parsed.report_date}): {daily_total:,} lamps installed across "
                f"{daily_consts_count} Constituencies and {daily_wards_count} Wards ({ward_stats.active_wards_pct:.1f}% of wards active) — {corp_parts}."
            )
        else:
            insights.append(f"Daily sheet ({daily_parsed.report_date}) recorded 0 newly installed lamps.")

    if installer_analysis and installer_analysis.total_installers > 0 and not installer_analysis.top_installers_cumulative.empty:
        top_inst = installer_analysis.top_installers_cumulative.iloc[0]
        today_inst_msg = ""
        if not installer_analysis.today_by_installer.empty:
            top_today_inst = installer_analysis.today_by_installer.iloc[0]
            today_inst_msg = (
                f" | Yesterday's top installer: {top_today_inst['Installed By']} ({int(top_today_inst['Yesterday']):,} lamps; "
                f"{installer_analysis.active_installers_today} installers active yesterday)."
            )
        insights.append(
            f"Leading installer overall ({installer_analysis.total_installers} total IDs): "
            f"{top_inst['Installed By']} with {int(top_inst['Total Lamps']):,} lamps ({top_inst['Share %']:.1f}%){today_inst_msg}"
        )

    if not corp_summary.empty:
        top_c = corp_summary.iloc[0]
        insights.append(
            f"Largest Corporation: {top_c['Corporation']} with {int(top_c['Total Lamps']):,} lamps ({top_c['Share %']:.1f}% of total)."
        )
    if not const_summary.empty:
        top_cn = const_summary.iloc[0]
        insights.append(
            f"Leading Constituency: {top_cn['Constituency']} ({int(top_cn['Total Lamps']):,} lamps across {int(top_cn['Wards'])} wards, avg {int(top_cn['Avg / Ward']):,}/ward)."
        )
    if not ward_summary.empty:
        insights.append(
            f"Ward count ranges from {ward_stats.min_ward} to {ward_stats.max_ward} (median {ward_stats.median_lamps:,} lamps/ward). "
            f"Most common rating: {top_wattage} ({top_wattage_pct:.1f}%)."
        )

    return LedAnalysis(
        kpis=kpis,
        wattages=all_wattages,
        wattage_summary=wattage_summary,
        corporation_summary=corp_summary,
        zone_summary=zone_summary,
        constituency_summary=const_summary,
        ward_summary=ward_summary,
        daily_corporation_summary=daily_corp_summary,
        daily_constituency_summary=daily_const_summary,
        daily_ward_summary=daily_ward_summary,
        daily_history=daily_history,
        top_wards=top_wards,
        bottom_wards=bottom_wards,
        ward_stats=ward_stats,
        installer_analysis=installer_analysis,
        insights=insights,
    )
