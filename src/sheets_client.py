from __future__ import annotations

import io
import json
import math
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Tuple

import gspread
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError


SHEET_ID_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
DRIVE_READONLY_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_XLSX_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def extract_spreadsheet_id(url_or_id: str) -> str:
    value = (url_or_id or "").strip()
    if not value:
        return ""
    match = SHEET_ID_PATTERN.search(value)
    if match:
        return match.group(1)
    return value


def get_service_account_email(service_account_path: Path) -> str | None:
    if not service_account_path.exists():
        return None
    try:
        with service_account_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("client_email")
    except Exception:
        return None


def _get_client(service_account_path: Path) -> gspread.Client:
    if not service_account_path.exists():
        raise FileNotFoundError(
            f"Service account file not found at: {service_account_path}"
        )
    return gspread.service_account(filename=str(service_account_path))


def list_accessible_spreadsheets(service_account_path: Path) -> list[dict[str, str]]:
    """List spreadsheets shared with the service account (requires Drive API enabled)."""
    client = _get_client(service_account_path)
    sheets = client.openall()
    return [{"id": s.id, "title": s.title} for s in sheets]


def _format_xlsx_cell(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        if val.hour == 0 and val.minute == 0 and val.second == 0:
            return val.strftime("%d/%m/%Y")
        return val.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return ""
        return str(int(val)) if val.is_integer() else str(val)
    return str(val).strip()


def xlsx_bytes_to_grid(xlsx_bytes: bytes, worksheet_name: str = "") -> Tuple[list[list[str]], str, list[str]]:
    """Read a specific worksheet from raw .xlsx bytes into a 2D string grid cleanly."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True, read_only=True)
    try:
        tab_names = list(wb.sheetnames)
        if not tab_names:
            raise ValueError("Workbook contains no worksheets.")

        if worksheet_name:
            if worksheet_name not in tab_names:
                raise ValueError(
                    f"Worksheet '{worksheet_name}' not found. Available tabs: {', '.join(tab_names)}"
                )
            resolved_tab = worksheet_name
        else:
            overall_guess, _ = auto_pick_tabs(tab_names)
            resolved_tab = overall_guess if overall_guess else tab_names[0]

        ws = wb[resolved_tab]
        grid: list[list[str]] = [
            [_format_xlsx_cell(cell) for cell in row]
            for row in ws.iter_rows(values_only=True)
        ]
        return grid, resolved_tab, tab_names
    finally:
        wb.close()


def _is_office_file_api_error(exc: Exception) -> bool:
    msg = str(exc)
    return (
        "Office file" in msg
        or "not supported for this document" in msg
        or "[400]" in msg
    )


def _fetch_drive_xlsx_entry(service_account_path: Path, file_id: str) -> dict[str, Any]:
    """Download an Excel (.xlsx) spreadsheet from Google Drive using the service account and cache briefly."""
    cache_key = (str(service_account_path.resolve()), file_id)
    now = time.monotonic()
    cached = _XLSX_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now:
        return cached

    if not service_account_path.exists():
        raise FileNotFoundError(f"Service account file not found at: {service_account_path}")

    creds = Credentials.from_service_account_file(str(service_account_path), scopes=DRIVE_READONLY_SCOPES)
    session = AuthorizedSession(creds)

    meta_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=id,name,mimeType&supportsAllDrives=true"
    meta_resp = session.get(meta_url, timeout=30)
    if meta_resp.status_code != 200:
        raise RuntimeError(f"Google Drive metadata lookup failed ({meta_resp.status_code}): {meta_resp.text}")
    meta = meta_resp.json()
    title = re.sub(r"\.xlsx?$", "", str(meta.get("name") or file_id), flags=re.IGNORECASE)

    media_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
    media_resp = session.get(media_url, timeout=120)
    if media_resp.status_code != 200:
        raise RuntimeError(f"Google Drive file download failed ({media_resp.status_code}): {media_resp.text}")

    entry = {
        "expires_at": now + 180.0,
        "title": title,
        "bytes": media_resp.content,
        "grids": {},
        "tab_names": None,
    }
    _XLSX_CACHE[cache_key] = entry
    return entry


def list_worksheets(service_account_path: Path, spreadsheet_id_or_url: str) -> list[str]:
    sheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    if not sheet_id:
        raise ValueError("Please provide a valid Google Sheet URL or Spreadsheet ID.")
    client = _get_client(service_account_path)
    try:
        spreadsheet = client.open_by_key(sheet_id)
        return [ws.title for ws in spreadsheet.worksheets()]
    except APIError as exc:
        if not _is_office_file_api_error(exc):
            raise
        entry = _fetch_drive_xlsx_entry(service_account_path, sheet_id)
        if entry["tab_names"] is None:
            _, _, tab_names = xlsx_bytes_to_grid(entry["bytes"], "")
            entry["tab_names"] = tab_names
        return list(entry["tab_names"])


def _extract_date_from_tab_name(tab_name: str) -> date | None:
    m = re.search(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b", tab_name or "")
    if not m:
        return None
    raw = m.group(1)
    for fmt in ("%d.%m.%y", "%d-%m-%y", "%d/%m/%y", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def find_all_daily_tabs(tab_names: list[str], overall_tab: str = "") -> list[str]:
    """Return all worksheet tabs that look like dated daily lamp installation sheets."""
    return [
        name
        for name in tab_names
        if name != overall_tab
        and not any(kw in name.strip().lower() for kw in ("overall", "till", "cumulative"))
        and (
            "installed" in name.lower()
            or "lamp" in name.lower()
            or bool(re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", name))
        )
    ]


def filter_daily_tabs_upto(tab_names: list[str], cutoff_date: date | None = None) -> list[str]:
    """Keep daily tabs up to cutoff_date (defaults to yesterday) so today's partial entries aren't treated as yesterday's report."""
    target = cutoff_date or (date.today() - timedelta(days=1))
    kept: list[tuple[date, int, str]] = []
    for idx, name in enumerate(tab_names):
        dt = _extract_date_from_tab_name(name)
        if dt is None:
            kept.append((target, idx, name))
        elif dt <= target:
            kept.append((dt, idx, name))
    kept.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in kept]


def auto_pick_raw_tab(
    tab_names: list[str],
    overall_tab: str = "",
    daily_tab: str = "",
) -> str:
    """Locate the raw lamp log tab (e.g. 'Sheet2', 'Lamp Report', 'Raw Data')."""
    base_excluded = {overall_tab, daily_tab}
    non_summary = [t for t in tab_names if t not in base_excluded and "lamp installed" not in t.lower()]
    for kw in ("sheet2", "lamp report", "raw", "log", "detail", "master", "data"):
        for t in non_summary:
            if kw in t.lower():
                return t

    excluded = base_excluded | set(find_all_daily_tabs(tab_names, overall_tab))
    candidates = [t for t in tab_names if t not in excluded]
    return candidates[0] if candidates else ""


def auto_pick_tabs(
    tab_names: list[str],
    *,
    reference_today: date | None = None,
) -> Tuple[str, str]:
    """Infer the Overall cumulative tab and Yesterday's Daily Installed tab from worksheet names."""
    if not tab_names:
        return "", ""

    overall_tab = ""
    daily_tab = ""

    overall_candidates = [
        name
        for name in tab_names
        if any(kw in name.strip().lower() for kw in ("overall", "till", "cumulative"))
    ]
    if overall_candidates:
        ref_today = reference_today or date.today()
        dated_overall = [
            (_extract_date_from_tab_name(name), idx, name)
            for idx, name in enumerate(overall_candidates)
        ]
        valid_dated = [item for item in dated_overall if item[0] is not None and item[0] <= ref_today]
        if valid_dated:
            valid_dated.sort(key=lambda item: (item[0], item[1]))
            overall_tab = valid_dated[-1][2]
        else:
            overall_tab = overall_candidates[-1]

    daily_candidates = find_all_daily_tabs(tab_names, overall_tab)
    if daily_candidates:
        yesterday = (reference_today or date.today()) - timedelta(days=1)
        exact_yesterday = [
            name for name in daily_candidates if _extract_date_from_tab_name(name) == yesterday
        ]
        if exact_yesterday:
            daily_tab = exact_yesterday[-1]
        else:
            upto_yesterday = filter_daily_tabs_upto(daily_candidates, cutoff_date=yesterday)
            daily_tab = upto_yesterday[-1] if upto_yesterday else daily_candidates[-1]

    if not overall_tab:
        overall_tab = tab_names[0]
        if daily_tab == overall_tab:
            daily_tab = ""

    return overall_tab, daily_tab


def fetch_raw_grid(
    service_account_path: Path,
    spreadsheet_id_or_url: str,
    worksheet_name: str = "",
) -> Tuple[list[list[str]], str, str, list[str]]:
    """Fetch raw 2D grid from a Google Sheet or Drive-hosted .xlsx workbook along with title and tab list."""
    sheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    if not sheet_id:
        raise ValueError("Please provide a valid Google Sheet URL or Spreadsheet ID.")

    client = _get_client(service_account_path)
    try:
        spreadsheet = client.open_by_key(sheet_id)
        tab_names = [ws.title for ws in spreadsheet.worksheets()]

        if worksheet_name:
            if worksheet_name not in tab_names:
                raise ValueError(
                    f"Worksheet '{worksheet_name}' not found. Available tabs: {', '.join(tab_names)}"
                )
            ws = spreadsheet.worksheet(worksheet_name)
        else:
            overall_guess, _ = auto_pick_tabs(tab_names)
            ws = spreadsheet.worksheet(overall_guess) if overall_guess else spreadsheet.get_worksheet(0)

        values = ws.get_all_values()
        return values, spreadsheet.title, ws.title, tab_names
    except APIError as exc:
        if not _is_office_file_api_error(exc):
            raise

        entry = _fetch_drive_xlsx_entry(service_account_path, sheet_id)
        if worksheet_name and worksheet_name in entry["grids"]:
            tab_names = list(entry["tab_names"])
            return entry["grids"][worksheet_name], entry["title"], worksheet_name, tab_names

        grid, resolved_tab, tab_names = xlsx_bytes_to_grid(entry["bytes"], worksheet_name)
        entry["tab_names"] = tab_names
        entry["grids"][resolved_tab] = grid
        return grid, entry["title"], resolved_tab, tab_names


def get_sample_grids() -> dict[str, list[list[str]]]:
    """Return raw 2D grids matching the exact structure of the user's Google Sheet tabs."""
    overall_grid = [
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["Count of Lamp ID", "Wattage", "", "", "", "", "", "", "Corporation", "Constituency", "34", "56", "78", "104", "173", "Grand Total"],
        ["Row Labels", "34", "56", "78", "104", "173", "Grand Total", "", "", "Bommanahali", "19823", "4898", "1439", "520", "343", "27023"],
        ["Bommanahali", "19823", "4898", "1439", "520", "343", "27023", "", "South", "Bommanahali - Z1", "19823", "4898", "1439", "520", "343", "27023"],
        ["Bommanahali - Z1", "19823", "4898", "1439", "520", "343", "27023", "", "", "BMH-W202", "976", "312", "61", "92", "28", "1469"],
        ["BMH-W202", "976", "312", "61", "92", "28", "1469", "", "", "BMH-W203", "2586", "781", "347", "19", "17", "3750"],
        ["BMH-W203", "2586", "781", "347", "19", "17", "3750", "", "", "BMH-W204", "1100", "261", "133", "87", "43", "1624"],
        ["BMH-W204", "1100", "261", "133", "87", "43", "1624", "", "", "BMH-W205", "1282", "305", "23", "21", "33", "1664"],
        ["BMH-W205", "1282", "305", "23", "21", "33", "1664", "", "", "BMH-W206", "970", "170", "67", "38", "18", "1263"],
        ["BMH-W206", "970", "170", "67", "38", "18", "1263", "", "", "BMH-W207", "1751", "923", "55", "3", "50", "2782"],
        ["BMH-W207", "1751", "923", "55", "3", "50", "2782", "", "", "BMH-W208", "1815", "482", "249", "69", "22", "2637"],
        ["BMH-W208", "1815", "482", "249", "69", "22", "2637", "", "", "BMH-W209", "2259", "536", "169", "64", "38", "3066"],
        ["BMH-W209", "2259", "536", "169", "64", "38", "3066", "", "", "BMH-W210", "2819", "687", "104", "112", "40", "3762"],
        ["BMH-W210", "2819", "687", "104", "112", "40", "3762", "", "", "BMH-W211", "2336", "375", "209", "6", "42", "2968"],
        ["BMH-W211", "2336", "375", "209", "6", "42", "2968", "", "", "BMH-W212", "1929", "66", "22", "9", "12", "2038"],
        ["BMH-W212", "1929", "66", "22", "9", "12", "2038", "", "", "East", "13196", "11725", "2008", "245", "296", "27470"],
        ["East", "13196", "11725", "2008", "245", "296", "27470", "", "North", "Hebbal", "6135", "3415", "447", "32", "93", "10122"],
        ["CVRamanNagar", "3097", "6843", "1303", "110", "49", "11402", "", "", "HEB-W61", "1327", "597", "134", "6", "23", "2087"],
        ["CVRN-W108", "580", "391", "128", "", "", "1099", "", "", "HEB-W62", "1249", "623", "152", "16", "30", "2070"],
        ["CVRN-W109", "395", "989", "252", "8", "", "1644", "", "", "HEB-W63", "730", "435", "21", "", "4", "1190"],
        ["CVRN-W110", "396", "260", "81", "", "", "737", "", "", "HEB-W64", "873", "601", "7", "1", "4", "1486"],
        ["CVRN-W111", "463", "796", "96", "12", "", "1367", "", "", "HEB-W65", "494", "303", "27", "1", "", "825"],
        ["CVRN-W112", "625", "1258", "146", "18", "8", "2055", "", "", "HEB-W66", "321", "210", "10", "", "", "541"],
        ["CVRN-W113", "128", "1096", "250", "", "14", "1488", "", "", "HEB-W67", "406", "504", "36", "1", "11", "958"],
        ["CVRN-W114", "203", "973", "194", "51", "12", "1433", "", "", "HEB-W68", "735", "142", "60", "7", "21", "965"],
        ["CVRN-W115", "307", "1080", "156", "21", "15", "1579", "", "", "PulakeshiNagar", "3964", "1467", "258", "103", "154", "5946"],
        ["", "", "", "", "", "", "", "", "", "PN-W69", "1195", "457", "74", "14", "25", "1765"],
        ["", "", "", "", "", "", "", "", "", "PN-W70", "508", "176", "27", "3", "", "714"],
        ["", "", "", "", "", "", "", "", "", "PN-W71", "553", "101", "6", "", "", "660"],
        ["", "", "", "", "", "", "", "", "", "PN-W72", "396", "144", "29", "6", "", "575"],
        ["", "", "", "", "", "", "", "", "", "PN-W73", "608", "164", "32", "8", "19", "831"],
        ["", "", "", "", "", "", "", "", "", "PN-W74", "60", "76", "20", "16", "32", "204"],
        ["", "", "", "", "", "", "", "", "", "PN-W75", "644", "349", "70", "56", "78", "1197"],
        ["", "", "", "", "", "", "", "", "East", "CVRamanNagar", "3097", "6843", "1303", "110", "49", "11402"],
        ["", "", "", "", "", "", "", "", "", "CVRN-W108", "580", "391", "128", "", "", "1099"],
        ["", "", "", "", "", "", "", "", "", "CVRN-W109", "395", "989", "252", "8", "", "1644"],
        ["", "", "", "", "", "", "", "", "", "CVRN-W110", "396", "260", "81", "", "", "737"],
        ["", "", "", "", "", "", "", "", "", "CVRN-W111", "463", "796", "96", "12", "", "1367"],
        ["", "", "", "", "", "", "", "", "", "CVRN-W112", "625", "1258", "146", "18", "8", "2055"],
        ["", "", "", "", "", "", "", "", "", "CVRN-W113", "128", "1096", "250", "", "14", "1488"],
        ["", "", "", "", "", "", "", "", "", "CVRN-W114", "203", "973", "194", "51", "12", "1433"],
        ["", "", "", "", "", "", "", "", "", "CVRN-W115", "307", "1080", "156", "21", "15", "1579"],
        ["", "", "", "", "", "", "", "", "", "Grand Total", "33019", "16623", "3447", "765", "639", "54493"],
    ]

    daily_grid = [
        ["", "", "", "", "", "", "", "Installed On", "11/11/2026", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["Count of Lamp ID", "Wattage", "", "", "", "", "", "Corporation", "Constituency", "34", "56", "104", "Grand Total"],
        ["Row Labels", "Grand Total", "", "", "", "", "", "", "Bommanahali", "7", "1", "1", "9"],
        ["Grand Total", "", "", "", "", "", "", "South", "Bommanahali - Z1", "7", "1", "1", "9"],
        ["", "", "", "", "", "", "", "", "BMH-W202", "1", "1", "", "2"],
        ["", "", "", "", "", "", "", "", "BMH-W203", "1", "", "", "1"],
        ["", "", "", "", "", "", "", "", "BMH-W204", "2", "", "", "2"],
        ["", "", "", "", "", "", "", "", "BMH-W206", "2", "", "", "2"],
        ["", "", "", "", "", "", "", "", "BMH-W210", "1", "", "1", "2"],
        ["", "", "", "", "", "", "", "", "East", "7", "5", "", "12"],
        ["", "", "", "", "", "", "", "North", "PulakeshiNagar", "4", "1", "", "5"],
        ["", "", "", "", "", "", "", "", "PN-W71", "1", "", "", "1"],
        ["", "", "", "", "", "", "", "", "PN-W73", "3", "1", "", "4"],
        ["", "", "", "", "", "", "", "", "SarvagnaNagar", "", "4", "", "4"],
        ["", "", "", "", "", "", "", "", "SN-W81", "", "1", "", "1"],
        ["", "", "", "", "", "", "", "", "SN-W84", "", "2", "", "2"],
        ["", "", "", "", "", "", "", "", "SN-W85", "", "1", "", "1"],
        ["", "", "", "", "", "", "", "Central", "ShanthiNagar", "2", "", "", "2"],
        ["", "", "", "", "", "", "", "", "SNTR-W166", "1", "", "", "1"],
        ["", "", "", "", "", "", "", "", "SNTR-W171", "1", "", "", "1"],
        ["", "", "", "", "", "", "", "", "ShivajiNagar", "1", "", "", "1"],
        ["", "", "", "", "", "", "", "", "SVJR-W120", "1", "", "", "1"],
        ["", "", "", "", "", "", "", "", "Grand Total", "14", "6", "1", "21"],
    ]

    sheet2_grid = [
        [
            "Region", "Zone", "Ward", "Pole ID", "Location", "Pole Type", "Pole Arm",
            "Connection Type", "Lamp ID", "Photo", "", "", "Type", "Wattage",
            "Manufacturer", "Batch", "Installed By", "Installed On", "Replaced",
            "Latitude", "Longitude",
        ],
        ["East", "ShivajiNagar", "SVJR-W120", "GBA-SNL-W120-P001", "Main Rd", "RCC", "1", "Overhead", "LEV-0034-101", "Image 1", "Image 2", "Image 3", "SL LED", "34", "LEV", "11/26", "srinathelectrical", "11-11-2026", "SVL - 250", "12.9768", "77.6012"],
        ["East", "ShanthiNagar", "SNTR-W166", "GBA-SNT-W166-P002", "Cross Rd", "RCC", "1", "ABC", "LEV-0034-102", "Image 1", "Image 2", "", "SL LED", "34", "LEV", "11/26", "nithyaelectrical", "11-11-2026", "", "12.9611", "77.5982"],
        ["East", "ShanthiNagar", "SNTR-W171", "GBA-SNT-W171-P003", "Park Ave", "Tubular", "1", "Under Ground", "LEV-0034-103", "Image 1", "", "", "SL LED", "34", "LEV", "11/26", "nithyaelectrical", "11-11-2026", "", "12.9589", "77.6041"],
        ["North", "PulakeshiNagar", "PN-W71", "GBA-PLN-W071-P004", "Mosque Rd", "RCC", "1", "Overhead", "LEV-0034-104", "Image 1", "Image 2", "Image 3", "SL LED", "34", "LEV", "11/26", "shridurga ent.", "11-11-2026", "SVL - 250", "12.9961", "77.6112"],
        ["North", "PulakeshiNagar", "PN-W73", "GBA-PLN-W073-P005", "Tannery Rd", "RCC", "1", "ABC", "LEV-0034-105", "Image 1", "Image 2", "", "SL LED", "34", "LEV", "11/26", "shridurga ent.", "11-11-2026", "", "12.9994", "77.6134"],
        ["North", "PulakeshiNagar", "PN-W73", "GBA-PLN-W073-P006", "Tannery Rd", "RCC", "1", "ABC", "LEV-0034-106", "Image 1", "", "", "SL LED", "34", "LEV", "11/26", "shridurga ent.", "11-11-2026", "", "12.9998", "77.6139"],
        ["North", "PulakeshiNagar", "PN-W73", "GBA-PLN-W073-P007", "Tannery Rd", "Tubular", "1", "Under Ground", "LEV-0056-107", "Image 1", "Image 2", "Image 3", "SL LED", "56", "LEV", "11/26", "Kusmitha1", "11-11-2026", "SVL - 250", "13.0002", "77.6145"],
        ["North", "PulakeshiNagar", "PN-W73", "GBA-PLN-W073-P008", "Benson Town", "RCC", "1", "Overhead", "LEV-0034-108", "", "", "", "SL LED", "34", "LEV", "11/26", "Kusmitha1", "11-11-2026", "", "13.0010", "77.6050"],
        ["North", "SarvagnaNagar", "SN-W81", "GBA-SVN-W081-P009", "Hennur Rd", "Tubular", "1", "ABC", "LEV-0056-109", "Image 1", "Image 2", "", "SL LED", "56", "LEV", "11/26", "sunilmysore1", "11-11-2026", "", "13.0185", "77.6380"],
        ["North", "SarvagnaNagar", "SN-W84", "GBA-SVN-W084-P010", "Kammanahalli", "RCC", "1", "ABC", "LEV-0056-110", "Image 1", "Image 2", "Image 3", "SL LED", "56", "LEV", "11/26", "sunilmysore1", "11-11-2026", "SVL - 250", "13.0155", "77.6410"],
        ["North", "SarvagnaNagar", "SN-W84", "GBA-SVN-W084-P011", "Kammanahalli", "RCC", "1", "Overhead", "LEV-0056-111", "Image 1", "", "", "SL LED", "56", "LEV", "11/26", "sunilmysore2", "11-11-2026", "", "13.0159", "77.6414"],
        ["North", "SarvagnaNagar", "SN-W85", "GBA-SVN-W085-P012", "Banaswadi", "Metal", "1", "Under Ground", "LEV-0056-112", "Image 1", "Image 2", "", "SL LED", "56", "LEV", "11/26", "sunilmysore2", "11-11-2026", "", "13.0091", "77.6462"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W202", "GBA-BMH-W202-P013", "HSR Sec 1", "RCC", "1", "ABC", "LEV-0034-113", "Image 1", "Image 2", "Image 3", "SL LED", "34", "LEV", "11/26", "project_office01", "11-11-2026", "", "12.9121", "77.6446"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W202", "GBA-BMH-W202-P014", "HSR Sec 1", "RCC", "1", "ABC", "LEV-0056-114", "Image 1", "", "", "SL LED", "56", "LEV", "11/26", "project_office01", "11-11-2026", "SVL - 250", "12.9125", "77.6449"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W203", "GBA-BMH-W203-P015", "Begur Rd", "RCC", "1", "Overhead", "LEV-0034-115", "Image 1", "Image 2", "", "SL LED", "34", "LEV", "11/26", "shridurga ent.", "11-11-2026", "", "12.8891", "77.6288"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W204", "GBA-BMH-W204-P016", "Kudlu Gate", "Tubular", "1", "Under Ground", "LEV-0034-116", "Image 1", "Image 2", "Image 3", "SL LED", "34", "LEV", "11/26", "shridurga ent.", "11-11-2026", "", "12.8935", "77.6382"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W204", "GBA-BMH-W204-P017", "Kudlu Gate", "RCC", "1", "Overhead", "LEV-0034-117", "", "", "", "SL LED", "34", "LEV", "11/26", "nithyaelectrical", "11-11-2026", "", "12.8939", "77.6387"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W206", "GBA-BMH-W206-P018", "Madiwala", "RCC", "1", "ABC", "LEV-0034-118", "Image 1", "Image 2", "", "SL LED", "34", "LEV", "11/26", "Kusmitha2", "11-11-2026", "", "12.9226", "77.6174"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W206", "GBA-BMH-W206-P019", "Madiwala", "RCC", "1", "ABC", "LEV-0034-119", "Image 1", "", "", "SL LED", "34", "LEV", "11/26", "Kusmitha2", "11-11-2026", "", "12.9229", "77.6178"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W210", "GBA-BMH-W210-P020", "Silk Board", "Tubular", "2", "Under Ground", "LEV-0104-120", "Image 1", "Image 2", "Image 3", "FL LED", "104", "LEV", "11/26", "srinathelectrical", "11-11-2026", "SVL - 250", "12.9177", "77.6238"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W210", "GBA-BMH-W210-P021", "Silk Board", "RCC", "1", "Overhead", "LEV-0034-121", "Image 1", "Image 2", "", "SL LED", "34", "LEV", "11/26", "srinathelectrical", "11-11-2026", "", "12.9180", "77.6241"],
        # Previous days & months for 14-day + monthly trend + cumulative installer rankings
        ["East", "ShivajiNagar", "SVJR-W121", "GBA-SNL-W121-P1572", "Halasuru", "RCC", "1", "Overhead", "LEV-0056-001", "Image 1", "Image 2", "Image 3", "SL LED", "56", "LEV", "05/26", "srinathelectrical", "10-11-2026", "SVL - 250", "12.9768", "77.6200"],
        ["East", "ShivajiNagar", "SVJR-W121", "GBA-SNL-W121-P1573", "Halasuru", "Tubular", "1", "Under Ground", "LEV-0173-002", "Image 1", "Image 2", "Image 3", "FL LED", "173", "LEV", "12/25", "nithyaelectrical", "10-11-2026", "", "12.9751", "77.6210"],
        ["North", "Hebbal", "HEB-W61", "GBA-HEB-W061-P050", "RT Nagar", "RCC", "1", "ABC", "LEV-0034-003", "Image 1", "", "", "SL LED", "34", "LEV", "03/26", "shridurga ent.", "09-11-2026", "", "13.0210", "77.5960"],
        ["North", "Hebbal", "HEB-W62", "GBA-HEB-W062-P051", "Ganganagar", "RCC", "1", "ABC", "LEV-0056-004", "Image 1", "Image 2", "", "SL LED", "56", "LEV", "03/26", "shridurga ent.", "08-11-2026", "", "13.0180", "77.5890"],
        ["East", "CVRamanNagar", "CVRN-W108", "GBA-CVR-W108-P070", "Indiranagar", "Tubular", "1", "Under Ground", "LEV-0056-005", "Image 1", "Image 2", "Image 3", "SL LED", "56", "LEV", "02/26", "project_office01", "07-11-2026", "SVL - 250", "12.9784", "77.6408"],
        ["East", "CVRamanNagar", "CVRN-W109", "GBA-CVR-W109-P071", "Byappanahalli", "RCC", "1", "Overhead", "LEV-0078-006", "Image 1", "", "", "SL LED", "78", "LEV", "02/26", "Kusmitha1", "06-11-2026", "", "12.9907", "77.6524"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W205", "GBA-BMH-W205-P080", "Garvebhavipalya", "RCC", "1", "ABC", "LEV-0034-007", "Image 1", "Image 2", "", "SL LED", "34", "LEV", "01/26", "sunilmysore1", "05-11-2026", "", "12.8990", "77.6340"],
        ["North", "PulakeshiNagar", "PN-W69", "GBA-PLN-W069-P090", "Frazer Town", "RCC", "1", "Overhead", "LEV-0034-008", "Image 1", "", "", "SL LED", "34", "LEV", "05/26", "shridurga ent.", "18-10-2026", "", "12.9980", "77.6120"],
        ["East", "ShivajiNagar", "SVJR-W121", "GBA-SNL-W121-P091", "Ulsoor", "Tubular", "1", "Under Ground", "LEV-0056-009", "Image 1", "Image 2", "", "SL LED", "56", "LEV", "04/26", "nithyaelectrical", "15-09-2026", "", "12.9810", "77.6290"],
        ["Bommanahali", "Bommanahali - Z1", "BMH-W207", "GBA-BMH-W207-P092", "Hongasandra", "RCC", "1", "ABC", "LEV-0034-010", "Image 1", "", "", "SL LED", "34", "LEV", "02/26", "Kusmitha2", "12-08-2026", "", "12.8970", "77.6290"],
        ["North", "Hebbal", "HEB-W64", "GBA-HEB-W064-P093", "Sanjaynagar", "Metal", "1", "Overhead", "LEV-0056-011", "Image 1", "Image 2", "", "SL LED", "56", "LEV", "01/26", "sunilmysore2", "29-04-2026", "", "13.0350", "77.5790"],
    ]

    return {
        "Overall till - 11.11.2026": overall_grid,
        "11.11.26- Lamp Installed": daily_grid,
        "Sheet2": sheet2_grid,
    }
