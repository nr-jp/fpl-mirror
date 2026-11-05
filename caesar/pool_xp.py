#!/usr/bin/env python3
"""
Dump every player's GW-by-GW projection from the CAESAR engine, so a post-mortem can score
the whole pool, not just the squad (lesson 27, 5 Nov 2026). Run it alongside caesar.py:

    python3 caesar/pool_xp.py --data data [--gw N] [--horizon 6] --json state/pool_gwN.json

Output: {"gw": N, "horizon": H, "fetched_at": ..., "rows": [[id, name, club, pos, price, p_next, own, xp0..xpH-1], ...]}
sorted by horizon xPts. Reads caesar/overrides.json through the engine exactly as caesar.py does.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import caesar as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--gw", type=int, default=None)
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = C.Data(a.data)
    gw = a.gw or D.nxt
    H = a.horizon
    strength, lg_avg = C.team_strength(D)
    C.lg_avg_global[0] = lg_avg
    models = C.player_model(D, strength, lg_avg)
    fix = C.fixture_layer(D, strength, gw, H)
    XP = C.points_matrix(D, models, fix, gw, H)
    meta = json.load(open(os.path.join(a.data, "derived", "meta.json")))
    rows = [[i, models[i]["name"], models[i]["club"], models[i]["pos"], models[i]["price"],
             round(float(models[i]["p_next"]), 2), round(float(models[i]["own"]), 3)]
            + [round(float(x), 2) for x in XP[i][:H]]
            for i in sorted(models, key=lambda i: -float(sum(XP[i][:H])))]
    out = dict(gw=gw, horizon=H, fetched_at=meta.get("fetched_at"), rows=rows)
    json.dump(out, open(a.json, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"pool_xp: GW{gw}, horizon {H}, {len(rows)} players -> {a.json}")


if __name__ == "__main__":
    main()
