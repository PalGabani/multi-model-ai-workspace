export type User = { id: string; email: string; display_name: string };
export type Workspace = {
  id: string;
  name: string;
  role: string;
  default_model_id: string | null;
  monthly_budget_usd: number | null;
  allowed_model_ids: string[] | null;
};
export type Model = {
  id: string;
  provider_id: string;
  label: string;
  description: string;
  input_cost_per_million: number;
  output_cost_per_million: number;
  context_window: number;
  enabled: boolean;
  available: boolean;
};
export type Conversation = {
  id: string;
  title: string;
  mode: "chat" | "compare";
  created_at: string;
  updated_at: string;
};
export type Message = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  model_id: string | null;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number | null;
  estimated_cost_usd: number;
  status: "complete" | "streaming" | "failed" | "stopped";
  created_at: string;
};
export type Usage = {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  average_latency_ms: number;
  failed_requests: number;
  by_model: {
    model_id: string;
    label: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
    average_latency_ms: number;
    failed_requests: number;
  }[];
};
export type StreamEvent = {
  type: "start" | "token" | "complete" | "error" | "retry";
  model_id?: string;
  message_id?: string;
  text?: string;
  message?: string;
  input_tokens?: number;
  output_tokens?: number;
  latency_ms?: number;
  estimated_cost_usd?: number;
};

const tokenKey = "modelspace-access-token";

export function getToken() {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(tokenKey) ?? "";
}

export function setToken(token: string) {
  window.sessionStorage.setItem(tokenKey, token);
}

export function clearToken() {
  window.sessionStorage.removeItem(tokenKey);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string; message?: string };
    throw new Error(payload.detail ?? payload.message ?? `Request failed (${response.status}).`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function consumeSse(
  response: Response,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
) {
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(payload.detail ?? `Request failed (${response.status}).`);
  }
  if (!response.body) throw new Error("Streaming is unavailable in this browser.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const messages = pending.split(/\r?\n\r?\n/);
      pending = messages.pop() ?? "";
      for (const message of messages) {
        const data = message
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (data) onEvent(JSON.parse(data) as StreamEvent);
      }
      if (done) break;
    }
  } finally {
    if (signal.aborted) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
