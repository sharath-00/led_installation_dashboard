"""High-Speed Parallel Downloader for Full ThingsBoard Lamp Installation Dataset."""

import argparse
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    s = (lamp_id or "").strip()
    res = {"Manufacturer": "", "Parsed_Wattage": "", "Batch_No": "", "Lamp_Type": ""}
    if not s:
        return res

    parts = s.split("-")
    if len(parts) >= 1:
        res["Manufacturer"] = parts[0].strip()
    if len(parts) >= 2:
        m_w = re.search(r"\d+", parts[1])
        if m_w:
            res["Parsed_Wattage"] = str(int(m_w.group(0)))
    
    m_batch = re.search(r"\b(\d{1,2}/\d{2,4})\b", s)
    if m_batch:
        res["Batch_No"] = m_batch.group(1)

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


def fetch_page_worker(host: str, headers: dict, customer_id: str, page: int, page_size: int = 2000):
    query = {
        "entityFilter": {
            "type": "assetSearchQuery",
            "rootEntity": {"entityType": "CUSTOMER", "id": customer_id},
            "direction": "FROM",
            "maxLevel": 10,
            "fetchLastLevelOnly": False,
            "relationType": "Contains",
            "assetTypes": ["lightPoint"],
        },
        "pageLink": {
            "pageSize": page_size,
            "page": page,
            "sortOrder": {"key": {"type": "ENTITY_FIELD", "key": "createdTime"}, "direction": "DESC"},
        },
        "keyFilters": [],
        "entityFields": [{"type": "ENTITY_FIELD", "key": "name"}, {"type": "ENTITY_FIELD", "key": "createdTime"}],
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
            {"type": "SERVER_ATTRIBUTE", "key": "ilm"},
        ],
    }
    url = f"{host.rstrip('/')}/api/entitiesQuery/find"
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=query, timeout=45)
            if r.status_code == 200:
                data = r.json()
                return page, data.get("data", []), data.get("totalElements", 0)
        except Exception:
            time.sleep(1.0)
    return page, [], 0


def fetch_all_thingsboard_data(
    host: str = DEFAULT_HOST,
    username: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    customer_id: str = BBMP_CUSTOMER_ID,
    page_size: int = 2000,
    max_workers: int = 5,
    output_base: str = "output/ThingsBoard_Total_Lamp_Report",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("=" * 70)
    print("  STARTING TOTAL LAMP INSTALLATION DATA FETCH FROM THINGSBOARD")
    print("=" * 70)
    print(f"Server: {host}")
    print(f"User: {username}")
    print(f"Customer ID: {customer_id}")

    start_time = time.time()
    token = login(host, username, password)
    headers = {"X-Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}

    # Probe Page 0 to get total count
    print("\nProbing initial batch to determine total asset volume...")
    p0, p0_items, total_elements = fetch_page_worker(host, headers, customer_id, 0, page_size)
    if not total_elements:
        raise RuntimeError("Failed to retrieve asset count from ThingsBoard.")

    total_pages = math.ceil(total_elements / page_size)
    print(f"Total LightPoint Assets in ThingsBoard: {total_elements:,}")
    print(f"Total Pages to Fetch: {total_pages} (at {page_size:,} records/page)")
    print(f"Running high-speed concurrent download with {max_workers} worker threads...\n")

    all_raw_items = [None] * total_pages
    all_raw_items[0] = p0_items

    pages_to_fetch = list(range(1, total_pages))
    completed_count = 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetch_page_worker, host, headers, customer_id, p, page_size): p for p in pages_to_fetch}
        for future in as_completed(future_map):
            page_idx, items, _ = future.result()
            all_raw_items[page_idx] = items
            completed_count += 1
            progress_pct = (completed_count / total_pages) * 100
            print(f"  [Progress {progress_pct:5.1f}%] Page {page_idx+1:02d}/{total_pages} fetched ({len(items):,} items)")

    download_time = time.time() - start_time
    total_downloaded = sum(len(x or []) for x in all_raw_items)
    print(f"\nDownload Phase Finished! Retrieved {total_downloaded:,} raw assets in {download_time:.1f}s.")

    # Transformation & Cleaning Phase
    print("\nProcessing, cleaning, and formatting all fields...")
    cleaned_rows = []

    for page_items in all_raw_items:
        if not page_items:
            continue
        for item in page_items:
            attrs = item.get("latest", {}).get("SERVER_ATTRIBUTE", {})
            lamp_id = (attrs.get("lamp", {}).get("value") or "").strip()
            raw_ts = str(attrs.get("installedOn", {}).get("value") or "").strip()
            status_val = (attrs.get("state", {}).get("value") or "").strip()

            # Skip assets with no lamp installed or surveyed without lamp
            if not lamp_id and not raw_ts and status_val != "INSTALLED":
                continue

            installed_date_str = ""
            ts_numeric = 0
            if raw_ts:
                try:
                    ts_num = int(raw_ts)
                    ts_numeric = ts_num
                    if ts_num > 1000000000000:
                        ts_num /= 1000
                    installed_date_str = datetime.fromtimestamp(ts_num).strftime("%d/%m/%Y")
                except Exception:
                    installed_date_str = raw_ts

            loc = attrs.get("preciseLandmark", {}).get("value") or attrs.get("landmark", {}).get("value") or ""
            raw_ward = (attrs.get("wardName", {}).get("value") or "").strip()
            raw_zone = (attrs.get("zoneName", {}).get("value") or "").strip()
            raw_region = (attrs.get("region", {}).get("value") or "").strip()

            corp, zone = _resolve_corp_and_zone(raw_region, raw_zone)
            lamp_meta = parse_lamp_metadata(lamp_id)
            wattage_val = attrs.get("lampWatts", {}).get("value") or lamp_meta["Parsed_Wattage"]
            arm_val = attrs.get("armType", {}).get("value") or attrs.get("poleArmCount", {}).get("value") or "1"

            cleaned_rows.append({
                "Corporation": corp,
                "Region": raw_region.upper() if raw_region else zone,
                "Zone": zone,
                "Constituency": raw_zone or zone,
                "Ward": raw_ward,
                "Location": loc,
                "Pole ID": (attrs.get("poleId", {}).get("value") or "").strip(),
                "Pole Type": attrs.get("poleType", {}).get("value") or "Tubular",
                "Arm Type": arm_val,
                "Connection Type": attrs.get("connectionType", {}).get("value") or "Under Ground",
                "Lamp ID": lamp_id,
                "Lamp Type": lamp_meta["Lamp_Type"],
                "Wattage": wattage_val,
                "Manufacturer": lamp_meta["Manufacturer"],
                "Batch No": lamp_meta["Batch_No"],
                "Installed By": (attrs.get("installedBy", {}).get("value") or "").strip(),
                "Installed On": installed_date_str,
                "Proposed Lamp(W)": attrs.get("proposedLamp", {}).get("value") or attrs.get("proposedWatts", {}).get("value") or "",
                "Status": status_val or "INSTALLED",
                "ILM": attrs.get("ilm", {}).get("value") or "-",
                "Latitude": attrs.get("latitude", {}).get("value") or "",
                "Longitude": attrs.get("longitude", {}).get("value") or "",
                "Raw Timestamp": ts_numeric,
            })

    df_all_installed = pd.DataFrame(cleaned_rows)
    print(f"Total Installed Lamp records extracted: {len(df_all_installed):,}")

    # Deduplication (Keep latest installation for each unique Lamp ID)
    print("Deduplicating multiple entries by Lamp ID (keeping most recent)...")
    if "Raw Timestamp" in df_all_installed.columns:
        df_all_installed = df_all_installed.sort_values(by="Raw Timestamp", ascending=False)
    
    # Filter rows with valid Lamp ID
    df_dedup = df_all_installed.drop_duplicates(subset=["Lamp ID"], keep="first").copy()
    print(f"Total Unique Cleaned Lamps: {len(df_dedup):,} (Removed {len(df_all_installed) - len(df_dedup):,} duplicates)")

    # Save outputs
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    csv_path = out_dir / f"{Path(output_base).name}.csv"
    xlsx_path = out_dir / f"{Path(output_base).name}.xlsx"

    print(f"\nWriting dataset to CSV: {csv_path.resolve()}...")
    df_dedup.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"Writing dataset to Excel: {xlsx_path.resolve()}...")
    df_dedup.to_excel(xlsx_path, index=False)

    total_time = time.time() - start_time
    print("=" * 70)
    print("  FETCH & CLEAN COMPLETED SUCCESSFULLY!")
    print("=" * 70)
    print(f"  * Total Raw Assets in TB:       {total_elements:,}")
    print(f"  * Valid Installed Lamp Rows:     {len(df_all_installed):,}")
    print(f"  * Unique Deduplicated Lamps:     {len(df_dedup):,}")
    print(f"  * Total Columns:                 {len(df_dedup.columns)}")
    print(f"  * Total Execution Time:          {total_time:.1f}s ({total_time/60:.1f} min)")
    print(f"  * Saved CSV File:                {csv_path.resolve()}")
    print(f"  * Saved Excel File:              {xlsx_path.resolve()}")
    print("=" * 70)

    return df_all_installed, df_dedup


if __name__ == "__main__":
    fetch_all_thingsboard_data()

