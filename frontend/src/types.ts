export type Point = [number, number];

export interface DecisionCandidate {
  activity: string;
  destination: string;
  score?: number;
  confidence?: number | string;
  reason?: string;
  drivers?: string[];
  etaMinutes?: number;
}

export interface PublicNote {
  title?: string;
  text: string;
  status?: string;
  source?: string;
  confidence?: number;
  revealed?: boolean;
}

export interface LedgerEntry {
  id?: string | number;
  tick?: number;
  day?: number;
  time?: string;
  category?: string;
  title: string;
  summary?: string;
  participants?: string[];
  amount?: number;
}

export interface FamilyLink {
  slug?: string;
  name: string;
  relation: string;
  lifeStage?: string;
  household?: string;
}

export interface HouseholdSummary {
  id: string | number;
  name: string;
  home: string;
  memberSlugs?: string[];
  memberNames?: string[];
  cash?: number;
  netWorth?: number;
  status?: string;
}

export interface PropertySummary {
  id?: string | number;
  name: string;
  type?: string;
  owner?: string;
  occupants?: string[];
  value?: number;
  status?: string;
  x?: number;
  y?: number;
  interiorAvailable?: boolean;
}

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
  needsHighIsGood?: boolean;
  lifeStage?: string;
  ageLabel?: string;
  household?: string;
  householdId?: string | number;
  wants?: PublicNote[];
  aspirations?: PublicNote[];
  decisionCandidates?: DecisionCandidate[];
  pondering?: { active?: boolean; thought: string; urgentNeeds?: string[]; untilTick?: number };
  urgentNeeds?: string[];
  spriteVariant?: number;
  family?: FamilyLink[];
  secrets?: PublicNote[];
  beliefs?: PublicNote[];
  health?: {
    status?: string;
    conditions?: string[];
    care?: string[];
    caregiver?: string;
    stress?: number;
  };
  career?: {
    title?: string;
    employer?: string;
    status?: string;
    performance?: number;
    schedule?: string;
    income?: number;
  };
  finances?: {
    cash?: number;
    chequing?: number;
    savings?: number;
    investments?: number;
    debt?: number;
    netWorth?: number;
  };
  properties?: PropertySummary[];
  inventory?: string[];
  lifeLedger?: LedgerEntry[];
  updatedTick: number;
}

export interface PollChoice {
  choiceId: string;
  title: string;
  category: string;
  preview: string;
  votes: number;
  winner: boolean;
  impact?: string;
  consequence?: string;
}

export interface Poll {
  id: number;
  day: number;
  status: string;
  opensTick: number;
  closesTick: number;
  options: PollChoice[];
  question?: string;
  allowChange?: boolean;
  appliesOnDay?: number;
}

export interface KrabvilleState {
  schemaVersion: number;
  ok: boolean;
  world?: {
    width?: number;
    height?: number;
    coordinateSpace?: "legacy" | "map";
    mapAsset?: string;
    interiorsAsset?: string;
  };
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
  ledger?: LedgerEntry[];
  households?: HouseholdSummary[];
  economy?: {
    currency?: string;
    totalCash?: number;
    totalDebt?: number;
    totalInvestments?: number;
    medianNetWorth?: number;
    employed?: number;
    unemployed?: number;
    businesses?: Array<{ name: string; owner?: string; employees?: number; cash?: number; status?: string }>;
  };
  families?: Array<{ id?: string | number; name: string; members: FamilyLink[]; summary?: string }>;
  properties?: PropertySummary[];
  buildings?: PropertySummary[];
  townEvents?: LedgerEntry[];
  seasonSummaries?: Array<{ id: number; number: number; status: string; headline?: string; progressPercent?: number }>;
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
    attraction?: number;
    affection?: number;
    respect?: number;
    commitment?: number;
    resentment?: number;
    kinship?: string;
  }>;
}
