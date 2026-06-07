"use client";

/**
 * useTelemetry — the control WebSocket as a React hook.
 *
 * Owns: connect + auto-reconnect, the connecting/live/disconnected link state
 * (so the UI never renders stale numbers as if fresh), a 1s token-lease
 * heartbeat (holds the drive token; the DrivePad sends the faster MANUAL
 * watchdog heartbeat), and the typed `nack` from the server (e.g. observer).
 *
 * StrictMode-safe: the socket + timers live in refs and are torn down in the
 * effect cleanup, so a double-mount doesn't leak sockets or duplicate timers.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { wsURL } from "./api";
import type { Mode } from "./api";
import type { StopReason } from "./stopReasons";

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
  target_dist_m: number | null;
  target_bearing_deg: number | null;
  gt_cm: number | null;
  model: string;
  model_status: string;
  model_error: string | null;
  camera: string;
  camera_profile: string | null;
  camera_calibrated: boolean;
  robot: string;
  frame_age_ms: number | null;
  video_stale_ms: number;
  eval_running: boolean;
  train_running: boolean;
  you_are_controller: boolean;
  controller_id: number | null;
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

    function connect() {
      setLink("connecting");
      const ws = new WebSocket(wsURL());
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "telemetry") {
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

    const heartbeat = setInterval(() => send({ type: "heartbeat" }), 1000);

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
