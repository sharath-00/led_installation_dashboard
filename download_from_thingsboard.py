"""Download Lamp Installation Report directly from ThingsBoard REST API with ALL report fields."""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from src.analytics import (
    _clean_str,
    _parse_int,
    _resolve_corp_and_zone,
)

DEFAULT_HOST = "https://schnelliot.in"
DEFAULT_USER = "vinoth.joel@schnellenergy.com"
DEFAULT_PASS = "vinoth555"
BBMP_CUSTOMER_ID = "e2119df0-45c3-11f0-94dc-77130b2f47e9"


def parse_lamp_metadata(lamp_id: str) -> dict[str, str]:
    """Extract manufacturer, wattage, batch from lamp ID (e.g. LEV-0173-02-00-09/26-A01588)."""
    s = (lamp_id or "").strip()
    res = {"Manufacturer": "", "Parsed_Wattage": "", "Batch_No": "", "Lamp_Type": ""}
    if not s:
        return res

    # Pattern: MFR-WATTS-TYPE-EXTRA-BATCH-SERIAL
    parts = s.split("-")
    if len(parts) >= 1:
        res["Manufacturer"] = parts[0].strip()
    if len(parts) >= 2:
        m_w = re.search(r"\d+", parts[1])
        if m_w:
            res["Parsed_Wattage"] = str(int(m_w.group(0)))
    
    # Check for batch pattern e.g. 09/26 or 07/25
    m_batch = re.search(r"\b(\d{1,2}/\d{2,4})\b", s)
    if m_batch:
        res["Batch_No"] = m_batch.group(1)

    # Determine lamp type by wattage / prefix
    w = _parse_int(res["Parsed_Wattage"])
    if w in {20, 34, 40, 60, 70, 90, 110, 120}:
        res["Lamp_Type"] = "SL LED"
    elif w in {140, 170, 173, 190, 200, 240}:
        res["Lamp_Type"] = "FL LED"
    else:
        res["Lamp_Type"] = "LED"

    return res


def login(host: str, username: str, password: str) -> str:
    url = f"{host.rstrip('/')}/api/auth/login"
    resp = requests.post(url, json={"username": username, "password": password}, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"ThingsBoard login failed ({resp.status_code}): {resp.text}")
    return resp.json()["token"]


def download_all_report_fields(
    host: str = DEFAULT_HOST,
    username: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    customer_id: str = BBMP_CUSTOMER_ID,
    max_records: int | None = None,
    batch_size: int = 1000,
    installed_only: bool = True,
    start_date: str = "2025-01-01",
    end_date: str | None = None,
    output_path: str = "output/ThingsBoard_Lamp_Installation_Report_2025_to_Current.xlsx",
) -> pd.DataFrame:
    print(f"Logging in to ThingsBoard ({host}) as {username}...")
    token = login(host, username, password)
    headers = {
        "X-Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    start_dt = pd.to_datetime(start_date) if start_date else None
    end_dt = pd.to_datetime(end_date) if end_date else datetime.now()
    if start_dt:
        print(f"Filtering installations from {start_dt.strftime('%d/%m/%Y')} to {end_dt.strftime('%d/%m/%Y')}...")

    base_query = {
        "entityFilter": {
            "type": "assetSearchQuery",
            "rootEntity": {
                "entityType": "CUSTOMER",
                "id": customer_id,
            },
            "direction": "FROM",
            "maxLevel": 10,
            "fetchLastLevelOnly": False,
            "relationType": "Contains",
            "assetTypes": ["lightPoint"],
        },
        "pageLink": {
            "pageSize": batch_size,
            "page": 0,
            "sortOrder": {
                "key": {"type": "ENTITY_FIELD", "key": "createdTime"},
                "direction": "DESC",
            },
        },
        "keyFilters": [],
        "entityFields": [
            {"type": "ENTITY_FIELD", "key": "name"},
            {"type": "ENTITY_FIELD", "key": "createdTime"},
        ],
        "latestValues": [
            {"type": "SERVER_ATTRIBUTE", "key": "wardName"},
            {"type": "SERVER_ATTRIBUTE", "key": "poleId"},
            {"type": "SERVER_ATTRIBUTE", "key": "lamp"},
            {"type": "SERVER_ATTRIBUTE", "key": "state"},
            {"type": "SERVER_ATTRIBUTE", "key": "installedOn"},
            {"type": "SERVER_ATTRIBUTE", "key": "installedBy"},
            {"type": "SERVER_ATTRIBUTE", "key": "lampWatts"},
            {"type": "SERVER_ATTRIBUTE", "key": "zoneName"},
            {"type": "SERVER_ATTRIBUTE", "key": "region"},
            {"type": "SERVER_ATTRIBUTE", "key": "preciseLandmark"},
            {"type": "SERVER_ATTRIBUTE", "key": "landmark"},
            {"type": "SERVER_ATTRIBUTE", "key": "poleType"},
            {"type": "SERVER_ATTRIBUTE", "key": "armType"},
            {"type": "SERVER_ATTRIBUTE", "key": "poleArmCount"},
            {"type": "SERVER_ATTRIBUTE", "key": "connectionType"},
            {"type": "SERVER_ATTRIBUTE", "key": "proposedLamp"},
            {"type": "SERVER_ATTRIBUTE", "key": "proposedWatts"},
            {"type": "SERVER_ATTRIBUTE", "key": "latitude"},
            {"type": "SERVER_ATTRIBUTE", "key": "longitude"},
            {"type": "SERVER_ATTRIBUTE", "key": "accuracy"},
            {"type": "SERVER_ATTRIBUTE", "key": "ilm"},
            {"type": "SERVER_ATTRIBUTE", "key": "auditImg"},
            {"type": "SERVER_ATTRIBUTE", "key": "img1"},
            {"type": "SERVER_ATTRIBUTE", "key": "img2"},
            {"type": "SERVER_ATTRIBUTE", "key": "img3"},
            {"type": "SERVER_ATTRIBUTE", "key": "photoUrls"},
        ],
    }

    rows = []
    page = 0
    has_next = True
    start_time = time.time()
    total_elements = None

    print(f"Beginning download of all Lamp Installation Report fields from ThingsBoard...")

    while has_next:
        base_query["pageLink"]["page"] = page
        url = f"{host.rstrip('/')}/api/entitiesQuery/find"
        
        t0 = time.time()
        resp = requests.post(url, headers=headers, json=base_query, timeout=45)
        if resp.status_code != 200:
            print(f"Error fetching page {page}: {resp.status_code} - {resp.text[:200]}")
            break

        data = resp.json()
        if total_elements is None:
            total_elements = data.get("totalElements", 0)
            print(f"Total matching assets in ThingsBoard: {total_elements:,}")

        items = data.get("data", [])
        if not items:
            break

        for item in items:
            attrs = item.get("latest", {}).get("SERVER_ATTRIBUTE", {})
            lamp_id = (attrs.get("lamp", {}).get("value") or "").strip()
            raw_ts = attrs.get("installedOn", {}).get("value") or ""
            
            # If installed_only, skip uninstalled assets
            if installed_only and not lamp_id and not raw_ts:
                continue

            # Format timestamp to readable date
            installed_date_str = ""
            if raw_ts:
                try:
                    ts_num = int(str(raw_ts).strip())
                    if ts_num > 1000000000000:
                        ts_num /= 1000
                    installed_date_str = datetime.fromtimestamp(ts_num).strftime("%d/%m/%Y")
                except Exception:
                    installed_date_str = str(raw_ts)

            # Extract location string
            loc = attrs.get("preciseLandmark", {}).get("value") or attrs.get("landmark", {}).get("value") or ""

            # Extract ward, zone, region
            raw_ward = attrs.get("wardName", {}).get("value") or ""
            raw_zone = attrs.get("zoneName", {}).get("value") or ""
            raw_region = attrs.get("region", {}).get("value") or ""

            corp, zone = _resolve_corp_and_zone(raw_region, raw_zone)

            # Parse lamp ID metadata
            lamp_meta = parse_lamp_metadata(lamp_id)
            wattage_val = attrs.get("lampWatts", {}).get("value") or lamp_meta["Parsed_Wattage"]

            # Arm type / pole arm count
            arm_val = attrs.get("armType", {}).get("value") or attrs.get("poleArmCount", {}).get("value") or "1"

            # Images
            img1 = attrs.get("img1", {}).get("value") or attrs.get("auditImg", {}).get("value") or ""
            img2 = attrs.get("img2", {}).get("value") or ""
            img3 = attrs.get("img3", {}).get("value") or ""

            # Filter by date (Jan 1, 2025 to Current Date)
            if start_dt and installed_date_str:
                try:
                    row_dt = datetime.strptime(installed_date_str, "%d/%m/%Y")
                    if row_dt < start_dt or row_dt > end_dt:
                        continue
                except Exception:
                    pass

            # All Report Columns matching the Looker Studio / Sheet2 dashboard
            row = {
                "Corporation": corp,
                "Region": raw_region.upper() if raw_region else zone,
                "Zone": zone,
                "Constituency": raw_zone,
                "Ward": raw_ward,
                "Location": loc,
                "Pole ID": attrs.get("poleId", {}).get("value") or "",
                "Pole Type": attrs.get("poleType", {}).get("value") or "Tubular",
                "Arm Type": arm_val,
                "Connection Type": attrs.get("connectionType", {}).get("value") or "Under Ground",
                "Lamp ID": lamp_id,
                "Lamp Type": lamp_meta["Lamp_Type"],
                "Wattage": wattage_val,
                "Manufacturer": lamp_meta["Manufacturer"],
                "Batch No": lamp_meta["Batch_No"],
                "Installed By": attrs.get("installedBy", {}).get("value") or "",
                "Installed On": installed_date_str,
                "Proposed Lamp(W)": attrs.get("proposedLamp", {}).get("value") or attrs.get("proposedWatts", {}).get("value") or "",
                "Status": attrs.get("state", {}).get("value") or "INSTALLED",
                "ILM": attrs.get("ilm", {}).get("value") or "-",
                "Latitude": attrs.get("latitude", {}).get("value") or "",
                "Longitude": attrs.get("longitude", {}).get("value") or "",
                "Image 1": img1,
                "Image 2": img2,
                "Image 3": img3,
                "Raw Timestamp": raw_ts,
            }
            rows.append(row)

        elapsed = time.time() - t0
        page += 1
        has_next = data.get("hasNext", False)
        print(f"  Page {page:02d} fetched ({len(items)} items in {elapsed:.1f}s) | Valid Lamp Installations: {len(rows):,}")

        if max_records and len(rows) >= max_records:
            rows = rows[:max_records]
            break

    total_time = time.time() - start_time
    print(f"\nDownload completed! Collected {len(rows):,} records across all fields in {total_time:.1f}s.")

    df = pd.DataFrame(rows)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.suffix.lower() == ".csv":
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
    else:
        df.to_excel(out_path, index=False)

    print(f"Saved complete Lamp Installation Report to: {out_path.resolve()} ({len(df):,} rows, {len(df.columns)} columns)")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download all fields from ThingsBoard Lamp Installation Report")
    parser.add_argument("--limit", type=int, default=2000, help="Maximum number of records to download (0 for all)")
    parser.add_argument("--start-date", default="2025-01-01", help="Start date (YYYY-MM-DD), default: 2025-01-01")
    parser.add_argument("--end-date", default=None, help="End date (YYYY-MM-DD), default: current date")
    parser.add_argument("--output", default="output/ThingsBoard_Lamp_Report_2025_to_Current.xlsx", help="Output file path (.xlsx or .csv)")
    parser.add_argument("--all", action="store_true", help="Download all records without limit")
    args = parser.parse_args()

    limit = None if args.all or args.limit == 0 else args.limit
    download_all_report_fields(
        max_records=limit,
        start_date=args.start_date,
        end_date=args.end_date,
        output_path=args.output,
    )
