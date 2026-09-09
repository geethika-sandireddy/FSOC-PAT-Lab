import { useState, useEffect, useRef, useCallback } from "react";

export type TrackState =
  | "SEARCHING"
  | "TENTATIVE"
  | "LOCKED"
  | "DEGRADED_LOCK"
  | "COASTING"
  | "REACQUIRING"
  | "LOST"
  | "DISCONNECTED";

export interface CandidateDetail {
  u: number;
  v: number;
  area: number;
  circularity: number;
  snr: number;
  ml_score: number;
  track_id?: number | null;
  track_age?: number;
}

export interface Telemetry {
  t: number;
  state: TrackState | string;
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
  gimbal_pan: number;
  gimbal_tilt: number;
  v_pan: number;
  v_tilt: number;
  slew_spd: number;
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
  // Optical link budget metrics
  rx_power: number;
  snr: number;
  margin: number;
  ber: number;
  pointing_error_urad: number;
  atm_loss: number;
  tracking_quality: number;
  temperature: number;
  humidity: number;
  wind_speed: number;
  tx_power: number;
  wavelength: number;
  distance: number;
  data_rate: number;
  // Real camera viewport & PS diagnostics
  beacon_uv: [number, number] | null;
  boresight_uv: [number, number];
  distractors_uv: [number, number, number][];
  cand_list_uv: [number, number][];
  candidates_detail?: CandidateDetail[];
  screen_w?: number;
  screen_h?: number;
  cam_center_uv?: [number, number];
  hfov_deg?: number;
  vfov_deg?: number;
  platform_mode?: string;
  atmosphere_name?: string;
  atmosphere_allowed?: boolean;
  target_shape?: string;
  target_size?: number;
  target_count?: number;
  motion_type?: string;
  gimbal_max_pan?: number;
  gimbal_max_tilt?: number;
  noise_types?: string[];
  last_reacq_s?: number | null;
  mean_reacq_s?: number | null;
  // Performance KPIs
  fps: number;
  acq_time: number | null;
  retention_pct: number;
  connected: boolean;
}

export interface HistoryPoint {
  t: number;
  rxPower: number;
  snr: number;
  ber: number;
  pointingError: number;
  atmLoss: number;
  state: string;
}

const WS_URL =
  typeof window !== "undefined"
    ? `ws://${window.location.hostname || "localhost"}:8000/ws`
    : "ws://localhost:8000/ws";
const API_URL =
  typeof window !== "undefined"
    ? `http://${window.location.hostname || "localhost"}:8000`
    : "http://localhost:8000";

export function useTelemetry() {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const [retryCount, setRetryCount] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);

  const sendCmd = useCallback((cmd: Record<string, unknown>) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(cmd));
    }
  }, []);

  const setPreset = useCallback(
    (name: string) => {
      sendCmd({ action: "set_preset", preset: name });
      fetch(`${API_URL}/preset/${name}`, { method: "POST" }).catch(() => {});
    },
    [sendCmd]
  );

  const resetSim = useCallback(() => {
    sendCmd({ action: "reset" });
    fetch(`${API_URL}/reset`, { method: "POST" }).catch(() => {});
  }, [sendCmd]);

  const toggleRunning = useCallback(() => {
    sendCmd({ action: "pause" });
    fetch(`${API_URL}/pause`, { method: "POST" }).catch(() => {});
  }, [sendCmd]);

  const setDisturbance = useCallback(
    (key: string, value: number) => {
      sendCmd({ action: "set_disturbance", [key]: value });
      fetch(`${API_URL}/disturbance`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: value }),
      }).catch(() => {});
    },
    [sendCmd]
  );

  const setOpticalParams = useCallback(
    (params: Record<string, number>) => {
      sendCmd({ action: "set_optical_params", ...params });
      fetch(`${API_URL}/optical_params`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      }).catch(() => {});
    },
    [sendCmd]
  );

  const triggerStress = useCallback(
    (scenarioId: string) => {
      sendCmd({ action: "trigger_stress", scenario_id: scenarioId });
    },
    [sendCmd]
  );

  const setPlatformMode = useCallback(
    (platform: string) => {
      sendCmd({ action: "set_platform", platform });
    },
    [sendCmd]
  );

  const setAtmosphere = useCallback(
    (atmosphere: string) => {
      sendCmd({ action: "set_atmosphere", atmosphere });
    },
    [sendCmd]
  );

  const setFov = useCallback(
    (hfov: number, vfov?: number) => {
      sendCmd({ action: "set_fov", hfov, vfov });
    },
    [sendCmd]
  );

  const setScreenSize = useCallback(
    (w: number, h: number) => {
      sendCmd({ action: "set_screen_size", w, h });
    },
    [sendCmd]
  );

  const setMotionType = useCallback(
    (motion: string) => {
      sendCmd({ action: "set_motion", motion });
    },
    [sendCmd]
  );

  const setTargetParams = useCallback(
    (params: { shape?: string; size?: number; count?: number; initial?: any }) => {
      sendCmd({ action: "set_target", ...params });
    },
    [sendCmd]
  );

  const setGimbalLimits = useCallback(
    (max_pan?: number, max_tilt?: number) => {
      sendCmd({ action: "set_gimbal", max_pan, max_tilt });
    },
    [sendCmd]
  );

  const setNoiseTypes = useCallback(
    (noise_types: string[]) => {
      sendCmd({ action: "set_noise_types", noise_types });
    },
    [sendCmd]
  );

  const injectOcclusion = useCallback(
    (duration: number = 1.0) => {
      sendCmd({ action: "inject_occlusion", duration });
    },
    [sendCmd]
  );

  useEffect(() => {
    aliveRef.current = true;

    function connect() {
      if (!aliveRef.current) return;
      setConnecting(true);

      try {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!aliveRef.current) {
            ws.close();
            return;
          }
          setConnected(true);
          setConnecting(false);
          setRetryCount(0);
        };

        ws.onmessage = (event) => {
          try {
            const data: Telemetry = JSON.parse(event.data);
            setTelemetry(data);

            setHistory((prev) => {
              const pt: HistoryPoint = {
                t: data.t,
                rxPower: data.rx_power,
                snr: data.snr,
                ber: data.ber,
                pointingError: data.pointing_error_urad,
                atmLoss: data.atm_loss,
                state: data.state,
              };
              return [...prev.slice(-179), pt];
            });
          } catch (e) {
            console.error("Telemetry parse error:", e);
          }
        };

        ws.onerror = () => {
          // Handled in onclose
        };

        ws.onclose = () => {
          wsRef.current = null;
          if (!aliveRef.current) return;
          setConnected(false);
          setConnecting(false);
          setRetryCount((c) => c + 1);

          // Retry connection after 1.5s
          reconnectTimeoutRef.current = setTimeout(connect, 1500);
        };
      } catch (err) {
        setConnected(false);
        setConnecting(false);
        setRetryCount((c) => c + 1);
        reconnectTimeoutRef.current = setTimeout(connect, 1500);
      }
    }

    connect();

    return () => {
      aliveRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return {
    telemetry,
    history,
    connected,
    connecting,
    retryCount,
    setPreset,
    resetSim,
    toggleRunning,
    setDisturbance,
    setOpticalParams,
    triggerStress,
    setPlatformMode,
    setAtmosphere,
    setFov,
    setScreenSize,
    setMotionType,
    setTargetParams,
    setGimbalLimits,
    setNoiseTypes,
    injectOcclusion,
  };
}
