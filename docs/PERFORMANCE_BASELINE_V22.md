# KVsim v2.2 Performance Baseline

KV23-201 records the current state, refresh, render, and asset hot path before the
2.3 read-model and loading work changes it. The machine-readable evidence is
[`performance/KV23-201_V22_BASELINE.json`](performance/KV23-201_V22_BASELINE.json).
This is a measurement baseline, not a performance gate; KV23-404 owns budgets.

## Reference workload

- Source under test: `d1243a53dc234eef606d2bf7c1a5fcdac5bba6ee`
- Synthetic release fixture: KVsim `2.2.1`, schema 13, tick 44
- Fixture SHA-256: `9749386cb96381fb6581fec222db5b222fa18e2af5007779bdc31eb6afc566a5`
- Runtime migration level during the sample: schema 14
- State shape: 12 residents, 32 events, 45 properties, and 67 accounts
- State protocol: two warmups followed by seven measured samples
- Browser protocol: Chromium 151, `1366x768`, loopback, ten-minute foreground soak
- Reference host: Windows AMD64, Python 3.13.6, Node.js 22.18.0

The retained fixture is synthetic and deterministic. The profiler uses a temporary
database and loopback API; it does not read production state or contact the Pi.

## Results

| Metric | v2.2 baseline |
|---|---:|
| SQL statements per `/api/v3/state` | 796 (765 `SELECT`, 31 `PRAGMA`) |
| Measured SQLite execute/fetch time | 33.209 ms median; 50.235 ms p95 |
| State construction | 43.792 ms median; 61.227 ms p95 |
| JSON serialization | 2.236 ms median; 2.935 ms p95 |
| In-process route round trip | 60.785 ms median; 222.755 ms p95 |
| State payload | 160,255 bytes raw; 14,736 bytes gzip |
| Chromium `JSON.parse` | 0.4 ms median; 1.2 ms p95 |
| Complete frontend build | 30,748,321 bytes raw; 29,740,738 bytes gzip |
| Observed initial static transfer | 14,960,244 bytes raw; 13,951,117 bytes gzip |
| Shell ready | 375.835 ms |
| Map interactive | 5,562.482 ms |
| Full-state refresh cadence | 4,996.961 ms median; 11.982 requests/minute |
| Ten-minute refreshes | 120 during the soak; 123 over the full observation |
| SSE | 1 connection; 0 reconnects; 32 retained events received |
| Used JS heap | 10,412,704 to 11,593,988 bytes; +1,181,284 bytes |
| DOM nodes/listeners | 564/185 initially and finally |
| Browser errors | 0 console, 0 page, 0 failed requests |

The initial gzip estimate is dominated by assets that the current page requests
before any interior or event-detail interaction:

| Initial file | Gzip bytes |
|---|---:|
| Spring map | 4,711,118 |
| Interior atlas | 4,020,118 |
| Event-prop atlas | 1,996,836 |
| Two resident atlases | 1,904,016 |
| Weather atlas | 548,582 |
| Life-stage atlas | 413,351 |
| Phaser/game chunk | 321,734 |

These numbers establish the comparison points for KV23-203, KV23-206, and
KV23-401 through KV23-404: query count, state bytes, polling frequency, initial
asset transfer, map readiness, and ten-minute browser growth.

## Run it

The retained report is an immutable historical measurement. Reproduce it only
from the recorded source and migration set; the profiler rejects any other HEAD
or runtime schema. From this branch, create a detached source worktree and copy
only the measurement tools into it:

```bash
SOURCE_REPO="$(pwd)"
git worktree add --detach ../Krabville-kv23-201-source d1243a53dc234eef606d2bf7c1a5fcdac5bba6ee
cp tools/profile_performance.py ../Krabville-kv23-201-source/tools/profile_performance.py
cp frontend/scripts/profile-performance.mjs ../Krabville-kv23-201-source/frontend/scripts/profile-performance.mjs
cd ../Krabville-kv23-201-source
python -m pip install '.[test]'
cd frontend
npm ci --ignore-scripts
npx playwright install chromium
cd ..
python tools/profile_performance.py --output "$SOURCE_REPO/.qa/performance/kv23-201-reproduction.json"
```

The command rebuilds the pinned frontend, verifies and migrates a temporary copy
of the retained fixture to schema 14, samples `/api/v3/state`, starts a loopback
API, and performs the ten-minute Chromium soak. It writes outside the committed
evidence path. A short non-committed smoke can add
`--browser-duration-seconds 5 --output "$SOURCE_REPO/.qa/performance/smoke.json"`.

## Interpretation limits

- SQL time is wall time around SQLite execute and row-fetch operations. It is not
  a native SQLite CPU profile.
- Gzip values use deterministic level-9 compression over built files and response
  bytes. They are comparison estimates; a CDN's wire encoding can differ.
- Render timings are a warm local loopback reference, not the later 10 Mbps and
  4x CPU release profile.
- CDP heap and DOM counters are reliable within Chromium but are not whole-process
  RSS. The used-heap delta is the useful comparison; reserved heap can grow without
  representing a leak.
- No threshold is enforced here. Any budget change belongs in a dedicated benchmark
  PR with evidence, as required by the 2.3 plan.
