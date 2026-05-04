"""
Mover Selfie Bot Ã¢ÂÂ GitHub Actions runner
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

# Ã¢ÂÂÃ¢ÂÂ Login Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

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
        raise RuntimeError("Login failed Ã¢ÂÂ still on login page. Check MOVER_EMAIL and MOVER_PASSWORD secrets.")

    log(f"Ã¢ÂÂ Logged in as {email}")
    return s

# Ã¢ÂÂÃ¢ÂÂ Get driver IDs Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

def get_driver_ids(session: requests.Session, customer_id: str, target_date: str) -> tuple:
    """Use the search trips endpoint for instant results - no pagination needed."""
    # target_date is DD-MM-YYYY, search form needs MM-DD-YYYY
    parts = target_date.split("-")  # [DD, MM, YYYY]
    search_date = parts[1] + "-" + parts[0] + "-" + parts[2]  # MM-DD-YYYY

    search_url = f"{BASE}/dk/da/user-area/trips/search-trips/"

    # Get CSRF token
    resp = session.get(search_url)
    csrf = session.cookies.get("csrftoken", "")

    # POST search form
    payload = {
        "trips":                "1",
        "field0":               "",           # trip id
        "field1":               "0",          # vehicle type
        "field2":               customer_id,  # customer id
        "field3":               "",           # status
        "field4":               search_date,  # trip start from
        "field5":               search_date,  # trip start to
        "field6":               "",           # internal ref
        "field7":               "",           # origin
        "field8":               "0",          # sorting
        "csrfmiddlewaretoken":  csrf,
    }
    resp = session.post(search_url, data=payload, headers={"Referer": search_url, "X-CSRFToken": csrf})
    soup = BeautifulSoup(resp.text, "html.parser")

    see_more_links = []
    for row in soup.select("table tbody tr"):
        for a in row.find_all("a", href=True):
            href = a["href"]
            full = BASE + href if href.startswith("/") else href
            if "/trips/session/" in full and full not in see_more_links:
                see_more_links.append(full)
                break

    log(f"  Found {len(see_more_links)} trip(s) for {target_date} via search")

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
            log(f"  Route page error: {e}")

    return list(driver_ids), len(see_more_links), see_more_links


# Ã¢ÂÂÃ¢ÂÂ Enable selfie Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

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

# Ã¢ÂÂÃ¢ÂÂ Run customer Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ


def run_customer(session: requests.Session, customer: dict, date_offset: int):
    target     = date.today() + timedelta(days=date_offset)
    target_str = format_date(target)
    label      = "today" if date_offset == 0 else "tomorrow"

    log(f"\nÃ¢ÂÂÃ¢ÂÂ {customer['name']} ({customer['id']}) Ã¢ÂÂ {target_str} ({label})")

    driver_ids, trip_count, route_links = get_driver_ids(session, customer["id"], target_str)

    if not trip_count:
        log(f"  Ã¢ÂÂ Ã¯Â¸Â  No trips found for {target_str}")
        return
    if not driver_ids:
        log(f"  Ã¢ÂÂ Ã¯Â¸Â  No driver IDs found ({trip_count} trips)")
        return

    log(f"  Found {len(driver_ids)} unique driver(s)")

    enabled = alreadyon = failed = 0
    for did in sorted(driver_ids):
        result = enable_selfie(session, did)
        if   result == "enabled":    log(f"  Ã¢ÂÂ Driver {did}: enabled");    enabled += 1
        elif result == "already_on": log(f"  Ã¢ÂÂ­Ã¯Â¸Â  Driver {did}: already on"); alreadyon += 1
        else:                        log(f"  Ã¢ÂÂ Driver {did}: {result}");    failed += 1

    log(f"  Ã¢ÂÂÃ¢ÂÂ Ã¢ÂÂ {enabled}  Ã¢ÂÂ­Ã¯Â¸Â  {alreadyon}  Ã¢ÂÂ {failed}")
    # Extract trip IDs from route URLs
    trip_ids = []
    import re as _re
    for url in route_links:
        m = _re.search(r"/trips/session/(\d+)", url)
        if m:
            trip_ids.append(m.group(1))
    return {"id": customer["id"], "name": customer["name"], "enabled": enabled, "already_on": alreadyon, "failed": failed, "trip_ids": trip_ids}

# Ã¢ÂÂÃ¢ÂÂ Main Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ

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

    # Collect all trip IDs across all customers
    all_trip_ids = []
    for c in results.get("customers", []):
        all_trip_ids.extend(c.get("trip_ids", []))

    existing.insert(0, {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "offset":    results.get("offset", 0),
        "customers": results.get("customers", []),
        "total_enabled": results.get("total_enabled", 0),
        "total_already_on": results.get("total_already_on", 0),
        "trip_ids": list(dict.fromkeys(all_trip_ids)),  # deduplicated
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
        log("Ã¢ÂÂ Run history saved")
    except Exception as e:
        log(f"Ã¢ÂÂ Ã¯Â¸Â  Could not save run history: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    email    = os.environ.get("MOVER_EMAIL")
    password = os.environ.get("MOVER_PASSWORD")
    if not email or not password:
        log("Ã¢ÂÂ MOVER_EMAIL and MOVER_PASSWORD environment variables required")
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
        else:
            # Still record the customer even if no trips found
            run_results["customers"].append({"id": customer["id"], "name": customer["name"], "enabled": 0, "already_on": 0, "failed": 0, "trip_ids": []})

    log("\nÃ¢ÂÂÃ¢ÂÂ All done Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ")
    save_run_history(run_results)

if __name__ == "__main__":
    main()
