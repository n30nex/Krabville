# Public Event Contract

KV23-202 defines `krabville.public-event` version 1. The authoritative Python
contract is `src/krabville/public_events.py`; `frontend/src/events.ts` is the
TypeScript binding. Both bindings are pinned by the golden registry and event
fixtures in `tests/fixtures/contracts`.

## Envelope

| Field | Meaning |
|---|---|
| `eventVersion` | Envelope schema version. Version 1 is the only supported value. |
| `seq` | Positive, monotonically increasing event-stream sequence. SSE `id` must equal it. |
| `seasonId` | Positive authoritative season ID, or `null` for a legacy/global event. |
| `tick` | Non-negative authoritative simulation tick in that season. |
| `type` | Snake-case event kind from the public registry. SSE `event` keeps this value. |
| `payload` | Event-specific public data. It is always a JSON object. |
| `createdAt` | UTC ISO-8601 timestamp recorded with the event. |

The envelope is additive to the existing transport. Existing `seq`, `tick`,
`type`, `payload`, and `createdAt` fields retain their meanings. Existing SSE
event names remain named events. The frontend also accepts the legacy SSE data
shape `{tick,payload,createdAt}` and derives `seq` from `Last-Event-ID`.

The registry includes every currently emitted public kind plus `snapshot`,
`relationship`, and `budget`, which remain accepted for existing SSE clients.
An advertised kind unknown to the compiled frontend is logged without its data
and ignored. Invalid versions, sequence IDs, timestamps, or payload containers
are also ignored rather than applied.

## Public Boundary

`/api/v3/state` remains available and backward compatible. This contract does
not add a public mutation; voting remains the only public write operation.
Sequence-gap recovery and a normalized client store belong to KV23-204/205.

## API Wiring

Recent state events, paginated `/api/v2|v3/events` responses, and SSE data all
use the same serializer. Existing response keys remain intact;
`eventVersion` and `seasonId` are additive. SSE `id` remains equal to `seq`, and
the existing named `event: <type>` transport is unchanged.

No route, vote handler, polling behavior, migration, or deployment ownership
changes are part of this package.
