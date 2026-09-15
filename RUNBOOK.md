# CAESAR RUNBOOK (v4.1, 15 Sep 2026)

Operating procedure for every FPL session on entry **1950353 (Caesar Salahd)**, whether a
scheduled run or a live chat. Objective: **finish inside the top 10,000 overall in 2026/27.**
The manager executes; the analyst decides. Every session ends with the season log updated.

## 0. Ground rules

- No em dashes. Short sentences. Decisions, not essays. Say HOLD when HOLD wins.
- Never answer from memory. Every number comes from the mirror pulled in this session.
- Nothing is "incomplete" or "unverified" any more. If a data file is missing, fix the mirror
  (edit `mirror.py`, push, wait for the run) or say exactly what is missing and why.
- The manager's job is three things only: make the transfers, set the team, play the chip.
  Everything else is ours. Never ask him for data. Never ask him to edit files.
- Name players as `Name (CLUB)`; web names collide (two Thomases, two Palmers).

## 1. Get the data (every session, first thing)

```bash
git clone --depth 1 https://github.com/nr-jp/fpl-mirror /tmp/fpl && cd /tmp/fpl
python3 -c "import json;m=json.load(open('data/derived/meta.json'));print(m['fetched_at'],m['current_event'],m['next_event'],m['next_deadline'],m['event_status'])"
```

If `fetched_at` is more than 90 minutes old, GitHub's scheduler is lagging (it ran 5 of the first
20 slots on 14 Sep). Force a run: commit the current UTC timestamp to `trigger/ping` on `main` with the
GitHub tool (any push under `trigger/` starts the workflow). Wait 3 minutes, re-clone, re-check
`fetched_at`. If it is still stale, report it with the last commit time. Do this before any decision.

Price changes land between roughly 22:00 and 23:30 UTC (observed 14 Sep: 21:03 pull clean, 23:50 pull
carried 11 falls). The 20:00 UTC run is the last look before them. Any price-motivated execution
must reach the manager by 21:00 UTC (17:00 Toronto).

Data files are described in the docstring at the top of `mirror.py`. Key ones:

| file | use |
|---|---|
| `data/derived/meta.json` | current GW, next deadline, bonus lock (`event_status`) |
| `data/latest/bootstrap-static.json` | every player: price, status, news, chance, ownership, xG, xA, defcon |
| `data/latest/fixtures.json` | all fixtures + per-fixture stat blocks (bonus, bps, goals) |
| `data/live/gwN.json` | every player's points and stats for GW N (with `explain`) |
| `data/element-summary/{id}.json` | per-player per-GW history and last-season totals |
| `data/entry/1950353/*.json` | our history, transfers, picks per GW |
| `data/leagues/overall_p200.json` | the rank-10,000 cutoff score (last row) |
| `data/derived/news_log.csv` | every status/news/chance change with timestamp (the injury monitor) |
| `data/derived/price_log.csv` | every price change with timestamp |

## 1b. What the manager has already done (every session, before any instruction)

The FPL API does not expose upcoming-gameweek transfers or an active chip until the deadline passes.
`transfers.json` and `history.json` chips lag by a full gameweek. So the mirror can never tell you
whether the manager has executed this week's instruction. Read `state/executed.json` first. It holds
the squad, chip, captain and XI the manager confirmed for the upcoming GW, and `pending_instruction`.
Rules:
- Never re-issue an instruction that `state/executed.json` shows as executed.
- When the manager confirms an execution in chat, write it to `state/executed.json` in the same turn
  (GitHub tool) and set `pending_instruction`.
- The current squad the engine loads from `picks/gw{cur}.json` is stale after an execution. Probe the
  executed squad with `--force-in` (all 15) and treat that as HOLD until the deadline passes.
- After the deadline passes and the mirror's entry data catches up, clear the file to `{"gw": N+1,
  "pending_instruction": "none"}`.
- A re-run that moves an executed squad by less than 2 points over 8 GWs is noise. Do not swap
  players on an active wildcard for noise; only a minutes or injury input reopens it. (15 Sep lesson:
  a run re-issued a whole new WC draft the morning after the manager had executed the old one.)

## 2. Decide which session this is

Let `deadline` = `meta.next_deadline`, `now` = UTC now, `cur` = current GW.

1. **POST-MORTEM** if GW `cur` is finished and `event_status` shows `bonus_added: true` for every
   day AND the season log's row for GW `cur` is not yet marked FINAL.
2. **DEADLINE** if `deadline - now <= 30 hours`.
3. **MID-GW RUN** if `deadline - now <= 5 days` and the log has no `PROVISIONAL ADOPT` for GW `cur+1`.
4. Otherwise **WATCH**: news, prices, midweek matches, no decision.

Several can apply in one run (post-mortem then mid-GW run). Do them in that order, one output block
each.

## 3. Run the engine

```bash
pip install -q numpy scipy 2>/dev/null
python3 caesar/caesar.py --data data --json /tmp/run.json            # next GW, 6-GW horizon
python3 caesar/caesar.py --data data --force-in "Name:CLUB,Name:CLUB" # probe a manual idea
```

Output: current squad with per-player xPts and flags, HOLD value, BRANCH TABLE (0..FT+1 moves, one
hit max), WILDCARD (8-GW premium over the best transfer branch, fires at +6), FREE HIT, captain
options, TC/BB overlays, XI and bench, top 25 by horizon xPts.

**Minutes overrides.** `caesar/overrides.json` maps element id (string) to
`{"p_start_next": 0.0-1.0, "p_start_later": 0.0-1.0, "out_until_gw": N, "note": "..."}`.
Write one whenever press conferences, match reports or the news log say something the FPL status
flag does not (late scan, manager quote, rotation pattern, red card suspension length). Remove
entries when they expire. Commit the file to the repo (GitHub tool) so the next session inherits it.

**Registered parameters** live at the top of `caesar/caesar.py`. Change them only after a scored
reason (see section 6) and log the change.

## 4. Before any decision session, scan the news

- `data/derived/news_log.csv` rows since the last session.
- Web search for press conferences (Thu/Fri) on every player in: our squad, the adopted branch's
  in-legs, the WC draft, the top 10 by horizon xPts. Record start / doubt / out / suspension.
- Midweek European and cup matches for the same players: started, minutes, injury, booking.
- Convert every finding into an override (section 3). Then re-run the engine.

## 5. Session outputs

### POST-MORTEM
```
GW[n] POST-MORTEM (locked: yes)
Score [x] | GW rank [x] | OR [x] (prev [x]) | GW average [x] | 10k cutoff [x] (gap [x])
Player lines (XI then bench, one line each, from data/live)
Reconciliation: attributions == history points (PASS/FAIL)
Captain: [pick] [pts] vs best owned [x] vs Haaland [x]
Model check: squad xPts predicted vs actual; biggest misses; parameter change yes/no
Verdicts closed / rolled
Log updated: yes
```
### MID-GW RUN
```
GW[n] MID-GW RUN: [time] to deadline [date/time UK]
OR [x] | 10k cutoff gap [x] | Value [x] | ITB [x] | FTs [x] | Chips left [list]
BRANCH TABLE (from caesar.py, top rows + HOLD)
PROVISIONAL ADOPT: [moves or HOLD or chip]   Why: one line
Captain / VC   XI   Bench order
WHAT COULD CHANGE IT: [the 2-4 news items that would flip the call]
```
### DEADLINE
```
GW[n] DEADLINE: [hours] to [time UK]
News since mid-GW: [none / list with source]
Re-run: [not needed / re-run, new verdict]
=== MANAGER: DO THIS ===
TRANSFERS: [Out -> In, ...]  HITS: [0/-4]
CHIP: [none / Wildcard / Free Hit / Bench Boost / Triple Captain]
CAPTAIN: [x]  VICE: [x]
XI: [formation, names]   BENCH ORDER: 1) 2) 3) (GK)
========================
NEXT 3 GW: one line each
```
The `MANAGER: DO THIS` block is the only thing he needs to read. Put it first when the run is a
deadline session. Nothing in it may depend on data older than this session's pull.

### WATCH
Five lines max: what changed (news, prices, midweek), whether the provisional adoption stands,
what the next session must check.

## 6. Scoring ourselves (every post-mortem)

- Compare each owned player's engine xPts (from the mid-GW run's `/tmp/run.json`, stored in the
  log) with actual points. Track the running mean error by position in the log.
- If the model is biased by more than 0.5 points/player/GW over the last 3 GWs in any position,
  adjust the relevant prior at the top of `caesar.py`, commit it, and log the change with the
  evidence. One parameter per week at most.
- Log the captain call versus the best owned alternative and versus Haaland.

## 7. Writing the log

`04_SEASON_LOG.md` in the Claude Project (Projects tool). Keep CURRENT STATE at the top accurate
(OR, total, 10k cutoff gap, value, ITB, FTs, chips, provisional adoption, overrides in force).
Append one dated entry per session. Keep the GW table. Keep it short; the data lives in the mirror.
If the Projects tool is unavailable in a run, write the entry to `state/LOG_APPEND.md` in this repo
instead and say so; the next session merges it.

## 8. Chip windows (hard)

Set 1 (WC, FH, BB, TC) expires at the GW19 deadline (2 Jan 2027). Set 2 runs GW20-38.
One chip per GW. From GW16, unspent set-1 chips go at the top of every output in bold.
WC1 decision is made by the engine's 8-GW premium test; TC when the captain's GW xPts >= 7.0;
BB when the bench's GW xPts >= 10.0; FH when a one-week squad beats the best transfer branch
by >= 10 in that GW (blank GWs qualify automatically).
