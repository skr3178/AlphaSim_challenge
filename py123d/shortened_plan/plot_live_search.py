"""Read-only trial-result watcher. No database writes or simulator calls."""
import argparse
import csv
import datetime
import io
import json
import os
from pathlib import Path
import time

os.environ.setdefault('MPLCONFIGDIR', '/tmp/alpasim-live-plots')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
STUDY = HERE / 'artifacts/optuna-development64-v1'
OUT = HERE / 'plots/live-search'


def atomic_text(path, content):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content)
    temporary.replace(path)


def refresh():
    baseline = json.loads((STUDY / 'baseline/result.json').read_text())
    previous = json.loads((STUDY / 'combo_2/result.json').read_text())
    rows = []
    for path in STUDY.glob('trial-*/result.json'):
        try:
            result = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue  # Writer may still be finishing this result.
        assert result['scenes'] == 64
        number = int(path.parent.name.split('-')[1]) + 1
        feasible = all(result[k] <= baseline[k] for k in ('collisions', 'corridor_exits'))
        rows.append(dict(trial=number, score=result['score'], feasible=feasible,
                         collisions=result['collisions'], corridor_exits=result['corridor_exits'],
                         progress=result['progress'], d2gt=result['d2gt'], seconds=result['wall_seconds'],
                         long_position_weight=result['gains']['long_position_weight'],
                         acceleration_weight=result['gains']['acceleration_weight'],
                         rel_acceleration_weight=result['gains']['rel_acceleration_weight'],
                         blend=result['stabilization_weight']))
    rows.sort(key=lambda r: r['trial'])
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    x = [r['trial'] for r in rows]
    ax = axes[0, 0]
    for feasible, color, label in [(True, '#0891b2', 'Within baseline safety counts'),
                                    (False, '#dc6655', 'Exceeds baseline safety counts')]:
        subset = [r for r in rows if r['feasible'] == feasible]
        ax.scatter([r['trial'] for r in subset], [r['score'] for r in subset], color=color, label=label)
    best = None
    running = []
    for r in rows:
        if r['feasible']:
            best = max(best, r['score']) if best is not None else r['score']
        running.append(best if best is not None else float('nan'))
    ax.plot(x, running, color='#166534', label='Best feasible trial so far')
    ax.axhline(baseline['score'], color='#64748b', linestyle='--', label=f"Baseline {baseline['score']:.4f}")
    ax.axhline(previous['score'], color='#a16207', linestyle=':', label=f"Previous tuned {previous['score']:.4f}")
    ax.axvline(20.5, color='#aaaaaa', linestyle=':')
    ax.set(xlim=(.5, 50.5), title='Scene score: 20 initial → 30 adaptive trials', xlabel='Trial (1-based)', ylabel='Mean score')
    ax.legend(fontsize=7)
    ax = axes[0, 1]
    ax.plot(x, [r['collisions'] for r in rows], 'o-', label='At-fault collisions')
    ax.plot(x, [r['corridor_exits'] for r in rows], 's-', label='Corridor exits')
    ax.axhline(baseline['collisions'], linestyle='--', color='C0', label='Baseline collisions')
    ax.axhline(baseline['corridor_exits'], linestyle='--', color='C1', label='Baseline corridor exits')
    ax.set(title='Safety counts per 64 scenes', xlabel='Trial (1-based)', ylabel='Scene count')
    ax.legend(fontsize=8)
    ax = axes[1, 0]
    top = sorted(rows, key=lambda r: r['score'], reverse=True)[:10]
    ax.barh([f"Trial {r['trial']}" for r in reversed(top)],
            [r['score']-baseline['score'] for r in reversed(top)],
            color=['#0891b2' if r['feasible'] else '#dc6655' for r in reversed(top)])
    ax.axvline(0, color='#64748b')
    ax.set(title='Top 10 observed scores (red = safety constraint exceeded)', xlabel='Score gain over baseline')
    ax = axes[1, 1]
    ax.plot(x, [r['seconds']/60 for r in rows], 'o-', color='#64748b')
    ax.set(title='Evaluation runtime', xlabel='Trial (1-based)', ylabel='Minutes')
    for ax in axes.flat:
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(alpha=.15)
    fig.suptitle(f'Py123d controller search — {len(rows)}/50 saved trial results\nUpdated {stamp}')
    fig.text(.5, .01, 'Development set only; not validation or PCS. Safety feasibility uses total counts, not per-scene regressions.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .04, 1, .93))
    for extension in ('png', 'svg'):
        target = OUT / ('search-progress.' + extension)
        temporary = target.with_suffix('.tmp.' + extension)
        fig.savefig(temporary, dpi=140)
        temporary.replace(target)
    plt.close(fig)
    if rows:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
        atomic_text(OUT / 'trials.csv', buffer.getvalue())
    atomic_text(OUT / 'status.json', json.dumps(dict(updated=stamp, saved_results=len(rows), best_feasible_score=best), indent=2))
    atomic_text(OUT / 'index.html', '''<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="60">
<title>Py123d live search</title><style>body{font-family:system-ui;margin:24px;background:#f8fafc}img{max-width:100%}</style>
<h1>Py123d live controller search</h1><p>Reloads every 60 seconds. Charts refresh every minute while watcher runs.</p>
<img id="plot" src="search-progress.png" alt="Search progress plots">
<script>document.getElementById('plot').src='search-progress.png?t='+Date.now()</script>
<p>Development scores only. No validation or leaderboard claims. Red trials exceed baseline safety counts.</p>
<a href="trials.csv">Download trial metrics</a>''')
    print(f'{stamp}: plotted {len(rows)}/50 results; best feasible={best}', flush=True)
    return len(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        count = refresh()
        if not args.watch or count >= 50:
            break
        time.sleep(60)
