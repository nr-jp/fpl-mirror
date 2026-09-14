#!/usr/bin/env python3
"""FPL API mirror. Runs on GitHub Actions hourly, commits full-fidelity JSON plus derived logs.

Layout:
  data/latest/bootstrap-static.json      full payload
  data/latest/fixtures.json              all 380 fixtures with stat blocks
  data/latest/event-status.json          bonus lock authority
  data/latest/set-piece-notes.json
  data/entry/{ENTRY}/entry.json, history.json, transfers.json
  data/entry/{ENTRY}/picks/gw{N}.json    every gameweek that has a deadline in the past
  data/live/gw{N}.json                   event/N/live for current (and previous until data_checked)
  data/element-summary/{id}.json         per player: history (per GW), history_past, fixtures. Daily 04 UTC
  data/leagues/overall_p1.json           world top 50
  data/leagues/overall_p200.json         ranks 9,951-10,000 (the top-10k cutoff)
  data/leagues/overall_p2000.json        ranks 99,951-100,000
  data/derived/players.csv               slim per-player table (all players, every run)
  data/derived/players_history/YYYY-MM-DD.csv  one slim snapshot per day (first run of the day)
  data/derived/news_log.csv              append-only: status / news / chance_of_playing changes
  data/derived/price_log.csv             append-only: now_cost changes
  data/derived/meta.json                 timestamp, current/next event, deadline, lock flags
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request

BASE = "https://fantasy.premierleague.com/api/"
ENTRY = int(os.environ.get("FPL_ENTRY", "1950353"))
ROOT = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(ROOT, "data")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) fpl-mirror/1.0"}


def get(path, retries=4):
    url = BASE + path
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception as e:  # noqa
            last = e
            time.sleep(2 + 3 * i)
    print(f"FAILED {url}: {last}", file=sys.stderr)
    return None


def save(obj, *parts):
    if obj is None:
        return False
    p = os.path.join(D, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    return True


def load(*parts):
    p = os.path.join(D, *parts)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


SLIM = [
    "id", "web_name", "first_name", "second_name", "team", "team_code", "element_type", "now_cost",
    "cost_change_event", "cost_change_start", "status", "chance_of_playing_next_round",
    "chance_of_playing_this_round", "news", "news_added", "selected_by_percent", "transfers_in_event",
    "transfers_out_event", "form", "points_per_game", "total_points", "event_points", "minutes",
    "starts", "goals_scored", "assists", "clean_sheets", "goals_conceded", "bonus", "bps",
    "expected_goals", "expected_assists", "expected_goal_involvements", "expected_goals_conceded",
    "expected_goals_per_90", "expected_assists_per_90", "expected_goal_involvements_per_90",
    "expected_goals_conceded_per_90", "defensive_contribution", "defensive_contribution_per_90",
    "clearances_blocks_interceptions", "recoveries", "tackles", "saves", "saves_per_90",
    "starts_per_90", "penalties_order", "corners_and_indirect_freekicks_order",
    "direct_freekicks_order", "ep_next", "ep_this", "dreamteam_count", "value_form", "value_season",
]


def elements_sorted(boot):
    return sorted(boot["elements"], key=lambda x: x["id"])


def write_players_csv(elements, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SLIM)
        for e in sorted(elements, key=lambda x: x["id"]):
            w.writerow([e.get(k, "") for k in SLIM])


def append_csv(path, header, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        for r in rows:
            w.writerow(r)


def main():
    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now.strftime("%Y-%m-%d")

    prev_boot = load("latest", "bootstrap-static.json")
    boot = get("bootstrap-static/")
    if boot is None:
        print("bootstrap failed, aborting run", file=sys.stderr)
        sys.exit(1)
    save(boot, "latest", "bootstrap-static.json")

    events = boot["events"]
    cur = next((e for e in events if e["is_current"]), None)
    nxt = next((e for e in events if e["is_next"]), None)
    cur_id = cur["id"] if cur else 0
    nxt_id = nxt["id"] if nxt else cur_id

    status = get("event-status/")
    save(status, "latest", "event-status.json")
    fixtures = get("fixtures/")
    save(fixtures, "latest", "fixtures.json")
    save(get("team/set-piece-notes/"), "latest", "set-piece-notes.json")

    # entry
    save(get(f"entry/{ENTRY}/"), "entry", str(ENTRY), "entry.json")
    hist = get(f"entry/{ENTRY}/history/")
    save(hist, "entry", str(ENTRY), "history.json")
    save(get(f"entry/{ENTRY}/transfers/"), "entry", str(ENTRY), "transfers.json")
    # picks for every gameweek whose deadline has passed (cheap, ~1 call each; refetch current only)
    for e in events:
        gw = e["id"]
        if e["deadline_time"] > stamp:
            continue
        target = os.path.join(D, "entry", str(ENTRY), "picks", f"gw{gw}.json")
        if gw == cur_id or not os.path.exists(target):
            save(get(f"entry/{ENTRY}/event/{gw}/picks/"), "entry", str(ENTRY), "picks", f"gw{gw}.json")

    # live: current event always; previous until data_checked
    for e in events:
        gw = e["id"]
        if gw == 0 or gw > cur_id:
            continue
        target = os.path.join(D, "live", f"gw{gw}.json")
        if gw == cur_id or (not e.get("data_checked")) or not os.path.exists(target):
            save(get(f"event/{gw}/live/"), "live", f"gw{gw}.json")

    # element summaries: prior-season totals + per-GW history. All players once a day
    # (04:xx UTC run) or when the file is missing; owned players every run.
    owned = set()
    cur_picks = load("entry", str(ENTRY), "picks", f"gw{cur_id}.json")
    if cur_picks:
        owned = {p["element"] for p in cur_picks.get("picks", [])}
    full = now.hour == 4 or os.environ.get("FULL") == "1"
    n_es = 0
    for e in elements_sorted(boot):
        if e["status"] == "u" and e["minutes"] == 0:
            continue
        target = os.path.join(D, "element-summary", f"{e['id']}.json")
        if full or e["id"] in owned or not os.path.exists(target):
            js = get(f"element-summary/{e['id']}/", retries=2)
            if js is not None:
                save(js, "element-summary", f"{e['id']}.json")
                n_es += 1
                time.sleep(0.15)
    print(f"element summaries fetched: {n_es}")

    # leagues
    save(get("leagues-classic/314/standings/?page_standings=1"), "leagues", "overall_p1.json")
    save(get("leagues-classic/314/standings/?page_standings=200"), "leagues", "overall_p200.json")
    save(get("leagues-classic/314/standings/?page_standings=2000"), "leagues", "overall_p2000.json")

    # derived
    elements = boot["elements"]
    write_players_csv(elements, os.path.join(D, "derived", "players.csv"))
    daily = os.path.join(D, "derived", "players_history", f"{today}.csv")
    if not os.path.exists(daily):
        write_players_csv(elements, daily)

    if prev_boot is not None:
        prev = {e["id"]: e for e in prev_boot["elements"]}
        teams = {t["id"]: t["short_name"] for t in boot["teams"]}
        news_rows, price_rows = [], []
        for e in elements:
            p = prev.get(e["id"])
            if p is None:
                continue
            if (e["status"], e["news"], e["chance_of_playing_next_round"]) != (
                p["status"], p["news"], p["chance_of_playing_next_round"]
            ):
                news_rows.append([
                    stamp, e["id"], e["web_name"], teams.get(e["team"], e["team"]),
                    p["status"], e["status"], p["chance_of_playing_next_round"],
                    e["chance_of_playing_next_round"], p["news"], e["news"], e.get("news_added", ""),
                ])
            if e["now_cost"] != p["now_cost"]:
                price_rows.append([
                    stamp, e["id"], e["web_name"], teams.get(e["team"], e["team"]),
                    p["now_cost"], e["now_cost"], e["selected_by_percent"], e["transfers_in_event"],
                    e["transfers_out_event"],
                ])
        append_csv(
            os.path.join(D, "derived", "news_log.csv"),
            ["ts", "id", "web_name", "team", "status_from", "status_to", "chance_from", "chance_to",
             "news_from", "news_to", "news_added"],
            news_rows,
        )
        append_csv(
            os.path.join(D, "derived", "price_log.csv"),
            ["ts", "id", "web_name", "team", "cost_from", "cost_to", "selected_by_percent",
             "transfers_in_event", "transfers_out_event"],
            price_rows,
        )

    meta = {
        "fetched_at": stamp,
        "current_event": cur_id,
        "next_event": nxt_id,
        "next_deadline": nxt["deadline_time"] if nxt else None,
        "current_finished": cur.get("finished") if cur else None,
        "current_data_checked": cur.get("data_checked") if cur else None,
        "current_average": cur.get("average_entry_score") if cur else None,
        "event_status": status,
        "entry_total": (hist["current"][-1]["total_points"] if hist and hist.get("current") else None),
        "entry_overall_rank": (hist["current"][-1]["overall_rank"] if hist and hist.get("current") else None),
    }
    save(meta, "derived", "meta.json")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
