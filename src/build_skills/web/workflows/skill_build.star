# Maintainer-owned declarative workflow. No user code is executed at runtime.
def node(id, title, subtitle, row, col, actions, form="", role=""):
    return {"id": id, "title": title, "subtitle": subtitle, "position": {"x": col * 420, "y": row * 580}, "actions": actions, "form": form, "role": role}

def edge(source, target, label=""):
    return {"id": source + "-" + target, "source": source, "target": target, "label": label}

workflow = {
    "id": "skill-build",
    "version": 1,
    "nodes": [
        node("source", "导入材料", "选择文件、文件夹或 URL", 0, 0, ["import"], "source"),
        node("configure", "模型与流程", "统一构建模型 · 独立执行模型", 0, 1, ["create", "save_defaults"], "configure"),
        node("parse", "解析与核对", "冻结本次使用的材料", 0, 2, ["accept_materials", "retry_parse", "cancel"], "parse", "builder"),
        node("review", "目标与问答", "只澄清影响结果的决定", 1, 2, ["review", "resume", "cancel"], "review", "builder"),
        node("approve", "确认范围", "确认后才开始构建", 1, 1, ["approve"], "approve"),
        node("build", "构建 Skill", "生成第一版候选", 1, 0, ["resume", "cancel"], "runtime", "builder"),
        node("execute", "开发执行", "模型 × 场景 × 重复次数", 2, 0, ["retry_development", "cancel"], "runtime", "executors"),
        node("evaluate", "开发评估", "文件检查与模型判断", 2, 1, ["resume", "cancel"], "runtime", "builder"),
        node("improve", "重构 Skill", "根据失败证据改进", 3, 1, ["resume", "cancel"], "runtime", "builder"),
        node("verify", "保留验证", "独立场景验证准确版本", 2, 2, ["retry_holdout", "cancel"], "runtime", "executors"),
        node("deliver", "交付与导出", "通过验证才可获取交付包", 3, 2, ["download", "report"], "deliver"),
    ],
    "edges": [
        edge("source", "configure"), edge("configure", "parse"), edge("parse", "review"),
        edge("review", "approve"), edge("approve", "build"), edge("build", "execute"),
        edge("execute", "evaluate"), edge("evaluate", "verify", "通过"),
        edge("evaluate", "improve", "未通过 · 有剩余轮次"), edge("improve", "execute", "下一轮"),
        edge("verify", "deliver", "通过"),
    ],
}
