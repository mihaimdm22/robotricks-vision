"use client";

/**
 * useTelemetry — the control WebSocket as a React hook.
 *
 * Owns: connect + auto-reconnect, the connecting/live/disconnected link state
 * (so the UI never renders stale numbers as if fresh), a 200ms token-lease
 * heartbeat (refreshes the MANUAL watchdog and holds the drive token), and the typed `nack` from the server (e.g. observer).
 *
 * StrictMode-safe: the socket + timers live in refs and are torn down in the
 * effect cleanup, so a double-mount doesn't leak sockets or duplicate timers.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { wsURL } from "./api";
import type { Mode } from "./api";
import type { StopReason } from "./stopReasons";

/** WS-B0 overlay contract: one detection, coords NORMALIZED to [0,1] of the frame. */
export type OverlayDet = {
  track_id: number | null;
  known_track_ids?: number[];
  cls: string;
  xyxy_norm: [number, number, number, number];
  conf: number;
  dist_m: number | null;
  dist_lo: number | null;
  dist_hi: number | null;
  bearing_deg: number;
  is_target: boolean;
  flags: string[];
};

/** WS-B0 per-frame overlay payload the console draws on a canvas over the MJPEG <img>. */
export type Overlay = {
  frame_id: number;
  frame_w: number;
  frame_h: number;
  dets: OverlayDet[];
  global_flags: string[];
};

/** Live cat cards for the picker (thumbnails refreshed ~2 Hz). */
export type CatCard = {
  id: number;
  conf: number;
  dist_m: number | null;
  bearing_deg: number;
  is_locked: boolean;
  is_preferred: boolean;
  thumb_jpeg_b64: string | null;
  in_view?: boolean;
  library_id?: number;
};

export type Telemetry = {
  mode: Mode;
  stop_reason: StopReason;
  estop: boolean;
  robot_connected: boolean;
  camera_connected: boolean;
  perception_available: boolean;
  n_cats: number;
  fps: number | null;
  target_id: number | null;
  target_ids?: number[];
  preferred_target_id?: number | null;
  cats?: CatCard[];
  find_library_id?: number | null;
  find_library_name?: string | null;
  target_dist_m: number | null;
  target_bearing_deg: number | null;
  gt_cm: number | null;
  model: string;
  model_status: string;
  model_error: string | null;
  camera: string;
  camera_profile: string | null;
  camera_calibrated: boolean;
  ptz_available?: boolean;
  robot: string;
  frame_age_ms: number | null;
  video_stale_ms: number;
  eval_running: boolean;
  train_running: boolean;
  you_are_controller: boolean;
  controller_id: number | null;
  overlay?: Overlay | null;
  /** CharBridge firmware peripheral toggles (null when not on char firmware). */
  peripherals?: { buzzer: boolean; rgb: boolean; lcd: boolean } | null;
  sonar_zone?: "red" | "yellow" | "green" | "cyan" | "blue" | null;
  sonar_obstacle?: boolean;
  buzzer_active?: boolean;
  sonar_range_cm?: number;
  sonar_display_cm?: number | null;
  sonar_no_echo?: boolean;
};

export type LinkState = "connecting" | "live" | "disconnected";
export type Nack = { code: string; problem: string; fix?: string };

export function useTelemetry() {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [link, setLink] = useState<LinkState>("connecting");
  const [nack, setNack] = useState<Nack | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const send = useCallback((obj: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }, []);

  useEffect(() => {
    let closed = false;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    let everLive = false;

    function connect() {
      // Only show "connecting" on the very first socket open — reconnects stay
      // on "disconnected" until telemetry returns so the UI doesn't flash.
      if (!everLive) setLink("connecting");
      const ws = new WebSocket(wsURL());
      wsRef.current = ws;
      ws.onopen = () => send({ type: "claim" });
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "telemetry") {
          everLive = true;
          setLink("live");
          setTelemetry(msg as Telemetry);
        } else if (msg.type === "nack") {
          setNack({ code: msg.code, problem: msg.problem, fix: msg.fix });
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setLink("disconnected");
        reconnect = setTimeout(connect, 1000);
      };
      ws.onerror = () => ws.close();
    }
    connect();

    const heartbeat = setInterval(() => {
      send({ type: "heartbeat" });
    }, 200);

    return () => {
      closed = true;
      if (reconnect) clearTimeout(reconnect);
      clearInterval(heartbeat);
      wsRef.current?.close();
    };
  }, [send]);

  const clearNack = useCallback(() => setNack(null), []);
  return { telemetry, link, nack, clearNack, send };
}
