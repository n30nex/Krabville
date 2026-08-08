import type { KrabvilleState, PropertyDetail, ResidentDetail } from "./types";

async function json<T>(path: string, options?: RequestInit): Promise<T> {
  const retryable = !options?.method || options.method === "GET";
  for (let attempt = 0; attempt < (retryable ? 3 : 1); attempt += 1) {
    const response = await fetch(path, { credentials: "same-origin", ...options });
    if (response.ok) return response.json() as Promise<T>;
    if (![502, 503, 504].includes(response.status) || attempt === 2) {
      throw new Error(response.status >= 500 ? "The town ledger is briefly unavailable." : `${response.status} ${response.statusText}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 250 * 2 ** attempt));
  }
  throw new Error("The town ledger is briefly unavailable.");
}

export const fetchState = () => json<KrabvilleState>("/api/v3/state");

export const fetchResident = (slug: string) =>
  json<ResidentDetail>(`/api/v3/residents/${encodeURIComponent(slug)}`);

export const fetchProperty = (slug: string) =>
  json<PropertyDetail>(`/api/v3/properties/${encodeURIComponent(slug)}`);

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
