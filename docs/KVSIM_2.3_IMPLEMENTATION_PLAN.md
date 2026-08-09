# Krabville KVsim 2.3 Implementation Plan

**Release name:** KVsim 2.3 — **Trust, Clarity, and Performance**  
**Status:** Authoritative implementation handoff  
**Repository:** `n30nex/Krabville`  
**Baseline branch:** `main`  
**Baseline release:** `v2.2.1`  
**Baseline commit:** `f630a9502b029097deeecbbc85b0f74aca4e99f9`  
**Baseline database level:** migration `013_kvsim_v22_depth.sql`  
**Plan date:** 2026-08-09

> Use this document as the controlling plan for KVsim 2.3. Do not replace it with a larger speculative roadmap. Work through the ordered PR backlog, preserve the existing deterministic simulation, and keep `main` releasable after every merge.

> **Baseline amendment:** v2.2.1 is the deployed starting point. It contains only the v2.2.0 inference boot-order reliability hotfix: web and engine start before a separately systemd-supervised inference worker. Database level remains migration 013.

---

## 1. Release mission

KVsim 2.2 established substantial simulation depth: authoritative ledger-backed history, deeper resident decisions, persistent goals, health and care, categorized economics, housing recovery, and bounded model enrichment.

KVsim 2.3 must make that depth **trustworthy, understandable, fast to watch, and safe to continue extending**.

The release promise is:

> **A visitor can open Krabville, understand the most important thing happening in the town, see who is involved, inspect why a resident acted, and follow the consequence—while the system remains recoverable, observable, efficient, and backward compatible.**

KVsim 2.3 is not a content expansion release. It is the release that turns the existing project into a durable public simulation product.

### 1.1 Required outcomes

| Outcome | KVsim 2.3 requirement |
|---|---|
| **Trustworthy** | Claimed browser, migration, replay, soak, backup, and restore validation becomes reproducible and required. |
| **Readable** | The default interface leads with the current story and its participants instead of exposing every analytical view at once. |
| **Explainable** | The backend is the sole authority for decisions, alternatives, factors, destinations, and evidence. |
| **Efficient** | Normal connected clients no longer download the complete public state every five seconds. Heavy assets and detail data load only when needed. |
| **Recoverable** | A failed tick, bad migration, stale event stream, or damaged deployment produces a visible diagnosis and a tested recovery path. |
| **Compatible** | Existing `/api/v3` consumers, live databases, seed determinism, public voting, and model-disabled operation remain supported. |
| **Maintainable** | The minimum frontend/backend extraction needed for the new transport and Watch experience is completed without a framework rewrite. |

---

## 2. Current baseline to preserve

KVsim 2.3 starts from a strong production baseline. The following are preservation requirements, not rewrite targets:

- The deterministic engine remains authoritative.
- World time never waits for model output.
- Model-generated dialogue, intentions, reflections, and chronicles remain bounded, schema-constrained, asynchronous, and optional.
- A failed model lane may reduce flavour but may not stop or corrupt deterministic simulation progression.
- SQLite WAL, foreign keys, busy timeouts, transaction boundaries, additive migrations, and online backup support remain intact.
- Public data remains read-only except for the existing bounded vote endpoint.
- Existing CSRF, signed voter identity, rate limiting, public-text sanitation, container hardening, and model credential isolation remain intact.
- Seed commitment, seed reveal, deterministic replay, lifecycle, care, housing, commerce, and accounting behaviour remain compatible unless a task explicitly documents an intentional correction.
- The public site continues to support desktop, compact displays, mobile/touch, keyboard access, and reduced motion.
- Existing `/api/v3/state`, `/api/v3/events`, `/api/v3/events/stream`, resident, property, poll, relationship, economy, and season routes remain available through the full 2.3 release.
- The live production database must be upgraded in place. A database reset is not an acceptable implementation shortcut.

### 2.1 Baseline constraints

Current implementation characteristics that directly shape the 2.3 work:

- The frontend currently subscribes to SSE and also refreshes the complete `/api/v3/state` payload every five seconds.
- The complete state route assembles residents, decisions, goals, life goals, properties, businesses, economy, analytics, care, health, housing, communications, chronicles, ledger evidence, model state, and archives.
- `frontend/src/main.ts`, `src/krabville/api.py`, `src/krabville/world.py`, `src/krabville/runtime_v2.py`, and `src/krabville/commerce_v2.py` have become broad multi-responsibility modules.
- The frontend contains its own location coordinate map and can synthesize resident forecasts when authoritative candidates are missing.
- The initial map path preloads the current exterior plus resident, life-stage, interior, event-prop, and weather atlases.
- Playwright already covers five viewport sizes and reduced motion, but the current required CI job does not execute it.
- Production v2.2.1 is released and identifies commit `f630a9502b029097deeecbbc85b0f74aca4e99f9`.

---

## 3. Scope

### 3.1 In scope for 2.3

1. Required release and browser gates.
2. Migration, upgrade, backup, restore, and rollback automation.
3. Tick freshness, runtime incidents, structured logs, and operational metrics.
4. A slim bootstrap/live-state contract and normalized frontend state store.
5. SSE-first delivery with sequence-gap recovery and periodic reconciliation.
6. A generated/shared world manifest.
7. Server-authoritative resident decision explanations.
8. A story-first **Watch** experience.
9. Simplified resident information architecture.
10. Resident, event, story, property, and season deep links.
11. Lazy Phaser and asset loading, mobile map variants, and caching.
12. Accessibility, mobile, empty-state, stale-state, paused-state, and degraded-state refinement.
13. A deterministic simulation-quality report that establishes the baseline for 2.4.
14. Minimal module extraction required to deliver the above safely.

### 3.2 Explicit non-goals

Do not include these in KVsim 2.3:

- Increasing the 20-season campaign length.
- Increasing the planned population or adult caps.
- Adding another major economy, lifecycle, relationship, health, housing, or inventory subsystem.
- Increasing model-call or token ceilings.
- Adding new model providers merely for variety.
- Turning visitors into direct resident controllers.
- Adding free-text public prompts or chat input.
- A frontend framework rewrite.
- A database-engine migration away from SQLite.
- A broad visual-art replacement.
- Merging the Phaser 4 major-version dependency update directly into the release branch.
- Arbitrary mod scripts or executable user content.
- Breaking or removing `/api/v3/state` during the 2.3 cycle.

### 3.3 Compatibility rules

- All database changes are additive.
- Applied migration files are immutable.
- Any new migration starts after `013`.
- Existing public route response fields remain valid; new hot-path routes may be added.
- Existing event names remain accepted during 2.3.
- The new client may stop using `/api/v3/state` as its normal live path, but the route remains tested.
- New client state must recover from a 2.2 event stream and a 2.2-compatible database.
- Model-disabled and fake-provider operation must remain first-class test configurations.

---

## 4. Product design for 2.3

### 4.1 Watch mode

Watch mode becomes the default public experience.

It must answer, without opening Analytics:

1. What is happening right now?
2. Who is involved?
3. Why are they acting?
4. What has changed because of it?
5. What should the visitor watch next?

#### Desktop layout

- The map remains the dominant visual area.
- A story stack or story drawer shows no more than three active items.
- The top story contains:
  - story/event title;
  - category and status;
  - two-line factual summary;
  - participants;
  - primary location;
  - latest consequence;
  - next unresolved question or likely next step;
  - links to evidence and affected residents.
- Resident navigation remains available but no longer competes visually with the active story.
- Voting remains immediately visible whenever open.

#### Mobile layout

- The map occupies the main viewport.
- The current story appears in a swipeable or expandable bottom sheet.
- A compact bottom navigation exposes **Watch**, **Map**, **People**, **Town**, and **Archive**.
- The visitor can close the sheet and use the map without losing the current story.
- The minimap may be hidden or simplified when it reduces useful map space.

#### Watch mode content rules

- Factual statements must come from the authoritative ledger/read model.
- Predictions must be labelled as forecasts.
- Model prose cannot be the sole evidence for a story claim.
- Stories must link to stable resident, property, event, ledger, decision, or season identifiers.
- The interface must distinguish **current fact**, **recent consequence**, and **likely next step**.

### 4.2 Navigation

Recommended top-level information architecture:

1. **Watch** — current story stack and town pulse.
2. **Map** — clean full-map exploration and optional overlays.
3. **People** — residents, households, and families.
4. **Town** — places, businesses, services, economy summary, and advanced analytics.
5. **Archive** — days, seasons, reports, and factual history.

Economy and Analytics remain available, but they move under Town or an **Inspect** subsection rather than appearing as equal first-level destinations beside the live story.

### 4.3 Resident inspector

The current detailed data remains available, but the first resident view must show:

- name, role, life stage, mood, location, and current activity;
- current intention;
- authoritative reason for the current/next decision;
- top alternative considered;
- one urgent need or constraint;
- active goal and progress;
- relevant relationship/care obligation;
- latest consequence or evidence record.

Consolidate the existing peer tabs into five sections:

1. **Overview** — identity, current activity, intention, mood, decision explanation.
2. **Life** — needs, health, care, wants, aspirations, and goals.
3. **Social** — family, relationships, calls, beliefs, gossip, and secrets visible to spectators.
4. **Work & Home** — career, money, accounts, property, clothing, carried goods, and home inventory.
5. **Evidence** — memories, decisions, factors, goal evidence, transactions, and permanent life ledger.

The grouped sections must preserve all current information. This is an information-architecture change, not a data deletion.

### 4.4 Event and consequence timeline

Every current story needs a compact evidence timeline:

- initiating vote or town event;
- participants selected;
- relevant resident decisions;
- resulting activities, conversations, purchases, care, health, housing, goal, relationship, or economic changes;
- current unresolved outcome.

Use existing authoritative IDs wherever possible. Add one generic causal-link mechanism only when the existing schema cannot represent a stable relationship. Do not add a different causal foreign-key column to every table.

### 4.5 Discovery and deep links

Add stable public routes:

```text
#/watch
#/resident/<slug>
#/property/<slug>
#/event/<id>
#/story/<id>
#/season/<id>
#/explore/<section>
```

Add resident search and filters for:

- name;
- life stage;
- household;
- current place;
- mood;
- urgent need;
- active story participation.

A visitor should be able to share a specific resident, place, event, story, or season without first reproducing the navigation path.

### 4.6 Required states

Every major view must have designed and tested states for:

- initial loading;
- no active season;
- running;
- paused;
- completed;
- intermission;
- model degraded;
- engine degraded;
- stale event stream;
- reconnecting;
- sequence gap recovery;
- empty list;
- request failure;
- archived/legacy data with incomplete verification metadata.

Do not represent all failures as “Connecting.”

### 4.7 Accessibility requirements

- All principal routes are usable without the canvas.
- Drawers, sheets, and dialogs trap focus and restore it when closed.
- Keyboard focus is always visible.
- Escape closes the current topmost layer only.
- Story changes use an `aria-live` summary with throttling; do not announce every tick.
- Need severity, relationship state, and service health use text/icons in addition to colour.
- Reduced motion disables non-essential camera movement, sprite wandering, pulses, and weather animation.
- Touch targets meet a minimum 44×44 CSS-pixel target where practical.
- Primary routes have no critical or serious axe violations.

---

## 5. Technical target architecture

### 5.1 Live client data flow

The normal 2.3 client flow is:

```text
GET /api/v3/bootstrap
        ↓
normalized client store
        ↓
GET /api/v3/events/stream (Last-Event-ID)
        ↓
apply typed event deltas
        ↓
sequence-gap detection
        ├─ no gap → continue
        └─ gap → GET /api/v3/events?after=<last-seq>
                    ↓
              apply backfill
                    ↓
       compact reconciliation snapshot
```

Detail data loads only when required:

```text
resident panel → /api/v3/residents/<slug>
property panel → /api/v3/properties/<slug>
economy detail → /api/v3/economy or a new summary/detail split
archive → /api/v3/seasons/<id>
```

`/api/v3/state` remains available as a compatibility and diagnostic snapshot but is not the normal five-second browser path.

### 5.2 New read models

Add focused routes without breaking existing v3 routes.

#### `GET /api/v3/bootstrap`

Contains only what the shell needs:

- release version and commit;
- API/event schema versions;
- current season summary;
- current sequence ID;
- capabilities;
- world-manifest URL/hash;
- minimal resident summaries;
- current poll summary;
- active Watch stories;
- connection/freshness metadata.

#### `GET /api/v3/world`

Compact reconciliation state:

- resident position, destination, path key, location, activity, mood, updated tick;
- compact urgent-need indicators;
- visible props and active world effects;
- current time/weather;
- active story participation;
- current sequence ID.

Do not include deep resident history, inventories, account ledgers, full analytics, or season archives.

#### `GET /api/v3/stories`

Returns active Watch items and their evidence references:

- stable story ID;
- root event/ledger ID;
- status;
- title and factual summary;
- participant slugs;
- place slug/map location;
- latest consequence;
- forecast label, if any;
- evidence links;
- updated tick/sequence.

#### Optional summary routes

Add only when profiling proves the existing routes are too broad:

- `/api/v3/economy/summary`
- `/api/v3/analytics/summary`
- `/api/v3/seasons/current/summary`

Do not create unused route families pre-emptively.

### 5.3 Public event envelope

Centralize all public event parsing around one versioned envelope while accepting existing event names.

Recommended shape:

```json
{
  "eventVersion": 1,
  "seq": 9001,
  "seasonId": 3,
  "tick": 733,
  "type": "decision",
  "entity": {
    "kind": "resident",
    "id": "maya-lin"
  },
  "storyId": "town-event-42",
  "payload": {},
  "createdAt": "2026-08-09T15:00:00Z"
}
```

Requirements:

- `seq` is monotonically increasing within the event stream.
- The client stores the last fully applied sequence.
- Unknown event types are logged and ignored safely rather than crashing the client.
- Event payloads are schema-validated in development/tests.
- One registry owns the supported public event list. Do not maintain separate event arrays in `api.ts` and `main.ts`.
- Existing SSE `event:` names remain usable for compatibility.

### 5.4 Authoritative decision contract

Every resident summary/detail with an active or recent decision should expose:

```json
{
  "decisionId": 123,
  "phase": "pondering",
  "selected": {
    "action": "eat_meal",
    "label": "Share a meal",
    "destination": "Hobbs Cafe",
    "expectedMinutes": 35,
    "score": 83.4,
    "confidence": 0.78
  },
  "alternatives": [
    {
      "action": "restore_energy",
      "label": "Rest at home",
      "destination": "Willow House",
      "score": 61.2
    }
  ],
  "positiveFactors": [],
  "negativeFactors": [],
  "constraints": [],
  "relatedGoalIds": [],
  "evidenceIds": []
}
```

The client may format this information, but it may not independently rank actions or invent reasons. Remove the unlabelled heuristic fallback from the public resident view.

If no authoritative decision exists, show a truthful empty state such as **No recorded decision yet**.

### 5.5 Shared world manifest

Create one generated or server-served world manifest containing:

- manifest version and release commit;
- world dimensions;
- coordinate-space version;
- locations and coordinates;
- property/map mappings;
- seasonal exterior assets;
- resident/life-stage atlas metadata;
- interior frame metadata;
- event-prop semantic groups;
- inventory atlas metadata;
- content hashes and dimensions.

The frontend game consumes the manifest. Backend tests validate it. CI fails when generated manifest content is stale.

Remove the duplicate hard-coded frontend location table once parity is proven.

### 5.6 Frontend module target

Do not introduce a framework rewrite. Extract only the boundaries needed for 2.3:

```text
frontend/src/
  app/
    shell.ts
    router.ts
    store.ts
    live-events.ts
    connection-state.ts
  api/
    client.ts
    contracts.ts
  views/
    watch.ts
    map.ts
    people.ts
    town.ts
    archive.ts
  resident/
    summary.ts
    dossier.ts
    sections/
  story/
    cards.ts
    timeline.ts
  game/
    index.ts
    scene.ts
    residents.ts
    buildings.ts
    weather.ts
    camera.ts
  ui/
    drawer.ts
    sheet.ts
    tabs.ts
    loading.ts
    formatting.ts
    accessibility.ts
```

Migration rule: extract behaviour behind existing tests, then change it. Do not move and redesign the same broad module in one PR.

### 5.7 Backend module target

Extract read-model and operations boundaries without attempting the complete v3 domain rewrite:

```text
src/krabville/
  api/
    app.py
    models.py
    routers/
      health.py
      bootstrap.py
      world.py
      stories.py
      residents.py
      properties.py
      economy.py
      polls.py
      seasons.py
      events.py
    read_models/
      bootstrap.py
      world.py
      stories.py
      resident.py
  operations/
    incidents.py
    backup.py
    migrations.py
    metrics.py
```

The existing broad modules may remain compatibility facades during 2.3. The release does not require a complete backend domain split.

### 5.8 Runtime and deployment target

Deployment order becomes explicit:

```text
backup/verification
        ↓
one-shot migrate/bootstrap job
        ↓
web ready
        ↓
engine ready and advancing
        ↓
inference optional/ready
```

Add:

- `/livez` — process responsive;
- `/readyz` — service can perform its role;
- `/healthz` — human-readable sanitized summary;
- `/metrics` or a private equivalent — machine-readable runtime metrics;
- `krabville-manage diagnose --json`;
- `krabville-manage backup`;
- `krabville-manage verify-backup`;
- `krabville-manage restore --dry-run`;
- migration checksums;
- durable runtime incidents for repeated authoritative tick failures.

A paused, completed, or intermission season is healthy. A stale or repeatedly failing authoritative tick is not ready.

---

## 6. Implementation phases

### Phase 0 — Freeze and rep…70 tokens truncated…, and commerce.
- Engine restart during ordinary tick, settlement, new day, poll close, and season close.
- Model-disabled and provider-failure runs.
- Backup, verify, disposable restore, and rollback rehearsal.
- SSE disconnect, reconnect, sequence-gap, and season-transition tests.
- Performance budgets.
- Security headers, vote security, secret scan, dependency audit, image scan, and SBOM.
- Release version, tag, image, commit, schema, and UI-health consistency.

#### Exit criteria

- No open P0 or P1 regressions.
- All required workflows pass on the release commit.
- Release notes identify schema, API, UI, operational, and performance changes.
- A verified pre-deployment backup exists.
- The previous image/commit remains available until live checks pass.
- Production health confirms tick freshness, sequence advancement, Watch rendering, resident/property routes, vote flow, and inference isolation.

---

## 7. Ordered PR backlog

The merge order below is authoritative. Small PRs are intentional: they reduce regression risk and allow independent review.

| ID | Priority | PR title | Primary owner | Depends on | Acceptance evidence |
|---|---:|---|---|---|---|
| **KV23-001** | P0 | Add `RELEASE_BASELINE_V22.md` and 2.3 scope lock | Integrator | none | Baseline commit, schema, routes, assets, commands, non-goals recorded |
| **KV23-002** | P0 | Run existing Playwright matrix in required CI | QA/Release | 001 | Desktop, mobile, reduced-motion jobs; traces/screenshots/logs on failure |
| **KV23-003** | P0 | Add focused Python/frontend quality checks | QA/Release | 001 | Ruff/format, frontend lint, coverage baseline; no broad unrelated reformat |
| **KV23-004** | P0 | Create unified `verify-release` entrypoint | QA/Release | 002,003 | Local and CI execute the same ordered checks |
| **KV23-005** | P0 | Add v2.2 migration fixture and replay verification | Backend/QA | 001 | Migration, reads, short replay, FK/accounting report |
| **KV23-006** | P0 | Enforce release version/commit/schema consistency | Backend/Release | 001 | Package, frontend, image, health, tag inputs agree |
| **KV23-101** | P0 | Add tick freshness, queue health, and runtime metrics | Backend/Ops | 001 | `/healthz`/metrics and `diagnose --json` show actionable freshness |
| **KV23-102** | P0 | Add structured logs and correlation fields | Backend/Ops | 101 | Season/tick/resident/job/sequence/elapsed fields in logs |
| **KV23-103** | P0 | Add bounded authoritative tick-failure incidents | Engine/QA | 101,102 | Injected fault retries same tick, records incident, degrades without skipping |
| **KV23-104** | P0 | Create one-shot migration/bootstrap service with checksums | Backend/Ops | 005 | One migration owner; modified applied migrations rejected |
| **KV23-105** | P1 | Add backup, verify, and dry-run restore commands | Backend/Ops | 104 | Disposable restore serves state and advances fake-provider ticks |
| **KV23-201** | P0 | Profile current state/refresh/asset hot path | Performance/QA | 004 | Query, bytes, parse, render, transfer, memory baselines saved |
| **KV23-202** | P0 | Define shared API/event contracts and event registry | Backend/Frontend | 001 | One event union/registry; contract fixtures; unknown event safe handling |
| **KV23-203** | P1 | Add bootstrap, world, and stories read models | Backend | 201,202 | Golden payload fixtures, query/size tests, v3 state unchanged |
| **KV23-204** | P1 | Add normalized frontend store and one live-event controller | Frontend | 202,203 | Existing map/routes render from store; one EventSource instance |
| **KV23-205** | P1 | Add SSE sequence-gap backfill and reconciliation | Full stack | 204 | Disconnect, dropped sequence, season transition, visibility-return tests |
| **KV23-206** | P1 | Remove normal five-second full-state refresh | Frontend/Backend | 205 | No `/state` polling while connected; stale/reconnect states visible |
| **KV23-301** | P1 | Generate and consume shared world manifest | Backend/Game | 201,202 | Duplicate frontend coordinates removed; manifest validation in CI |
| **KV23-302** | P1 | Make decision explanations fully server-authoritative | Simulation/API/Frontend | 202 | API, peek, Overview, and dossier show identical decision; local heuristic removed |
| **KV23-303** | P1 | Add minimum causal evidence links for current stories | Simulation/API | 302 | Event→decision→effect traversal works for new records |
| **KV23-401** | P1 | Dynamically load Phaser after Watch/bootstrap shell | Frontend/Game | 203,204 | Story shell useful before canvas; map remains functional |
| **KV23-402** | P1 | Lazy-load interior, inventory, and event asset packs | Frontend/Game | 401 | Heavy atlases absent from ordinary first load |
| **KV23-403** | P1 | Add mobile map variants and immutable asset caching | Frontend/Art/Ops | 401 | Mobile transfer/memory targets and cache-header tests pass |
| **KV23-404** | P1 | Enforce performance budgets in CI | Performance/QA | 201,401-403 | Transfer, payload, interaction, memory, console gates |
| **KV23-501** | P1 | Build Watch route and active story stack | Frontend/UX | 203,204,303 | Desktop/mobile story acceptance flow passes |
| **KV23-502** | P1 | Consolidate top-level navigation | Frontend/UX | 501 | Watch/Map/People/Town/Archive; legacy routes preserved |
| **KV23-503** | P1 | Consolidate resident dossier into five sections | Frontend/UX | 302,501 | All old data retained; Overview shows authoritative decision |
| **KV23-504** | P1 | Add event/story timeline and stable deep links | Full stack | 303,501 | Resident/property/event/story/season URLs survive refresh |
| **KV23-505** | P1 | Add resident search, filters, and follow mode | Frontend/Game | 503,504 | Follow survives live updates; manual camera override works |
| **KV23-506** | P1 | Complete accessibility, mobile sheets, and state handling | Frontend/QA | 501-505 | Keyboard, axe, touch, reduced-motion, stale/error/empty states pass |
| **KV23-601** | P1 | Add deterministic simulation-quality baseline report | Simulation/QA | 004 | Multi-seed behaviour/social/economy/care report without balance changes |
| **KV23-602** | P0 | Add release-candidate, nightly soak, and restore workflows | QA/Release | 004,105,206,404,506,601 | Required RC artifacts and failure reproduction commands |
| **KV23-603** | P0 | Prepare and validate `v2.3.0` release | Integrator | all above | Production-compatible upgrade, backup, deploy, live checks, rollback evidence |

### 7.1 Critical path

```text
001 → 002/003 → 004 → 201/202 → 203 → 204 → 205 → 206
                                         ├→ 301 → 302 → 303
                                         └→ 401 → 402/403 → 404
303 + 204 → 501 → 502/503 → 504 → 505 → 506
004 + 105 + 206 + 404 + 506 + 601 → 602 → 603
```

### 7.2 Parallel work rules

Safe parallel groups after their prerequisites are merged:

- `KV23-002`, `003`, `005`, and `006`
- `KV23-101` and `201`
- `KV23-301` and `302` after contract ownership is settled
- `KV23-402` and `403`
- `KV23-502` and `503` after Watch is stable

Do not run overlapping edits in `api.py`, `main.ts`, `game.ts`, or migration files without one named integrator. Parallel agents may audit or prepare tests, but one owner merges each code path.

---

## 8. Validation matrix

### 8.1 Every PR

Run all applicable checks:

- focused unit/integration tests;
- complete Python suite when authoritative simulation or schema changes;
- TypeScript build and frontend unit tests;
- affected Playwright routes/viewports;
- deterministic replay fixture for behaviour changes;
- database migration test for schema changes;
- contract fixture for API/event changes;
- accessibility checks for UI changes;
- before/after performance evidence for hot-path or asset changes;
- documentation update for new commands/contracts.

### 8.2 Nightly

- accelerated complete-season run;
- multi-seed simulation-quality report;
- multi-season soak;
- economy/accounting reconciliation;
- migration from retained release fixtures;
- backup/restore verification;
- production image build and clean-stack synthetic browser run;
- dependency and image scan;
- browser memory and event reconnect soak.

### 8.3 Release candidate

- all nightly and per-PR checks on the exact release commit;
- production-database copy upgrade;
- fake-provider and model-disabled runs;
- provider timeout/failure and fallback tests;
- restart tests at settlement, day change, poll close, season close;
- performance budgets;
- version/tag/image/commit/schema consistency;
- release notes and rollback instructions;
- verified pre-deployment backup.

### 8.4 Live deployment smoke

Immediately after deployment verify:

1. `/livez`, `/readyz`, and `/healthz` report the expected commit/schema.
2. Tick and event sequence advance.
3. Watch renders a factual current story.
4. Map loads and residents move/update.
5. A resident detail shows an authoritative decision explanation.
6. A property detail opens.
7. Vote flow works when open.
8. Disconnect/reconnect resumes from the last sequence.
9. Model lane status is correct and credentials remain isolated.
10. Logs contain no repeated incidents or unexpected 5xx responses.

Keep the prior image and backup until these checks pass through at least one settlement boundary.

---

## 9. Reliability and rollback policy

### 9.1 Rollback triggers

Rollback or stop progression when any of the following occur after deployment:

- database integrity or foreign-key failure;
- repeated failure of the same authoritative tick;
- tick freshness exceeds the agreed threshold during a running season;
- sequence advancement stops while the engine reports running;
- migration checksum mismatch;
- unexplained accounting imbalance;
- public state/Watch data exposes private operational content;
- sustained 5xx errors on bootstrap/world/events/resident routes;
- browser cannot render the fallback non-canvas Watch experience;
- upgrade has modified live data in a way not reproducible from migration tests.

### 9.2 Rollback procedure

1. Pause or stop all three services.
2. Preserve the failed database and logs for diagnosis.
3. Restore the verified pre-deployment backup only if the migration is not safely backward readable.
4. Deploy the previously recorded image/commit.
5. Run health, state, tick, and event-sequence checks.
6. Resume only after database and accounting checks pass.
7. Open a P0 issue with the failed release commit, schema, tick, incident ID, and reproduction command.

Never delete the failed database before a copy is retained.

---

## 10. Simulation-quality baseline for 2.4

KVsim 2.3 should measure current behaviour without turning into a large balancing release.

The report must run across fixed seeds and include:

### Behaviour

- action distribution by resident/life stage/hour;
- repeated-action streaks;
- decision alternative diversity;
- critical-need duration;
- unexplained missed work, school, care, or appointments;
- invalid/blocked travel and venue attempts;
- goal progress, completion, and stall rate.

### Social

- interactions per resident;
- isolated residents;
- relationship concentration;
- reciprocity;
- tension/affinity distribution;
- conversation repetition;
- participant knowledge violations when detectable.

### Economy

- total debit/credit reconciliation;
- cash/debt/investment changes;
- household disposable income;
- business revenue/profit/closure;
- inventory stockout duration;
- purchase affordability and shortfalls;
- shelter/housing costs and recovery.

### Care and health

- dependent coverage;
- caregiver overload/self-care interruption;
- untreated condition duration;
- treatment/recovery duration;
- care handoff failures;
- shelter duration and rehousing convergence.

### Narrative evidence

- percentage of public story claims with ledger references;
- decision explanations with factors and alternatives;
- chronicles with verified source IDs;
- model rejection/fallback rates;
- repeated or generic generated text indicators.

The 2.3 release records this baseline and obvious correctness failures. Broad tuning and new planning systems belong to 2.4.

---

## 11. Required repository deliverables

By release, the repository should contain or update:

```text
docs/
  KVSIM_2.3_IMPLEMENTATION_PLAN.md
  RELEASE_BASELINE_V22.md
  RELEASE_CHECKLIST.md
  OBSERVABILITY.md
  LIVE_STATE_CONTRACT.md
  BACKUP_AND_RESTORE.md
  ARCHITECTURE.md            # minimum current-state boundaries

scripts/
  verify-release.*
  check-version.*
  benchmark-live-state.*
  run-simulation-quality.*

.github/workflows/
  ci.yml
  nightly.yml
  release-candidate.yml

frontend/src/
  app/
  api/
  views/watch.*
  story/
  resident/
  game/                      # extracted only as required

src/krabville/
  api/                       # routers/read models as required
  operations/

src/krabville/migrations/
  014_*.sql                  # additive only, if runtime incidents/checksums require it
  015_*.sql                  # additive only, if generic causal links require it
```

Exact filenames may vary, but the responsibilities and tests may not be omitted.

---

## 12. Definition of done

A KVsim 2.3 task is complete only when all applicable conditions are true:

- The root cause is addressed with the smallest maintainable change.
- Deterministic authority is preserved.
- No client-side duplicate source of truth is introduced.
- Existing v3 routes and live databases remain compatible.
- A focused test demonstrates the new behaviour or fixed failure.
- Relevant full-suite, replay, invariant, migration, and browser checks pass.
- Desktop, mobile, touch, keyboard, and reduced-motion behaviour is covered for UI changes.
- New background/runtime behaviour has logs and metrics.
- Hot-path changes include measured before/after evidence.
- Schema changes are additive, documented, and upgrade-tested.
- Security and public-data boundaries remain intact.
- Documentation, acceptance criteria, and release notes are updated.
- Generated evidence is uploaded as CI artifacts rather than committed unless it is intended source data.
- The PR can be reverted without requiring unrelated code rollback.

---

## 13. Agent team structure

Use a small specialist team with one integrator.

| Role | Owns | Must not do |
|---|---|---|
| **Integrator** | Scope, contracts, merge order, release gate, cross-agent conflicts | Merge dependency-violating work or accept giant mixed PRs |
| **QA/Release agent** | CI, Playwright, fixtures, soak, performance artifacts, release workflows | Weaken assertions to make a branch green |
| **Backend/Ops agent** | API read models, health, migrations, incidents, backup/restore | Change simulation semantics during extraction |
| **Simulation contract agent** | Decision explanations, causal evidence, deterministic quality report | Add large new simulation systems in 2.3 |
| **Frontend/UX agent** | Watch, navigation, dossier, store, routes, accessibility | Recreate backend decision/world logic |
| **Game/Performance agent** | Phaser loading, manifests, atlases, map variants, rendering performance | Merge Phaser 4 or replace the visual engine during 2.3 |

Every PR receives independent review from the role closest to its failure mode.

---

## 14. Codex goal prompt

```text
Implement Krabville KVsim 2.3 using KVSIM_2.3_IMPLEMENTATION_PLAN.md as the
controlling roadmap.

Baseline: main at KVsim v2.2.1, commit
f630a9502b029097deeecbbc85b0f74aca4e99f9, database migration 013.

Work strictly in the ordered KV23 PR backlog. Begin with KV23-001 and continue
through the first incomplete dependency-ready item. Keep every PR small,
reversible, and limited to one feature or extraction. Keep main releasable after
every merge.

Preserve:
- deterministic simulation authority and seed replay;
- model-disabled operation and bounded schema-constrained inference;
- public read-only behaviour except the existing vote endpoint;
- live database compatibility and additive migrations;
- /api/v3 compatibility;
- current security, container, backup, TV-14, and asset-provenance boundaries;
- desktop, compact, mobile, touch, keyboard, and reduced-motion support.

Do not:
- add unrelated simulation breadth;
- increase population, season, model-call, or token limits;
- merge Phaser 4;
- rewrite the frontend framework;
- reset the live database;
- remove /api/v3/state in 2.3;
- recreate decision or coordinate authority in the client;
- weaken tests or hide failures.

For each task:
1. inspect the current implementation and acceptance criteria;
2. identify the smallest root-cause change and source-of-truth contract;
3. add the focused test first;
4. implement the bounded change;
5. run all affected unit, integration, migration, replay, browser,
   accessibility, security, and performance checks;
6. attach before/after evidence;
7. update documentation and the plan checklist;
8. obtain specialist review;
9. merge only when dependencies and Definition of Done are satisfied.

Use specialist sub-agents for QA/release, backend/operations, simulation
contracts, frontend/UX, and game/performance. The integrator owns contracts and
merge order. Continue until the KVsim 2.3 release gates are completely green
and a production-compatible v2.3.0 release with tested rollback is prepared.
```

---

## 15. Final release checklist

### Scope

- [ ] No non-goal entered the release.
- [ ] No Phaser 4 merge.
- [ ] No population, season, call, or token-limit increase.
- [ ] No live database reset or destructive migration.

### Release confidence

- [ ] Unified verification command passes.
- [ ] Required Playwright CI passes.
- [ ] Retained v2.2 migration fixture passes.
- [ ] Production-copy migration passes.
- [ ] Golden-seed replay passes.
- [ ] Full-season and multi-season soaks pass.
- [ ] Backup verification and disposable restore pass.

### Runtime

- [ ] Tick freshness and event sequence advance.
- [ ] Runtime incident injection/recovery test passes.
- [ ] Migration checksums are valid.
- [ ] One migration owner is enforced.
- [ ] Health and metrics expose the exact release/schema.

### Live state

- [ ] Bootstrap/world/stories contracts are documented and tested.
- [ ] One event registry is used.
- [ ] SSE gap recovery passes.
- [ ] Normal five-second `/state` polling is gone.
- [ ] Legacy `/api/v3/state` remains functional.

### Authority

- [ ] Shared world manifest replaces duplicate frontend coordinates.
- [ ] Resident decisions are server-authoritative in every view.
- [ ] Watch claims link to evidence.
- [ ] Predictions are visibly labelled.

### Performance

- [ ] Desktop and mobile transfer budgets pass.
- [ ] Interior, inventory, and event packs load lazily.
- [ ] Mobile map variant is used.
- [ ] Shell and map interaction budgets pass.
- [ ] Ten-minute memory test passes.
- [ ] Browser console/page errors are zero.

### UX and accessibility

- [ ] Watch is the default route.
- [ ] First-use acceptance script passes on desktop and mobile.
- [ ] Resident dossier has five grouped sections with no data loss.
- [ ] Deep links survive refresh/reconnect.
- [ ] Keyboard-only flow passes.
- [ ] Reduced-motion flow passes.
- [ ] No critical/serious axe violations.
- [ ] Loading, stale, reconnecting, paused, completed, degraded, empty, and error states are tested.

### Security and operations

- [ ] Vote security tests pass.
- [ ] Public outputs contain no operational secrets.
- [ ] Security headers pass.
- [ ] Dependency/image scans meet policy.
- [ ] SBOM is attached.
- [ ] Version, tag, image, commit, schema, and UI health agree.
- [ ] Pre-deployment backup is verified.
- [ ] Previous image and rollback instructions are retained.

### Production

- [ ] Live smoke passes.
- [ ] At least one settlement boundary passes after deployment.
- [ ] No repeated runtime incidents or unexplained 5xx responses.
- [ ] Release `v2.3.0` is published with exact commit and migration notes.


