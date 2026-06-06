/**
 * Typed client for the CatRanger FastAPI control plane.
 *
 * Origin resolution (runtime, in this order):
 *   1. localStorage["catranger.apiBase"] — the operator's saved Backend URL, so a
 *      single build can point at any LAN box without a rebuild (phone access too).
 *   2. NEXT_PUBLIC_API_BASE              — build-time default (inlined at build).
 *   3. http://localhost:8080            — hardcoded fallback.
 * Resolved LAZILY inside each call (never at module load) and window-guarded: the
 * /console route prerenders server-side, where `localStorage` is undefined — an
 * unguarded read would throw at build. REST + the MJPEG <img> + the control
 * WebSocket all derive from it, so there is no Next.js rewrite/proxy in the path
 * (a dev proxy's WS upgrade is flaky — talking straight to FastAPI is robust).
 */

const API_BASE_KEY = "catranger.apiBase";
const DEFAULT_API_BASE = "http://localhost:8080";
const strip = (s: string) => s.replace(/\/$/, "");

/** Build-time default (NEXT_PUBLIC_API_BASE is statically inlined at `next build`). */
export const buildDefaultBase = strip(
  process.env.NEXT_PUBLIC_API_BASE || DEFAULT_API_BASE,
);

/** The operator's saved runtime override, or null. SSR-safe (null on the server). */
export function storedApiBase(): string | null {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(API_BASE_KEY);
  return v ? strip(v) : null;
}

/** Effective base: saved override > build default. Resolved on every use. */
export function apiBase(): string {
  return storedApiBase() ?? buildDefaultBase;
}

// Subscribers (the console's useSyncExternalStore) re-read the base when an
// override is saved/cleared — that's what drives the WS/MJPEG remount (R6).
const baseListeners = new Set<() => void>();

/** Subscribe to override changes. Returns an unsubscribe fn (useSyncExternalStore). */
export function subscribeApiBase(cb: () => void): () => void {
  baseListeners.add(cb);
  return () => baseListeners.delete(cb);
}

/** Persist a runtime override (a blank value clears it). No-op during SSR. */
export function setApiBase(url: string): void {
  if (typeof window === "undefined") return;
  const v = strip(url.trim());
  if (v) window.localStorage.setItem(API_BASE_KEY, v);
  else window.localStorage.removeItem(API_BASE_KEY);
  baseListeners.forEach((cb) => cb());
}

/** Drop the override, falling back to the build default. No-op during SSR. */
export function clearApiBase(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(API_BASE_KEY);
  baseListeners.forEach((cb) => cb());
}

export function videoURL(): string {
  return `${apiBase()}/video`;
}

export function wsURL(): string {
  // http(s)://host -> ws(s)://host/ws
  return `${apiBase().replace(/^http/, "ws")}/ws`;
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
  const base = apiBase();
  try {
    const r = await fetch(`${base}${path}`, {
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
      cause: `no response from ${base}`,
      fix: "start `catranger serve`, or set the Backend URL in the Connections tab",
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
