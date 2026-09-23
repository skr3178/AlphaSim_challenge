# Local-only corrected-state feature ablation — 2026-09-19

The proposed next test was to correct ego-state inputs and compare otherwise
identical heads with and without Cosmos features, at the same training budget,
using unseen source logs. The user replied: "ok lets do that".

Bounded implementation: retain the original ten training scenes from four logs;
select one evaluation scene from each of the other nine development source logs
by deterministic SHA-256 ranking, before seeing outcomes. Use 100 head optimizer
updates per arm (200 total), identical initialization, batch order, optimizer and
loss; Cosmos stays frozen. Evaluate both final checkpoints once on the nine
unseen-log examples. No held-out labels may enter fitting or model selection.

All samples come from existing saved ASLs. No new data download, full simulator
evaluation, public leaderboard submission or backbone update is authorized.
The original protected validation/holdout suites remain unused. The nine logs
are unseen by these fitted heads, not guaranteed unseen in Cosmos pretraining.

This is user authorization for a local diagnostic, not organizer permission to
train on public evaluation data. Competition eligibility remains unverified;
all fitted heads are local-only and excluded from submissions. Preserve the
original manifests and the earlier 100-update diagnostic checkpoint unchanged.
