import { memo } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import {
  Database,
  Globe,
  WandSparkles,
  GitBranch,
  Combine,
  FileBarChart,
  Timer,
  ChartNoAxesCombined,
  Check,
  LoaderCircle,
  AlertTriangle,
  Minus,
  Play,
} from "lucide-react";
import type { Definition } from "./types";
import { labels } from "./api";
export const icons: Record<string, typeof Database> = {
  manual_input: Database,
  transform: WandSparkles,
  condition: GitBranch,
  merge: Combine,
  report: FileBarChart,
  delay: Timer,
  aggregate: ChartNoAxesCombined,
  http_request: Globe,
};
export type BlockData = Record<string, unknown> & {
  definition: Definition;
  label: string;
  summary: string;
  status: string;
  count?: number;
  attempt?: number;
  readOnly: boolean;
};
export type StudioNode = Node<BlockData, "block">;
export default memo(function BlockNode({
  data,
  selected,
}: NodeProps<StudioNode>) {
  const d = data.definition,
    Icon = icons[d.type] || Database;
  return (
    <div
      className={"block " + (selected ? "is-selected " : "") + data.status}
      style={{ "--accent": d.color } as React.CSSProperties}
    >
      {d.inputs.map((p) => (
        <Handle
          key={p}
          type="target"
          position={Position.Left}
          id={p}
          isConnectable={!data.readOnly}
          aria-label="Giriş bağlantısı"
        />
      ))}
      <div className="block-top">
        <span className="block-symbol">
          <Icon size={20} />
        </span>
        <div>
          <span>{d.category.toLocaleUpperCase("tr")}</span>
          <strong>{data.label || d.title}</strong>
        </div>
        <span className="block-dots">···</span>
      </div>
      <p>{data.summary || d.description}</p>
      <div className="block-foot">
        <span className={"state " + data.status}>
          {data.status === "succeeded" ? (
            <Check size={11} />
          ) : data.status === "running" ? (
            <LoaderCircle size={11} className="spin" />
          ) : data.status === "failed" ? (
            <AlertTriangle size={11} />
          ) : data.status === "skipped" ? (
            <Minus size={11} />
          ) : (
            <span className="state-dot" />
          )}
          {labels[data.status] || "Hazır"}
        </span>
        <small>
          {data.count !== undefined ? data.count + " kayıt" : "v1.0"}
        </small>
      </div>
      {d.outputs.map((p, i) => (
        <Handle
          key={p}
          type="source"
          position={Position.Right}
          id={p}
          isConnectable={!data.readOnly}
          style={
            d.outputs.length > 1
              ? {
                  top: 58 + i * 57,
                  background: p === "true" ? "#69ceb0" : "#bca072",
                }
              : {}
          }
          aria-label={p + " çıkışı"}
        />
      ))}
      {d.type === "condition" && (
        <>
          <span className="port-label true">EVET</span>
          <span className="port-label false">HAYIR</span>
        </>
      )}
    </div>
  );
});
