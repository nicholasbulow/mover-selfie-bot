"""
Mover Selfie Checker - runs on a schedule, notifies Teams when all selfies are taken
"""

import os
import sys
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

BASE = "https://admin.mover.dk"

def log(msg):
    print(msg, flush=True)

def login(email, password):
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    login_page = f"{BASE}/dk/da/user-area/"
    resp = s.get(login_page)
    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form")
    if not form:
        raise RuntimeError("Login form not found")
    action = form.get("action", "").strip() or resp.url
    if action.startswith("/"):
        action = BASE + action
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
    resp = s.post(action, data=payload, headers={"Referer": login_page})
    post_soup = BeautifulSoup(resp.text, "html.parser")
    if post_soup.find("input", {"type": "password"}):
        raise RuntimeError("Login failed")
    log(f"Logged in as {email}")
    return s

def check_selfie_taken(session, trip_id):
    url = f"{BASE}/dk/da/user-area/trips/session/{trip_id}"
    try:
        resp = session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            href = a["href"].lower()
            if "selfie" in text and ("s3" in href or "selfie" in href):
                return True
        return False
    except Exception as e:
        log(f"  Error checking trip {trip_id}: {e}")
        return None

def send_teams_notification(webhook_url, run_entry, confirmed, total):
    offset_label = "Tomorrow" if run_entry.get("offset") == 1 else "Today"
    customers = run_entry.get("customers", [])
    cust_names = ", ".join(c["name"] for c in customers) if customers else "All customers"
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "3dbfa0",
        "summary": "All selfies received",
        "sections": [{
            "activityTitle": "All selfies received",
            "activitySubtitle": f"{cust_names} - {offset_label}",
            "facts": [
                {"name": "Routes confirmed", "value": f"{confirmed}/{total}"},
                {"name": "Run time", "value": run_entry.get("timestamp", "").replace("T", " ").replace("Z", "") + " UTC"},
            ],
            "markdown": True
        }],
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "Open Selfie Bot Dashboard",
            "targets": [{"os": "default", "uri": "https://nicholasbulow.github.io/mover-selfie-bot/"}]
        }]
    }
    resp = requests.post(webhook_url, json=payload, timeout=10)
    log(f"  Teams notification sent: {resp.status_code}")

def main():
    email    = os.environ.get("MOVER_EMAIL")
    password = os.environ.get("MOVER_PASSWORD")
    webhook  = os.environ.get("TEAMS_WEBHOOK_URL")
    if not email or not password:
        log("MOVER_EMAIL and MOVER_PASSWORD required")
        sys.exit(1)
    if not webhook:
        log("TEAMS_WEBHOOK_URL required")
        sys.exit(1)

    history_path = os.path.join(os.path.dirname(__file__), "run_history.json")
    if not os.path.exists(history_path):
        log("No run_history.json found")
        return

    with open(history_path) as f:
        history = json.load(f)
    if not history:
        log("run_history.json is empty")
        return

    latest = history[0]

    if latest.get("selfies_confirmed"):
        log("Already notified for latest run")
        return

    try:
        run_time = datetime.fromisoformat(latest["timestamp"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - run_time
        if age > timedelta(hours=12):
            log(f"Latest run is {age} old - skipping")
            return
    except Exception as e:
        log(f"Could not parse timestamp: {e}")

    trip_ids = latest.get("trip_ids", [])
    if not trip_ids:
        log("No trip IDs in latest run")
        return

    log(f"Checking {len(trip_ids)} route(s) from {latest.get('timestamp')}")
    session = login(email, password)

    confirmed = 0
    unknown = 0
    for trip in trip_ids:
        trip_id = trip["id"] if isinstance(trip, dict) else trip
        result = check_selfie_taken(session, trip_id)
        if result is True:
            log(f"  Route {trip_id}: selfie taken")
            confirmed += 1
        elif result is False:
            log(f"  Route {trip_id}: no selfie yet")
        else:
            log(f"  Route {trip_id}: unknown")
            unknown += 1

    total = len(trip_ids)
    log(f"  {confirmed}/{total} selfies confirmed ({unknown} unknown)")

    if confirmed == total and unknown == 0:
        log("All selfies received! Sending Teams notification...")
        send_teams_notification(webhook, latest, confirmed, total)
        history[0]["selfies_confirmed"] = True
        history[0]["selfies_confirmed_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
        try:
            subprocess.run(["git", "config", "user.email", "selfiebot@mover.dk"], check=True)
            subprocess.run(["git", "config", "user.name", "Selfie Bot"], check=True)
            subprocess.run(["git", "add", history_path], check=True)
            subprocess.run(["git", "commit", "-m", "Mark selfies confirmed"], check=True)
            subprocess.run(["git", "push"], check=True)
        except Exception as e:
            log(f"Could not update history: {e}")
    else:
        log("Not all selfies received yet - will check again next run")

if __name__ == "__main__":
    main()
