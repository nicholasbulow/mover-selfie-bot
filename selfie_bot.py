"""
Mover Selfie Bot — GitHub Actions runner
Hybrid approach: requests for login, Playwright for JS-rendered pages.
"""

import os
import sys
import json
import re
import argparse
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE      = "https://admin.mover.dk"
LOGIN_URL = f"{BASE}/dk/da/login/"

def log(msg: str):
    print(msg, flush=True)

def format_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")

# ── Step 1: Login with requests (proven to work) ───────────────────────────────

def requests_login(email: str, password: str) -> list:
    """Returns a list of cookie dicts for Playwright."""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})

    # GET login page to obtain CSRF cookie
    s.get(LOGIN_URL)
    csrf = s.cookies.get("csrftoken", "")

    resp = s.post(LOGIN_URL, data={
        "csrfmiddlewaretoken": csrf,
        "username": email,
        "password": password,
    }, headers={"Referer": LOGIN_URL, "X-CSRFToken": csrf})

    if "/login" in resp.url:
        raise RuntimeError("Login failed — check MOVER_EMAIL and MOVER_PASSWORD secrets")

    log(f"✅ Logged in as {email}")

    # Convert requests cookies to Playwright cookie format
    playwright_cookies = []
    for c in s.cookies:
        playwright_cookies.append({
            "name":   c.name,
            "value":  c.value,
            "domain": c.domain or "admin.mover.dk",
            "path":   c.path or "/",
        })
    return playwright_cookies

# ── Step 2: Use Playwright with those cookies ──────────────────────────────────

def get_driver_ids(page, customer_id: str, target_date: str) -> tuple:
    trips_url = f"{BASE}/dk/da/user-area/users/{customer_id}/trips/"
    page.goto(trips_url)
    page.wait_for_load_state("networkidle", timeout=20000)

    try:
        page.wait_for_selector("table tbody tr", timeout=10000)
    except PWTimeout:
        log("  ⚠️  Trips table not found")
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

    log(f"  Found {len(see_more_links)} trip(s) for {target_date}")

    driver_ids = set()
    for url in see_more_links:
        try:
            page.goto(url, wait_until="networkidle")
            for a in page.query_selector_all("a"):
                href = a.get_attribute("href") or ""
                m = re.search(r"/users/(\d+)", href)
                if m and m.group(1) != customer_id:
                    driver_ids.add(m.group(1))
                    break
        except Exception as e:
            log(f"  ⚠️  Route page error: {e}")

    return list(driver_ids), len(see_more_links)

def find_selfie_checkbox(page):
    headings = page.query_selector_all("h1,h2,h3,h4,h5,h6,legend")
    selfie_heading = None
    for h in headings:
        if "selfie" in h.inner_text().lower():
            selfie_heading = h
            break
    if not selfie_heading:
        return None

    return page.evaluate("""(heading) => {
        const TAGS = new Set(['H1','H2','H3','H4','H5','H6','LEGEND']);
        function walk(start) {
            let node = start.nextElementSibling;
            while (node) {
                if (TAGS.has(node.tagName)) break;
                if (node.tagName === 'INPUT' && node.type === 'checkbox') return node;
                const inner = node.querySelector('input[type="checkbox"]');
                if (inner) return inner;
                node = node.nextElementSibling;
            }
            return null;
        }
        return walk(heading) || (heading.parentElement && walk(heading.parentElement));
    }""", selfie_heading)

def enable_selfie(page, driver_id: str) -> str:
    url = f"{BASE}/dk/da/user-area/users/{driver_id}/settings/"
    page.goto(url, wait_until="networkidle")

    cb = find_selfie_checkbox(page)
    if cb is None:
        return "selfie checkbox not found"

    is_checked = page.evaluate("el => el.checked", cb)
    if is_checked:
        return "already_on"

    page.evaluate("el => el.click()", cb)

    save = page.query_selector("input[value='Save'], button:has-text('Save'), button[type='submit']")
    if not save:
        return "save button not found"
    save.click()
    page.wait_for_load_state("networkidle")

    # Verify
    page.goto(url, wait_until="networkidle")
    cb2 = find_selfie_checkbox(page)
    if cb2 and page.evaluate("el => el.checked", cb2):
        return "enabled"
    return "save_failed"

def run_customer(page, customer: dict, date_offset: int):
    target     = date.today() + timedelta(days=date_offset)
    target_str = format_date(target)
    label      = "today" if date_offset == 0 else "tomorrow"

    log(f"\n── {customer['name']} ({customer['id']}) — {target_str} ({label})")

    dow      = target.isoweekday() % 7
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

    log(f"  Found {len(driver_ids)} unique driver(s)")

    enabled = alreadyon = failed = 0
    for did in sorted(driver_ids):
        result = enable_selfie(page, did)
        if   result == "enabled":    log(f"  ✅ Driver {did}: enabled");    enabled += 1
        elif result == "already_on": log(f"  ⏭️  Driver {did}: already on"); alreadyon += 1
        else:                        log(f"  ❌ Driver {did}: {result}");    failed += 1

    log(f"  ── ✅ {enabled}  ⏭️  {alreadyon}  ❌ {failed}")

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
        log("No active customers configured")
        return

    # Login with requests (proven reliable)
    cookies = requests_login(email, password)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Inject login cookies so Playwright is already authenticated
        context.add_cookies(cookies)
        page = context.new_page()

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
