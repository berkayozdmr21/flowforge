import {
  useState,
  useEffect,
  useMemo,
  useRef,
  useCallback,
  type ReactNode,
} from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  MiniMap,
  Controls,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type NodeChange,
  type Edge,
  type EdgeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Workflow,
  Plus,
  Search,
  ChevronRight,
  ChevronDown,
  ArrowUpRight,
  Play,
  Square,
  Undo2,
  Redo2,
  Save,
  Download,
  Upload,
  Layers,
  History,
  Settings2,
  Check,
  ChevronUp,
  X,
  LoaderCircle,
  Copy,
  Trash2,
  Maximize2,
  PanelRightClose,
  PanelLeftClose,
  FileJson,
  BookOpen,
  AlertCircle,
  Wifi,
  WifiOff,
  Terminal,
  ArrowLeft,
  FolderOpen,
  ArrowDownToLine,
  Command,
  Activity,
  GitBranch,
} from "lucide-react";
import BlockNode, { icons, type StudioNode } from "./BlockNode";
import { useStudio } from "./store";
import { api, post, clone, labels, stamp } from "./api";
import { validConnection, parseGraph } from "./graph";
import type {
  Graph,
  GraphNode,
  GraphEdge,
  Definition,
  Flow,
  Run,
  RunBrief,
  Template,
  Event,
  Version,
  Config,
} from "./types";

const nodeTypes = { block: BlockNode };
const terminal = new Set(["succeeded", "failed", "cancelled"]);
const describe = (n: GraphNode) =>
  n.type === "manual_input"
    ? `${(n.config.records as unknown[]).length} kayıt · JSON`
    : n.type === "transform"
      ? [
          n.config.trim && "Kenar boşlukları",
          n.config.deduplicate && "Tekrarlar",
          n.config.filterOp !== "none" && "Filtre",
        ]
          .filter(Boolean)
          .join(" · ")
      : n.type === "condition"
        ? `${n.config.field} ${n.config.op} ${String(n.config.value)}`
        : n.type === "report"
          ? "JSON · CSV · HTML"
          : n.type === "delay"
            ? n.config.seconds + " saniye"
            : n.type === "aggregate"
              ? `${n.config.groupBy} · ${n.config.operation}`
              : n.type === "http_request"
                ? `${n.config.method} · ${n.config.url}`
                : "Paralel yollar";

function Dialog({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement,
      overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const nodes = Array.from(
          ref.current?.querySelectorAll<HTMLElement>(
            "button:not(:disabled),input,textarea,select,a[href]",
          ) || [],
        );
        if (e.shiftKey && document.activeElement === nodes[0]) {
          e.preventDefault();
          nodes.at(-1)?.focus();
        } else if (!e.shiftKey && document.activeElement === nodes.at(-1)) {
          e.preventDefault();
          nodes[0]?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, []);
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div
        className={"dialog " + (wide ? "wide" : "")}
        ref={ref}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <div>
            <span className="overline">FLOWFORGE / WORKSPACE</span>
            <h2>{title}</h2>
          </div>
          <button className="icon-button" aria-label="Kapat" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

function Studio() {
  const qc = useQueryClient(),
    flowApi = useReactFlow();
  const { graph, set: setGraph, past, future, undo, redo } = useStudio();
  const [current, setCurrent] = useState<Flow | null>(null),
    [selected, setSelected] = useState<string | null>("source"),
    [search, setSearch] = useState(""),
    [category, setCategory] = useState("Tümü"),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [dialog, setDialog] = useState<string | null>(null),
    [inspector, setInspector] = useState(() => window.innerWidth >= 1250),
    [palette, setPalette] = useState(true),
    [bottom, setBottom] = useState(true),
    [bottomTab, setBottomTab] = useState("events"),
    [run, setRun] = useState<Run | null>(null),
    [events, setEvents] = useState<Event[]>([]),
    [watching, setWatching] = useState(false),
    [preview, setPreview] = useState<unknown>(null),
    [raw, setRaw] = useState(""),
    [rawError, setRawError] = useState(""),
    [draftPositions, setDraftPositions] = useState<
      Record<string, { x: number; y: number }>
    >({}),
    [readOnly, setReadOnly] = useState(false),
    [reduced, setReduced] = useState(
      () =>
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ||
        false,
    ),
    [edgeSelected, setEdgeSelected] = useState<string | null>(null),
    [connectionFrom, setConnectionFrom] = useState(""),
    [connectionTo, setConnectionTo] = useState(""),
    [connectionPort, setConnectionPort] = useState("out");
  const upload = useRef<HTMLInputElement>(null),
    graphRef = useRef(graph),
    pendingStart = useRef<{ signature: string; key: string } | null>(null);
  graphRef.current = graph;
  const currentRef = useRef(current),
    readOnlyRef = useRef(readOnly);
  currentRef.current = current;
  readOnlyRef.current = readOnly;
  const boot = useQuery({
    queryKey: ["bootstrap"],
    queryFn: async () => {
      const [definitions, templates, flows] = await Promise.all([
        api<Definition[]>("/node-types"),
        api<Template[]>("/templates"),
        api<Flow[]>("/workflows"),
      ]);
      return { definitions, templates, flows };
    },
    retry: 1,
  });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () =>
      api<{ status: string; database: string; orchestrator: string }>(
        "/health/ready",
      ),
    refetchInterval: 10000,
    retry: false,
  });
  const history = useQuery({
    queryKey: ["runs", current?.id],
    queryFn: () => api<RunBrief[]>("/runs?flow_id=" + current!.id),
    enabled: !!current,
    refetchInterval: run && !terminal.has(run.status) ? 2000 : false,
  });
  const versions = useQuery({
    queryKey: ["versions", current?.id],
    queryFn: () => api<Version[]>("/workflows/" + current!.id + "/versions"),
    enabled: !!current && dialog === "versions",
  });
  const registry = boot.data?.definitions || [],
    templates = boot.data?.templates || [],
    flows = boot.data?.flows || [];
  const item = graph?.nodes.find((n) => n.id === selected),
    definition = registry.find((d) => d.type === item?.type),
    dirty =
      !!graph &&
      !!current &&
      JSON.stringify(graph) !== JSON.stringify(current.graph),
    active = !!run && !terminal.has(run.status);
  const openFlow = useCallback(
    (f: Flow, restore = true) => {
      const previous = currentRef.current;
      if (previous && graphRef.current && !readOnlyRef.current) {
        try {
          localStorage.setItem(
            "flowforge-draft:" + previous.id,
            JSON.stringify({
              graph: graphRef.current,
              revision: previous.revision,
            }),
          );
        } catch {}
      }
      let g = f.graph;
      if (restore) {
        try {
          const saved = JSON.parse(
            localStorage.getItem("flowforge-draft:" + f.id) || "null",
          );
          if (saved?.graph) g = parseGraph(saved.graph);
        } catch {}
      }
      setCurrent(f);
      setGraph(g, false);
      setSelected(g.nodes[0]?.id || null);
      setRun(null);
      setEvents([]);
      setReadOnly(false);
      setDraftPositions({});
      localStorage.setItem("flowforge-current", f.id);
      setTimeout(() => flowApi.fitView({ padding: 0.24, duration: 450 }), 80);
    },
    [setGraph, flowApi],
  );
  useEffect(() => {
    if (!boot.data || current) return;
    const last = localStorage.getItem("flowforge-current");
    const f =
      boot.data.flows.find((f) => f.id === last) ||
      boot.data.flows.find((f) => f.id === "welcome") ||
      boot.data.flows[0];
    if (f) openFlow(f);
  }, [boot.data, current, openFlow]);
  useEffect(() => {
    if (!graph || !current || readOnly) return;
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(
          "flowforge-draft:" + current.id,
          JSON.stringify({ graph, revision: current.revision }),
        );
      } catch {
        setNotice("Taslak alanı dolu. JSON dışa aktarımını kullan.");
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [graph, current, readOnly]);
  useEffect(() => {
    const t = setTimeout(
      () => flowApi.fitView({ padding: 0.2, duration: reduced ? 0 : 350 }),
      100,
    );
    return () => clearTimeout(t);
  }, [inspector, palette, bottom]);
  useEffect(() => {
    if (!current) return;
    const id = localStorage.getItem("flowforge-active:" + current.id);
    if (!id) return;
    let alive = true;
    api<Run>("/runs/" + id)
      .then((r) => {
        if (alive && !terminal.has(r.status)) {
          setRun(r);
          setGraph(r.graph, false);
          setReadOnly(true);
          setSelected(r.graph.nodes[0]?.id || null);
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [current?.id]);
  useEffect(() => {
    if (!run || !current) return;
    const key = "flowforge-active:" + current.id;
    if (!terminal.has(run.status)) localStorage.setItem(key, run.id);
    else localStorage.removeItem(key);
  }, [run?.id, run?.status, current?.id]);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 7000);
    return () => clearTimeout(t);
  }, [notice]);
  useEffect(() => {
    if (!item) return;
    setRaw(
      JSON.stringify(
        item.type === "manual_input" ? item.config.records : item.config,
        null,
        2,
      ),
    );
    setRawError("");
  }, [item?.id, item?.config]);
  useEffect(() => {
    if (!run || !selected) {
      setPreview(null);
      return;
    }
    let alive = true;
    api("/runs/" + run.id + "/nodes/" + selected + "/output")
      .then((v) => {
        if (alive) setPreview(v);
      })
      .catch(() => {
        if (alive) setPreview(null);
      });
    return () => {
      alive = false;
    };
  }, [run?.id, run?.sequence, selected]);
  useEffect(() => {
    if (!run) return;
    let disposed = false,
      socket: WebSocket | undefined,
      retry: ReturnType<typeof setTimeout> | undefined,
      refreshTimer: ReturnType<typeof setTimeout> | undefined,
      last = run.sequence;
    setEvents([]);
    const refresh = () => {
      if (refreshTimer) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = undefined;
        api<Run>("/runs/" + run.id)
          .then((v) => {
            if (!disposed) {
              setRun(v);
              if (terminal.has(v.status))
                qc.invalidateQueries({ queryKey: ["runs"] });
            }
          })
          .catch(() => {});
      }, 90);
    };
    const connect = (after: number) => {
      if (disposed) return;
      socket = new WebSocket(
        (location.protocol === "https:" ? "wss:" : "ws:") +
          "//" +
          location.host +
          "/api/runs/" +
          run.id +
          "/stream?after_sequence=" +
          after,
      );
      socket.onopen = () => {
        if (!disposed) setWatching(true);
      };
      socket.onmessage = (e) => {
        const value = JSON.parse(e.data) as Event;
        if (value.kind === "stream.complete") {
          setWatching(false);
          return;
        }
        last = Math.max(last, value.sequence);
        setEvents((old) =>
          old.some((x) => x.id === value.id)
            ? old
            : [...old, value]
                .sort((a, b) => a.sequence - b.sequence)
                .slice(-500),
        );
        refresh();
      };
      socket.onclose = () => {
        if (disposed) return;
        setWatching(false);
        api<Run>("/runs/" + run.id)
          .then(async (v) => {
            if (disposed) return;
            const missed = await api<Event[]>(
              "/runs/" + run.id + "/events?after_sequence=" + last,
            );
            if (disposed) return;
            setEvents((old) =>
              [...new Map([...old, ...missed].map((e) => [e.id, e])).values()]
                .sort((a, b) => a.sequence - b.sequence)
                .slice(-500),
            );
            last = Math.max(last, missed.at(-1)?.sequence || 0);
            setRun(v);
            if (!terminal.has(v.status) || last < v.sequence)
              retry = setTimeout(() => connect(last), 1000);
          })
          .catch(() => {
            if (!disposed) retry = setTimeout(() => connect(last), 2000);
          });
      };
    };
    api<Event[]>("/runs/" + run.id + "/events")
      .then((initial) => {
        if (disposed) return;
        setEvents(initial);
        last = initial.at(-1)?.sequence || 0;
        connect(last);
      })
      .catch(() => connect(0));
    return () => {
      disposed = true;
      setWatching(false);
      clearTimeout(retry);
      clearTimeout(refreshTimer);
      socket?.close();
    };
  }, [run?.id, qc]);
  function patchItem(config: Config) {
    if (!item || !graph || readOnly) return;
    setGraph({
      ...graph,
      nodes: graph.nodes.map((n) =>
        n.id === item.id ? { ...n, config: { ...n.config, ...config } } : n,
      ),
    });
  }
  function removeSelected() {
    if (!graph || readOnly) return;
    if (edgeSelected) {
      setGraph({
        ...graph,
        edges: graph.edges.filter((e) => e.id !== edgeSelected),
      });
      setEdgeSelected(null);
      return;
    }
    if (!selected) return;
    setGraph({
      ...graph,
      nodes: graph.nodes.filter((n) => n.id !== selected),
      edges: graph.edges.filter(
        (e) => e.source !== selected && e.target !== selected,
      ),
    });
    setSelected(null);
  }
  function duplicate() {
    if (!graph || !item || readOnly) return;
    const id = crypto.randomUUID();
    setGraph({
      ...graph,
      nodes: [
        ...graph.nodes,
        {
          ...clone(item),
          id,
          label: ((item.label || definition?.title || "Blok") + " kopya").slice(
            0,
            80,
          ),
          position: { x: item.position.x + 45, y: item.position.y + 160 },
        },
      ],
    });
    setSelected(id);
  }
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        dialog ||
        readOnly ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(
          (e.target as HTMLElement).tagName,
        )
      )
        return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        e.shiftKey ? redo() : undo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d") {
        e.preventDefault();
        duplicate();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        removeSelected();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [graph, selected, edgeSelected, dialog, readOnly]);
  async function saveCurrent() {
    if (!graph || !current) throw Error("Önce bir akış aç.");
    if (readOnly) return current;
    if (!dirty) return current;
    const next = await api<Flow>("/workflows/" + current.id, {
      method: "PATCH",
      body: JSON.stringify({ revision: current.revision, graph }),
    });
    setCurrent(next);
    qc.invalidateQueries({ queryKey: ["bootstrap"] });
    return next;
  }
  async function save() {
    setBusy(true);
    try {
      await saveCurrent();
      setNotice("Akış sunucuya kaydedildi.");
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function createFlow(g: Graph) {
    setBusy(true);
    try {
      const f = await api<Flow>("/workflows", post(g));
      openFlow(f, false);
      setDialog(null);
      qc.invalidateQueries({ queryKey: ["bootstrap"] });
      setNotice("Yeni akış hazır.");
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function start(versionId?: string) {
    setBusy(true);
    try {
      if (rawError) throw Error("Bloktaki JSON hatasını önce düzelt.");
      if (
        item &&
        raw !==
          JSON.stringify(
            item.type === "manual_input" ? item.config.records : item.config,
            null,
            2,
          )
      )
        throw Error(
          "JSON değişikliğini önce blok panelindeki uygula düğmesiyle onayla.",
        );
      const f = await saveCurrent();
      const body = {
          revision: f.revision,
          ...(versionId ? { versionId } : {}),
        },
        signature = JSON.stringify([f.id, body]);
      if (pendingStart.current?.signature !== signature)
        pendingStart.current = { signature, key: crypto.randomUUID() };
      const r = await api<Run>("/workflows/" + f.id + "/runs", {
        ...post(body),
        headers: { "Idempotency-Key": pendingStart.current!.key },
      });
      pendingStart.current = null;
      setRun(r);
      setBottom(true);
      setBottomTab("events");
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["versions"] });
      setNotice("Çalıştırma kuyruğa alındı.");
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function validate() {
    if (!graph) return;
    try {
      const result = await api<{ valid: boolean; order: string[] }>(
        "/workflows/validate",
        post(graph),
      );
      setNotice(
        `Akış geçerli. ${result.order.length} blok çalıştırmaya hazır.`,
      );
    } catch (e) {
      setNotice((e as Error).message);
    }
  }
  async function openRun(id: string) {
    try {
      if (current && graph && !readOnly)
        localStorage.setItem(
          "flowforge-draft:" + current.id,
          JSON.stringify({ graph, revision: current.revision }),
        );
      const r = await api<Run>("/runs/" + id);
      setRun(r);
      setBottom(true);
      setDialog(null);
      setGraph(r.graph, false);
      setReadOnly(true);
      setSelected(r.graph.nodes[0]?.id || null);
      setTimeout(() => flowApi.fitView({ padding: 0.25, duration: 400 }), 100);
    } catch (e) {
      setNotice((e as Error).message);
    }
  }
  function add(type: string) {
    if (!graph || readOnly) return;
    if (graph.nodes.length >= 100) {
      setNotice("Bir akışta en fazla 100 blok olabilir.");
      return;
    }
    const d = registry.find((d) => d.type === type)!;
    const id = crypto.randomUUID(),
      position = flowApi.screenToFlowPosition({
        x: window.innerWidth * 0.5,
        y: window.innerHeight * 0.45,
      });
    setGraph({
      ...graph,
      nodes: [
        ...graph.nodes,
        {
          id,
          type,
          typeVersion: 1,
          label: d.title,
          position,
          config: clone(d.defaults),
        },
      ],
    });
    setSelected(id);
    setInspector(true);
  }
  function connect(connection: Connection) {
    if (!graph || readOnly) return;
    const port = connection.sourceHandle || "out";
    if (
      !validConnection(
        graph,
        connection.source,
        connection.target,
        port,
        registry,
      )
    ) {
      setNotice("Bu bağlantı geçersiz veya döngü oluşturuyor.");
      return;
    }
    const edge: GraphEdge = {
      id: crypto.randomUUID(),
      source: connection.source,
      target: connection.target,
      sourceHandle: port,
      targetHandle: "in",
    };
    setGraph({ ...graph, edges: [...graph.edges, edge] });
  }
  function exportJSON() {
    if (!graph) return;
    const blob = new Blob([JSON.stringify(graph, null, 2)], {
        type: "application/json",
      }),
      url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = "flowforge-workflow.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function importJSON(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      if (file.size > 1024 * 1024) throw Error("JSON en fazla 1 MB olabilir.");
      const value = parseGraph(JSON.parse(await file.text()));
      await createFlow(value);
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      e.target.value = "";
    }
  }
  function applyRaw() {
    if (!item) return;
    try {
      const value = JSON.parse(raw);
      if (item.type === "manual_input") {
        if (
          !Array.isArray(value) ||
          value.some((x) => !x || typeof x !== "object" || Array.isArray(x))
        )
          throw Error("Bir JSON nesneleri listesi gerekli.");
        patchItem({ records: value });
      } else {
        if (!value || typeof value !== "object" || Array.isArray(value))
          throw Error("Ayarlar bir JSON nesnesi olmalı.");
        if (graph)
          setGraph({
            ...graph,
            nodes: graph.nodes.map((n) =>
              n.id === item.id ? { ...n, config: value } : n,
            ),
          });
      }
      setRawError("");
      setNotice("Blok ayarları uygulandı.");
    } catch (e) {
      setRawError((e as Error).message);
    }
  }
  const nodes = useMemo<StudioNode[]>(
    () =>
      graph
        ? graph.nodes.map((n) => {
            const d = registry.find((d) => d.type === n.type)!;
            const result = run?.nodes.find((v) => v.id === n.id);
            return {
              id: n.id,
              type: "block",
              width: 220,
              height: 143,
              position: draftPositions[n.id] || n.position,
              selected: n.id === selected,
              data: {
                definition: d,
                label: n.label,
                summary: describe(n),
                status: result?.status || "ready",
                count: result?.output?.count,
                attempt: result?.attempt,
                readOnly,
              },
            };
          })
        : [],
    [graph, registry, selected, run, draftPositions, readOnly],
  );
  const edges = useMemo<Edge[]>(
    () =>
      graph
        ? graph.edges.map((e) => {
            const parent = run?.nodes.find((n) => n.id === e.source),
              child = run?.nodes.find((n) => n.id === e.target),
              running =
                parent?.status === "succeeded" && child?.status === "running";
            return {
              ...e,
              selected: e.id === edgeSelected,
              type: "smoothstep",
              animated: running && !reduced,
              className:
                child?.status === "skipped"
                  ? "edge-skipped"
                  : parent?.status === "succeeded"
                    ? "edge-success"
                    : "",
              style: {
                stroke:
                  e.id === edgeSelected
                    ? "#708a57"
                    : running
                      ? "#78945c"
                      : parent?.status === "succeeded" &&
                          child?.status !== "skipped"
                        ? "#729367"
                        : "#a7b399",
                strokeWidth: 1.6,
              },
              label:
                e.sourceHandle === "true"
                  ? "Evet"
                  : e.sourceHandle === "false"
                    ? "Hayır"
                    : undefined,
              labelStyle: { fill: "#7e8e6f", fontSize: 10 },
              labelBgStyle: { fill: "#eff2e7" },
            };
          })
        : [],
    [graph, run, edgeSelected, reduced],
  );
  const onChanges = (changes: NodeChange<StudioNode>[]) => {
    if (readOnly) return;
    for (const c of changes)
      if (c.type === "position" && c.position)
        setDraftPositions((old) => ({ ...old, [c.id]: c.position! }));
  };
  const onEdgeChanges = (changes: EdgeChange[]) => {
    const removed = new Set(
      changes.filter((c) => c.type === "remove").map((c) => c.id),
    );
    if (graph && removed.size && !readOnly)
      setGraph({
        ...graph,
        edges: graph.edges.filter((e) => !removed.has(e.id)),
      });
  };
  const definitionList = registry.filter(
    (d) =>
      (category === "Tümü" || category === d.category) &&
      [d.title, d.description]
        .join(" ")
        .toLocaleLowerCase("tr")
        .includes(search.toLocaleLowerCase("tr")),
  );

  if (!graph || !boot.data)
    return (
      <div className="boot-screen">
        <div className="boot-logo">
          <Workflow size={30} />
        </div>
        <h1>FlowForge</h1>
        <p>
          {boot.isError
            ? "Çalışma alanına ulaşılamadı. BASLAT.cmd ile servisleri başlat."
            : "Çalışma alanın hazırlanıyor…"}
        </p>
        <button className="primary" onClick={() => boot.refetch()}>
          {boot.isError ? (
            "Yeniden dene"
          ) : (
            <LoaderCircle className="spin" size={18} />
          )}
        </button>
      </div>
    );
  return (
    <div
      className={
        "app " +
        (reduced ? "reduced " : "") +
        (!palette ? "hide-palette " : "") +
        (!inspector ? "hide-inspector" : "")
      }
    >
      <a className="skip" href="#block-settings">
        Blok ayarlarına geç
      </a>
      <nav className="rail" aria-label="Ana gezinme">
        <button
          className="brand-symbol"
          aria-label="FlowForge hakkında"
          onClick={() => setDialog("about")}
        >
          <Workflow size={26} />
        </button>
        <span className="rail-divider" />
        <button
          className="rail-button active"
          title="Editör"
          aria-label="Editör"
        >
          <Layers size={20} />
        </button>
        <button
          className="rail-button"
          aria-label="Akışlarım"
          onClick={() => setDialog("flows")}
        >
          <FolderOpen size={20} />
        </button>
        <button
          className="rail-button"
          aria-label="Çalıştırma geçmişi"
          onClick={() => setDialog("history")}
        >
          <History size={20} />
        </button>
        <button
          className="rail-button"
          aria-label="Hazır şablonlar"
          onClick={() => setDialog("templates")}
        >
          <Workflow size={20} />
        </button>
        <div className="rail-bottom">
          <button
            className="rail-button"
            aria-label="Kullanım rehberi"
            onClick={() => setDialog("about")}
          >
            <BookOpen size={19} />
          </button>
          <span className="avatar" title="Yerel çalışma alanı">
            B
          </span>
        </div>
      </nav>
      <header className="topbar">
        <div className="breadcrumb">
          <span>Çalışma alanım</span>
          <ChevronRight size={13} />
          <button onClick={() => setDialog("flows")}>
            Akışlar <ChevronDown size={12} />
          </button>
        </div>
        <div className="project-name">
          <span className="project-dot" />
          {readOnly ? (
            <span>{graph.name}</span>
          ) : (
            <input
              aria-label="Akış adı"
              value={graph.name}
              maxLength={100}
              onChange={(e) => setGraph({ ...graph, name: e.target.value })}
            />
          )}
          <span className="version-chip">
            {readOnly ? "v" + run?.version : "TASLAK"}
          </span>
        </div>
        <div className="top-actions">
          <button
            className="icon-button"
            aria-label="Sürüm geçmişi"
            onClick={() => setDialog("versions")}
          >
            <History size={16} />
          </button>
          <button
            className="secondary save-button"
            disabled={busy || readOnly}
            onClick={save}
          >
            <Save size={14} />
            <span>Kaydet</span>
          </button>
          <button
            className="primary run-button"
            disabled={busy || active || rawError !== ""}
            onClick={() => start(readOnly ? run?.versionId : undefined)}
          >
            {busy ? (
              <LoaderCircle size={14} className="spin" />
            ) : (
              <Play size={14} fill="currentColor" />
            )}
            <span>Çalıştır</span>
            <kbd>↵</kbd>
          </button>
        </div>
      </header>
      <aside className="palette">
        <div className="palette-heading">
          <span className="overline">YOUR AUTOMATION TOOLKIT</span>
          <h1>
            Fikirden akışa<span>.</span>
          </h1>
          <p>Doğru parçaları bir araya getir.</p>
        </div>
        <label className="search">
          <Search size={14} />
          <input
            aria-label="Blok ara"
            placeholder="Bir blok ara…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd>⌕</kbd>
        </label>
        <div className="category-tabs">
          {["Tümü", "Veri işleme", "Kontrol", "Çıktı", "Entegrasyon"].map(
            (c) => (
              <button
                key={c}
                className={category === c ? "selected" : ""}
                onClick={() => setCategory(c)}
              >
                {c}
              </button>
            ),
          )}
        </div>
        <div className="palette-label">
          <span>YAPI TAŞLARI</span>
          <span>{String(definitionList.length).padStart(2, "0")}</span>
        </div>
        <div className="block-library">
          {definitionList.map((d) => {
            const Icon = icons[d.type];
            return (
              <button
                key={d.type}
                className="library-item"
                aria-label={d.title + " ekle"}
                disabled={readOnly}
                onClick={() => add(d.type)}
              >
                <span
                  className="library-icon"
                  style={{
                    background: d.color + "14",
                    color: d.color,
                    borderColor: d.color + "29",
                  }}
                >
                  <Icon size={18} />
                </span>
                <span>
                  <strong>{d.title}</strong>
                  <small>{d.description}</small>
                </span>
                <Plus size={14} />
              </button>
            );
          })}
        </div>
        <button
          className="template-card"
          onClick={() => setDialog("templates")}
        >
          <span className="template-glyph">
            <Workflow size={23} />
            <span>✦</span>
          </span>
          <strong>Boş bir tuvalden fazlası.</strong>
          <p>Hazır akışlarla bir adım önden başla.</p>
          <span>
            Şablonları keşfet <ArrowUpRight size={14} />
          </span>
        </button>
        <div className="local-note">
          <span
            className={"health-dot " + (health.data ? "online" : "offline")}
          />
          <span>
            {health.data
              ? "PostgreSQL + Temporal"
              : "Servis bağlantısı bekleniyor"}
          </span>
        </div>
      </aside>
      <main className="editor">
        <div className="canvas-bar">
          <div className="canvas-bar-title">
            <span className="overline">AUTOMATION STUDIO</span>
            <strong>
              {readOnly ? "Çalıştırma görünümü" : "Her adımın bir anlamı var."}
            </strong>
          </div>
          <div className="canvas-tools">
            <button
              aria-label="Geri al"
              title="Geri al"
              disabled={!past.length || readOnly}
              onClick={undo}
            >
              <Undo2 size={15} />
            </button>
            <button
              aria-label="İleri al"
              title="İleri al"
              disabled={!future.length || readOnly}
              onClick={redo}
            >
              <Redo2 size={15} />
            </button>
            <span />
            <button
              aria-label="Bağlantı ekle"
              title="Bağlantı ekle"
              disabled={readOnly}
              onClick={() => {
                setConnectionFrom(graph.nodes[0]?.id || "");
                setConnectionTo(graph.nodes[1]?.id || "");
                setDialog("connect");
              }}
            >
              <GitBranch size={15} />
            </button>
            <button
              aria-label="Sol paneli aç veya kapat"
              onClick={() => setPalette(!palette)}
            >
              <PanelLeftClose size={15} />
            </button>
            <button
              aria-label="Sağ paneli aç veya kapat"
              onClick={() => setInspector(!inspector)}
            >
              <PanelRightClose size={15} />
            </button>
            <button
              aria-label="Akışı kadraja sığdır"
              onClick={() =>
                flowApi.fitView({ padding: 0.22, duration: reduced ? 0 : 450 })
              }
            >
              <Maximize2 size={15} />
            </button>
          </div>
        </div>
        {readOnly && (
          <div className="read-only-bar">
            <History size={13} /> v{run?.version} · {stamp(run?.created || 0)} ·
            Değişmez çalıştırma kopyası
            <button
              onClick={() => {
                if (current) openFlow(current);
              }}
            >
              Taslağa dön <ArrowLeft size={12} />
            </button>
          </div>
        )}
        <div className={"canvas " + (!bottom ? "full-height" : "")}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            colorMode="light"
            onNodesChange={onChanges}
            onEdgesChange={onEdgeChanges}
            onConnect={connect}
            isValidConnection={(c) =>
              validConnection(
                graph,
                c.source,
                c.target,
                c.sourceHandle || "out",
                registry,
              )
            }
            onNodeClick={(_, n) => {
              setSelected(n.id);
              setEdgeSelected(null);
              setInspector(true);
            }}
            onEdgeClick={(_, e) => {
              setEdgeSelected(e.id);
              setSelected(null);
            }}
            onPaneClick={() => {
              setSelected(null);
              setEdgeSelected(null);
            }}
            onNodeDragStop={(_, n) => {
              if (readOnly) return;
              setGraph({
                ...graph,
                nodes: graph.nodes.map((i) =>
                  i.id === n.id ? { ...i, position: n.position } : i,
                ),
              });
              setDraftPositions({});
            }}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.3}
            maxZoom={1.7}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            deleteKeyCode={null}
            selectionKeyCode="Shift"
            snapToGrid
            snapGrid={[20, 20]}
            defaultEdgeOptions={{ type: "smoothstep" }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={22}
              size={1}
              color="#cdd3c3"
            />
            <Controls showInteractive={false} />
            <MiniMap
              style={{ width: 112, height: 72 }}
              pannable
              zoomable
              nodeColor={(n) =>
                (n.data as { definition: Definition }).definition?.color ||
                "#9e8be8"
              }
              maskColor="#edf1e5bc"
              nodeBorderRadius={4}
            />
          </ReactFlow>
          <div className="canvas-watermark">
            FLOW / FORGE<span>MAKE WORK FLOW.</span>
          </div>
        </div>
        <section className={"execution-panel " + (!bottom ? "collapsed" : "")}>
          <header>
            <div className="run-title">
              <span className={"run-indicator " + (run?.status || "idle")} />
              <strong>{run ? labels[run.status] : "Çalıştırma alanı"}</strong>
              {run && <span className="run-code">#{run.id.slice(0, 7)}</span>}
              {watching && (
                <span className="live-label">
                  <span />
                  CANLI
                </span>
              )}
            </div>
            <div className="execution-actions">
              {active && (
                <button
                  className="cancel-button"
                  onClick={async () => {
                    try {
                      await api("/runs/" + run.id + "/cancel", post({}));
                      setNotice("İptal isteği gönderildi.");
                    } catch (e) {
                      setNotice((e as Error).message);
                    }
                  }}
                >
                  <Square size={11} /> İptal et
                </button>
              )}
              <button
                aria-label="Çalıştırma panelini aç veya kapat"
                onClick={() => setBottom(!bottom)}
              >
                {bottom ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
              </button>
            </div>
          </header>
          {bottom && (
            <>
              <div className="execution-tabs">
                {[
                  ["events", "Olay günlüğü"],
                  ["output", "Blok çıktısı"],
                  ["files", "Raporlar"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    className={bottomTab === id ? "selected" : ""}
                    onClick={() => setBottomTab(id)}
                  >
                    {label}
                    {id === "files" && !!run?.artifacts.length && (
                      <span>{run.artifacts.length}</span>
                    )}
                  </button>
                ))}
                <button
                  className="history-shortcut"
                  onClick={() => setDialog("history")}
                >
                  <History size={12} /> Geçmiş
                </button>
              </div>
              <div className="execution-content">
                {!run ? (
                  <div className="execution-empty">
                    <span>
                      <Terminal size={18} />
                    </span>
                    <div>
                      <strong>Bir fikir, ilk adımını bekliyor.</strong>
                      <p>
                        Akışını çalıştır; her bloğun sonucunu burada takip et.
                      </p>
                    </div>
                    <button onClick={validate}>
                      Akışı kontrol et <ArrowUpRight size={12} />
                    </button>
                  </div>
                ) : bottomTab === "events" ? (
                  events.length ? (
                    <div className="event-log">
                      {[...events].reverse().map((e) => (
                        <div
                          key={e.id}
                          className={
                            e.kind.includes("failed") ||
                            e.kind.includes("error")
                              ? "error-row"
                              : ""
                          }
                        >
                          <time>{stamp(e.created)}</time>
                          <span className="event-level">
                            {e.kind.startsWith("node") ? "NODE" : "RUN"}
                          </span>
                          <strong>
                            {e.nodeId
                              ? run.graph.nodes.find((n) => n.id === e.nodeId)
                                  ?.label || e.nodeId
                              : "Çalıştırma"}
                          </strong>
                          <span>
                            {e.kind === "run.completed"
                              ? labels[String(e.payload.status)]
                              : labels[e.kind.split(".")[1]] || e.kind}
                          </span>
                          {e.payload.count !== undefined && (
                            <b>{String(e.payload.count)} kayıt</b>
                          )}
                          {!!e.payload.error && (
                            <em>{String(e.payload.error)}</em>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-small">Olaylar bekleniyor…</div>
                  )
                ) : bottomTab === "output" ? (
                  <div className="output-preview">
                    {selected ? (
                      <pre>
                        {preview
                          ? JSON.stringify(preview, null, 2)
                          : "Bu blok henüz bir çıktı üretmedi."}
                      </pre>
                    ) : (
                      <div className="empty-small">
                        Çıktısını incelemek için bir blok seç.
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="artifact-list">
                    {run.artifacts.length ? (
                      run.artifacts.map((a) => (
                        <a key={a.id} href={a.url} download>
                          <span className={"format-icon " + a.format}>
                            {a.format.toUpperCase()}
                          </span>
                          <div>
                            <strong>{a.title}</strong>
                            <small>
                              {(a.size / 1024).toFixed(1)} KB ·{" "}
                              {a.format.toUpperCase()}
                            </small>
                          </div>
                          <ArrowDownToLine size={16} />
                        </a>
                      ))
                    ) : (
                      <div className="empty-small">
                        Rapor bloğu tamamlandığında dosyalar burada görünür.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </main>
      <aside className="inspector" id="block-settings">
        <div className="inspector-heading">
          <span className="overline">THE DETAILS MAKE THE FLOW</span>
          <h2>İnce ayarlar.</h2>
          <p>Her parçayı amacına göre şekillendir.</p>
        </div>
        {item && definition ? (
          <>
            <div className="selected-block">
              <span
                style={{
                  background: definition.color + "18",
                  color: definition.color,
                }}
              >
                {(() => {
                  const Icon = icons[item.type];
                  return <Icon size={22} />;
                })()}
              </span>
              <div>
                <small>{definition.category.toLocaleUpperCase("tr")}</small>
                <h3>{definition.title}</h3>
              </div>
              <span className="schema-version">V1</span>
            </div>
            <label className="field">
              Blok adı
              <input
                value={item.label}
                aria-label="Blok adı"
                maxLength={80}
                disabled={readOnly}
                onChange={(e) =>
                  setGraph({
                    ...graph,
                    nodes: graph.nodes.map((n) =>
                      n.id === item.id ? { ...n, label: e.target.value } : n,
                    ),
                  })
                }
              />
            </label>
            <div className="inspector-section">
              <span>01</span>
              <h3>Yapılandırma</h3>
              <Settings2 size={13} />
            </div>
            {item.type === "manual_input" ? (
              <>
                <label className="field">
                  Girdi kayıtları <span className="field-tag">JSON ARRAY</span>
                  <textarea
                    aria-label="Girdi JSON"
                    className="code-editor"
                    spellCheck={false}
                    value={raw}
                    disabled={readOnly}
                    onChange={(e) => {
                      setRaw(e.target.value);
                      try {
                        JSON.parse(e.target.value);
                        setRawError("");
                      } catch {
                        setRawError("JSON biçimini kontrol et.");
                      }
                    }}
                  />
                </label>
                <button
                  className="secondary full"
                  disabled={readOnly}
                  onClick={applyRaw}
                >
                  <Check size={13} /> Girdiyi uygula
                </button>
                <p className="field-help">
                  Her satır bir JSON nesnesidir. Düzenledikten sonra girdiyi
                  uygula.
                </p>
              </>
            ) : item.type === "transform" ? (
              <>
                <div className="toggle-list">
                  {[
                    ["trim", "Kenar boşluklarını temizle"],
                    ["removeEmpty", "Boş kayıtları çıkar"],
                    ["deduplicate", "Tekrarları kaldır"],
                  ].map(([key, label]) => (
                    <label key={key}>
                      <span>{label}</span>
                      <input
                        type="checkbox"
                        checked={Boolean(item.config[key])}
                        disabled={readOnly}
                        onChange={(e) => patchItem({ [key]: e.target.checked })}
                      />
                    </label>
                  ))}
                </div>
                <label className="field">
                  Zorunlu alan
                  <input
                    placeholder="Örn. email"
                    value={String(item.config.requiredField)}
                    disabled={readOnly}
                    onChange={(e) =>
                      patchItem({ requiredField: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  Filtre alanı
                  <input
                    placeholder="Örn. amount"
                    value={String(item.config.filterField)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ filterField: e.target.value })}
                  />
                </label>
                <label className="field">
                  Filtre işlemi
                  <select
                    value={String(item.config.filterOp)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ filterOp: e.target.value })}
                  >
                    {[
                      ["none", "Filtreleme yok"],
                      ["eq", "Eşittir"],
                      ["ne", "Eşit değildir"],
                      ["gt", "Büyüktür"],
                      ["gte", "Büyük veya eşit"],
                      ["lt", "Küçüktür"],
                      ["lte", "Küçük veya eşit"],
                      ["contains", "İçerir"],
                    ].map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                {item.config.filterOp !== "none" && (
                  <label className="field">
                    Karşılaştırma değeri
                    <input
                      value={String(item.config.filterValue ?? "")}
                      disabled={readOnly}
                      onChange={(e) =>
                        patchItem({ filterValue: e.target.value })
                      }
                    />
                  </label>
                )}
              </>
            ) : item.type === "condition" ? (
              <>
                <label className="field">
                  Kontrol edilecek alan
                  <input
                    value={String(item.config.field)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ field: e.target.value })}
                  />
                </label>
                <p className="field-help">
                  Kayıt sayısı için records.count, bir alan için ilk kaydın alan
                  adı.
                </p>
                <label className="field">
                  Karşılaştırma
                  <select
                    value={String(item.config.op)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ op: e.target.value })}
                  >
                    {["gt", "gte", "lt", "lte", "eq", "ne", "contains"].map(
                      (v) => (
                        <option key={v}>{v}</option>
                      ),
                    )}
                  </select>
                </label>
                <label className="field">
                  Değer
                  <input
                    value={String(item.config.value)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ value: e.target.value })}
                  />
                </label>
                <div className="info-note">
                  <GitBranch size={14} />
                  <p>
                    Koşul tek bir kolu etkinleştirir. Diğer kol hata vermeden
                    atlanır.
                  </p>
                </div>
              </>
            ) : item.type === "report" ? (
              <>
                <label className="field">
                  Rapor başlığı
                  <input
                    value={String(item.config.title)}
                    disabled={readOnly}
                    maxLength={100}
                    onChange={(e) => patchItem({ title: e.target.value })}
                  />
                </label>
                <span className="field-label">Çıktı biçimleri</span>
                <div className="format-options">
                  {["json", "csv", "html"].map((fmt) => (
                    <button
                      key={fmt}
                      aria-pressed={(item.config.formats as string[]).includes(
                        fmt,
                      )}
                      className={
                        (item.config.formats as string[]).includes(fmt)
                          ? "selected"
                          : ""
                      }
                      disabled={readOnly}
                      onClick={() => {
                        const f = item.config.formats as string[];
                        if (f.includes(fmt) && f.length === 1) return;
                        patchItem({
                          formats: f.includes(fmt)
                            ? f.filter((x) => x !== fmt)
                            : [...f, fmt],
                        });
                      }}
                    >
                      {fmt.toUpperCase()}
                    </button>
                  ))}
                </div>
                <p className="field-help">
                  Raporlar sunucuda oluşturulur ve çalıştırma kaydına bağlanır.
                </p>
              </>
            ) : item.type === "merge" ? (
              <>
                <div className="info-note">
                  <Layers size={14} />
                  <p>
                    Etkin yolların bitmesini bekler. Atlanan yolları yok sayar;
                    kayıt sırasını korur.
                  </p>
                </div>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={Boolean(item.config.deduplicate)}
                    disabled={readOnly}
                    onChange={(e) =>
                      patchItem({ deduplicate: e.target.checked })
                    }
                  />{" "}
                  Tekrarları kaldır
                </label>
              </>
            ) : item.type === "http_request" ? (
              <>
                <label className="field">
                  HTTP yöntemi
                  <select
                    value={String(item.config.method)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ method: e.target.value })}
                  >
                    <option value="GET">GET — Veri al</option>
                    <option value="POST">POST — JSON gönder</option>
                  </select>
                </label>
                <label className="field">
                  API adresi
                  <input
                    type="url"
                    value={String(item.config.url)}
                    disabled={readOnly}
                    placeholder="https://api.example.com/data"
                    onChange={(e) => patchItem({ url: e.target.value })}
                  />
                </label>
                <label className="field">
                  Zaman aşımı (saniye)
                  <input
                    type="number"
                    min="1"
                    max="30"
                    value={Number(item.config.timeoutSeconds)}
                    disabled={readOnly}
                    onChange={(e) =>
                      patchItem({ timeoutSeconds: e.target.valueAsNumber })
                    }
                  />
                </label>
                <label className="field">
                  JSON yanıt yolu
                  <input
                    value={String(item.config.responsePath)}
                    disabled={readOnly}
                    placeholder="Boş: tüm yanıt · Örnek: data.items"
                    onChange={(e) =>
                      patchItem({ responsePath: e.target.value })
                    }
                  />
                </label>
                {item.config.method === "POST" && (
                  <label className="field">
                    JSON gövdesi
                    <select
                      value={String(item.config.bodySource)}
                      disabled={readOnly}
                      onChange={(e) =>
                        patchItem({ bodySource: e.target.value })
                      }
                    >
                      <option value="records">Önceki bloğun kayıtları</option>
                      <option value="json">
                        Gelişmiş ayarlardaki body nesnesi
                      </option>
                    </select>
                  </label>
                )}
                <label className="field">
                  Token ortam değişkeni adı (isteğe bağlı)
                  <input
                    value={String(item.config.tokenEnv)}
                    disabled={readOnly}
                    placeholder="Örnek: CRM"
                    onChange={(e) => patchItem({ tokenEnv: e.target.value })}
                  />
                </label>
                <p className="field-help">
                  Token için sunucuda FLOWFORGE_HTTP_TOKEN_AD tanımla. Buraya
                  anahtarın kendisini yazma. Yanıt bir JSON nesnesi veya nesne
                  listesi olmalı. Başlıkları ve özel POST gövdesini gelişmiş
                  JSON ayarlarından düzenleyebilirsin. Yalnızca genel ağ
                  adresleri desteklenir; yönlendirmeler izlenmez. POST hataları
                  otomatik yeniden denenmez.
                </p>
              </>
            ) : item.type === "delay" ? (
              <label className="field">
                Bekleme süresi (saniye)
                <input
                  type="number"
                  aria-label="Bekleme süresi"
                  min=".1"
                  max="300"
                  step=".1"
                  value={Number(item.config.seconds)}
                  disabled={readOnly}
                  onChange={(e) =>
                    patchItem({ seconds: e.target.valueAsNumber })
                  }
                />
              </label>
            ) : item.type === "aggregate" ? (
              <>
                <label className="field">
                  Gruplama alanı
                  <input
                    value={String(item.config.groupBy)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ groupBy: e.target.value })}
                  />
                </label>
                <label className="field">
                  Sayısal alan
                  <input
                    value={String(item.config.valueField)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ valueField: e.target.value })}
                  />
                </label>
                <label className="field">
                  İşlem
                  <select
                    value={String(item.config.operation)}
                    disabled={readOnly}
                    onChange={(e) => patchItem({ operation: e.target.value })}
                  >
                    <option value="sum">Toplam</option>
                    <option value="count">Adet</option>
                    <option value="mean">Ortalama</option>
                  </select>
                </label>
              </>
            ) : null}
            {rawError && <p className="field-error">{rawError}</p>}
            {item.type !== "manual_input" && (
              <details className="advanced">
                <summary>
                  Gelişmiş JSON ayarları <FileJson size={12} />
                </summary>
                <textarea
                  className="code-editor"
                  aria-label="Blok ayarları JSON"
                  spellCheck={false}
                  value={raw}
                  disabled={readOnly}
                  onChange={(e) => setRaw(e.target.value)}
                />
                <button
                  className="secondary full"
                  disabled={readOnly}
                  onClick={applyRaw}
                >
                  Ayarları uygula
                </button>
              </details>
            )}
            <div className="inspector-section">
              <span>02</span>
              <h3>Bağlantılar</h3>
            </div>
            <div className="port-info">
              <span>
                Giriş <b>{definition.inputs.length ? "Veri zarfı" : "—"}</b>
              </span>
              <span>
                Çıkış{" "}
                <b>{definition.outputs.join(" / ") || "Rapor dosyaları"}</b>
              </span>
            </div>
            <div className="object-actions">
              <button disabled={readOnly} onClick={duplicate}>
                <Copy size={13} /> Çoğalt
              </button>
              <button disabled={readOnly} onClick={removeSelected}>
                <Trash2 size={13} /> Sil
              </button>
            </div>
          </>
        ) : edgeSelected ? (
          <div className="no-selection">
            <GitBranch size={30} />
            <h3>Bağlantı seçildi.</h3>
            <p>Bu bağlantıyı silerek akış yönünü yeniden düzenleyebilirsin.</p>
            <button
              className="secondary full"
              disabled={readOnly}
              onClick={removeSelected}
            >
              <Trash2 size={14} /> Bağlantıyı sil
            </button>
          </div>
        ) : (
          <div className="no-selection">
            <Settings2 size={30} />
            <h3>Bir parçayı seç.</h3>
            <p>
              Bir bloğa dokun; verisini, ayarlarını ve çıktısını burada keşfet.
            </p>
            <button className="secondary full" onClick={validate}>
              Akışı doğrula <Check size={14} />
            </button>
          </div>
        )}
        <div className="inspector-footer">
          <span>
            <span className="tiny-dot" />
            {graph.nodes.length} blok · {graph.edges.length} bağlantı
          </span>
          <p>
            {readOnly
              ? "Geçmiş çalıştırma değiştirilemez."
              : dirty
                ? "Kaydedilmemiş değişiklikler var."
                : "Sunucu kaydı güncel."}
          </p>
        </div>
      </aside>
      <footer className="statusbar">
        <span className="status-left">
          <Check size={11} />
          {readOnly
            ? "Sürüm anlık görüntüsü"
            : "Taslak bu tarayıcıda saklanır."}
        </span>
        <div>
          <button onClick={exportJSON}>
            <Download size={11} /> JSON
          </button>
          <button onClick={() => upload.current?.click()}>
            <Upload size={11} /> İçe aktar
          </button>
          <button onClick={validate}>
            <Check size={11} /> Doğrula
          </button>
        </div>
        <button onClick={() => setReduced(!reduced)}>
          {reduced ? "Hareket azaltıldı" : "Animasyon açık"}
          <Settings2 size={11} />
        </button>
        <span className="status-signature">DESIGNED TO KEEP MOVING.</span>
        <input
          ref={upload}
          type="file"
          accept=".json,application/json"
          hidden
          onChange={importJSON}
        />
      </footer>
      {notice && (
        <div className="toast" role="status">
          <Activity size={15} />
          <span>{notice}</span>
          <button aria-label="Bildirimi kapat" onClick={() => setNotice("")}>
            <X size={15} />
          </button>
        </div>
      )}
      {dialog === "templates" && (
        <Dialog title="Bir fikirle başla." onClose={() => setDialog(null)} wide>
          <p>
            Gerçek veriyle çalışan, anahtar gerektirmeyen başlangıç akışları.
          </p>
          <div className="template-grid">
            {templates.map((t, i) => (
              <button
                key={t.id}
                disabled={busy}
                onClick={() => createFlow(clone(t.graph))}
              >
                <div className="template-art">
                  <span />
                  <Workflow size={46} />
                  <span />
                  <b>0{i + 1}</b>
                </div>
                <small>{t.tag}</small>
                <h3>{t.graph.name.split(" · ")[0]}</h3>
                <p>{t.description}</p>
                <span>
                  {t.graph.nodes.length} blok <ArrowUpRight size={14} />
                </span>
              </button>
            ))}
          </div>
        </Dialog>
      )}
      {dialog === "flows" && (
        <Dialog title="Akışların." onClose={() => setDialog(null)} wide>
          <div className="modal-toolbar">
            <p>Her otomasyon bir fikirle başlar.</p>
            <button
              className="primary"
              disabled={busy}
              onClick={() =>
                createFlow({ ...clone(templates[0].graph), name: "Yeni akış" })
              }
            >
              <Plus size={14} /> Yeni akış
            </button>
          </div>
          <div className="flow-list">
            {flows.map((f) => (
              <button
                key={f.id}
                onClick={() => {
                  openFlow(f);
                  setDialog(null);
                }}
              >
                <span>
                  <Workflow size={20} />
                </span>
                <div>
                  <strong>{f.name}</strong>
                  <small>
                    {f.graph.nodes.length} blok · Son kayıt{" "}
                    {new Date(f.updated * 1000).toLocaleDateString("tr-TR")}
                  </small>
                </div>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
          <button
            className="secondary full"
            disabled={busy}
            onClick={() =>
              createFlow({ ...clone(graph), name: graph.name + " · kopya" })
            }
          >
            <Copy size={14} /> Açık akışı yeni bir kopya olarak kaydet
          </button>
        </Dialog>
      )}
      {dialog === "history" && (
        <Dialog
          title="Her çalıştırma bir hikâye."
          onClose={() => setDialog(null)}
          wide
        >
          <p>Kaydedilen sürümler, gerçek sonuçlar ve olay geçmişi.</p>
          <div className="history-list">
            {history.data?.length ? (
              history.data.map((r) => (
                <button key={r.id} onClick={() => openRun(r.id)}>
                  <span className={"history-state " + r.status}>
                    {r.status === "succeeded" ? (
                      <Check size={17} />
                    ) : (
                      <Activity size={17} />
                    )}
                  </span>
                  <div>
                    <strong>#{r.id.slice(0, 8)}</strong>
                    <small>
                      {new Date(r.created * 1000).toLocaleString("tr-TR")}
                    </small>
                  </div>
                  <span className={"state " + r.status}>
                    {labels[r.status]}
                  </span>
                  <ArrowUpRight size={15} />
                </button>
              ))
            ) : (
              <div className="empty-modal">
                <History size={30} />
                <h3>İlk çalıştırmanı bekliyoruz.</h3>
              </div>
            )}
          </div>
        </Dialog>
      )}
      {dialog === "versions" && (
        <Dialog title="Fikirlerinin izini tut." onClose={() => setDialog(null)}>
          <p>
            Her çalıştırma değişmez bir sürüm kullanır. Eski bir sürümü
            taslağına alabilir veya aynı sürümü yeniden çalıştırabilirsin.
          </p>
          <div className="version-list">
            {versions.data?.length ? (
              versions.data.map((v) => (
                <article key={v.id}>
                  <div>
                    <b>v{v.number}</b>
                    <span>
                      {new Date(v.created * 1000).toLocaleString("tr-TR")}
                    </span>
                  </div>
                  <small>
                    {v.graph.nodes.length} blok · {v.digest.slice(0, 10)}
                  </small>
                  <button
                    className="secondary full"
                    disabled={busy}
                    onClick={() => {
                      setGraph(v.graph);
                      setReadOnly(false);
                      setDialog(null);
                      setRun(null);
                      setNotice(
                        "Eski sürüm taslağa alındı. Kaydettiğinde yeni sürüm oluşturulabilir.",
                      );
                    }}
                  >
                    Taslak olarak aç <ArrowUpRight size={13} />
                  </button>
                </article>
              ))
            ) : (
              <div className="empty-small">
                İlk çalıştırmada ilk sürüm oluşturulur.
              </div>
            )}
          </div>
        </Dialog>
      )}
      {dialog === "connect" && (
        <Dialog
          title="İki adımı birbirine bağla."
          onClose={() => setDialog(null)}
        >
          <label className="field">
            Kaynak blok
            <select
              value={connectionFrom}
              onChange={(e) => {
                setConnectionFrom(e.target.value);
                setConnectionPort("out");
              }}
            >
              {graph.nodes
                .filter((n) => n.type !== "report")
                .map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
            </select>
          </label>
          <label className="field">
            Çıkış
            <select
              value={connectionPort}
              onChange={(e) => setConnectionPort(e.target.value)}
            >
              {(
                registry.find(
                  (d) =>
                    d.type ===
                    graph.nodes.find((n) => n.id === connectionFrom)?.type,
                )?.outputs || []
              ).map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Hedef blok
            <select
              value={connectionTo}
              onChange={(e) => setConnectionTo(e.target.value)}
            >
              {graph.nodes
                .filter((n) => n.type !== "manual_input")
                .map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
            </select>
          </label>
          <button
            className="primary full"
            disabled={
              !validConnection(
                graph,
                connectionFrom,
                connectionTo,
                connectionPort,
                registry,
              )
            }
            onClick={() => {
              connect({
                source: connectionFrom,
                target: connectionTo,
                sourceHandle: connectionPort,
                targetHandle: "in",
              });
              setDialog(null);
            }}
          >
            Bağlantıyı oluştur <GitBranch size={14} />
          </button>
          <p className="field-help">
            Tuvalde blokların kenarlarındaki portları sürükleyerek de bağlantı
            kurabilirsin.
          </p>
        </Dialog>
      )}
      {dialog === "about" && (
        <Dialog title="İşler aksın. Sen üret." onClose={() => setDialog(null)}>
          <p>
            FlowForge, Berkay Özdemir tarafından geliştirilen görsel otomasyon
            stüdyosudur. Blokları bağla, akışını çalıştır ve gerçek sonuçlarını
            izle.
          </p>
          <div className="about-stack">
            <span>React + TypeScript</span>
            <span>FastAPI</span>
            <span>PostgreSQL</span>
            <span>Temporal</span>
          </div>
          <p>
            Ctrl+Z: geri al · Ctrl+Shift+Z: ileri al · Ctrl+D: çoğalt · Delete:
            sil. Düzenlenen JSON girdisini çalıştırmadan önce uygula. Veri
            girişi, temizleme, koşul, birleştirme, rapor, kalıcı bekleme ve
            özetleme blokları API anahtarı gerektirmez.
          </p>
          <p>
            Bu sürüm tek kullanıcılı yerel çalışma alanıdır. Temporal geliştirme
            sunucusu kullanır; ekip yetkilendirmesi ve dış servis/AI
            bağlantıları bu teslimata dahil değildir.
          </p>
          <a
            className="secondary full"
            href="/docs"
            target="_blank"
            rel="noreferrer"
          >
            API belgeleri <ArrowUpRight size={14} />
          </a>
        </Dialog>
      )}
    </div>
  );
}
export default function App() {
  return (
    <ReactFlowProvider>
      <Studio />
    </ReactFlowProvider>
  );
}
