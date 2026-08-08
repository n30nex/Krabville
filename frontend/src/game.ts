import Phaser from "phaser";

import type { KrabvilleState, Point, Resident } from "./types";

const WORLD_WIDTH = 1774;
const WORLD_HEIGHT = 887;
const TICK_SECONDS = 12.5;
const STEP_DISTANCE = 38;

const LOCATIONS: Record<string, Point> = {
  "Town Square": [885, 430],
  "Hobbs Cafe": [454, 451],
  "Lagoon Library": [536, 653],
  "Lagoon Clinic": [1105, 470],
  "Radio Shack": [150, 386],
  "Harbour Office": [850, 795],
  Boatworks: [1455, 786],
  "Weather Station": [362, 180],
  "Post Office": [648, 462],
  "Repair Workshop": [1588, 580],
  Observatory: [362, 180],
  "Garden Studio": [1328, 216],
  "Ferry Dock": [850, 795],
  "Willow House": [600, 250],
  "Maple House": [806, 250],
  "Lantern House": [1085, 260],
  "Cedar House": [1580, 315],
  "Glass House": [1328, 216],
  "Post House": [648, 462],
  "Rose House": [165, 600],
  "Gear House": [536, 653],
  "Birch House": [1370, 466],
  "Pine House": [1290, 754],
  "Lotus House": [1455, 786],
  "Anchor House": [850, 795],
  "Artists' house": [536, 653],
  "Photo studio": [1328, 216],
  "Painting studio": [600, 250],
  "Animation lab": [806, 250],
  "Theatre workshop": [1580, 315],
  "Writing loft": [1085, 260],
  "Harbour apartment": [850, 795],
  "Radio engineering shack": [150, 386],
  "Observatory cottage": [362, 180],
  "Lagoon observatory": [362, 180],
  "Garden apartment": [165, 600],
  "Library and park": [536, 653],
  "Oak Hill dorm": [806, 250],
  "College library": [536, 653],
  "College and training field": [820, 300],
  "Lin family home": [1370, 466],
  "Oak Hill College": [1105, 470],
  "Moreno family home": [1580, 315],
  "Willow Market": [454, 451],
};

interface ResidentView {
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  label: Phaser.GameObjects.Text;
  thought: Phaser.GameObjects.Text;
  resident: Resident;
  updatedTick: number;
}

function projectedPosition(resident: Resident): Point {
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
  return [x, y];
}

type ResidentPeekHandler = (resident: Resident | null, x?: number, y?: number) => void;

class LagoonScene extends Phaser.Scene {
  private state: KrabvilleState | null = null;
  private residents = new Map<string, ResidentView>();
  private selectedSlug: string | null = null;
  private lighting!: Phaser.GameObjects.Rectangle;
  private weatherLayer!: Phaser.GameObjects.Container;
  private lightLayer!: Phaser.GameObjects.Container;
  private propLayer!: Phaser.GameObjects.Container;
  private minimap!: Phaser.Cameras.Scene2D.Camera;
  private dragging = false;
  private previousPointer: Point = [0, 0];
  private currentWeather = "";
  private readonly reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  constructor(
    private readonly onSelect: (slug: string) => void,
    private readonly onPeek: ResidentPeekHandler,
  ) {
    super("lagoon");
  }

  preload(): void {
    this.load.image("lagoon-map", "/assets/krabville-map.webp");
    this.load.spritesheet("residents-a", "/assets/residents-a.png", {
      frameWidth: 192,
      frameHeight: 192,
    });
    this.load.spritesheet("residents-b", "/assets/residents-b.png", {
      frameWidth: 192,
      frameHeight: 192,
    });
  }

  create(): void {
    this.add.image(0, 0, "lagoon-map").setOrigin(0).setDisplaySize(WORLD_WIDTH, WORLD_HEIGHT);
    this.cameras.main.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    this.propLayer = this.add.container(0, 0).setDepth(70);
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
      .setZoom(0.1)
      .centerOn(WORLD_WIDTH / 2, WORLD_HEIGHT / 2)
      .setBackgroundColor("rgba(3,12,18,.82)");
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
      this.dragging = true;
      this.previousPointer = [pointer.x, pointer.y];
    });
    this.input.on("pointerup", () => {
      this.dragging = false;
    });
    this.input.on("pointermove", (pointer: Phaser.Input.Pointer) => {
      if (!this.dragging || !pointer.isDown) return;
      const [oldX, oldY] = this.previousPointer;
      const camera = this.cameras.main;
      camera.scrollX -= (pointer.x - oldX) / camera.zoom;
      camera.scrollY -= (pointer.y - oldY) / camera.zoom;
      this.previousPointer = [pointer.x, pointer.y];
    });
    this.input.on(
      "wheel",
      (_pointer: Phaser.Input.Pointer, _objects: unknown[], _dx: number, dy: number) => {
        this.setZoom(this.cameras.main.zoom * (dy > 0 ? 0.9 : 1.1));
      },
    );
  }

  private createResident(resident: Resident, index: number): ResidentView {
    const atlas = index < 6 ? "residents-a" : "residents-b";
    const row = index % 6;
    const animationKey = `walk-${resident.slug}`;
    if (!this.anims.exists(animationKey)) {
      this.anims.create({
        key: animationKey,
        frames: this.anims.generateFrameNumbers(atlas, { start: row * 4, end: row * 4 + 3 }),
        frameRate: 6,
        repeat: -1,
      });
    }
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
      .setVisible(false);
    const container = this.add.container(resident.x, resident.y, [ring, sprite, label, thought]).setDepth(50 + resident.y / 1000);
    const showPeek = (pointer: Phaser.Input.Pointer) => {
      this.onPeek(this.residents.get(resident.slug)?.resident ?? resident, pointer.x, pointer.y);
    };
    sprite.on("pointerover", showPeek);
    sprite.on("pointermove", showPeek);
    sprite.on("pointerout", () => this.onPeek(null));
    sprite.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      pointer.event.stopPropagation();
      this.onPeek(null);
      this.selectResident(resident.slug);
      this.onSelect(resident.slug);
    });
    return { container, sprite, label, thought, resident, updatedTick: resident.updatedTick - 1 };
  }

  applyState(state: KrabvilleState): void {
    this.state = state;
    if (!this.sys.isActive()) return;
    const active = new Set<string>();
    state.residents.forEach((resident, index) => {
      active.add(resident.slug);
      let view = this.residents.get(resident.slug);
      if (!view) {
        view = this.createResident(resident, index);
        this.residents.set(resident.slug, view);
      }
      view.resident = resident;
      view.label.setText(resident.name.split(" ")[0] ?? resident.name);
      view.thought.setText(resident.publicThought);
      view.thought.setVisible(this.selectedSlug === resident.slug);
      if (view.updatedTick === resident.updatedTick) return;
      view.updatedTick = resident.updatedTick;
      this.tweens.killTweensOf(view.container);
      if (Math.hypot(view.container.x - resident.x, view.container.y - resident.y) > STEP_DISTANCE * 2) {
        view.container.setPosition(resident.x, resident.y);
      }
      const [targetX, targetY] = projectedPosition(resident);
      const moving = resident.path.length > 0 && Math.hypot(targetX - resident.x, targetY - resident.y) > 1;
      view.container.setDepth(50 + targetY / 1000);
      if (moving && !this.reducedMotion) {
        view.sprite.play(`walk-${resident.slug}`, true);
        view.sprite.setFlipX(targetX < resident.x);
        this.tweens.add({
          targets: view.container,
          x: targetX,
          y: targetY,
          duration: TICK_SECONDS * 1000,
          ease: "Linear",
        });
      } else {
        view.sprite.stop();
        view.container.setPosition(resident.x, resident.y);
      }
    });
    for (const [slug, view] of this.residents) {
      if (!active.has(slug)) {
        view.container.destroy(true);
        this.residents.delete(slug);
      }
    }
    this.updateLighting(state);
    this.updateWeather(state.season?.weather.condition ?? "clear");
    this.updateProps(state);
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
      const point = LOCATIONS[location];
      if (!point) continue;
      const glow = this.add.circle(point[0], point[1] - 18, 20, 0xffc85f, Math.min(0.62, darkness + 0.12));
      glow.setBlendMode(Phaser.BlendModes.ADD);
      this.lightLayer.add(glow);
      if (!this.reducedMotion) {
        this.tweens.add({ targets: glow, alpha: 0.22, duration: 1200, yoyo: true, repeat: -1 });
      }
    }
  }

  private updateWeather(condition: string): void {
    if (condition === this.currentWeather) return;
    this.currentWeather = condition;
    this.weatherLayer.removeAll(true);
    if (condition === "fog") {
      this.weatherLayer.add(this.add.rectangle(0, 0, WORLD_WIDTH, WORLD_HEIGHT, 0xd9f3f2, 0.22).setOrigin(0));
      return;
    }
    if (!condition.includes("rain") && condition !== "storm") return;
    const count = this.reducedMotion ? 20 : 70;
    for (let index = 0; index < count; index += 1) {
      const x = Phaser.Math.Between(0, WORLD_WIDTH);
      const y = Phaser.Math.Between(-100, WORLD_HEIGHT);
      const drop = this.add.rectangle(x, y, 2, 18, 0x9edfff, condition === "storm" ? 0.62 : 0.42).setRotation(-0.22);
      this.weatherLayer.add(drop);
      if (!this.reducedMotion) {
        this.tweens.add({
          targets: drop,
          x: x - 180,
          y: WORLD_HEIGHT + 100,
          duration: Phaser.Math.Between(1200, 2100),
          repeat: -1,
          delay: Phaser.Math.Between(0, 1400),
        });
      }
    }
  }

  private updateProps(state: KrabvilleState): void {
    this.propLayer.removeAll(true);
    for (const prop of state.props) {
      const point = LOCATIONS[prop.location] ?? LOCATIONS["Town Square"];
      if (!point) continue;
      const marker = this.add.rectangle(0, 0, 13, 13, 0xffc857, 0.92).setRotation(Math.PI / 4);
      marker.setStrokeStyle(2, 0x17323c, 1);
      const label = this.add
        .text(0, -14, prop.prop.replaceAll("-", " "), {
          fontFamily: "Inter, Segoe UI, sans-serif",
          fontSize: "11px",
          color: "#fff7d6",
          backgroundColor: "rgba(6,18,23,.86)",
          padding: { x: 4, y: 2 },
        })
        .setOrigin(0.5, 1);
      const container = this.add.container(point[0] + 24, point[1], [marker, label]);
      this.propLayer.add(container);
      if (!this.reducedMotion) {
        this.tweens.add({ targets: marker, scale: 1.25, duration: 900, yoyo: true, repeat: -1 });
      }
    }
  }

  selectResident(slug: string | null): void {
    this.selectedSlug = slug;
    for (const [residentSlug, view] of this.residents) {
      view.thought.setVisible(residentSlug === slug);
    }
    if (slug) {
      const view = this.residents.get(slug);
      if (view) this.cameras.main.pan(view.container.x, view.container.y, this.reducedMotion ? 0 : 450, "Sine.easeInOut");
    }
  }

  setZoom(value: number): void {
    this.cameras.main.setZoom(Phaser.Math.Clamp(value, 0.42, 1.65));
  }

  zoomBy(factor: number): void {
    this.setZoom(this.cameras.main.zoom * factor);
  }

  fitMap(): void {
    const zoom = Math.min(this.scale.width / WORLD_WIDTH, this.scale.height / WORLD_HEIGHT);
    this.cameras.main.setZoom(Phaser.Math.Clamp(zoom, 0.42, 1.15)).centerOn(WORLD_WIDTH / 2, WORLD_HEIGHT / 2);
  }

  private fillMap(): void {
    const zoom = Math.max(this.scale.width / WORLD_WIDTH, this.scale.height / WORLD_HEIGHT);
    this.cameras.main.setZoom(Phaser.Math.Clamp(zoom, 0.42, 1.15)).centerOn(WORLD_WIDTH / 2, WORLD_HEIGHT / 2);
  }
}

export class LagoonWorld {
  private readonly scene: LagoonScene;
  private readonly game: Phaser.Game;

  constructor(parent: string, onSelect: (slug: string) => void, onPeek: ResidentPeekHandler) {
    this.scene = new LagoonScene(onSelect, onPeek);
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
}
