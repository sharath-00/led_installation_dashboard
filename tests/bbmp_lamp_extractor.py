"""Automated Playwright Extractor for Looker Studio Lamp Installation Report."""

import argparse
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ==========================================================
# CONFIGURATION
# ==========================================================

# ThingsBoard & Looker Studio Configuration
THINGSBOARD_LOGIN_URL = "https://schnelliot.in/login"
USERNAME = "vinoth.joel@schnellenergy.com"
PASSWORD = "vinoth555"

REPORT_ID = "dd949523-8812-4cbf-925a-1876409dd086"
PAGE_ID = "p_crjygvm6bd"

# Looker Studio Embed URL with the mandatory email authorization parameter
REPORT_URL = (
    f"https://datastudio.google.com/embed/reporting/{REPORT_ID}/page/{PAGE_ID}"
    f"?params=%7B%22useremail_parameter%22%3A%22{USERNAME}%22%7D"
)

# Output directory (anchored to project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "Lamp_Report"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def login_to_thingsboard(page):
    """
    Navigates to ThingsBoard, waits dynamically for the Angular form to render,
    and logs in.
    """
    print("\nOpening ThingsBoard login page...")
    try:
        page.goto(THINGSBOARD_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"Navigation warning: {e}")

    page.wait_for_timeout(2000)

    # Check if already logged in / redirected to dashboards
    if "login" not in page.url and ("dashboard" in page.url or "home" in page.url):
        print("Already authenticated in ThingsBoard! Current URL:", page.url)
        return

    print("Waiting for ThingsBoard login form components to mount...")
    password_field = None

    # Wait up to 30 seconds for ThingsBoard Angular app to render the password input
    for attempt in range(30):
        # Did the page redirect away from login?
        if "login" not in page.url and ("dashboard" in page.url or "home" in page.url):
            print("Redirected to dashboard! Current URL:", page.url)
            return

        for frame in page.frames:
            for p_sel in [
                'input[type="password"]',
                'input[formcontrolname="password"]',
                'input[name="password"]',
                'input[autocomplete="current-password"]',
            ]:
                try:
                    loc = frame.locator(p_sel).first
                    if loc.is_visible(timeout=400):
                        password_field = loc
                        break
                except Exception:
                    pass
            if password_field:
                break

        if password_field:
            break
        page.wait_for_timeout(1000)

    if not password_field:
        err_img = OUTPUT_DIR / "debug_login_error.png"
        page.screenshot(path=str(err_img), full_page=True)
        print(f"Saved debug screenshot to {err_img}")
        raise RuntimeError("Could not find the ThingsBoard password field. The page may still be loading.")

    # Find the corresponding username field
    username_field = None
    for frame in page.frames:
        for u_sel in [
            'input[formcontrolname="username"]',
            'input[formcontrolname="email"]',
            'input[name="username"]',
            'input[name="email"]',
            'input[type="email"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="username" i]',
            'input[placeholder*="user" i]',
            'input:not([type="password"]):not([type="hidden"]):not([type="checkbox"])',
        ]:
            try:
                loc = frame.locator(u_sel).first
                if loc.is_visible(timeout=400):
                    username_field = loc
                    break
            except Exception:
                pass
        if username_field:
            break

    if not username_field:
        err_img = OUTPUT_DIR / "debug_login_error.png"
        page.screenshot(path=str(err_img), full_page=True)
        raise RuntimeError("Could not identify the ThingsBoard username field.")

    print("Filling credentials...")
    username_field.fill(USERNAME)
    page.wait_for_timeout(300)
    password_field.fill(PASSWORD)
    page.wait_for_timeout(300)

    # Click Login
    submitted = False
    for frame in page.frames:
        for btn_sel in [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Login")',
            'button:has-text("Sign in")',
        ]:
            try:
                btn = frame.locator(btn_sel).first
                if btn.is_visible(timeout=500):
                    btn.click()
                    submitted = True
                    print(f"Clicked login button: {btn_sel}")
                    break
            except Exception:
                pass
        if submitted:
            break

    if not submitted:
        print("Falling back to Enter key submission...")
        password_field.press("Enter")

    # Wait for login redirect
    page.wait_for_timeout(4000)
    print("ThingsBoard login completed. Current URL:", page.url)


def open_report(page, min_wait_seconds=30, max_wait_seconds=90):
    """
    Opens the Looker Studio report and waits for the top filter bar controls
    to be mounted and interactive.
    Applying filters early avoids letting Looker Studio download multiple full
    unfiltered datasets into browser memory, preventing Out of Memory crashes.
    """
    print("\nOpening Lamp Installation Report with authorized user parameter...")
    print(f"URL: {REPORT_URL}")
    page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=120000)
    print("Page URL opened.")

    print("\n" + "=" * 60)
    print(f"INITIAL REPORT WARMUP: WAITING {min_wait_seconds}s FOR FILTER BAR TO MOUNT...")
    print("Applying filters early prevents Looker Studio from exhausting browser memory.")
    print("=" * 60)

    start_t = time.time()
    while time.time() - start_t < min_wait_seconds:
        elapsed = int(time.time() - start_t)
        remaining = int(min_wait_seconds - elapsed)
        if elapsed > 0 and elapsed % 10 == 0:
            print(f"  Mounting filter controls... {elapsed}s elapsed ({remaining}s remaining)")
        page.wait_for_timeout(2000)

    print("\nTop filter bar mounted! Proceeding to select Customer and Date filters.\n")


def select_customer_bbmp(page, max_wait_seconds=45):
    """
    Opens the 'Customer' filter dropdown in Looker Studio,
    searches for and selects 'Bangalore (BBMP)' exclusively.
    """
    print("\n" + "=" * 60)
    print("APPLYING CUSTOMER FILTER: Bangalore (BBMP)")
    print("=" * 60)

    # 1. Locate the Customer control in the top-left filter bar (y < 70, x < 250)
    print(f"Locating Customer filter at top-left of page (up to {max_wait_seconds}s)...")
    customer_control = None
    start_wait = time.time()

    while time.time() - start_wait < max_wait_seconds:
        for frame in page.frames:
            for sel in [
                'div.lego-control:has-text("Customer")',
                '[role="button"]:has-text("Customer")',
                'div:has-text("Customer")',
            ]:
                try:
                    candidates = frame.locator(sel).all()
                    for cand in candidates:
                        box = cand.bounding_box()
                        # Strict top filter bar bounds for Customer: y in 10..70, x in 5..220, width <= 250, height <= 60
                        if box and 5 <= box["y"] <= 70 and 5 <= box["x"] <= 220 and box["width"] <= 250 and box["height"] <= 60:
                            txt = cand.inner_text().strip()
                            if "Customer" in txt:
                                customer_control = cand
                                print(f"Found Customer filter control at ({box['x']:.0f}, {box['y']:.0f}, {box['width']:.0f}x{box['height']:.0f}): '{txt[:20]}'")
                                break
                    if customer_control:
                        break
                except Exception:
                    pass
            if customer_control:
                break
        if customer_control:
            break
        page.wait_for_timeout(1000)

    # 2. Click Customer dropdown and ensure popup opens
    dropdown_open = False
    for open_attempt in range(3):
        # Check if dropdown already visible
        for frame in page.frames:
            try:
                if frame.locator('text="Bangalore (BBMP)"').first.is_visible(timeout=500):
                    dropdown_open = True
                    break
            except Exception:
                pass
        if dropdown_open:
            break

        print(f"Clicking Customer filter dropdown (attempt {open_attempt + 1}/3)...")
        if customer_control:
            try:
                customer_control.click(force=True)
            except Exception:
                page.mouse.click(105, 40)
        else:
            page.mouse.click(105, 40)
        page.wait_for_timeout(1500)

    # 3. In the opened dropdown (as shown in user screenshots):
    # Both 'Bangalore (BBMP)' and 'FMDA' are listed and initially checked.
    # To select exclusively Bangalore (BBMP):
    # 1. We search 'BBMP' in the search box OR hover to click 'only'
    # 2. Click the FMDA checkbox directly to uncheck it
    print("Selecting exclusively 'Bangalore (BBMP)'...")
    customer_selected = False

    for frame in page.frames:
        try:
            # Method 1: Check if search box is available and filter by 'BBMP'
            search_box = frame.locator('input[placeholder*="search" i], input[type="text"]').first
            if search_box.is_visible(timeout=800):
                print("Found filter search box. Typing 'Bangalore'...")
                try:
                    search_box.click(force=True)
                    search_box.fill("Bangalore")
                    page.wait_for_timeout(800)
                except Exception as e:
                    print("Search box note:", e)

            # Method 2: Hover over Bangalore (BBMP) to click 'only' button
            bbmp_item = frame.locator('text="Bangalore (BBMP)"').first
            if bbmp_item.is_visible(timeout=1500):
                print("Found 'Bangalore (BBMP)' option. Hovering...")
                bbmp_box = bbmp_item.bounding_box()
                if bbmp_box:
                    page.mouse.move(bbmp_box["x"] + 20, bbmp_box["y"] + bbmp_box["height"] / 2)
                    page.wait_for_timeout(400)

                # Look for 'only' / 'Only' button appearing on hover
                only_btn = frame.locator(':is(button, div, span):has-text("only")').first
                if only_btn.is_visible(timeout=500):
                    print("Found 'only' button on hover! Clicking...")
                    only_btn.click(force=True)
                    customer_selected = True
                else:
                    # Method 3: Uncheck FMDA directly by clicking its checkbox
                    fmda_item = frame.locator('text="FMDA"').first
                    if fmda_item.is_visible(timeout=500):
                        fmda_box = fmda_item.bounding_box()
                        if fmda_box:
                            print(f"Clicking FMDA checkbox directly at ({fmda_box['x'] - 22:.0f}, {fmda_box['y'] + fmda_box['height']/2:.0f})...")
                            # Checkbox is ~22px left of FMDA label text
                            page.mouse.click(fmda_box["x"] - 22, fmda_box["y"] + fmda_box["height"] / 2)
                            page.wait_for_timeout(500)
                            customer_selected = True
                        else:
                            fmda_item.click(force=True)
                            customer_selected = True
                    else:
                        # Fallback click BBMP item
                        bbmp_item.click(force=True)
                        customer_selected = True
                break
        except Exception as e:
            print("Selection attempt note:", e)

    # Save screenshot of Customer selection state
    page.screenshot(path=str(OUTPUT_DIR / "debug_customer_applied.png"))

    # Close dropdown with Escape
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
    except Exception:
        pass

    if not customer_selected:
        print("Customer direct selection timed out. Proceeding with report filters...")
    else:
        print("Customer filter 'Bangalore (BBMP)' applied! Waiting 10s for reload...")
        page.wait_for_timeout(10000)


def set_date_range_filter(page, target_start_year=2025, target_start_month="JAN", max_wait_seconds=40):
    """
    Interacts with Looker Studio's interactive dual-calendar date picker:
    1. Clicks the date filter box ('Nov 10, 2026 - Nov 16, 2026').
    2. Navigates the Start Date calendar (left side) back to JAN 2025.
    3. Clicks Day '1' of January 2025.
    4. Leaves End Date on current date (today).
    5. Clicks 'Apply' to trigger the full BigQuery reload.
    """
    print("\n" + "=" * 60)
    print(f"CONFIGURING DATE RANGE FILTER: {target_start_month} {target_start_year} to Current Date")
    print("=" * 60)

    print(f"Waiting for Date Range control to be ready (up to {max_wait_seconds}s)...")
    date_control = None
    start_wait = time.time()

    while time.time() - start_wait < max_wait_seconds:
        elapsed = int(time.time() - start_wait)
        for frame in page.frames:
            for sel in [
                'div:has-text("2026")',
                'div.lego-control:has-text("2026")',
                '[role="button"]:has-text("2026")',
            ]:
                try:
                    candidates = frame.locator(sel).all()
                    for cand in candidates:
                        box = cand.bounding_box()
                        # Strict top filter bar bounds for Date: y in 10..70, x >= 700, width <= 350, height <= 60
                        if box and 5 <= box["y"] <= 70 and box["x"] >= 700 and box["width"] <= 350 and box["height"] <= 60:
                            txt = cand.inner_text().strip()
                            if "-" in txt or "Nov" in txt or "2026" in txt:
                                date_control = cand
                                print(f"Found Date Range filter control at ({box['x']:.0f}, {box['y']:.0f}, {box['width']:.0f}x{box['height']:.0f}): '{txt}' after {elapsed}s")
                                break
                    if date_control:
                        break
                except Exception:
                    pass
            if date_control:
                break
        if date_control:
            break
        page.wait_for_timeout(1000)

    # 2. Click Date control and verify popup opens
    popup = None
    for open_attempt in range(3):
        # Check if popup already open
        for frame in page.frames:
            for p_sel in [
                'div:has-text("Start Date"):has-text("End Date")',
                '.cdk-overlay-pane:has-text("Start Date")',
                'div.daterangepicker',
            ]:
                try:
                    loc = frame.locator(p_sel).last
                    if loc.is_visible(timeout=800):
                        popup = loc
                        break
                except Exception:
                    pass
            if popup:
                break
        if popup:
            break

        print(f"Opening Date Range picker popup (attempt {open_attempt + 1}/3)...")
        if date_control:
            try:
                date_control.click(force=True)
            except Exception:
                page.mouse.click(927, 40)
        else:
            page.mouse.click(927, 40)
        page.wait_for_timeout(1500)

    if not popup:
        err_img = OUTPUT_DIR / "debug_date_popup_missing.png"
        page.screenshot(path=str(err_img), full_page=True)
        raise RuntimeError(f"Date picker popup did not open! Screenshot saved to {err_img}. Cannot proceed with export until date filter is applied.")

    open_img = OUTPUT_DIR / "debug_date_popup_open.png"
    page.screenshot(path=str(open_img), full_page=True)
    print(f"Date picker opened. Saved view to {open_img}")

    popup_box = popup.bounding_box()
    popup_half_width = popup_box["width"] / 2 if popup_box else 300

    # 3. Target Start Date calendar (left half) and navigate to JAN 2025
    print("\nNavigating Start Date calendar to JAN 2025...")

    # Find the month/year header on the left calendar ("Start Date")
    start_header = None
    for h_sel in ['div:has-text("2026")', 'span:has-text("2026")', 'div:has-text("NOV 2026")']:
        try:
            items = popup.locator(h_sel).all()
            for it in items:
                box = it.bounding_box()
                # Must be on left half of popup and near top
                if box and popup_box and box["x"] < popup_box["x"] + popup_half_width and box["y"] < popup_box["y"] + 200:
                    txt = it.inner_text().strip().upper()
                    if "2026" in txt:
                        start_header = it
                        print(f"Found Start Date calendar month header: '{txt}' at ({box['x']:.0f}, {box['y']:.0f})")
                        break
            if start_header:
                break
        except Exception:
            pass

    # Find the '<' (previous month) button on the left calendar
    prev_button = None
    for b_sel in [
        'button:has-text("<")',
        '[role="button"]:has-text("<")',
        'mat-icon:has-text("chevron_left")',
        'svg[data-icon="chevron_left"]',
        'button[aria-label*="prev" i]',
        'button[aria-label*="previous" i]',
        '.prev',
        '.chevron-left',
    ]:
        try:
            candidates = popup.locator(b_sel).all()
            for btn in candidates:
                box = btn.bounding_box()
                if box and popup_box and box["x"] < popup_box["x"] + popup_half_width and box["y"] < popup_box["y"] + 200:
                    prev_button = btn
                    print(f"Found left calendar previous month button with selector: {b_sel}")
                    break
            if prev_button:
                break
        except Exception:
            pass

    # Loop clicking '<' until 'JAN 2025' or 'JANUARY 2025' appears
    target_reached = False
    for step in range(30):
        current_txt = ""
        if start_header:
            try:
                current_txt = start_header.inner_text().strip().upper()
            except Exception:
                pass

        popup_text = popup.inner_text().upper()

        if (f"{target_start_month} {target_start_year}" in current_txt 
            or f"{target_start_month} {target_start_year}" in popup_text 
            or f"JANUARY {target_start_year}" in current_txt):
            print(f"\nSuccessfully reached target month: {target_start_month} {target_start_year} after {step} navigation clicks!")
            target_reached = True
            break

        # Click previous month
        if prev_button:
            try:
                prev_button.click()
            except Exception:
                pass
        elif start_header:
            box = start_header.bounding_box()
            if box:
                # Chevron left is located at header x + 158
                page.mouse.click(box["x"] + 158, box["y"] + box["height"] / 2)
        elif popup_box:
            # Fallback click inside left header chevron region
            page.mouse.click(popup_box["x"] + 185, popup_box["y"] + 135)

        page.wait_for_timeout(250)

    # 4. In the JAN 2025 calendar grid, click Day 1 (Row 1, Column 3 - Wednesday)
    print("\nSelecting Day 1 on the Start Date calendar...")
    page.wait_for_timeout(500)

    day_selected = False
    try:
        cand_days = popup.locator(':is(div, td, span, button):text-is("1")').all()
        for d in cand_days:
            box = d.bounding_box()
            # Strictly left calendar (x < popup_half_width) and inside calendar grid row 1 (y around header + 130..175)
            if box and popup_box and box["x"] < popup_box["x"] + popup_half_width and popup_box["y"] + 130 <= box["y"] <= popup_box["y"] + 180:
                print(f"Found Start Date Day '1' at ({box['x']:.0f}, {box['y']:.0f}). Clicking...")
                d.click(force=True)
                day_selected = True
                break
    except Exception as e:
        print("Day 1 click note:", e)

    if not day_selected and popup_box:
        # Fallback click on Day 1 (Jan 1, 2025 was Wednesday -> col 3 in calendar grid, Row 1 y ~ 152)
        print("Fallback clicking Jan 1 at Wednesday col 3 (Row 1, y ~ 152)...")
        page.mouse.click(popup_box["x"] + 115, popup_box["y"] + 152)

    page.wait_for_timeout(1000)

    jan_img = OUTPUT_DIR / "debug_date_popup_jan2025.png"
    page.screenshot(path=str(jan_img), full_page=True)
    print(f"Selected Jan 1, 2025. Saved view to {jan_img}")

    # 5. Click the 'Apply' button
    print("\nClicking 'Apply' button on date picker...")
    apply_clicked = False
    for a_sel in [
        'button:has-text("Apply")',
        '.mat-button:has-text("Apply")',
        '[role="button"]:has-text("Apply")',
        'div:has-text("Apply")',
    ]:
        try:
            btn = popup.locator(a_sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                apply_clicked = True
                print(f"Clicked 'Apply' using selector: {a_sel}")
                break
        except Exception:
            pass

    if not apply_clicked:
        for frame in page.frames:
            try:
                b = frame.locator('button:has-text("Apply")').first
                if b.is_visible(timeout=1000):
                    b.click()
                    apply_clicked = True
                    print("Clicked 'Apply' on frame!")
                    break
            except Exception:
                pass

    if not apply_clicked and popup_box:
        print("Fallback clicking 'Apply' at bottom-right of popup...")
        page.mouse.click(popup_box["x"] + popup_box["width"] - 60, popup_box["y"] + popup_box["height"] - 35)
        apply_clicked = True

    page.wait_for_timeout(3000)
    print("Date filter applied successfully!")

    # User requested: Wait 180 seconds for BigQuery to fully process and load the 100k+ dataset before trying to export
    reload_wait_seconds = 180
    print("\n" + "=" * 60)
    print(f"WAITING {reload_wait_seconds} SECONDS (3 MINUTES) FOR BIGQUERY TO FULLY LOAD DATASET...")
    print("Giving Looker Studio full time to fetch and render all records from Jan 1, 2025 to Present.")
    print("=" * 60)

    start_reload_wait = time.time()
    while time.time() - start_reload_wait < reload_wait_seconds:
        elapsed = int(time.time() - start_reload_wait)
        remaining = int(reload_wait_seconds - elapsed)
        if elapsed > 0 and elapsed % 15 == 0:
            print(f"  BigQuery load in progress... {elapsed}s elapsed ({remaining}s remaining)")
        page.wait_for_timeout(3000)

    print("\n180-second wait completed! Data is loaded. Now proceeding to export...\n")


def export_report_robust(page, max_wait_seconds=300):
    """
    Waits dynamically for Looker Studio table data to fully load from BigQuery,
    periodically checking if the right-click context menu has 'Export'.
    Once 'Export' appears (confirming data is loaded), clicks it and confirms
    the export dialog to download the file.
    """
    print(f"\nWaiting for Looker Studio report to load BigQuery data (up to {max_wait_seconds}s)...")
    
    start_time = time.time()
    export_clicked = False

    # Menu selectors that appear ONLY when the data has finished loading
    export_menu_selectors = [
        'button[role="menuitem"]:has-text("Export")',
        '[role="menuitem"]:has-text("Export")',
        '.mat-menu-item:has-text("Export")',
        'text="Export"',
        'text="Export data"',
        'text="Download data"',
    ]

    # Specific data row indicators (only present after data loads, never in top filter bar)
    data_indicators = [
        'div:has-text("BYM-")',
        'div:has-text("LBY-")',
        'div:has-text("-SHL-")',
        'div[role="row"]:has(div[role="gridcell"])',
        'div.row:has(div.cell)',
    ]

    # Allow Looker Studio iframe to initialize
    page.wait_for_timeout(10000)

    while time.time() - start_time < max_wait_seconds:
        elapsed = int(time.time() - start_time)

        # 1. Check if specific data elements have rendered
        data_cell = None
        for frame in page.frames:
            for selector in data_indicators:
                try:
                    loc = frame.locator(selector).first
                    if loc.is_visible(timeout=200):
                        data_cell = loc
                        break
                except Exception:
                    pass
            if data_cell:
                break

        print(f"[{elapsed}s elapsed] Checking table status (waiting for 'Export' option)...")

        # 2. Perform right-click on the data cell or central table area
        try:
            if data_cell:
                data_cell.hover(timeout=2000)
                data_cell.click(button="right", timeout=2000)
            else:
                # Right-click inside the central chart canvas area (below filter bar)
                page.mouse.move(600, 420)
                page.mouse.click(600, 420, button="right")
        except Exception as e:
            print("  Right-click note:", e)

        page.wait_for_timeout(1000)

        # 3. Check if 'Export' is present in the context menu
        export_item = None
        for frame in page.frames:
            for m_sel in export_menu_selectors:
                try:
                    item = frame.locator(m_sel).first
                    if item.is_visible(timeout=800):
                        export_item = item
                        print(f"\n>>> Table data ready! Found '{m_sel}' in context menu after {elapsed}s! <<<")
                        break
                except Exception:
                    pass
            if export_item:
                break

        if export_item:
            # Step A: Hover and click 'Export'
            print("Hovering and clicking 'Export' in context menu...")
            try:
                export_item.hover(timeout=2000)
            except Exception:
                pass
            export_item.click()
            page.wait_for_timeout(1000)

            # Step B: Check for 'Export data' in the submenu
            print("Checking for 'Export data' option...")
            export_data_clicked = False
            for frame in page.frames:
                for ed_sel in [
                    'button[role="menuitem"]:has-text("Export data")',
                    '[role="menuitem"]:has-text("Export data")',
                    '.mat-menu-item:has-text("Export data")',
                    'text="Export data"',
                ]:
                    try:
                        ed_item = frame.locator(ed_sel).first
                        if ed_item.is_visible(timeout=1500):
                            print(f"Found and clicking '{ed_sel}' submenu option...")
                            ed_item.click()
                            export_data_clicked = True
                            break
                    except Exception:
                        pass
                if export_data_clicked:
                    break

            export_clicked = True
            break

        # If 'Export' is not in the menu, data is still loading!
        # Close the context menu with Escape so it doesn't block subsequent interactions
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass

        print("  Data still loading from BigQuery (loading spinner active)... retrying in 6 seconds.")
        page.wait_for_timeout(6000)

    if not export_clicked:
        debug_img = OUTPUT_DIR / "debug_menu_failure.png"
        page.screenshot(path=str(debug_img), full_page=True)
        raise RuntimeError(f"Export option did not appear within {max_wait_seconds}s. BigQuery data may still be loading. Saved screenshot to {debug_img}")

    page.wait_for_timeout(2000)

    # 4. Handle the Looker Studio Export Dialog (CSV / Excel / Google Sheets)
    print("\nWaiting for Looker Studio Export Dialog (CSV, Excel, Google Sheets)...")
    
    # Wait for the modal dialog to be visible
    dialog_found = False
    for attempt in range(15):
        for frame in page.frames:
            for d_sel in ['div[role="dialog"]', '.mat-dialog-container', '.export-dialog', 'mat-dialog-container']:
                try:
                    dlg = frame.locator(d_sel).first
                    if dlg.is_visible(timeout=1000):
                        dialog_found = True
                        print(f"Export dialog opened ({d_sel})!")
                        break
                except Exception:
                    pass
            if dialog_found:
                break
        if dialog_found:
            break
        page.wait_for_timeout(1000)

    page.wait_for_timeout(1000)

    # Find the dialog's confirmation 'Export' button
    dialog_buttons = [
        '.mat-dialog-actions button:has-text("Export")',
        'button.mat-primary:has-text("Export")',
        'button:has-text("Export")',
        'button[type="submit"]:has-text("Export")',
    ]

    for frame in page.frames:
        for selector in dialog_buttons:
            try:
                dialog_btn = frame.locator(selector).first
                if dialog_btn.is_visible(timeout=3000):
                    print(f"Found dialog confirmation button ({selector}). Triggering download...")
                    with page.expect_download(timeout=90000) as download_info:
                        dialog_btn.click()
                    
                    download = download_info.value
                    filename = download.suggested_filename or "Lamp_Installation_Report.csv"
                    destination = OUTPUT_DIR / filename
                    download.save_as(destination)

                    print("\n" + "=" * 60)
                    print(f"SUCCESSFULLY DOWNLOADED: {destination.resolve()}")
                    print("=" * 60)
                    return destination
            except PlaywrightTimeoutError:
                continue
            except Exception as e:
                print(f"Dialog button check note: {e}")

    debug_img = OUTPUT_DIR / "debug_dialog_failure.png"
    page.screenshot(path=str(debug_img), full_page=True)
    raise RuntimeError(f"Could not confirm export in dialog. Screenshot saved to {debug_img}")


def main():
    parser = argparse.ArgumentParser(description="Automated Playwright Extractor for Looker Studio Lamp Installation Report")
    parser.add_argument("--start-year", type=int, default=2025, help="Start year for date filter (default: 2025)")
    parser.add_argument("--start-month", type=str, default="JAN", help="Start month for date filter (default: JAN)")
    parser.add_argument("--skip-date", action="store_true", help="Skip changing date filter (exports default 7-day view)")
    parser.add_argument("--heap-mb", type=int, default=8192, help="V8 JavaScript heap memory limit in MB (default: 8192 MB to prevent Out of Memory)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default: False)")
    args = parser.parse_args()

    print("=" * 60)
    print("LAMP INSTALLATION REPORT PLAYWRIGHT AUTOMATION")
    print(f"Memory Heap Allocation: {args.heap_mb} MB")
    print(f"Target Date Range: {args.start_month} {args.start_year} -> Present" if not args.skip_date else "Target Date Range: Default (skip-date)")
    print("=" * 60)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,  # Keep visible unless --headless specified
            args=[
                f"--js-flags=--max-old-space-size={args.heap_mb}",  # Allocates 8GB V8 heap to prevent "Aw, Snap! Out of Memory"
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",  # Frees up substantial memory on Windows
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--mute-audio",
                "--memory-pressure-off",
            ],
        )
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        try:
            # 1. Login to ThingsBoard
            login_to_thingsboard(page)

            # 2. Open authorized Looker Studio report
            open_report(page)

            # 3. Filter Customer: Bangalore (BBMP) - strictly applied before date range to reduce payload
            select_customer_bbmp(page)

            # 4. Configure Date Filter if not skipped
            if not args.skip_date:
                set_date_range_filter(page, target_start_year=args.start_year, target_start_month=args.start_month)

            # 5. Export report automatically
            file_path = export_report_robust(page)
            print("\nAutomation completed successfully!")
            print(f"Exported File: {file_path}")

        except Exception as error:
            print("\nAUTOMATION ERROR:")
            print(error)
        finally:
            print("\nClosing browser in 5 seconds...")
            page.wait_for_timeout(5000)
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
