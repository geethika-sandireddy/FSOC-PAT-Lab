import { useState, useEffect, useRef, useCallback } from "react";

export type TrackState =
  | "SEARCHING" | "TENTATIVE" | "LOCKED" | "DEGRADED_LOCK"
  | "COASTING" | "REACQUIRING" | "LOST";

export interface Telemetry {
  t: number;
  state: TrackState;
  preset: string;
  confidence: number;
  pointing_err_deg: number;
  est_err_deg: number;
  truth_az: number;
  truth_el: number;
  est_az: number;
  est_el: number;
  candidates: number;
  beacon_visible: boolean;
  in_fov: boolean;
  gimbal_sat_pan: number;
  gimbal_sat_tilt: number;
  vision_trust: number;
  model_trust: number;
  trust_mode: string;
  id_conf: number;
  pos_conf: number;
  pred_conf: number;
  pt_conf: number;
  sigma_px: number;
  false_lock: boolean;
  disturbances: {
    turbulence: number;
    vibration: number;
    sensor_noise: number;
    jerk_prob: number;
    beacon_fade: number;
  };
}

export interface HistoryPoint {
  t: number;
  pointing_err: number;
  est_err: number;
  confidence: number;
  state: TrackState;
}

const WS_URL = "ws://localhost:8000/ws";
const API_URL = "http://localhost:8000";

// Demo/offline telemetry for when the server is not reachable
function makeDemoTelemetry(tick: number, preset: string): Telemetry {
  const t = tick * 0.033;
  const angle = t * 0.8;
  const truth_az = Math.sin(angle) * 1.5;
  const truth_el = Math.cos(angle * 0.7) * 0.9;
  const noise = () => (Math.random() - 0.5) * 0.02;
  const est_az = truth_az + noise();
  const est_el = truth_el + noise();
  const pointing_err = Math.sqrt((truth_az - est_az) ** 2 + (truth_el - est_el) ** 2);
  const est_err = pointing_err * 0.8 + Math.random() * 0.005;
  const conf = 0.85 + Math.sin(t * 0.3) * 0.1 + (Math.random() - 0.5) * 0.05;
  const locked = tick > 15;
  return {
    t,
    state: tick < 8 ? "SEARCHING" : tick < 15 ? "TENTATIVE" : "LOCKED",
    preset,
    confidence: Math.max(0, Math.min(1, conf)),
    pointing_err_deg: pointing_err,
    est_err_deg: est_err,
    truth_az, truth_el, est_az, est_el,
    candidates: locked ? 1 : Math.floor(Math.random() * 3),
    beacon_visible: true,
    in_fov: true,
    gimbal_sat_pan: 0,
    gimbal_sat_tilt: 0,
    vision_trust: 0.72,
    model_trust: 0.45,
    trust_mode: "VISION_DOMINANT",
    id_conf: 0.88,
    pos_conf: 0.82,
    pred_conf: 0.79,
    pt_conf: 0.91,
    sigma_px: 3.2,
    false_lock: false,
    disturbances: { turbulence: 5, vibration: 2, sensor_noise: 5, jerk_prob: 0, beacon_fade: 0 },
  };
}

export function useTelemetry() {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [connected, setConnected] = useState(false);
  const [running, setRunningState] = useState(true);
  const [preset, setPresetState] = useState("EASY");
  const [demoMode, setDemoMode] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const demoTickRef = useRef(0);
  const demoTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const sendCmd = useCallback((cmd: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(cmd));
    }
  }, []);

  const setPreset = useCallback((name: string) => {
    setPresetState(name);
    sendCmd({ action: "set_preset", preset: name });
    // Also try REST fallback
    fetch(`${API_URL}/preset/${name}`, { method: "POST" }).catch(() => {});
  }, [sendCmd]);

  const resetSim = useCallback(() => {
    sendCmd({ action: "reset" });
    fetch(`${API_URL}/reset`, { method: "POST" }).catch(() => {});
  }, [sendCmd]);

  const toggleRunning = useCallback(() => {
    sendCmd({ action: "pause" });
    fetch(`${API_URL}/pause`, { method: "POST" }).catch(() => {});
    setRunningState(r => !r);
  }, [sendCmd]);

  const setDisturbance = useCallback((key: string, value: number) => {
    sendCmd({ action: "set_disturbance", [key]: value });
    fetch(`${API_URL}/disturbance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [key]: value }),
    }).catch(() => {});
  }, [sendCmd]);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let alive = true;

    function connect() {
      try {
        ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          setConnected(true);
          setDemoMode(false);
          if (demoTimerRef.current) {
            clearInterval(demoTimerRef.current);
            demoTimerRef.current = null;
          }
        };

        ws.onmessage = (ev) => {
          try {
            const data: Telemetry = JSON.parse(ev.data);
            setTelemetry(data);
            setPresetState(data.preset);
            setHistory(prev => {
              const next = [
                ...prev.slice(-239),
                {
                  t: data.t,
                  pointing_err: data.pointing_err_deg,
                  est_err: data.est_err_deg,
                  confidence: data.confidence,
                  state: data.state,
                },
              ];
              return next;
            });
          } catch {}
        };

        ws.onclose = () => {
          setConnected(false);
          wsRef.current = null;
          if (!alive) return;
          // Fall back to demo mode
          setDemoMode(true);
          if (!demoTimerRef.current) {
            demoTimerRef.current = setInterval(() => {
              demoTickRef.current += 1;
              const t = makeDemoTelemetry(demoTickRef.current, preset);
              setTelemetry(t);
              setHistory(prev => [
                ...prev.slice(-239),
                { t: t.t, pointing_err: t.pointing_err_deg, est_err: t.est_err_deg, confidence: t.confidence, state: t.state },
              ]);
            }, 33);
          }
          reconnectTimer = setTimeout(connect, 3000);
        };

        ws.onerror = () => { ws.close(); };
      } catch {
        setDemoMode(true);
        reconnectTimer = setTimeout(connect, 3000);
      }
    }

    connect();

    return () => {
      alive = false;
      clearTimeout(reconnectTimer);
      if (demoTimerRef.current) clearInterval(demoTimerRef.current);
      ws?.close();
    };
  }, []);  // eslint-disable-line

  return {
    telemetry, history, connected, running, preset, demoMode,
    setPreset, resetSim, toggleRunning, setDisturbance,
  };
}
