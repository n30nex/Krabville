export type Point = [number, number];

export interface Resident {
  slug: string;
  name: string;
  role: string;
  routine: string;
  about: string;
  home: string;
  workplace: string;
  color: string;
  traits: Record<string, number>;
  possessions: string[];
  x: number;
  y: number;
  destinationX: number;
  destinationY: number;
  path: Point[];
  location: string;
  activity: string;
  publicThought: string;
  intention: string;
  reflection: string;
  mood: string;
  needs: Record<string, number>;
  updatedTick: number;
}

export interface PollChoice {
  choiceId: string;
  title: string;
  category: string;
  preview: string;
  votes: number;
  winner: boolean;
}

export interface Poll {
  id: number;
  day: number;
  status: string;
  opensTick: number;
  closesTick: number;
  options: PollChoice[];
}

export interface KrabvilleState {
  schemaVersion: number;
  ok: boolean;
  season: null | {
    id: number;
    number: number;
    status: string;
    tick: number;
    targetTicks: number;
    day: number;
    worldMinutes: number;
    progressPercent: number;
    seedCommitment: string;
    revealedSeed: string | null;
    modelLocked: boolean;
    modelDegraded: boolean;
    weather: { condition?: string; temperatureC?: number; windKmh?: number };
    startedAt: string | null;
    completedAt: string | null;
    completionReason: string;
  };
  models: { primary: string; primaryReasoning: string; fallback: string; fallbackReasoning: string };
  currentEvent: null | {
    day: number;
    slug: string;
    title: string;
    category: string;
    summary: string;
    prop: string;
    strange: boolean;
    participants: string[];
  };
  residents: Resident[];
  poll: Poll | null;
  usage: {
    calls: number;
    callLimit: number;
    totalTokens: number;
    tokenGuard: number;
    inputTokens: number;
    cachedInputTokens: number;
    outputTokens: number;
    reasoningTokens: number;
    models: Record<string, { calls: number; tokens: number }>;
  };
  events: Array<{ seq: number; tick: number; type: string; payload: Record<string, unknown>; createdAt: string }>;
  conversations: Array<{
    tick: number;
    residentA: string;
    residentAName: string;
    residentB: string;
    residentBName: string;
    location: string;
    dialogue: Array<{ speaker: string; text: string }>;
    summary: string;
  }>;
  goals: Array<{
    resident: string;
    residentName: string;
    scope: string;
    description: string;
    status: string;
    progress: number;
  }>;
  props: Array<{ location: string; prop: string; status: string; createdTick: number }>;
  chronicles: Array<{ day: number; title: string; narrative: string }>;
  report: null | { headline: string; narrative: string; poster: string; statistics: Record<string, unknown> };
  updatedAt: string;
}

export interface ResidentDetail extends Resident {
  goals: KrabvilleState["goals"];
  memories: Array<{ kind: string; content: string; tags: string; valence: number; salience: number; created_tick: number }>;
  relationships: Array<{
    otherSlug: string;
    otherName: string;
    affinity: number;
    trust: number;
    tension: number;
    familiarity: number;
    interactions: number;
  }>;
}
