import {
  Activity,
  Archive,
  BookOpen,
  Brain,
  Building2,
  ChevronRight,
  CloudSun,
  createIcons,
  House,
  Landmark,
  LocateFixed,
  Map as MapIcon,
  MessageCircle,
  PackageOpen,
  Phone,
  Radio,
  ShoppingBasket,
  Store,
  Users,
  Vote as VoteIcon,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide";

import { connectEvents, fetchProperty, fetchResident, fetchSeason, fetchSeasons, fetchState, vote } from "./api";
import type { InventoryItem, KrabvilleState, LedgerEntry, Point, PropertyDetail, PublicNote, Resident, ResidentDetail } from "./types";
import "./style.css";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("app root missing");

const INTERIOR_GRID_SIZE = 5;
const INTERIOR_FRAME_COUNT = INTERIOR_GRID_SIZE * INTERIOR_GRID_SIZE;

app.innerHTML = `
  <div class="shell">
    <header class="topbar">
      <button class="icon-button mobile-only" id="roster-toggle" aria-label="Open residents"><i data-lucide="users"></i></button>
      <div class="brand-mark" aria-hidden="true">K</div>
      <div class="brand-copy"><strong>Krabville</strong><span>Lagoon social simulation</span></div>
      <nav class="top-nav" aria-label="Explore Krabville">
        <button class="active" id="map-home" aria-label="Live map"><i data-lucide="map"></i><span>Map</span></button>
        <button data-explore="residents"><i data-lucide="users"></i><span>People</span></button>
        <button data-explore="places"><i data-lucide="building-2"></i><span>Places</span></button>
        <button data-explore="bank"><i data-lucide="landmark"></i><span>Economy</span></button>
        <button data-explore="analytics"><i data-lucide="activity"></i><span>Analytics</span></button>
        <button data-explore="story"><i data-lucide="book-open"></i><span>Story</span></button>
        <button id="archive-open"><i data-lucide="archive"></i><span>Seasons</span></button>
      </nav>
      <div class="season-clock" id="season-clock">Waiting for the town...</div>
      <div class="status-cluster">
        <div class="live-state" id="live-state"><span></span><b>Connecting</b></div>
        <div class="budget-mini" id="budget-mini"></div>
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
          <button class="icon-button" id="map-fit" aria-label="Center the Lagoon"><i data-lucide="locate-fixed"></i></button>
        </div>
        <div class="weather-pill" id="weather-pill"><i data-lucide="cloud-sun"></i><span>Weather pending</span></div>
        <section class="map-vote" id="map-vote" aria-label="Visitor vote">
          <button class="map-vote-trigger" id="map-vote-trigger"><i data-lucide="vote"></i><span>Vote pending</span><small></small></button>
          <div class="map-vote-panel" id="map-vote-panel" hidden></div>
        </section>
        <aside class="resident-peek" id="resident-peek" role="tooltip" hidden></aside>
        <aside class="interior-view" id="interior-view" hidden aria-label="Building interior">
          <div class="interior-head"><div><span>Inside</span><b id="interior-name">Building</b></div><button class="icon-button" id="interior-close" aria-label="Close interior"><i data-lucide="x"></i></button></div>
          <div class="interior-art" id="interior-art" role="img"></div>
          <div class="interior-occupants" id="interior-occupants"></div>
          <button class="interior-open" id="interior-open">Open building details</button>
        </aside>
        <div class="live-ticker"><span class="ticker-signal"></span><b>LIVE</b><p id="live-ticker">Connecting to the town ledger...</p></div>
      </section>
    </main>
  </div>
  <section class="side-drawer" id="dossier" hidden aria-label="Resident dossier">
    <div class="drawer-head"><div><span>Resident dossier</span><h2 id="dossier-name">Resident</h2></div><button class="icon-button" id="dossier-close" aria-label="Close dossier"><i data-lucide="x"></i></button></div>
    <div class="drawer-body" id="dossier-body"></div>
  </section>
  <section class="explore-view" id="explore-view" hidden aria-label="Explore Krabville">
    <div class="explore-head"><div><span>Town directory</span><h2 id="explore-title">Explore</h2></div><button class="icon-button" id="explore-close" aria-label="Close explorer"><i data-lucide="x"></i></button></div>
    <div class="explore-content" id="explore-content"></div>
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
    Building2,
    ChevronRight,
    CloudSun,
    House,
    Landmark,
    LocateFixed,
    Map: MapIcon,
    MessageCircle,
    PackageOpen,
    Phone,
    Radio,
    ShoppingBasket,
    Store,
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
let initialRouteApplied = false;
let selectedSlug: string | null = null;
let lastFreshAt = 0;
let refreshPending: Promise<void> | null = null;
let activePropertySlug = "";
let mapVoteOpen = false;

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
    ? `${titleCase(weather.season ?? "summer")} | ${weather.condition ?? "clear"}  ${weather.temperatureC ?? "--"} C  ${weather.windKmh ?? "--"} km/h`
    : "Weather pending";
  byId("map-stage").dataset.season = weather?.season ?? "summer";
}

function renderRoster(value: KrabvilleState): void {
  byId("resident-count").textContent = String(value.residents.length);
  const list = byId("resident-list");
  list.innerHTML = value.residents
    .map(
      (resident) => `
      <button class="resident-row ${selectedSlug === resident.slug ? "selected" : ""}" data-resident="${h(resident.slug)}" data-life-stage="${h(resident.lifeStage ?? "adult")}">
        <span class="resident-dot" style="--resident-color:${h(resident.color)}"></span>
        <span><b>${h(resident.name)}</b><small>${h(resident.activity)}${resident.care?.caregiver ? ` | ${h(resident.care.caregiver)}` : ""}</small></span>
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
      ${resident.care?.caregiver ? `<div class="peek-care"><span>${h(resident.care.state.replaceAll("_", " "))}</span><b>Caregiver: ${h(resident.care.caregiver)}</b></div>` : ""}
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
  if (/clinic|hospital|health/.test(name)) return 13;
  if (/school|college/.test(name)) return 12;
  if (/library/.test(name)) return 9;
  if (/daycare|nursery|child|care service/.test(name)) return 24;
  if (/bank|credit union/.test(name)) return 11;
  if (/town hall|community|office/.test(name)) return 7;
  if (/cafe|restaurant/.test(name)) return 6;
  if (/workshop|boatworks|repair|radio/.test(name)) return 10;
  if (/pharmacy/.test(name)) return 17;
  if (/outfitter/.test(name)) return 19;
  if (/market|shop|store/.test(name)) return 14;
  if (/ferry/.test(name)) return 22;
  if (/shelter/.test(name)) return 20;
  if (/bed|apartment|flat/.test(name)) return 23;
  return /house|home|cottage/.test(name) ? 0 : 8;
}

function interiorPosition(frame: number): [number, number] {
  const normalized = ((frame % INTERIOR_FRAME_COUNT) + INTERIOR_FRAME_COUNT) % INTERIOR_FRAME_COUNT;
  const step = 100 / (INTERIOR_GRID_SIZE - 1);
  return [(normalized % INTERIOR_GRID_SIZE) * step, Math.floor(normalized / INTERIOR_GRID_SIZE) * step];
}

type InteriorResident = { slug: string; name: string; activity: string; mood?: string };

const LIFE_STAGE_SPRITE_ROWS: Record<string, number> = { baby: 0, child: 1, teen: 2, senior: 3 };

function stableHash(value: string): number {
  let hash = 2166136261;
  for (const character of value) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  return hash >>> 0;
}

function interiorActorMarkup(occupants: InteriorResident[], sceneKey: string): string {
  return `<div class="interior-live-actors" data-scene="${h(sceneKey)}">${occupants.map((occupant, index) => {
    const resident = state?.residents.find((item) => item.slug === occupant.slug);
    const rosterIndex = Math.max(0, state?.residents.findIndex((item) => item.slug === occupant.slug) ?? stableHash(occupant.slug) % 12);
    const lifeStage = resident?.lifeStage?.toLowerCase() ?? "adult";
    const lifeRow = LIFE_STAGE_SPRITE_ROWS[lifeStage];
    const variant = Math.abs(resident?.spriteVariant ?? rosterIndex) % 12;
    const atlas = lifeRow === undefined ? (variant < 6 ? "resident-a" : "resident-b") : "life-stage";
    const row = lifeRow ?? variant % 6;
    const rowCount = lifeRow === undefined ? 6 : 4;
    const rowPosition = row * (100 / (rowCount - 1));
    const activity = occupant.activity.toLowerCase();
    const resting = /sleep|nap|rest|bed/.test(activity);
    const zone: [number, number] = /cook|meal|eat|bottle|breakfast|lunch|dinner/.test(activity) ? [52, 65]
      : /wash|bath|hygiene|shower/.test(activity) ? [74, 61]
        : /read|study|homework|lesson/.test(activity) ? [31, 59]
          : /care|play|visit|talk|social|meeting/.test(activity) ? [47, 72]
            : /work|shift|shop|stock|repair|build|write/.test(activity) ? [64, 64]
              : resting ? [72, 55] : [40, 69];
    const hash = stableHash(`${sceneKey}:${occupant.slug}`);
    const spreadX = ((hash % 17) - 8) + (index % 3) * 7;
    const spreadY = (((hash >>> 5) % 11) - 5) + Math.floor(index / 3) * 6;
    const left = Math.max(19, Math.min(81, zone[0] + spreadX));
    const top = Math.max(43, Math.min(80, zone[1] + spreadY));
    const walkX = ((hash >>> 9) % 2 ? 1 : -1) * (14 + (hash % 13));
    const walkY = ((hash >>> 12) % 2 ? 1 : -1) * (4 + (hash % 8));
    const duration = 5 + (hash % 5);
    const firstName = occupant.name.split(" ")[0] ?? occupant.name;
    return `<button class="interior-actor ${resting ? "is-resting" : "is-moving"}" data-resident="${h(occupant.slug)}" style="--actor-left:${left}%;--actor-top:${top}%;--actor-walk-x:${walkX}px;--actor-walk-y:${walkY}px;--actor-duration:${duration}s;--actor-delay:-${hash % 7}s;--sprite-y:${rowPosition}%" aria-label="${h(`${occupant.name}: ${occupant.activity}`)}" title="${h(`${occupant.name} - ${occupant.activity}`)}"><span class="interior-actor-action">${h(occupant.activity)}</span><span class="interior-actor-sprite ${atlas}" aria-hidden="true"></span><b>${h(firstName)}</b></button>`;
  }).join("")}</div>`;
}

function insideListMarkup(occupants: InteriorResident[]): string {
  return occupants.map((resident) => `<button data-resident="${h(resident.slug)}"><b>${h(resident.name)}</b><span>${h(resident.activity)}</span><em>${h(resident.mood ?? state?.residents.find((item) => item.slug === resident.slug)?.mood ?? "active")}</em></button>`).join("") || `<div class="empty-state">The building is empty.</div>`;
}

function syncInteriorViews(value: KrabvilleState): void {
  if (currentInteriorSlug && !byId<HTMLElement>("interior-view").hidden) {
    const property = value.properties?.find((item) => item.slug === currentInteriorSlug);
    const occupants = property?.inside ?? [];
    byId("interior-art").innerHTML = interiorActorMarkup(occupants, currentInteriorSlug);
    byId("interior-occupants").innerHTML = occupants.length
      ? occupants.map((resident) => `<button data-resident="${h(resident.slug)}"><b>${h(resident.name)}</b><span>${h(resident.activity)}</span></button>`).join("")
      : `<span>Nobody is inside right now.</span>`;
  }
  if (!activePropertySlug) return;
  const property = value.properties?.find((item) => item.slug === activePropertySlug);
  const actorLayer = byId("explore-content").querySelector<HTMLElement>(".interior-live-actors");
  if (!property || !actorLayer) return;
  actorLayer.outerHTML = interiorActorMarkup(property.inside ?? [], activePropertySlug);
  const count = byId("explore-content").querySelector<HTMLElement>("[data-inside-count]");
  const list = byId("explore-content").querySelector<HTMLElement>(".inside-list");
  if (count) count.textContent = String(property.inside?.length ?? 0);
  if (list) list.innerHTML = insideListMarkup(property.inside ?? []);
}

let currentInteriorSlug = "";

function showInterior(location: string): void {
  const property = state?.properties?.find((item) => item.name === location || item.mapLocation === location);
  const frame = property?.interiorVariant ?? interiorFrame(location);
  const [x, y] = interiorPosition(frame);
  const art = byId<HTMLElement>("interior-art");
  art.style.setProperty("--interior-x", `${x}%`);
  art.style.setProperty("--interior-y", `${y}%`);
  const name = property?.name ?? location;
  art.setAttribute("aria-label", `${name} interior cutaway`);
  byId("interior-name").textContent = name;
  currentInteriorSlug = property?.slug ?? "";
  const occupants = property?.inside ?? [];
  art.innerHTML = interiorActorMarkup(occupants, currentInteriorSlug || name);
  byId("interior-occupants").innerHTML = occupants.length
    ? occupants.map((resident) => `<button data-resident="${h(resident.slug)}"><b>${h(resident.name)}</b><span>${h(resident.activity)}</span></button>`).join("")
    : `<span>Nobody is inside right now.</span>`;
  byId<HTMLButtonElement>("interior-open").disabled = !currentInteriorSlug;
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

function countdownLabel(ticks: number): string {
  const seconds = Math.max(0, Math.ceil(ticks * 12.5));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function renderMapVote(value: KrabvilleState): void {
  const trigger = byId<HTMLButtonElement>("map-vote-trigger");
  const panel = byId<HTMLElement>("map-vote-panel");
  const poll = value.poll;
  const season = value.season;
  const storedChoice = poll ? localStorage.getItem(`kv-vote-${poll.id}`) : null;
  const selected = poll?.options.find((option) => option.choiceId === storedChoice);
  trigger.className = "map-vote-trigger";
  trigger.disabled = !poll || poll.status !== "open";
  if (!season) {
    trigger.querySelector("span")!.textContent = "Voting offline";
    trigger.querySelector("small")!.textContent = "No active season";
  } else if (poll?.status === "open") {
    const remaining = Math.max(0, poll.closesTick - season.tick);
    trigger.classList.add(selected ? "chosen" : "attention");
    trigger.querySelector("span")!.textContent = selected ? selected.title : "Vote on tomorrow";
    trigger.querySelector("small")!.textContent = selected ? `Choice saved | ${countdownLabel(remaining)} left` : `${countdownLabel(remaining)} left`;
  } else {
    const dayStart = Math.floor(season.tick / 288) * 288;
    let nextOpen = dayStart + 24;
    if (nextOpen <= season.tick) nextOpen += 288;
    const winner = poll?.options.find((option) => option.winner);
    trigger.querySelector("span")!.textContent = winner ? `Next: ${winner.title}` : "Next visitor vote";
    trigger.querySelector("small")!.textContent = season.day >= 6 ? "Next season" : `opens in ${countdownLabel(nextOpen - season.tick)}`;
  }
  if (!poll || poll.status !== "open" || !mapVoteOpen) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  panel.innerHTML = `<header><div><span>Visitor decision</span><b>${h(poll.question ?? "Choose tomorrow's catalyst")}</b></div><button type="button" data-close-vote aria-label="Close vote"><i data-lucide="x"></i></button></header><div>${poll.options.map((option) => `<button class="map-vote-choice ${option.choiceId === storedChoice ? "selected" : ""}" data-map-choice="${h(option.choiceId)}"><span>${h(option.category)}</span><b>${h(option.title)}</b><small>${h(option.preview)}</small></button>`).join("")}</div>`;
  createIcons({ icons: { X } });
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
  const latest = entries.slice().sort((left, right) => (right.tick ?? right.day ?? 0) - (left.tick ?? left.day ?? 0)).slice(0, 16);
  return `<div class="town-card-list">${latest.map((entry) => `
    <article><span>${h(entry.category ?? (entry.day !== undefined ? `Day ${entry.day + 1}` : "Town record"))}</span><h4>${h(entry.title)}</h4>${entry.summary ? `<p>${h(entry.summary)}</p>` : ""}${entry.amount !== undefined ? `<b>${formatCad(entry.amount)}</b>` : ""}</article>
  `).join("")}</div>`;
}

function derivedHouseholds(value: KrabvilleState): NonNullable<KrabvilleState["households"]> {
  if (value.households?.length) return value.households;
  const homes = new Map<string, string[]>();
  for (const resident of value.residents) homes.set(resident.home, [...(homes.get(resident.home) ?? []), resident.name]);
  return [...homes].map(([home, memberNames], index) => ({ id: `v2-${index}`, name: home.replace(/ house$/i, " household"), home, memberNames }));
}

function propertyForPlace(value: KrabvilleState, place: string) {
  return value.properties?.find((property) => property.name === place || property.mapLocation === place);
}

function renderHouseholds(value: KrabvilleState): string {
  const households = derivedHouseholds(value);
  return `<div class="town-heading"><span>Households</span><b>${households.length}</b><p>Who shares a roof, and where daily life happens.</p></div><div class="town-card-list">${households.map((household) => {
    const members = household.memberNames ?? household.memberSlugs?.map((slug) => value.residents.find((resident) => resident.slug === slug)?.name ?? slug) ?? [];
    const property = propertyForPlace(value, household.home);
    const action = property?.slug ? `data-property="${h(property.slug)}"` : `data-focus-place="${h(household.home)}"`;
    return `<article class="place-card"><span>${h(household.status ?? "Household")}</span><h4>${h(household.name)}</h4><p>${h(members.join(", ") || "No residents listed")}</p><small>${h(household.home)}</small><button ${action}>Focus home</button></article>`;
  }).join("")}</div>`;
}

function renderFamilies(value: KrabvilleState): string {
  if (!value.families?.length) return `<div class="town-heading"><span>Family network</span><b>0</b><p>Kinship, caregiving, and generations appear here as relationships form.</p></div><div class="empty-state large">No public kinship records are available yet.</div>`;
  return `<div class="town-heading"><span>Family network</span><b>${value.families.length}</b><p>Families know only what their members have lived; spectators see the full lineage.</p></div><div class="town-card-list">${value.families.map((family) => `<article><span>Family</span><h4>${h(family.name)}</h4><p>${h(family.summary ?? family.members.map((member) => `${member.name} (${member.relation})`).join(", "))}</p></article>`).join("")}</div>`;
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

function occupantNames(property: NonNullable<KrabvilleState["properties"]>[number]): string {
  return property.inside?.map((resident) => resident.name).join(", ")
    || property.occupants?.map((resident) => resident.name).join(", ")
    || "Nobody is inside right now";
}

function miniNeedBars(resident: Resident): string {
  return displayedNeeds(resident)
    .sort((left, right) => left[1] - right[1])
    .slice(0, 3)
    .map(([label, value]) => `<div class="directory-meter"><span>${h(label)}</span><i><b class="${needTone(value)}" style="width:${value}%"></b></i><em>${Math.round(value)}</em></div>`)
    .join("");
}

function sparkline(values: number[]): string {
  if (!values.length) return `<div class="empty-chart">History begins after the next 04:00 settlement.</div>`;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 50 : (index * 100) / (values.length - 1);
    const y = high === low ? 50 : 92 - ((value - low) * 84) / (high - low);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  return `<svg class="money-chart" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Financial history"><polyline points="${points}"></polyline></svg>`;
}

function lineChart(series: Array<{ label: string; color: string; values: number[] }>, label: string, rebase = false): string {
  const plotted = rebase
    ? series.map((item) => ({ ...item, label: `${item.label} change`, values: item.values.map((value) => value - (item.values[0] ?? 0)) }))
    : series;
  const values = plotted.flatMap((item) => item.values);
  if (!values.length) return `<div class="empty-chart">History begins after the next daily settlement.</div>`;
  const low = Math.min(0, ...values);
  const high = Math.max(1, ...values);
  const lines = plotted.map((item) => {
    const points = item.values.map((value, index) => {
      const x = item.values.length === 1 ? 50 : (index * 100) / (item.values.length - 1);
      const y = 94 - ((value - low) * 86) / Math.max(1, high - low);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");
    return `<polyline points="${points}" style="--series-color:${item.color}"></polyline>`;
  }).join("");
  const dots = plotted.map((item) => item.values.map((value, index) => {
    const x = item.values.length === 1 ? 50 : (index * 100) / (item.values.length - 1);
    const y = 94 - ((value - low) * 86) / Math.max(1, high - low);
    return `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="1.35" style="--series-color:${item.color}"></circle>`;
  }).join("")).join("");
  return `<div class="chart-wrap"><svg class="line-chart" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="${h(label)}"><path class="chart-grid" d="M0 25H100 M0 50H100 M0 75H100"></path>${lines}${dots}</svg><div class="chart-legend">${plotted.map((item) => `<span style="--series-color:${item.color}"><i></i>${h(item.label)}</span>`).join("")}</div></div>`;
}

function barChart(items: Array<{ label: string; value: number }>, formatter: (value: number) => string = (value) => Math.round(value).toLocaleString()): string {
  const maximum = Math.max(1, ...items.map((item) => Math.max(0, item.value)));
  return `<div class="bar-chart">${items.map((item) => {
    const normalized = Math.max(0, item.value);
    return `<div><span>${h(item.label)}</span><i><b style="width:${normalized ? Math.max(2, (100 * normalized) / maximum) : 0}%"></b></i><em>${h(formatter(item.value))}</em></div>`;
  }).join("") || `<div class="empty-state">No samples yet.</div>`}</div>`;
}

function renderAnalytics(value: KrabvilleState): string {
  const stageCounts = Object.entries(value.residents.reduce<Record<string, number>>((counts, resident) => {
    const key = titleCase(resident.lifeStage ?? "adult");
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {})).map(([label, count]) => ({ label, value: count }));
  const moodCounts = Object.entries(value.residents.reduce<Record<string, number>>((counts, resident) => {
    const key = titleCase(resident.mood || "steady");
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {})).map(([label, count]) => ({ label, value: count })).sort((left, right) => right.value - left.value);
  const needKeys = [...new Set(value.residents.flatMap((resident) => Object.keys(resident.needs)))];
  const needs = needKeys.map((key) => ({
    label: titleCase(key),
    value: value.residents.reduce((sum, resident) => sum + needSatisfaction(resident, key), 0) / Math.max(1, value.residents.length),
  })).sort((left, right) => left.value - right.value);
  const locations = Object.entries(value.residents.reduce<Record<string, number>>((counts, resident) => {
    counts[resident.location] = (counts[resident.location] ?? 0) + 1;
    return counts;
  }, {})).map(([label, count]) => ({ label, value: count })).sort((left, right) => right.value - left.value);
  const economy = value.economy;
  const history = economy?.history ?? [];
  const relationships = value.analytics?.relationships;
  const modelSeries = Object.entries(value.usage.models).map(([model, usage]) => ({ label: shortModel(model), value: usage.tokens }));
  return `<div class="analytics-hero"><div><span>Krabville Analytics Lab</span><h3>Town pulse at Day ${(value.season?.day ?? 0) + 1}, ${formatTime(value.season?.worldMinutes ?? 0)}</h3><p>Live social, wellbeing, economy, inventory, activity, and model measurements from the public simulation ledger.</p></div><div class="analytics-live"><i></i><b>${value.season?.status ?? "ready"}</b><span>updated ${new Date(value.updatedAt).toLocaleTimeString()}</span></div></div>
    <div class="analytics-kpis"><article><span>Residents</span><b>${value.residents.length}</b><small>${stageCounts.map((item) => `${item.value} ${item.label.toLowerCase()}`).join(" | ")}</small></article><article><span>Town net worth</span><b>${formatCad((economy?.totalCash ?? 0) + (economy?.totalInvestments ?? 0) - (economy?.totalDebt ?? 0))}</b><small>${formatCad(economy?.totalDebt)} debt</small></article><article><span>Goods in shops</span><b>${Math.round(economy?.stockUnits ?? 0).toLocaleString()}</b><small>${economy?.catalogItems ?? 0} catalog items</small></article><article><span>Social activity</span><b>${relationships?.interactions ?? 0}</b><small>${relationships?.pairs ?? 0} relationship pairs</small></article><article><span>Story events</span><b>${value.townEvents?.length ?? value.events.length}</b><small>${value.conversations.length} conversations</small></article><article><span>Model calls</span><b>${value.usage.calls}</b><small>${value.usage.totalTokens.toLocaleString()} tokens</small></article></div>
    <div class="analytics-grid">
      <section><header><span>Population</span><b>Life stages</b></header>${barChart(stageCounts)}</section>
      <section><header><span>Wellbeing</span><b>Average need satisfaction</b></header>${barChart(needs, (number) => `${Math.round(number)}%`)}</section>
      <section><header><span>Mood</span><b>Residents now</b></header>${barChart(moodCounts)}</section>
      <section><header><span>Occupancy</span><b>Where everyone is</b></header>${barChart(locations)}</section>
      <section class="wide"><header><span>Economy</span><b>Daily change from first sample</b></header>${lineChart([{ label: "Net worth", color: "#60d394", values: history.map((point) => point.netWorth) }, { label: "Cash", color: "#63d8e3", values: history.map((point) => point.cash) }, { label: "Debt", color: "#ff6b6b", values: history.map((point) => point.debt) }, { label: "Investments", color: "#ffc857", values: history.map((point) => point.investments) }], "Town financial change over time", true)}</section>
      <section><header><span>Inventory</span><b>Units by category</b></header>${barChart((value.analytics?.inventoryByCategory ?? []).slice(0, 12).map((item) => ({ label: item.category, value: item.units })))}</section>
      <section><header><span>Goods flow</span><b>Movement by type</b></header>${barChart((value.analytics?.movements ?? []).map((item) => ({ label: item.type, value: item.units })))}</section>
      <section><header><span>Relationships</span><b>Town averages</b></header>${barChart([{ label: "Affinity", value: relationships?.affinity ?? 0 }, { label: "Trust", value: relationships?.trust ?? 0 }, { label: "Familiarity", value: relationships?.familiarity ?? 0 }, { label: "Tension", value: relationships?.tension ?? 0 }])}</section>
      <section><header><span>Inference</span><b>Tokens by model</b></header>${barChart(modelSeries)}</section>
    </div>
    <div class="section-label"><span>Most active relationships</span><b>${value.analytics?.strongestConnections?.length ?? 0}</b></div><div class="comparison-table">${(value.analytics?.strongestConnections ?? []).map((pair) => `<article><b>${h(pair.residentA)} + ${h(pair.residentB)}</b><span>Affinity ${pair.affinity}</span><span>Trust ${pair.trust}</span><span>Tension ${pair.tension}</span><em>${pair.interactions} interactions</em></article>`).join("") || `<div class="empty-state">Relationships are still forming.</div>`}</div>`;
}

function inventoryGrid(items: InventoryItem[]): string {
  if (!items.length) return `<div class="empty-state">No goods recorded here.</div>`;
  return `<div class="inventory-grid">${items.map((item) => {
    const index = Math.abs(item.assetIndex ?? stableHash(item.assetKey ?? item.name)) % 196;
    const x = (index % 14) * (100 / 13);
    const y = Math.floor(index / 14) * (100 / 13);
    return `<article data-inventory-name="${h(item.name.toLowerCase())}" data-inventory-category="${h(item.category)}"><span class="item-icon" data-item="${h(item.assetKey ?? "item")}" style="--item-x:${x}%;--item-y:${y}%" role="img" aria-label="${h(item.name)}"></span><div><b>${h(item.name)}</b><small>${h(item.category)}${item.condition !== undefined ? ` | ${item.condition}% condition` : ""}</small></div><em>${item.quantity.toLocaleString(undefined, { maximumFractionDigits: 1 })}${item.price !== undefined ? ` | ${formatCad(item.price)}` : ""}</em></article>`;
  }).join("")}</div>`;
}

function inventoryTools(items: InventoryItem[]): string {
  if (items.length < 12) return "";
  const categories = [...new Set(items.map((item) => item.category))].sort();
  return `<div class="inventory-tools"><label><span>Find an item</span><input type="search" data-inventory-search placeholder="Search ${items.length} items" autocomplete="off" /></label><label><span>Category</span><select data-inventory-category><option value="">All ${categories.length} categories</option>${categories.map((category) => `<option value="${h(category)}">${h(titleCase(category))}</option>`).join("")}</select></label><b data-inventory-visible>${items.length} shown</b></div>`;
}

const PROPERTY_EXTERIOR_POINTS: Record<string, [number, number]> = {
  "home-cedar-cottage": [576, 144],
  "home-tidepool-house": [2384, 160],
  "home-maple-row": [1360, 184],
  "home-north-dock-flat": [2160, 960],
  "home-harbour-family": [2448, 1744],
  "home-garden-family": [288, 912],
  "home-canal-family": [2704, 704],
  "home-lighthouse-single": [1696, 400],
  "home-market-single": [560, 736],
  "home-willow-single": [824, 592],
  "property-business-blue-kettle-cafe": [1040, 992],
  "property-business-community-house": [1456, 720],
  "property-business-harbour-library": [1328, 1136],
  "property-business-krabville-credit-union": [1872, 1040],
  "property-business-krabville-school": [2400, 1280],
  "property-business-lagoon-field-lab": [1040, 712],
  "property-business-lagoon-health-centre": [2008, 736],
  "property-business-signal-house": [488, 384],
  "property-business-tideway-gardens": [2896, 1312],
  "property-lagoon-general-store": [2416, 960],
  "property-harbour-pharmacy": [2384, 728],
  "property-tideway-outfitters": [832, 1360],
  "property-lagoon-ferry": [1488, 1680],
  "harbour-shelter": [2160, 960],
  "property-venture-s1-d0-30": [2080, 1216],
};

function buildingThumbnail(property: NonNullable<KrabvilleState["properties"]>[number] | undefined): string {
  if (!property || typeof property.x !== "number" || typeof property.y !== "number" || !Number.isFinite(property.x) || !Number.isFinite(property.y)) return `<div class="building-thumb fallback" role="img" aria-label="Building exterior unavailable"><span aria-hidden="true">KV</span></div>`;
  const [centerX, centerY] = PROPERTY_EXTERIOR_POINTS[property.slug ?? ""] ?? [property.x, property.y];
  const cropWidth = 480;
  const cropHeight = 270;
  const left = Math.max(0, Math.min(3072 - cropWidth, centerX - cropWidth / 2));
  const top = Math.max(0, Math.min(2048 - cropHeight, centerY - cropHeight / 2));
  const x = (100 * left) / (3072 - cropWidth);
  const y = (100 * top) / (2048 - cropHeight);
  return `<div class="building-thumb" style="--building-x:${x}%;--building-y:${y}%" role="img" aria-label="${h(property.name)} exterior"></div>`;
}

function directoryProperties(kind: "homes" | "buildings" | "places"): string {
  if (!state) return "";
  const homes = new Set(["house", "apartment"]);
  const properties = (state.properties ?? []).filter((property) => kind === "places" || (kind === "homes" ? homes.has(property.type ?? "") : !homes.has(property.type ?? "")));
  return `<div class="directory-grid property-directory">${properties.map((property) => `
    <button class="directory-card property-directory-card" data-property="${h(property.slug ?? "")}">
      ${buildingThumbnail(property)}
      <span class="card-state ${h(property.status ?? "active")}">${h(property.type ?? "place")} | ${h(property.status ?? "active")}</span>
      <h3>${h(property.name)}</h3><p>${h(property.address ?? property.mapLocation ?? "Krabville")}</p>
      <div class="card-totals"><span><b>${property.inside?.length ?? 0}</b> inside</span><span><b>${property.inventoryItems ?? 0}</b> items</span><span><b>${Math.round(property.inventoryUnits ?? 0)}</b> units</span></div>
      <div class="occupancy-line"><span>${h(occupantNames(property))}</span></div>
      <footer><span>${formatCad(property.value)}</span><em>${property.condition ?? 100}% condition</em></footer>
    </button>`).join("") || `<div class="empty-state large">No matching properties.</div>`}</div>`;
}

function exploreTabs(items: Array<[string, string]>, active: string): string {
  return `<nav class="explore-tabs" aria-label="Detail sections">${items.map(([route, label]) => `<button class="${route === active ? "active" : ""}" data-explore="${route}">${label}</button>`).join("")}</nav>`;
}

function renderExplorer(section: string): string {
  if (!state) return `<div class="loading-state">Waiting for town state...</div>`;
  const peopleTabs = exploreTabs([["residents", "Residents"], ["households", "Households"], ["family", "Families"], ["calls", "Calls"]], section);
  const placeTabs = exploreTabs([["places", "All places"], ["homes", "Homes"], ["buildings", "Work & civic"], ["shops", "Shops"]], section);
  const storyTabs = exploreTabs([["story", "Live story"], ["events", "Event ledger"], ["seasons", "Seasons"]], section);
  if (section === "residents") {
    return `${peopleTabs}<div class="explore-intro"><div><span>Everybody in town</span><h3>${state.residents.length} living residents</h3></div><p>Open anyone for decisions, relationships, money, calls, possessions, home goods, and their permanent life ledger.</p></div>
      <div class="directory-grid resident-directory">${state.residents.map((resident) => `
        <button class="directory-card resident-directory-card" data-resident="${h(resident.slug)}">
          <header><span style="--resident-color:${h(resident.color)}"></span><div><h3>${h(resident.name)}</h3><p>${h(resident.lifeStage ?? "resident")} | ${h(resident.role)}</p></div><em>${h(resident.mood)}</em></header>
          <b>${resident.indoors ? `Inside ${h(resident.building)}` : h(resident.activity)}</b>${miniNeedBars(resident)}
        </button>`).join("")}</div>`;
  }
  if (section === "households") return `${peopleTabs}${renderHouseholds(state)}`;
  if (section === "family") return `${peopleTabs}${renderFamilies(state)}`;
  if (section === "homes" || section === "buildings" || section === "places") return `${placeTabs}${directoryProperties(section)}`;
  if (section === "shops") {
    const businesses = state.economy?.businesses ?? [];
    return `${placeTabs}<div class="explore-intro"><div><span>Working economy</span><h3>${businesses.length} businesses</h3></div><p>Stock moves from the ferry into shops, residents buy what their households need, and shortages affect prices.</p></div>
      <div class="directory-grid shop-directory">${businesses.map((business) => `<button class="directory-card shop-card" data-property="${h(business.propertySlug ?? "")}">${buildingThumbnail(state?.properties?.find((property) => property.slug === business.propertySlug))}<span class="card-state ${h(business.status ?? "active")}">${h(business.status ?? "active")}</span><h3>${h(business.name)}</h3><p>${h(business.industry ?? "local business")} | ${business.employees ?? 0} staff</p><div class="shop-metrics"><b>${formatCad(business.cash)}</b><span>${business.inventoryItems ?? 0} items</span><span>${Math.round(business.inventoryUnits ?? 0)} units</span><em>${business.lowStockItems ?? 0} low</em></div><footer><span>${formatCad(business.sales)} sales</span><em>${h(business.owner ?? "community-owned")}</em></footer></button>`).join("")}</div>`;
  }
  if (section === "calls") {
    const calls = state.communications ?? [];
    return `${peopleTabs}<div class="explore-intro"><div><span>Lagoon phone network</span><h3>${calls.length} recent calls</h3></div><p>Teen, adult, and senior residents call to talk, ask for help, arrange work, trade, and make plans.</p></div><div class="call-ledger">${calls.map((call) => `<article class="${call.visibility}"><span>${h(call.purpose)} | ${call.durationMinutes} min | ${h(call.visibility)}</span><h3><button data-resident="${h(call.caller)}">${h(call.callerName)}</button> called <button data-resident="${h(call.recipient)}">${h(call.recipientName)}</button></h3><p>${h(call.summary)}</p></article>`).join("") || `<div class="empty-state large">The first calls will appear during the next daytime phone window.</div>`}</div>`;
  }
  if (section === "story") return `${storyTabs}<div class="story-explorer">${renderLiveStory(state)}${renderDocket(state)}</div>`;
  if (section === "events") return `${storyTabs}<div class="story-explorer">${renderEvents(state)}</div>`;
  if (section === "seasons") return `${storyTabs}${renderSeasons(state)}`;
  if (section === "analytics") return renderAnalytics(state);
  const economy = state.economy;
  const history = economy?.history ?? [];
  const accounts = economy?.accounts ?? [];
  const businesses = economy?.businesses ?? [];
  return `<div class="bank-hero"><div><span>Krabville Credit Union</span><h3>${formatCad((economy?.totalCash ?? 0) + (economy?.totalInvestments ?? 0) - (economy?.totalDebt ?? 0))}</h3><p>Town net worth across ${accounts.length} resident, household, and business accounts</p></div>${lineChart([{ label: "Net worth", color: "#60d394", values: history.map((point) => point.netWorth) }, { label: "Cash", color: "#63d8e3", values: history.map((point) => point.cash) }, { label: "Debt", color: "#ff6b6b", values: history.map((point) => point.debt) }, { label: "Investments", color: "#ffc857", values: history.map((point) => point.investments) }], "Krabville financial change", true)}</div>
    <div class="metric-grid bank-metrics"><article><span>Liquid cash</span><b>${formatCad(economy?.totalCash)}</b></article><article><span>Investments</span><b>${formatCad(economy?.totalInvestments)}</b></article><article><span>Debt</span><b>${formatCad(economy?.totalDebt)}</b></article><article><span>Median worth</span><b>${formatCad(economy?.medianNetWorth)}</b></article><article><span>Business revenue</span><b>${formatCad(economy?.businessRevenue)}</b></article><article><span>Services</span><b>${formatCad(economy?.serviceRevenue)}</b></article><article><span>Transactions</span><b>${economy?.transactionCount ?? 0}</b></article><article><span>Money moved</span><b>${formatCad(economy?.transactionVolume)}</b></article><article><span>Goods sold</span><b>${Math.round(economy?.goodsSold ?? 0)}</b></article><article><span>Stock units</span><b>${Math.round(economy?.stockUnits ?? 0)}</b></article><article><span>Barters</span><b>${economy?.barters ?? 0}</b></article><article><span>Phone calls</span><b>${economy?.phoneCalls ?? 0}</b></article></div>
    <div class="bank-analysis"><section><header><span>Account comparison</span><b>Largest balances</b></header>${barChart(accounts.slice().sort((left, right) => right.balance - left.balance).slice(0, 12).map((account) => ({ label: account.owner, value: Math.max(0, account.balance) })), formatCad)}</section><section><header><span>Business comparison</span><b>Operating cash</b></header>${barChart(businesses.slice().sort((left, right) => (right.cash ?? 0) - (left.cash ?? 0)).map((business) => ({ label: business.name, value: business.cash ?? 0 })), formatCad)}</section><section><header><span>Market prices</span><b>Average basket over days</b></header>${lineChart([{ label: "Average item", color: "#ffc857", values: (state.analytics?.prices ?? []).map((point) => point.averagePrice) }, { label: "Units sold", color: "#63d8e3", values: (state.analytics?.prices ?? []).map((point) => point.unitsSold) }], "Average prices and units sold")}</section></div>
    <div class="section-label"><span>All resident, household, and business accounts</span><b>${accounts.length}</b></div>
    <div class="bank-ledger">${accounts.map((account) => account.residentSlug
      ? `<button type="button" class="${h(account.ownerKind)}" data-resident="${h(account.residentSlug)}"><span class="account-mark">${h(account.ownerKind.slice(0, 1).toUpperCase())}</span><span><b>${h(account.owner)}</b><small>${h(account.name)} | ${h(account.type)} | ${h(account.status)}</small></span><em>${formatCad(account.balance)}</em></button>`
      : `<article class="${h(account.ownerKind)}"><span class="account-mark">${h(account.ownerKind.slice(0, 1).toUpperCase())}</span><div><b>${h(account.owner)}</b><small>${h(account.name)} | ${h(account.type)} | ${h(account.status)}</small></div><em>${formatCad(account.balance)}</em></article>`).join("") || `<div class="empty-state">No financial accounts yet.</div>`}</div>
    <div class="section-label"><span>Recent transactions</span><b>${economy?.transactions?.length ?? 0}</b></div>${renderLedgerEntries((economy?.transactions ?? []).map((entry) => ({ ...entry, title: entry.description })), "No posted transactions yet.")}`;
}

async function openExplorer(section: string, pushHistory = true): Promise<void> {
  if (!state) return;
  closeDossier();
  activePropertySlug = "";
  const view = byId<HTMLElement>("explore-view");
  view.hidden = false;
  const titles: Record<string, string> = { residents: "Residents", households: "Households", family: "Families", calls: "Phone network", places: "Places", homes: "Homes", buildings: "Work & civic places", shops: "Shops & businesses", bank: "Bank & economy", analytics: "Krabville Analytics Lab", story: "Living story", events: "Event ledger", seasons: "Seasons" };
  byId("explore-title").textContent = titles[section] ?? "Explore";
  const content = byId("explore-content");
  content.innerHTML = renderExplorer(section);
  content.scrollTop = 0;
  const people = ["residents", "households", "family", "calls"];
  const places = ["places", "homes", "buildings", "shops"];
  const story = ["story", "events", "seasons"];
  const topRoute = people.includes(section) ? "residents" : places.includes(section) ? "places" : story.includes(section) ? "story" : section;
  document.querySelectorAll<HTMLButtonElement>(".top-nav [data-explore]").forEach((button) => button.classList.toggle("active", button.dataset.explore === topRoute));
  byId("map-home").classList.remove("active");
  if (pushHistory) history.pushState(null, "", `#/explore/${section}`);
}

async function openProperty(slug: string, pushHistory = true): Promise<void> {
  if (!slug) return;
  activePropertySlug = slug;
  const view = byId<HTMLElement>("explore-view");
  view.hidden = false;
  byId("explore-title").textContent = "Building";
  const content = byId("explore-content");
  content.scrollTop = 0;
  content.innerHTML = `<div class="loading-state">Opening the building ledger...</div>`;
  try {
    const detail: PropertyDetail = await fetchProperty(slug);
    const [x, y] = interiorPosition(detail.interiorVariant);
    const inventoryUnits = detail.inventory.reduce((sum, item) => sum + item.quantity, 0);
    const inventoryCategories = new Set(detail.inventory.map((item) => item.category)).size;
    const lowStockItems = detail.inventory.filter((item) => item.lowStock).length;
    byId("explore-title").textContent = detail.name;
    content.innerHTML = `<div class="building-detail-head"><div><span>${h(detail.type)} | ${h(detail.status)}</span><h3>${h(detail.name)}</h3><p>${h(detail.address)} | ${detail.condition}% condition | ${formatCad(detail.value)}</p></div><button data-focus-place="${h(detail.mapLocation)}">Show on map</button></div>
      <div class="building-detail-grid"><div class="property-interior" style="--interior-x:${x}%;--interior-y:${y}%" role="group" aria-label="${h(detail.name)} live interior">${interiorActorMarkup(detail.residents, detail.slug)}</div><section><div class="section-label"><span>Inside now</span><b data-inside-count>${detail.residents.length}</b></div><div class="inside-list">${insideListMarkup(detail.residents)}</div></section></div>
      <div class="inventory-summary"><article><span>Unique items</span><b>${detail.inventory.length}</b></article><article><span>Total units</span><b>${inventoryUnits.toLocaleString(undefined, { maximumFractionDigits: 1 })}</b></article><article><span>Categories</span><b>${inventoryCategories}</b></article><article><span>Low stock</span><b>${lowStockItems}</b></article></div>
      <div class="section-label"><span>${detail.business ? "Shop stock" : "Home inventory"}</span><b>${detail.inventory.length}</b></div>${inventoryTools(detail.inventory)}${inventoryGrid(detail.inventory)}
      <div class="section-label"><span>Building transactions</span><b>${detail.transactions.length}</b></div>${renderLedgerEntries(detail.transactions.map((entry) => ({ ...entry, title: entry.description })), "No business transactions recorded here.")}`;
    const search = content.querySelector<HTMLInputElement>("[data-inventory-search]");
    const category = content.querySelector<HTMLSelectElement>("[data-inventory-category]");
    const visible = content.querySelector<HTMLElement>("[data-inventory-visible]");
    const applyInventoryFilter = () => {
      const query = search?.value.trim().toLowerCase() ?? "";
      const selected = category?.value ?? "";
      let shown = 0;
      content.querySelectorAll<HTMLElement>(".inventory-grid article").forEach((item) => {
        const matches = (!query || (item.dataset.inventoryName ?? "").includes(query))
          && (!selected || item.dataset.inventoryCategory === selected);
        item.hidden = !matches;
        if (matches) shown += 1;
      });
      if (visible) visible.textContent = `${shown} shown`;
    };
    search?.addEventListener("input", applyInventoryFilter);
    category?.addEventListener("change", applyInventoryFilter);
    document.querySelectorAll<HTMLButtonElement>(".top-nav [data-explore]").forEach((button) => button.classList.toggle("active", button.dataset.explore === "places"));
    byId("map-home").classList.remove("active");
    if (pushHistory) history.pushState(null, "", `#/property/${encodeURIComponent(slug)}`);
  } catch (error) {
    content.innerHTML = `<div class="empty-state large"><b>Building ledger unavailable</b><p>${h(error instanceof Error ? error.message : "Please try again.")}</p><button data-retry-property="${h(slug)}">Retry</button></div>`;
  }
}

function closeExplorer(clearHash = true): void {
  byId<HTMLElement>("explore-view").hidden = true;
  activePropertySlug = "";
  document.querySelectorAll<HTMLButtonElement>(".top-nav [data-explore]").forEach((button) => button.classList.remove("active"));
  byId("map-home").classList.add("active");
  if (clearHash && location.hash.startsWith("#/")) history.replaceState(null, "", location.pathname + location.search);
}

function applyHashRoute(): void {
  const exploreMatch = location.hash.match(/^#\/explore\/([a-z-]+)$/);
  const propertyMatch = location.hash.match(/^#\/property\/([^/]+)$/);
  if (exploreMatch) void openExplorer(exploreMatch[1]!, false);
  else if (propertyMatch) void openProperty(decodeURIComponent(propertyMatch[1]!), false);
  else closeExplorer(false);
}

function render(value: KrabvilleState): void {
  state = value;
  lastFreshAt = Date.now();
  renderTop(value);
  renderRoster(value);
  renderMapVote(value);
  syncInteriorViews(value);
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
      if (!initialRouteApplied) {
        initialRouteApplied = true;
        applyHashRoute();
      }
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
    const onPerson = detail.onPersonInventory ?? inventory.map((name) => ({ name, category: "personal", quantity: 1 }));
    const clothing = detail.clothing ?? onPerson.filter((item) => ["clothing", "accessories"].includes(item.category));
    const carried = onPerson.filter((item) => !["clothing", "accessories"].includes(item.category));
    const homeInventory = detail.homeInventory ?? [];
    const relationshipRows = detail.relationships.slice().sort((left, right) => (right.affinity + right.trust - right.tension) - (left.affinity + left.trust - left.tension));
    const finance = detail.finances;
    byId("dossier-name").textContent = detail.name;
    byId("dossier-body").innerHTML = `
      <section class="resident-summary"><span style="--resident-color:${h(detail.color)}"></span><div><b>${h(detail.role)}${detail.lifeStage ? ` | ${h(detail.lifeStage)}` : ""}</b><p>${h(detail.activity)} at ${h(detail.location)}</p></div><em>${h(detail.mood)}</em></section>
      <nav class="detail-tabs" aria-label="Dossier sections">
        <button class="active" data-detail-target="dossier-life">Life</button><button data-detail-target="dossier-needs">Needs</button><button data-detail-target="dossier-family">Family</button><button data-detail-target="dossier-relationships">Relationships</button><button data-detail-target="dossier-phone">Phone</button><button data-detail-target="dossier-secrets">Secrets</button><button data-detail-target="dossier-health">Health</button><button data-detail-target="dossier-career">Career</button><button data-detail-target="dossier-finances">Money</button><button data-detail-target="dossier-property">Home & goods</button><button data-detail-target="dossier-memory">Memories</button><button data-detail-target="dossier-ledger">Life ledger</button>
      </nav>

      <section class="detail-section dossier-section" id="dossier-life">
        <div class="section-label"><span>Life</span><b>${h(detail.ageLabel ?? detail.lifeStage ?? "Resident")}</b></div>
        <div class="profile-band"><p>${h(detail.about)}</p><small>${h(detail.routine)}</small></div>
        <div class="thought-band"><span>In their head</span><p>${h(detail.pondering?.thought || detail.publicThought)}</p><small>${h(detail.intention)}</small></div>
        <div class="trait-grid">${Object.entries(detail.traits).map(([trait, score]) => `<div><span>${h(titleCase(trait))}</span><b>${Math.round(score)}</b></div>`).join("")}</div>
        <div class="section-label"><span>Likely decisions</span><b>Top ${forecasts.length}</b></div>${renderDecisionForecasts(forecasts)}
      </section>

      <section class="detail-section dossier-section" id="dossier-needs"><div class="section-label"><span>Needs, high is healthy</span><b>${h(detail.mood)}</b></div>${displayedNeeds(detail).map(([label, value, key]) => needBar(label, value, key)).join("")}<div class="section-label"><span>Wants and aspirations</span><b>${wants.length}</b></div>${renderNotes(wants, "No public wants have formed yet.")}</section>

      <section class="detail-section dossier-section" id="dossier-family"><div class="section-label"><span>Family and household</span><b>${detail.family?.length ?? 0}</b></div><div class="fact-grid"><article><span>Home</span><b>${h(detail.home)}</b></article><article><span>Household</span><b>${h(detail.household ?? "Not yet recorded")}</b></article></div>${detail.family?.length ? `<div class="note-list">${detail.family.map((member) => `<article><span>${h(member.relation)}</span><h4>${h(member.name)}</h4><p>${h([member.lifeStage, member.household].filter(Boolean).join(" | "))}</p></article>`).join("")}</div>` : `<div class="empty-state">No public kinship record is available for this resident.</div>`}</section>

      <section class="detail-section dossier-section" id="dossier-relationships"><div class="section-label"><span>Relationship map</span><b>${detail.relationships.length}</b></div><canvas class="relationship-canvas" id="relationship-canvas"></canvas><div class="relationship-list">${relationshipRows.map((relationship) => `<article><b>${h(relationship.otherName)}</b><span>Affinity ${relationship.affinity} | Trust ${relationship.trust} | Tension ${relationship.tension}</span>${relationship.kinship ? `<small>${h(relationship.kinship)}</small>` : ""}</article>`).join("")}</div></section>

      <section class="detail-section dossier-section" id="dossier-phone"><div class="section-label"><span>Phone</span><b>${h(detail.phone?.number ?? "No phone")}</b></div><div class="phone-card"><i data-lucide="phone"></i><div><span>${h(detail.phone?.device ?? "No device issued")}</span><b>${h(detail.phone?.number ?? "Children receive a phone as teens")}</b></div><em>${detail.phone?.active ? "connected" : "offline"}</em></div><div class="section-label"><span>Recent calls</span><b>${detail.communications?.length ?? 0}</b></div><div class="call-ledger">${detail.communications?.map((call) => `<article class="${h(call.visibility)}"><span>${h(call.direction)} | ${h(call.purpose)} | ${call.durationMinutes} min | ${h(call.visibility)}</span><h3>${h(call.otherName)}</h3><p>${h(call.summary)}</p></article>`).join("") || `<div class="empty-state">No calls yet.</div>`}</div></section>

      <section class="detail-section dossier-section" id="dossier-secrets"><div class="section-label"><span>Secrets</span><b>${detail.secrets?.length ?? 0}</b></div>${renderNotes(detail.secrets, "No spectator-visible secrets yet.")}<div class="section-label"><span>Beliefs and gossip</span><b>${detail.beliefs?.length ?? 0}</b></div>${renderNotes(detail.beliefs, "No conflicting beliefs have formed yet.")}</section>

      <section class="detail-section dossier-section" id="dossier-health"><div class="section-label"><span>Health and care</span><b>${h(detail.health?.status ?? "No current record")}</b></div><div class="fact-grid"><article><span>Conditions</span><b>${h(detail.health?.conditions?.join(", ") || "None published")}</b></article><article><span>Caregiver</span><b>${h(detail.health?.caregiver ?? "Independent")}</b></article><article><span>Care plan</span><b>${h(detail.health?.care?.join(", ") || "None")}</b></article><article><span>Stress</span><b>${detail.health?.stress ?? "--"}</b></article></div></section>

      <section class="detail-section dossier-section" id="dossier-career"><div class="section-label"><span>Career</span><b>${h(detail.career?.status ?? "Current")}</b></div><div class="fact-grid"><article><span>Role</span><b>${h(detail.career?.title ?? detail.role)}</b></article><article><span>Employer</span><b>${h(detail.career?.employer ?? detail.workplace)}</b></article><article><span>Schedule</span><b>${h(detail.career?.schedule ?? detail.routine)}</b></article><article><span>Daily income</span><b>${formatCad(detail.career?.income)}</b></article></div></section>

      <section class="detail-section dossier-section" id="dossier-finances"><div class="section-label"><span>Finances and net worth</span><b>${formatCad(finance?.netWorth)}</b></div><div class="resident-finance-chart">${sparkline(finance?.history?.map((point) => point.netWorth) ?? [])}</div><div class="metric-grid"><article><span>Cash</span><b>${formatCad(finance?.cash)}</b></article><article><span>Chequing</span><b>${formatCad(finance?.chequing)}</b></article><article><span>Savings</span><b>${formatCad(finance?.savings)}</b></article><article><span>Investments</span><b>${formatCad(finance?.investments)}</b></article><article><span>Debt</span><b>${formatCad(finance?.debt)}</b></article><article><span>Net worth</span><b>${formatCad(finance?.netWorth)}</b></article></div><div class="section-label"><span>Accounts</span><b>${finance?.accounts?.length ?? 0}</b></div><div class="account-list">${finance?.accounts?.map((account) => `<article><span>${h(account.type)} | ${h(account.status)}</span><b>${h(account.name)}</b><em>${formatCad(account.balance)}</em></article>`).join("") || `<div class="empty-state">No accounts.</div>`}</div><div class="section-label"><span>Transactions</span><b>${detail.transactions?.length ?? 0}</b></div>${renderLedgerEntries((detail.transactions ?? []).map((entry) => ({ ...entry, title: entry.description })), "No posted transactions yet.")}</section>

      <section class="detail-section dossier-section" id="dossier-property"><div class="section-label"><span>Home and property</span><b>${detail.properties?.length ?? 0}</b></div><div class="fact-grid"><article><span>Home</span><b>${h(detail.home)}</b></article><article><span>Workplace</span><b>${h(detail.workplace)}</b></article></div>${detail.properties?.map((property) => `<button class="property-row" data-property="${h(property.slug ?? "")}"><span>${h(property.type ?? "Property")}</span><b>${h(property.name)}</b><small>${formatCad(property.value)}</small></button>`).join("") ?? ""}<div class="section-label"><span>Clothing and outfit</span><b>${clothing.length}</b></div>${inventoryGrid(clothing)}<div class="section-label"><span>Carried now</span><b>${carried.length}</b></div>${inventoryGrid(carried)}<div class="section-label"><span>Stocked at home</span><b>${homeInventory.length}</b></div>${inventoryGrid(homeInventory)}</section>

      <section class="detail-section dossier-section" id="dossier-memory"><div class="section-label"><span>Recent memories</span><b>${detail.memories.length}</b></div><div class="memory-list">${detail.memories.slice(0, 16).map((memory) => `<article><span>${h(memory.kind)} | salience ${memory.salience}</span><p>${h(memory.content)}</p></article>`).join("") || `<div class="empty-state">No retained memories yet.</div>`}</div></section>

      <section class="detail-section dossier-section" id="dossier-ledger"><div class="section-label"><span>Life ledger</span><b>${detail.lifeLedger?.length ?? 0}</b></div>${renderLedgerEntries(detail.lifeLedger ?? [], "Births, moves, relationships, careers, money, and other lasting changes will collect here.")}</section>
    `;
    const sections = [...byId("dossier-body").querySelectorAll<HTMLElement>(".dossier-section")];
    sections.forEach((section, index) => { section.hidden = index !== 0; });
    for (const button of byId("dossier-body").querySelectorAll<HTMLButtonElement>("[data-detail-target]")) {
      button.addEventListener("click", () => {
        const target = document.getElementById(button.dataset.detailTarget ?? "");
        if (!target) return;
        byId("dossier-body").querySelectorAll("[data-detail-target]").forEach((item) => item.classList.toggle("active", item === button));
        sections.forEach((section) => { section.hidden = section !== target; });
        byId("dossier-body").scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      });
    }
    for (const button of byId("dossier-body").querySelectorAll<HTMLButtonElement>("[data-property]")) {
      button.addEventListener("click", () => { closeDossier(); void openProperty(button.dataset.property ?? ""); });
    }
    createIcons({ icons: { Phone } });
    requestAnimationFrame(() => drawRelationshipGraph(byId<HTMLCanvasElement>("relationship-canvas"), detail));
  } catch (error) {
    byId("dossier-name").textContent = state?.residents.find((resident) => resident.slug === slug)?.name ?? "Resident";
    byId("dossier-body").innerHTML = `<div class="empty-state large"><b>Dossier temporarily unavailable</b><p>${h(error instanceof Error ? error.message : "Please try again.")}</p><button id="dossier-retry">Retry</button></div>`;
    byId("dossier-retry").addEventListener("click", () => void openResident(slug));
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

for (const button of document.querySelectorAll<HTMLButtonElement>("[data-explore]")) {
  button.addEventListener("click", () => void openExplorer(button.dataset.explore ?? "residents"));
}

byId("explore-content").addEventListener("click", async (event) => {
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest<HTMLButtonElement>("button");
  if (!button) return;
  if (button.dataset.explore) {
    void openExplorer(button.dataset.explore);
  } else if (button.dataset.resident) {
    void openResident(button.dataset.resident);
  } else if (button.dataset.property) {
    void openProperty(button.dataset.property);
  } else if (button.dataset.focusPlace) {
    world?.focus(button.dataset.focusPlace);
    closeExplorer();
  } else if (button.dataset.retryProperty) {
    void openProperty(button.dataset.retryProperty, false);
  } else if (button.dataset.choice) {
    if (!state?.poll) return;
    button.disabled = true;
    try {
      await vote(state.poll.id, button.dataset.choice);
      setTicker("vote", { title: "Your vote is in. You can change it until the poll closes." });
      await refresh();
      void openExplorer("vote", false);
    } catch (error) {
      setTicker("alert", { title: error instanceof Error ? error.message : "Vote failed" });
      button.disabled = false;
    }
  } else if (button.hasAttribute("data-open-archive")) {
    void openArchive();
  }
});

byId("zoom-in").addEventListener("click", () => world?.zoomIn());
byId("zoom-out").addEventListener("click", () => world?.zoomOut());
byId("map-fit").addEventListener("click", () => world?.fit());
byId("dossier-close").addEventListener("click", closeDossier);
byId("explore-close").addEventListener("click", () => closeExplorer());
byId("interior-close").addEventListener("click", hideInterior);
byId("interior-open").addEventListener("click", () => {
  if (!currentInteriorSlug) return;
  hideInterior();
  void openProperty(currentInteriorSlug);
});
byId("interior-occupants").addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const resident = event.target.closest<HTMLButtonElement>("[data-resident]")?.dataset.resident;
  if (resident) { hideInterior(); void openResident(resident); }
});
byId("interior-art").addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const resident = event.target.closest<HTMLButtonElement>("[data-resident]")?.dataset.resident;
  if (resident) { hideInterior(); void openResident(resident); }
});
byId("map-vote-trigger").addEventListener("click", () => {
  if (!state?.poll || state.poll.status !== "open") return;
  mapVoteOpen = !mapVoteOpen;
  renderMapVote(state);
});
byId("map-vote-panel").addEventListener("click", async (event) => {
  if (!(event.target instanceof Element) || !state?.poll) return;
  const button = event.target.closest<HTMLButtonElement>("button");
  if (!button) return;
  if (button.hasAttribute("data-close-vote")) {
    mapVoteOpen = false;
    renderMapVote(state);
    return;
  }
  if (!button.dataset.mapChoice) return;
  button.disabled = true;
  try {
    await vote(state.poll.id, button.dataset.mapChoice);
    localStorage.setItem(`kv-vote-${state.poll.id}`, button.dataset.mapChoice);
    mapVoteOpen = false;
    setTicker("vote", { title: "Your choice is saved for tomorrow." });
    await refresh();
  } catch (error) {
    setTicker("alert", { title: error instanceof Error ? error.message : "Vote failed" });
    button.disabled = false;
  }
});
byId("archive-open").addEventListener("click", () => void openArchive());
byId("archive-close").addEventListener("click", () => { byId("archive-view").hidden = true; });
byId("roster-toggle").addEventListener("click", () => byId("resident-rail").classList.toggle("open"));
byId("map-home").addEventListener("click", () => {
  closeDossier();
  hideInterior();
  byId<HTMLElement>("archive-view").hidden = true;
  closeExplorer();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closeDossier();
  hideInterior();
  byId("archive-view").hidden = true;
  closeExplorer();
  byId("resident-rail").classList.remove("open");
});

window.addEventListener("popstate", () => {
  applyHashRoute();
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
