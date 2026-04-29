"""
Mover Selfie Bot — GitHub Actions runner
Enables 'Required selfie on next stop' for all drivers with trips
on configured customer accounts.
"""

import os
import sys
import json
import argparse
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

BASE = "https://admin.mover.dk"
LOGIN_URL = f"{BASE}/dk/da/login/"

# ── Auth ───────────────────────────────────────────────────────────────────────

def create_session(email: str, password: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})

    # Get CSRF token from login page
resp = session.get(LOGIN_URL)
    # Try cookie first (Django sets csrftoken cookie on GET)
    csrf_value = session.cookies.get("csrftoken", "")
    if not csrf_value:
        # Fallback: try HTML form field
        soup = BeautifulSoup(resp.text, "html.parser")
        csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
        csrf_value = csrf_input["value"] if csrf_input else ""

login_resp = s.post(LOGIN_URL, data={
        "csrfmiddlewaretoken": csrf_value,
        "username": email,
        "password": password,
    }, headers={"Referer": LOGIN_URL})

    if "/login" in login_resp.url:
        raise RuntimeError("Login failed — check MOVER_EMAIL and MOVER_PASSWORD secrets")

    print(f"✅ Logged in as {email}")
    return s


# ── Core logic ─────────────────────────────────────────────────────────────────

def format_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def find_selfie_checkbox(soup: BeautifulSoup):
    """Find the selfie checkbox by locating the heading then walking forward."""
    heading = None
    for tag in soup.find_all(["h1","h2","h3","h4","h5","h6","legend"]):
        if "selfie" in tag.get_text().lower():
            heading = tag
            break
    if not heading:
        return None

    # Walk forward siblings from heading
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

    # Fallback: try parent's next sibling
    parent = heading.parent
    if parent:
        node = parent.find_next_sibling()
        while node:
            if node.name in ["h1","h2","h3","h4","h5","h6","legend"]:
                break
            cb = node.find("input", type="checkbox") if hasattr(node, "find") else None
            if cb:
                return cb
            node = node.find_next_sibling()

    return None


def get_driver_ids(session: requests.Session, customer_id: str, target_date: str) -> tuple[list, int]:
    trips_url = f"{BASE}/dk/da/user-area/users/{customer_id}/trips/"
    resp = session.get(trips_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    see_more_links = []
    for row in soup.select("table tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        date_text = cells[1].get_text(strip=True).split()[0]
        if date_text != target_date:
            continue
        for a in row.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if "see" in text or "more" in text or "info" in text:
                full = BASE + a["href"]
                if full not in see_more_links:
                    see_more_links.append(full)

    driver_ids = set()
    for url in see_more_links:
        try:
            r = session.get(url)
            doc = BeautifulSoup(r.text, "html.parser")
            for a in doc.find_all("a", href=True):
                import re
                m = re.search(r"/users/(\d+)", a["href"])
                if m and m.group(1) != customer_id:
                    driver_ids.add(m.group(1))
                    break
        except Exception:
            pass

    return list(driver_ids), len(see_more_links)


def enable_selfie(session: requests.Session, driver_id: str) -> str:
    """Returns: 'enabled', 'already_on', or error string."""
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

    # Get CSRF from form
    csrf_input = form.find("input", {"name": "csrfmiddlewaretoken"})
    csrf = csrf_input["value"] if csrf_input else ""

    # Build POST payload
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
            # Force selfie on; preserve other checked boxes
            if el == checkbox or el.get("checked") is not None:
                payload[name] = el.get("value", "1")
        elif kind == "radio":
            if el.get("checked") is not None:
                payload[name] = el.get("value", "on")
        else:
            payload[name] = el.get("value", "")

    session.post(action, data=payload, headers={"Referer": url, "X-CSRFToken": csrf})

    # Verify
    verify = session.get(url)
    vsoup  = BeautifulSoup(verify.text, "html.parser")
    vcb    = find_selfie_checkbox(vsoup)
    return "enabled" if (vcb and vcb.get("checked") is not None) else "save_failed"


# ── Runner ─────────────────────────────────────────────────────────────────────

def run_customer(session: requests.Session, customer: dict, date_offset: int):
    target      = date.today() + timedelta(days=date_offset)
    target_str  = format_date(target)
    label       = "today" if date_offset == 0 else "tomorrow"

    print(f"\n── {customer['name']} ({customer['id']}) — {target_str} ({label})")

    # Day-of-week check
    day = target.weekday() + 1  # Mon=1 ... Sun=7, convert to 0=Sun..6=Sat
    dow = target.isoweekday() % 7  # Sun=0, Mon=1 ... Sat=6
    run_days = customer.get("run_days", list(range(7)))
    if run_days and dow not in run_days:
        day_names = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
        print(f"  ⏭️  Skipping — not scheduled for {day_names[dow]}")
        return

    driver_ids, trip_count = get_driver_ids(session, customer["id"], target_str)

    if not trip_count:
        print(f"  ⚠️  No trips found for {target_str}")
        return

    if not driver_ids:
        print(f"  ⚠️  No driver IDs found ({trip_count} trips)")
        return

    print(f"  Found {len(driver_ids)} driver(s) across {trip_count} trip(s)")

    enabled = alreadyon = failed = 0
    for did in sorted(driver_ids):
        result = enable_selfie(session, did)
        if   result == "enabled":    print(f"  ✅ Driver {did}: enabled");    enabled += 1
        elif result == "already_on": print(f"  ⏭️  Driver {did}: already on"); alreadyon += 1
        else:                        print(f"  ❌ Driver {did}: {result}");    failed += 1

    print(f"  ── ✅ {enabled}  ⏭️  {alreadyon}  ❌ {failed}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0,
                        help="Date offset: 0=today, 1=tomorrow")
    args = parser.parse_args()

    email    = os.environ.get("MOVER_EMAIL")
    password = os.environ.get("MOVER_PASSWORD")
    if not email or not password:
        print("❌ MOVER_EMAIL and MOVER_PASSWORD environment variables required")
        sys.exit(1)

    # Load customer config
    config_path = os.path.join(os.path.dirname(__file__), "customers.json")
    with open(config_path) as f:
        customers = json.load(f)

    active = [c for c in customers if c.get("enabled", True)]
    if not active:
        print("No active customers in customers.json")
        return

    session = create_session(email, password)

    total_enabled = 0
    for customer in active:
        should_run = customer.get("run_today") if args.offset == 0 else customer.get("run_tomorrow")
        if not should_run:
            print(f"\nSkipping {customer['name']} (not configured for {'today' if args.offset == 0 else 'tomorrow'})")
            continue
        run_customer(session, customer, args.offset)

    print("\n══ All done ══════════════════════")


if __name__ == "__main__":
    main()
