export type Data = Record<string, any>;
export interface Definition {
  id: string;
  title: string;
  subtitle: string;
  position: { x: number; y: number };
  actions: string[];
  form: string;
  role: string;
}
export interface Description {
  id: string;
  version: number;
  source_sha256: string;
  nodes: Definition[];
  edges: { id: string; source: string; target: string; label: string }[];
}
export async function api<T = Data>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/${path}`, {
      ...init,
      headers: {
        "X-Build-Skills": "local",
        ...(init.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...init.headers,
      },
    });
  } catch {
    throw Error(
      "无法连接本地服务。服务恢复后点击重新连接，已保存的任务会保留。",
    );
  }
  const data = await response.json();
  if (!response.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data as T;
}
export function duration(value: number = 0) {
  return `${Math.floor(value / 60)} 分 ${Math.floor(value % 60)} 秒`;
}
export function preview(text: string) {
  return text.length > 10000
    ? text.slice(0, 10000) +
        "\n…仅预览前 10,000 字符，完整材料保存在本次任务中。"
    : text;
}
