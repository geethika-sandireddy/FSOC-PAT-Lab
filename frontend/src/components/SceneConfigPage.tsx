import { useState } from "react";

interface Props {
  currentPreset: string;
  onSetPreset: (p: string) => void;
  onSetDisturbance: (k: string, v: number) => void;
  onSetPlatformMode?: (pm: string) => void;
  onSetAtmosphere?: (atm: string) => void;
  onSetFov?: (hfov: number, vfov?: number) => void;
  onSetTargetParams?: (params: any) => void;
  onSetMotionType?: (motion: string) => void;
  onSetGimbalLimits?: (pan?: number, tilt?: number) => void;
  onSetNoiseTypes?: (types: string[]) => void;
  onInjectOcclusion?: (dur?: number) => void;
  telemetry: any;
}

const PRESETS = ["EASY", "MODERATE", "HARD", "SEVERE", "ADVERSARIAL", "ISRO_RX"];

const PRESET_COLORS: Record<string, string> = {
  EASY: "#00d4aa",
  MODERATE: "#4a9eff",
  HARD: "#f0a500",
  SEVERE: "#ff7700",
  ADVERSARIAL: "#ff3c3c",
  ISRO_RX: "#be82ff",
};

const PLATFORMS = [
  { id: "SATELLITE_SATELLITE", label: "SAT-SAT", desc: "LEO/MEO Inter-Satellite (Vacuum Path · No Weather)", vacuum: true },
  { id: "UAV_SATELLITE", label: "UAV-SAT", desc: "Air-to-Space Uplink/Downlink (Tropospheric Turbulence)", vacuum: false },
  { id: "UAV_UAV", label: "UAV-UAV", desc: "Air-to-Air Terminal Link (Boundary Layer Wind & Scintillation)", vacuum: false },
];

const ATMOSPHERES = [
  { id: "CLEAR", label: "Clear", desc: "Baseline atmospheric transmission (1.5 dB)" },
  { id: "HAZE", label: "Haze", desc: "Aerosol scattering & mild contrast reduction" },
  { id: "FOG", label: "Fog", desc: "Severe Mie scattering & cloud veil attenuation" },
  { id: "RAIN", label: "Rain", desc: "Precipitation droplet streaks & severe optical fade" },
  { id: "LOW_LIGHT", label: "Low Light", desc: "Night operations with sensor gain boost" },
];

const MOTIONS = [
  { id: "straight_line", label: "Straight Line", badge: "PS MANDATORY" },
  { id: "circular", label: "Circular", badge: "PS MANDATORY" },
  { id: "figure_eight", label: "Figure 8", badge: "PS MANDATORY" },
  { id: "random", label: "Random Walk", badge: "PS MANDATORY" },
  { id: "spiral", label: "Spiral", badge: "PS OPTIONAL" },
  { id: "sinusoidal", label: "Sinusoidal", badge: "PS OPTIONAL" },
];

const TARGET_SHAPES = ["SQUARE", "CIRCLE", "SPOT"];

export default function SceneConfigPage({
  currentPreset,
  onSetPreset,
  onSetDisturbance,
  onSetPlatformMode,
  onSetAtmosphere,
  onSetFov,
  onSetTargetParams,
  onSetMotionType,
  onSetGimbalLimits,
  onSetNoiseTypes,
  onInjectOcclusion,
  telemetry,
}: Props) {
  const platform = telemetry?.platform_mode || "SATELLITE_SATELLITE";
  const atmosphere = telemetry?.atmosphere_name || "CLEAR";
  const isVacuum = platform === "SATELLITE_SATELLITE" || telemetry?.atmosphere_allowed === false;

  const [hfov, setLocalHfov] = useState(telemetry?.hfov_deg ?? 4.0);
  const [vfov, setLocalVfov] = useState(telemetry?.vfov_deg ?? 3.0);
  const [targetSize, setTargetSize] = useState(telemetry?.target_size ?? 10);
  const [targetShape, setTargetShape] = useState(telemetry?.target_shape ?? "SQUARE");
  const [targetCount, setTargetCount] = useState(telemetry?.target_count ?? 1);
  const [targetMotion, setTargetMotion] = useState(telemetry?.motion_type ?? "straight_line");
  const [maxPan, setMaxPan] = useState(telemetry?.gimbal_max_pan ?? 5.0);
  const [maxTilt, setMaxTilt] = useState(telemetry?.gimbal_max_tilt ?? 5.0);
  const [activeNoise, setActiveNoise] = useState<string[]>(
    telemetry?.noise_types || ["gaussian"]
  );

  const localDist = {
    turbulence: telemetry?.disturbances?.turbulence ?? 5,
    vibration: telemetry?.disturbances?.vibration ?? 2,
    sensor_noise: telemetry?.disturbances?.sensor_noise ?? 5,
    jerk_prob: telemetry?.disturbances?.jerk_prob ?? 0,
    beacon_fade: telemetry?.disturbances?.beacon_fade ?? 0,
  };

  const handleNoiseToggle = (type: string) => {
    let next: string[];
    if (activeNoise.includes(type)) {
      if (activeNoise.length === 1) return;
      next = activeNoise.filter((n) => n !== type);
    } else {
      next = [...activeNoise, type];
    }
    setActiveNoise(next);
    onSetNoiseTypes?.(next);
  };

  return (
    <div className="p-4 overflow-y-auto h-full flex flex-col gap-4" style={{ fontFamily: "var(--font-mono)" }}>
      {/* Top Banner: ISRO SIH26169 Parameter Compliance Badge */}
      <div
        className="p-3 rounded flex items-center justify-between"
        style={{
          background: "linear-gradient(90deg, rgba(0, 212, 255, 0.1) 0%, rgba(15, 23, 42, 0.6) 100%)",
          border: "1px solid rgba(0, 212, 255, 0.3)",
        }}
      >
        <div className="flex items-center gap-3">
          <span style={{ fontSize: 16 }}>🛰️</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#00d4ff", letterSpacing: "0.08em" }}>
              ISRO SIH26169 · COMPLIANCE & SCENARIO CONTROL CENTER
            </div>
            <div style={{ fontSize: 10, color: "#94a3b8" }}>
              Virtual Screen: 2000×2000 px · Camera: 640×480 @ ≥30 Hz · Real-Time CV & Pointing Physics
            </div>
          </div>
        </div>
        <div className="flex gap-4 items-center">
          <div className="text-right">
            <span style={{ fontSize: 9, color: "#64748b" }}>EMPIRICAL REACQUISITION</span>
            <div style={{ fontSize: 12, fontWeight: 700, color: telemetry?.last_reacq_s ? "#00ff88" : "#94a3b8" }}>
              {telemetry?.last_reacq_s != null ? `${telemetry.last_reacq_s.toFixed(2)}s` : "NOMINAL LOCKED"}
            </div>
          </div>
          <button
            onClick={() => onInjectOcclusion?.(1.5)}
            className="px-3 py-1.5 rounded text-xs font-bold transition-all"
            style={{
              background: "rgba(255, 45, 85, 0.2)",
              border: "1px solid #ff2d55",
              color: "#ff2d55",
              cursor: "pointer",
            }}
          >
            ⚡ SIMULATE TARGET LOSS (1.5s)
          </button>
        </div>
      </div>

      {/* Grid Row 1: Platform Mode + Atmosphere Gating */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Platform Modes */}
        <div className="p-4 rounded" style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)" }}>
          <div className="text-xs font-bold mb-1" style={{ color: "#00d4ff", letterSpacing: "0.08em" }}>
            1. PLATFORM MODE SELECTION (PS REQUIREMENT #9)
          </div>
          <div className="text-xs mb-3" style={{ color: "#64748b" }}>
            Dictates physical range, relative orbital dynamics, platform jitter, and atmosphere applicability.
          </div>
          <div className="grid grid-cols-3 gap-2 mb-3">
            {PLATFORMS.map((p) => {
              const active = platform === p.id;
              return (
                <button
                  key={p.id}
                  onClick={() => onSetPlatformMode?.(p.id)}
                  className="p-2.5 rounded text-left transition-all"
                  style={{
                    background: active ? "rgba(0, 212, 255, 0.15)" : "#0a0f1c",
                    border: `1px solid ${active ? "#00d4ff" : "#1a2340"}`,
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 700, color: active ? "#00d4ff" : "#dce3f0" }}>{p.label}</div>
                  <div style={{ fontSize: 9, color: active ? "#94a3b8" : "#475569", marginTop: 2 }}>{p.desc}</div>
                </button>
              );
            })}
          </div>
          {isVacuum ? (
            <div
              className="p-2 rounded flex items-center gap-2"
              style={{ background: "rgba(190, 130, 255, 0.1)", border: "1px solid rgba(190, 130, 255, 0.4)" }}
            >
              <span style={{ fontSize: 13 }}>🌌</span>
              <span style={{ fontSize: 10, color: "#be82ff" }}>
                <strong>SPACE VACUUM ACTIVE:</strong> Terrestrial weather is physically NOT applicable on SAT-SAT vacuum optical path. Atmosphere engine is hard-locked to CLEAR.
              </span>
            </div>
          ) : (
            <div
              className="p-2 rounded flex items-center gap-2"
              style={{ background: "rgba(0, 255, 136, 0.1)", border: "1px solid rgba(0, 255, 136, 0.3)" }}
            >
              <span style={{ fontSize: 13 }}>☁️</span>
              <span style={{ fontSize: 10, color: "#00ff88" }}>
                <strong>ATMOSPHERIC LINK ACTIVE:</strong> Atmospheric scintillation, haze, fog, and rain effects enabled on the beam path.
              </span>
            </div>
          )}
        </div>

        {/* Atmosphere Conditions */}
        <div className="p-4 rounded" style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)" }}>
          <div className="text-xs font-bold mb-1" style={{ color: isVacuum ? "#64748b" : "#00d4ff", letterSpacing: "0.08em" }}>
            2. ATMOSPHERIC CONDITIONS (PS REQUIREMENT #10) {isVacuum && "(LOCKED · VACUUM)"}
          </div>
          <div className="text-xs mb-3" style={{ color: "#64748b" }}>
            Applies physical scattering, contrast attenuation, droplet streaks, and link margin loss.
          </div>
          <div className="grid grid-cols-2 gap-2">
            {ATMOSPHERES.map((a) => {
              const active = atmosphere === a.id;
              return (
                <button
                  key={a.id}
                  disabled={isVacuum && a.id !== "CLEAR"}
                  onClick={() => onSetAtmosphere?.(a.id)}
                  className="p-2 rounded text-left transition-all"
                  style={{
                    background: active ? "rgba(0, 255, 136, 0.12)" : "#0a0f1c",
                    border: `1px solid ${active ? "#00ff88" : "#1a2340"}`,
                    cursor: isVacuum && a.id !== "CLEAR" ? "not-allowed" : "pointer",
                    opacity: isVacuum && a.id !== "CLEAR" ? 0.35 : 1,
                  }}
                >
                  <div style={{ fontSize: 11, fontWeight: 700, color: active ? "#00ff88" : "#dce3f0" }}>{a.label}</div>
                  <div style={{ fontSize: 9, color: "#64748b" }}>{a.desc}</div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Grid Row 2: Target Parameters + Motion Profiles */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Target Parameters */}
        <div className="p-4 rounded" style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)" }}>
          <div className="text-xs font-bold mb-1" style={{ color: "#00d4ff", letterSpacing: "0.08em" }}>
            3. TARGET CONFIGURATION (PS REQUIREMENTS #5 & #6)
          </div>
          <div className="text-xs mb-3" style={{ color: "#64748b" }}>
            Target shape (Square default), size in 5–20 px range, multiple targets (1–5), and initial location.
          </div>

          <div className="grid grid-cols-2 gap-4 mb-3">
            <div>
              <span className="text-xs text-slate-400 block mb-1">Target Shape:</span>
              <div className="flex gap-2">
                {TARGET_SHAPES.map((sh) => (
                  <button
                    key={sh}
                    onClick={() => {
                      setTargetShape(sh);
                      onSetTargetParams?.({ shape: sh });
                    }}
                    className="px-2.5 py-1 rounded text-xs transition-all"
                    style={{
                      background: targetShape === sh ? "rgba(0, 212, 255, 0.2)" : "#0a0f1c",
                      border: `1px solid ${targetShape === sh ? "#00d4ff" : "#1a2340"}`,
                      color: targetShape === sh ? "#00d4ff" : "#94a3b8",
                      fontWeight: targetShape === sh ? 700 : 400,
                      cursor: "pointer",
                    }}
                  >
                    {sh}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className="text-xs text-slate-400 block mb-1">Number of Targets:</span>
              <div className="flex gap-1.5">
                {[1, 2, 3, 4, 5].map((cnt) => (
                  <button
                    key={cnt}
                    onClick={() => {
                      setTargetCount(cnt);
                      onSetTargetParams?.({ count: cnt });
                    }}
                    className="w-7 h-6 rounded text-xs transition-all"
                    style={{
                      background: targetCount === cnt ? "rgba(0, 255, 136, 0.2)" : "#0a0f1c",
                      border: `1px solid ${targetCount === cnt ? "#00ff88" : "#1a2340"}`,
                      color: targetCount === cnt ? "#00ff88" : "#94a3b8",
                      fontWeight: targetCount === cnt ? 700 : 400,
                      cursor: "pointer",
                    }}
                  >
                    {cnt}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Target Size Slider (PS Range: 5-20 px) */}
          <div className="mb-3">
            <div className="flex justify-between text-xs mb-1">
              <span className="text-slate-400">Target Size (PS Range 5–20 px):</span>
              <span className="text-emerald-400 font-bold">{targetSize} × {targetSize} px</span>
            </div>
            <input
              type="range"
              min={5}
              max={20}
              step={1}
              value={targetSize}
              onChange={(e) => {
                const val = parseInt(e.target.value);
                setTargetSize(val);
                onSetTargetParams?.({ size: val });
              }}
              className="w-full"
            />
          </div>

          {/* Initial Target Position */}
          <div>
            <span className="text-xs text-slate-400 block mb-1">Initial Target Position:</span>
            <div className="flex gap-2">
              {[
                { id: "RANDOM", label: "Random (PS Default)" },
                { id: "CENTER", label: "Boresight Center (0,0)" },
              ].map((pos) => (
                <button
                  key={pos.id}
                  onClick={() => onSetTargetParams?.({ initial: pos.id })}
                  className="px-2.5 py-1 rounded text-xs transition-all"
                  style={{
                    background: "#0a0f1c",
                    border: "1px solid #1a2340",
                    color: "#94a3b8",
                    cursor: "pointer",
                  }}
                >
                  {pos.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Target Motion Profiles */}
        <div className="p-4 rounded" style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)" }}>
          <div className="text-xs font-bold mb-1" style={{ color: "#00d4ff", letterSpacing: "0.08em" }}>
            4. TARGET MOTION TRAJECTORIES (PS REQUIREMENT #7)
          </div>
          <div className="text-xs mb-3" style={{ color: "#64748b" }}>
            Governs the dynamic angular motion of the beacon line-of-sight across the virtual sensor.
          </div>
          <div className="grid grid-cols-2 gap-2">
            {MOTIONS.map((m) => {
              const active = targetMotion === m.id;
              return (
                <button
                  key={m.id}
                  onClick={() => {
                    setTargetMotion(m.id);
                    onSetMotionType?.(m.id);
                  }}
                  className="p-2 rounded text-left transition-all"
                  style={{
                    background: active ? "rgba(0, 212, 255, 0.15)" : "#0a0f1c",
                    border: `1px solid ${active ? "#00d4ff" : "#1a2340"}`,
                    cursor: "pointer",
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span style={{ fontSize: 11, fontWeight: 700, color: active ? "#00d4ff" : "#dce3f0" }}>
                      {m.label}
                    </span>
                    <span
                      style={{
                        fontSize: 8,
                        color: m.badge.includes("MANDATORY") ? "#00ff88" : "#64748b",
                        border: `1px solid ${m.badge.includes("MANDATORY") ? "rgba(0,255,136,0.3)" : "#1e293b"}`,
                        padding: "1px 4px",
                        borderRadius: 2,
                      }}
                    >
                      {m.badge}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Grid Row 3: Camera & Optics (FOV) + Gimbal Speed Constraints */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Camera & FOV */}
        <div className="p-4 rounded" style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)" }}>
          <div className="text-xs font-bold mb-1" style={{ color: "#00d4ff", letterSpacing: "0.08em" }}>
            5. CAMERA OPTICS & USER-DEFINED FOV (PS REQUIREMENTS #1, #2, #3, #4)
          </div>
          <div className="text-xs mb-3" style={{ color: "#64748b" }}>
            Virtual Screen: 2000×2000 px · Camera Center: (1000, 1000) px · Monochrome 640×480
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-400">Horizontal FOV:</span>
                <span className="text-cyan-400 font-bold">{hfov.toFixed(1)}°</span>
              </div>
              <input
                type="range"
                min={1.0}
                max={10.0}
                step={0.5}
                value={hfov}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  setLocalHfov(val);
                  onSetFov?.(val, vfov);
                }}
                className="w-full"
              />
            </div>
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-400">Vertical FOV:</span>
                <span className="text-cyan-400 font-bold">{vfov.toFixed(1)}°</span>
              </div>
              <input
                type="range"
                min={1.0}
                max={8.0}
                step={0.5}
                value={vfov}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  setLocalVfov(val);
                  onSetFov?.(hfov, val);
                }}
                className="w-full"
              />
            </div>
          </div>
          <div className="mt-2 text-right" style={{ fontSize: 9, color: "#64748b" }}>
            Effective Optical Resolution: ~{(640 / hfov).toFixed(0)} px/deg · Focal Length: ~{(320 / Math.tan((hfov * Math.PI) / 360)).toFixed(0)} px
          </div>
        </div>

        {/* Gimbal Rate Limits */}
        <div className="p-4 rounded" style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)" }}>
          <div className="text-xs font-bold mb-1" style={{ color: "#00d4ff", letterSpacing: "0.08em" }}>
            6. GIMBAL MAXIMUM SLEW LIMITS (PS REQUIREMENT #8)
          </div>
          <div className="text-xs mb-3" style={{ color: "#64748b" }}>
            PS Default: 5.0 °/s (Range 5.0–10.0 °/s). Servo dynamics strictly enforce rate & acceleration clamping.
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-400">Max Pan Slew:</span>
                <span className="text-emerald-400 font-bold">{maxPan.toFixed(1)} °/s</span>
              </div>
              <input
                type="range"
                min={5.0}
                max={10.0}
                step={0.5}
                value={maxPan}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  setMaxPan(val);
                  onSetGimbalLimits?.(val, maxTilt);
                }}
                className="w-full"
              />
            </div>
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-400">Max Tilt Slew:</span>
                <span className="text-emerald-400 font-bold">{maxTilt.toFixed(1)} °/s</span>
              </div>
              <input
                type="range"
                min={5.0}
                max={10.0}
                step={0.5}
                value={maxTilt}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  setMaxTilt(val);
                  onSetGimbalLimits?.(maxPan, val);
                }}
                className="w-full"
              />
            </div>
          </div>
          <div className="mt-2 text-right" style={{ fontSize: 9, color: "#64748b" }}>
            Actual Realized Velocities: Pan {telemetry?.v_pan?.toFixed(2) ?? "0.00"} °/s · Tilt {telemetry?.v_tilt?.toFixed(2) ?? "0.00"} °/s
          </div>
        </div>
      </div>

      {/* Grid Row 4: Disturbance Sliders & Noise Types Checkboxes */}
      <div className="p-4 rounded" style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)" }}>
        <div className="text-xs font-bold mb-1" style={{ color: "#00d4ff", letterSpacing: "0.08em" }}>
          7. DISTURBANCE ENGINE & NOISE CHANNELS (PS REQUIREMENT #11)
        </div>
        <div className="text-xs mb-3" style={{ color: "#64748b" }}>
          Select active noise injection types and adjust physical perturbation dials. Every control directly affects simulation physics.
        </div>

        {/* Noise Types Checkboxes */}
        <div className="flex gap-4 mb-4 p-2.5 rounded" style={{ background: "#0a0f1c", border: "1px solid #1a2340" }}>
          <span className="text-xs text-slate-400 self-center">Active Noise Types:</span>
          {[
            { id: "gaussian", label: "Gaussian Noise", color: "#4a9eff" },
            { id: "salt_pepper", label: "Salt & Pepper", color: "#f0a500" },
            { id: "poisson", label: "Poisson Shot Noise", color: "#be82ff" },
          ].map((n) => {
            const checked = activeNoise.includes(n.id);
            return (
              <label key={n.id} className="flex items-center gap-2 cursor-pointer text-xs">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => handleNoiseToggle(n.id)}
                  style={{ accentColor: n.color }}
                />
                <span style={{ color: checked ? n.color : "#64748b", fontWeight: checked ? 700 : 400 }}>
                  {n.label}
                </span>
              </label>
            );
          })}
        </div>

        {/* Sliders */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-slate-400">Turbulence (Scintillation):</span>
              <span className="text-cyan-400 font-bold">{localDist.turbulence} %</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={localDist.turbulence}
              onChange={(e) => onSetDisturbance("turbulence", parseInt(e.target.value))}
              className="w-full"
            />
          </div>
          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-slate-400">Platform Vibration:</span>
              <span className="text-cyan-400 font-bold">{localDist.vibration} %</span>
            </div>
            <input
              type="range"
              min={0}
              max={60}
              value={localDist.vibration}
              onChange={(e) => onSetDisturbance("vibration", parseInt(e.target.value))}
              className="w-full"
            />
          </div>
          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-slate-400">Sensor Noise Amplitude:</span>
              <span className="text-cyan-400 font-bold">{localDist.sensor_noise} %</span>
            </div>
            <input
              type="range"
              min={0}
              max={50}
              value={localDist.sensor_noise}
              onChange={(e) => onSetDisturbance("sensor_noise", parseInt(e.target.value))}
              className="w-full"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
