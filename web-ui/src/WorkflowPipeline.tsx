import { useEffect, useRef, type ReactNode } from "react";
import {
  Check,
  LockKeyhole,
  LoaderCircle,
  ChevronDown,
  ArrowDown,
  ArrowRight,
  RotateCcw,
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

// Layout follows the validated main path, including archived descriptions whose
// display coordinates used the former canvas. Confirmation and run data stay intact.
export function pipelineSteps(description: Description): Definition[] {
  const steps: Definition[] = [];
  let id: string | undefined = "source";
  while (id && !steps.some((n) => n.id === id)) {
    const node = description.nodes.find((n) => n.id === id);
    if (!node) break;
    steps.push(node);
    id = description.edges.find(
      (e) => e.source === id && e.target !== "improve",
    )?.target;
  }
  return steps;
}

export default function WorkflowPipeline({
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
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const node = container.current?.querySelector<HTMLElement>(
        `[data-step="${selected}"]`,
      );
      if (!node) return;
      node.querySelector(".node-body")?.scrollTo({ top: 0 });
      node.focus({ preventScroll: true });
      node.scrollIntoView({
        block: "start",
        inline: "nearest",
        behavior: "auto",
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [selected, focusKey, description.source_sha256]);
  const steps = pipelineSteps(description);
  const improvement = description.nodes.find((n) => n.id === "improve");
  function card(node: Definition) {
    const status = states[node.id]?.status || "blocked";
    const expanded = node.id === selected;
    const index = description.nodes.findIndex((n) => n.id === node.id) + 1;
    return (
      <article
        data-step={node.id}
        tabIndex={-1}
        aria-label={`${node.title}步骤`}
        className={`workflow-card ${expanded ? "expanded" : ""} ${status}`}
      >
        <button
          className="node-header"
          aria-expanded={expanded}
          onClick={() => onSelect(node.id)}
        >
          <span className="node-number">{String(index).padStart(2, "0")}</span>
          <span className="node-title">
            <strong>{node.title}</strong>
            <small>{node.subtitle}</small>
          </span>
          <ChevronDown size={17} className={expanded ? "rotated" : ""} />
        </button>
        <div className="node-status">
          {status === "running" ? (
            <LoaderCircle className="spin" size={14} />
          ) : status === "success" ? (
            <Check size={14} />
          ) : status === "failed" ? (
            <AlertCircle size={14} />
          ) : status === "blocked" ? (
            <LockKeyhole size={13} />
          ) : null}
          <span>{stateLabels[status] || status}</span>
          {node.role && (
            <span className="role-tag">
              {node.id === "verify"
                ? "执行与评估"
                : node.role === "builder"
                  ? "构建模型"
                  : "执行模型"}
            </span>
          )}
        </div>
        {expanded ? (
          <div className="node-body">{body(node)}</div>
        ) : (
          <button className="node-open" onClick={() => onSelect(node.id)}>
            展开此步骤 <ChevronDown size={14} />
          </button>
        )}
      </article>
    );
  }
  return (
    <div
      className="pipeline-scroll"
      ref={container}
      aria-label="Skill 构建 Pipeline"
    >
      <div className="pipeline-intro">
        <span className="pipeline-label">PIPELINE</span>
        <p>沿主线完成构建。开发评估未通过时，重构后回到开发执行。</p>
      </div>
      <div className="pipeline-track">
        {steps.map((node, index) => (
          <div className="pipeline-row" key={node.id}>
            <div className="pipeline-main-step">
              {card(node)}
              {index < steps.length - 1 && (
                <div
                  className={`pipeline-connector ${states[node.id]?.status === "success" ? "complete" : ""}`}
                  aria-hidden="true"
                >
                  <ArrowDown size={19} />
                  {
                    description.edges.find(
                      (e) =>
                        e.source === node.id &&
                        e.target === steps[index + 1].id,
                    )?.label
                  }
                </div>
              )}
            </div>
            {node.id === "evaluate" && improvement && (
              <aside
                className="pipeline-branch"
                aria-label="开发评估失败后的重构支路"
              >
                <div className="branch-label">
                  <ArrowRight size={17} />
                  {
                    description.edges.find(
                      (e) => e.source === "evaluate" && e.target === "improve",
                    )?.label
                  }
                </div>
                {card(improvement)}
                <button
                  type="button"
                  className="loop-back"
                  onClick={() => onSelect("execute")}
                >
                  <RotateCcw size={15} />
                  改进后回到开发执行 <span>↑</span>
                </button>
              </aside>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
