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


