1. What the driver receives every tick

The simulator sends the route as ~10 waypoints that start 40 m ahead of the car and run to ~80 m. Those waypoints are the recorded human path snapped to the lane centre-line — i.e. very close to the ground-truth path the scorer measures dist_to_gt against.

```
                   route waypoints (this tick)
                     ●───●───●───●───●───●───●───●───●───●
                    40m                                   80m
```

   ═════════════════════════════════════════════════════════════════  lane
        🚗 ego
   ────── 0m ──────────  gap: nothing sent for 0–40 m  ────────────►
2. What we built (VaVAM + selection + w_disc)
The camera model proposes 5 short paths (3 s, ~15–35 m). The selector scores them against a bridge to the route and picks one. The route can only choose among the model's guesses — it never generates the path.

  camera image ──► VaVAM ──► 5 sampled paths (each ends ~30 m out)
                                  ╱╱ ─ ─ ─ ╲  candidate 1
                                 ╱ ─ ─ ─ ─ ─  candidate 2
        🚗 ═══════════════════════ ─ ─ ─ ─ ─  candidate 3  ◄─ selector picks the one
                                 ╲ ─ ─ ─ ─ ─  candidate 4     closest to a Hermite
                                  ╲╲ ─ ─ ─ ╱  candidate 5     bridge toward ●40m
                                                        ●───●───●───●  route (40–80 m)
  w_disc  = "prefer the candidate that resembles what I picked last tick"
  k, seed = which 5 guesses get drawn
  gain    = stretch the chosen path (speed)
Limits: if all 5 guesses drift 1.5 m left, the selector picks the least-bad drift — it cannot pull the car back to the lane. And the model only sees one frame, so its guesses wander scene to scene. Result on the board: every VaVAM-based entry sits at dist_to_gt ≥ 2.65 m.

1. Route follower

Two changes. (a) Accumulate: keep every route observation, transform it by the ego's motion, and stitch them. After ~4 s of driving you hold the path behind, under, and ahead of the car — the 40 m gap disappears (allowed by the organizers). (b) Follow: emit that path directly as the trajectory, with a speed profile.

  tick t-8 ......... ●───●───●───●───●
  tick t-4 ................. ●───●───●───●───●
  tick t   ......................... ●───●───●───●───●     ◄ raw observations
                                                            (each 40–80 m ahead
                                                             of where the car was)
  stitched: ●───●───●───●───●───●───●───●───●───●───●───●───●
            behind ◄──── 🚗 ────► ahead      (continuous lane-centre path)

  driver output = the stitched path from the ego forward, resampled at a chosen speed:
        🚗 ═●═●═●═●═●═●═●═●═●═●═●═  trajectory handed to the controller
  speed profile: current speed, capped by curvature (slow into turns),
                 later: a lead-vehicle guard from the camera for braking
No camera model on the lateral path. The lateral error is then just the lane-centre offset (~1 m — which is exactly NaLa's 0.98 m).

## 4. Side by side


|                              | VaVAM + selection (`w_disc` etc.)           | route follower                                                      |
| ---------------------------- | ------------------------------------------- | ------------------------------------------------------------------- |
| who decides the lateral path | camera model's random samples               | the route geometry (= GT path snapped to lane centre)               |
| role of the route            | scores/vetoes guesses through a 40 m bridge | *is* the path, accumulated to cover 0 → 80 m                        |
| model/weights                | VaVAM-B, 103–130 ms/call                    | none for steering (a few ms); optional model only for speed/braking |
| dist_to_gt achievable        | 2.6–3.7 m (all board entries)               | ~1 m (lane-centre offset)                                           |
| failure modes it removes     | few (1–2 incidents/100, at the noise floor) | lateral drift, corridor exits, wrong-lane, drift-induced collisions |
| failure modes it keeps       | everything                                  | front collisions (needs braking logic), speed choice                |
| what our tuning knobs were   | k, seed, gain, w_disc, consensus, guards    | speed profile, path smoothing, accumulation window                  |


## Route accumulation

route (accumulated, lane-centre)  ──►  reference path            ◄── fixes the lateral path
                                          │
                                          ├── speed profile(s): curvature cap, IDM-style options
                                          │
camera model (VaVAM / lead guard) ──►  longitudinal choice only   ◄── learned part, bounded
                                          │
                                          ▼
                                   trajectory → controller




## Model review

All verified against the renderer and the rollout data. Answers in order:

1. The orange/yellow line — the driver's own plan
It's selected_trajectory: the trajectory our driver returned to the simulator on that tick, drawn with color="orange", linewidth=3 (data.py:488-497). It's re-drawn every frame from driver_responses.render_at_time(..., "now"), so you're watching the plan change tick by tick. (If we ever emitted debug_info.sampled_trajectories, the k candidates would appear as thin blue lines; we don't, so you only see the chosen one.) The same plan is projected into the camera image at the bottom — that's the orange curve on the road (overlay_plans_on_camera: true).

2. The green — three different things, all green
element	style	meaning
gt_linestring	thin solid green	the recorded human path for the whole clip — what dist_to_gt is measured against
route	solid green	the map route the driver was sent (starts 40 m ahead)
route_to_first_wp	dashed green	the connector from the ego to the route's first waypoint — i.e. the 40 m gap itself
ego_gt_ghost_polygon + EGO box	limegreen fill, α 0.3	the ego and the ghost of where the human car was at this timestamp
other actors	black outline, α 0.1 (grey)	replayed traffic
So in your screenshot: the dashed green line running up the middle is the ego→route connector, the green box at the bottom is our car, and the grey box overlapping its left side is the vehicle it hit.

3. Inputs — and yes, your instinct about side/rear impacts is right
Our policy sees one camera: CAM_F0, rectified to a pinhole (fx = 1545 over 1920 px) → 63.7° horizontal FOV, ±32°. Plus ego pose history, rig-frame velocities/accelerations, and the route. No actor or obstacle data is ever sent — no boxes, no tracks.

But the interface offers more than we use: the official challenge config requests 8 cameras — CAM_F0, L0/L1/L2, R0/R1/R2 and CAM_B0 (rear) (base.yaml:125-153). VaVAM is architecturally front-only, so we discard seven of them.

Measured on candidate #2's 13 at-fault collisions (bearing of the struck actor at impact):

where the other vehicle was	count
ahead (|bearing| < 45°)	7
to the side (45–135°)	6
behind (> 135°)	0
6 of 13 were beyond ±32° — outside our camera's view at the moment of contact, including two lateral hits at +106° and −123° (vehicles overtaking on the left at 5–10 m/s; the scene in your screenshot is the +106° one). Note the scorer's rule: front bumper → collision_front, rear bumper → collision_rear, anything else → collision_lateral, and at-fault = front ∪ lateral. So drifting into a car alongside counts against us even though we couldn't see it. True rear-endings (us being hit from behind) are not at fault and happened only once in 400 scenes.

4. Do the inputs evolve?
Yes — a new image every 500 ms, fresh egomotion and a fresh route every tick. But the model doesn't accumulate any of it: VaVAM is called with a single frame (context length 1), so it has no memory between ticks. The driver keeps 32 poses, and the route follower was the only component that accumulated anything. The checkpoint was actually fine-tuned with an 8-frame context at 2 Hz — feeding it one frame is a train/test mismatch, which is exactly the B3 experiment still queued.

5. Why the plan zig-zags
Four compounding reasons, in order of contribution:

The model is stochastic. VaVAM is a flow-matching sampler — every inference integrates from fresh Gaussian noise, so consecutive plans genuinely differ. We measured a 1.7 m median spread between 5 samples at the 3 s point.
Replanning every 500 ms with new noise, so the orange line jumps between ticks (this is precisely what the w_disc continuity work targeted).
6 waypoints at 2 Hz linearly interpolated to 10 Hz → visible kinks at the 0.5 s knots, and headings computed as arctan2 of consecutive deltas amplify small lateral noise into visible angle changes.
Single-frame input (no temporal smoothing from history).
The μP fix shrank the amplitude (the raw model output was 4× too large) but didn't remove the wander — it's inherent to sampling one draw per tick.

6. The layout
Top-left — BEV, rotated so the ego always points up (rotate_map_to_ego: true), ego pinned at bottom-centre, 20 m radius. Shows map lanes/edges, replayed traffic (grey), the ego (green), the human path and route (green solid/dashed), and the driver's current plan (orange).
Top-right — metrics table. Agg = the value aggregated over the rollout so far with its aggregation rule in brackets (max for collisions/drift, last for progress, min for progress_rel); Per-Ts = the value at the current frame. In your screenshot collision_lateral 1.00 (max) with Per-Ts 0.00 means the contact happened at a different timestep than the frame you're paused on. N/A on collision_at_fault is because it's a derived event, computed at aggregation time, not per-timestep.
Bottom — CAM_F0, the actual image the model saw, with the same plan projected onto the road.
Below the table: Time: in µs of sim time.

Now, untangling the confusion — these are three separate things that only collided in today's chatter:

what it is	whose	status
Candidate #2	VaVAM-B + the μP fix — our actual driver	ours	the submission, validated on 400 scenes, staged in ECR
w_disc	a knob inside our selection branch	ours	parked
route follower	replaces the steering with the map route	ours	parked (failed the 400-scene gate)
WA-JEPA	a different model altogether	another session	being screened right now
What w_disc actually is. In the selection branch, VaVAM draws 5 candidate paths per tick (it's a stochastic sampler, so each draw differs by ~1.7 m at the 3-second point) and a rule picks one. w_disc is one weight in that rule: "prefer the candidate that resembles the one you picked last tick." Plan continuity. That's the entire scope — it doesn't change the model, only which of its own noisy guesses we trust.

Why it resurfaced today. Not because we're pursuing it. Two peer sessions claimed our scene-score numbers read 0.035 high, and the w_disc runs happened to be the reference runs everyone was calibrating against. It was a measurement argument (settled: the evaluator writes the official score, our numbers were exact), and w_disc was just the yardstick lying nearest to hand.

Are they in the same territory? Only in the loosest sense — both aim at "follow the right path" — but they operate at completely different levels, and that's the important part:

w_disc is polishing sampler noise: measured effect +0.028 on 100 scenes, inside a 0.049 band that the same unchanged config produces just by reseeding. It cannot be resolved at that scale, which is why it's parked.
WA-JEPA is replacing the model. If its tracking claim holds, it's not a 0.028-scale knob — it's the difference between 2.35 m and 0.22 m of path error, i.e. the axis we measured as 80 % of all our lost scenes.
Is WA-JEPA substantially better? Unknown, and I'd resist the temptation to believe it yet. The evidence so far is a 20-scene smoke test: dist_to_gt median 0.22 m and wrong-lane 10 %, against candidate #2's 2.35 m and 28 % on 400 scenes. That's striking — but 20 scenes is below every noise floor we've measured, and the comparison isn't paired. The 100-scene paired screen is running now (~30 min).

And we have a specific reason for caution from our own work: the route follower also produced excellent path metrics (lateral 1.20 m, best we'd ever seen) and still failed the 400-scene gate because it traded drift for collisions. Better tracking does not automatically convert into score. So the honest bar I gave that session is: WA-JEPA needs lateral error below our follower's (median 0.67 / p90 2.44 m) with at-fault no worse, and then it needs to survive 400 scenes. Until then it's a promising lead, not a better solution.


# Results 12-arm 

On the frozen 300 (stock vs μP, paired):

config	scene score	avgDist	at-fault	corridor
vavam-stock	0.8264	0.513 km	19	33
vavam + μP	0.8843	1.112 km	8	24
On navtest_local100 (μP vs WA-JEPA, paired):

config	scene score	avgDist	at-fault	corridor
vavam + μP (draw 1)	0.9067	0.936 km	3	6
vavam + μP (draw 2)	0.9064	0.937 km	3	6
wajepa-s12	0.9667	∞	0	3

steps	ms/prediction
12	974
4	364
2	215
1	140
encoder only (fixed floor)	59
That works out to roughly 63 ms fixed plus ~77 ms per step.



# ON board metrics

	km between at-fault ↑	dist_to_gt ↓
NaLa (#1, PCS 1715)	3.36	0.98
메타몽 (#1=, PCS 1715)	3.09	2.65
SymPhi (#3, 1690)	1.75	3.72
us — stock, submitted (1592)	1.62	3.05
candidate #2 (400 scenes, local)	0.90	2.35
WA-JEPA 2-step (100 scenes, local)	> 2.58 (zero incidents in 2.58 km)	1.50


## Run score

run	score ↑	zeros ↓	at-fault ↓	corridor ↓	prog<0.8 ↓	lateral med/p90 ◇	ms ↓	%wall ↓
cand #2 draw A	0.9067	9	3	6	9	0.99 / 3.13	103	16.7%
cand #2 draw B	0.8582	13	7	6	10	1.09 / 3.17	102	16.9%
cand #2 draw C (mine)	0.9064	9	3	6	9	1.05 / 3.13	104	16.8%
route follower (best prior)	0.8926	10	6	4	16	0.67 / 2.29	109	18.2%
WA-JEPA 12 steps	0.9667	3	0	3	8	0.63 / 1.76	1516	104%
WA-JEPA 4 steps	0.9493	5	0	5	5	0.35 / 2.43	520	58.3%
WA-JEPA 2 steps	0.9499	5	0	5	4	0.42 / 2.38	295	38.9%


## per scene score

The result (400 paired scenes, both sessions computed it separately and agree exactly)
candidate #2	WA-JEPA	gate
scene score	0.8813	0.9247 (+0.043)	✅
at-fault collisions	13	2	✅ (needed ≤ 8)
corridor exits	33	24	—
zero-scored scenes	46	26	—
mean progress	1.020	0.957	❌ (needed ≥ 0.989)
scenes below the 0.8 threshold	37	37	—
lateral error med/p90	0.90 / 3.50 m	0.50 / 2.64 m	—
per-city at-fault	6, 4, 3, 0	0, 1, 0, 1	✅
latency	103 ms	290 ms	✅
Per scene: 59 better, 35 worse, 306 identical — sign test p = 0.017. At-fault 13 → 2 across 400 scenes. My pre-registered prediction was "0–4 if the n=100 zero was real, 9–13 if it was noise." It's 2. The zero was real.


## Co-relation

The quadrant table (split at the medians: 1.66 km, 1.24 m)
quadrant	n	median PCS	max PCS	>1600
avgDist high + d2gt high	15	1213	1715	3
avgDist high + d2gt low	16	1096	1715	1
avgDist low + d2gt high	16	1152	1601	1
avgDist low + d2gt low	15	879	1009	0


## controller-gains


runs/wajepa-s2-400/controller-config.yaml:

field	value we used	new allowed range
long_position_weight	2.0	0–10
lat_position_weight	1.0	0–10
heading_weight	1.0	0–10
acceleration_weight	0.1	0–10
rel_front_steering_angle_weight	5.0	0–10
rel_acceleration_weight	1.0	0–10
idx_start_penalty	10	0–19
Plus mpc_implementation: nonlinear, dt_mpc: 0.1.