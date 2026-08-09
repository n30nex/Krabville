import { expect, test } from "@playwright/test";

import eventFixture from "../../tests/fixtures/contracts/public-event-v1.json" with { type: "json" };
import registryFixture from "../../tests/fixtures/contracts/public-event-registry-v1.json" with { type: "json" };
import {
  PUBLIC_EVENT_KINDS,
  eventSubscriptionKinds,
  parsePublicEvent,
} from "../src/events";


test.beforeEach(({}, testInfo) => {
  test.skip(testInfo.project.name !== "1366x768", "contract tests run once");
});

test("public event registry and canonical envelope match the golden fixtures", () => {
  expect(PUBLIC_EVENT_KINDS).toEqual(registryFixture.eventKinds);
  expect(parsePublicEvent(JSON.stringify(eventFixture), "decision", "9001")).toEqual(eventFixture);
});

test("legacy SSE data normalizes to v1", () => {
  const legacy = {
    tick: eventFixture.tick,
    payload: eventFixture.payload,
    createdAt: eventFixture.createdAt,
  };

  expect(parsePublicEvent(JSON.stringify(legacy), "decision", "9001")).toEqual({
    ...eventFixture,
    seasonId: null,
  });
});

test("an advertised unknown event is logged and ignored", () => {
  const warnings: string[] = [];
  const originalWarn = console.warn;
  console.warn = (...values: unknown[]) => warnings.push(values.map(String).join(" "));
  try {
    expect(eventSubscriptionKinds(["future_event"])).toContain("future_event");
    expect(parsePublicEvent(
      JSON.stringify({ ...eventFixture, type: "future_event" }),
      "future_event",
      "9001",
    )).toBeNull();
  } finally {
    console.warn = originalWarn;
  }
  expect(warnings).toEqual([
    "[Krabville events] Ignoring unknown event type \"future_event\".",
  ]);
});
