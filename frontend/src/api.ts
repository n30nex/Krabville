import type { KrabvilleState, ResidentDetail } from "./types";

async function json<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const fetchState = () => json<KrabvilleState>("/api/v3/state");

export const fetchResident = (slug: string) =>
  json<ResidentDetail>(`/api/v3/residents/${encodeURIComponent(slug)}`);

export const fetchSeasons = () =>
  json<{ seasons: Array<Record<string, unknown>> }>("/api/v3/seasons");

export const fetchSeason = (id: number) =>
  json<{ season: Record<string, unknown>; chronicles: Array<Record<string, unknown>>; report: null | Record<string, unknown> }>(
    `/api/v3/seasons/${id}`,
  );

function cookie(name: string): string {
  const prefix = `${name}=`;
  const value = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return decodeURIComponent(value?.slice(prefix.length) ?? "");
}

export const vote = (pollId: number, choiceId: string) =>
  json<{ ok: true }>(`/api/v3/polls/${pollId}/vote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choiceId, csrfToken: cookie("kv_csrf") }),
  });

export function connectEvents(onEvent: (type: string, payload: Record<string, unknown>) => void): EventSource {
  const source = new EventSource("/api/v3/events/stream");
  for (const type of [
    "snapshot",
    "tick",
    "activity",
    "decision",
    "conversation",
    "relationship",
    "town_event",
    "micro_event",
    "life_event",
    "economy",
    "poll",
    "model_job",
    "budget",
    "chronicle",
    "season",
  ]) {
    source.addEventListener(type, (event) => {
      try {
        const value = JSON.parse((event as MessageEvent).data) as { payload?: Record<string, unknown> };
        onEvent(type, value.payload ?? {});
      } catch {
        onEvent(type, {});
      }
    });
  }
  return source;
}
