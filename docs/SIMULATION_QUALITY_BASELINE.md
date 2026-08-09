# Deterministic simulation-quality baseline

`KV23-601` measures the current simulation without changing its scoring, content,
timing, population limits, or balance. It runs the authoritative engine against
three fixed seeds in disposable databases. No inference worker or provider is
started.

Install the pinned test dependencies and run:

```bash
python -m pip install '.[test]'
python scripts/run_simulation_quality.py
```

The command runs each seed twice and writes stable evidence to:

- `.qa/simulation-quality/simulation-quality.json`
- `.qa/simulation-quality/simulation-quality.md`

The JSON is sorted, contains no timestamps or temporary paths, and is byte-stable
when the same code, schema, seeds, and configuration produce the same simulation.
The Markdown file is a compact human review of the same data. Both files are meant
for CI artifacts rather than source control.

## Measurements

- **Behaviour:** decisions and actions by resident, life stage, and hour; repeated
  action streaks; alternative diversity; interrupted choices; missed commitments;
  critical-need duration; and goal status.
- **Social:** interactions and isolation; changed relationship pairs; movement in
  every relationship dimension; interaction concentration; and repeated
  conversation summaries.
- **Economy:** double-entry reconciliation; transaction categories and volume;
  owner balance changes; product and category turnover; inventory movement; price
  movement; stockouts; and business status.
- **Care and health:** observed dependent coverage; scheduled coverage; guardians,
  active arrangements, caregiver load, failed handoffs, and untreated conditions.
- **Events:** category and event-type counts, dominant shares, concentration, and
  repeated town-event streaks.
- **Lifecycle and population:** stage distribution, births, deaths, population and
  adult caps, housing/capacity, duplicate births, and post-death activity.
- **Narrative evidence:** ledger-linked claims, explained decisions, verified
  chronicles, and proof that model attempts stayed at zero.
- **Reproducibility:** every fixed seed is replayed from a new database; stable
  domain digests and the complete metrics must match.

The command exits nonzero only when deterministic replay or a correctness invariant
fails. Observational values such as action mix, relationship movement, product
turnover, and event concentration are recorded without arbitrary pass thresholds;
they are the baseline for later balance work.

For a quick local plumbing check, keep at least two seeds and shorten the run:

```bash
python scripts/run_simulation_quality.py \
  --seed 3131313131313131313131313131313131313131313131313131313131313131 \
  --seed 3232323232323232323232323232323232323232323232323232323232323232 \
  --ticks 24 \
  --output-dir .qa/simulation-quality-smoke
```
