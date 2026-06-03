# Event Detection Discipline

These rules govern any change to `app/detector.py`. The detector is the graded
core of this project; changes here must preserve its design intent.

## No naive fixed thresholds on raw values
- Do NOT add detectors that fire on an absolute reading alone (e.g.
  `temperature > 30`). Such a rule ignores context and is explicitly out of
  scope for this project's notion of "notable".
- Anomaly detection must compare a reading against that city's RECENT history
  and normalise by how variable the field/city normally is. The same absolute
  swing must be judged differently in Vancouver (stable) than in Ottawa.

## Per-field reasoning
- Temperature, wind, and precipitation behave differently and must use
  different logic. Precipitation is near-zero most of the time, so it is handled
  categorically (onset / heavy), NOT with a z-score.
- New fields require an explicit choice of detector style; do not reuse the
  temperature path by default.

## Selectivity over noise
- A new or changed detector must be validated against `tests/test_detector.py`,
  which asserts both that expected events fire AND that a calm history stays
  quiet. If a change makes the stable-history test fire, the change is wrong.
- Every emitted event MUST include a human-readable `reason` string that states
  what happened and why it was considered notable. No event without a reason.

## Tuning constants
- Detection thresholds live as named module constants at the top of
  `detector.py` and must be documented in the README. Do not inline magic
  numbers inside the detection functions.
