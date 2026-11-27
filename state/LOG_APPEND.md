# LOG APPEND (merge into 04_SEASON_LOG.md; the Projects tool was not available in this session)

## CURRENT STATE (27 Nov 2026, ~16:20 UTC, GW11 POST-MORTEM + GW12 DEADLINE in live chat, manager's "Run")

| Field | Value |
|---|---|
| OR | **1,186,818** after GW11 (prev 928,644). GW11 rank 8,691,325 |
| Total | **676**. GW11 28 (average 35, highest 106) |
| Top-10k cutoff | 769 after GW11. Gap **93** |
| Value / ITB | 101.4 incl. bank, ITB 0.2 (0.4 after the GW12 moves) |
| FTs | 2 for GW12, both used in the adopted branch, so 1 for GW13. Derive again from history.json |
| Chips | 5 left: FH1 (dies at the GW19 deadline, 2 Jan 2027), WC2, FH2, BB2, TC2 |
| Next deadline | GW12 Fri 27 Nov 18:30 GMT. GW13 is midweek: first game Tue 1 Dec 20:00 GMT, so the deadline is about 18:30 GMT that day (check meta.json) |
| Pending instruction | GW12: B.Fernandes (MUN) + McBurnie (HUL) out, Wirtz (LIV) + Isak (LIV) in, no hit. Tavernier (C), Haaland (VC). In `state/executed.json` (commit 044b7cc), not yet confirmed |
| Overrides in force (commit 761db25) | 426 B.Fernandes .40 / .90 (virus); 427 Mbeumo .90 / .90; 8 Calafiori .95; 12 Saka out to GW17; 31 Konsa .60 / .50; 173 Thomas .50 / .90 (stale, review); 391 Gvardiol .80 / .70 (stale, review) |
| Open work | Backtest GW5-11 still not done (failure 25). Upside term and captain leverage rule still not in the engine or 07 |

## GW11 POST-MORTEM (Fri 27 Nov, scored three days late)

Mirror 14:17 UTC at clone (two hours old), forced to 16:14:34 UTC (ping e88e832). bonus_added true on all three days,
data_checked true. FINAL.

```
GW11 POST-MORTEM (locked: yes)
Score 28 | GW rank 8,691,325 | OR 1,186,818 (prev 928,644) | GW average 35 | highest 106 | 10k cutoff 769 (gap 93)
```

Executed as adopted: HOLD, no chip, Haaland (C), Tavernier (VC).

Player lines (`live/gw11.json`): Trafford (LEE) 2 (90, 1 conceded). Calafiori (ARS) 1 (90, 2 conceded). Gabriel (ARS) 1 (90,
2 conceded). Vuskovic (BHA) 0 (90, 2 conceded, yellow). Mbeumo (MUN) 1 (started, off after 21 min at LIV, LIV 4-0 MUN).
Groß (BHA) 4 (90, bps 24). B.Fernandes (MUN) 2 (90). Tavernier (BOU) (VC) 8 (90, assist, CS point, 2 bonus). Gomez (BHA)
3 (79). Haaland (MCI) (C) 2 x2 = 4 (90, blank). Barry (EVE) 2 (68). Bench: Leno (FUL) 2, McBurnie (HUL) 13
(two goals, 3 bonus), Diop (IPS) 0, Davis (IPS) 1. Bench 16.

Reconciliation: 28 == picks entry_history; 676 == 648 + 28. PASS.

Captain: Haaland 4 vs best owned McBurnie 13 (26, on the bench) vs best in the XI Tavernier 8 (16) vs template Haaland 4.
Third captain blank in a row (4, 4, 4). 0 against the field, -12 against the VC.

Model check (registered 21 Nov, actual minus predicted): Trafford -2.0, Leno -1.1; Gabriel -4.3, Calafiori -3.6, Vuskovic
-4.5, Diop -2.7, Davis -1.4; Tavernier +2.8, Groß -0.6, B.Fernandes -2.5, Mbeumo -2.9, Gomez -0.9; Haaland -5.0, Barry
-2.3, McBurnie +10.1. Position means: GK -1.6, DEF -3.3, MID -0.8, FWD +0.9. XI with C predicted 58.8, actual 28.

Pool-wide (`state/pool_gw11_slim.json`), nailed players who played: GK +0.51 (n 18), DEF -0.15 (n 45), MID +0.42 (n 45),
FWD -0.33 (n 12). Spearman on 106 nailed 60-minute starters **0.14** (GW9 0.19, GW10 0.27), MAE 2.54. Lesson-22 trigger
(predicted-4+ MID bin GW9-11): GW11 n 12, +0.14; pooled n 34, about +0.2. Does not fire. CLOSED, no parameter change.
Verdict: calibrated on average for a third week, and it still cannot rank players. A low-scoring week (average 35) in which
our four defenders all conceded. Variance on the score; the ranking problem is the standing finding.

Field (event 11): 137,848 WC, 56,517 FH, 203,038 TC, 276,872 BB. Most captained Haaland. Average 35.

**Process failure 25 (24-27 Nov): the GW11 post-mortem (due Tue 24 Nov), the backtest and the GW12 mid-GW run (due Wed 25
Nov) did not happen.** No session ran between 21 Nov and this one, 2h15m before the GW12 deadline. Post-mortem, run and
deadline scan carried in one session again (lessons 25, 29). The backtest is now three weeks late.

## GW12 DEADLINE (Fri 27 Nov, ~16:13 to 16:25 UTC, carries the mid-GW run)

News (mirror news_log + web, Fri 27 Nov). **B.Fernandes (MUN): virus, missed training Friday. Pochettino: "we don't know",
"we will not take any risks", call on Saturday morning (manutd.com, Sports Mole, Hayters). FPL 75%.** Override .40 / .90.
Mbeumo (MUN): started at LIV and came off after 21 minutes; started at Sporting Wed; every predicted XI v BRE starts him.
Override .90. Man City: everyone fit bar Semenyo (Maresca, FFS). Arsenal: Raya 50%, back in training; Saliba to get minutes
this week; no item on Gabriel or Calafiori. Tarkowski (EVE) suspended. Davis (IPS) calf flag cleared to 100% at the 16:14
pull. Gakpo, Gravenberch (LIV) out; Isak and Wirtz both 100%, both 84 to 90 minutes in GW10-11. Thiago (BRE) banned.

```
BRANCH TABLE (caesar.py, 16:14 UTC mirror, horizon 6, 2 FTs, bank 0.2)
chip  mv hit bank      D   GW0  moves
NONE   3   4    1   +5.8  59.3  IN Ødegaard (ARS), Isak (LIV), Silva (BOU) | OUT McBurnie (HUL), Davis (IPS), B.Fernandes (MUN) | ITB 0.1
NONE   2   0    1   +4.9  58.0  IN Wirtz (LIV), Isak (LIV) | OUT McBurnie (HUL), B.Fernandes (MUN) | ITB 0.4
NONE   1   0    2   +2.1  57.5  IN Hill (BOU) | OUT Calafiori (ARS) | ITB 0.2
NONE   0   0    3   +0.0  56.0  HOLD
FREE HIT: +1.6 v 10.0 -> hold.  TC / BB: set 1 spent.
CHIP WINDOW GW12-19 captain / bench (current squad): 12:5.7/13.1 13:6.7/13.8 14:6.9/13.1 15:7.1/13.7 16:7.5/12.8 17:7.2/13.7 18:6.9/13.4 19:6.5/13.2
```

**ADOPT: Wirtz (LIV) 7.5 + Isak (LIV) 9.4 for B.Fernandes (MUN) 11.6 + McBurnie (HUL) 5.5. 2 FTs, no hit, ITB 0.4. No chip.**
Why: first run in which selling Bruno beats HOLD. It does not rest on the virus: with Bruno at .95 the same row is still
+2.5 (best row then De Cuyper + Silva for Calafiori + Vuskovic, +3.7). At .40 it is +4.9. It is also the approach review's
item 4: Bruno's 11.6 funds two players with a ceiling. CLOSE CALL: the 3-move hit row is 0.9 higher, inside noise. No hit.

**CAPTAIN: Tavernier (BOU) at FUL, 5.5 (34% own). VC Haaland (MCI) at ARS, 5.7 (75% own).** First use of the approach
review's item 3 rule, by hand: differential when inside 1.0 of Haaland and his ownership is above 70%. The gap is 0.2 on
a model whose rank correlation is 0.14 to 0.27, so the two are level on expected points and Tavernier is the only one of
the two that moves rank. This departs from 00 rule 4 as written (highest xPts); 00 and 07 need the rule written in
before GW13 or the captain goes back to pure xPts.

XI 3-5-2: Trafford (LEE) 5.1; Vuskovic (BHA) 4.5, Gabriel (ARS) 3.9, Calafiori (ARS) 3.2; Tavernier (BOU) 5.5 (C), Groß (BHA)
5.1, Gomez (BHA) 4.4, Wirtz (LIV) 4.3, Mbeumo (MUN) 4.1; Haaland (MCI) 5.7, Isak (LIV) 5.0. XI with C about 56.5.
Bench: 1) Barry (EVE) 4.1 2) Diop (IPS) 3.0 3) Davis (IPS) 2.9, GK Leno (FUL) 3.0.

Registered GW12 predictions: as above (held-squad figures: B.Fernandes 2.3, McBurnie 3.4). Full pool reproducible with
`caesar/pool_xp.py` on the 16:14:34 UTC mirror pull with overrides 761db25.

Lesson 35: a session that starts two hours before a deadline still does all three jobs, but the model work it keeps
deferring (backtest, leverage rule) never fits in it. That work needs its own "run" message on a non-deadline day.

Next: post-mortem after GW12 locks (Mon 30 Nov). GW13 is midweek, deadline about Tue 1 Dec 18:30 GMT, 1 FT: the run
has to happen Monday with the post-mortem.
