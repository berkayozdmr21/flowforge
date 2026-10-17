import { it, expect, beforeEach } from "vitest";
import { useStudio } from "./store";
import type { Graph } from "./types";
const graph: Graph = { schemaVersion: 1, name: "One", nodes: [], edges: [] };
beforeEach(() => useStudio.setState({ graph: null, past: [], future: [] }));
it("undoes and redoes an edit", () => {
  const s = useStudio.getState();
  s.set(graph, false);
  s.set({ ...graph, name: "Two" });
  s.undo();
  expect(useStudio.getState().graph?.name).toBe("One");
  s.redo();
  expect(useStudio.getState().graph?.name).toBe("Two");
});
it("does not add history for identical data", () => {
  const s = useStudio.getState();
  s.set(graph, false);
  s.set(graph);
  expect(useStudio.getState().past).toHaveLength(0);
});
it("clears redo after a new branch", () => {
  const s = useStudio.getState();
  s.set(graph, false);
  s.set({ ...graph, name: "Two" });
  s.undo();
  s.set({ ...graph, name: "Three" });
  expect(useStudio.getState().future).toHaveLength(0);
});
it("isolates graph data from caller mutations", () => {
  const g = { ...graph };
  useStudio.getState().set(g, false);
  g.name = "mutated";
  expect(useStudio.getState().graph?.name).toBe("One");
});
it("limits undo history to sixty entries", () => {
  for (let i = 0; i < 90; i++)
    useStudio.getState().set({ ...graph, name: String(i) });
  expect(useStudio.getState().past).toHaveLength(60);
});
