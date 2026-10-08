import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import {
  Boxes,
  Plus,
  RefreshCw,
  Upload,
  FolderOpen,
  GitBranch,
  Link2,
  FileText,
  Download,
  Copy,
  LoaderCircle,
  Play,
  Square,
  CircleHelp,
  CheckCheck,
  ExternalLink,
} from "lucide-react";
import WorkflowPipeline from "./WorkflowPipeline";
import { emptySettings, settingsFrom } from "./state";
import {
  api,
  duration,
  preview,
  type Data,
  type Definition,
  type Description,
} from "./api";

type Choice = {
  provider: string;
  model: string;
  reasoning_effort: string | null;
};
type LocalItem = {
  path: string;
  bytes: number;
  supported: boolean;
  reason: string;
  file: File;
};
const labels: Record<string, string> = {
  retry_parse: "重新解析材料",
  resume: "继续执行",
  retry_development: "重试开发失败项",
  retry_holdout: "重试保留失败项",
  cancel: "取消当前调用",
};

function ModelEditor({
  value,
  onChange,
  options,
  label,
}: {
  value: Choice;
  onChange: (c: Choice) => void;
  options: Data;
  label: string;
}) {
  const [custom, setCustom] = useState(false);
  const presets: Data[] = options.catalog || [];
  const index = presets.findIndex(
    (p) =>
      p.provider === value.provider &&
      p.model === value.model &&
      (p.reasoning_effort || null) === (value.reasoning_effort || null),
  );
  return (
    <div className="model-editor">
      <label>
        {label}
        <select
          aria-label={label}
          value={custom || index < 0 ? "custom" : String(index)}
          onChange={(e) => {
            if (e.target.value === "custom") {
              setCustom(true);
            } else {
              setCustom(false);
              const p = presets[Number(e.target.value)];
              onChange({
                provider: p.provider,
                model: p.model,
                reasoning_effort: p.reasoning_effort,
              });
            }
          }}
        >
          {presets.map((p, i) => (
            <option key={i} value={i}>
              {p.label}
            </option>
          ))}
          <option value="custom">自定义模型</option>
        </select>
      </label>
      <details open={custom || index < 0}>
        <summary>修改模型或思考等级</summary>
        <label>
          Agent 连接
          <select
            value={value.provider}
            onChange={(e) => onChange({ ...value, provider: e.target.value })}
          >
            {Object.entries(options.connections || {}).map(([name, p]) => (
              <option key={name} value={name}>
                {name} ({(p as Data).kind})
              </option>
            ))}
          </select>
        </label>
        <label>
          模型名称
          <input
            value={value.model}
            list="model-names"
            required={options.connections?.[value.provider]?.kind !== "command"}
            onChange={(e) => onChange({ ...value, model: e.target.value })}
          />
        </label>
        <label>
          思考等级
          <input
            value={value.reasoning_effort || ""}
            list="reasoning-levels"
            placeholder="Agent 默认值"
            pattern="[a-z][a-z0-9_-]*"
            onChange={(e) =>
              onChange({ ...value, reasoning_effort: e.target.value || null })
            }
          />
        </label>
      </details>
    </div>
  );
}

function ReviewForm({
  job,
  state,
  onSubmit,
}: {
  job: string;
  state: Data;
  onSubmit: (payload: Data) => Promise<void>;
}) {
  const key = `build-skills.flow-review.${job}.${state.brief_digest}`;
  const [answers, setAnswers] = useState<string[]>([]),
    [feedback, setFeedback] = useState(""),
    [saved, setSaved] = useState(false);
  useEffect(() => {
    try {
      const d = JSON.parse(sessionStorage.getItem(key) || "null");
      setAnswers(d?.answers || state.brief.questions.map(() => ""));
      setFeedback(d?.feedback || "");
      setSaved(!!d);
    } catch {
      setAnswers(state.brief.questions.map(() => ""));
      setFeedback("");
    }
  }, [key]);
  function save(a: string[], f: string) {
    setAnswers(a);
    setFeedback(f);
    try {
      sessionStorage.setItem(key, JSON.stringify({ answers: a, feedback: f }));
      setSaved(true);
    } catch {
      setSaved(false);
    }
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void onSubmit({ digest: state.brief_digest, answers, feedback });
      }}
    >
      {saved && (
        <p className="hint">回答草稿已保存在当前标签页，刷新可恢复。</p>
      )}
      {state.brief.questions.map((q: string, i: number) => (
        <label key={i}>
          {i + 1}. {q}
          <textarea
            rows={3}
            required
            maxLength={10000}
            placeholder="填写你的决定、范围或规则"
            value={answers[i] || ""}
            onChange={(e) => {
              const a = [...answers];
              a[i] = e.target.value;
              save(a, feedback);
            }}
          />
        </label>
      ))}
      {state.brief.questions.length > 0 && (
        <button
          type="button"
          className="secondary full"
          onClick={() =>
            save(
              state.brief.questions.map((_: string, i: number) =>
                answers[i]?.trim()
                  ? answers[i]
                  : "请采用满足目标的最简单、可逆的合理默认规则，在草案中说明，不扩展范围；真正阻塞的矛盾才继续询问。",
              ),
              feedback,
            )
          }
        >
          未回答问题采用合理默认规则
        </button>
      )}
      <details>
        <summary>查看范围、标准与场景</summary>
        <p className="prose">{state.brief.scope}</p>
        <ol>
          {state.brief.criteria.map((c: string, i: number) => (
            <li key={i}>{c}</li>
          ))}
        </ol>
        {["development", "holdout"].map((k) => (
          <div key={k}>
            <h4>{k === "development" ? "开发场景" : "独立保留场景"}</h4>
            {state.brief[k].map((s: Data) => (
              <details key={s.id}>
                <summary>{s.id}</summary>
                <p>{s.task}</p>
                {Object.entries(s.files).map(([n, t]) => (
                  <div key={n}>
                    <strong>{n}</strong>
                    <pre>{preview(String(t))}</pre>
                  </div>
                ))}
              </details>
            ))}
          </div>
        ))}
      </details>
      {(state.review_history || []).length > 0 && (
        <details>
          <summary>此前提交的回答</summary>
          {state.review_history.map((item: Data, i: number) => (
            <div key={i}>
              {item.answers.map((a: Data, j: number) => (
                <p key={j}>
                  {a.question}
                  <br />
                  {a.answer}
                </p>
              ))}
              {item.requested_changes && <p>{item.requested_changes}</p>}
            </div>
          ))}
        </details>
      )}
      <label>
        其他修改意见
        <textarea
          rows={2}
          maxLength={20000}
          placeholder="例如：只处理 UTF-8，不增加其他编码功能"
          value={feedback}
          onChange={(e) => save(answers, e.target.value)}
        />
      </label>
      <button
        disabled={!state.allowed_actions?.includes("review")}
        className="full"
      >
        <RefreshCw size={15} />
        {state.brief.questions.length
          ? "提交回答并更新草案"
          : "根据修改意见更新草案"}
      </button>
    </form>
  );
}

export default function App() {
  const [mobile, setMobile] = useState(window.innerWidth <= 900);
  useEffect(() => {
    const media = window.matchMedia("(max-width:900px)");
    const change = () => setMobile(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  const builtin = useRef<Description | null>(null);
  const [description, setDescription] = useState<Description | null>(null),
    [options, setOptions] = useState<Data | null>(null),
    [jobs, setJobs] = useState<Data[]>([]);
  const [job, setJob] = useState(
      new URLSearchParams(location.search).get("job") || "",
    ),
    [state, setState] = useState<Data | null>(null),
    [selected, setSelected] = useState("source"),
    [follow, setFollow] = useState(true),
    [focusKey, setFocusKey] = useState(0);
  const [settings, setSettings] = useState(emptySettings),
    [sourceKind, setSourceKind] = useState("files"),
    [local, setLocal] = useState<LocalItem[]>([]),
    [remote, setRemote] = useState<Data | null>(null),
    [checked, setChecked] = useState<string[]>([]),
    [url, setUrl] = useState(""),
    [ref, setRef] = useState(""),
    [search, setSearch] = useState(""),
    [material, setMaterial] = useState<Data | null>(null);
  const [pending, setPending] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [connected, setConnected] = useState(false);
  const handledFailure = useRef("");
  const inFlight = useRef(false),
    selectedJob = useRef(job),
    serial = useRef(0),
    applied = useRef(0),
    lastApproval = useRef(false),
    followRef = useRef(true);
  useEffect(() => {
    selectedJob.current = job;
  }, [job]);
  async function connect() {
    try {
      const [o, d, list] = await Promise.all([
        api("options"),
        api<Description>("workflow"),
        api<Data[]>("jobs"),
      ]);
      setOptions(o);
      builtin.current = d;
      if (!selectedJob.current) setDescription(d);
      setJobs(list);
      if (!options) {
        let draft: Data | null = null;
        try {
          draft = JSON.parse(
            sessionStorage.getItem("build-skills.flow-setup") || "null",
          );
        } catch {
          /* Unavailable browser storage does not block a new task. */
        }
        setSettings(draft?.settings || settingsFrom(o));
        if (!selectedJob.current && draft?.material) {
          setMaterial(draft.material);
          setSelected("configure");
        }
      }
      setConnected(true);
      setError("");
    } catch (e) {
      setConnected(false);
      setError(String(e instanceof Error ? e.message : e));
    }
  }
  useEffect(() => {
    void connect();
  }, []);
  async function refresh(id: string) {
    const ticket = ++serial.current;
    try {
      const s = await api(`jobs/${id}`);
      if (selectedJob.current !== id || ticket < applied.current) return;
      applied.current = ticket;
      setConnected(true);
      setState(s);
      if (s.workflow) setDescription(s.workflow);
      const firstApproval = !!s.approval && !lastApproval.current;
      lastApproval.current = !!s.approval;
      // One authoritative focus decision per snapshot. Terminal failures take
      // priority over initial approval, and manual inspection disables all of it.
      if (followRef.current) {
        if (s.delivery) setSelected("deliver");
        else if (s.error && !s.busy) {
          const key = `${id}:${s.operation?.id}:${s.calls}`;
          if (handledFailure.current !== key) {
            handledFailure.current = key;
            const failed = Object.entries(s.nodes || {}).find(
              ([, v]) =>
                ["failed", "cancelled"].includes((v as Data).status) &&
                (v as Data).actions?.length,
            );
            if (failed) setSelected(failed[0]);
          }
        } else if (s.busy) {
          const active = Object.entries(s.nodes || {}).find(
            ([, v]) => (v as Data).status === "running",
          );
          if (active) setSelected(active[0]);
        } else if (firstApproval) setSelected("build");
        else if (!s.approval && s.brief)
          setSelected((prev) =>
            ["source", "configure", "parse"].includes(prev) ? "review" : prev,
          );
      }
    } catch (e) {
      setConnected(false);
      setError(String(e instanceof Error ? e.message : e));
    }
  }
  useEffect(() => {
    setState(null);
    lastApproval.current = false;
    if (!job) return;
    selectedJob.current = job;
    void refresh(job);
    const timer = setInterval(() => void refresh(job), 2000);
    return () => clearInterval(timer);
  }, [job]);
  async function run(label: string, fn: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(label);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      inFlight.current = false;
      setPending("");
    }
  }
  function selectNode(id: string) {
    setSelected(id);
    setFocusKey((v) => v + 1);
    setFollow(false);
    followRef.current = false;
  }
  function chooseJob(id: string) {
    if (!id && builtin.current) setDescription(builtin.current);
    setJob(id);
    selectedJob.current = id;
    setSelected("review");
    setFollow(true);
    followRef.current = true;
    history.replaceState(null, "", id ? `?job=${id}` : location.pathname);
  }
  async function reset() {
    chooseJob("");
    setState(null);
    setMaterial(null);
    setLocal([]);
    setRemote(null);
    setChecked([]);
    setSelected("source");
    setError("");
    setNotice("");
    const o = await api("options");
    setOptions(o);
    setSettings(settingsFrom(o));
  }
  useEffect(() => {
    if (!options || job) return;
    try {
      sessionStorage.setItem(
        "build-skills.flow-setup",
        JSON.stringify({
          settings,
          material: material
            ? {
                id: material.id,
                files: material.files.map((f: Data) => ({
                  name: f.name,
                  bytes: f.bytes,
                })),
              }
            : null,
        }),
      );
    } catch {
      /* Files and server-side jobs remain available without browser storage. */
    }
  }, [settings, material, options, job]);
  const disabled = !!pending || !!state?.busy;
  const allowed = (id: string) =>
    !!state?.allowed_actions?.includes(id) && !pending;
  function setField(key: string, value: unknown) {
    setSettings((s) => ({ ...s, [key]: value }));
  }
  function readFiles(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    const types = options?.source_file_types || [];
    const items = files.map((file) => {
      const path = file.webkitRelativePath || file.name;
      const ext = "." + file.name.split(".").pop()?.toLowerCase();
      const excluded = path
        .split("/")
        .some(
          (p) =>
            [
              ".git",
              ".venv",
              "node_modules",
              "__pycache__",
              ".build-skills",
            ].includes(p) ||
            p === ".env" ||
            p.startsWith(".env."),
        );
      const ok =
        (types.includes(ext) || ["LICENSE", "NOTICE"].includes(file.name)) &&
        file.size <= 10000000 &&
        !excluded;
      return {
        path,
        bytes: file.size,
        supported: ok,
        reason: excluded
          ? "已排除本地环境或凭据文件"
          : file.size > 10000000
            ? "超过 10 MB"
            : "暂不支持此类型",
        file,
      };
    });
    setLocal(items);
    setRemote(null);
    setChecked([]);
    setMaterial(null);
    setSearch("");
  }
  async function importChosen() {
    await run("导入材料", async () => {
      let m: Data;
      if (remote) {
        m = await api(`sources/${remote.id}/select`, {
          method: "POST",
          body: JSON.stringify({ files: checked }),
        });
      } else {
        const form = new FormData();
        const chosen = local.filter((f) => checked.includes(f.path));
        chosen.forEach((item) =>
          form.append("files", item.file, item.file.name),
        );
        form.append("paths", JSON.stringify(chosen.map((item) => item.path)));
        m = await api("materials", { method: "POST", body: form });
      }
      setMaterial(m);
      setSelected("configure");
    });
  }
  async function jobAction(action: string, payload: Data = {}) {
    await run(labels[action] || action, async () => {
      await api(
        `jobs/${job}/${["review", "approve", "accept-materials"].includes(action) ? action : `actions/${action}`}`,
        { method: "POST", body: JSON.stringify(payload) },
      );
      if (action !== "cancel") {
        setFollow(true);
        followRef.current = true;
      }
      if (action === "approve") setSelected("build");
      if (action === "accept-materials") setSelected("review");
      await refresh(job);
    });
  }
  const items: Data[] = remote?.files || local;
  const sourceForm = (
    <>
      <div className="source-tabs">
        {[
          ["files", "文件", Upload],
          ["folder", "文件夹", FolderOpen],
          ["git", "Git", GitBranch],
          ["url", "文件链接", Link2],
        ].map(([id, title, Icon]) => {
          const Component = Icon as typeof Upload;
          return (
            <button
              key={String(id)}
              type="button"
              className={sourceKind === id ? "active" : ""}
              disabled={!!job || disabled}
              onClick={() => {
                setSourceKind(String(id));
                setLocal([]);
                setRemote(null);
                setChecked([]);
                setMaterial(null);
              }}
            >
              <Component size={15} />
              {String(title)}
            </button>
          );
        })}
      </div>
      {!job && (sourceKind === "files" || sourceKind === "folder") && (
        <label className="upload-box">
          <Upload size={25} />
          <strong>
            {sourceKind === "folder" ? "选择本地文件夹" : "选择本地文件"}
          </strong>
          <span>先查看文件树，再选取材料</span>
          <input
            type="file"
            multiple
            disabled={disabled}
            ref={(el) => {
              if (el && sourceKind === "folder")
                el.setAttribute("webkitdirectory", "");
              else if (el) el.removeAttribute("webkitdirectory");
            }}
            onChange={readFiles}
          />
        </label>
      )}
      {!job && (sourceKind === "git" || sourceKind === "url") && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run("读取来源", async () => {
              setRemote(
                await api("sources/url", {
                  method: "POST",
                  body: JSON.stringify({
                    kind: sourceKind,
                    url,
                    ref: sourceKind === "git" ? ref : "",
                  }),
                }),
              );
              setChecked([]);
              setLocal([]);
              setMaterial(null);
            });
          }}
        >
          <label>
            {sourceKind === "git" ? "公开 Git 仓库地址" : "直接文件链接"}
            <input
              type="url"
              required
              value={url}
              placeholder="https://…"
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
          {sourceKind === "git" && (
            <label>
              分支或标签（选填）
              <input
                value={ref}
                onChange={(e) => setRef(e.target.value)}
                placeholder="默认分支"
              />
            </label>
          )}
          <button className="secondary full" disabled={disabled}>
            <GitBranch size={15} />
            {pending === "读取来源"
              ? "正在读取（最多 45 秒）"
              : "读取来源文件树"}
          </button>
          <p className="hint">
            第一版支持公开 HTTP(S) 来源；不会执行仓库脚本。
          </p>
        </form>
      )}
      {job ? (
        <>
          <p className="hint">本次材料已冻结，修改材料请新建运行。</p>
          {state?.settings?.material && (
            <p className="mono">
              来源批次 {state.settings.material.slice(0, 8)}
            </p>
          )}
          {(state?.source_files || []).map((f: Data, i: number) => (
            <div key={i}>
              <p className="model-pill">{f.name}</p>
              {f.origin?.url && <p className="hint mono">{f.origin.url}</p>}
              {f.origin?.commit && (
                <p className="hint mono">
                  commit {f.origin.commit.slice(0, 12)}
                </p>
              )}
            </div>
          ))}
        </>
      ) : (
        items.length > 0 && (
          <>
            <div className="tree-head">
              <strong>文件树</strong>
              <span>{checked.length}/20 已选择</span>
            </div>
            <input
              aria-label="筛选材料路径"
              placeholder="筛选路径…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="file-tree">
              {items
                .filter((i) =>
                  i.path.toLowerCase().includes(search.toLowerCase()),
                )
                .map((item) => (
                  <label
                    className={`file-row ${!item.supported ? "muted" : ""}`}
                    key={item.path}
                    title={item.supported ? item.path : item.reason}
                  >
                    <input
                      type="checkbox"
                      disabled={
                        disabled ||
                        !item.supported ||
                        (checked.length >= 20 && !checked.includes(item.path))
                      }
                      checked={checked.includes(item.path)}
                      onChange={(e) =>
                        setChecked((list) =>
                          e.target.checked
                            ? [...list, item.path]
                            : list.filter((n) => n !== item.path),
                        )
                      }
                    />
                    <FileText size={14} />
                    <span>
                      {item.path}
                      <small>
                        {item.supported
                          ? `${(item.bytes / 1000).toFixed(1)} KB`
                          : item.reason}
                      </small>
                    </span>
                  </label>
                ))}
            </div>
            {remote?.commit && (
              <p className="hint mono">commit {remote.commit.slice(0, 12)}</p>
            )}
            <button
              className="full"
              disabled={!checked.length || disabled}
              onClick={() => void importChosen()}
            >
              <Upload size={15} />
              导入所选文件
            </button>
          </>
        )
      )}
      {material && (
        <p className="success-text">已导入 {material.files.length} 个文件</p>
      )}
    </>
  );
  function form(node: Definition): ReactNode {
    if (node.form === "source") return sourceForm;
    if (node.id === "configure" && job)
      return (
        <>
          <p className="hint">本次配置已固定，修改参数请新建运行。</p>
          <p className="prose">{state?.settings?.goal}</p>
          <h4>构建 · 评估 · 重构</h4>
          <p className="model-pill">
            {state?.settings?.builder?.model ||
              state?.settings?.providers?.[state?.settings?.roles?.build]
                ?.model ||
              "演示替身"}
          </p>
          <h4>执行模型</h4>
          {(state?.settings?.executors || state?.settings?.models || []).map(
            (c: any, i: number) => (
              <p className="model-pill" key={i}>
                {typeof c === "string"
                  ? state?.settings?.providers?.[c]?.model || c
                  : c.model || "演示替身"}{" "}
                · 执行项 {i + 1}
              </p>
            ),
          )}
          <div className="compact-stats">
            <span>
              最多 <b>{state?.settings?.max_rounds}</b> 轮
            </span>
            <span>
              每场景 <b>{state?.settings?.repetitions}</b> 次
            </span>
          </div>
          <p className="hint">
            模型调用超时{" "}
            {state?.settings?.agent_timeout_seconds || "沿用历史配置"} 秒
          </p>
        </>
      );
    if (node.id === "configure")
      return (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run("创建任务", async () => {
              if (!material) throw Error("请先导入所选材料");
              if (!settings.executors.length)
                throw Error("至少添加一个执行模型");
              const result = await api("jobs", {
                method: "POST",
                body: JSON.stringify({ ...settings, material: material.id }),
              });
              chooseJob(result.id);
              setSelected("parse");
              setJobs(await api<Data[]>("jobs"));
            });
          }}
        >
          <fieldset disabled={!!job || disabled}>
            <label>
              Skill 名称
              <input
                required
                pattern="[a-zA-Z0-9_-]+"
                value={settings.name}
                onChange={(e) => setField("name", e.target.value)}
              />
            </label>
            <label>
              构建目标
              <textarea
                rows={3}
                required
                value={settings.goal}
                onChange={(e) => setField("goal", e.target.value)}
              />
            </label>
            {options && (
              <>
                <ModelEditor
                  label="构建 · 评估 · 重构"
                  value={settings.builder}
                  options={options}
                  onChange={(v) => setField("builder", v)}
                />
                <h4>执行模型</h4>
                {settings.executors.map((value, i) => (
                  <div key={i}>
                    <ModelEditor
                      label={`执行项 ${i + 1}`}
                      value={value}
                      options={options}
                      onChange={(v) =>
                        setField(
                          "executors",
                          settings.executors.map((c, j) => (j === i ? v : c)),
                        )
                      }
                    />
                    <div className="inline-actions">
                      <button
                        type="button"
                        className="secondary small"
                        onClick={() =>
                          setField("executors", [...settings.executors, value])
                        }
                        disabled={settings.executors.length >= 20}
                      >
                        重复此模型
                      </button>
                      <button
                        type="button"
                        className="secondary small"
                        onClick={() =>
                          setField(
                            "executors",
                            settings.executors.filter((_, j) => j !== i),
                          )
                        }
                      >
                        移除
                      </button>
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  className="secondary full"
                  disabled={settings.executors.length >= 20}
                  onClick={() =>
                    setField("executors", [
                      ...settings.executors,
                      options.executors[0],
                    ])
                  }
                >
                  ＋ 添加执行项
                </button>
              </>
            )}
            <div className="number-grid">
              {[
                ["max_rounds", "Loop 轮次", 1, 100, 1],
                ["repetitions", "每场景重复次数", 1, 20, 1],
                ["minimum_score", "最低分数", 0, 1, 0.05],
                ["agent_timeout_seconds", "调用超时（秒）", 1, 7200, 1],
                ["parsing_timeout_seconds", "解析超时（秒）", 1, 7200, 1],
              ].map(([key, label, min, max, step]) => (
                <label key={String(key)}>
                  {String(label)}
                  <input
                    type="number"
                    required
                    min={Number(min)}
                    max={Number(max)}
                    step={Number(step)}
                    value={settings[key as keyof typeof settings] as number}
                    onChange={(e) =>
                      setField(String(key), Number(e.target.value))
                    }
                  />
                </label>
              ))}
            </div>
            <button
              type="button"
              className="secondary full"
              onClick={() =>
                void run("保存默认值", async () => {
                  const { name, goal, ...defaults } = settings;
                  setOptions(
                    await api("defaults", {
                      method: "PUT",
                      body: JSON.stringify(defaults),
                    }),
                  );
                  setNotice("默认配置已保存在本机，用于后续新任务。");
                })
              }
            >
              保存为默认配置
            </button>
            <button className="full" disabled={!material}>
              <Play size={15} />
              解析并核对材料
            </button>
          </fieldset>
          {job && state?.settings && (
            <p className="hint">
              本次配置已固定。构建：
              {state.settings.builder?.model || "演示替身"}；执行项{" "}
              {state.settings.executors?.length ||
                state.settings.models?.length ||
                1}
              。
            </p>
          )}
        </form>
      );
    if (node.form === "parse")
      return (
        <>
          {state?.parsing?.files?.map((f: Data) => (
            <details key={f.source} open={state.parsing.files.length === 1}>
              <summary>
                {f.name} · {f.status === "partial" ? "部分解析" : "已读取"}
              </summary>
              {f.warnings.map((w: string, i: number) => (
                <p className="warning" key={i}>
                  {w}
                </p>
              ))}
              <pre>{preview(f.text)}</pre>
            </details>
          ))}
          {allowed("accept_materials") && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void jobAction("accept-materials", {
                  digest: state?.parsing_digest,
                });
              }}
            >
              <label className="check">
                <input type="checkbox" required />
                我已核对文字和遗漏，确认采用这些材料
              </label>
              <button className="full">
                <CheckCheck size={15} />
                采用材料并生成草案
              </button>
            </form>
          )}
          {!state?.parsing && (
            <p className="hint">
              创建任务后，复杂文件由所选构建模型解析。文本直接读取。
            </p>
          )}
        </>
      );
    if (node.form === "review")
      return state?.brief && !state.approval ? (
        <ReviewForm
          key={`${job}:${state.brief_digest}`}
          job={job}
          state={state}
          onSubmit={(payload) => jobAction("review", payload)}
        />
      ) : (
        <p className="hint">
          材料核对后整理范围、标准和场景；已有决定会保留在问答历史中。
        </p>
      );
    if (node.form === "approve")
      return (
        <>
          {state?.brief && (
            <>
              <p className="prose">{state.brief.scope}</p>
              <div className="compact-stats">
                <span>
                  开发场景 <b>{state.brief.development.length}</b>
                </span>
                <span>
                  保留场景 <b>{state.brief.holdout.length}</b>
                </span>
              </div>
              <p className="hint">
                {state.brief.questions.length
                  ? `还有 ${state.brief.questions.length} 个问题，请在目标与问答节点处理。`
                  : "确认后按固定范围、模型与预算执行。"}
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void jobAction("approve", { digest: state.brief_digest });
                }}
              >
                <label className="check">
                  <input
                    type="checkbox"
                    required
                    disabled={!allowed("approve")}
                  />
                  我已审阅范围、标准和两类场景
                </label>
                <button disabled={!allowed("approve")} className="full">
                  <Play size={15} />
                  确认并开始构建
                </button>
              </form>
            </>
          )}
        </>
      );
    if (node.form === "deliver")
      return (
        <>
          {state?.delivery ? (
            <>
              <div className="delivery-success">
                <CheckCheck size={25} />
                <strong>Skill 已通过最终验证</strong>
                <p>交付包包含准确版本和完整报告。</p>
              </div>
              <label>
                本地交付地址
                <input readOnly value={state.delivery} />
              </label>
              <button
                className="secondary full"
                onClick={() =>
                  void run("复制地址", async () => {
                    await navigator.clipboard.writeText(state.delivery);
                    setNotice("已复制本地地址。");
                  })
                }
              >
                <Copy size={15} />
                复制地址
              </button>
              <a className="button full" href={`/api/jobs/${job}/download`}>
                <Download size={15} />
                下载 Skill ZIP
              </a>
            </>
          ) : (
            <p className="hint">独立保留验证通过后，才能下载交付包。</p>
          )}
          {job && Object.keys(state?.reports || {}).length > 0 && (
            <a
              className="button secondary full"
              href={`/api/jobs/${job}/report`}
            >
              <Download size={15} />
              下载测评结论
            </a>
          )}
          {Object.entries(state?.reports || {}).map(([name, r]) => (
            <details key={name}>
              <summary>
                {name.startsWith("holdout") ? "保留验证" : "开发评估"} ·{" "}
                {(r as Data).passed ? "通过" : "未通过"}
              </summary>
              {(r as Data).judgments?.map((j: Data, i: number) => (
                <p key={i}>
                  <b>{j.scenario}</b>
                  <br />
                  {j.judgment?.reason || j.error}
                </p>
              ))}
            </details>
          ))}
        </>
      );
    const call = state?.nodes?.[node.id]?.progress;
    return (
      <>
        {call && (
          <div className="progress-box">
            <LoaderCircle className="spin" size={19} />
            <div>
              <strong>已运行 {duration(call.elapsed_seconds)}</strong>
              <small>
                {call.timeout_seconds
                  ? `本次超时 ${call.timeout_seconds} 秒`
                  : "正在启动当前操作"}
              </small>
            </div>
          </div>
        )}
        <div className="compact-stats">
          <span>
            候选轮次 <b>{state?.round || 0}</b>
          </span>
          <span>
            模型调用 <b>{state?.calls || 0}</b>
          </span>
        </div>
        {["execute", "verify"].includes(node.id) &&
          state?.matrices?.[
            node.id === "verify" ? "holdout" : "development"
          ]?.map((r: Data, i: number) => (
            <p className="case-row" key={i}>
              <span>{r.scenario}</span>
              <b>{r.status === "completed" ? "完成" : "未完成"}</b>
            </p>
          ))}
        {["evaluate", "verify"].includes(node.id) &&
          Object.entries(state?.reports || {})
            .filter(([name]) =>
              node.id === "verify"
                ? name.startsWith("holdout")
                : name.startsWith("development"),
            )
            .map(([name, r]) => (
              <p
                className={(r as Data).passed ? "success-text" : "warning"}
                key={name}
              >
                {(r as Data).passed ? "场景评估通过" : "场景尚未通过"} ·{" "}
                {name.split("-").pop()} 版
              </p>
            ))}
        <p className="hint">
          {node.id === "verify"
            ? "保留质量失败需要新运行；仅基础设施失败可重试。"
            : node.id === "improve"
              ? "仅针对质量失败重构；权限或进程错误需修复环境后重试。"
              : "按固定范围运行，完成结果与证据保存在本机。"}
        </p>
      </>
    );
  }
  const states: Data = state?.nodes || {
    source: { status: material ? "success" : "ready" },
    configure: { status: material ? "ready" : "blocked" },
  };
  function body(node: Definition) {
    return (
      <>
        {states[node.id]?.status === "failed" && state?.error && (
          <p className="warning">{state.error}</p>
        )}
        {node.form !== "runtime" && states[node.id]?.progress && (
          <div className="progress-box">
            <LoaderCircle className="spin" size={19} />
            <div>
              <strong>
                已运行 {duration(states[node.id].progress.elapsed_seconds)}
              </strong>
              <small>
                本次超时{" "}
                {states[node.id].progress.timeout_seconds || "沿用配置"} 秒
              </small>
            </div>
          </div>
        )}
        {["failed", "cancelled"].includes(states[node.id]?.status) &&
          state?.failure && (
            <details>
              <summary>查看调用失败详情</summary>
              <p>
                {state.failure.stage} · 退出码{" "}
                {state.failure.exit_code ?? "未正常结束"}
              </p>
              <pre>{state.failure.stderr_excerpt || state.error}</pre>
              <p className="mono">{state.failure.path}</p>
            </details>
          )}
        {form(node)}
        {(states[node.id]?.actions || [])
          .filter((a: string) => Object.keys(labels).includes(a))
          .map((action: string) => (
            <button
              key={action}
              className={`full ${action === "cancel" ? "secondary danger" : ""}`}
              disabled={!!pending}
              onClick={() => void jobAction(action)}
            >
              {action === "cancel" ? <Square size={14} /> : <Play size={14} />}{" "}
              {labels[action]}
            </button>
          ))}
        {pending && selected === node.id && (
          <p className="hint">
            <LoaderCircle className="spin inline-icon" size={13} />
            {pending}…
          </p>
        )}
      </>
    );
  }
  const completed = Object.values(states).filter((s: any) =>
    ["success", "skipped"].includes(s.status),
  ).length;
  return (
    <>
      <header className="topbar">
        <a href="/" className="brand">
          <span className="brand-symbol">
            <Boxes size={24} />
          </span>
          <span>
            Skill Studio<small>本地流程工作台</small>
          </span>
        </a>
        <div className="top-actions">
          <span className={`connection ${connected ? "online" : ""}`}>
            {connected ? "本地连接已就绪" : "连接中断"}
          </span>
          <button
            className="secondary"
            onClick={() => void connect()}
            aria-label="重新连接"
          >
            <RefreshCw size={16} />
          </button>
          <button onClick={() => void run("新建运行", reset)}>
            <Plus size={16} />
            新建运行
          </button>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <h2>工作区</h2>
          <label>
            本地任务
            <select value={job} onChange={(e) => chooseJob(e.target.value)}>
              <option value="">新的构建流程</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.name} · {j.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <div className="sidebar-heading">
            流程节点{" "}
            <span>
              {completed}/{description?.nodes.length || 11}
            </span>
          </div>
          <nav aria-label="流程节点">
            {description?.nodes.map((n, i) => (
              <button
                key={n.id}
                className={selected === n.id ? "selected" : ""}
                aria-current={selected === n.id ? "step" : undefined}
                onClick={() => selectNode(n.id)}
              >
                <span
                  className={`rail-number ${states[n.id]?.status || "blocked"}`}
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span>{n.title}</span>
                {states[n.id]?.status === "running" && (
                  <LoaderCircle className="spin" size={13} />
                )}
              </button>
            ))}
          </nav>
          <div className="sidebar-note">
            <CircleHelp size={16} />
            <p>材料与产物保存在本机。只有通过保留验证的版本才能交付。</p>
          </div>
          <div className="dsl-label">
            <GitBranch size={14} />
            内置 Starlark 流程 · v{description?.version || 1}
          </div>
        </aside>
        <main>
          <div className="canvas-heading">
            <div>
              <p className="eyebrow">MATERIALS → VERIFIED SKILL</p>
              <h1>
                {state?.delivery
                  ? "交付已就绪"
                  : job
                    ? jobs.find((j) => j.id === job)?.name || "构建进行中"
                    : "构建一个可验证的 Skill"}
              </h1>
              <p>
                {mobile
                  ? "沿 Pipeline 配置与处理，点击步骤展开操作。"
                  : "沿 Pipeline 配置与处理，点击左侧步骤展开并定位。"}
              </p>
            </div>
            {job && (
              <div className="heading-actions">
                <button
                  className="secondary small"
                  onClick={() => {
                    const next = !follow;
                    setFollow(next);
                    followRef.current = next;
                    if (next) {
                      const nodes = Object.entries(state?.nodes || {});
                      const target = state?.delivery
                        ? "deliver"
                        : nodes.find(
                            ([, v]) => (v as Data).status === "running",
                          )?.[0] ||
                          nodes.find(
                            ([, v]) =>
                              ["failed", "cancelled", "waiting"].includes(
                                (v as Data).status,
                              ) && (v as Data).actions?.length,
                          )?.[0];
                      if (target) {
                        setSelected(target);
                        setFocusKey((v) => v + 1);
                      }
                    }
                  }}
                >
                  {follow ? "正在跟随节点" : "跟随当前节点"}
                </button>
                <span className="run-id">
                  RUN {job.slice(0, 8)} <ExternalLink size={12} />
                </span>
              </div>
            )}
          </div>
          {error && (
            <div className="banner error" role="alert">
              {error}
              <button onClick={() => setError("")} aria-label="关闭提示">
                ×
              </button>
            </div>
          )}
          {notice && (
            <div className="banner notice" role="status">
              {notice}
            </div>
          )}
          {state?.error && (
            <div className="banner error" role="alert">
              {state.error}
            </div>
          )}
          <div className={mobile ? "mobile-flow" : "canvas-shell"}>
            {description ? (
              <WorkflowPipeline
                description={description}
                states={states}
                selected={selected}
                onSelect={selectNode}
                focusKey={focusKey}
                body={body}
              />
            ) : (
              <div className="loading">
                <LoaderCircle className="spin" />
                连接服务以加载内置流程
              </div>
            )}
          </div>
          <footer>
            <span>源文件选取 → 人工确认 → 独立验证 → 准确版本导出</span>
            <span>
              {state?.busy
                ? "当前调用运行中"
                : state?.delivery
                  ? "验证完成"
                  : job
                    ? "任务已保存在本机"
                    : "等待导入材料"}
            </span>
          </footer>
        </main>
      </div>
      <datalist id="model-names">
        {options?.catalog?.map((p: Data, i: number) => (
          <option value={p.model} key={i} />
        ))}
      </datalist>
      <datalist id="reasoning-levels">
        {["low", "medium", "high", "xhigh", "max"].map((v) => (
          <option value={v} key={v} />
        ))}
      </datalist>
    </>
  );
}
