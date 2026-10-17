import { create } from "zustand";
import type { Graph } from "./types";
import { clone } from "./api";
type State = {
  graph: Graph | null;
  past: Graph[];
  future: Graph[];
  set: (g: Graph, history?: boolean) => void;
  undo: () => void;
  redo: () => void;
};
export const useStudio = create<State>((set, get) => ({
  graph: null,
  past: [],
  future: [],
  set: (g, history = true) => {
    const s = get();
    if (JSON.stringify(g) === JSON.stringify(s.graph)) return;
    set({
      graph: clone(g),
      past:
        history && s.graph
          ? [...s.past, clone(s.graph)].slice(-60)
          : history
            ? s.past
            : [],
      future: [],
    });
  },
  undo: () => {
    const s = get();
    if (!s.past.length || !s.graph) return;
    set({
      graph: s.past.at(-1)!,
      past: s.past.slice(0, -1),
      future: [clone(s.graph), ...s.future],
    });
  },
  redo: () => {
    const s = get();
    if (!s.future.length || !s.graph) return;
    set({
      graph: s.future[0],
      past: [...s.past, clone(s.graph)],
      future: s.future.slice(1),
    });
  },
}));
