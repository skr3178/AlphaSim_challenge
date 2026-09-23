# Cosmos3-Edge: saved trajectory review

Reviewed 2026-09-18. This reads the existing one-scene compatibility run only.
No inference, simulator, evaluator, training or submission was run for this review.

## Plots

- [Overview: plans, driven path, speed and corridor distance](artifacts/20260918T130423Z_alpasim_compat/plots/trajectory-overview.png)
- [All ten predicted paths individually](artifacts/20260918T130423Z_alpasim_compat/plots/all-ten-plans.png)
- [Per-plan measurements](artifacts/20260918T130423Z_alpasim_compat/plots/per-plan.csv)
- [Diagnostics and source path](artifacts/20260918T130423Z_alpasim_compat/plots/trajectory-diagnostics.json)

SVG versions of both plots are saved beside the PNGs.

## What the saved data shows

Cosmos produced ten finite four-second paths. **Nine were used by the controller.**
The first prediction, at 0.017 s, was generated during ground-truth priming:
the runtime supplied a reference trajectory to the controller until 0.517 s.
This does not mean Cosmos received future ground-truth conditioning; it did not.

| Prediction | Time | Observed ego speed | Speed implied by first 0.1 s of plan | Four-second plan length |
| --- | ---: | ---: | ---: | ---: |
| #1, not executed | 0.017 s | 13.31 m/s | 4.04 m/s | 17.00 m |
| #2, first executed | 0.517 s | 13.22 m/s | 3.58 m/s | 15.83 m |
| #3 | 1.017 s | 9.64 m/s | 0.20 m/s | 2.07 m |

These are large initial-speed discontinuities. The current model call uses one
front image and a fixed prompt, without explicit speed, route or image-history
conditioning. The numerical mismatch is observed; which model/adapter changes
would fix it has not been established.

The reference path is nearly straight. The actual path first deviates left, then
turns right of the reference and does not recover. Later generated paths also
continue away from the reference. There is visible controller tracking error
early in the run, so the actual driven path must not be confused with a direct
rendering of the generated waypoints. Each plan is replaced after 0.5 seconds;
the full four-second paths are predictions, not executed four-second segments.

The saved local scorer first flags corridor exit at **3.517 s**, when its
box-centre lateral distance reaches **4.1146 m**, above the configured **4 m**
threshold. That matches the saved aggregate distance and zero scene score.
Simulation continues to 5.017 s, by which time the same distance is **5.1624 m**.
The aggregate 4.11 m therefore does not describe the final logged position.

## Coordinate and provenance checks

- Parsed the saved ASL and all ten prediction JSONs; their returned poses agree.
- Converted logged vehicle-box poses to rear-axle poses using metadata's 1.461 m
  rig-to-box offset before overlaying actual, reference and predicted paths.
- Anchored each plan using the controller's true current pose and the driver's
  relative plan. Verified all nine executed controller trajectories match that
  relative plan, with maximum matrix-element difference below 0.000007.
- Rotated the plot into the initial vehicle frame: forward on x, left on y.
- The plotted scorer distance deliberately remains in its original box-centre
  convention. A plotted rear-axle point need not be exactly 4.11 m from the line
  when the scorer first fails, particularly when the car is rotated.
- Actual paths connect logged half-second samples. Dashed reference tail is
  outside the simulation window; there is no extrapolated reference beyond
  the available recording.

## Conclusion and next diagnostic

**Missing action output is not the problem.** The image-only checkpoint and
experimental adapter produce paths, but this scene exposes speed-consistency
and closed-loop path-following problems. It does not isolate a single cause or
establish Cosmos' general driving quality.

Before fine-tuning or another evaluation, prioritize a static audit of the
action time/scale contract and feasible initial velocity/acceleration, followed
by the controller's response to the near-stationary third plan. Runtime-to-
controller frame transfer is numerically consistent; that alone does not prove
the upstream raw-action decoder is semantically correct.

The plotter is [plot_trajectories.py](plot_trajectories.py), a CPU-only reader of
saved artifacts; it has no model, simulator or evaluator invocation.
