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
  slug?: string;
  name: string;
  type?: string;
  address?: string;
  mapLocation?: string;
  owner?: string;
  occupants?: Array<{ slug: string; name: string; lifeStage?: string }>;
  inside?: Array<{ slug: string; name: string; activity: string }>;
  value?: number;
  status?: string;
  condition?: number;
  x?: number;
  y?: number;
  interiorAvailable?: boolean;
  interiorVariant?: number;
  business?: { id?: number; slug?: string; name?: string; status?: string } | null;
}

export interface InventoryItem {
  name: string;
  category: string;
  quantity: number;
  condition?: number;
  price?: number;
  lowStock?: boolean;
  assetKey?: string;
}

export interface AccountSummary {
  ownerKind: "resident" | "household" | "business";
  owner: string;
  residentSlug?: string | null;
  name: string;
  type: string;
  status: string;
  balance: number;
}

export interface CommunicationSummary {
  tick: number;
  direction: "incoming" | "outgoing";
  otherSlug: string;
  otherName: string;
  purpose: string;
  summary: string;
  visibility: "public" | "private";
  durationMinutes: number;
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
  indoors?: boolean;
  building?: string | null;
  care?: { state: string; caregiver?: string | null };
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
    accounts?: Array<{ name: string; type: string; status: string; balance: number }>;
    history?: Array<{ season: number; day: number; cash: number; debt: number; investments: number; netWorth: number }>;
  };
  phone?: { number: string; device: string; active: boolean } | null;
  communications?: CommunicationSummary[];
  properties?: PropertySummary[];
  inventory?: string[];
  onPersonInventory?: InventoryItem[];
  homeInventory?: InventoryItem[];
  transactions?: Array<{ id: number; tick: number; category: string; description: string; amount: number }>;
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
    businesses?: Array<{
      id?: number; slug?: string; name: string; industry?: string; owner?: string; employees?: number;
      cash?: number; status?: string; propertySlug?: string; location?: string; inventoryUnits?: number;
      lowStockItems?: number; sales?: number;
    }>;
    accounts?: AccountSummary[];
    transactions?: Array<{ id: number; tick: number; category: string; description: string; amount: number }>;
    history?: Array<{ season: number; day: number; cash: number; debt: number; investments: number; netWorth: number }>;
    catalogItems?: number;
    stockUnits?: number;
    barters?: number;
    phoneCalls?: number;
  };
  families?: Array<{ id?: string | number; name: string; members: FamilyLink[]; summary?: string }>;
  properties?: PropertySummary[];
  buildings?: PropertySummary[];
  communications?: Array<{
    tick: number;
    caller: string;
    callerName: string;
    recipient: string;
    recipientName: string;
    purpose: string;
    visibility: "public" | "private";
    durationMinutes: number;
    summary: string;
  }>;
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

export interface PropertyDetail {
  id: number;
  slug: string;
  name: string;
  type: string;
  address: string;
  mapLocation: string;
  status: string;
  condition: number;
  value: number;
  interiorVariant: number;
  residents: Array<{ slug: string; name: string; activity: string; mood: string }>;
  households: Array<{ id: number; name: string }>;
  business: null | Record<string, unknown>;
  inventory: InventoryItem[];
  transactions: Array<{ id: number; tick: number; category: string; description: string; amount: number }>;
}
