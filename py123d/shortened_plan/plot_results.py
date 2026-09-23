"""Refresh charts from saved metrics only; never launches evaluations."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import polars as pl
import yaml
from eval.aggregation.processing import aggregate_and_write_metrics_results_txt
from eval.aggregation.modifiers import RemoveTimestepsAfterEvent
from eval.aggregation.scene_score import score_rollout
from eval.schema import SceneScoreConfig

HERE = Path(__file__).resolve().parent
ART = HERE / 'artifacts'
OUT = HERE / 'plots'


def main():
    OUT.mkdir(exist_ok=True)
    sweep = ART / 'sweep-20260922T070619Z'
    rows = []

    def add(suite, result, source):
        rows.append(dict(suite=suite, arm=result['arm'], scenes=result['scenes'],
                         score=result['score'], collisions=result['collisions'],
                         corridor_exits=result['corridor_exits'], source=str(source)))

    for path in sorted(sweep.glob('*/result.json')):
        add('Development 24', json.loads(path.read_text()), path)
    sim = ART / 'split-validation-20260922T100233Z/available144_baseline/simulation'
    paths = [p for p in sim.glob('rollouts/*/*/metrics.parquet') if (p.parent / '_complete').exists()]
    cfg = yaml.safe_load((sim / 'eval-config.yaml').read_text())
    processed = aggregate_and_write_metrics_results_txt(
        pl.concat([pl.read_parquet(p) for p in paths]),
        additional_modifiers=[RemoveTimestepsAfterEvent(pl.col('dist_to_gt_trajectory') >= cfg['aggregation_modifiers']['max_dist_to_gt_trajectory'])])
    base = processed.df_wide_avg_t.to_dicts()
    scores = [score_rollout(r, SceneScoreConfig(**cfg['scene_score'])).score for r in base]
    tuned_path = ART / 'tuned141-20260922T104409Z/combo_2/result.json'
    tuned_summary = json.loads((tuned_path.parent / 'simulation/aggregate/results-summary.json').read_text())
    assert {r['clipgt_id'] for r in base} == {r['clipgt_id'] for r in tuned_summary['rollouts']}
    assert len(base) == 141
    add('Validation 141 (partial)', dict(arm='baseline', scenes=len(base), score=sum(scores)/len(scores),
        collisions=sum(r['collision_at_fault'] for r in base),
        corridor_exits=sum(r['left_corridor_laterally'] for r in base)), sim)
    add('Validation 141 (partial)', json.loads(tuned_path.read_text()), tuned_path)
    for arm in ('baseline', 'combo_2'):
        path = ART / 'optuna-development64-v1' / arm / 'result.json'
        if path.exists():
            result = json.loads(path.read_text())
            result['arm'] = arm
            add('Development 64', result, path)
    with (OUT / 'tuning-results.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 3, figsize=(14, 5), sharey=True)
    suites = ['Development 24', 'Validation 141 (partial)', 'Development 64']
    for ax, suite in zip(axes, suites):
        subset = [r for r in rows if r['suite'] == suite and r['arm'] in ('baseline', 'combo_2')]
        ax.set_title(suite)
        ax.set_ylim(0, 1)
        ax.set_xticks([0, 1], ['Baseline', 'Tuned combo_2'])
        for r in subset:
            x = int(r['arm'] == 'combo_2')
            ax.bar(x, r['score'], color=['#64748b', '#0891b2'][x], width=.6)
            ax.text(x, r['score']+.025, f"{r['score']:.4f}", ha='center')
        if len(subset) == 2:
            values = {r['arm']: r['score'] for r in subset}
            ax.set_xlabel(f"Tuned − baseline: {values['combo_2']-values['baseline']:+.5f}")
        else:
            ax.text(.5, .45, 'Reference results pending' if not subset else 'Tuned result pending',
                    ha='center', transform=ax.transAxes)
    axes[0].set_ylabel('Mean local scene score (higher is better)')
    fig.suptitle('Frozen Py123d checkpoint: controller tuning, not neural-network training')
    fig.text(.5, .025, 'Compare within each panel only. Different scene sets; not leaderboard PCS.\n141-scene subset excludes 3 route errors and 6 untested scenes.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .1, 1, .94))
    for ext in ('png', 'svg'):
        fig.savefig(OUT / ('baseline-vs-tuned.' + ext), dpi=160)
    plt.close(fig)
    dev = [r for r in rows if r['suite'] == 'Development 24']
    baseline = next(r['score'] for r in dev if r['arm'] == 'baseline')
    dev.sort(key=lambda r: r['score'])
    fig, ax = plt.subplots(figsize=(12, 12))
    delta = [r['score']-baseline for r in dev]
    ax.barh([r['arm'] for r in dev], delta, color=['#0891b2' if d >= 0 else '#e07663' for d in delta])
    ax.axvline(0, color='#64748b', linewidth=1)
    ax.set_xlabel('Change in mean scene score versus baseline on the same 24 scenes')
    ax.set_title('All saved 24-scene sweep results, including repeat checks\nDevelopment selection results—not independent validation')
    fig.tight_layout()
    for ext in ('png', 'svg'):
        fig.savefig(OUT / ('development24-sweep.' + ext), dpi=160)
    plt.close(fig)
    print(f'Saved {len(rows)} result rows and two charts (PNG + SVG) to {OUT}')


if __name__ == '__main__':
    main()
