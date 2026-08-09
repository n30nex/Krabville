export const PUBLIC_EVENT_VERSION = 1 as const;

export const PUBLIC_EVENT_KINDS = [
  "snapshot",
  "tick",
  "activity",
  "decision",
  "conversation",
  "communication",
  "relationship",
  "relationship_change",
  "town_event",
  "micro_event",
  "life_event",
  "economy",
  "purchase",
  "housing",
  "health",
  "care_handoff",
  "goal_change",
  "poll",
  "model_job",
  "budget",
  "chronicle",
  "verified_chronicle",
  "season",
  "runtime_incident",
] as const;

export type PublicEventKind = (typeof PUBLIC_EVENT_KINDS)[number];

export interface PublicEventEnvelope {
  eventVersion: typeof PUBLIC_EVENT_VERSION;
  seq: number;
  seasonId: number | null;
  tick: number;
  type: PublicEventKind;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface PublicStateEvent {
  eventVersion?: number;
  seq: number;
  seasonId?: number | null;
  tick: number;
  type: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

const PUBLIC_EVENT_KIND_SET = new Set<string>(PUBLIC_EVENT_KINDS);

export function isPublicEventKind(value: unknown): value is PublicEventKind {
  return typeof value === "string" && PUBLIC_EVENT_KIND_SET.has(value);
}

export function eventSubscriptionKinds(advertisedKinds: readonly string[] = []): string[] {
  return [...new Set<string>([...PUBLIC_EVENT_KINDS, ...advertisedKinds])];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isInteger(value: unknown, minimum: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum;
}

function isUtcTimestamp(value: unknown): value is string {
  return typeof value === "string"
    && /(?:Z|\+00:00)$/.test(value)
    && !Number.isNaN(Date.parse(value));
}

function ignore(reason: string): null {
  console.warn(`[Krabville events] Ignoring ${reason}.`);
  return null;
}

export function parsePublicEvent(
  data: string,
  transportType?: string,
  lastEventId = "",
): PublicEventEnvelope | null {
  let value: unknown;
  try {
    value = JSON.parse(data) as unknown;
  } catch {
    return ignore("invalid event JSON");
  }
  if (!isRecord(value)) return ignore("invalid event envelope");

  const declaredType = typeof value.type === "string" ? value.type : undefined;
  const type = declaredType ?? transportType;
  if (!isPublicEventKind(type)) return ignore(`unknown event type "${type ?? "<missing>"}"`);
  if (transportType && declaredType && transportType !== declaredType) {
    return ignore(`invalid ${type} event envelope`);
  }

  const eventVersion = value.eventVersion ?? PUBLIC_EVENT_VERSION;
  const legacySequence = /^\d+$/.test(lastEventId) ? Number(lastEventId) : Number.NaN;
  const seq = value.seq ?? legacySequence;
  const seasonId = value.seasonId ?? null;
  if (
    eventVersion !== PUBLIC_EVENT_VERSION
    || !isInteger(seq, 1)
    || (lastEventId !== "" && seq !== legacySequence)
    || (seasonId !== null && !isInteger(seasonId, 1))
    || !isInteger(value.tick, 0)
    || !isRecord(value.payload)
    || !isUtcTimestamp(value.createdAt)
  ) {
    return ignore(`invalid ${type} event envelope`);
  }

  return {
    eventVersion,
    seq,
    seasonId,
    tick: value.tick,
    type,
    payload: value.payload,
    createdAt: value.createdAt,
  };
}
