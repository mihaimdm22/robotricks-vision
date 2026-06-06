/**
 * Typed client for the CatRanger FastAPI control plane.
 *
 * One origin source of truth: NEXT_PUBLIC_API_BASE (default http://localhost:8080).
 * REST + the MJPEG <img> + the control WebSocket all derive from it, so there is
 * no Next.js rewrite / proxy in the path (the WS upgrade through a dev proxy is
 * flaky — talking straight to FastAPI is robust). For phone/LAN access, set
 * NEXT_PUBLIC_API_BASE to the host machine's LAN IP.
 */

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080"
).replace(/\/$/, "");

export const VIDEO_URL = `${API_BASE}/video`;

export function wsURL(): string {
  // http(s)://host -> ws(s)://host/ws
  return `${API_BASE.replace(/^http/, "ws")}/ws`;
}

/** Backend's typed error shape: never a stack trace to the operator. */
export type ApiError = {
  ok: false;
  code: string;
  problem: string;
  cause?: string;
  fix?: string;
};

export type ApiResult<T> = (T & { ok: true }) | ApiError;

async function req<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const r = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok && body?.ok !== false) {
      return {
        ok: false,
        code: `http_${r.status}`,
        problem: `request failed (${r.status})`,
        fix: "check the server is running and reachable",
      };
    }
    return body as ApiResult<T>;
  } catch {
    return {
      ok: false,
      code: "unreachable",
      problem: "cannot reach the control server",
      cause: `no response from ${API_BASE}`,
      fix: "start it with `catranger serve`, and check NEXT_PUBLIC_API_BASE",
    };
  }
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const get = <T>(path: string) => req<T>(path, { method: "GET" });

// ----------------------------------------------------------------- domain types
export type Mode = "IDLE" | "MANUAL" | "FOLLOW";

export type ModelInfo = {
  id: string;
  name: string;
  backend: string;
  dataset?: string;
};

export type EvalMetrics = Record<string, Record<string, number | boolean | null>>;

export type EvalStatus = {
  ok: true;
  state: "idle" | "running" | "done" | "error" | "cancelled";
  done: number;
  total: number | null;
  started_at: number | null;
  n_frames: number | null;
  error: string | null;
};

export type EvalReport = {
  ok: true;
  markdown: string;
  metrics: EvalMetrics;
  approach: string;
  n_frames: number;
};

export type DiscoverResult = {
  ok: true;
  serial: { target: string; label: string }[];
  ble_available: boolean;
  hint: string | null;
};

// --------------------------------------------------------------------- endpoints
export const api = {
  setMode: (mode: Mode) => post<{ mode: string }>("/api/mode", { mode }),
  estop: () => post("/api/estop"),
  reset: () => post("/api/reset"),
  getModels: () =>
    get<{ models: ModelInfo[]; active: string; status: string }>("/api/models"),
  selectModel: (id: string) =>
    post<{ model: string; status: string; warning?: string }>("/api/models/select", { id }),
  connectCamera: (spec: string) =>
    post<{ label: string; warning: string | null }>("/api/camera/connect", { spec }),
  disconnectCamera: () => post("/api/camera/disconnect"),
  connectRobot: (connection: string, target: string | null, baud: number) =>
    post<{ bridge: string; connected: boolean; warning: string | null }>("/api/robot/connect", {
      connection,
      target,
      baud,
    }),
  disconnectRobot: () => post("/api/robot/disconnect"),
  discover: () => get<DiscoverResult>("/api/robot/discover"),
  evalRun: (body: {
    source: string;
    approach: string;
    classes: string | null;
    max_frames: number;
    use_depth: boolean;
  }) => post<{ state: string }>("/api/eval/run", body),
  evalStatus: () => get<EvalStatus>("/api/eval/status"),
  evalReport: () => get<EvalReport>("/api/eval/report"),
  evalCancel: () => post<{ cancelled: boolean }>("/api/eval/cancel"),
};
