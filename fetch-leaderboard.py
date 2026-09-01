#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["gradio_client>=1.0"]
# ///
"""
Download the AlpaSim E2E Challenge 2026 leaderboards (nuPlan + PAI) to local files.

    ./fetch-leaderboard.py                      # both tracks -> ./leaderboard/
    ./fetch-leaderboard.py --track nuplan       # one track
    ./fetch-leaderboard.py --out /tmp/lb        # elsewhere
    ./fetch-leaderboard.py --best-only          # dedupe to each team's best submission
    ./fetch-leaderboard.py --quiet              # no stdout table

The shebang uses uv's inline-script mode, so no venv or pip install is needed --
uv resolves gradio_client on the fly. Plain `python fetch-leaderboard.py` also
works if gradio_client is already importable.

Writes per track:  <track>.json  <track>.csv     plus  raw.json  SUMMARY.md

--------------------------------------------------------------------------------
Notes earned the hard way (2026-08-29), keep them:

1. The Space exposes the leaderboard through ~10 anonymous `/lambda*` endpoints
   rather than named ones. Empirically /lambda../lambda_4 back one board and
   /lambda_5../lambda_9 the other -- but that numbering is an artifact of Gradio's
   event ordering and WILL shift if the app's UI is edited. So this script does
   NOT hardcode which endpoint is which track: it calls them and reads the
   `track` field out of the returned payload. Endpoint numbering may rot; the
   payload's self-description will not.

2. Within each group the endpoints differ in latency: some are cached
   (p50 ~0 ms) and some do a real backend refresh (p50 ~3-6 s). Any of them
   returns the same shape, so we take the first that parses.

3. `show_all=False` (the UI default) returns only each team's BEST submission --
   18 of 58 rows for nuPlan. Pass show_all=True for the complete set. This script
   fetches everything and does its own dedupe with --best-only, so you keep the
   raw data either way.

4. gradio_client renamed the auth kwarg: `hf_token=` in 0.x/1.x, `token=` in 2.x.
   Passing the wrong one is a TypeError at construction. _make_client() probes the
   signature instead of guessing.

5. A token is NOT required -- these leaderboards are public. HF_TOKEN is used if
   present, purely to avoid anonymous rate limits.

6. `rank` in the payload is NOT monotonic in policy_capability_score: organizer
   baseline rows (team_id "host") are interleaved. Sort on the score yourself.
   This script does.
--------------------------------------------------------------------------------
"""
from __future__ import annotations

import argparse
import csv
import datetime
import inspect
import json
import os
import sys
from pathlib import Path

SPACE = "nvidia/AlpasimE2EClosedLoopChallenge2026"

# Probed in this order. Slower (uncached) endpoints first: they force a real
# backend read rather than replaying whatever the app last rendered.
ENDPOINT_GROUPS = [
    ["/lambda_4", "/lambda_3", "/lambda_2", "/lambda_1", "/lambda"],
    ["/lambda_9", "/lambda_8", "/lambda_7", "/lambda_6", "/lambda_5"],
]

# The straight-line starter driver produces this exact metric pair. Any
# submission matching it is an unmodified starter kit -- a free reference point
# for "what does zero policy work score?".
STARTER_FINGERPRINT = (0.27835287112208, 2.47247355828445)


def _make_client(space: str, token: str | None):
    """Construct a Client across gradio_client versions (hf_token= vs token=)."""
    from gradio_client import Client

    params = inspect.signature(Client.__init__).parameters
    kw = {}
    if token:
        if "token" in params:
            kw["token"] = token
        elif "hf_token" in params:
            kw["hf_token"] = token
        else:
            print("  ! this gradio_client takes no token kwarg; going anonymous", file=sys.stderr)
    return Client(space, **kw)


def fetch_boards(client, verbose=True) -> dict:
    """Call each endpoint group until one yields a parseable payload.

    Returns {track_name: {endpoint, header, payload}} keyed by the track the
    server reports, not by which endpoint we happened to call.
    """
    boards: dict[str, dict] = {}
    for group in ENDPOINT_GROUPS:
        for ep in group:
            try:
                res = client.predict(
                    show_all=True, sort_by="Rank", ascending=True, api_name=ep
                )
            except Exception as e:  # endpoint renumbered, removed, or erroring
                if verbose:
                    print(f"  {ep}: {type(e).__name__}: {str(e)[:90]}")
                continue

            parts = list(res) + [None, None, None]
            header, _html, payload_json = parts[0], parts[1], parts[2]
            if not payload_json:
                continue
            try:
                payload = json.loads(payload_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict) or "leaderboard" not in payload:
                continue

            track = str(payload.get("track", "unknown")).lower()
            boards[track] = {"endpoint": ep, "header": header, "payload": payload}
            if verbose:
                print(f"  {ep} -> {track}: {payload.get('count')} entries")
            break  # got this group's board
    return boards


def best_per_team(rows: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for r in rows:
        t = r.get("team_id")
        if t not in best or r.get("policy_capability_score", 0) > best[t].get(
            "policy_capability_score", 0
        ):
            best[t] = r
    return sorted(best.values(), key=lambda r: -r.get("policy_capability_score", 0))


def is_starter(row: dict, tol=1e-9) -> bool:
    a, d = STARTER_FINGERPRINT
    return (
        abs((row.get("avg_dist_between_incidents_at_fault") or -1) - a) < tol
        and abs((row.get("dist_to_gt_trajectory") or -1) - d) < tol
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    # union of keys, first-seen order -- rows are not guaranteed uniform
    fields: list[str] = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def write_summary(path: Path, boards: dict, fetched_at: str) -> None:
    L = [f"# AlpaSim 2026 leaderboard snapshot", ""]
    L.append(f"Fetched **{fetched_at}** from `{SPACE}`.")
    L.append("")
    for track, b in sorted(boards.items()):
        p = b["payload"]
        rows = p["leaderboard"]
        teams = best_per_team(rows)
        L.append(f"- **{track}**: {p.get('count')} submissions, {len(teams)} teams "
                 f"(`{b['endpoint']}`)")
    L.append("")

    for track, b in sorted(boards.items()):
        p = b["payload"]
        rows = p["leaderboard"]
        teams = best_per_team(rows)
        L.append(f"## {track} — best submission per team")
        L.append("")
        L.append(f"Metric `{p.get('primary_score')}` "
                 f"(order `{p.get('score_order')}`, algorithm "
                 f"`{rows[0].get('metric_algorithm') if rows else '?'}`)")
        L.append("")
        L.append("| # | Team | PCS | AvgDist@Fault | dist_to_gt | Tag | Submitted |")
        L.append("|---|---|---|---|---|---|---|")
        for i, r in enumerate(teams, 1):
            L.append(
                f"| {i} | {r.get('team_display_name')} (`{r.get('team_id')}`) "
                f"| **{r.get('policy_capability_score', 0):.1f}** "
                f"| {r.get('avg_dist_between_incidents_at_fault') or 0:.3f} "
                f"| {r.get('dist_to_gt_trajectory') or 0:.3f} "
                f"| `{r.get('image_tag')}` | {str(r.get('submitted_at'))[:10]} |"
            )
        L.append("")
        base = sorted([r for r in rows if is_starter(r)],
                      key=lambda r: -r.get("policy_capability_score", 0))
        if base:
            top = teams[0].get("policy_capability_score", 0)
            floor = base[0].get("policy_capability_score", 0)
            L.append(f"**Starter-kit floor:** {len(base)} submission(s) match the "
                     f"unmodified straight-line driver's metric fingerprint, scoring "
                     f"~**{floor:.0f}**. Top of board is **{top:.1f}** — "
                     f"~**{top - floor:.0f}** points of headroom.")
            L.append("")
    path.write_text("\n".join(L))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--track", help="only save this track (e.g. nuplan, pai)")
    ap.add_argument("--out", default="leaderboard", help="output dir (default: ./leaderboard)")
    ap.add_argument("--best-only", action="store_true",
                    help="write only each team's best submission")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    verbose = not a.quiet

    token = os.environ.get("HF_TOKEN")
    if verbose:
        print(f"connecting to {SPACE}" + (" (with HF_TOKEN)" if token else " (anonymous)"))
    client = _make_client(SPACE, token)

    boards = fetch_boards(client, verbose=verbose)
    if not boards:
        print("ERROR: no leaderboard payload returned. The Space's /lambda* endpoint "
              "numbering has probably changed — re-check the API docs page and update "
              "ENDPOINT_GROUPS.", file=sys.stderr)
        return 1

    fetched_at = datetime.datetime.now().isoformat(timespec="seconds")
    (out / "raw.json").write_text(json.dumps(
        {"fetched_at": fetched_at, "space": SPACE, "boards": boards}, indent=2))

    wanted = {a.track.lower()} if a.track else set(boards)
    for track, b in boards.items():
        if track not in wanted:
            continue
        p = b["payload"]
        rows = best_per_team(p["leaderboard"]) if a.best_only else p["leaderboard"]
        (out / f"{track}.json").write_text(json.dumps(
            {"fetched_at": fetched_at, **p}, indent=2))
        write_csv(out / f"{track}.csv", rows)
        if verbose:
            print(f"  wrote {out/track}.json + {track}.csv  ({len(rows)} rows)")

    write_summary(out / "SUMMARY.md", {k: v for k, v in boards.items() if k in wanted},
                  fetched_at)
    if verbose:
        print(f"  wrote {out}/SUMMARY.md")
        for track, b in sorted(boards.items()):
            if track not in wanted:
                continue
            teams = best_per_team(b["payload"]["leaderboard"])
            print(f"\n{track}: top 5 of {len(teams)} teams")
            for i, r in enumerate(teams[:5], 1):
                print(f"  {i}. {str(r.get('team_display_name'))[:24]:<24} "
                      f"{r.get('policy_capability_score', 0):>9.1f}  "
                      f"{str(r.get('image_tag'))[:30]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
