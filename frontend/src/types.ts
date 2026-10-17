export type Config = Record<string, unknown>;
export type GraphNode = {
  id: string;
  type: string;
  typeVersion: 1;
  label: string;
  position: { x: number; y: number };
  config: Config;
};
export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle: string;
  targetHandle: "in";
};
export type Graph = {
  schemaVersion: 1;
  name: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
};
export type Definition = {
  type: string;
  title: string;
  category: string;
  description: string;
  icon: string;
  color: string;
  version: number;
  defaults: Config;
  inputs: string[];
  outputs: string[];
  configSchema: Record<string, unknown>;
};
export type Flow = {
  id: string;
  name: string;
  graph: Graph;
  revision: number;
  updated: number;
};
export type NodeRun = {
  id: string;
  status: string;
  attempt: number;
  output: { ref?: string; count: number } | null;
  error: string | null;
  started: number | null;
  finished: number | null;
};
export type Run = {
  id: string;
  flowId: string;
  versionId: string;
  version: number;
  status: string;
  sequence: number;
  created: number;
  finished: number | null;
  error: string | null;
  graph: Graph;
  nodes: NodeRun[];
  artifacts: Artifact[];
};
export type Artifact = {
  id: string;
  nodeId: string;
  format: string;
  title: string;
  size: number;
  url: string;
};
export type Event = {
  id: string;
  runId: string;
  sequence: number;
  kind: string;
  nodeId: string | null;
  payload: Record<string, unknown>;
  created: number;
};
export type Template = {
  id: string;
  tag: string;
  description: string;
  graph: Graph;
};
export type RunBrief = {
  id: string;
  flowId: string;
  status: string;
  created: number;
  finished: number | null;
  error: string | null;
};
export type Version = {
  id: string;
  number: number;
  created: number;
  digest: string;
  graph: Graph;
};
