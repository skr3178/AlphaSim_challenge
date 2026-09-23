# Local-only ten-example head test — user authorization

Date: 2026-09-19.

The user requested: "i want to start a small sample test that this cosmos model
can be fine tuned. pick say 10 samples and then lets run the test".

After being asked to confirm 100 waypoint-head optimizer steps with Cosmos frozen,
as a local-only test excluded from submissions, the user replied:

> keep local head only- almost the same as the odyssey 3 training for indian roads

Authorized implementation: ten real development-scene examples, frozen local
Cosmos generator/VAE, a newly initialized waypoint head, at most 100 optimizer
steps, and local diagnostics/checkpoint artifacts only. The same ten scene IDs
were selected and feature-probed before this confirmation. No holdout, full
evaluation, submission, full-backbone update or new data download is authorized.

This records user authorization for a local experiment, **not organizer training
permission**. Competition training-data eligibility remains unverified. This
experiment's fitted head is excluded from submission candidates. All 207 public
scenes from its four source logs remain marked as training-exposed for any future
independent assessment of a derived model. The original conditional eight-scene
pilot manifest and public evaluation manifest are preserved unchanged.

The samples are from Boston, Pittsburgh, Singapore and Las Vegas, not India.
The experiment follows a frozen-backbone/learned-head pattern; it does not claim
to reproduce Odyssey's data, implementation or results.
