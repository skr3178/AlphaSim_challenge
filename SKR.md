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