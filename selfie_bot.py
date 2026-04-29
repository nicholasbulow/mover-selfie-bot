"""
Mover Selfie Bot — GitHub Actions runner
"""

import os
import sys
import json
import re
import argparse
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

BASE      = "https://admin.mover.dk"
LOGIN_URL = f"{BASE}/dk/da/login/"

def log(msg: str):
    print(msg, flush=True)

def format_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")

# ── Login ──────────────────────────────────────────────────────────────────────

def login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})

    resp = s.get(LOGIN_URL)
    csrf = s.cookies.get("csrftoken", "")
    log(f"  Login page: {resp.url} | CSRF: {'✓' if csrf else '✗'}")

    # Find the actual form field names from the page
    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form")
    if form:
        fields = [(i.get("name",""), i.get("type","")) for i in form.find_all("input")]
        log(f"  Form fields: {fields}")

    # Build payload with all possible field name variants
    # We'll try the ones we see in the form
    email_field = "loginEmail"
    password_field = "loginPassword"

    # Try to detect field names from the form
    if form:
        for inp in form.find_all("input"):
            t = inp.get("type","").lower()
            n = inp.get("name","")
            if t == "email" or (t == "text" and "email" in n.lower()):
                email_field = n
            elif t == "password":
                password_field = n

    log(f"  Using fields: email={email_field}, password={password_field}")

    resp = s.post(LOGIN_URL, data={
        "csrfmiddlewaretoken": csrf,
        email_field:    email,
        password_field: password,
    }, headers={"Referer": LOGIN_URL, "X-CSRFToken": csrf})

    log(f"  Post-login URL: {resp.url}")

    if "/login" in resp.url:
        raise RuntimeError("Login failed — URL still on login page. Check MOVER_EMAIL and MOVER_PASSWORD secrets.")

    log(f"✅ Logged in as {email}")
    return s

# ── Get driver IDs ─────────────────────────────────────────────────────────────

def get_driver_ids(session: requests.Session, customer_id: str, target_date: str) -> tuple:
    trips_url = f"{BASE}/dk/da/user-area/users/{customer_id}/trips/"
    resp = session.get(trips_url)
    log(f"  Trips page URL: {resp.url}")
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = soup.select("table tbody tr")
    log(f"  Page has {len(rows)} total trip rows")

    see_more_links = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        date_text = cells[1].get_text(strip=True).split()[0]
        if date_text != target_date:
            continue
        for a in row.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if "see" in text or "more" in text or "info" in text:
                href = a["href"]
                full = BASE + href if href.startswith("/") else href
                if full not in see_more_links:
                    see_more_links.append(full)

    log(f"  Found {len(see_more_links)} trip(s) for {target_date}")

    driver_ids = set()
    for url in see_more_links:
        try:
            r = session.get(url)
            doc = BeautifulSoup(r.text, "html.parser")
            for a in doc.find_all("a", href=True):
                m = re.search(r"/users/(\d+)", a["href"])
                if m and m.group(1) != customer_id:
                    driver_ids.add(m.group(1))
                    break
        except Exception as e:
            log(f"  ⚠️  Route page error: {e}")

    return list(driver_ids), len(see_more_links)

# ── Enable selfie ──────────────────────────────────────────────────────────────

def find_selfie_checkbox(soup: BeautifulSoup):
    heading = None
    for tag in soup.find_all(["h1","h2","h3","h4","h5","h6","legend"]):
        if "selfie" in tag.get_text().lower():
            heading = tag
            break
    if not heading:
        return None

    node = heading.find_next_sibling()
    while node:
        if node.name in ["h1","h2","h3","h4","h5","h6","legend"]:
            break
        cb = node.find("input", type="checkbox") if hasattr(node, "find") else None
        if cb:
            return cb
        if node.name == "input" and node.get("type") == "checkbox":
            return node
        node = node.find_next_sibling()

    if heading.parent:
        node = heading.parent.find_next_sibling()
        while node:
            if node.name in ["h1","h2","h3","h4","h5","h6","legend"]:
                break
            cb = node.find("input", type="checkbox") if hasattr(node, "find") else None
            if cb:
                return cb
            node = node.find_next_sibling()

    return None

def enable_selfie(session: requests.Session, driver_id: str) -> str:
    url = f"{BASE}/dk/da/user-area/users/{driver_id}/settings/"
    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    checkbox = find_selfie_checkbox(soup)
    if not checkbox:
        return "selfie checkbox not found"
    if checkbox.get("checked") is not None:
        return "already_on"

    form = checkbox.find_parent("form")
    if not form:
        return "no form found"

    action = form.get("action", "").strip() or url
    if action.startswith("/"):
        action = BASE + action

    csrf = session.cookies.get("csrftoken", "")
    payload = {"csrfmiddlewaretoken": csrf}

    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or name == "csrfmiddlewaretoken":
            continue
        tag  = el.name
        kind = el.get("type", "text").lower()

        if tag == "select":
            selected = el.find("option", selected=True)
            payload[name] = selected["value"] if selected else (el.find("option") or {}).get("value", "")
        elif tag == "textarea":
            payload[name] = el.get_text()
        elif kind == "checkbox":
            if el == checkbox or el.get("checked") is not None:
                payload[name] = el.get("value", "1")
        elif kind == "radio":
            if el.get("checked") is not None:
                payload[name] = el.get("value", "on")
        else:
            payload[name] = el.get("value", "")

    session.post(action, data=payload, headers={"Referer": url, "X-CSRFToken": csrf})

    verify = session.get(url)
    vsoup  = BeautifulSoup(verify.text, "html.parser")
    vcb    = find_selfie_checkbox(vsoup)
    return "enabled" if (vcb and vcb.get("checked") is not None) else "save_failed"

# ── Run customer ───────────────────────────────────────────────────────────────

def run_customer(session: requests.Session, customer: dict, date_offset: int):
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

    driver_ids, trip_count = get_driver_ids(session, customer["id"], target_str)

    if not trip_count:
        log(f"  ⚠️  No trips found for {target_str}")
        return
    if not driver_ids:
        log(f"  ⚠️  No driver IDs found ({trip_count} trips)")
        return

    log(f"  Found {len(driver_ids)} unique driver(s)")

    enabled = alreadyon = failed = 0
    for did in sorted(driver_ids):
        result = enable_selfie(session, did)
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
        log("No active customers configured")
        return

    session = login(email, password)

    for customer in active:
        should_run = customer.get("run_today") if args.offset == 0 else customer.get("run_tomorrow")
        if not should_run:
            label = "today" if args.offset == 0 else "tomorrow"
            log(f"\nSkipping {customer['name']} (not configured for {label})")
            continue
        run_customer(session, customer, args.offset)

    log("\n══ All done ══════════════════════")

if __name__ == "__main__":
    main()
