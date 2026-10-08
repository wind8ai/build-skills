import { useEffect, useState, type ReactNode } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  useReactFlow,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Check,
  LockKeyhole,
  LoaderCircle,
  ChevronDown,
  ArrowUpRight,
  AlertCircle,
} from "lucide-react";
import type { Data, Definition, Description } from "./api";
export const stateLabels: Record<string, string> = {
  blocked: "等待前序节点",
  ready: "可以处理",
  waiting: "需要你处理",
  running: "正在运行",
  success: "已完成",
  failed: "需要处理",
  cancelled: "已取消",
  skipped: "本次无需",
};
type CardData = {
  definition: Definition;
  status: string;
  selected: boolean;
  index: number;
  body: ReactNode;
  onSelect: (id: string) => void;
};
type Card = Node<CardData, "workflow">;
function WorkflowNode({ data }: NodeProps<Card>) {
  const status = data.status;
  return (
    <article
      className={`workflow-card ${data.selected ? "expanded" : ""} ${status}`}
    >
      <Handle type="target" position={Position.Left} />
      <button
        className="node-header"
        onClick={() => data.onSelect(data.definition.id)}
        aria-expanded={data.selected}
      >
        <span className="node-number">
          {status === "success" ? (
            <Check size={17} />
          ) : (
            String(data.index + 1).padStart(2, "0")
          )}
        </span>
        <span className="node-title">
          <strong>{data.definition.title}</strong>
          <small>{data.definition.subtitle}</small>
        </span>
        <ChevronDown size={17} className={data.selected ? "rotated" : ""} />
      </button>
      <div className="node-status">
        {status === "running" ? (
          <LoaderCircle className="spin" size={14} />
        ) : status === "failed" ? (
          <AlertCircle size={14} />
        ) : status === "blocked" ? (
          <LockKeyhole size={13} />
        ) : null}
        <span>{stateLabels[status] || status}</span>
        {data.definition.role && (
          <span className="role-tag">
            {data.definition.role === "builder" ? "构建模型" : "执行模型"}
          </span>
        )}
      </div>
      {data.selected ? (
        <div className="node-body nodrag nopan nowheel">{data.body}</div>
      ) : (
        <button
          className="node-open"
          onClick={() => data.onSelect(data.definition.id)}
        >
          查看表单与操作 <ArrowUpRight size={13} />
        </button>
      )}
      <Handle type="source" position={Position.Right} />
    </article>
  );
}
const nodeTypes = { workflow: WorkflowNode };
function Canvas({
  description,
  states,
  selected,
  onSelect,
  body,
  focusKey,
}: {
  description: Description;
  states: Data;
  selected: string;
  onSelect: (id: string) => void;
  body: (node: Definition) => ReactNode;
  focusKey: number;
}) {
  const flow = useReactFlow();
  const [dimensions, setDimensions] = useState<
    Record<string, { width: number; height: number }>
  >({});
  const rows = [...new Set(description.nodes.map((n) => n.position.y))].sort(
    (a, b) => a - b,
  );
  const selectedRow = description.nodes.find((n) => n.id === selected)?.position
    .y;
  const offsets = new Map<number, number>();
  let offset = 0;
  for (const row of rows) {
    offsets.set(row, offset);
    offset += (row === selectedRow ? 460 : 170) + 70;
  }
  const position = (n: Definition) => ({
    x: n.position.x,
    y: offsets.get(n.position.y) || 0,
  });
  useEffect(() => {
    const n = description.nodes.find((n) => n.id === selected);
    if (n)
      void flow.setCenter(position(n).x + 180, position(n).y + 210, {
        zoom: 1,
        duration: 400,
      });
  }, [selected, description.source_sha256, focusKey]);
  const nodes: Card[] = description.nodes.map((definition, index) => ({
    id: definition.id,
    type: "workflow",
    position: position(definition),
    draggable: false,
    measured: dimensions[definition.id],
    data: {
      definition,
      status: states[definition.id]?.status || "blocked",
      selected: selected === definition.id,
      index,
      body: body(definition),
      onSelect,
    },
  }));
  const edges = description.edges.map((e) => ({
    ...e,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed, color: "#8298b8" },
    animated: states[e.target]?.status === "running",
    style: {
      stroke: states[e.source]?.status === "success" ? "#367cff" : "#c5cfdd",
      strokeWidth: 2,
    },
    labelStyle: { fontSize: 13, fill: "#52647c" },
  }));
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={(changes) => {
        const measured = changes.filter(
          (c) => c.type === "dimensions" && c.dimensions,
        );
        if (!measured.length) return;
        setDimensions((previous) => {
          const next = { ...previous };
          for (const change of measured) {
            if (change.type === "dimensions" && change.dimensions)
              next[change.id] = change.dimensions;
          }
          return next;
        });
      }}
      nodesConnectable={false}
      elementsSelectable={true}
      minZoom={0.35}
      maxZoom={1.3}
      defaultViewport={{ x: 20, y: 30, zoom: 1 }}
      ariaLabelConfig={{
        "controls.zoomIn.ariaLabel": "放大流程",
        "controls.zoomOut.ariaLabel": "缩小流程",
        "controls.fitView.ariaLabel": "查看整个流程",
      }}
    >
      <Background color="#cbd5e3" gap={24} size={1} />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(n) =>
          (n.data as CardData).status === "success" ? "#337bef" : "#cbd6e6"
        }
      />
    </ReactFlow>
  );
}
export default function WorkflowCanvas(props: Parameters<typeof Canvas>[0]) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
