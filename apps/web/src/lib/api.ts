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
  // Same-origin proxy avoids cross-origin MJPEG repaint bugs in Chromium/Safari.
  const base = encodeURIComponent(apiBase());
  return `/api/catranger/video?backend=${base}`;
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
      const needsRestart =
        r.status === 404 &&
        (path.includes("/robot/flash") || path.startsWith("/api/cats"));
      const fix = needsRestart
        ? "restart `catranger serve` (or `make web`) so the backend loads the latest API routes"
        : "check the server is running and reachable";
      const problem =
        r.status === 404 && path.includes("/robot/flash")
          ? "flash API not found on the control server"
          : r.status === 404 && path.startsWith("/api/cats")
            ? "cat library API not found — backend is out of date"
            : `request failed (${r.status})`;
      return {
        ok: false,
        code: `http_${r.status}`,
        problem,
        fix,
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
const patch = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) });
const del = <T>(path: string) => req<T>(path, { method: "DELETE" });

// ----------------------------------------------------------------- domain types
export type Mode = "IDLE" | "MANUAL" | "FOLLOW";

export type ModelInfo = {
  id: string;
  name: string;
  backend: string;
  dataset?: string;
  notes?: string;
  source?: string;
  run_kind?: string;
  trained_at?: string;
  status?: string;
  metric?: number | null;
  metric_key?: string | null;
  duration_s?: number | null;
  summary?: string;
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

export type FlashReadiness = {
  ok: boolean;
  arduino_cli: string | null;
  sketch_dir: string;
  fqbn: string;
  problem?: string;
  fix?: string;
};

export type FlashStatus = {
  ok: true;
  state: "idle" | "running" | "done" | "error";
  elapsed_s?: number | null;
  port?: string | null;
  error?: string | null;
  result?: { ok: boolean; log?: string; problem?: string; fix?: string };
};

/** Camera sensor/lens profile — picks the intrinsics + (un)distortion model. */
export type CameraProfile = "go2_1080p" | "tapo_c211";

export type CameraConnectResult = {
  ok: true;
  label: string;
  warning?: string;
  camera_profile: string;
  calibrated: boolean;
  ptz_available?: boolean;
};

export type SonarCalibrateResult = {
  ok: boolean;
  scale?: number;
  old_fy?: number;
  new_fy?: number;
  n_samples?: number;
  pred_m_mean?: number;
  gt_m_mean?: number;
  baseline_m?: number;
  profile?: string;
  dry_run?: boolean;
  calibrated?: boolean;
  camera_profile?: string;
  warning?: string;
  code?: string;
  problem?: string;
  fix?: string;
};

// ---- training (CV tab) ----
export type TrainKind = "prepare" | "train" | "autoresearch";

export type TrainReadiness = {
  ok: true;
  ml_available: boolean;
  dataset_ready: boolean;
  running: boolean;
  eval_running: boolean;
  idle: boolean;
};

export type TrainStatus = {
  ok: true;
  state: "idle" | "running" | "done" | "error" | "cancelled";
  kind: string | null;
  started_at: number | null;
  elapsed_s: number | null;
  epoch: number | null;
  total_epochs: number | null;
  log_tail: string;
  rc: number | null;
  error: string | null;
  summary: string | null;
};

export type TrainReport = {
  ok: true;
  kind: string;
  status: string;
  rc: number | null;
  metric: number | null;
  metric_key: string | null;
  metrics: Record<string, unknown>; // winner dict incl. nested `overrides`
};

export type TrainHistoryRun = {
  ts: string; // sortable stamp "YYYYMMDD-HHMMSS-<suffix>" from catranger.history
  kind: string;
  status: string;
  metric: number | null;
  metric_key: string | null;
  duration_s: number | null;
  summary: string | null;
  dir: string;
};

// --------------------------------------------------------------------- endpoints
export const api = {
  setMode: (mode: Mode) => post<{ mode: string }>("/api/mode", { mode }),
  estop: () => post("/api/estop"),
  reset: () => post("/api/reset"),
  getModels: () =>
    get<{ ok: true; models: ModelInfo[]; active: string; status: string }>(
      "/api/models",
    ),
  selectModel: (id: string) =>
    post<{ model: string; status: string; warning?: string }>("/api/models/select", { id }),
  connectCamera: (spec: string, camera?: CameraProfile) =>
    post<CameraConnectResult>("/api/camera/connect", camera ? { spec, camera } : { spec }),
  disconnectCamera: () => post("/api/camera/disconnect"),
  calibrateWithSonar: (body: {
    camera?: CameraProfile;
    baseline_m?: number;
    duration_s?: number;
    dry_run?: boolean;
  }) => post<SonarCalibrateResult>("/api/calibrate/sonar", body),
  ptz: (pan: number, tilt: number) =>
    post<{ throttled?: boolean }>("/api/camera/ptz", { pan, tilt }),
  ptzPreset: (name: string) => post("/api/camera/ptz/preset", { name }),
  connectRobot: (connection: string, target: string | null, baud: number) =>
    post<{ bridge: string; connected: boolean; warning: string | null }>("/api/robot/connect", {
      connection,
      target,
      baud,
    }),
  disconnectRobot: () => post("/api/robot/disconnect"),
  discover: () => get<DiscoverResult>("/api/robot/discover"),
  flashReadiness: () => get<FlashReadiness>("/api/robot/flash/readiness"),
  flashFirmware: (port: string | null) =>
    post<{ state: string; port?: string | null }>("/api/robot/flash", { port }),
  flashStatus: () => get<FlashStatus>("/api/robot/flash/status"),
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
  trainReadiness: () => get<TrainReadiness>("/api/train/readiness"),
  trainRun: (body: {
    kind: TrainKind;
    config?: string;
    epochs?: number;
    device?: string;
    source?: string;
  }) => post<{ state: string; kind: string }>("/api/train/run", body),
  trainStatus: () => get<TrainStatus>("/api/train/status"),
  trainReport: () => get<TrainReport>("/api/train/report"),
  trainCancel: () => post<{ cancelled: boolean }>("/api/train/cancel"),
  trainHistory: (limit = 50) =>
    get<{ runs: TrainHistoryRun[] }>(`/api/train/history?limit=${limit}`),
  trainPromote: (body: {
    weights?: string;
    run_dir?: string;
    model_id?: string;
    name?: string;
  }) =>
    post<{ weights: string; model_id: string; cli_changed: boolean }>("/api/train/promote", body),
  listCats: async (limit = 200) => {
    const res = await get<{ ok: true; cats: LibraryCat[] }>(`/api/cats?limit=${limit}`);
    if (!res.ok) throw new Error(res.problem);
    return res;
  },
  renameCat: async (id: number, name: string) => {
    const res = await patch<{ ok: true; id: number; name: string }>(`/api/cats/${id}`, { name });
    if (!res.ok) throw new Error(res.problem);
    return res;
  },
  deleteCat: async (id: number) => {
    const res = await del<{ ok: true; id: number }>(`/api/cats/${id}`);
    if (!res.ok) throw new Error(res.problem);
    return res;
  },
  findCat: (id: number, follow = true) =>
    post<{ ok: true; find_library_id: number; mode: string }>(`/api/cats/${id}/find`, { follow }),
};

export type LibraryCat = {
  id: number;
  name: string;
  last_tracker_id: number | null;
  last_conf: number | null;
  last_dist_m: number | null;
  last_bearing_deg: number | null;
  last_seen_ts: number | null;
  sighting_count: number;
  created_ts: number;
  has_thumb?: boolean;
  thumb_jpeg_b64?: string | null;
};
