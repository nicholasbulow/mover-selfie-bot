"""
Mover Selfie Bot — GitHub Actions runner
"""

import os
import sys
import json
import re
import argparse
from datetime import date, timedelta, datetime

import requests
from bs4 import BeautifulSoup

BASE = "https://admin.mover.dk"

def log(msg: str):
    print(msg, flush=True)

def format_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")

# ── Login ──────────────────────────────────────────────────────────────────────

def login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})

    # The login form lives at /dk/da/user-area/ when not authenticated
    login_page = f"{BASE}/dk/da/user-area/"
    resp = s.get(login_page)
    soup = BeautifulSoup(resp.text, "html.parser")

    form = soup.find("form")
    if not form:
        raise RuntimeError("Login form not found on page")

    # Use the form's action URL, falling back to the page URL
    action = form.get("action", "").strip()
    if not action:
        action = resp.url
    if action.startswith("/"):
        action = BASE + action

    # Build POST payload from ALL form inputs
    # - hidden fields: include their existing value (e.g. CSRF tokens)
    # - text fields: fill with email
    # - password fields: fill with password
    payload = {}
    for inp in form.find_all("input"):
        name = inp.get("name", "")
        if not name:
            continue
        kind = inp.get("type", "text").lower()
        if kind == "hidden":
            payload[name] = inp.get("value", "")
        elif kind in ("text", "email"):
            payload[name] = email
        elif kind == "password":
            payload[name] = password
        # skip submit buttons

    log(f"  Posting to: {action} | Fields: {list(payload.keys())}")

    resp = s.post(action, data=payload, headers={"Referer": login_page})
    log(f"  Post-login URL: {resp.url}")

    # Check success: if login failed, the password field will still be on the page
    post_soup = BeautifulSoup(resp.text, "html.parser")
    if post_soup.find("input", {"type": "password"}):
        raise RuntimeError("Login failed — still on login page. Check MOVER_EMAIL and MOVER_PASSWORD secrets.")

    log(f"✅ Logged in as {email}")
    return s

# ── Get driver IDs ─────────────────────────────────────────────────────────────

def get_driver_ids(session: requests.Session, customer_id: str, target_date: str) -> tuple:
    # Parse target date for comparison — trips are sorted newest first,
    # so we stop paginating once we pass the target date
    from datetime import datetime
    target_dt = datetime.strptime(target_date, "%d-%m-%Y")

    see_more_links = []
    page_url = f"{BASE}/dk/da/user-area/users/{customer_id}/trips/"
    page_num = 1

    while page_url:
        log(f"  Fetching trips page {page_num}: {page_url}")
        resp = session.get(page_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table tbody tr")
        log(f"  Page {page_num} has {len(rows)} rows")

        found_older = False
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            date_text = cells[1].get_text(strip=True).split()[0]

            # Parse this row's date
            try:
                row_dt = datetime.strptime(date_text, "%d-%m-%Y")
            except ValueError:
                continue

            # Trips are newest-first — if this row is older than target, stop paging
            if row_dt < target_dt:
                found_older = True

            if date_text == target_date:
                for a in row.find_all("a", href=True):
                    text = a.get_text(strip=True).lower()
                    if "see" in text or "more" in text or "info" in text:
                        href = a["href"]
                        full = BASE + href if href.startswith("/") else href
                        if full not in see_more_links:
                            see_more_links.append(full)

        # If we've seen rows older than our target, no need to go further back
        if found_older:
            log(f"  Passed target date on page {page_num} — stopping pagination")
            break

        # Find the "older trips" pagination link (Ældre ture >)
        next_link = None
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if "ældre" in text or "older" in text or "next" in text:
                href = a["href"]
                next_link = BASE + href if href.startswith("/") else href
                break

        if next_link and next_link != page_url:
            page_url = next_link
            page_num += 1
        else:
            break  # No more pages

    log(f"  Found {len(see_more_links)} trip(s) for {target_date} across {page_num} page(s)")

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
    return {"id": customer["id"], "name": customer["name"], "enabled": enabled, "already_on": alreadyon, "failed": failed}

# ── Main ───────────────────────────────────────────────────────────────────────

def save_run_history(results):
    """Save run summary to run_history.json in the repo via git."""
    import subprocess, tempfile, os
    if not results:
        return
    history_path = os.path.join(os.path.dirname(__file__), "run_history.json")
    try:
        existing = []
        if os.path.exists(history_path):
            with open(history_path) as f:
                existing = json.load(f)
    except Exception:
        existing = []

    existing.insert(0, {
        "timestamp": datetime.today().strftime("%Y-%m-%dT%H:%M:%S"),
        "offset":    results.get("offset", 0),
        "customers": results.get("customers", []),
        "total_enabled": results.get("total_enabled", 0),
        "total_already_on": results.get("total_already_on", 0),
    })
    # Keep last 50 runs
    existing = existing[:50]

    with open(history_path, "w") as f:
        json.dump(existing, f, indent=2)

    # Commit and push via git (available in GitHub Actions)
    try:
        subprocess.run(["git", "config", "user.email", "selfiebot@mover.dk"], check=True)
        subprocess.run(["git", "config", "user.name", "Selfie Bot"], check=True)
        subprocess.run(["git", "add", history_path], check=True)
        subprocess.run(["git", "commit", "-m", "Update run history"], check=True)
        subprocess.run(["git", "push"], check=True)
        log("✅ Run history saved")
    except Exception as e:
        log(f"⚠️  Could not save run history: {e}")


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

    # If a specific customer ID is provided, only run that one
    target_id = os.environ.get("CUSTOMER_ID", "").strip()
    if target_id:
        active = [c for c in customers if c.get("id") == target_id]
        if not active:
            log(f"Customer ID {target_id} not found in customers.json")
            return
        log(f"Running for specific customer: {active[0]['name']} ({target_id})")
    else:
        active = [c for c in customers if c.get("enabled", True)]
        if not active:
            log("No active customers configured")
            return

    session = login(email, password)

    run_results = {"offset": args.offset, "customers": [], "total_enabled": 0, "total_already_on": 0}
    for customer in active:
        result = run_customer(session, customer, args.offset)
        if result:
            run_results["customers"].append(result)
            run_results["total_enabled"]    += result["enabled"]
            run_results["total_already_on"] += result["already_on"]

    log("\n══ All done ══════════════════════")
    save_run_history(run_results)

if __name__ == "__main__":
    main()
