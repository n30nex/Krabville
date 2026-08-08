import {
  Activity,
  Archive,
  BookOpen,
  Brain,
  ChevronRight,
  CloudSun,
  createIcons,
  LocateFixed,
  Map as MapIcon,
  MessageCircle,
  PackageOpen,
  PanelRightOpen,
  Radio,
  Users,
  Vote as VoteIcon,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide";

import { connectEvents, fetchResident, fetchSeason, fetchSeasons, fetchState, vote } from "./api";
import type { KrabvilleState, LedgerEntry, Point, PublicNote, Resident, ResidentDetail } from "./types";
import "./style.css";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("app root missing");

app.innerHTML = `
  <div class="shell">
    <header class="topbar">
      <button class="icon-button mobile-only" id="roster-toggle" aria-label="Open residents"><i data-lucide="users"></i></button>
      <div class="brand-mark" aria-hidden="true">K</div>
      <div class="brand-copy"><strong>Krabville</strong><span>Lagoon social simulation</span></div>
      <div class="season-clock" id="season-clock">Waiting for the town...</div>
      <div class="status-cluster">
        <div class="live-state" id="live-state"><span></span><b>Connecting</b></div>
        <div class="budget-mini" id="budget-mini"></div>
        <button class="command-button" id="archive-open"><i data-lucide="archive"></i><span>Seasons</span></button>
      </div>
    </header>
    <main class="workspace">
      <aside class="resident-rail" id="resident-rail" aria-label="Krabville residents">
        <div class="rail-heading"><span>Residents</span><b id="resident-count">0</b></div>
        <div class="resident-list" id="resident-list"></div>
      </aside>
      <section class="map-stage" id="map-stage" aria-label="Live map of Krabville">
        <div id="world"></div>
        <div class="map-tools" aria-label="Map controls">
          <button class="icon-button" id="zoom-in" aria-label="Zoom in"><i data-lucide="zoom-in"></i></button>
          <button class="icon-button" id="zoom-out" aria-label="Zoom out"><i data-lucide="zoom-out"></i></button>
          <button class="icon-button" id="map-fit" aria-label="Show the whole Lagoon"><i data-lucide="locate-fixed"></i></button>
        </div>
        <div class="weather-pill" id="weather-pill"><i data-lucide="cloud-sun"></i><span>Weather pending</span></div>
        <button class="story-toggle" id="story-toggle"><i data-lucide="panel-right-open"></i><span>Town</span></button>
        <aside class="resident-peek" id="resident-peek" role="tooltip" hidden></aside>
        <aside class="interior-view" id="interior-view" hidden aria-label="Building interior">
          <div class="interior-head"><div><span>Inside</span><b id="interior-name">Building</b></div><button class="icon-button" id="interior-close" aria-label="Close interior"><i data-lucide="x"></i></button></div>
          <div class="interior-art" id="interior-art" role="img"></div>
        </aside>
        <div class="live-ticker"><span class="ticker-signal"></span><b>LIVE</b><p id="live-ticker">Connecting to the town ledger...</p></div>
      </section>
      <aside class="story-rail" id="story-rail">
        <div class="story-tabs" role="tablist">
          <button class="active" data-story-tab="ledger"><i data-lucide="activity"></i><span>Ledger</span></button>
          <button data-story-tab="households"><span>Households</span></button>
          <button data-story-tab="economy"><span>Economy</span></button>
          <button data-story-tab="family"><span>Family</span></button>
          <button data-story-tab="property"><span>Property</span></button>
          <button data-story-tab="events"><span>Events</span></button>
          <button data-story-tab="vote"><i data-lucide="vote"></i><span>Vote</span></button>
          <button data-story-tab="seasons"><i data-lucide="archive"></i><span>Seasons</span></button>
        </div>
        <div class="story-content" id="story-content"></div>
      </aside>
    </main>
  </div>
  <section class="side-drawer" id="dossier" hidden aria-label="Resident dossier">
    <div class="drawer-head"><div><span>Resident dossier</span><h2 id="dossier-name">Resident</h2></div><button class="icon-button" id="dossier-close" aria-label="Close dossier"><i data-lucide="x"></i></button></div>
    <div class="drawer-body" id="dossier-body"></div>
  </section>
  <section class="archive-view" id="archive-view" hidden aria-label="Season archive">
    <div class="archive-head"><div><span>Permanent chronicle</span><h2>Season archive</h2></div><button class="icon-button" id="archive-close" aria-label="Close archive"><i data-lucide="x"></i></button></div>
    <div class="archive-layout"><nav id="archive-list"></nav><article id="archive-detail"></article></div>
  </section>
  <div class="screen-shade" id="screen-shade" hidden></div>
`;

createIcons({
  icons: {
    Activity,
    Archive,
    BookOpen,
    Brain,
    ChevronRight,
    CloudSun,
    LocateFixed,
    Map: MapIcon,
    MessageCircle,
    PackageOpen,
    PanelRightOpen,
    Radio,
    Users,
    Vote: VoteIcon,
    X,
    ZoomIn,
    ZoomOut,
  },
});

const byId = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) throw new Error(`missing #${id}`);
  return element as T;
};

const h = (value: unknown): string =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const formatTime = (minutes: number): string => {
  const hour = Math.floor(minutes / 60) % 24;
  const minute = minutes % 60;
  return `${hour.toString().padStart(2, "0")}:${minute.toString().padStart(2, "0")}`;
};

const clampNeed = (value: number): number => Math.max(0, Math.min(100, Number.isFinite(value) ? value : 50));

const NEED_ORDER = [
  "energy", "hunger", "hygiene", "health", "comfort", "safety", "fun", "social", "belonging", "privacy", "purpose", "autonomy", "financialSecurity", "financial_security",
];
const LEGACY_PRESSURE_NEEDS = new Set(["hunger", "social"]);

const titleCase = (value: string): string => value.replaceAll("_", " ").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/\b\w/g, (letter) => letter.toUpperCase());

function needSatisfaction(resident: Pick<Resident, "needs" | "needsHighIsGood">, key: string): number {
  const raw = clampNeed(Number(resident.needs[key] ?? 50));
  const modernNeeds = Object.keys(resident.needs).some((name) => !["energy", "hunger", "social", "purpose", "comfort"].includes(name));
  return resident.needsHighIsGood || modernNeeds || !LEGACY_PRESSURE_NEEDS.has(key) ? raw : 100 - raw;
}

function displayedNeeds(resident: Pick<Resident, "needs" | "needsHighIsGood">): Array<[string, number, string]> {
  const keys = [...NEED_ORDER.filter((key) => key in resident.needs), ...Object.keys(resident.needs).filter((key) => !NEED_ORDER.includes(key))];
  return [...new Set(keys)].map((key) => [titleCase(key), needSatisfaction(resident, key), key]);
}

interface ResidentForecast {
  destination: string;
  activity: string;
  confidence: string;
  reason: string;
  score: number;
  etaMinutes?: number;
}

function confidenceLabel(score: number, nextScore: number): string {
  const margin = score - nextScore;
  return margin >= 35 ? "Strong signal" : margin >= 15 ? "Likely" : "Possible";
}

function forecastResidents(resident: Resident, value: KrabvilleState): ResidentForecast[] {
  if (resident.decisionCandidates?.length) {
    return resident.decisionCandidates.slice(0, 3).map((candidate, index, candidates) => {
      const score = clampNeed(Number(candidate.score ?? (100 - index * 18)));
      const confidence = typeof candidate.confidence === "string"
        ? candidate.confidence
        : candidate.confidence !== undefined
          ? `${Math.round(Number(candidate.confidence) * (Number(candidate.confidence) <= 1 ? 100 : 1))}%`
          : confidenceLabel(score, Number(candidates[index + 1]?.score ?? 0));
      return {
        destination: candidate.destination,
        activity: candidate.activity,
        confidence,
        reason: candidate.reason || candidate.drivers?.join(", ") || "Their current needs and plans support this choice.",
        score,
        etaMinutes: candidate.etaMinutes,
      };
    });
  }
  const distance = Math.hypot(resident.destinationX - resident.x, resident.destinationY - resident.y);
  const committed = resident.path.length > 0 || distance > 6 ? {
      destination: resident.location,
      activity: resident.activity,
      confidence: "En route",
      reason: "Their current path already points there.",
      score: 100,
    } satisfies ResidentForecast : null;

  const energy = needSatisfaction(resident, "energy");
  const hunger = needSatisfaction(resident, "hunger");
  const social = needSatisfaction(resident, "social");
  const purpose = needSatisfaction(resident, "purpose");
  const comfort = needSatisfaction(resident, "comfort");
  const openness = Number(resident.traits.openness ?? 50);
  const sociability = Number(resident.traits.sociability ?? 50);
  const conscientiousness = Number(resident.traits.conscientiousness ?? 50);
  const hour = (value.season?.worldMinutes ?? 720) / 60;
  const mealWindow = (hour >= 6.5 && hour < 8) || (hour >= 12 && hour < 13.5) || (hour >= 18 && hour < 19.5);
  const workWindow = (hour >= 8.5 && hour < 12) || (hour >= 13 && hour < 17.5);
  const sleepWindow = hour >= 22 || hour < 6;
  const evening = hour >= 17 && hour < 22;
  const harshWeather = ["rain", "storm", "fog", "first-snow"].includes(value.season?.weather.condition ?? "");
  const options = [
    { score: (100 - energy) * 1.25 + (sleepWindow ? 95 : 0), activity: "sleeping", destination: resident.home, reason: "Low energy and the hour point home." },
    { score: (100 - hunger) * 1.35 + (mealWindow ? 52 : 0) + (100 - social) * 0.12, activity: "sharing a meal", destination: social < 52 ? "Hobbs Cafe" : resident.home, reason: "Hunger and meal timing point toward food." },
    { score: (100 - purpose) * 0.8 + (workWindow ? 74 : 0) + conscientiousness * 0.2, activity: `working as ${resident.role}`, destination: resident.workplace, reason: "Work hours and purpose point to their workplace." },
    { score: (100 - social) * 0.9 + (evening ? 35 : 0) + sociability * 0.25, activity: "spending time with neighbours", destination: "Town Square", reason: "Low social connection and the hour point to the square." },
    { score: (100 - comfort) * 0.92 + (harshWeather ? 44 : 0), activity: "settling somewhere comfortable", destination: resident.home, reason: "Comfort and the weather point toward home." },
    { score: (100 - purpose) * 0.75 + openness * 0.24, activity: "making progress on a personal project", destination: resident.workplace, reason: "Purpose and curiosity point to project time." },
    { score: 28 + openness * 0.24 + (hour >= 7 && hour < 21 ? 18 : -20) - (harshWeather ? 30 : 0), activity: "taking an unhurried walk around the Lagoon", destination: "Town Square", reason: "Their needs are steady enough for a Lagoon walk." },
  ];
  if (value.currentEvent?.participants.includes(resident.slug)) {
    options.push({
      score: 72 + (hour >= 14 && hour < 18 ? 38 : 0) + Number(resident.traits.agreeableness ?? 50) * 0.2,
      activity: `responding to ${value.currentEvent.title.toLowerCase()}`,
      destination: "Town Square",
      reason: "They are involved in today's catalyst.",
    });
  }
  options.sort((left, right) => right.score - left.score);
  const ranked = options.filter((option, index, all) => all.findIndex((item) => item.activity === option.activity && item.destination === option.destination) === index).slice(0, committed ? 2 : 3);
  const forecasts = ranked.map((option, index) => ({
    destination: option.destination,
    activity: option.activity,
    confidence: confidenceLabel(option.score, ranked[index + 1]?.score ?? 0),
    reason: `${value.season?.status === "running" ? "" : "When time resumes, "}${option.reason.charAt(0).toLowerCase()}${option.reason.slice(1)}`,
    score: clampNeed(option.score),
  }));
  return committed ? [committed, ...forecasts].slice(0, 3) : forecasts;
}

const shortModel = (model: string): string =>
  model.replace("gpt-", "GPT ").replace("-codex", " Codex").replaceAll("-", " ");

let state: KrabvilleState | null = null;
let selectedSlug: string | null = null;
let storyTab = "ledger";
let storyMarkup = "";
let storyMarkupTab = "";
let lastFreshAt = 0;
let refreshPending: Promise<void> | null = null;

let world: import("./game").LagoonWorld | null = null;
let worldLoading: Promise<import("./game").LagoonWorld> | null = null;

async function ensureWorld(): Promise<import("./game").LagoonWorld> {
  if (world) return world;
  if (!worldLoading) {
    worldLoading = import("./game").then(({ LagoonWorld }) => {
      world = new LagoonWorld("world", (slug) => void openResident(slug), showResidentPeek, showInterior);
      if (state) world.update(state);
      return world;
    });
  }
  return worldLoading;
}

function renderTop(value: KrabvilleState): void {
  const season = value.season;
  byId("season-clock").textContent = season
    ? `Season ${season.number}  |  Day ${season.day + 1}  |  ${formatTime(season.worldMinutes)}`
    : "No season running";
  const live = byId("live-state");
  const status = season?.status ?? "ready";
  live.className = `live-state ${status} ${season?.modelDegraded ? "degraded" : ""}`;
  live.querySelector("b")!.textContent = season?.modelDegraded ? "Model degraded" : status;
  const usage = value.usage;
  const callPercent = Math.min(100, (100 * usage.calls) / Math.max(1, usage.callLimit));
  byId("budget-mini").innerHTML = `
    <div><span>LLM allowance</span><b>${usage.calls} / ${usage.callLimit} calls</b></div>
    <div class="meter"><i style="width:${callPercent}%"></i></div>
  `;
  const weather = season?.weather;
  byId("weather-pill").querySelector("span")!.textContent = weather
    ? `${weather.condition ?? "clear"}  ${weather.temperatureC ?? "--"} C  ${weather.windKmh ?? "--"} km/h`
    : "Weather pending";
}

function renderRoster(value: KrabvilleState): void {
  byId("resident-count").textContent = String(value.residents.length);
  const list = byId("resident-list");
  list.innerHTML = value.residents
    .map(
      (resident) => `
      <button class="resident-row ${selectedSlug === resident.slug ? "selected" : ""}" data-resident="${h(resident.slug)}">
        <span class="resident-dot" style="--resident-color:${h(resident.color)}"></span>
        <span><b>${h(resident.name)}</b><small>${h(resident.activity)}</small></span>
        <i class="activity-beat" aria-hidden="true"></i>
      </button>`,
    )
    .join("");
  for (const button of list.querySelectorAll<HTMLButtonElement>("[data-resident]")) {
    const resident = value.residents.find((item) => item.slug === button.dataset.resident);
    button.addEventListener("click", () => {
      hideResidentPeek();
      void openResident(button.dataset.resident ?? "");
    });
    if (!resident) continue;
    button.addEventListener("mouseenter", (event) => {
      const stage = byId("map-stage").getBoundingClientRect();
      showResidentPeek(resident, 0, event.clientY - stage.top);
    });
    button.addEventListener("mouseleave", hideResidentPeek);
    button.addEventListener("focus", () => showResidentPeek(resident, 0, button.offsetTop + button.offsetHeight / 2));
    button.addEventListener("blur", hideResidentPeek);
  }
}

function needTone(value: number): string {
  return value < 30 ? "critical" : value < 58 ? "warning" : "good";
}

function compactNeedBar(label: string, value: number): string {
  return `<div class="peek-need"><span>${h(label)}</span><div><i class="${needTone(value)}" style="width:${value}%"></i></div><b>${Math.round(value)}</b></div>`;
}

function showResidentPeek(resident: Resident | null, x = 0, y = 0): void {
  if (!resident || !state) {
    hideResidentPeek();
    return;
  }
  const peek = byId<HTMLElement>("resident-peek");
  const forecast = forecastResidents(resident, state)[0];
  const updateKey = `${resident.slug}:${resident.updatedTick}:${state.season?.worldMinutes ?? 0}`;
  if (peek.dataset.updateKey !== updateKey) {
    peek.innerHTML = `
      <div class="peek-head"><span style="--resident-color:${h(resident.color)}"></span><div><b>${h(resident.name)}</b><small>${h(resident.activity)}</small></div><em>${h(resident.mood)}</em></div>
      <div class="peek-needs">${displayedNeeds(resident).sort((left, right) => left[1] - right[1]).slice(0, 6).map(([label, need]) => compactNeedBar(label, need)).join("")}</div>
      ${forecast ? `<div class="peek-forecast"><span>Pondering | ${h(forecast.confidence)}</span><b>${h(resident.pondering?.thought || resident.publicThought || `Maybe ${forecast.activity} next.`)}</b><small>${h(forecast.destination)} | ${h(forecast.reason)}</small></div>` : ""}`;
    peek.dataset.updateKey = updateKey;
  }
  peek.hidden = false;
  peek.dataset.x = String(x);
  peek.dataset.y = String(y);
  requestAnimationFrame(() => {
    const stage = byId("map-stage");
    const left = Math.max(8, Math.min(stage.clientWidth - peek.offsetWidth - 8, x + 18));
    const top = Math.max(8, Math.min(stage.clientHeight - peek.offsetHeight - 8, y - peek.offsetHeight / 2));
    peek.style.left = `${left}px`;
    peek.style.top = `${top}px`;
  });
}

function hideResidentPeek(): void {
  byId<HTMLElement>("resident-peek").hidden = true;
}

function interiorFrame(location: string): number {
  const name = location.toLowerCase();
  if (/clinic|hospital|health/.test(name)) return 7;
  if (/school|college|library/.test(name)) return 4;
  if (/daycare|nursery|child/.test(name)) return 5;
  if (/bank|town hall|office/.test(name)) return 6;
  if (/cafe|restaurant/.test(name)) return 8;
  if (/workshop|boatworks|repair|radio/.test(name)) return 10;
  if (/market|shop|store/.test(name)) return 11;
  if (/bed|apartment/.test(name)) return 2;
  return /house|home/.test(name) ? 0 : 9;
}

function showInterior(location: string): void {
  const frame = interiorFrame(location);
  const column = frame % 4;
  const row = Math.floor(frame / 4);
  const art = byId<HTMLElement>("interior-art");
  art.style.setProperty("--interior-x", `${column * 100 / 3}%`);
  art.style.setProperty("--interior-y", `${row * 50}%`);
  art.setAttribute("aria-label", `${location} interior cutaway`);
  byId("interior-name").textContent = location;
  byId<HTMLElement>("interior-view").hidden = false;
}

function hideInterior(): void {
  byId<HTMLElement>("interior-view").hidden = true;
}

function eventCard(value: KrabvilleState): string {
  const event = value.currentEvent;
  if (!event) return `<div class="empty-state">The town is waiting for its next catalyst.</div>`;
  return `
    <section class="event-band ${event.strange ? "strange" : ""}">
      <span>${h(event.category)} catalyst</span>
      <h3>${h(event.title)}</h3>
      <p>${h(event.summary)}</p>
      <div class="participant-line">${event.participants.map((slug) => `<button data-resident="${h(slug)}">${h(value.residents.find((resident) => resident.slug === slug)?.name ?? slug)}</button>`).join("")}</div>
    </section>`;
}

function renderLiveStory(value: KrabvilleState): string {
  const conversations = value.conversations.slice(-4).reverse();
  return `${eventCard(value)}
    <div class="section-label"><span>Recent conversations</span><b>${value.conversations.length}</b></div>
    <div class="conversation-list">
      ${conversations.length ? conversations.map((conversation) => `
        <button class="conversation-row" data-resident="${h(conversation.residentA)}">
          <span>${h(conversation.residentAName)} + ${h(conversation.residentBName)}</span>
          <p>${h(conversation.summary)}</p>
          <small>${h(conversation.location)}</small>
        </button>`).join("") : `<div class="empty-state">Conversations will appear as residents meet.</div>`}
    </div>
    <div class="usage-band">
      <div><span>Tokens</span><b>${value.usage.totalTokens.toLocaleString()}</b><small>of ${value.usage.tokenGuard.toLocaleString()} guard</small></div>
      <div><span>Primary</span><b>${h(shortModel(value.models.primary))}</b><small>${h(value.models.primaryReasoning)} reasoning</small></div>
      <div><span>Fallback</span><b>${h(shortModel(value.models.fallback))}</b><small>${h(value.models.fallbackReasoning)} reasoning</small></div>
    </div>`;
}

function renderPoll(value: KrabvilleState): string {
  const poll = value.poll;
  if (!poll) return `<div class="empty-state large">Today\'s visitor poll opens at 02:00 in-world.</div>`;
  const total = poll.options.reduce((sum, option) => sum + option.votes, 0);
  return `
    <section class="poll-band">
      <span>Day ${poll.day + 1} visitor decision</span>
      <h3>${h(poll.question ?? (poll.status === "open" ? "Choose tomorrow's catalyst" : "Voting has closed"))}</h3>
      <p>Shape the environment, community, economy, relationships, or a wildcard surprise. ${poll.allowChange === false ? "Votes are final." : "You may change your vote before closing."}</p>
    </section>
    <div class="vote-categories">${[...new Set(poll.options.map((option) => option.category))].map((category) => `<span>${h(category)}</span>`).join("")}</div>
    <div class="poll-options">
      ${poll.options.map((option) => {
        const percent = total ? Math.round((100 * option.votes) / total) : 0;
        return `<button class="poll-choice ${option.winner ? "winner" : ""}" data-choice="${h(option.choiceId)}" ${poll.status !== "open" ? "disabled" : ""}>
          <span><b>${h(option.choiceId)}</b><em>${h(option.category)}</em></span>
          <h4>${h(option.title)}</h4><p>${h(option.preview)}</p>${option.impact || option.consequence ? `<em class="choice-impact">${h(option.impact ?? option.consequence)}</em>` : ""}
          <div class="choice-meter"><i style="width:${percent}%"></i></div><small>${option.votes} vote${option.votes === 1 ? "" : "s"}  |  ${percent}%</small>
        </button>`;
      }).join("")}
    </div>`;
}

function renderDocket(value: KrabvilleState): string {
  const activeGoals = value.goals.filter((goal) => goal.status === "active").slice(0, 12);
  return `
    <div class="section-label"><span>Story docket</span><b>${activeGoals.length}</b></div>
    <div class="docket-list">${activeGoals.map((goal) => `
      <button data-resident="${h(goal.resident)}"><span>${h(goal.residentName)}</span><p>${h(goal.description)}</p><div class="goal-meter"><i style="width:${Math.max(3, goal.progress)}%"></i></div></button>
    `).join("")}</div>
    <div class="section-label"><span>Daily chronicle</span><b>${value.chronicles.length} / 7</b></div>
    <div class="chronicle-list">${value.chronicles.slice().reverse().map((entry) => `
      <article><span>Day ${entry.day + 1}</span><h4>${h(entry.title)}</h4><p>${h(entry.narrative)}</p></article>
    `).join("") || `<div class="empty-state">The first chronicle is written at nightfall.</div>`}</div>`;
}

const formatCad = (value: number | undefined): string => value === undefined ? "Not published" : new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(value);

function renderLedgerEntries(entries: LedgerEntry[], empty: string): string {
  if (!entries.length) return `<div class="empty-state">${h(empty)}</div>`;
  return `<div class="town-card-list">${entries.slice(-16).reverse().map((entry) => `
    <article><span>${h(entry.category ?? (entry.day !== undefined ? `Day ${entry.day + 1}` : "Town record"))}</span><h4>${h(entry.title)}</h4>${entry.summary ? `<p>${h(entry.summary)}</p>` : ""}${entry.amount !== undefined ? `<b>${formatCad(entry.amount)}</b>` : ""}</article>
  `).join("")}</div>`;
}

function derivedHouseholds(value: KrabvilleState): NonNullable<KrabvilleState["households"]> {
  if (value.households?.length) return value.households;
  const homes = new Map<string, string[]>();
  for (const resident of value.residents) homes.set(resident.home, [...(homes.get(resident.home) ?? []), resident.name]);
  return [...homes].map(([home, memberNames], index) => ({ id: `v2-${index}`, name: home.replace(/ house$/i, " household"), home, memberNames }));
}

function renderHouseholds(value: KrabvilleState): string {
  const households = derivedHouseholds(value);
  return `<div class="town-heading"><span>Households</span><b>${households.length}</b><p>Who shares a roof, and where daily life happens.</p></div><div class="town-card-list">${households.map((household) => {
    const members = household.memberNames ?? household.memberSlugs?.map((slug) => value.residents.find((resident) => resident.slug === slug)?.name ?? slug) ?? [];
    return `<article class="place-card"><span>${h(household.status ?? "Household")}</span><h4>${h(household.name)}</h4><p>${h(members.join(", ") || "No residents listed")}</p><small>${h(household.home)}</small><button data-place="${h(household.home)}">Focus home</button></article>`;
  }).join("")}</div>`;
}

function renderEconomy(value: KrabvilleState): string {
  const economy = value.economy;
  const employed = economy?.employed ?? value.residents.filter((resident) => resident.role && !/student|child|retired/i.test(resident.role)).length;
  return `<div class="town-heading"><span>Town economy</span><b>${h(economy?.currency ?? "CAD")}</b><p>Daily settlement, employment, debt, savings, and local enterprise.</p></div>
    <div class="metric-grid"><article><span>Employed</span><b>${employed}</b></article><article><span>Town cash</span><b>${formatCad(economy?.totalCash)}</b></article><article><span>Debt</span><b>${formatCad(economy?.totalDebt)}</b></article><article><span>Median worth</span><b>${formatCad(economy?.medianNetWorth)}</b></article></div>
    <div class="section-label"><span>Businesses</span><b>${economy?.businesses?.length ?? 0}</b></div>
    <div class="town-card-list">${economy?.businesses?.map((business) => `<article><span>${h(business.status ?? "Operating")}</span><h4>${h(business.name)}</h4><p>${h(business.owner ? `Owned by ${business.owner}` : "Ownership not published")} | ${business.employees ?? 0} staff</p><b>${formatCad(business.cash)}</b></article>`).join("") || `<div class="empty-state">Detailed accounts will appear when the KVsim v3 economy begins.</div>`}</div>`;
}

function renderFamilies(value: KrabvilleState): string {
  if (!value.families?.length) return `<div class="town-heading"><span>Family network</span><b>v3</b><p>Kinship, caregiving, and generations will appear as the new world forms.</p></div><div class="empty-state large">The current v2 ledger has no public family graph.</div>`;
  return `<div class="town-heading"><span>Family network</span><b>${value.families.length}</b><p>Families know only what their members have lived; spectators see the full lineage.</p></div><div class="town-card-list">${value.families.map((family) => `<article><span>Family</span><h4>${h(family.name)}</h4><p>${h(family.summary ?? family.members.map((member) => `${member.name} (${member.relation})`).join(", "))}</p></article>`).join("")}</div>`;
}

function renderProperty(value: KrabvilleState): string {
  const properties: NonNullable<KrabvilleState["properties"]> = value.properties?.length ? value.properties : value.buildings?.length ? value.buildings : derivedHouseholds(value).map((household) => ({ name: household.home, type: "Home", occupants: household.memberNames, interiorAvailable: true }));
  return `<div class="town-heading"><span>Property and places</span><b>${properties.length}</b><p>Select a building to bring its entrance and interior affordance into focus.</p></div><div class="town-card-list">${properties.map((property) => `<article class="place-card"><span>${h(property.type ?? "Place")}${property.interiorAvailable ? " | Interior" : ""}</span><h4>${h(property.name)}</h4><p>${h(property.occupants?.join(", ") || property.owner || property.status || "Town location")}</p>${property.value !== undefined ? `<b>${formatCad(property.value)}</b>` : ""}<button data-place="${h(property.name)}">Focus building</button></article>`).join("")}</div>`;
}

function renderEvents(value: KrabvilleState): string {
  const entries = value.townEvents ?? value.ledger ?? value.events.map((event) => ({ tick: event.tick, category: event.type, title: String(event.payload.title ?? event.payload.summary ?? event.type), summary: typeof event.payload.summary === "string" ? event.payload.summary : undefined }));
  return `${eventCard(value)}<div class="section-label"><span>Historical ledger</span><b>${entries.length}</b></div>${renderLedgerEntries(entries, "Major events will be preserved here as the season unfolds.")}`;
}

function renderSeasons(value: KrabvilleState): string {
  const seasons = value.seasonSummaries?.length ? value.seasonSummaries : value.season ? [{ id: value.season.id, number: value.season.number, status: value.season.status, progressPercent: value.season.progressPercent }] : [];
  return `<div class="town-heading"><span>Season archive</span><b>${seasons.length}</b><p>Permanent chronicles, reports, and illustrated week-ending posters.</p></div><div class="town-card-list">${seasons.map((season) => `<article><span>${h(season.status)}</span><h4>Season ${season.number}</h4><p>${h(season.headline ?? `${season.progressPercent ?? 0}% complete`)}</p></article>`).join("") || `<div class="empty-state">No season has been recorded yet.</div>`}</div><button class="archive-launch" data-open-archive>Open full season archive</button>`;
}

function renderLedger(value: KrabvilleState): string {
  return `${renderLiveStory(value)}${renderDocket(value)}`;
}

function renderStory(value: KrabvilleState): void {
  const content = byId("story-content");
  const views: Record<string, () => string> = {
    ledger: () => renderLedger(value),
    households: () => renderHouseholds(value),
    economy: () => renderEconomy(value),
    family: () => renderFamilies(value),
    property: () => renderProperty(value),
    events: () => renderEvents(value),
    vote: () => renderPoll(value),
    seasons: () => renderSeasons(value),
  };
  const nextMarkup = (views[storyTab] ?? views.ledger!)();
  if (storyMarkupTab === storyTab && storyMarkup === nextMarkup) return;
  storyMarkupTab = storyTab;
  storyMarkup = nextMarkup;
  content.innerHTML = nextMarkup;
}

function render(value: KrabvilleState): void {
  state = value;
  lastFreshAt = Date.now();
  renderTop(value);
  renderRoster(value);
  renderStory(value);
  if (world) world.update(value);
  else void ensureWorld();
  const lastEvent = value.events.at(-1);
  if (lastEvent) setTicker(lastEvent.type, lastEvent.payload);
}

function setTicker(type: string, payload: Record<string, unknown>): void {
  const summary = payload.summary ?? payload.title ?? payload.activity ?? payload.status ?? payload.kind;
  byId("live-ticker").textContent = summary ? `${type.replaceAll("_", " ")}: ${String(summary)}` : `${type.replaceAll("_", " ")} recorded in the town ledger.`;
}

async function refresh(): Promise<void> {
  if (refreshPending) return refreshPending;
  refreshPending = (async () => {
    try {
      render(await fetchState());
    } catch (error) {
      const live = byId("live-state");
      live.className = "live-state offline";
      live.querySelector("b")!.textContent = "Offline";
      byId("live-ticker").textContent = error instanceof Error ? `Public ledger unavailable: ${error.message}` : "Public ledger unavailable";
    } finally {
      refreshPending = null;
    }
  })();
  return refreshPending;
}

function needBar(label: string, value: number, key = label): string {
  return `<div class="need-row" data-need="${h(key)}" data-satisfaction="${Math.round(value)}"><span>${h(label)}</span><div><i class="${needTone(value)}" style="width:${value}%"></i></div><b>${Math.round(value)}</b></div>`;
}

function renderNotes(notes: PublicNote[] | undefined, empty: string): string {
  if (!notes?.length) return `<div class="empty-state">${h(empty)}</div>`;
  return `<div class="note-list">${notes.map((note) => `<article><span>${h(note.status ?? (note.revealed === false ? "Private" : "Known"))}</span><h4>${h(note.title ?? note.text)}</h4>${note.title ? `<p>${h(note.text)}</p>` : ""}${note.source ? `<small>Source: ${h(note.source)}</small>` : ""}</article>`).join("")}</div>`;
}

function renderDecisionForecasts(forecasts: ResidentForecast[]): string {
  return `<div class="decision-list">${forecasts.map((forecast, index) => `<article class="decision-row"><b>${index + 1}</b><div><span>${h(forecast.confidence)}${forecast.etaMinutes !== undefined ? ` | about ${forecast.etaMinutes} min` : ""}</span><h4>${h(forecast.activity)}</h4><p>${h(forecast.destination)} | ${h(forecast.reason)}</p></div><i style="--decision-score:${forecast.score}%"></i></article>`).join("")}</div>`;
}

function drawRelationshipGraph(canvas: HTMLCanvasElement, detail: ResidentDetail): void {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  if (!context) return;
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);
  const center: Point = [width / 2, height / 2];
  const relationships = detail.relationships.slice(0, 8);
  relationships.forEach((relationship, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(1, relationships.length) - Math.PI / 2;
    const radius = Math.min(width, height) * 0.36;
    const x = center[0] + Math.cos(angle) * radius;
    const y = center[1] + Math.sin(angle) * radius;
    const strength = Math.max(0, relationship.affinity + relationship.trust - relationship.tension) / 200;
    context.strokeStyle = `rgba(95, 213, 190, ${0.2 + strength * 0.75})`;
    context.lineWidth = 1 + strength * 4;
    context.beginPath();
    context.moveTo(center[0], center[1]);
    context.lineTo(x, y);
    context.stroke();
    context.fillStyle = "#16333b";
    context.beginPath();
    context.arc(x, y, 14, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "#dbeef1";
    context.font = "11px Inter, Segoe UI, sans-serif";
    context.textAlign = "center";
    context.fillText(relationship.otherName.split(" ")[0] ?? relationship.otherName, x, y + 27);
  });
  context.fillStyle = "#ffbf5a";
  context.beginPath();
  context.arc(center[0], center[1], 19, 0, Math.PI * 2);
  context.fill();
  context.fillStyle = "#071116";
  context.font = "700 12px Inter, Segoe UI, sans-serif";
  context.textAlign = "center";
  context.fillText(detail.name.split(" ")[0]?.slice(0, 1) ?? "K", center[0], center[1] + 4);
}

async function openResident(slug: string): Promise<void> {
  if (!slug) return;
  hideResidentPeek();
  selectedSlug = slug;
  world?.select(slug);
  if (state) renderRoster(state);
  const drawer = byId<HTMLElement>("dossier");
  drawer.hidden = false;
  byId("dossier-name").textContent = "Loading...";
  byId("dossier-body").innerHTML = `<div class="loading-state">Opening the resident ledger...</div>`;
  try {
    const detail = await fetchResident(slug);
    const forecasts = state ? forecastResidents(detail, state) : [];
    const wants = [...(detail.wants ?? []), ...(detail.aspirations ?? []), ...detail.goals.map((goal) => ({ title: goal.scope, text: goal.description, status: `${goal.status} | ${goal.progress}%` }))];
    const inventory = [...new Set([...(detail.inventory ?? []), ...detail.possessions])];
    const relationshipRows = detail.relationships.slice().sort((left, right) => (right.affinity + right.trust - right.tension) - (left.affinity + left.trust - left.tension));
    const finance = detail.finances;
    byId("dossier-name").textContent = detail.name;
    byId("dossier-body").innerHTML = `
      <section class="resident-summary"><span style="--resident-color:${h(detail.color)}"></span><div><b>${h(detail.role)}${detail.lifeStage ? ` | ${h(detail.lifeStage)}` : ""}</b><p>${h(detail.activity)} at ${h(detail.location)}</p></div><em>${h(detail.mood)}</em></section>
      <nav class="detail-tabs" aria-label="Dossier sections">
        <button class="active" data-detail-target="dossier-life">Life</button><button data-detail-target="dossier-needs">Needs & wants</button><button data-detail-target="dossier-family">Family</button><button data-detail-target="dossier-relationships">Relationships</button><button data-detail-target="dossier-secrets">Secrets & beliefs</button><button data-detail-target="dossier-health">Health & care</button><button data-detail-target="dossier-career">Career</button><button data-detail-target="dossier-finances">Finances</button><button data-detail-target="dossier-property">Property</button><button data-detail-target="dossier-memory">Memories</button><button data-detail-target="dossier-ledger">Life ledger</button>
      </nav>

      <section class="detail-section dossier-section" id="dossier-life">
        <div class="section-label"><span>Life</span><b>${h(detail.ageLabel ?? detail.lifeStage ?? "Resident")}</b></div>
        <div class="profile-band"><p>${h(detail.about)}</p><small>${h(detail.routine)}</small></div>
        <div class="thought-band"><span>In their head</span><p>${h(detail.pondering?.thought || detail.publicThought)}</p><small>${h(detail.intention)}</small></div>
        <div class="trait-grid">${Object.entries(detail.traits).map(([trait, score]) => `<div><span>${h(titleCase(trait))}</span><b>${Math.round(score)}</b></div>`).join("")}</div>
        <div class="section-label"><span>Likely decisions</span><b>Top ${forecasts.length}</b></div>${renderDecisionForecasts(forecasts)}
      </section>

      <section class="detail-section dossier-section" id="dossier-needs"><div class="section-label"><span>Needs, high is healthy</span><b>${h(detail.mood)}</b></div>${displayedNeeds(detail).map(([label, value, key]) => needBar(label, value, key)).join("")}<div class="section-label"><span>Wants and aspirations</span><b>${wants.length}</b></div>${renderNotes(wants, "No public wants have formed yet.")}</section>

      <section class="detail-section dossier-section" id="dossier-family"><div class="section-label"><span>Family and household</span><b>${detail.family?.length ?? 0}</b></div><div class="fact-grid"><article><span>Home</span><b>${h(detail.home)}</b></article><article><span>Household</span><b>${h(detail.household ?? "Not yet recorded")}</b></article></div>${detail.family?.length ? `<div class="note-list">${detail.family.map((member) => `<article><span>${h(member.relation)}</span><h4>${h(member.name)}</h4><p>${h([member.lifeStage, member.household].filter(Boolean).join(" | "))}</p></article>`).join("")}</div>` : `<div class="empty-state">Kinship and caregiving arrive with the KVsim v3 family ledger.</div>`}</section>

      <section class="detail-section dossier-section" id="dossier-relationships"><div class="section-label"><span>Relationship map</span><b>${detail.relationships.length}</b></div><canvas class="relationship-canvas" id="relationship-canvas"></canvas><div class="relationship-list">${relationshipRows.map((relationship) => `<article><b>${h(relationship.otherName)}</b><span>Affinity ${relationship.affinity} | Trust ${relationship.trust} | Tension ${relationship.tension}</span>${relationship.kinship ? `<small>${h(relationship.kinship)}</small>` : ""}</article>`).join("")}</div></section>

      <section class="detail-section dossier-section" id="dossier-secrets"><div class="section-label"><span>Secrets</span><b>${detail.secrets?.length ?? 0}</b></div>${renderNotes(detail.secrets, "No spectator-visible secrets yet.")}<div class="section-label"><span>Beliefs and gossip</span><b>${detail.beliefs?.length ?? 0}</b></div>${renderNotes(detail.beliefs, "No conflicting beliefs have formed yet.")}</section>

      <section class="detail-section dossier-section" id="dossier-health"><div class="section-label"><span>Health and care</span><b>${h(detail.health?.status ?? "No v3 record")}</b></div><div class="fact-grid"><article><span>Conditions</span><b>${h(detail.health?.conditions?.join(", ") || "None published")}</b></article><article><span>Caregiver</span><b>${h(detail.health?.caregiver ?? "Independent")}</b></article><article><span>Care plan</span><b>${h(detail.health?.care?.join(", ") || "None")}</b></article><article><span>Stress</span><b>${detail.health?.stress ?? "--"}</b></article></div></section>

      <section class="detail-section dossier-section" id="dossier-career"><div class="section-label"><span>Career</span><b>${h(detail.career?.status ?? "Current")}</b></div><div class="fact-grid"><article><span>Role</span><b>${h(detail.career?.title ?? detail.role)}</b></article><article><span>Employer</span><b>${h(detail.career?.employer ?? detail.workplace)}</b></article><article><span>Schedule</span><b>${h(detail.career?.schedule ?? detail.routine)}</b></article><article><span>Daily income</span><b>${formatCad(detail.career?.income)}</b></article></div></section>

      <section class="detail-section dossier-section" id="dossier-finances"><div class="section-label"><span>Finances and net worth</span><b>${formatCad(finance?.netWorth)}</b></div><div class="metric-grid"><article><span>Cash</span><b>${formatCad(finance?.cash)}</b></article><article><span>Chequing</span><b>${formatCad(finance?.chequing)}</b></article><article><span>Savings</span><b>${formatCad(finance?.savings)}</b></article><article><span>Investments</span><b>${formatCad(finance?.investments)}</b></article><article><span>Debt</span><b>${formatCad(finance?.debt)}</b></article><article><span>Net worth</span><b>${formatCad(finance?.netWorth)}</b></article></div>${finance ? "" : `<div class="empty-state">The v2 API does not publish private account balances. KVsim v3 will fill this ledger.</div>`}</section>

      <section class="detail-section dossier-section" id="dossier-property"><div class="section-label"><span>Property and inventory</span><b>${inventory.length}</b></div><div class="fact-grid"><article><span>Home</span><b>${h(detail.home)}</b></article><article><span>Workplace</span><b>${h(detail.workplace)}</b></article></div><div class="possession-list">${inventory.map((item) => `<span>${h(item)}</span>`).join("") || `<div class="empty-state">No inventory recorded.</div>`}</div>${detail.properties?.map((property) => `<article class="property-row"><span>${h(property.type ?? "Property")}</span><b>${h(property.name)}</b><small>${formatCad(property.value)}</small></article>`).join("") ?? ""}</section>

      <section class="detail-section dossier-section" id="dossier-memory"><div class="section-label"><span>Recent memories</span><b>${detail.memories.length}</b></div><div class="memory-list">${detail.memories.slice(0, 16).map((memory) => `<article><span>${h(memory.kind)} | salience ${memory.salience}</span><p>${h(memory.content)}</p></article>`).join("") || `<div class="empty-state">No retained memories yet.</div>`}</div></section>

      <section class="detail-section dossier-section" id="dossier-ledger"><div class="section-label"><span>Life ledger</span><b>${detail.lifeLedger?.length ?? 0}</b></div>${renderLedgerEntries(detail.lifeLedger ?? [], "Births, moves, relationships, careers, money, and other lasting changes will collect here.")}</section>
    `;
    for (const button of byId("dossier-body").querySelectorAll<HTMLButtonElement>("[data-detail-target]")) {
      button.addEventListener("click", () => {
        const target = document.getElementById(button.dataset.detailTarget ?? "");
        if (!target) return;
        byId("dossier-body").querySelectorAll("[data-detail-target]").forEach((item) => item.classList.toggle("active", item === button));
        target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      });
    }
    requestAnimationFrame(() => drawRelationshipGraph(byId<HTMLCanvasElement>("relationship-canvas"), detail));
  } catch (error) {
    byId("dossier-body").innerHTML = `<div class="empty-state large">${h(error instanceof Error ? error.message : "Dossier unavailable")}</div>`;
  }
}

function closeDossier(): void {
  byId("dossier").hidden = true;
  selectedSlug = null;
  world?.select(null);
  if (state) renderRoster(state);
}

async function openArchive(): Promise<void> {
  const view = byId<HTMLElement>("archive-view");
  view.hidden = false;
  const list = byId("archive-list");
  list.innerHTML = `<div class="loading-state">Loading seasons...</div>`;
  try {
    const payload = await fetchSeasons();
    list.innerHTML = payload.seasons.map((season) => `
      <button data-season="${h(season.id)}"><span>Season ${h(season.number)}</span><b>${h(season.status)}</b><small>${h(season.progressPercent)}% complete</small><i data-lucide="chevron-right"></i></button>
    `).join("");
    createIcons({ icons: { ChevronRight } });
    const buttons = list.querySelectorAll<HTMLButtonElement>("[data-season]");
    for (const button of buttons) {
      button.addEventListener("click", () => void showSeason(Number(button.dataset.season)));
    }
    const first = buttons.item(0);
    if (first) await showSeason(Number(first.dataset.season));
  } catch (error) {
    list.innerHTML = `<div class="empty-state">${h(error instanceof Error ? error.message : "Archive unavailable")}</div>`;
  }
}

async function showSeason(id: number): Promise<void> {
  const detail = byId("archive-detail");
  detail.innerHTML = `<div class="loading-state">Opening chronicle...</div>`;
  const payload = await fetchSeason(id);
  const season = payload.season;
  const report = payload.report;
  detail.innerHTML = `
    <div class="archive-title"><span>Season ${h(season.number)}</span><h3>${h(report?.headline ?? "A week around the Lagoon")}</h3><p>Commitment ${h(String(season.seedCommitment ?? "").slice(0, 24))}...</p></div>
    ${report?.poster ? `<img src="${h(report.poster)}" alt="Illustrated Season ${h(season.number)} chronicle" />` : ""}
    <div class="archive-days">${payload.chronicles.map((chronicle) => `<article><span>Day ${Number(chronicle.day) + 1}</span><h4>${h(chronicle.title)}</h4><p>${h(chronicle.narrative)}</p></article>`).join("")}</div>
  `;
}

for (const button of document.querySelectorAll<HTMLButtonElement>("[data-story-tab]")) {
  button.addEventListener("click", () => {
    storyTab = button.dataset.storyTab ?? "ledger";
    document.querySelectorAll("[data-story-tab]").forEach((item) => item.classList.toggle("active", item === button));
    if (state) renderStory(state);
  });
}

byId("story-content").addEventListener("click", async (event) => {
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest<HTMLButtonElement>("button");
  if (!button) return;
  if (button.dataset.resident !== undefined) {
    void openResident(button.dataset.resident);
    return;
  }
  if (button.dataset.choice !== undefined) {
    if (!state?.poll) return;
    button.disabled = true;
    try {
      await vote(state.poll.id, button.dataset.choice);
      setTicker("vote", { title: "Your vote is in. You can change it until the poll closes." });
      await refresh();
    } catch (error) {
      setTicker("alert", { title: error instanceof Error ? error.message : "Vote failed" });
      button.disabled = false;
    }
    return;
  }
  if (button.dataset.place !== undefined) {
    world?.focus(button.dataset.place);
    showInterior(button.dataset.place || "Building");
    byId("story-rail").classList.remove("open");
    return;
  }
  if (button.hasAttribute("data-open-archive")) void openArchive();
});

byId("zoom-in").addEventListener("click", () => world?.zoomIn());
byId("zoom-out").addEventListener("click", () => world?.zoomOut());
byId("map-fit").addEventListener("click", () => world?.fit());
byId("dossier-close").addEventListener("click", closeDossier);
byId("interior-close").addEventListener("click", hideInterior);
byId("archive-open").addEventListener("click", () => void openArchive());
byId("archive-close").addEventListener("click", () => { byId("archive-view").hidden = true; });
byId("roster-toggle").addEventListener("click", () => byId("resident-rail").classList.toggle("open"));
byId("story-toggle").addEventListener("click", () => byId("story-rail").classList.toggle("open"));

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closeDossier();
  hideInterior();
  byId("archive-view").hidden = true;
  byId("resident-rail").classList.remove("open");
  byId("story-rail").classList.remove("open");
});

connectEvents((type, payload) => {
  setTicker(type, payload);
  if (!document.hidden) void refresh();
});

setInterval(() => {
  if (!document.hidden) void refresh();
}, 5000);

setInterval(() => {
  if (lastFreshAt && Date.now() - lastFreshAt > 30_000) {
    const live = byId("live-state");
    live.classList.add("stale");
    live.querySelector("b")!.textContent = "Stale";
  }
}, 5000);

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void refresh();
});

void refresh();
