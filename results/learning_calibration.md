# Learning-state correction and calibration check

The shortcut learner now preserves evidence when a broad concept is split into
module-specific shortcuts. Previously, the first failure on a new child could
replace three inherited successes with zero successes and one failure. Repeated
split passes could also overwrite the child's subsequent feedback. Regression
tests cover both cases, positive feedback, and restart hydration.

The correction does not change the published HTTPX or Flask scores. It prevents
incorrect future updates; it is not an accuracy gain on these datasets.

## Experimental memory calibration

We tested five fixed memory strengths (`0.08`, `0`, `0.04`, `0.16`, `0.32`) using
only the original training split. The last 30% of training commits form a frozen
validation slice. Each candidate starts fresh, learns only from earlier commits,
and is selected by strict function accuracy@10, then MRR. Default settings win
exact ties. At least ten fitting reports and five validation reports are required.
Commit groups stay together; duplicate tickets, overlapping query text and
reversed chronology are rejected.

| Repository | Fit / validation / evaluation | Default correct@10 | Calibrated correct@10 | Default / calibrated MRR |
| --- | --- | --- | --- | --- |
| HTTPX | 35 / 16 / 33 | 15/33 | 14/33 | 0.419 / 0.350 |
| Flask | 7 / 6 / 7 | 4/7 | 4/7 | 0.550 / 0.550 |

HTTPX selected `0.32`, which performed worse on evaluation. Flask retained `0.08`
because its fitting set was too small. Calibration remains an opt-in evaluation
experiment; it does not change serving defaults or the existing runtime.

These are previously examined retrospective datasets, not a fresh confirmation
sample. The current-source-snapshot and issue-edit limitations in the original
transfer reports still apply. Neither experiment connects to HydraDB, modifies
the Django runtime, or establishes a cross-repository learning improvement.

[Full results, selection traces and source hashes](learning_calibration.json).

## Reproduce

Use the exact checkout snapshots in the existing transfer datasets, then run:

```sh
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 HF_HUB_OFFLINE=1 \
  .venv/bin/python -m scripts.eval_transfer \
  --repo work/transfer/httpx \
  --dataset results/transfer_httpx_dataset.json \
  --work work/calibration-httpx \
  --output work/calibration-httpx/results.json --calibrate
```

Omit `--calibrate` for the corrected-default comparison. Replace `httpx` with
`flask` for the other repository. Keep outputs separate from published evidence.
