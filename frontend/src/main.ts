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
import type { KrabvilleState, Point, ResidentDetail } from "./types";
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
      <section class="map-stage" aria-label="Live map of Krabville">
        <div id="world"></div>
        <div class="map-tools" aria-label="Map controls">
          <button class="icon-button" id="zoom-in" aria-label="Zoom in"><i data-lucide="zoom-in"></i></button>
          <button class="icon-button" id="zoom-out" aria-label="Zoom out"><i data-lucide="zoom-out"></i></button>
          <button class="icon-button" id="map-fit" aria-label="Show the whole Lagoon"><i data-lucide="locate-fixed"></i></button>
        </div>
        <div class="weather-pill" id="weather-pill"><i data-lucide="cloud-sun"></i><span>Weather pending</span></div>
        <button class="story-toggle" id="story-toggle"><i data-lucide="panel-right-open"></i><span>Town story</span></button>
        <div class="live-ticker"><span class="ticker-signal"></span><b>LIVE</b><p id="live-ticker">Connecting to the town ledger...</p></div>
      </section>
      <aside class="story-rail" id="story-rail">
        <div class="story-tabs" role="tablist">
          <button class="active" data-story-tab="live"><i data-lucide="activity"></i><span>Live</span></button>
          <button data-story-tab="vote"><i data-lucide="vote"></i><span>Vote</span></button>
          <button data-story-tab="docket"><i data-lucide="book-open"></i><span>Docket</span></button>
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

const shortModel = (model: string): string =>
  model.replace("gpt-", "GPT ").replace("-codex", " Codex").replaceAll("-", " ");

let state: KrabvilleState | null = null;
let selectedSlug: string | null = null;
let storyTab = "live";
let lastFreshAt = 0;
let refreshPending: Promise<void> | null = null;

let world: import("./game").LagoonWorld | null = null;
let worldLoading: Promise<import("./game").LagoonWorld> | null = null;

async function ensureWorld(): Promise<import("./game").LagoonWorld> {
  if (world) return world;
  if (!worldLoading) {
    worldLoading = import("./game").then(({ LagoonWorld }) => {
      world = new LagoonWorld("world", (slug) => void openResident(slug));
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
    button.addEventListener("click", () => void openResident(button.dataset.resident ?? ""));
  }
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
      <h3>${poll.status === "open" ? "Choose tomorrow's catalyst" : "Voting has closed"}</h3>
      <p>The winning event is guaranteed to shape the next day.</p>
    </section>
    <div class="poll-options">
      ${poll.options.map((option) => {
        const percent = total ? Math.round((100 * option.votes) / total) : 0;
        return `<button class="poll-choice ${option.winner ? "winner" : ""}" data-choice="${h(option.choiceId)}" ${poll.status !== "open" ? "disabled" : ""}>
          <span><b>${h(option.choiceId)}</b><em>${h(option.category)}</em></span>
          <h4>${h(option.title)}</h4><p>${h(option.preview)}</p>
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

function renderStory(value: KrabvilleState): void {
  const content = byId("story-content");
  content.innerHTML = storyTab === "vote" ? renderPoll(value) : storyTab === "docket" ? renderDocket(value) : renderLiveStory(value);
  for (const button of content.querySelectorAll<HTMLButtonElement>("[data-resident]")) {
    button.addEventListener("click", () => void openResident(button.dataset.resident ?? ""));
  }
  for (const button of content.querySelectorAll<HTMLButtonElement>("[data-choice]")) {
    button.addEventListener("click", async () => {
      if (!value.poll) return;
      button.disabled = true;
      try {
        await vote(value.poll.id, button.dataset.choice ?? "");
        setTicker("vote", { title: "Your vote is in. You can change it until the poll closes." });
        await refresh();
      } catch (error) {
        setTicker("alert", { title: error instanceof Error ? error.message : "Vote failed" });
        button.disabled = false;
      }
    });
  }
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

function needBar(label: string, value: number): string {
  return `<div class="need-row"><span>${h(label)}</span><div><i style="width:${Math.max(0, Math.min(100, value))}%"></i></div><b>${Math.round(value)}</b></div>`;
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
  selectedSlug = slug;
  world?.select(slug);
  if (state) renderRoster(state);
  const drawer = byId<HTMLElement>("dossier");
  drawer.hidden = false;
  byId("dossier-name").textContent = "Loading...";
  byId("dossier-body").innerHTML = `<div class="loading-state">Opening the resident ledger...</div>`;
  try {
    const detail = await fetchResident(slug);
    byId("dossier-name").textContent = detail.name;
    byId("dossier-body").innerHTML = `
      <section class="resident-summary" id="dossier-overview"><span style="--resident-color:${h(detail.color)}"></span><div><b>${h(detail.role)}</b><p>${h(detail.activity)} at ${h(detail.location)}</p></div></section>
      <section class="profile-band"><p>${h(detail.about)}</p><small>${h(detail.routine)}</small></section>
      <section class="thought-band"><span>Public thought</span><p>${h(detail.publicThought)}</p><small>${h(detail.intention)}</small></section>
      <nav class="detail-tabs" aria-label="Dossier sections"><button class="active" data-detail-target="dossier-overview">Overview</button><button data-detail-target="dossier-memory">Memory</button><button data-detail-target="dossier-relationships">Relationships</button></nav>
      <section class="detail-section"><div class="section-label"><span>Needs</span><b>${h(detail.mood)}</b></div>${Object.entries(detail.needs).map(([key, value]) => needBar(key, value)).join("")}</section>
      <section class="detail-section"><div class="section-label"><span>Possessions</span><b>${detail.possessions.length}</b></div><div class="possession-list">${detail.possessions.map((item) => `<span>${h(item)}</span>`).join("")}</div></section>
      <section class="detail-section" id="dossier-relationships"><div class="section-label"><span>Relationship map</span><b>${detail.relationships.length}</b></div><canvas class="relationship-canvas" id="relationship-canvas"></canvas></section>
      <section class="detail-section" id="dossier-memory"><div class="section-label"><span>Recent memory</span><b>${detail.memories.length}</b></div><div class="memory-list">${detail.memories.slice(0, 8).map((memory) => `<article><span>${h(memory.kind)}  |  salience ${memory.salience}</span><p>${h(memory.content)}</p></article>`).join("") || `<div class="empty-state">No retained memories yet.</div>`}</div></section>
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
    storyTab = button.dataset.storyTab ?? "live";
    document.querySelectorAll("[data-story-tab]").forEach((item) => item.classList.toggle("active", item === button));
    if (state) renderStory(state);
  });
}

byId("zoom-in").addEventListener("click", () => world?.zoomIn());
byId("zoom-out").addEventListener("click", () => world?.zoomOut());
byId("map-fit").addEventListener("click", () => world?.fit());
byId("dossier-close").addEventListener("click", closeDossier);
byId("archive-open").addEventListener("click", () => void openArchive());
byId("archive-close").addEventListener("click", () => { byId("archive-view").hidden = true; });
byId("roster-toggle").addEventListener("click", () => byId("resident-rail").classList.toggle("open"));
byId("story-toggle").addEventListener("click", () => byId("story-rail").classList.toggle("open"));

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closeDossier();
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
