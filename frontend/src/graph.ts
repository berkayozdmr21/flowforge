import type { Graph, Definition } from "./types";
export function validConnection(
  graph: Graph,
  source: string,
  target: string,
  port: string,
  registry: Definition[],
): boolean {
  if (source === target) return false;
  const a = graph.nodes.find((n) => n.id === source),
    b = graph.nodes.find((n) => n.id === target);
  if (
    !a ||
    !b ||
    !registry.find((d) => d.type === a.type)?.outputs.includes(port) ||
    b.type === "manual_input"
  )
    return false;
  if (b.type !== "merge" && graph.edges.some((e) => e.target === target))
    return false;
  if (
    graph.edges.some(
      (e) =>
        e.source === source && e.target === target && e.sourceHandle === port,
    )
  )
    return false;
  const visited = new Set<string>(),
    queue = [target];
  while (queue.length) {
    const id = queue.pop()!;
    if (id === source) return false;
    if (visited.has(id)) continue;
    visited.add(id);
    queue.push(
      ...graph.edges.filter((e) => e.source === id).map((e) => e.target),
    );
  }
  return true;
}
export function parseGraph(value: unknown): Graph {
  const g = value as Graph;
  if (
    !g ||
    g.schemaVersion !== 1 ||
    typeof g.name !== "string" ||
    !Array.isArray(g.nodes) ||
    !Array.isArray(g.edges) ||
    g.nodes.length > 100 ||
    g.edges.length > 200
  )
    throw Error("Geçerli bir FlowForge JSON dosyası seç.");
  for (const n of g.nodes)
    if (
      !n ||
      typeof n.id !== "string" ||
      !n.config ||
      typeof n.config !== "object" ||
      !n.position ||
      !Number.isFinite(n.position.x) ||
      !Number.isFinite(n.position.y)
    )
      throw Error("Blok belgesi geçersiz.");
  return g;
}
