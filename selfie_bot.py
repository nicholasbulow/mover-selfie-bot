"""
Mover Selfie Bot — GitHub Actions runner (Playwright version)
Uses a real headless browser so JavaScript-rendered pages work correctly.
"""

import os
import sys
import json
import argparse
from datetime import date, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE      = "https://admin.mover.dk"
LOGIN_URL = f"{BASE}/dk/da/login/"

# ── Helpers ────────────────────────────────────────────────────────────────────

def format_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")

def log(msg: str):
    print(msg, flush=True)

# ── Login ──────────────────────────────────────────────────────────────────────

def login(page, email: str, password: str):
    page.goto(LOGIN_URL, wait_until="networkidle")
    page.fill("input[name='username']", email)
    page.fill("input[name='password']", password)
    page.click("button[type='submit'], input[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    log(f"✅ Logged in as {email}")

# ── Get driver IDs for a customer on a given date ─────────────────────────────

def get_driver_ids(page, customer_id: str, target_date: str) -> tuple:
    trips_url = f"{BASE}/dk/da/user-area/users/{customer_id}/trips/"
    page.goto(trips_url, wait_until="networkidle")

    # Wait for table to appear
    try:
        page.wait_for_selector("table tbody tr", timeout=10000)
    except PWTimeout:
        return [], 0

    rows = page.query_selector_all("table tbody tr")
    see_more_links = []

    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) < 2:
            continue
        date_text = cells[1].inner_text().strip().split()[0]
        if date_text != target_date:
            continue
        for a in row.query_selector_all("a"):
            text = a.inner_text().strip().lower()
            href = a.get_attribute("href") or ""
            if "see" in text or "more" in text or "info" in text:
                full = BASE + href if href.startswith("/") else href
                if full not in see_more_links:
                    see_more_links.append(full)

    driver_ids = set()
    for url in see_more_links:
        try:
            page.goto(url, wait_until="networkidle")
            for a in page.query_selector_all("a[href*='/user-area/users/']"):
                href = a.get_attribute("href") or ""
                import re
                m = re.search(r"/users/(\d+)", href)
                if m and m.group(1) != customer_id:
                    driver_ids.add(m.group(1))
                    break
        except Exception as e:
            log(f"  ⚠️  Could not read route page: {e}")

    return list(driver_ids), len(see_more_links)

# ── Enable selfie for one driver ──────────────────────────────────────────────

def find_selfie_checkbox(page):
    """Find the selfie checkbox by locating the heading then the next checkbox."""
    headings = page.query_selector_all("h1, h2, h3, h4, h5, h6, legend")
    selfie_heading = None
    for h in headings:
        if "selfie" in h.inner_text().lower():
            selfie_heading = h
            break
    if not selfie_heading:
        return None

    # Evaluate in page context to walk forward siblings
    cb = page.evaluate("""(heading) => {
        const HEADING_TAGS = new Set(['H1','H2','H3','H4','H5','H6','LEGEND']);
        function walkForward(start) {
            let node = start.nextElementSibling;
            while (node) {
                if (HEADING_TAGS.has(node.tagName)) break;
                if (node.tagName === 'INPUT' && node.type === 'checkbox') return node;
                const inner = node.querySelector('input[type="checkbox"]');
                if (inner) return inner;
                node = node.nextElementSibling;
            }
            return null;
        }
        return walkForward(heading) || (heading.parentElement && walkForward(heading.parentElement));
    }""", selfie_heading)

    return cb

def enable_selfie(page, driver_id: str) -> str:
    url = f"{BASE}/dk/da/user-area/users/{driver_id}/settings/"
    page.goto(url, wait_until="networkidle")

    cb_handle = find_selfie_checkbox(page)
    if cb_handle is None:
        return "selfie checkbox not found"

    # Check if already enabled
    is_checked = page.evaluate("el => el.checked", cb_handle)
    if is_checked:
        return "already_on"

    # Click the checkbox
    page.evaluate("el => el.click()", cb_handle)

    # Click Save button
    try:
        save_btn = page.query_selector("button[type='submit'], input[type='submit'], button:has-text('Save'), input[value='Save']")
        if save_btn:
            save_btn.click()
            page.wait_for_load_state("networkidle")
        else:
            return "save button not found"
    except Exception as e:
        return f"save error: {e}"

    # Verify
    page.goto(url, wait_until="networkidle")
    cb_verify = find_selfie_checkbox(page)
    if cb_verify and page.evaluate("el => el.checked", cb_verify):
        return "enabled"
    return "save_failed"

# ── Run for one customer ───────────────────────────────────────────────────────

def run_customer(page, customer: dict, date_offset: int):
    import re
    target     = date.today() + timedelta(days=date_offset)
    target_str = format_date(target)
    label      = "today" if date_offset == 0 else "tomorrow"

    log(f"\n── {customer['name']} ({customer['id']}) — {target_str} ({label})")

    # Day-of-week check (0=Sun, 1=Mon ... 6=Sat)
    dow = target.isoweekday() % 7
    run_days = customer.get("run_days", list(range(7)))
    if run_days and dow not in run_days:
        day_names = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
        log(f"  ⏭️  Skipping — not scheduled for {day_names[dow]}")
        return

    driver_ids, trip_count = get_driver_ids(page, customer["id"], target_str)

    if not trip_count:
        log(f"  ⚠️  No trips found for {target_str}")
        return
    if not driver_ids:
        log(f"  ⚠️  No driver IDs found ({trip_count} trips)")
        return

    log(f"  Found {len(driver_ids)} driver(s) across {trip_count} trip(s)")

    enabled = alreadyon = failed = 0
    for did in sorted(driver_ids):
        result = enable_selfie(page, did)
        if   result == "enabled":    log(f"  ✅ Driver {did}: enabled");    enabled += 1
        elif result == "already_on": log(f"  ⏭️  Driver {did}: already on"); alreadyon += 1
        else:                        log(f"  ❌ Driver {did}: {result}");    failed += 1

    log(f"  ── ✅ {enabled}  ⏭️  {alreadyon}  ❌ {failed}")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    email    = os.environ.get("MOVER_EMAIL")
    password = os.environ.get("MOVER_PASSWORD")
    if not email or not password:
        log("❌ MOVER_EMAIL and MOVER_PASSWORD environment variables required")
        sys.exit(1)

    config_path = os.path.join(os.path.dirname(__file__), "customers.json")
    with open(config_path) as f:
        customers = json.load(f)

    active = [c for c in customers if c.get("enabled", True)]
    if not active:
        log("No active customers in customers.json")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_page()

        login(page, email, password)

        for customer in active:
            should_run = customer.get("run_today") if args.offset == 0 else customer.get("run_tomorrow")
            if not should_run:
                label = "today" if args.offset == 0 else "tomorrow"
                log(f"\nSkipping {customer['name']} (not configured for {label})")
                continue
            run_customer(page, customer, args.offset)

        browser.close()

    log("\n══ All done ══════════════════════")

if __name__ == "__main__":
    main()
