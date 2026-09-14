#!/usr/bin/env python3
"""
CAESAR v4: full-pool FPL decision engine fed by the fpl-mirror repo.

Usage (inside a fresh clone of https://github.com/nr-jp/fpl-mirror):
    python caesar/caesar.py --data data --gw 5 --horizon 6 [--fts 2] [--json out.json]

Every player in the game is priced automatically. Nothing is hand-entered except
caesar/overrides.json (minutes / availability judgments from press conferences).

Layers
  1. team strength     FPL strength ratings blended with realised season xG for/against
  2. minutes           p_start from recent starts + status/chance flags + overrides
  3. rates             xG90 / xA90 shrunk toward last-season rates (element-summary history_past)
                       and position-price priors; defcon hit rate, bonus, saves, cards
  4. points            expected points per player per GW over the horizon
  5. optimiser         MILP (scipy HiGHS): squad, XI, captain, per transfer count / chip branch
  6. branch table      HOLD, 1..FT free, one hit, WC, FH; TC and BB overlays
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_PTS = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}
CS_PTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
DEFCON_THR = {"GK": None, "DEF": 10, "MID": 12, "FWD": 12}
SQUAD = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_MIN = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}

# registered parameters (change here, log the change)
DISCOUNT = 0.92          # per-GW discount inside the horizon
BENCH_W = 0.10           # weight on bench players' points (auto-sub value)
FT_VALUE = 0.8           # points-equivalent value of one banked free transfer
HIT_COST = 4.0
WC_HORIZON = 8
WC_PREMIUM = 6.0         # WC fires when it beats the best non-chip branch by this over WC_HORIZON
FH_PREMIUM = 10.0        # FH fires when GW+0 squad beats the current squad by this
TC_THRESHOLD = 7.0       # captain GW+0 xPts to spend TC
BB_THRESHOLD = 10.0      # bench GW+0 xPts to spend BB
K_SHRINK_RATE = 10.0     # games of prior weight on xG/xA rates
GOAL_BLEND = 0.15        # weight on actual goals vs xG in the observed rate
HOME_BASE, AWAY_BASE = 1.50, 1.20   # league-average expected goals, home / away team


# ----------------------------------------------------------------------------- data
class Data:
    def __init__(self, root):
        self.root = root
        self.boot = self._j("latest/bootstrap-static.json")
        self.fixtures = self._j("latest/fixtures.json")
        self.status = self._j("latest/event-status.json")
        self.teams = {t["id"]: t for t in self.boot["teams"]}
        self.short = {t["id"]: t["short_name"] for t in self.boot["teams"]}
        self.el = {e["id"]: e for e in self.boot["elements"]}
        self.events = {e["id"]: e for e in self.boot["events"]}
        self.cur = next((e["id"] for e in self.boot["events"] if e["is_current"]), 0)
        self.nxt = next((e["id"] for e in self.boot["events"] if e["is_next"]), self.cur)
        self.live = {}
        for gw in range(1, self.cur + 1):
            p = f"live/gw{gw}.json"
            if self._exists(p):
                self.live[gw] = {x["id"]: x for x in self._j(p)["elements"]}
        self.summ = {}
        d = os.path.join(root, "element-summary")
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.endswith(".json"):
                    self.summ[int(fn[:-5])] = json.load(open(os.path.join(d, fn)))
        ov = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides.json")
        self.overrides = json.load(open(ov)) if os.path.exists(ov) else {}

    def _j(self, rel):
        return json.load(open(os.path.join(self.root, rel)))

    def _exists(self, rel):
        return os.path.exists(os.path.join(self.root, rel))

    def entry(self, entry_id):
        base = f"entry/{entry_id}"
        hist = self._j(f"{base}/history.json")
        transfers = self._j(f"{base}/transfers.json")
        picks_gw = self.cur
        picks = self._j(f"{base}/picks/gw{picks_gw}.json")
        return hist, transfers, picks

    def finished_gws(self):
        return [g for g, e in self.events.items() if e["finished"] and g <= self.cur]

    def gw_locked(self, gw):
        e = self.events[gw]
        return bool(e.get("data_checked"))


# ------------------------------------------------------------------- team strength
def team_strength(D):
    """team -> (attack_home, attack_away, defence_home, defence_away), multipliers around 1.0.
    attack: goals-scored factor; defence: goals-conceded factor (lower = better defence).
    Prior: FPL strength_overall_home/away (2-5 FDR scale; the attack/defence fields are 0 in 2026/27).
    Blend: realised season xG for / against per game (from live GW element xG), weight g/(g+6)."""
    ATT_PRIOR = {5: 1.35, 4: 1.15, 3: 0.95, 2: 0.78, 1: 0.65}
    DEF_PRIOR = {5: 0.65, 4: 0.85, 3: 1.05, 2: 1.25, 1: 1.40}
    t = D.teams
    ids = sorted(t)
    fpl = {}
    for i in ids:
        sh, sa = t[i].get("strength_overall_home") or 3, t[i].get("strength_overall_away") or 3
        fpl[i] = (ATT_PRIOR[sh], ATT_PRIOR[sa], DEF_PRIOR[sh], DEF_PRIOR[sa])

    xgf = defaultdict(float); xga = defaultdict(float); games = defaultdict(int)
    for gw, live in D.live.items():
        fx_gw = [f for f in D.fixtures if f["event"] == gw and f["finished"]]
        team_xg = defaultdict(float)
        for eid, row in live.items():
            e = D.el.get(eid)
            if not e:
                continue
            team_xg[e["team"]] += float(row["stats"].get("expected_goals", 0) or 0)
        for f in fx_gw:
            h, a = f["team_h"], f["team_a"]
            nh = sum(1 for g in fx_gw if h in (g["team_h"], g["team_a"]))
            na = sum(1 for g in fx_gw if a in (g["team_h"], g["team_a"]))
            xgh, xga_ = team_xg[h] / max(nh, 1), team_xg[a] / max(na, 1)
            xgf[h] += xgh; xga[h] += xga_; games[h] += 1
            xgf[a] += xga_; xga[a] += xgh; games[a] += 1
    n_all = sum(games.values())
    lg_avg = (sum(xgf.values()) / n_all) if n_all else 1.35
    out = {}
    for i in ids:
        g = games.get(i, 0)
        w = g / (g + 6.0)
        af = (xgf[i] / g / lg_avg) if g else 1.0
        df = (xga[i] / g / lg_avg) if g else 1.0
        fa_h, fa_a, fd_h, fd_a = fpl[i]
        pa, pd_ = (fa_h + fa_a) / 2, (fd_h + fd_a) / 2
        lvl_a = w * af + (1 - w) * pa
        lvl_d = w * df + (1 - w) * pd_
        out[i] = (lvl_a * fa_h / pa, lvl_a * fa_a / pa, lvl_d * fd_h / pd_, lvl_d * fd_a / pd_)
    return out, lg_avg


def fixture_layer(D, strength, gw_from, H):
    """team -> list over horizon of (lambda_for, lambda_against, n_fixtures). Blank GW -> (0,0,0)."""
    out = {i: [] for i in D.teams}
    for w in range(H):
        gw = gw_from + w
        fx = [f for f in D.fixtures if f["event"] == gw]
        per = {i: [0.0, 0.0, 0] for i in D.teams}
        for f in fx:
            h, a = f["team_h"], f["team_a"]
            ah, _, dh, _ = strength[h]
            _, aa, _, da = strength[a]
            lam_h = HOME_BASE * ah * da
            lam_a = AWAY_BASE * aa * dh
            per[h][0] += lam_h; per[h][1] += lam_a; per[h][2] += 1
            per[a][0] += lam_a; per[a][1] += lam_h; per[a][2] += 1
        for i in D.teams:
            out[i].append(tuple(per[i]))
    return out


# --------------------------------------------------------------------- player model
PRIOR_G90 = {"GK": 0.0, "DEF": 0.04, "MID": 0.10, "FWD": 0.25}
PRIOR_A90 = {"GK": 0.0, "DEF": 0.06, "MID": 0.12, "FWD": 0.10}
PRIOR_DEFCON = {"GK": 0.0, "DEF": 0.35, "MID": 0.12, "FWD": 0.03}


def price_prior(pos, price):
    """Position-price prior for attacking rates, per 90."""
    if pos == "GK":
        return 0.0, 0.0
    if pos == "DEF":
        return 0.03 + 0.012 * max(0, price - 4.0), 0.05 + 0.02 * max(0, price - 4.0)
    if pos == "MID":
        return 0.06 + 0.055 * max(0, price - 4.5), 0.08 + 0.04 * max(0, price - 4.5)
    return 0.15 + 0.065 * max(0, price - 4.5), 0.06 + 0.02 * max(0, price - 4.5)


def player_model(D, strength, lg_avg):
    """Return dict id -> model dict with rates, p_start, etc."""
    models = {}
    team_games = defaultdict(int)
    for gw in D.finished_gws():
        for f in D.fixtures:
            if f["event"] == gw and f["finished"]:
                team_games[f["team_h"]] += 1; team_games[f["team_a"]] += 1
    for eid, e in D.el.items():
        pos = POS[e["element_type"]]
        price = e["now_cost"] / 10.0
        mins = e["minutes"]
        g90p, a90p = price_prior(pos, price)
        # last-season rates from element-summary history_past
        s = D.summ.get(eid)
        past = None
        if s and s.get("history_past"):
            hp = s["history_past"][-1]
            if hp.get("minutes", 0) >= 600:
                past = hp
        if past:
            pm = past["minutes"] / 90.0
            pg = float(past.get("expected_goals", 0) or 0) / pm
            pa = float(past.get("expected_assists", 0) or 0) / pm
            # blend price prior with last season (club change unknown here; equal weights)
            g90p = 0.5 * g90p + 0.5 * ((1 - GOAL_BLEND) * pg + GOAL_BLEND * past.get("goals_scored", 0) / pm)
            a90p = 0.5 * a90p + 0.5 * pa
        n90 = mins / 90.0
        xg = float(e.get("expected_goals", 0) or 0)
        xa = float(e.get("expected_assists", 0) or 0)
        g_obs = (1 - GOAL_BLEND) * xg + GOAL_BLEND * e["goals_scored"]
        g90 = (g_obs + g90p * K_SHRINK_RATE) / (n90 + K_SHRINK_RATE)
        a90 = (xa + a90p * K_SHRINK_RATE) / (n90 + K_SHRINK_RATE)

        # minutes: recent starts from element-summary history, else season starts
        starts_recent = []
        if s:
            hist = sorted(s.get("history", []), key=lambda r: r["round"])
            for r in hist[-5:]:
                starts_recent.append((r["round"], r.get("starts", 1 if r["minutes"] >= 60 else 0), r["minutes"]))
        tg = max(team_games[e["team"]], 1)
        if starts_recent:
            # starts_recent is chronological; newest gets the largest weight
            wts = [0.4, 0.3, 0.15, 0.1, 0.05][: len(starts_recent)][::-1]
            wts = np.array(wts) / sum(wts)
            p_start = float(sum(w * (1 if st else 0) for w, (_, st, _) in zip(wts, starts_recent)))
            # season-level anchor
            p_start = 0.75 * p_start + 0.25 * min(1.0, e["starts"] / tg)
        else:
            p_start = min(1.0, e["starts"] / tg) if tg else 0.3
            if mins == 0 and e["starts"] == 0:
                p_start = 0.15
        # availability flags
        status, chance = e["status"], e.get("chance_of_playing_next_round")
        p_next = p_start
        p_later = p_start
        if status in ("i", "s", "u", "n"):
            p_next = 0.0
            p_later = 0.0 if status in ("u", "n") else 0.5 * p_start
        elif status == "d":
            c = (chance if chance is not None else 50) / 100.0
            p_next = p_start * c
            p_later = p_start * (0.5 + 0.5 * c)
        ov = D.overrides.get(str(eid))
        if ov:
            if "p_start_next" in ov:
                p_next = float(ov["p_start_next"])
            if "p_start_later" in ov:
                p_later = float(ov["p_start_later"])
            if "out_until_gw" in ov:
                pass  # handled in points()

        # defcon hit rate from live GW explains
        hits, apps = 0, 0
        for gw, live in D.live.items():
            row = live.get(eid)
            if not row or row["stats"]["minutes"] == 0:
                continue
            apps += 1
            for ex in row.get("explain", []):
                for st in ex.get("stats", []):
                    if st["identifier"] == "defensive_contribution" and st["points"] > 0:
                        hits += 1
        dc_rate = (hits + PRIOR_DEFCON[pos] * 3) / (apps + 3)
        if pos == "GK":
            dc_rate = 0.0
        bonus_obs = e["bonus"]
        pb = 0.25 if pos in ("GK", "DEF") else 0.10 + 1.2 * (g90 + a90)
        bonus90 = (bonus_obs + pb * 10) / (max(e["starts"], 1) + 10)   # bonus is noisy: 10-app prior
        saves90 = 0.0
        if pos == "GK":
            saves90 = (e["saves"] + 3.0 * 3) / (n90 + 3)
        yc90 = (e.get("yellow_cards", 0) + 0.12 * 6) / (n90 + 6)
        models[eid] = dict(
            id=eid, name=e["web_name"], team=e["team"], club=D.short[e["team"]], pos=pos, price=price,
            g90=g90, a90=a90, p_next=p_next, p_later=p_later, dc_rate=dc_rate, bonus90=bonus90,
            saves90=saves90, yc90=yc90, own=float(e["selected_by_percent"]) / 100.0,
            status=status, news=e.get("news", ""), chance=chance, override=ov or {},
        )
    return models


def points_matrix(D, models, fixlayer, gw_from, H):
    """id -> np.array of expected points per GW over horizon."""
    XP = {}
    for eid, m in models.items():
        pos = m["pos"]
        row = np.zeros(H)
        for w in range(H):
            lam_for, lam_against, nfix = fixlayer[m["team"]][w]
            if nfix == 0:
                continue
            gw = gw_from + w
            p = m["p_next"] if w == 0 else m["p_later"]
            ou = m["override"].get("out_until_gw")
            if ou and gw < int(ou):
                p = 0.0
            if p <= 0:
                continue
            # per-fixture averages, then multiplied by the number of fixtures in the GW
            lf, la = lam_for / nfix, lam_against / nfix
            att = lf / lg_avg_global[0]
            g = m["g90"] * att
            a = m["a90"] * att
            cs = math.exp(-la)
            p60 = 0.97 if pos == "GK" else 0.86
            app = p * (2 * p60 + 1 * (1 - p60)) + (1 - p) * (0.30 if pos in ("MID", "FWD") else 0.12) * 1.0
            scale = p * (p60 + 0.6 * (1 - p60)) + (1 - p) * 0.30 * 0.3
            x = app
            x += scale * (GOAL_PTS[pos] * g + 3 * a)
            x += p * p60 * CS_PTS[pos] * cs
            x += scale * 2 * m["dc_rate"]
            x += scale * m["bonus90"]
            if pos == "GK":
                x += scale * m["saves90"] / 3.0
            if pos in ("GK", "DEF"):
                x -= scale * 0.45 * la
            x -= scale * m["yc90"]
            row[w] = x * nfix
        XP[eid] = row
    return XP


lg_avg_global = [1.35]
FORCE_IN, FORCE_OUT = [], []


# ------------------------------------------------------------------------ optimiser
class Optimiser:
    def __init__(self, D, models, XP, incumbents, sell_prices, bank, H):
        self.D, self.M, self.XP = D, models, XP
        self.inc = set(incumbents)
        self.sell = sell_prices          # id -> sell price (incumbents)
        self.bank = bank
        self.H = H
        # candidate pool: incumbents + anyone plausible
        ids = [i for i, m in models.items()
               if i in self.inc or (m["status"] not in ("u", "n") and max(m["p_next"], m["p_later"]) >= 0.25
                                    and XP[i].sum() > 0)]
        self.ids = sorted(ids)
        self.idx = {i: k for k, i in enumerate(self.ids)}
        self.n = len(self.ids)
        disc = np.array([DISCOUNT ** w for w in range(H)])
        self.val = np.array([(XP[i] * disc).sum() for i in self.ids])          # horizon value
        self.val0 = np.array([XP[i][0] for i in self.ids])                     # GW+0 value
        self.cost = np.array([self.sell[i] if i in self.inc else models[i]["price"] for i in self.ids])
        self.pos = [models[i]["pos"] for i in self.ids]
        self.team = [models[i]["team"] for i in self.ids]

    def budget(self):
        return self.bank + sum(self.sell[i] for i in self.inc)

    def solve(self, max_transfers, horizon_weights=None, force_in=(), force_out=(), gw0_only=False):
        need = len([i for i in FORCE_IN if i not in self.inc]) + len([i for i in FORCE_OUT if i in self.inc])
        if max_transfers >= need:          # probes only bind on branches that can afford them
            force_in = list(force_in) + FORCE_IN
            force_out = list(force_out) + FORCE_OUT
        n = self.n; m = 3 * n
        val = self.val0 if gw0_only else self.val
        A, lb, ub = [], [], []

        def con(r, lo, hi):
            A.append(r); lb.append(lo); ub.append(hi)

        for P, q in SQUAD.items():
            r = np.zeros(m); r[[k for k in range(n) if self.pos[k] == P]] = 1; con(r, q, q)
        r = np.zeros(m); r[n:2 * n] = 1; con(r, 11, 11)
        for P in SQUAD:
            r = np.zeros(m); r[[n + k for k in range(n) if self.pos[k] == P]] = 1; con(r, XI_MIN[P], XI_MAX[P])
        r = np.zeros(m); r[:n] = self.cost; con(r, 0, self.budget() + 1e-6)
        for t in set(self.team):
            r = np.zeros(m); r[[k for k in range(n) if self.team[k] == t]] = 1; con(r, 0, 3)
        r = np.zeros(m); r[[k for k in range(n) if self.ids[k] in self.inc]] = 1
        con(r, max(0, 15 - max_transfers), 15)
        for k in range(n):
            r = np.zeros(m); r[k] = -1; r[n + k] = 1; con(r, -1, 0)      # y <= x
            r = np.zeros(m); r[n + k] = -1; r[2 * n + k] = 1; con(r, -1, 0)  # z <= y
        r = np.zeros(m); r[2 * n:] = 1; con(r, 1, 1)
        for i in force_in:
            if i in self.idx:
                r = np.zeros(m); r[self.idx[i]] = 1; con(r, 1, 1)
        for i in force_out:
            if i in self.idx:
                r = np.zeros(m); r[self.idx[i]] = 1; con(r, 0, 0)
        c = -np.concatenate([BENCH_W * val, (1 - BENCH_W) * val, self.val0])
        res = milp(c, constraints=LinearConstraint(np.array(A), lb, ub),
                   integrality=np.ones(m), bounds=Bounds(0, 1),
                   options={"time_limit": 60})
        if not res.success or res.x is None:
            return None
        x = res.x[:n].round().astype(bool); y = res.x[n:2 * n].round().astype(bool); z = res.x[2 * n:].round().astype(bool)
        squad = [self.ids[k] for k in range(n) if x[k]]
        xi = [self.ids[k] for k in range(n) if y[k]]
        cap = [self.ids[k] for k in range(n) if z[k]][0]
        spend = float(sum(self.cost[k] for k in range(n) if x[k]))
        return dict(obj=-res.fun, squad=squad, xi=xi, cap=cap, bank=round(self.budget() - spend, 1))

    def value_of(self, squad, xi, cap):
        """Horizon value of a fixed squad with a weekly re-picked XI and captain (greedy per GW)."""
        tot = 0.0; per_gw = []
        for w in range(self.H):
            pts = {i: self.XP[i][w] for i in squad}
            xi_w = best_xi(pts, {i: self.M[i]["pos"] for i in squad})
            capw = max(xi_w, key=lambda i: pts[i])
            v = sum(pts[i] for i in xi_w) + pts[capw]
            bench = sum(pts[i] for i in squad if i not in xi_w)
            per_gw.append(v + BENCH_W * bench)
            tot += (DISCOUNT ** w) * (v + BENCH_W * bench)
        return tot, per_gw


def best_xi(pts, pos):
    """Greedy valid XI maximising points."""
    by = defaultdict(list)
    for i, p in pos.items():
        by[p].append(i)
    for p in by:
        by[p].sort(key=lambda i: -pts[i])
    xi = [by["GK"][0]] if by["GK"] else []
    xi += by["DEF"][:3] + by["MID"][:2] + by["FWD"][:1]
    rest = by["DEF"][3:] + by["MID"][2:] + by["FWD"][1:]
    rest.sort(key=lambda i: -pts[i])
    # respect XI_MAX
    cnt = {"DEF": 3, "MID": 2, "FWD": 1}
    for i in rest:
        if len(xi) >= 11:
            break
        p = pos[i]
        if cnt[p] < XI_MAX[p]:
            xi.append(i); cnt[p] += 1
    return xi


# ----------------------------------------------------------------------- the gate
def run_gate(D, models, XP, XP8, incumbents, sell, bank, fts, H, chips_left):
    opt = Optimiser(D, models, XP, incumbents, sell, bank, H)
    hold = opt.solve(0)
    hold_val, hold_gw = opt.value_of(hold["squad"], hold["xi"], hold["cap"])
    rows = []
    max_t = fts + 1
    for t in range(0, max_t + 1):
        sol = opt.solve(t)
        if sol is None:
            continue
        moves = len(set(sol["squad"]) - set(incumbents))
        hits = max(0, moves - fts) * HIT_COST
        banked = min(5, fts - moves + 1) if moves <= fts else 1
        v, per = opt.value_of(sol["squad"], sol["xi"], sol["cap"])
        d = v - hold_val - hits + FT_VALUE * (banked - min(5, fts + 1))
        rows.append(dict(chip="NONE", moves=moves, hits=hits, banked=banked, D=d, raw=v - hold_val,
                         gw0=per[0], sol=sol,
                         in_=sorted(set(sol["squad"]) - set(incumbents)), out=sorted(set(incumbents) - set(sol["squad"]))))
    best_none = max(rows, key=lambda r: r["D"])
    # wildcard: 8-GW horizon, premium over best non-chip branch on the same horizon
    wc = None
    if "wildcard" in chips_left:
        opt8 = Optimiser(D, models, XP8, incumbents, sell, bank, WC_HORIZON)
        wsol = opt8.solve(15)
        b8 = opt8.solve(len(best_none["in_"]))
        if wsol and b8:
            wv, wper = opt8.value_of(wsol["squad"], wsol["xi"], wsol["cap"])
            bv, _ = opt8.value_of(b8["squad"], b8["xi"], b8["cap"])
            prem = wv - bv + best_none["hits"]
            wc = dict(chip="WC", moves=len(set(wsol["squad"]) - set(incumbents)), hits=0, banked=fts,
                      value8=wv, D=prem, gw0=wper[0], sol=wsol, premium=prem, fires=bool(prem >= WC_PREMIUM),
                      in_=sorted(set(wsol["squad"]) - set(incumbents)), out=sorted(set(incumbents) - set(wsol["squad"])))
    fh = None
    if "freehit" in chips_left and not (wc and wc["fires"]):
        fsol = opt.solve(15, gw0_only=True)
        if fsol:
            fv = sum(XP[i][0] for i in fsol["xi"]) + XP[fsol["cap"]][0]
            fh = dict(chip="FH", D=fv - best_none["gw0"], gw0=fv, sol=fsol, fires=bool((fv - best_none["gw0"]) >= FH_PREMIUM))
    return dict(opt=opt, hold=hold, hold_val=hold_val, hold_gw=hold_gw, rows=sorted(rows, key=lambda r: -r["D"]),
                best_none=best_none, wc=wc, fh=fh)


# ----------------------------------------------------------------------- reporting
def nm(models, i):
    m = models[i]
    return f"{m['name']} ({m['club']})"


def fmt_player(D, models, i, XP=None):
    m = models[i]
    s = f"{m['name']} ({m['club']} {m['pos']} {m['price']:.1f})"
    if XP is not None:
        s += f" {XP[i][0]:.1f}"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--entry", type=int, default=1950353)
    ap.add_argument("--gw", type=int, default=None, help="gameweek to optimise for (default: next)")
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--fts", type=int, default=None)
    ap.add_argument("--bank", type=float, default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--force-in", default="", help="comma list of Name:CLUB to force into every branch")
    ap.add_argument("--force-out", default="", help="comma list of Name:CLUB to force out of every branch")
    a = ap.parse_args()

    D = Data(a.data)
    gw = a.gw or D.nxt
    H = a.horizon
    strength, lg_avg = team_strength(D)
    lg_avg_global[0] = lg_avg
    models = player_model(D, strength, lg_avg)
    fix = fixture_layer(D, strength, gw, max(H, WC_HORIZON))
    XPfull = points_matrix(D, models, fix, gw, max(H, WC_HORIZON))
    XP = {i: v[:H] for i, v in XPfull.items()}
    XP8 = {i: v[:WC_HORIZON] for i, v in XPfull.items()}

    hist, transfers, picks = D.entry(a.entry)
    incumbents = [p["element"] for p in picks["picks"]]
    # sell prices: purchase price + half the rise (rounded down to 0.1)
    buy = {}
    for t in sorted(transfers, key=lambda t: (t["event"], t["time"])):
        buy[t["element_in"]] = t["element_in_cost"] / 10.0
    # initial squad purchases at GW1 price: assume current price if no transfer record and
    # cost_change_start gives the rise since season start
    sell = {}
    for i in incumbents:
        e = D.el[i]
        now = e["now_cost"] / 10.0
        if i in buy:
            b = buy[i]
        else:
            b = (e["now_cost"] - e["cost_change_start"]) / 10.0
        sell[i] = round(b + math.floor(max(0.0, now - b) * 10 / 2) / 10, 1) if now > b else now
    last = hist["current"][-1]
    bank = a.bank if a.bank is not None else last["bank"] / 10.0
    # free transfers: 1 + carried; derive from history (transfers made vs available), cap 5
    if a.fts is None:
        # 1 FT for GW2; each later GW: carry = min(5, carry - used + 1), floor 1
        fts = 1
        for row in hist["current"]:
            if row["event"] < 2:
                continue
            fts = max(1, min(5, fts - row["event_transfers"] + 1))
    else:
        fts = a.fts
    chips_used = {c["name"] for c in hist.get("chips", [])}
    chips_left = {"wildcard", "freehit", "bboost", "3xc"} - chips_used

    def resolve(spec):
        ids = []
        for tok in [t for t in spec.split(",") if t.strip()]:
            n, _, c = tok.strip().partition(":")
            hits = [i for i, m in models.items() if m["name"].lower() == n.lower() and (not c or m["club"].lower() == c.lower())]
            if len(hits) != 1:
                sys.exit(f"force spec {tok!r} matched {len(hits)} players: {[nm(models, i) for i in hits]}")
            ids.append(hits[0])
        return ids
    FORCE_IN[:] = resolve(a.force_in)
    FORCE_OUT[:] = resolve(a.force_out)
    if FORCE_IN or FORCE_OUT:
        print("PROBE: force in", [nm(models, i) for i in FORCE_IN], "force out", [nm(models, i) for i in FORCE_OUT])
    G = run_gate(D, models, XP, XP8, incumbents, sell, bank, fts, H, chips_left)

    # ---- print
    ev = D.events[gw]
    print(f"CAESAR v4 | GW{gw} | deadline {ev['deadline_time']} | horizon {H} | FTs {fts} | bank {bank:.1f} | chips {sorted(chips_left)}")
    print(f"team strength blend: league avg xG/game {lg_avg:.2f}; live GWs {sorted(D.live)}; element summaries {len(D.summ)}")
    print("\nCURRENT SQUAD (GW+0 xPts, horizon xPts, p_start next, sell):")
    for i in sorted(incumbents, key=lambda i: -XP[i].sum()):
        m = models[i]
        flag = f" [{m['status']}{'' if m['chance'] is None else ' ' + str(m['chance']) + '%'}] {m['news']}" if m["status"] != "a" else ""
        print(f"  {m['name']:<16}{m['club']:<4}{m['pos']:<4}{m['price']:>5.1f} sell {sell[i]:>4.1f} | {XP[i][0]:>4.1f} | {XP[i].sum():>5.1f} | p {m['p_next']:.2f}{flag}")
    print(f"\nHOLD value over {H}: {G['hold_val']:.1f} (GW+0 {G['hold_gw'][0]:.1f})")
    print("\nBRANCH TABLE (D = horizon points vs HOLD, hits and FT value included)")
    print(f"{'chip':<5}{'mv':>3}{'hit':>4}{'bank':>5}{'D':>7}{'GW0':>6}  moves")
    for r in G["rows"]:
        ins = ", ".join(nm(models, i) for i in r["in_"]); outs = ", ".join(nm(models, i) for i in r["out"])
        print(f"{r['chip']:<5}{r['moves']:>3}{int(r['hits']):>4}{r['banked']:>5}{r['D']:>+7.1f}{r['gw0']:>6.1f}  IN {ins} | OUT {outs} | C {models[r['sol']['cap']]['name']} | ITB {r['sol']['bank']}")
    if G["wc"]:
        w = G["wc"]
        print(f"\nWILDCARD ({WC_HORIZON} GW): squad value {w['value8']:.1f}; premium over best transfer branch {w['premium']:+.1f} (threshold {WC_PREMIUM}) -> {'FIRE' if w['fires'] else 'HOLD'}")
        print("  WC squad: " + ", ".join(f"{nm(models, i)} {models[i]['price']:.1f} [{XP8[i].sum():.0f}]" for i in sorted(w["sol"]["squad"], key=lambda i: (list(SQUAD).index(models[i]['pos']), -XP8[i].sum()))))
        print(f"  IN {', '.join(nm(models, i) for i in w['in_'])}\n  OUT {', '.join(nm(models, i) for i in w['out'])}\n  ITB {w['sol']['bank']} | C {nm(models, w['sol']['cap'])}")
    if G["fh"]:
        f = G["fh"]
        print(f"\nFREE HIT: GW+0 gain {f['D']:+.1f} (threshold {FH_PREMIUM}) -> {'FIRE' if f['fires'] else 'HOLD'}")
    # captain / TC / BB on the best branch
    best = G["wc"] if (G["wc"] and G["wc"]["fires"]) else G["best_none"]
    sq = best["sol"]["squad"]
    pts0 = {i: XP[i][0] for i in sq}
    xi0 = best_xi(pts0, {i: models[i]["pos"] for i in sq})
    caps = sorted(xi0, key=lambda i: -pts0[i])[:4]
    bench0 = sum(pts0[i] for i in sq if i not in xi0)
    print(f"\nCAPTAIN options GW{gw}: " + " | ".join(f"{models[i]['name']} {pts0[i]:.1f} ({models[i]['own']:.0%} own)" for i in caps))
    chip_this_gw = (G["wc"] and G["wc"]["fires"]) or (G["fh"] and G["fh"]["fires"])
    tc_ok = (not chip_this_gw) and pts0[caps[0]] >= TC_THRESHOLD and "3xc" in chips_left
    bb_ok = (not chip_this_gw) and bench0 >= BB_THRESHOLD and "bboost" in chips_left
    print(f"TC: best {pts0[caps[0]]:.1f} vs {TC_THRESHOLD} -> {'SPEND' if tc_ok else 'hold'}   BB: bench {bench0:.1f} vs {BB_THRESHOLD} -> {'SPEND' if bb_ok else 'hold'}{'   (one chip per GW: WC/FH already firing)' if chip_this_gw else ''}")
    print("XI: " + ", ".join(f"{nm(models, i)} {pts0[i]:.1f}" for i in sorted(xi0, key=lambda i: (list(SQUAD).index(models[i]['pos']), -pts0[i]))))
    print("Bench: " + ", ".join(f"{nm(models, i)} {pts0[i]:.1f}" for i in sorted([i for i in sq if i not in xi0], key=lambda i: (models[i]['pos'] != 'GK', -pts0[i]))))
    print(f"\nTOP {a.top} by horizon xPts (all players):")
    top = sorted(models, key=lambda i: -XP[i].sum())[: a.top]
    for i in top:
        m = models[i]
        print(f"  {m['name']:<16}{m['club']:<4}{m['pos']:<4}{m['price']:>5.1f} | {XP[i][0]:>4.1f} | {XP[i].sum():>5.1f} | p {m['p_next']:.2f} | own {m['own']:.1%}")

    if a.json:
        out = dict(gw=gw, horizon=H, fts=fts, bank=bank, chips_left=sorted(chips_left),
                   hold_val=G["hold_val"],
                   rows=[dict(chip=r["chip"], moves=r["moves"], hits=r["hits"], D=r["D"], gw0=r["gw0"],
                              in_=[models[i]["name"] for i in r["in_"]], out=[models[i]["name"] for i in r["out"]],
                              cap=models[r["sol"]["cap"]]["name"], bank=r["sol"]["bank"]) for r in G["rows"]],
                   wc=None if not G["wc"] else dict(premium=G["wc"]["premium"], fires=G["wc"]["fires"],
                                                     squad=[models[i]["name"] for i in G["wc"]["sol"]["squad"]],
                                                     in_=[models[i]["name"] for i in G["wc"]["in_"]],
                                                     out=[models[i]["name"] for i in G["wc"]["out"]], bank=G["wc"]["sol"]["bank"]),
                   fh=None if not G["fh"] else dict(D=G["fh"]["D"], fires=G["fh"]["fires"]),
                   captain=[dict(name=models[i]["name"], xp=pts0[i], own=models[i]["own"]) for i in caps],
                   xi=[models[i]["name"] for i in xi0],
                   squad_xp={models[i]["name"]: [round(float(x), 2) for x in XP[i]] for i in incumbents})
        json.dump(out, open(a.json, "w"), indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))


if __name__ == "__main__":
    main()
