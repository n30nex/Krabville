export type Point = [number, number];

export interface DecisionFactor {
  kind: string;
  key: string;
  weight: number;
  explanation: string;
}

export interface DecisionCandidate {
  activity: string;
  destination: string;
  score?: number;
  confidence?: number | string;
  reason?: string;
  drivers?: string[];
  factors?: DecisionFactor[];
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
  participantDetails?: Array<{ slug: string; name: string; role: string }>;
  amount?: number;
  phase?: string;
  epilogue?: boolean;
  verificationStatus?: "verified" | "unverified" | "legacy" | string;
  verified?: boolean | null;
}

export interface GoalEvidence {
  id?: number | string | null;
  goalId?: number | string | null;
  goalScope?: "season" | "life" | string;
  tick: number;
  kind: string;
  summary: string;
  progressDelta: number;
  ledgerId?: number | string | null;
  verified: boolean;
}

export interface CareSchedule {
  arrangementId: number;
  resident: string;
  residentName: string;
  type: string;
  typeLabel?: string;
  status: string;
  statusLabel?: string;
  caregiver?: string | null;
  caregiverSlug?: string | null;
  day?: number | null;
  startMinute?: number | null;
  endMinute?: number | null;
  costPerDay: number;
  scheduleLabel?: string;
}

export interface HealthCondition {
  id: number;
  resident: string;
  residentName: string;
  key: string;
  name: string;
  type: string;
  typeLabel?: string;
  severity: number;
  severityLabel?: string;
  status: string;
  statusLabel?: string;
  contagious: boolean;
  contagionLabel?: string;
  provider?: string | null;
  treatmentCost: number;
}

export interface HousingRecoveryPlan {
  id?: number | string | null;
  householdId?: number | string | null;
  residentId?: number | string | null;
  status: string;
  statusLabel?: string;
  stage: string;
  stageLabel?: string;
  arrearsDays?: number;
  failedAttempts?: number;
  stableDays: number;
  stabilityLabel?: string;
  nextStep: string;
}

export interface ModelCircuit {
  jobKind: string;
  jobLabel?: string;
  model?: string | null;
  status: string;
  statusLabel?: string;
  consecutiveFailures: number;
  day?: number | null;
  openedDay?: number | null;
  openedAt?: string | null;
  probeDay?: number | null;
  fallbackModel?: string | null;
  updatedAt?: string | null;
}

export interface LifeGoal {
  id: number;
  resident: string;
  residentName: string;
  scope: "life";
  category: string;
  description: string;
  status: string;
  progress: number;
  createdSeasonId?: number | null;
  createdTick?: number;
  completedSeasonId?: number | null;
  completedTick?: number | null;
  evidence: GoalEvidence[];
  evidenceCount: number;
}

export interface EconomyIndicators {
  residentMedianWealth: number;
  disposableIncome: number;
  cpi?: number | null;
  retailVolume: number;
  businessRevenue: number;
  businessProfit: number;
  employmentRate: number;
  debtDelinquencyRate: number;
  delinquentDebts: number;
  wealthGini: number;
  shelterOccupancy: number;
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
  capacity?: number;
  householdCount?: number;
  business?: { id?: number; slug?: string; name?: string; status?: string } | null;
  inventoryItems?: number;
  inventoryUnits?: number;
}

export interface InventoryItem {
  name: string;
  category: string;
  quantity: number;
  condition?: number;
  price?: number;
  lowStock?: boolean;
  assetKey?: string;
  assetIndex?: number;
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
  decisionFactors?: DecisionFactor[];
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
    careStatus?: string;
    conditions?: string[];
    care?: string[];
    caregiver?: string;
    stress?: number;
    conditionDetails?: HealthCondition[];
    careSchedules?: CareSchedule[];
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
  clothing?: InventoryItem[];
  onPersonInventory?: InventoryItem[];
  homeInventory?: InventoryItem[];
  transactions?: Array<{ id: number; tick: number; category: string; description: string; amount: number }>;
  lifeLedger?: LedgerEntry[];
  goalEvidence?: GoalEvidence[];
  housingRecovery?: {
    available: boolean;
    trackingLabel?: string;
    inShelter: boolean;
    shelter?: string | null;
    stateLabel?: string;
    recoveryLabel?: string;
    plans: HousingRecoveryPlan[];
  };
  lifeGoals?: LifeGoal[];
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
  totalVotes?: number;
  selectionSource?: "visitors" | "town" | null;
  winnerLabel?: string | null;
}

export interface KrabvilleState {
  schemaVersion: number;
  ok: boolean;
  world?: {
    width?: number;
    height?: number;
    coordinateSpace?: "legacy" | "map";
    mapAsset?: string;
    mapAssets?: Record<"spring" | "summer" | "fall" | "winter", string>;
    interiorsAsset?: string;
    weatherAsset?: string;
    inventoryAsset?: string;
    eventAsset?: string;
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
    weather: { condition?: string; temperatureC?: number; windKmh?: number; season?: string };
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
  eventKinds?: string[];
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
    id?: number;
    resident: string;
    residentName: string;
    scope: string;
    description: string;
    status: string;
    progress: number;
    evidence?: GoalEvidence[];
    evidenceCount?: number;
  }>;
  lifeGoals?: LifeGoal[];
  props: Array<{ location: string; prop: string; status: string; createdTick: number }>;
  chronicles: Array<{ day: number; title: string; narrative: string; source?: string; ledgerIds?: number[]; verificationStatus?: string; verified?: boolean | null }>;
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
      inventoryItems?: number; lowStockItems?: number; sales?: number;
    }>;
    accounts?: AccountSummary[];
    transactions?: Array<{ id: number; tick: number; category: string; description: string; amount: number }>;
    history?: Array<{ season: number; day: number; cash: number; debt: number; investments: number; netWorth: number }>;
    catalogItems?: number;
    stockUnits?: number;
    barters?: number;
    phoneCalls?: number;
    transactionCount?: number;
    transactionVolume?: number;
    businessRevenue?: number;
    serviceRevenue?: number;
    goodsSold?: number;
    indicators?: EconomyIndicators;
    metricHistory?: Array<{
      day: number;
      residentMedianWealth?: number | null;
      disposableIncome: number;
      cpi?: number | null;
      retailVolume: number;
      businessRevenue: number;
      businessProfit: number;
    }>;
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
  analytics?: {
    relationships?: { pairs: number; interactions: number; affinity: number; trust: number; tension: number; familiarity: number };
    strongestConnections?: Array<{ residentA: string; residentB: string; affinity: number; trust: number; tension: number; interactions: number }>;
    inventoryByCategory?: Array<{ category: string; units: number; items: number }>;
    movements?: Array<{ type: string; units: number; events: number }>;
    prices?: Array<{ day: number; averagePrice: number; unitsSold: number }>;
    population?: {
      living: number; target: number; stages: Record<string, number>; births: number;
      arrivals: number; deaths: number; activeHouseholds: number;
    };
    housing?: {
      residents: number; capacity: number; available: number; properties: number;
      activeLeases: number; apartments: number; apartmentResidents: number;
      apartmentCapacity: number; sharedBuildings: number;
    };
    economy?: EconomyIndicators;
    care?: { scheduledBlocks: number; dependents: number };
    health?: { activeConditions: number; recovering: number; contagious: number };
  };
  townEvents?: LedgerEntry[];
  ledgerVerification?: { available: boolean; verified: number; unverified: number; legacy: number; participantLinks: number };
  epilogues?: LedgerEntry[];
  goalEvidence?: GoalEvidence[];
  careSchedules?: CareSchedule[];
  healthConditions?: HealthCondition[];
  housingRecovery?: {
    available: boolean;
    trackingLabel?: string;
    shelterResidents: number;
    shelterHouseholds: number;
    residents: Array<{ slug: string; name: string; household: string; shelter: string }>;
    plans: HousingRecoveryPlan[];
  };
  modelCircuits?: { available: boolean; summaryLabel?: string; circuits: ModelCircuit[] };
  docket?: {
    source: string;
    entries: LedgerEntry[];
    activeGoals: KrabvilleState["goals"];
    lifeGoals?: LifeGoal[];
    epilogues: LedgerEntry[];
    verification?: KrabvilleState["ledgerVerification"];
  };
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
  capacity: number;
  householdCount: number;
  residents: Array<{ slug: string; name: string; activity: string; mood: string }>;
  households: Array<{ id: number; name: string }>;
  business: null | Record<string, unknown>;
  inventory: InventoryItem[];
  transactions: Array<{ id: number; tick: number; category: string; description: string; amount: number }>;
}
