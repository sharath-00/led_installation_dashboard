"""Automated Playwright Extractor for Schnell-IoT Installed SLC Report (Bangalore BBMP)."""

import argparse
import base64
import json
import time
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ==========================================================
# CONFIGURATION
# ==========================================================

THINGSBOARD_HOST = "https://schnelliot.in"
THINGSBOARD_LOGIN_URL = f"{THINGSBOARD_HOST}/login"
USERNAME = "vinoth.joel@schnellenergy.com"
PASSWORD = "vinoth555"

SLC_DASHBOARD_ID = "3b82ad20-5b91-11ef-9d99-8f0cdda88afb"
BBMP_CUSTOMER_ID = "e2119df0-45c3-11f0-94dc-77130b2f47e9"
BBMP_CUSTOMER_NAME = "Bangalore (BBMP)"

# Standard ThingsBoard iframe wrapper URL (opens Project Context selector first)
SLC_REPORT_IFRAME_URL = (
    f"{THINGSBOARD_HOST}/iframeView/child"
    f"?stateId=Information%20Reports"
    f"&childStateId=Installed%20SLC%20Report"
    f"&childIframeUrl=dashboard%2F{SLC_DASHBOARD_ID}"
    f"&childSetAccessToken=true"
)

# Output directory anchored to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "SLC_Report"


def build_direct_slc_dashboard_url(
    customer_id: str = BBMP_CUSTOMER_ID,
    customer_name: str = BBMP_CUSTOMER_NAME,
) -> str:
    """
    Builds the direct ThingsBoard dashboard URL with the target customer
    (e.g. Bangalore (BBMP)) pre-selected in the URL state parameter.
    """
    state_obj = [
        {
            "id": "default",
            "params": {
                "selectedCustomer": {
                    "entityId": {"id": customer_id, "entityType": "CUSTOMER"},
                    "entityName": customer_name,
                    "entityLabel": customer_name,
                },
                "targetEntityParamName": "selectedEntity",
                "selectedEntity": {
                    "entityId": {"id": customer_id, "entityType": "CUSTOMER"},
                    "entityName": customer_name,
                    "entityLabel": customer_name,
                },
            },
        }
    ]
    encoded = base64.b64encode(
        json.dumps(state_obj, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"{THINGSBOARD_HOST}/dashboard/{SLC_DASHBOARD_ID}?state={quote(encoded, safe='')}"


def login_to_thingsboard(page, output_dir: Path):
    """Navigates to ThingsBoard login page and authenticates."""
    print("\nOpening ThingsBoard login page...")
    try:
        page.goto(THINGSBOARD_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"Navigation warning: {e}")

    page.wait_for_timeout(2000)

    if "login" not in page.url and ("dashboard" in page.url or "home" in page.url or "iframeView" in page.url):
        print("Already authenticated in ThingsBoard! Current URL:", page.url)
        return

    print("Waiting for ThingsBoard login form components to mount...")
    password_field = None
    for _ in range(30):
        if "login" not in page.url and ("dashboard" in page.url or "home" in page.url or "iframeView" in page.url):
            print("Redirected after auth! Current URL:", page.url)
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
        err_img = output_dir / "debug_slc_login_error.png"
        page.screenshot(path=str(err_img), full_page=True)
        raise RuntimeError(f"Could not find ThingsBoard password field. Screenshot saved to {err_img}")

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
        err_img = output_dir / "debug_slc_login_error.png"
        page.screenshot(path=str(err_img), full_page=True)
        raise RuntimeError(f"Could not identify ThingsBoard username field. Screenshot saved to {err_img}")

    print("Filling credentials...")
    username_field.fill(USERNAME)
    page.wait_for_timeout(300)
    password_field.fill(PASSWORD)
    page.wait_for_timeout(300)

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
        password_field.press("Enter")

    # Wait until redirect leaves /login
    for _ in range(25):
        if "/login" not in page.url:
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(2000)
    print("ThingsBoard login completed. Current URL:", page.url)


def _find_export_button(page):
    """Searches all frames for the ThingsBoard widget 'Export widget data' button."""
    selectors = [
        'button[aria-label="Export widget data"]',
        'button[title="Export widget data"]',
        'button[mattooltip="Export widget data"]',
        'button:has(mat-icon:text-is("file_download"))',
        'button:has(mat-icon:text-is("download"))',
        'button:has(mat-icon:text-is("get_app"))',
        'button[aria-label*="Export widget" i]',
    ]
    for frame in page.frames:
        for sel in selectors:
            try:
                loc = frame.locator(sel).first
                if loc.is_visible(timeout=400):
                    return frame, loc
            except Exception:
                pass
    return None, None


def _select_customer_in_project_context(page, customer_name: str, max_wait_seconds: int = 30) -> bool:
    """
    If ThingsBoard opened the 'Project Context' screen (Select a Customer + Project hierarchy),
    clicks the customer row (e.g. 'Bangalore (BBMP)') and then clicks the root tree item
    in 'Project hierarchy' to open the Installed SLC Report table.
    """
    print(f"Checking for Project Context selector to pick '{customer_name}'...")
    start = time.time()
    customer_clicked = False

    while time.time() - start < max_wait_seconds:
        # Already on the report table?
        _, export_btn = _find_export_button(page)
        if export_btn is not None:
            print("Installed SLC Report table is already open!")
            return True

        for frame in page.frames:
            try:
                if not customer_clicked:
                    cust_cell = frame.locator(f'td:text-is("{customer_name}"), span:text-is("{customer_name}"), text="{customer_name}"').first
                    if cust_cell.is_visible(timeout=500):
                        print(f"Found customer '{customer_name}' in list. Clicking...")
                        cust_cell.click(force=True)
                        customer_clicked = True
                        page.wait_for_timeout(2000)
                        break
                else:
                    # Click root node in Project hierarchy tree to load report
                    tree_item = frame.locator(f'[role="treeitem"]:has-text("{customer_name}")').first
                    if tree_item.is_visible(timeout=800):
                        print(f"Found '{customer_name}' in Project hierarchy tree. Clicking...")
                        tree_item.click(force=True)
                        page.wait_for_timeout(2500)
                        return True
            except Exception:
                pass

        page.wait_for_timeout(1000)

    return customer_clicked


def open_installed_slc_report(
    page,
    customer_name: str = BBMP_CUSTOMER_NAME,
    use_iframe_nav: bool = False,
    max_wait_seconds: int = 60,
):
    """
    Opens the Installed SLC Report with Bangalore (BBMP) selected.
    By default uses the direct ThingsBoard dashboard URL with BBMP state pre-selected;
    if the Project Context screen appears (or --via-iframe is passed), selects the customer via UI.
    """
    print("\n" + "=" * 60)
    print(f"OPENING INSTALLED SLC REPORT FOR: {customer_name}")
    print("=" * 60)

    if use_iframe_nav or customer_name != BBMP_CUSTOMER_NAME:
        target_url = SLC_REPORT_IFRAME_URL
    else:
        target_url = build_direct_slc_dashboard_url(BBMP_CUSTOMER_ID, customer_name)

    print(f"Navigating to: {target_url}")
    page.goto(target_url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(4000)

    start = time.time()
    while time.time() - start < max_wait_seconds:
        # 1. Check if Export widget data button + table rows are visible
        frame, export_btn = _find_export_button(page)
        if export_btn is not None:
            # Verify data rows or pagination count ("1 – 10 of ...") have loaded
            try:
                body_txt = frame.locator("body").inner_text(timeout=1500)
                if "of " in body_txt and ("Panel UID" in body_txt or "Controller ID" in body_txt or "SLC" in body_txt):
                    # Extract count line if present
                    for line in body_txt.splitlines():
                        if "–" in line and "of " in line:
                            print(f"Report data loaded! Pagination status: {line.strip()}")
                            break
                    else:
                        print("Report table loaded and ready for export!")
                    return frame
            except Exception:
                pass

        # 2. Check if we landed on Project Context selector
        for fr in page.frames:
            try:
                if fr.locator('text="Select a Customer"').first.is_visible(timeout=300):
                    _select_customer_in_project_context(page, customer_name, max_wait_seconds=30)
                    break
            except Exception:
                pass

        elapsed = int(time.time() - start)
        if elapsed > 0 and elapsed % 5 == 0:
            print(f"  Waiting for Installed SLC Report table to populate... ({elapsed}s elapsed)")
        page.wait_for_timeout(1500)

    raise RuntimeError(
        f"Timed out after {max_wait_seconds}s waiting for Installed SLC Report table to load."
    )


def export_slc_report(
    page,
    output_dir: Path,
    export_format: str = "csv",
    download_timeout_seconds: int = 180,
) -> Path:
    """
    Clicks the ThingsBoard widget's 'Export widget data' menu and selects
    'Export data to CSV...' (or XLS / XLSX), capturing the downloaded file.
    """
    fmt = export_format.strip().upper()
    if fmt not in {"CSV", "XLS", "XLSX"}:
        raise ValueError(f"Unsupported format '{export_format}'. Choose csv, xls, or xlsx.")

    menu_label = f"Export data to {fmt}..."
    print("\n" + "=" * 60)
    print(f"EXPORTING INSTALLED SLC REPORT AS {fmt}")
    print("=" * 60)

    frame, export_btn = _find_export_button(page)
    if export_btn is None:
        debug_img = output_dir / "debug_slc_export_button_missing.png"
        page.screenshot(path=str(debug_img), full_page=True)
        raise RuntimeError(f"Could not find 'Export widget data' button. Saved screenshot to {debug_img}")

    print("Clicking 'Export widget data' menu button...")
    export_btn.click(force=True)
    page.wait_for_timeout(1000)

    # Locate the requested export menu item across frames (Angular CDK overlay renders inside the dashboard frame)
    menu_item = None
    menu_selectors = [
        f'[role="menuitem"]:has-text("{menu_label}")',
        f'button:has-text("{menu_label}")',
        f'[role="menuitem"]:has-text("{fmt}")',
        f'text="{menu_label}"',
    ]
    for fr in page.frames:
        for sel in menu_selectors:
            try:
                cand = fr.locator(sel).first
                if cand.is_visible(timeout=1200):
                    menu_item = cand
                    print(f"Found export menu option: '{menu_label}' (selector: {sel})")
                    break
            except Exception:
                pass
        if menu_item:
            break

    if menu_item is None:
        debug_img = output_dir / "debug_slc_export_menu_missing.png"
        page.screenshot(path=str(debug_img), full_page=True)
        raise RuntimeError(f"Could not find '{menu_label}' in export menu. Screenshot saved to {debug_img}")

    print(
        f"Clicking '{menu_label}' and waiting up to {download_timeout_seconds}s "
        "for ThingsBoard to paginate all records and download the file..."
    )
    with page.expect_download(timeout=download_timeout_seconds * 1000) as download_info:
        menu_item.click(force=True)

    download = download_info.value
    suggested = download.suggested_filename or f"Installed_SLC_Report_Bangalore.{fmt.lower()}"
    destination = output_dir / suggested
    download.save_as(destination)

    size_kb = destination.stat().st_size / 1024 if destination.exists() else 0
    print("\n" + "=" * 60)
    print(f"SUCCESSFULLY DOWNLOADED: {destination.resolve()}")
    print(f"File Size: {size_kb:,.1f} KB")
    print("=" * 60)
    return destination


def main():
    parser = argparse.ArgumentParser(
        description="Automated Playwright Extractor for Schnell-IoT Installed SLC Report (Bangalore BBMP)"
    )
    parser.add_argument(
        "--format",
        choices=["csv", "xls", "xlsx"],
        default="csv",
        help="Export file format (default: csv)",
    )
    parser.add_argument(
        "--customer",
        default=BBMP_CUSTOMER_NAME,
        help=f"Customer / Project Context name (default: '{BBMP_CUSTOMER_NAME}')",
    )
    parser.add_argument(
        "--via-iframe",
        action="store_true",
        help="Navigate via the full Schnell-IoT sidebar/Project Context UI instead of the direct BBMP dashboard URL",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory to save downloaded report (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Download wait timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium in headless mode (default: visible browser)",
    )
    args = parser.parse_args()

    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("INSTALLED SLC REPORT PLAYWRIGHT AUTOMATION")
    print(f"Customer: {args.customer} | Format: {args.format.upper()}")
    print(f"Output Directory: {output_dir.resolve()}")
    print("=" * 60)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--mute-audio",
            ],
        )
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        try:
            # 1. Authenticate on ThingsBoard
            login_to_thingsboard(page, output_dir)

            # 2. Open Installed SLC Report for Bangalore (BBMP)
            open_installed_slc_report(
                page,
                customer_name=args.customer,
                use_iframe_nav=args.via_iframe,
            )

            # 3. Export widget data to CSV / XLS / XLSX
            downloaded_path = export_slc_report(
                page,
                output_dir=output_dir,
                export_format=args.format,
                download_timeout_seconds=args.timeout,
            )
            print("\nAutomation completed successfully!")
            print(f"Saved File: {downloaded_path}")

        except Exception as error:
            print("\nAUTOMATION ERROR:")
            print(error)
            try:
                err_shot = output_dir / "debug_slc_error.png"
                page.screenshot(path=str(err_shot), full_page=True)
                print(f"Debug screenshot saved to: {err_shot}")
            except Exception:
                pass
            raise SystemExit(1)
        finally:
            print("\nClosing browser in 3 seconds...")
            page.wait_for_timeout(3000)
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
