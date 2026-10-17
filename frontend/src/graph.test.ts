import { describe, it, expect } from "vitest";
import { validConnection, parseGraph } from "./graph";
import type { Graph, Definition } from "./types";
const registry = [
  { type: "manual_input", outputs: ["out"] },
  { type: "transform", outputs: ["out"] },
  { type: "report", outputs: [] },
  { type: "merge", outputs: ["out"] },
  { type: "condition", outputs: ["true", "false"] },
] as Definition[];
const graph: Graph = {
  schemaVersion: 1,
  name: "Test",
  nodes: [
    {
      id: "a",
      type: "manual_input",
      typeVersion: 1,
      label: "a",
      position: { x: 0, y: 0 },
      config: { records: [] },
    },
    {
      id: "b",
      type: "transform",
      typeVersion: 1,
      label: "b",
      position: { x: 300, y: 0 },
      config: {},
    },
    {
      id: "c",
      type: "report",
      typeVersion: 1,
      label: "c",
      position: { x: 600, y: 0 },
      config: {},
    },
  ],
  edges: [],
};
it("allows a new valid connection", () =>
  expect(validConnection(graph, "a", "b", "out", registry)).toBe(true));
it("rejects self connection", () =>
  expect(validConnection(graph, "a", "a", "out", registry)).toBe(false));
it("rejects missing nodes", () =>
  expect(validConnection(graph, "missing", "b", "out", registry)).toBe(false));
it("rejects wrong port", () =>
  expect(validConnection(graph, "a", "b", "false", registry)).toBe(false));
it("rejects incoming to trigger", () =>
  expect(validConnection(graph, "b", "a", "out", registry)).toBe(false));
it("rejects outgoing from report", () =>
  expect(validConnection(graph, "c", "b", "out", registry)).toBe(false));
it("rejects duplicate connections", () =>
  expect(
    validConnection(
      {
        ...graph,
        edges: [
          {
            id: "e",
            source: "a",
            target: "b",
            sourceHandle: "out",
            targetHandle: "in",
          },
        ],
      },
      "a",
      "b",
      "out",
      registry,
    ),
  ).toBe(false));
it("rejects a cycle through two transforms", () => {
  const g: Graph = {
    ...graph,
    nodes: [...graph.nodes, { ...graph.nodes[1], id: "d" }],
    edges: [
      {
        id: "e",
        source: "b",
        target: "d",
        sourceHandle: "out",
        targetHandle: "in",
      },
    ],
  };
  expect(validConnection(g, "d", "b", "out", registry)).toBe(false);
});
it("rejects a second incoming edge to a transform", () => {
  const g: Graph = {
    ...graph,
    nodes: [...graph.nodes, { ...graph.nodes[1], id: "d" }],
    edges: [
      {
        id: "e",
        source: "a",
        target: "b",
        sourceHandle: "out",
        targetHandle: "in",
      },
    ],
  };
  expect(validConnection(g, "d", "b", "out", registry)).toBe(false);
});
it("accepts graph JSON", () =>
  expect(parseGraph(JSON.parse(JSON.stringify(graph)))).toEqual(graph));
it("rejects malformed graph imports", () =>
  expect(() => parseGraph({ nodes: "bad" })).toThrow());
it("rejects non-finite positions", () =>
  expect(() =>
    parseGraph({
      ...graph,
      nodes: [{ ...graph.nodes[0], position: { x: NaN, y: 0 } }],
    }),
  ).toThrow());
