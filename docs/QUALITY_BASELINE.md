# KVsim Quality Baseline

This is the measurable quality baseline for `KV23-003`, recorded against
`9e9883622a1be011f9bc6b9055747b6bdde90bcd`. It adds gates without reformatting or
otherwise changing the existing simulation, API, frontend runtime, or deployment code.

## Python

Install the pinned QA dependencies and run the Ruff regression gate:

```bash
python -m pip install '.[test]'
python scripts/check_python_quality.py
```

The gate runs Ruff lint and formatter verification across `src`, `tests`, `scripts`,
and both release tools. The exact baseline debt is machine-readable in
`scripts/ruff_baseline.json`: 15 lint findings and 36 files that predate Ruff
formatting. Any difference from that exact baseline fails the command; intentional
cleanup must refresh the baseline in the same change.

Measure line and branch coverage without enforcing a threshold yet:

```bash
python -m pytest \
  --cov=krabville \
  --cov-report=term-missing \
  --cov-report=json:.qa/coverage.json
```

Baseline result on Python 3.13.6: 123 passed, 1 skipped in 125.4 seconds. Coverage
was 4,656 of 5,585 statements (83.4% line coverage), 1,429 of 1,978 branches
(72.2% branch coverage), and 80.5% combined. This records the starting point; it
does not set a fail-under threshold before the team has trend data.

## Frontend

Install exactly the locked packages, then run the TypeScript-aware Oxlint check and
the existing compiler/build gate:

```bash
cd frontend
npm ci --ignore-scripts
npm run lint
npm run build
```

Oxlint checks correctness rules across frontend source, scripts, and build/test
configuration. The config narrowly accepts three pre-existing findings in
`src/main.ts`; warnings elsewhere fail the command. TypeScript compilation remains
part of `npm run build`.

## Unified release verification

Prepare the pinned Python and frontend dependencies and install Playwright Chromium,
then run the release gate from the repository root:

```bash
python -m pip install '.[test]'
cd frontend
npm ci --ignore-scripts
npx playwright install chromium
cd ..
python tools/verify_release.py
```

The Python entrypoint is the only release-check invocation used by CI. In order, it
runs release identity/schema consistency, Python quality, the complete Python suite,
a wheel build, frontend lint/build, Compose validation, the tracked-secret scan, a
seeded API health check, and every Playwright project. The runtime always uses a
temporary data directory and a free
loopback port; ambient `KRABVILLE_*` settings are discarded. Per-run command output,
API health/server logs, wheel output, and Playwright failure evidence remain under
`.qa/verify-release/`.
