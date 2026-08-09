import Phaser from "phaser";

import type { KrabvilleState, Point, PropertySummary, Resident } from "./types";

const WORLD_WIDTH = 4608;
const WORLD_HEIGHT = 3072;
const LEGACY_WORLD_WIDTH = 1774;
const LEGACY_WORLD_HEIGHT = 887;
const TICK_SECONDS = 12.5;
const STEP_DISTANCE = 38;
const SEASON_MAPS: Record<string, string> = {
  spring: "/assets/kvsim-town-v21-spring.webp",
  summer: "/assets/kvsim-town-v21-summer.webp",
  fall: "/assets/kvsim-town-v21-fall.webp",
  winter: "/assets/kvsim-town-v21-winter.webp",
};

const LEGACY_PRESSURE_NEEDS = new Set(["hunger", "social"]);
const NEED_BADGES: Record<string, string> = {
  energy: "EN",
  hunger: "FOOD",
  hygiene: "WASH",
  health: "HP",
  comfort: "COMF",
  safety: "SAFE",
  fun: "FUN",
  social: "SOC",
  belonging: "BEL",
  privacy: "PRIV",
  purpose: "GOAL",
  autonomy: "FREE",
  financialSecurity: "CASH",
  financial_security: "CASH",
};

const LOCATIONS: Record<string, Point> = {
  "Town Square": [866, 372], "Hobbs Cafe": [653, 381], "Lagoon Library": [335, 381],
  "Lagoon Clinic": [1109, 286], "Harbour Shelter": [1109, 286], "Radio Shack": [75, 173],
  "Harbour Office": [809, 658], Boatworks: [1444, 650], "Weather Station": [670, 277],
  "Post Office": [976, 377], "Repair Workshop": [1132, 468], Observatory: [670, 277],
  "Garden Studio": [1698, 264], "Ferry Dock": [809, 658], "Willow House": [670, 208],
  "Maple House": [924, 165], "Lantern House": [1294, 165], "Cedar House": [1444, 199],
  "Glass House": [1698, 264], "Post House": [976, 377], "Rose House": [578, 528],
  "Gear House": [335, 381], "Birch House": [1352, 338], "Pine House": [1571, 546],
  "Lotus House": [1444, 650], "Anchor House": [809, 658], "Artists' house": [335, 381],
  "Photo studio": [1698, 264], "Painting studio": [670, 208], "Animation lab": [924, 165],
  "Theatre workshop": [1444, 199], "Writing loft": [1294, 165], "Harbour apartment": [809, 658],
  "Radio engineering shack": [75, 173], "Observatory cottage": [670, 277],
  "Lagoon observatory": [670, 277], "Garden apartment": [578, 528],
  "Library and park": [335, 381], "Oak Hill dorm": [924, 165], "College library": [335, 381],
  "College and training field": [924, 234], "Lin family home": [1352, 338],
  "Oak Hill College": [1109, 286], "Moreno family home": [1444, 199], "Willow Market": [653, 381],
  "Seagrass Apartments": [364, 61], "Harbourview Co-op": [1190, 368],
  "Tideglass Towers": [1594, 212], "Cedar Quays Apartments": [1433, 576],
  "Boardwalk Row": [1536, 585], "Spruce Court": [1328, 641], "Heron House": [462, 191],
  "Lighthouse Row": [1328, 121], "Canal Childcare": [416, 95], "Tide Market": [1005, 372],
  "Lagoon Bakery": [1409, 580], "Boardwalk Restaurant": [1363, 580], "Lagoon Cinema": [901, 468],
  "Tide Theatre": [1005, 476], "Krabville Gym": [1617, 779], "Shoreline Arcade": [312, 459],
  "Northstar Electronics": [323, 727], "Harbour Hardware": [1132, 468], "Seagrass Laundry": [1502, 693],
};

interface ResidentView {
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  label: Phaser.GameObjects.Text;
  thought: Phaser.GameObjects.Text;
  needSignal: Phaser.GameObjects.Text;
  resident: Resident;
  updatedTick: number;
  decisionKey: string;
  atlas: string;
  animationKey: string;
  thoughtTimer?: Phaser.Time.TimerEvent;
}

function needSatisfaction(resident: Resident, key: string): number {
  const value = Phaser.Math.Clamp(Number(resident.needs[key] ?? 100), 0, 100);
  const modernNeeds = Object.keys(resident.needs).some((name) => !["energy", "hunger", "social", "purpose", "comfort"].includes(name));
  return resident.needsHighIsGood || modernNeeds || !LEGACY_PRESSURE_NEEDS.has(key) ? value : 100 - value;
}

function urgentNeedKeys(resident: Resident): string[] {
  const explicit = resident.pondering?.urgentNeeds ?? resident.urgentNeeds;
  if (explicit?.length) return explicit.slice(0, 2);
  return Object.keys(resident.needs)
    .map((key) => [key, needSatisfaction(resident, key)] as const)
    .filter(([, value]) => value < 32)
    .sort((left, right) => left[1] - right[1])
    .slice(0, 2)
    .map(([key]) => key);
}

function decisionKey(resident: Resident): string {
  return [resident.activity, resident.intention, resident.destinationX, resident.destinationY].join("|");
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (const character of value) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  return hash >>> 0;
}

function eventPropGroup(prop: string): number {
  const value = prop.toLowerCase();
  const semantic: Array<[RegExp, number]> = [
    [/baby|crib|bottle|child|nursery/, 17], [/arrival|move|visitor-bag|guest-bag/, 16],
    [/supper|recipe|food|picnic|table/, 18], [/market|order|shop|sale|ticket/, 19],
    [/bread|pastry|baking/, 20], [/concert|theatre|stage|dance/, 21],
    [/game|sport|training|gym/, 22], [/arcade|controller/, 23],
    [/phone|radio|signal/, 24], [/barter|exchange|swap/, 25],
    [/business|contract|construction|project/, 26], [/memorial|death|funeral/, 27],
    [/birthday|anniversary|aging/, 28], [/ferry|parcel|delivery|crate/, 29],
    [/snow|winter|leaf|autumn|fall|cold/, 30], [/storm|repair|damage|outage|fire/, 31],
  ];
  return semantic.find(([pattern]) => pattern.test(value))?.[1] ?? stableHash(value) % 32;
}

function usesMapCoordinates(state: KrabvilleState): boolean {
  return state.world?.coordinateSpace === "map" || (state.schemaVersion >= 3 && state.world?.coordinateSpace !== "legacy");
}

function projectLegacyPoint([x, y]: Point): Point {
  return [x * WORLD_WIDTH / LEGACY_WORLD_WIDTH, y * WORLD_HEIGHT / LEGACY_WORLD_HEIGHT];
}

function projectPoint(point: Point, state: KrabvilleState): Point {
  return usesMapCoordinates(state) ? point : projectLegacyPoint(point);
}

function projectedPosition(resident: Resident, state: KrabvilleState): Point {
  let x = resident.x;
  let y = resident.y;
  let remaining = STEP_DISTANCE;
  for (const point of resident.path) {
    const [targetX, targetY] = point;
    const distance = Math.hypot(targetX - x, targetY - y);
    if (distance <= remaining) {
      x = targetX;
      y = targetY;
      remaining -= distance;
      continue;
    }
    if (distance > 0) {
      x += ((targetX - x) / distance) * remaining;
      y += ((targetY - y) / distance) * remaining;
    }
    break;
  }
  return projectPoint([x, y], state);
}

type ResidentPeekHandler = (resident: Resident | null, x?: number, y?: number) => void;
type BuildingFocusHandler = (location: string) => void;

const LIFE_STAGE_ROWS: Record<string, number> = { baby: 0, child: 1, teen: 2, senior: 3 };

function spriteSpec(resident: Resident, index: number): { atlas: string; row: number; animationKey: string } {
  const lifeStage = resident.lifeStage?.toLowerCase() ?? "adult";
  const lifeRow = LIFE_STAGE_ROWS[lifeStage];
  const atlas = lifeRow === undefined ? (index < 6 ? "residents-a" : "residents-b") : "life-stages";
  const row = lifeRow ?? index % 6;
  return { atlas, row, animationKey: `walk-${resident.slug}-${atlas}-${row}` };
}

class LagoonScene extends Phaser.Scene {
  private state: KrabvilleState | null = null;
  private residents = new Map<string, ResidentView>();
  private selectedSlug: string | null = null;
  private map!: Phaser.GameObjects.Image;
  private lighting!: Phaser.GameObjects.Rectangle;
  private weatherLayer!: Phaser.GameObjects.Container;
  private seasonLayer!: Phaser.GameObjects.Container;
  private lightLayer!: Phaser.GameObjects.Container;
  private propLayer!: Phaser.GameObjects.Container;
  private buildingLayer!: Phaser.GameObjects.Container;
  private minimap!: Phaser.Cameras.Scene2D.Camera;
  private dragging = false;
  private previousPointer: Point = [0, 0];
  private currentWeather = "";
  private currentSeason = "";
  private readonly reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  constructor(
    private readonly onSelect: (slug: string) => void,
    private readonly onPeek: ResidentPeekHandler,
    private readonly onBuildingFocus: BuildingFocusHandler,
  ) {
    super("lagoon");
  }

  preload(): void {
    this.load.image("lagoon-map-spring", SEASON_MAPS.spring);
    this.load.spritesheet("residents-a", "/assets/residents-a.png", {
      frameWidth: 192,
      frameHeight: 192,
    });
    this.load.spritesheet("residents-b", "/assets/residents-b.png", {
      frameWidth: 192,
      frameHeight: 192,
    });
    this.load.spritesheet("life-stages", "/assets/life-stages-v2.png", {
      frameWidth: 192,
      frameHeight: 192,
    });
    this.load.spritesheet("interiors", "/assets/interiors-v4.png", {
      frameWidth: 256,
      frameHeight: 256,
    });
    this.load.spritesheet("event-props", "/assets/event-props-v21.png", {
      frameWidth: 128,
      frameHeight: 128,
    });
    this.load.spritesheet("weather-seasons", "/assets/weather-seasons-v1.png", {
      frameWidth: 128,
      frameHeight: 128,
    });
  }

  create(): void {
    const source = this.textures.get("lagoon-map-spring").getSourceImage() as { width: number; height: number };
    if (source.width !== WORLD_WIDTH || source.height !== WORLD_HEIGHT) {
      throw new Error(`KVsim town map must be ${WORLD_WIDTH}x${WORLD_HEIGHT}, received ${source.width}x${source.height}`);
    }
    const worldElement = document.getElementById("world");
    if (worldElement) {
      worldElement.dataset.mapAsset = SEASON_MAPS.spring;
      worldElement.dataset.worldWidth = String(WORLD_WIDTH);
      worldElement.dataset.worldHeight = String(WORLD_HEIGHT);
    }
    this.map = this.add.image(0, 0, "lagoon-map-spring").setOrigin(0).setDisplaySize(WORLD_WIDTH, WORLD_HEIGHT);
    this.textures.get("lagoon-map-spring").setFilter(Phaser.Textures.FilterMode.NEAREST);
    this.textures.get("weather-seasons").setFilter(Phaser.Textures.FilterMode.NEAREST);
    this.textures.get("event-props").setFilter(Phaser.Textures.FilterMode.NEAREST);
    this.cameras.main.setRoundPixels(true);
    this.cameras.main.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    this.propLayer = this.add.container(0, 0).setDepth(70);
    this.buildingLayer = this.add.container(0, 0).setDepth(45);
    this.seasonLayer = this.add.container(0, 0).setDepth(42);
    this.lightLayer = this.add.container(0, 0).setDepth(80);
    this.weatherLayer = this.add.container(0, 0).setDepth(90);
    this.lighting = this.add
      .rectangle(0, 0, WORLD_WIDTH, WORLD_HEIGHT, 0x06101c, 0)
      .setOrigin(0)
      .setDepth(75)
      .setBlendMode(Phaser.BlendModes.MULTIPLY);
    this.minimap = this.cameras
      .add(Math.max(8, this.scale.width - 190), Math.max(8, this.scale.height - 102), 180, 92)
      .setName("minimap")
      .setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT)
      .setZoom(Math.min(180 / WORLD_WIDTH, 92 / WORLD_HEIGHT))
      .centerOn(WORLD_WIDTH / 2, WORLD_HEIGHT / 2)
      .setBackgroundColor("rgba(3,12,18,.82)");
    this.minimap.ignore([this.weatherLayer, this.seasonLayer, this.lightLayer, this.lighting]);
    this.fillMap();
    this.bindCameraControls();
    this.scale.on("resize", () => {
      this.minimap.setViewport(
        Math.max(8, this.scale.width - 190),
        Math.max(8, this.scale.height - 102),
        180,
        92,
      );
      this.fillMap();
    });
    if (this.state) {
      this.applyState(this.state);
    }
  }

  private bindCameraControls(): void {
    this.input.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      if (pointer.event.target !== this.game.canvas) return;
      this.dragging = true;
      this.previousPointer = [pointer.x, pointer.y];
    });
    this.input.on("pointerup", () => {
      this.dragging = false;
    });
    this.input.on("pointermove", (pointer: Phaser.Input.Pointer) => {
      if (!this.dragging || !pointer.isDown || pointer.event.target !== this.game.canvas) return;
      const [oldX, oldY] = this.previousPointer;
      const camera = this.cameras.main;
      camera.scrollX -= (pointer.x - oldX) / camera.zoom;
      camera.scrollY -= (pointer.y - oldY) / camera.zoom;
      this.previousPointer = [pointer.x, pointer.y];
    });
    this.input.on(
      "wheel",
      (pointer: Phaser.Input.Pointer, _objects: unknown[], _dx: number, dy: number) => {
        if (pointer.event.target !== this.game.canvas) return;
        this.setZoom(this.cameras.main.zoom * (dy > 0 ? 0.9 : 1.1));
      },
    );
  }

  private ensureWalkAnimation(atlas: string, row: number, animationKey: string): void {
    if (!this.anims.exists(animationKey)) {
      this.anims.create({
        key: animationKey,
        frames: this.anims.generateFrameNumbers(atlas, { start: row * 4, end: row * 4 + 3 }),
        frameRate: 6,
        repeat: -1,
      });
    }
  }

  private createResident(resident: Resident, index: number, state: KrabvilleState): ResidentView {
    const { atlas, row, animationKey } = spriteSpec(resident, index);
    this.ensureWalkAnimation(atlas, row, animationKey);
    const ring = this.add.circle(0, 24, 25, Phaser.Display.Color.HexStringToColor(resident.color).color, 0.28);
    ring.setStrokeStyle(2, 0xffffff, 0.7);
    const sprite = this.add.sprite(0, 0, atlas, row * 4).setDisplaySize(62, 62).setInteractive({ useHandCursor: true });
    const label = this.add
      .text(0, 35, resident.name.split(" ")[0] ?? resident.name, {
        fontFamily: "Inter, Segoe UI, sans-serif",
        fontSize: "12px",
        color: "#ffffff",
        backgroundColor: "rgba(4,13,18,.82)",
        padding: { x: 5, y: 2 },
      })
      .setOrigin(0.5, 0);
    const thought = this.add
      .text(0, -52, "", {
        fontFamily: "Inter, Segoe UI, sans-serif",
        fontSize: "13px",
        color: "#effbff",
        backgroundColor: "rgba(5,18,24,.93)",
        padding: { x: 8, y: 6 },
        wordWrap: { width: 190 },
        align: "center",
      })
      .setOrigin(0.5, 1)
      .setAlpha(0)
      .setVisible(false);
    const needSignal = this.add
      .text(0, -39, "", {
        fontFamily: "Inter, Segoe UI, sans-serif",
        fontSize: "9px",
        fontStyle: "bold",
        color: "#fff7eb",
        backgroundColor: "rgba(177,49,58,.94)",
        padding: { x: 5, y: 3 },
      })
      .setOrigin(0.5, 1)
      .setVisible(false);
    const [x, y] = projectPoint([resident.x, resident.y], state);
    const container = this.add.container(x, y, [ring, sprite, label, needSignal, thought]).setDepth(50 + y / WORLD_HEIGHT);
    const showPeek = (pointer: Phaser.Input.Pointer) => {
      this.onPeek(this.residents.get(resident.slug)?.resident ?? resident, pointer.x, pointer.y);
    };
    sprite.on("pointerover", showPeek);
    sprite.on("pointermove", showPeek);
    sprite.on("pointerout", () => this.onPeek(null));
    sprite.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      if (pointer.event.target !== this.game.canvas) return;
      pointer.event.stopPropagation();
      this.onPeek(null);
      this.selectResident(resident.slug);
      this.onSelect(resident.slug);
    });
    return {
      container,
      sprite,
      label,
      thought,
      needSignal,
      resident,
      updatedTick: resident.updatedTick,
      decisionKey: decisionKey(resident),
      atlas,
      animationKey,
    };
  }

  private showThought(view: ResidentView, text: string): void {
    if (!text.trim()) return;
    view.thoughtTimer?.remove(false);
    view.thought.setText(text).setVisible(true).setAlpha(1);
    document.getElementById("world")?.setAttribute("aria-label", `${view.resident.name} is pondering: ${text}`);
    view.thoughtTimer = this.time.delayedCall(6000, () => {
      if (this.reducedMotion) {
        view.thought.setVisible(false);
        return;
      }
      this.tweens.add({
        targets: view.thought,
        alpha: 0,
        duration: 280,
        onComplete: () => view.thought.setVisible(false),
      });
    });
  }

  applyState(state: KrabvilleState): void {
    this.state = state;
    if (!this.sys.isActive()) return;
    const projectedPoints = state.residents.flatMap((resident) => [
      projectPoint([resident.x, resident.y], state),
      ...resident.path.map((point) => projectPoint(point, state)),
    ]);
    const worldElement = document.getElementById("world");
    if (worldElement) {
      worldElement.dataset.coordinateSpace = usesMapCoordinates(state) ? "map" : "projected-legacy";
      worldElement.dataset.pathsInBounds = String(projectedPoints.every(([x, y]) => x >= 0 && x <= WORLD_WIDTH && y >= 0 && y <= WORLD_HEIGHT));
    }
    const active = new Set<string>();
    state.residents.forEach((resident, index) => {
      active.add(resident.slug);
      let view = this.residents.get(resident.slug);
      if (!view) {
        view = this.createResident(resident, index, state);
        this.residents.set(resident.slug, view);
      }
      const spec = spriteSpec(resident, index);
      if (view.atlas !== spec.atlas || view.animationKey !== spec.animationKey) {
        this.ensureWalkAnimation(spec.atlas, spec.row, spec.animationKey);
        view.sprite.setTexture(spec.atlas, spec.row * 4);
        view.atlas = spec.atlas;
        view.animationKey = spec.animationKey;
      }
      const nextDecisionKey = decisionKey(resident);
      const changedDecision = view.decisionKey !== nextDecisionKey;
      view.resident = resident;
      view.decisionKey = nextDecisionKey;
      view.label.setText(resident.name.split(" ")[0] ?? resident.name);
      const urgent = urgentNeedKeys(resident);
      view.needSignal.setText(urgent.map((key) => NEED_BADGES[key] ?? key.slice(0, 4).toUpperCase()).join(" + "));
      view.needSignal.setVisible(urgent.length > 0);
      view.container.setVisible(!resident.indoors);
      if (resident.pondering?.active || changedDecision) {
        this.showThought(view, resident.pondering?.thought || resident.publicThought || resident.intention);
      }
      if (resident.indoors) {
        view.sprite.stop();
        view.container.setPosition(...projectPoint([resident.x, resident.y], state));
        view.updatedTick = resident.updatedTick;
        return;
      }
      if (view.updatedTick === resident.updatedTick) return;
      view.updatedTick = resident.updatedTick;
      this.tweens.killTweensOf(view.container);
      const [currentX, currentY] = projectPoint([resident.x, resident.y], state);
      if (Math.hypot(view.container.x - currentX, view.container.y - currentY) > 180) {
        view.container.setPosition(currentX, currentY);
      }
      const [targetX, targetY] = projectedPosition(resident, state);
      const moving = resident.path.length > 0 && Math.hypot(targetX - currentX, targetY - currentY) > 1;
      view.container.setDepth(50 + targetY / WORLD_HEIGHT);
      if (moving && !this.reducedMotion) {
        view.sprite.play(view.animationKey, true);
        view.sprite.setFlipX(targetX < currentX);
        this.tweens.add({
          targets: view.container,
          x: targetX,
          y: targetY,
          duration: TICK_SECONDS * 1000,
          delay: changedDecision && !this.reducedMotion ? 850 : 0,
          ease: "Linear",
        });
      } else {
        view.sprite.stop();
        view.container.setPosition(currentX, currentY);
      }
    });
    for (const [slug, view] of this.residents) {
      if (!active.has(slug)) {
        view.container.destroy(true);
        this.residents.delete(slug);
      }
    }
    this.updateLighting(state);
    this.updateWeather(state.season?.weather ?? {}, state.season?.number ?? 1);
    this.updateProps(state);
    this.updateBuildings(state);
    this.updateObjectScale();
  }

  private updateBuildings(state: KrabvilleState): void {
    this.buildingLayer.removeAll(true);
    const buildings: PropertySummary[] = state.buildings?.length
      ? state.buildings.filter((building) => building.interiorAvailable || building.x !== undefined)
      : ["Hobbs Cafe", "Lagoon Library", "Lagoon Clinic", "Radio Shack", "Harbour Office"].map((name) => ({ name, interiorAvailable: true }));
    for (const building of buildings.slice(0, 72)) {
      const point = building.x !== undefined && building.y !== undefined
        ? projectPoint([building.x, building.y], state)
        : this.locationPoint(building.name, state);
      if (!point) continue;
      const marker = this.add.circle(0, 0, 7, 0x63d8e3, 0.8).setStrokeStyle(2, 0xe8fbff, 0.9).setInteractive({ useHandCursor: true });
      const inside = building.inside ?? [];
      const label = this.add.text(0, -13, building.interiorAvailable ? `${building.name}  |  ${inside.length} INSIDE` : building.name, {
        fontFamily: "Inter, Segoe UI, sans-serif",
        fontSize: "10px",
        color: "#eafcff",
        backgroundColor: "rgba(4,15,20,.92)",
        padding: { x: 5, y: 3 },
      }).setOrigin(0.5, 1).setVisible(false);
      marker.on("pointerover", () => label.setVisible(true));
      marker.on("pointerout", () => label.setVisible(false));
      marker.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
        if (pointer.event.target !== this.game.canvas) return;
        pointer.event.stopPropagation();
        this.focusLocation(building.name, point);
        this.onBuildingFocus(building.name);
      });
      const occupants: Phaser.GameObjects.GameObject[] = [];
      inside.slice(0, 5).forEach((occupant, index) => {
        const resident = state.residents.find((item) => item.slug === occupant.slug);
        const x = (index - (Math.min(inside.length, 5) - 1) / 2) * 18;
        const badge = this.add.circle(x, -24, 9, resident ? Phaser.Display.Color.HexStringToColor(resident.color).color : 0x63d8e3, 0.96);
        badge.setStrokeStyle(2, 0xf4fdff, 0.9);
        const initial = this.add.text(x, -24, occupant.name.slice(0, 1), {
          fontFamily: "Inter, Segoe UI, sans-serif", fontSize: "9px", fontStyle: "bold", color: "#071116",
        }).setOrigin(0.5);
        occupants.push(badge, initial);
      });
      this.buildingLayer.add(this.add.container(point[0], point[1] - 14, [marker, label, ...occupants]));
    }
  }

  private locationPoint(location: string, state = this.state): Point | undefined {
    const building = state?.buildings?.find((item) => item.name === location || item.mapLocation === location);
    if (state && building?.x !== undefined && building.y !== undefined) return projectPoint([building.x, building.y], state);
    const legacy = LOCATIONS[location];
    return legacy ? projectLegacyPoint(legacy) : undefined;
  }

  private updateLighting(state: KrabvilleState): void {
    const minutes = state.season?.worldMinutes ?? 720;
    let darkness = 0;
    if (minutes < 330 || minutes > 1260) darkness = 0.52;
    else if (minutes < 450) darkness = 0.52 * (450 - minutes) / 120;
    else if (minutes > 1080) darkness = 0.52 * (minutes - 1080) / 180;
    this.lighting.setFillStyle(minutes > 1080 && minutes < 1260 ? 0x21122b : 0x06101c, darkness);
    this.lightLayer.removeAll(true);
    if (darkness < 0.12) return;
    const occupied = new Set(state.residents.map((resident) => resident.location));
    for (const location of occupied) {
      const point = this.locationPoint(location, state);
      if (!point) continue;
      const glow = this.add.circle(point[0], point[1] - 18, 20, 0xffc85f, Math.min(0.62, darkness + 0.12));
      glow.setBlendMode(Phaser.BlendModes.ADD);
      this.lightLayer.add(glow);
      if (!this.reducedMotion) {
        this.tweens.add({ targets: glow, alpha: 0.22, duration: 1200, yoyo: true, repeat: -1 });
      }
    }
  }

  private clearLayer(layer: Phaser.GameObjects.Container): void {
    this.tweens.killTweensOf(layer.list);
    layer.removeAll(true);
  }

  private updateSeason(season: string): void {
    if (season === this.currentSeason) return;
    this.currentSeason = season;
    this.clearLayer(this.seasonLayer);
    this.swapSeasonMap(season);
    const settings: Record<string, { frames: number[]; count: number; alpha: number }> = {
      spring: { frames: [53, 63], count: 38, alpha: 0.76 },
      summer: { frames: [33, 34, 39], count: 18, alpha: 0.38 },
      fall: { frames: [16, 18, 20, 52, 58], count: 52, alpha: 0.78 },
      winter: { frames: [48, 49, 54, 59, 62], count: 58, alpha: 0.82 },
    };
    const setting = settings[season] ?? settings.summer!;
    for (let index = 0; index < setting.count; index += 1) {
      const x = (113 + index * 619) % WORLD_WIDTH;
      const y = (71 + index * 353) % WORLD_HEIGHT;
      const sprite = this.add.sprite(x, y, "weather-seasons", setting.frames[index % setting.frames.length])
        .setScale(0.24 + (index % 4) * 0.035)
        .setAlpha(setting.alpha)
        .setRotation(((index % 7) - 3) * 0.08);
      this.seasonLayer.add(sprite);
    }
    const worldElement = document.getElementById("world");
    if (worldElement) worldElement.dataset.season = season;
  }

  private swapSeasonMap(season: string): void {
    const normalized = SEASON_MAPS[season] ? season : "summer";
    const key = `lagoon-map-${normalized}`;
    const path = SEASON_MAPS[normalized]!;
    const apply = () => {
      this.textures.get(key).setFilter(Phaser.Textures.FilterMode.NEAREST);
      this.map.setTexture(key).setDisplaySize(WORLD_WIDTH, WORLD_HEIGHT);
      const worldElement = document.getElementById("world");
      if (worldElement) worldElement.dataset.mapAsset = path;
    };
    if (this.textures.exists(key)) {
      apply();
      return;
    }
    this.load.image(key, path);
    this.load.once(Phaser.Loader.Events.COMPLETE, apply);
    this.load.start();
  }

  private updateWeather(weather: { condition?: string; season?: string }, seasonNumber: number): void {
    const condition = String(weather.condition ?? "clear").toLowerCase();
    const season = String(
      weather.season ?? ["spring", "summer", "fall", "winter"][Math.min(3, Math.max(0, Math.floor((seasonNumber - 1) / 5)))] ?? "spring",
    ).toLowerCase();
    this.updateSeason(season);
    const weatherKey = `${season}:${condition}`;
    if (weatherKey === this.currentWeather) return;
    this.currentWeather = weatherKey;
    this.clearLayer(this.weatherLayer);
    const worldElement = document.getElementById("world");
    if (worldElement) worldElement.dataset.weather = condition;
    if (condition === "clear") {
      const count = this.reducedMotion ? 5 : 16;
      for (let index = 0; index < count; index += 1) {
        const glint = this.add.sprite((index * 733) % WORLD_WIDTH, (index * 419) % WORLD_HEIGHT, "weather-seasons", 33 + index % 7).setScale(0.2).setAlpha(0.34);
        this.weatherLayer.add(glint);
        if (!this.reducedMotion) this.tweens.add({ targets: glint, alpha: 0.08, scale: 0.28, duration: 1600 + index * 37, yoyo: true, repeat: -1 });
      }
      return;
    }
    if (condition === "fog" || condition === "cloudy") {
      const veil = this.add.rectangle(0, 0, WORLD_WIDTH, WORLD_HEIGHT, 0xd9f3f2, condition === "fog" ? 0.18 : 0.08).setOrigin(0);
      this.weatherLayer.add(veil);
      const count = this.reducedMotion ? 8 : 24;
      for (let index = 0; index < count; index += 1) {
        const cloud = this.add.sprite((index * 509) % WORLD_WIDTH, (index * 277) % WORLD_HEIGHT, "weather-seasons", 40 + index % 5).setScale(0.45 + index % 3 * 0.12).setAlpha(condition === "fog" ? 0.28 : 0.18);
        this.weatherLayer.add(cloud);
        if (!this.reducedMotion) this.tweens.add({ targets: cloud, x: cloud.x + 320, duration: 12000 + index * 180, repeat: -1, yoyo: true });
      }
      return;
    }
    if (condition === "rain" || condition === "storm") {
      const count = this.reducedMotion ? 16 : 62;
      for (let index = 0; index < count; index += 1) {
        const drop = this.add.sprite((index * 347) % WORLD_WIDTH, -80 + (index * 193) % (WORLD_HEIGHT + 80), "weather-seasons", index % 8).setScale(0.16 + index % 3 * 0.04).setAlpha(condition === "storm" ? 0.74 : 0.52).setRotation(-0.18);
        this.weatherLayer.add(drop);
        if (!this.reducedMotion) this.tweens.add({ targets: drop, x: drop.x - 260, y: WORLD_HEIGHT + 120, duration: 1450 + index % 9 * 95, repeat: -1, delay: index * 31 });
      }
      if (condition === "storm") {
        const flash = this.add.sprite(WORLD_WIDTH * 0.62, WORLD_HEIGHT * 0.28, "weather-seasons", 24).setScale(1.6).setAlpha(this.reducedMotion ? 0.5 : 0);
        this.weatherLayer.add(flash);
        if (!this.reducedMotion) this.tweens.add({ targets: flash, alpha: { from: 0, to: 0.82 }, duration: 90, hold: 80, yoyo: true, repeat: -1, repeatDelay: 3400 });
      }
      return;
    }
    if (condition === "snow" || condition === "first-snow") {
      const count = this.reducedMotion ? 14 : 54;
      for (let index = 0; index < count; index += 1) {
        const flake = this.add.sprite((index * 401) % WORLD_WIDTH, -60 + (index * 227) % (WORLD_HEIGHT + 60), "weather-seasons", 8 + index % 6).setScale(0.13 + index % 4 * 0.035).setAlpha(0.78);
        this.weatherLayer.add(flake);
        if (!this.reducedMotion) this.tweens.add({ targets: flake, x: flake.x + (index % 2 ? 150 : -150), y: WORLD_HEIGHT + 100, rotation: Math.PI * 2, duration: 4300 + index % 8 * 260, repeat: -1, delay: index * 43 });
      }
      return;
    }
    if (condition === "windy") {
      const frames = season === "fall" ? [16, 17, 18, 19, 20, 21, 22, 23] : [43, 44, 45, 46];
      const count = this.reducedMotion ? 10 : 34;
      for (let index = 0; index < count; index += 1) {
        const gust = this.add.sprite(-80 + (index * 431) % (WORLD_WIDTH + 80), (index * 271) % WORLD_HEIGHT, "weather-seasons", frames[index % frames.length]).setScale(0.18 + index % 3 * 0.05).setAlpha(0.66);
        this.weatherLayer.add(gust);
        if (!this.reducedMotion) this.tweens.add({ targets: gust, x: WORLD_WIDTH + 100, y: gust.y + (index % 2 ? 90 : -90), rotation: index % 2 ? 1.2 : -1.2, duration: 3200 + index % 7 * 240, repeat: -1, delay: index * 47 });
      }
    }
  }

  private updateProps(state: KrabvilleState): void {
    this.propLayer.removeAll(true);
    for (const prop of state.props) {
      const point = this.locationPoint(prop.location, state) ?? this.locationPoint("Town Square", state);
      if (!point) continue;
      const group = eventPropGroup(prop.prop);
      const atlasRow = Math.floor(group / 2);
      const firstFrame = atlasRow * 8 + (group % 2) * 4;
      const animationKey = `event-prop-${group}`;
      if (!this.anims.exists(animationKey)) {
        this.anims.create({
          key: animationKey,
          frames: this.anims.generateFrameNumbers("event-props", { start: firstFrame, end: firstFrame + 3 }),
          frameRate: 3,
          repeat: -1,
        });
      }
      const marker = this.add.sprite(0, 0, "event-props", firstFrame).setScale(0.42);
      if (!this.reducedMotion) marker.play(animationKey);
      const label = this.add
        .text(0, -31, prop.prop.replaceAll("-", " "), {
          fontFamily: "Inter, Segoe UI, sans-serif",
          fontSize: "11px",
          color: "#fff7d6",
          backgroundColor: "rgba(6,18,23,.86)",
          padding: { x: 4, y: 2 },
        })
        .setOrigin(0.5, 1);
      const container = this.add.container(point[0] + 24, point[1], [marker, label]);
      this.propLayer.add(container);
    }
  }

  selectResident(slug: string | null): void {
    this.selectedSlug = slug;
    for (const [residentSlug, view] of this.residents) {
      if (residentSlug === slug && !view.thought.visible) this.showThought(view, view.resident.publicThought || view.resident.intention);
    }
    if (slug) {
      const view = this.residents.get(slug);
      if (view) this.cameras.main.pan(view.container.x, view.container.y, this.reducedMotion ? 0 : 450, "Sine.easeInOut");
    }
  }

  private minimumZoom(): number {
    return Math.max(0.12, Math.min(this.scale.width / WORLD_WIDTH, this.scale.height / WORLD_HEIGHT));
  }

  private updateObjectScale(): void {
    const scale = Phaser.Math.Clamp(0.9 / this.cameras.main.zoom, 0.78, 3.1);
    for (const view of this.residents.values()) view.container.setScale(scale);
    for (const child of [...this.buildingLayer.list, ...this.propLayer.list]) {
      if (child instanceof Phaser.GameObjects.Container) child.setScale(scale);
    }
  }

  focusLocation(location: string, explicitPoint?: Point): void {
    const point = explicitPoint ?? this.locationPoint(location);
    if (!point) return;
    this.setZoom(Math.max(this.cameras.main.zoom, 1.05));
    this.cameras.main.pan(point[0], point[1], this.reducedMotion ? 0 : 500, "Sine.easeInOut");
    const element = document.getElementById("world");
    if (element) element.dataset.focusedLocation = location;
  }

  setZoom(value: number): void {
    this.cameras.main.setZoom(Phaser.Math.Clamp(value, this.minimumZoom(), 2.5));
    const element = document.getElementById("world");
    if (element) element.dataset.cameraZoom = this.cameras.main.zoom.toFixed(4);
    this.updateObjectScale();
  }

  zoomBy(factor: number): void {
    this.setZoom(this.cameras.main.zoom * factor);
  }

  fitMap(): void {
    this.fillMap();
  }

  private fillMap(): void {
    const zoom = Math.max(this.scale.width / WORLD_WIDTH, this.scale.height / WORLD_HEIGHT);
    this.cameras.main.setZoom(Phaser.Math.Clamp(zoom, this.minimumZoom(), 1.15)).centerOn(WORLD_WIDTH / 2, WORLD_HEIGHT / 2);
    const element = document.getElementById("world");
    if (element) element.dataset.cameraZoom = this.cameras.main.zoom.toFixed(4);
    this.updateObjectScale();
  }
}

export class LagoonWorld {
  private readonly scene: LagoonScene;
  private readonly game: Phaser.Game;

  constructor(parent: string, onSelect: (slug: string) => void, onPeek: ResidentPeekHandler, onBuildingFocus: BuildingFocusHandler) {
    this.scene = new LagoonScene(onSelect, onPeek, onBuildingFocus);
    const element = document.getElementById(parent);
    if (!element) throw new Error("map parent missing");
    this.game = new Phaser.Game({
      type: Phaser.CANVAS,
      parent,
      width: Math.max(320, element.clientWidth),
      height: Math.max(280, element.clientHeight),
      backgroundColor: "#07151b",
      pixelArt: true,
      roundPixels: true,
      render: { antialias: false, pixelArt: true, roundPixels: true },
      scale: { mode: Phaser.Scale.NONE, autoCenter: Phaser.Scale.CENTER_BOTH },
      scene: this.scene,
    });
    const observer = new ResizeObserver(() => {
      const width = Math.max(320, element.clientWidth);
      const height = Math.max(280, element.clientHeight);
      this.game.scale.resize(width, height);
    });
    observer.observe(element);
  }

  update(state: KrabvilleState): void {
    this.scene.applyState(state);
  }

  select(slug: string | null): void {
    this.scene.selectResident(slug);
  }

  zoomIn(): void {
    this.scene.zoomBy(1.16);
  }

  zoomOut(): void {
    this.scene.zoomBy(0.86);
  }

  fit(): void {
    this.scene.fitMap();
  }

  focus(location: string): void {
    this.scene.focusLocation(location);
  }
}
