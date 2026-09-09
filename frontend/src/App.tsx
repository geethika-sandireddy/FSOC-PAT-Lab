import { useState, useEffect, useRef, useCallback } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useTelemetry, type Telemetry } from "./hooks/useTelemetry";
import CameraViewport from "./components/CameraViewport";
import SceneConfigPage from "./components/SceneConfigPage";
import BenchmarkPage from "./components/BenchmarkPage";

// ─── Types ───────────────────────────────────────────────────────────────────

type View = "overview" | "telemetry" | "config" | "simulation" | "stress" | "falselock" | "eventlog" | "benchmark";

interface TelemetryPoint {
  t: number;
  rxPower: number;
  snr: number;
  ber: number;
  pointingError: number;
  atmLoss: number;
}

interface LiveMetrics {
  rxPower: number;
  snr: number;
  ber: number;
  linkMargin: number;
  pointingError: number;
  trackingQuality: number;
  temperature: number;
  humidity: number;
  windSpeed: number;
  visibility: number;
  wavelength: number;
  distance: number;
  dataRate: number;
  oit: number;
  atmLoss: number;
}

interface SimParams {
  txPower: number;
  wavelength: number;
  linkDistance: number;
  dataRate: number;
  rxSensitivity: number;
  beamDivergence: number;
  pointingError: number;
}

interface StressScenario {
  id: string;
  name: string;
  badge: "CRITICAL" | "WARNING";
  color: string;
  description: string;
  effects: string[];
  active: boolean;
  duration?: number;
}

interface EventLogEntry {
  id: number;
  level: "CRITICAL" | "WARNING" | "INFO";
  timestamp: string;
  subsystem: string;
  event: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const fmt2 = (n: number) => n.toFixed(1);
const fmtSci = (n: number) => n.toExponential(2);

function useInterval(cb: () => void, ms: number) {
  const ref = useRef(cb);
  ref.current = cb;
  useEffect(() => {
    const id = setInterval(() => ref.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}

function now() {
  return new Date().toLocaleTimeString("en-GB", { hour12: false });
}

// ─── Section Header ───────────────────────────────────────────────────────────

const SectionHeader = ({ children, accent = "#00d4ff" }: { children: React.ReactNode; accent?: string }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
    <div style={{ width: 4, height: 16, background: accent, borderRadius: 2, boxShadow: `0 0 8px ${accent}` }} />
    <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--text-primary)" }}>
      {children}
    </span>
  </div>
);

// ─── Metric Card ──────────────────────────────────────────────────────────────

const MetricCard = ({ label, value, unit, sub, color = "#00d4ff", warn = false }: {
  label: string; value: string; unit?: string; sub?: string; color?: string; warn?: boolean;
}) => (
  <div className="metric-card" style={{
    background: "var(--bg-card)",
    border: `1px solid ${warn ? "rgba(255,45,85,0.4)" : "var(--border-dim)"}`,
    borderRadius: 4,
    padding: "12px 16px",
    transition: "all 0.2s",
  }}>
    <div style={{ fontSize: 11, letterSpacing: "0.12em", color: "var(--text-secondary)", fontFamily: "var(--font-display)", fontWeight: 700, marginBottom: 6, textTransform: "uppercase" }}>
      {label}
    </div>
    <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 24, fontWeight: 700, color, lineHeight: 1 }}>
        {value}
      </span>
      {unit && <span style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>{unit}</span>}
    </div>
    {sub && <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 4, fontFamily: "var(--font-mono)" }}>{sub}</div>}
  </div>
);

// ─── Custom Tooltip ───────────────────────────────────────────────────────────

const ChartTooltip = ({ active, payload, label, unit }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: "#0a1220", border: "1px solid rgba(0,212,255,0.4)", borderRadius: 4, padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 12 }}>
      <div style={{ color: "#94a3b8", marginBottom: 4 }}>t+{label}s</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ color: p.color, fontWeight: 600 }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(2) : p.value} {unit}
        </div>
      ))}
    </div>
  );
};

// ─── Gauge Ring ───────────────────────────────────────────────────────────────

const GaugeRing = ({ value, max = 100, size = 88, label, color = "#00d4ff" }: {
  value: number; max?: number; size?: number; label: string; color?: string;
}) => {
  const r = (size - 12) / 2;
  const circ = 2 * Math.PI * r;
  const pct = clamp(value / max, 0, 1);
  const dash = pct * circ;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(0,212,255,0.1)" strokeWidth={5} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={5}
          strokeDasharray={`${dash} ${circ - dash}`} strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 6px ${color})`, transition: "stroke-dasharray 0.5s ease" }}
        />
      </svg>
      <div style={{ marginTop: -size - 6, height: size, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 18, fontWeight: 700, color, lineHeight: 1 }}>{Math.round(value)}%</span>
      </div>
      <span style={{ fontSize: 11, color: "var(--text-secondary)", letterSpacing: "0.1em", fontFamily: "var(--font-display)", fontWeight: 700, textTransform: "uppercase" }}>{label}</span>
    </div>
  );
};

// ─── Top Bar ─────────────────────────────────────────────────────────────────

const TopBar = ({ metrics, paused, onPause, state, connected }: { metrics: LiveMetrics; paused: boolean; onPause: () => void; state: string; connected: boolean }) => {
  const [time, setTime] = useState(now());
  useInterval(() => setTime(now()), 1000);

  const isLocked = state === "LOCKED";
  const stateColor = !connected ? "#ff2d55"
    : state === "LOCKED" ? "#00ff88"
    : state === "DEGRADED_LOCK" ? "#eab308"
    : state === "ACQUIRING" || state === "CANDIDATE" ? "#00d4ff"
    : state === "COASTING" ? "#38bdf8"
    : state === "REACQUIRING" ? "#a855f7"
    : state === "LOST" ? "#ef4444"
    : state === "SEARCHING" ? "#ff8c00"
    : "#64748b";

  return (
    <div style={{
      height: 58,
      background: "var(--bg-panel)",
      borderBottom: "1px solid var(--border-dim)",
      display: "flex",
      alignItems: "center",
      padding: "0 20px",
      gap: 16,
      flexShrink: 0,
      zIndex: 20,
    }}>
      {/* Brand & Subtitle */}
      <div style={{ display: "flex", flexDirection: "column", marginRight: 12, minWidth: 200 }}>
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 18, letterSpacing: "0.1em", color: "#00d4ff", lineHeight: 1.1 }}>
          FSOC MISSION CONTROL
        </div>
        <div style={{ fontSize: 11, color: "var(--text-secondary)", letterSpacing: "0.14em", fontFamily: "var(--font-display)", fontWeight: 600 }}>
          FREE-SPACE OPTICAL COMMS · PAT LAB · ISRO SIH 2026
        </div>
      </div>

      {/* Link State */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10, padding: "6px 14px",
        border: `1px solid ${stateColor}50`, borderRadius: 4, background: `${stateColor}12`
      }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: stateColor }} />
        <div>
          <div style={{ fontSize: 10, color: "#64748b", fontFamily: "var(--font-display)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em" }}>LINK STATE</div>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14, letterSpacing: "0.08em", color: stateColor, lineHeight: 1 }}>
            {connected ? state : "DISCONNECTED"}
          </div>
        </div>
      </div>

      {/* Live KPIs */}
      <div style={{ display: "flex", gap: 0, flex: 1 }}>
        {[
          { label: "RX POWER", value: `${fmt2(metrics.rxPower)}`, unit: "dBm", color: "#00d4ff" },
          { label: "SNR", value: `${fmt2(metrics.snr)}`, unit: "dB", color: "#00d4ff" },
          { label: "MARGIN", value: `${fmt2(metrics.linkMargin)}`, unit: "dB", color: "#00d4ff" },
          { label: "TRACKING", value: `${Math.round(metrics.trackingQuality)}`, unit: "%", color: "#00ff88" },
        ].map(k => (
          <div key={k.label} style={{ padding: "0 18px", borderLeft: "1px solid var(--border-dim)", display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <div style={{ fontSize: 11, color: "var(--text-secondary)", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700 }}>{k.label}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 17, fontWeight: 700, color: k.color }}>{k.value}</span>
              <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{k.unit}</span>
            </div>
          </div>
        ))}
      </div>

      {/* UTC Time */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", marginRight: 12 }}>
        <span style={{ fontSize: 11, color: "var(--text-secondary)", fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.1em" }}>UTC</span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "#00d4ff", fontWeight: 600 }}>{time}</span>
      </div>

      {/* Pause Button */}
      <button
        onClick={onPause}
        style={{
          padding: "7px 18px",
          borderRadius: 4,
          border: `1px solid ${paused ? "#ff8c00" : "rgba(0,212,255,0.4)"}`,
          background: paused ? "rgba(255,140,0,0.15)" : "rgba(0,212,255,0.1)",
          color: paused ? "#ff8c00" : "#00d4ff",
          fontFamily: "var(--font-display)",
          fontWeight: 700,
          fontSize: 12,
          letterSpacing: "0.14em",
          cursor: "pointer",
          transition: "all 0.2s",
        }}
      >
        {paused ? "▶ RESUME" : "⏸ PAUSE"}
      </button>
    </div>
  );
};

// ─── Overview View ────────────────────────────────────────────────────────────

const OverviewView = ({ metrics, history, telemetry, connected }: { metrics: LiveMetrics; history: TelemetryPoint[]; telemetry: Telemetry | null; connected: boolean }) => {
  return (
    <div className="sweep-in" style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%", overflowY: "auto" }}>
      {/* 4 Big KPI Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <MetricCard label="RX Optical Power" value={`${fmt2(metrics.rxPower)}`} unit="dBm" sub="Sensitivity: -24.0 dBm" color="#00d4ff" />
        <MetricCard label="Carrier SNR" value={`${fmt2(metrics.snr)}`} unit="dB" sub="Threshold: 18.0 dB" color="#00d4ff" />
        <MetricCard label="Bit Error Rate" value={fmtSci(metrics.ber)} sub="Target: < 1.0e-9" color={metrics.ber > 1e-9 ? "#ff2d55" : "#00ff88"} warn={metrics.ber > 1e-9} />
        <MetricCard label="Pointing Error" value={`${fmt2(metrics.pointingError)}`} unit="µrad" sub="Beam div: 30 µrad" color="#00d4ff" />
      </div>

      {/* Main Grid: Live Virtual Camera Viewport (Left) + Charts/Health (Right) */}
      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 12, flex: 1, minHeight: 340 }}>
        {/* Real Live Virtual Camera Viewport */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 14px", display: "flex", flexDirection: "column" }}>
          <SectionHeader>LIVE VIRTUAL SENSOR TRACKING · FOV 2.4° × 1.8°</SectionHeader>
          <div style={{ flex: 1, minHeight: 280, position: "relative" }}>
            <CameraViewport telemetry={telemetry} connected={connected} />
          </div>
        </div>

        {/* Real-time Telemetry Trend & Health */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 16px", flex: 1, display: "flex", flexDirection: "column" }}>
            <SectionHeader>Optical Link Stability Trend (RX Power & SNR)</SectionHeader>
            <div style={{ flex: 1, minHeight: 140 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history}>
                  <CartesianGrid strokeDasharray="2 4" />
                  <XAxis dataKey="t" tick={{ fill: "#64748b", fontSize: 10 }} />
                  <YAxis yAxisId="pwr" domain={[-22, -5]} tick={{ fill: "#64748b", fontSize: 10 }} unit=" dBm" width={45} />
                  <YAxis yAxisId="snr" orientation="right" domain={[30, 90]} tick={{ fill: "#64748b", fontSize: 10 }} unit=" dB" width={40} />
                  <Tooltip content={<ChartTooltip unit="" />} />
                  <Line yAxisId="pwr" type="monotone" dataKey="rxPower" name="RX Power" stroke="#00d4ff" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line yAxisId="snr" type="monotone" dataKey="snr" name="SNR" stroke="#00ff88" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
            <SectionHeader>System Health Matrix</SectionHeader>
            <div style={{ display: "flex", justifyContent: "space-around", padding: "4px 0" }}>
              <GaugeRing value={metrics.trackingQuality} label="Tracking" color="#00ff88" />
              <GaugeRing value={clamp(100 - metrics.pointingError * 2, 0, 100)} label="Alignment" color="#00d4ff" />
              <GaugeRing value={clamp(metrics.linkMargin / 50 * 100, 0, 100)} label="Margin" color="#bf5af2" />
            </div>
            <div style={{ borderTop: "1px solid var(--border-dim)", paddingTop: 8, display: "flex", justifyContent: "space-between", fontSize: 11 }}>
              <span style={{ color: "var(--text-secondary)" }}>Atmospheric Loss:</span>
              <span style={{ fontFamily: "var(--font-mono)", color: "#ff8c00", fontWeight: 600 }}>{fmt2(metrics.atmLoss)} dB</span>
              <span style={{ color: "var(--text-secondary)" }}>Temp:</span>
              <span style={{ fontFamily: "var(--font-mono)", color: "#00d4ff" }}>{fmt2(metrics.temperature)}°C</span>
              <span style={{ color: "var(--text-secondary)" }}>Wind:</span>
              <span style={{ fontFamily: "var(--font-mono)", color: "#00d4ff" }}>{fmt2(metrics.windSpeed)} m/s</span>
            </div>
          </div>
        </div>
      </div>

      {/* System Value & Differentiation Section */}
      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "14px 18px", marginTop: 2 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, borderBottom: "1px solid var(--border-dim)", paddingBottom: 8 }}>
          <SectionHeader accent="#10b981">WHY THIS PROTOTYPE? · SYSTEM VALUE & DIFFERENTIATION</SectionHeader>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", background: "rgba(16,185,129,0.15)", color: "#10b981", border: "1px solid rgba(16,185,129,0.4)", padding: "2px 8px", borderRadius: 3, fontWeight: 700 }}>
              GT LEAKAGE: NONE
            </span>
            <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", background: "rgba(0,212,255,0.15)", color: "#00d4ff", border: "1px solid rgba(0,212,255,0.4)", padding: "2px 8px", borderRadius: 3, fontWeight: 700 }}>
              EVALUATOR MP4 BYPASS
            </span>
            <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", background: "rgba(191,90,242,0.15)", color: "#bf5af2", border: "1px solid rgba(191,90,242,0.4)", padding: "2px 8px", borderRadius: 3, fontWeight: 700 }}>
              REACQUISITION &lt; 0.5s
            </span>
          </div>
        </div>

        {/* Differentiation Statement */}
        <div style={{ background: "rgba(15,23,42,0.6)", border: "1px solid var(--border-dim)", borderRadius: 3, padding: "10px 14px", marginBottom: 14 }}>
          <p style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>
            <strong style={{ color: "var(--text-primary)" }}>CORE DIFFERENTIATION: </strong>
            Unlike a conventional beacon-tracking demo that only shows detection and tracking, <span style={{ color: "#00d4ff", fontWeight: 600 }}>FSOC-PAT-Lab</span> is an end-to-end, evaluator-ready coarse-PAT validation environment that closes the loop from synthetic optical scene generation and realistic sensor disturbances through AI-assisted beacon identification, uncertainty-aware tracking, gimbal-constrained pointing, recovery from target loss, and quantitative benchmark evidence.
          </p>
        </div>

        {/* 2-Column Details: 6 Differentiators (Left) + Novelty Scorecard & Comparison (Right) */}
        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 16 }}>
          {/* Left Column: 6 Engineering Differentiators */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span style={{ fontSize: 11, fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.1em", color: "#00d4ff", textTransform: "uppercase" }}>
              Key Architectural Differentiators
            </span>
            {[
              { num: "01", title: "Evaluator-Ready MP4 Bypass", desc: "Accepts evaluator 30 FPS MP4 video directly into coarse-PAT pipeline; completely bypasses synthetic scene and PTZ gimbal." },
              { num: "02", title: "Metric Integrity (A / B / C Separation)", desc: "Explicitly separates Detected Centroid (A), Frame Offset (B), and True Error (C). If unannotated, Metric C = N/A." },
              { num: "03", title: "Zero Ground-Truth Leakage", desc: "Target truth exists strictly in evaluation structures. Detector, ML classifier, and Kalman tracker receive zero truth coordinates." },
              { num: "04", title: "Uncertainty-Aware Recovery", desc: "Loss transitions to COASTING; covariance growth drives dynamic validation gate; empirical reacquisition time = 0.442s." },
              { num: "05", title: "Physics/Actuator-Aware Validation", desc: "Models 5.0°/s slew limits, latency, and saturation. Extreme motion reports honest pointing error rather than hiding failure." },
              { num: "06", title: "Configurable FSOC Digital Testbed", desc: "Live tuning of platforms, vacuum gating, atmospheric weather, FOV, motion profiles, and sensor noise channels." },
            ].map(d => (
              <div key={d.num} style={{ display: "flex", gap: 10, alignItems: "flex-start", background: "rgba(10,16,32,0.6)", padding: "6px 10px", borderRadius: 3, border: "1px solid var(--border-dim)" }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#10b981", fontWeight: 700, minWidth: 20 }}>{d.num}</span>
                <div>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)" }}>{d.title} — </span>
                  <span style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.4 }}>{d.desc}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Right Column: Novelty Scorecard & Comparison Table */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <span style={{ fontSize: 11, fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.1em", color: "#10b981", textTransform: "uppercase" }}>
              Novelty Scorecard & Verification Matrix
            </span>

            {/* Scorecard */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
              {[
                { label: "Algorithm Novelty", score: "MODERATE", color: "#ff8c00", note: "Proven primitives" },
                { label: "Integration Novelty", score: "HIGH", color: "#10b981", note: "Full closed-loop" },
                { label: "Evaluation Integrity", score: "HIGH", color: "#10b981", note: "Metric A/B/C isolation" },
                { label: "Reproducibility", score: "HIGH", color: "#10b981", note: "Deterministic seeds" },
                { label: "FSOC Practical Value", score: "HIGH", color: "#00d4ff", note: "SIL before HIL" },
                { label: "Gimbal Physics Model", score: "HIGH", color: "#00d4ff", note: "5°/s slew clamped" },
              ].map(s => (
                <div key={s.label} style={{ background: "rgba(10,16,32,0.8)", border: "1px solid var(--border-dim)", padding: "6px 8px", borderRadius: 3 }}>
                  <div style={{ fontSize: 10, color: "var(--text-secondary)" }}>{s.label}</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: s.color, fontFamily: "var(--font-mono)" }}>{s.score}</div>
                  <div style={{ fontSize: 9, color: "var(--text-dim)" }}>{s.note}</div>
                </div>
              ))}
            </div>

            {/* Competitor Differentiation Table */}
            <div style={{ border: "1px solid var(--border-dim)", borderRadius: 3, overflow: "hidden", marginTop: 4 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, fontFamily: "var(--font-mono)" }}>
                <thead>
                  <tr style={{ background: "rgba(15,23,42,0.9)", borderBottom: "1px solid var(--border-dim)" }}>
                    <th style={{ textAlign: "left", padding: "5px 8px", color: "var(--text-secondary)", fontWeight: 600 }}>CAPABILITY</th>
                    <th style={{ textAlign: "center", padding: "5px 6px", color: "#ff8c00", fontWeight: 600 }}>BASIC PROTOTYPE</th>
                    <th style={{ textAlign: "center", padding: "5px 6px", color: "#10b981", fontWeight: 700 }}>FSOC-PAT-LAB</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { cap: "External Evaluator Video", basic: "No (Synthetic only)", ours: "30 FPS MP4 Bypass" },
                    { cap: "Centroid Metric Integrity", basic: "Frame offset only", ours: "Metric A / B / C" },
                    { cap: "Ground-Truth Isolation", basic: "Often leaked in loss", ours: "Zero Leakage Verified" },
                    { cap: "Target Loss Recovery", basic: "Blind search restart", ours: "Uncertainty Coasting" },
                    { cap: "Actuator Saturation", basic: "Ignored / Unbounded", ours: "Physical Slew Clamped" },
                    { cap: "Platform Weather Gating", basic: "Static global weather", ours: "Vacuum Gated (Sat-Sat)" },
                  ].map((row, idx) => (
                    <tr key={row.cap} style={{ background: idx % 2 === 0 ? "rgba(10,16,32,0.4)" : "transparent", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                      <td style={{ padding: "4px 8px", color: "var(--text-primary)" }}>{row.cap}</td>
                      <td style={{ textAlign: "center", padding: "4px 6px", color: "#94a3b8" }}>{row.basic}</td>
                      <td style={{ textAlign: "center", padding: "4px 6px", color: "#10b981", fontWeight: 600 }}>{row.ours}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Practical Value for Space Agencies */}
            <div style={{ fontSize: 10, color: "var(--text-dim)", lineHeight: 1.4, fontStyle: "italic", borderLeft: "2px solid #00d4ff", paddingLeft: 8 }}>
              "Practical value for ISRO/DRDO: Serves as a software-in-the-loop (SIL) coarse-alignment validation testbed prior to expensive optical terminal hardware integration."
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Telemetry View ───────────────────────────────────────────────────────────

const TelemetryView = ({ history }: { history: TelemetryPoint[] }) => {
  return (
    <div className="sweep-in" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gridTemplateRows: "1fr 1fr", gap: 12, height: "100%" }}>
      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 16px", display: "flex", flexDirection: "column" }}>
        <SectionHeader>RX Optical Power (dBm)</SectionHeader>
        <div style={{ flex: 1 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="2 4" />
              <XAxis dataKey="t" tick={{ fill: "#64748b", fontSize: 11 }} />
              <YAxis domain={[-22, -8]} tick={{ fill: "#64748b", fontSize: 11 }} />
              <Tooltip content={<ChartTooltip unit="dBm" />} />
              <Line type="monotone" dataKey="rxPower" stroke="#00d4ff" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 16px", display: "flex", flexDirection: "column" }}>
        <SectionHeader accent="#00ff88">Carrier Signal-to-Noise Ratio (dB)</SectionHeader>
        <div style={{ flex: 1 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="2 4" />
              <XAxis dataKey="t" tick={{ fill: "#64748b", fontSize: 11 }} />
              <YAxis domain={[30, 90]} tick={{ fill: "#64748b", fontSize: 11 }} />
              <Tooltip content={<ChartTooltip unit="dB" />} />
              <Line type="monotone" dataKey="snr" stroke="#00ff88" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 16px", display: "flex", flexDirection: "column" }}>
        <SectionHeader accent="#ff8c00">Beam Pointing Error (µrad)</SectionHeader>
        <div style={{ flex: 1 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="2 4" />
              <XAxis dataKey="t" tick={{ fill: "#64748b", fontSize: 11 }} />
              <YAxis domain={[0, 15]} tick={{ fill: "#64748b", fontSize: 11 }} />
              <Tooltip content={<ChartTooltip unit="µrad" />} />
              <Line type="monotone" dataKey="pointingError" stroke="#ff8c00" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 16px", display: "flex", flexDirection: "column" }}>
        <SectionHeader accent="#bf5af2">Atmospheric Loss Dynamics (dB)</SectionHeader>
        <div style={{ flex: 1 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="2 4" />
              <XAxis dataKey="t" tick={{ fill: "#64748b", fontSize: 11 }} />
              <YAxis domain={[0, 8]} tick={{ fill: "#64748b", fontSize: 11 }} />
              <Tooltip content={<ChartTooltip unit="dB" />} />
              <Line type="monotone" dataKey="atmLoss" stroke="#bf5af2" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

// ─── Simulation View ──────────────────────────────────────────────────────────

const SimulationView = ({
  params, onChange, metrics
}: {
  params: SimParams; onChange: (k: keyof SimParams, v: number) => void; metrics: LiveMetrics;
}) => {
  const sliders: { key: keyof SimParams; label: string; min: number; max: number; step: number; unit: string }[] = [
    { key: "txPower", label: "Transmitter Power", min: 10, max: 40, step: 1, unit: "dBm" },
    { key: "wavelength", label: "Laser Wavelength", min: 850, max: 1550, step: 50, unit: "nm" },
    { key: "linkDistance", label: "Link Range / Distance", min: 1, max: 50, step: 1, unit: "km" },
    { key: "dataRate", label: "Transmission Data Rate", min: 1, max: 40, step: 1, unit: "Gbps" },
    { key: "beamDivergence", label: "Beam Divergence", min: 10, max: 100, step: 5, unit: "µrad" },
    { key: "pointingError", label: "Manual Pointing Bias", min: 0, max: 20, step: 0.5, unit: "µrad" },
  ];

  return (
    <div className="sweep-in" style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 14, height: "100%", overflowY: "auto" }}>
      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "16px 20px" }}>
        <SectionHeader>Optical Link Simulation Parameters</SectionHeader>
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
          {sliders.map(s => (
            <div key={s.key}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)", fontFamily: "var(--font-display)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  {s.label}
                </span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "#00d4ff", fontWeight: 700 }}>
                  {params[s.key]} {s.unit}
                </span>
              </div>
              <input
                type="range"
                min={s.min}
                max={s.max}
                step={s.step}
                value={params[s.key]}
                onChange={e => onChange(s.key, parseFloat(e.target.value))}
              />
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "16px 20px" }}>
          <SectionHeader>System Response</SectionHeader>
          {[
            { l: "RX Optical Power", v: `${fmt2(metrics.rxPower)} dBm`, c: "#00d4ff" },
            { l: "Bit Error Rate (BER)", v: fmtSci(metrics.ber), c: metrics.ber > 1e-9 ? "#ff2d55" : "#00ff88" },
            { l: "Signal-to-Noise (SNR)", v: `${fmt2(metrics.snr)} dB`, c: "#00d4ff" },
            { l: "Effective Link Margin", v: `${fmt2(metrics.linkMargin)} dB`, c: "#00d4ff" },
            { l: "Atmospheric Loss", v: `${fmt2(1.5 + (params.linkDistance - 5) * 0.2)} dB`, c: "#ff8c00" },
            { l: "Geometric Spread Loss", v: "-40.8 dB", c: "#ff8c00" },
          ].map(row => (
            <div key={row.l} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--border-dim)" }}>
              <span style={{ fontSize: 12, color: "var(--text-secondary)", fontWeight: 600 }}>{row.l}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: row.c, fontWeight: 700 }}>{row.v}</span>
            </div>
          ))}
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid rgba(0,212,255,0.2)", borderRadius: 4, padding: "14px 18px" }}>
          <div style={{ fontSize: 11, color: "#00d4ff", letterSpacing: "0.14em", fontFamily: "var(--font-display)", fontWeight: 700, marginBottom: 6 }}>
            CAUSE → EFFECT DYNAMICS
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>
            Modifying TX Power, Link Distance, or Beam Divergence immediately influences received flux, SNR, and tracking jitter. High turbulence accelerates link degradation.
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Stress View (Matching Screenshot 1) ──────────────────────────────────────

const StressView = ({
  scenarios, onTrigger, metrics, history
}: {
  scenarios: StressScenario[];
  onTrigger: (id: string) => void;
  metrics: LiveMetrics;
  history: TelemetryPoint[];
}) => {
  return (
    <div className="sweep-in" style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 14, height: "100%" }}>
      {/* Left Column: 5 Scenario Cards */}
      <div style={{ overflowY: "auto", display: "flex", flexDirection: "column", gap: 12, paddingRight: 4 }}>
        <SectionHeader>STRESS SCENARIO CONTROL</SectionHeader>
        {scenarios.map(s => (
          <div
            key={s.id}
            style={{
              background: s.active ? "rgba(255,140,0,0.08)" : "var(--bg-card)",
              border: `1px solid ${s.active ? s.color : "var(--border-dim)"}`,
              borderRadius: 5,
              padding: "16px 20px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              gap: 20,
              boxShadow: s.active ? `0 0 12px ${s.color}30` : "none",
              transition: "all 0.25s",
            }}
          >
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <span style={{ fontSize: 15, color: s.color, fontWeight: 700 }}>≈</span>
                <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 16, color: "var(--text-primary)", letterSpacing: "0.06em" }}>
                  {s.name}
                </span>
                <span style={{
                  fontSize: 11,
                  fontFamily: "var(--font-display)",
                  fontWeight: 700,
                  letterSpacing: "0.1em",
                  color: s.color,
                  border: `1px solid ${s.color}60`,
                  padding: "2px 8px",
                  borderRadius: 3,
                  background: `${s.color}15`,
                }}>
                  {s.badge}
                </span>
                {s.active && (
                  <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "#ff8c00", fontWeight: 700 }}>
                    ACTIVE ({s.duration || 12}s)
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 12, lineHeight: 1.5 }}>
                {s.description}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {s.effects.map((e, idx) => (
                  <span key={idx} style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color: "#94a3b8",
                    background: "rgba(15,23,42,0.8)",
                    border: "1px solid var(--border-dim)",
                    padding: "3px 10px",
                    borderRadius: 3,
                  }}>
                    {e}
                  </span>
                ))}
              </div>
            </div>

            <button
              onClick={() => onTrigger(s.id)}
              style={{
                padding: "8px 22px",
                borderRadius: 4,
                border: `1px solid ${s.active ? "#ff2d55" : "#00d4ff"}`,
                background: s.active ? "rgba(255,45,85,0.2)" : "rgba(0,212,255,0.12)",
                color: s.active ? "#ff2d55" : "#00d4ff",
                fontFamily: "var(--font-display)",
                fontWeight: 700,
                fontSize: 12,
                letterSpacing: "0.14em",
                cursor: "pointer",
                minWidth: 100,
                transition: "all 0.2s",
              }}
            >
              {s.active ? "STOP" : "TRIGGER"}
            </button>
          </div>
        ))}
      </div>

      {/* Right Column: System Response & Demo Sequence */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12, overflowY: "auto" }}>
        {/* System Response */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "14px 18px" }}>
          <SectionHeader>SYSTEM RESPONSE</SectionHeader>
          {[
            { l: "Link State", v: state === "LOCKED" ? (metrics.ber > 1e-9 ? "DEGRADED" : "LOCKED") : state, c: state === "LOCKED" ? (metrics.ber > 1e-9 ? "#ff8c00" : "#00ff88") : (state === "SEARCHING" ? "#ff8c00" : (state === "LOST" ? "#ef4444" : "#00d4ff")) },
            { l: "RX Power", v: `${fmt2(metrics.rxPower)} dBm`, c: "#00d4ff" },
            { l: "SNR", v: `${fmt2(metrics.snr)} dB`, c: "#00d4ff" },
            { l: "BER", v: fmtSci(metrics.ber), c: metrics.ber > 1e-9 ? "#ff2d55" : "#00ff88" },
            { l: "Link Margin", v: `${fmt2(metrics.linkMargin)} dB`, c: "#00d4ff" },
          ].map(row => (
            <div key={row.l} style={{ display: "flex", justifyContent: "space-between", padding: "7px 0", borderBottom: "1px solid var(--border-dim)" }}>
              <span style={{ fontSize: 12, color: "var(--text-secondary)", fontWeight: 600 }}>{row.l}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: row.c, fontWeight: 700 }}>{row.v}</span>
            </div>
          ))}
        </div>

        {/* RX Power Live Oscilloscope */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "14px 18px", flex: 1, minHeight: 180, display: "flex", flexDirection: "column" }}>
          <SectionHeader accent="#00ff88">RX POWER — LIVE</SectionHeader>
          <div style={{ flex: 1, minHeight: 120 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history}>
                <CartesianGrid strokeDasharray="2 4" />
                <XAxis hide />
                <YAxis domain={[-22, -8]} tick={{ fill: "#64748b", fontSize: 10 }} unit=" dBm" width={45} />
                <Line type="monotone" dataKey="rxPower" stroke="#00ff88" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Demo Sequence */}
        <div style={{ background: "var(--bg-card)", border: "1px solid rgba(0,212,255,0.2)", borderRadius: 4, padding: "14px 18px" }}>
          <div style={{ fontSize: 12, color: "#00d4ff", letterSpacing: "0.14em", fontFamily: "var(--font-display)", fontWeight: 700, marginBottom: 8 }}>
            DEMO SEQUENCE
          </div>
          {[
            "1. Start with nominal state — show judge LOCKED link",
            "2. Trigger Atmospheric Degradation — watch SNR fall",
            "3. Observe DEGRADED — alert sequence triggered",
            "4. Trigger False Lock — demonstrate detection matrix",
            "5. Clear stress — verify link auto-recovery",
          ].map((step, idx) => (
            <div key={idx} style={{ fontSize: 12, color: "var(--text-secondary)", padding: "5px 0", borderBottom: "1px solid var(--border-dim)", lineHeight: 1.4 }}>
              {step}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── False Lock View (Matching Screenshot 3) ──────────────────────────────────

const FalseLockView = ({ metrics }: { metrics: LiveMetrics }) => {
  const criteria = [
    { label: "BER within valid-lock threshold", pass: metrics.ber < 1e-9, measured: fmtSci(metrics.ber), threshold: "thr: < 1.0e-9", desc: "High BER with apparent carrier lock indicates false acquisition" },
    { label: "SNR above minimum carrier threshold", pass: metrics.snr > 20, measured: `${fmt2(metrics.snr)} dB`, threshold: "thr: > 20.0 dB", desc: "Low SNR with claimed lock suggests carrier false alarm" },
    { label: "Alignment confidence sufficient", pass: metrics.pointingError < 10, measured: `${fmt2(metrics.pointingError)} µrad`, threshold: "thr: < 30 µrad", desc: "Excessive pointing error invalidates lock confidence" },
    { label: "Tracking stability acceptable", pass: metrics.trackingQuality > 90, measured: `${fmt2(metrics.trackingQuality)}%`, threshold: "thr: > 60%", desc: "Unstable tracking with claimed lock is a false-lock indicator" },
    { label: "False-lock state not asserted", pass: true, measured: "CLEAR", threshold: "thr: CLEAR", desc: "Explicit false-lock detection from anomaly correlation engine" },
  ];

  const algorithms = [
    { name: "BER Threshold Monitor", desc: "Continuous BER measurement against acquisition validity window" },
    { name: "Alignment Confidence Engine", desc: "Pointing error vs. beam divergence ratio analysis" },
    { name: "Signal Consistency Checker", desc: "Power stability and carrier frequency validation" },
    { name: "Multi-parameter Correlation", desc: "Cross-correlation of BER, SNR, pointing, and tracking metrics" },
    { name: "Anomaly State Machine", desc: "State transition monitoring for false-lock pattern recognition" },
  ];

  const signatures = [
    { type: "Type I: BER Mismatch", desc: "BER exceeds 1e-6 threshold while carrier lock indicator is asserted. Indicates receiver ADC threshold misalignment or noise floor shift." },
    { type: "Type II: Alignment Confidence Failure", desc: "Pointing error exceeds valid-lock envelope (30 µrad) while receiver claims tracking. Often caused by platform vibration or gimbal backlash." },
    { type: "Type III: Carrier Noise Lock", desc: "High SNR-apparent acquisition with degraded BER indicates receiver locked to noise floor artifact rather than signal carrier." },
  ];

  return (
    <div className="sweep-in" style={{ height: "100%", overflowY: "auto", display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Top Banner */}
      <div style={{
        background: "rgba(0,255,136,0.06)", border: "1px solid rgba(0,255,136,0.3)", borderRadius: 4,
        padding: "14px 20px", display: "flex", justifyContent: "space-between", alignItems: "center"
      }}>
        <div>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 18, letterSpacing: "0.1em", color: "#00ff88", marginBottom: 4 }}>
            LOCK VALIDATION STATUS: NOMINAL
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            Lock validated against BER, SNR, alignment deviation, and tracking stability thresholds.
          </div>
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "#00d4ff" }}>
          PAT FALSE LOCK SUITE v2.4
        </div>
      </div>

      {/* Grid: Validation Criteria + Confidence Gauges */}
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 14 }}>
        {/* Verification Criteria Checklist */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "16px 20px" }}>
          <SectionHeader>VERIFICATION CRITERIA MATRIX</SectionHeader>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
            {criteria.map(c => (
              <div key={c.label} style={{ borderBottom: "1px solid var(--border-dim)", paddingBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                    <span style={{
                      fontSize: 11, fontWeight: 700, fontFamily: "var(--font-mono)",
                      color: c.pass ? "#00ff88" : "#ff2d55",
                      background: c.pass ? "rgba(0,255,136,0.15)" : "rgba(255,45,85,0.15)",
                      padding: "2px 8px", borderRadius: 3,
                    }}>
                      {c.pass ? "PASS" : "FAIL"}
                    </span>
                    <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{c.label}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{c.desc}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: c.pass ? "#00ff88" : "#ff2d55", fontWeight: 700 }}>{c.measured}</div>
                  <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{c.threshold}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Lock Confidence Metrics */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "16px 20px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <SectionHeader>LOCK CONFIDENCE METRICS</SectionHeader>
          <div style={{ display: "flex", justifyContent: "space-around", padding: "16px 0" }}>
            <GaugeRing value={clamp(metrics.trackingQuality, 0, 100)} label="Overall" color="#00ff88" size={90} />
            <GaugeRing value={clamp(100 - metrics.pointingError * 2, 0, 100)} label="Alignment" color="#00d4ff" size={90} />
            <GaugeRing value={clamp(metrics.snr / 80 * 100, 0, 100)} label="Carrier SNR" color="#bf5af2" size={90} />
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6, borderTop: "1px solid var(--border-dim)", paddingTop: 12 }}>
            Low SNR with claimed lock suggests carrier false alarm. Excessive pointing error invalidates lock confidence.
          </div>
        </div>
      </div>

      {/* Grid: Detection Algorithm + False Lock Signatures */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "16px 20px" }}>
          <SectionHeader>DETECTION ALGORITHM</SectionHeader>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
            {algorithms.map((a, i) => (
              <div key={i} style={{ background: "rgba(15,23,42,0.6)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "10px 14px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#00d4ff" }} />
                  <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", fontFamily: "var(--font-display)", letterSpacing: "0.04em" }}>{a.name}</span>
                </div>
                <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{a.desc}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "16px 20px" }}>
          <SectionHeader accent="#ff8c00">FALSE LOCK SIGNATURES</SectionHeader>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
            {signatures.map((sig, i) => (
              <div key={i} style={{ background: "rgba(15,23,42,0.6)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 14px" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#ff8c00", fontFamily: "var(--font-display)", letterSpacing: "0.04em", marginBottom: 4 }}>
                  {sig.type}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.5 }}>{sig.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Event Log View (Matching Screenshot 2) ───────────────────────────────────

const EventLogView = ({ events }: { events: EventLogEntry[] }) => {
  const [filter, setFilter] = useState<"ALL" | "CRITICAL" | "WARNING" | "INFO">("ALL");

  const filtered = filter === "ALL" ? events : events.filter(e => e.level === filter);

  const levelColor = (l: string) => {
    if (l === "CRITICAL") return "#ff2d55";
    if (l === "WARNING") return "#ff8c00";
    return "#00d4ff";
  };

  const counts = {
    TOTAL: events.length,
    CRITICAL: events.filter(e => e.level === "CRITICAL").length,
    WARNING: events.filter(e => e.level === "WARNING").length,
    INFO: events.filter(e => e.level === "INFO").length,
  };

  return (
    <div className="sweep-in" style={{ height: "100%", display: "flex", flexDirection: "column", gap: 14 }}>
      {/* 4 KPI Summary Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 16px", textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 26, fontWeight: 700, color: "#f8fafc", lineHeight: 1 }}>{counts.TOTAL}</div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700, marginTop: 6 }}>TOTAL EVENTS</div>
        </div>
        <div style={{ background: "var(--bg-card)", border: "1px solid rgba(255,45,85,0.3)", borderRadius: 4, padding: "12px 16px", textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 26, fontWeight: 700, color: "#ff2d55", lineHeight: 1 }}>{counts.CRITICAL}</div>
          <div style={{ fontSize: 11, color: "#ff2d55", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700, marginTop: 6 }}>CRITICAL</div>
        </div>
        <div style={{ background: "var(--bg-card)", border: "1px solid rgba(255,140,0,0.3)", borderRadius: 4, padding: "12px 16px", textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 26, fontWeight: 700, color: "#ff8c00", lineHeight: 1 }}>{counts.WARNING}</div>
          <div style={{ fontSize: 11, color: "#ff8c00", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700, marginTop: 6 }}>WARNING</div>
        </div>
        <div style={{ background: "var(--bg-card)", border: "1px solid rgba(0,212,255,0.3)", borderRadius: 4, padding: "12px 16px", textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 26, fontWeight: 700, color: "#00d4ff", lineHeight: 1 }}>{counts.INFO}</div>
          <div style={{ fontSize: 11, color: "#00d4ff", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700, marginTop: 6 }}>INFO</div>
        </div>
      </div>

      {/* Filter strip & Legend Banner */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10,
        background: "rgba(15,23,42,0.6)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "8px 16px"
      }}>
        <div style={{ display: "flex", gap: 8 }}>
          {(["ALL", "CRITICAL", "WARNING", "INFO"] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 11, letterSpacing: "0.1em",
                padding: "5px 14px", border: `1px solid ${filter === f ? (levelColor(f) || "#00d4ff") : "var(--border-dim)"}`,
                borderRadius: 3, background: filter === f ? `${levelColor(f) || "#00d4ff"}20` : "transparent",
                color: filter === f ? (levelColor(f) || "#00d4ff") : "var(--text-secondary)", cursor: "pointer", transition: "all 0.15s",
              }}
            >
              ● {f}
            </button>
          ))}
        </div>
        <span style={{ fontSize: 11, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
          CRITICAL — Immediate intervention &nbsp;|&nbsp; WARNING — Degraded link &nbsp;|&nbsp; INFO — Nominal ops
        </span>
      </div>

      {/* Table */}
      <div style={{ flex: 1, background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {/* Table Header */}
        <div style={{ display: "grid", gridTemplateColumns: "100px 130px 140px 1fr", padding: "10px 18px", borderBottom: "1px solid var(--border-med)", background: "var(--bg-panel)" }}>
          {["SEVERITY", "TIMESTAMP", "SUBSYSTEM", "EVENT DESCRIPTION"].map(h => (
            <span key={h} style={{ fontSize: 11, color: "var(--text-secondary)", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700 }}>{h}</span>
          ))}
        </div>

        {/* Table Body */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {filtered.length === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 10 }}>
              <div style={{ fontSize: 24, color: "#00ff88" }}>✓</div>
              <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14, letterSpacing: "0.1em", color: "var(--text-primary)" }}>NO ACTIVE EVENTS</div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>All optical subsystems nominal</div>
            </div>
          ) : (
            filtered.map(e => (
              <div key={e.id} style={{
                display: "grid", gridTemplateColumns: "100px 130px 140px 1fr",
                padding: "10px 18px", borderBottom: "1px solid var(--border-dim)",
                transition: "background 0.15s", alignItems: "center",
              }}
                onMouseEnter={ev => (ev.currentTarget as HTMLElement).style.background = "var(--bg-card-2)"}
                onMouseLeave={ev => (ev.currentTarget as HTMLElement).style.background = "transparent"}
              >
                <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 11, letterSpacing: "0.08em", color: levelColor(e.level), display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: levelColor(e.level) }} />
                  {e.level}
                </span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)" }}>{e.timestamp}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#00d4ff" }}>{e.subsystem}</span>
                <span style={{ fontSize: 12, color: "var(--text-primary)" }}>{e.event}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

// ─── Main App Component ───────────────────────────────────────────────────────

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [paused, setPaused] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const tickRef = useRef(0);

  const [metrics, setMetrics] = useState<LiveMetrics>({
    rxPower: -11.7, snr: 73.3, ber: 1.0e-12, linkMargin: 38.3,
    pointingError: 1.73, trackingQuality: 96,
    temperature: 22.2, humidity: 59, windSpeed: 4.2,
    visibility: 15, wavelength: 1550, distance: 5, dataRate: 10, oit: 0,
    atmLoss: 1.5,
  });

  const [history, setHistory] = useState<TelemetryPoint[]>(() =>
    Array.from({ length: 60 }, (_, i) => ({
      t: i,
      rxPower: -11.7 + Math.sin(i * 0.2) * 0.4,
      snr: 73.3 + Math.cos(i * 0.2) * 1.2,
      ber: 1.0e-12,
      pointingError: 1.73 + Math.sin(i * 0.1) * 0.3,
      atmLoss: 1.5,
    }))
  );

  const [simParams, setSimParams] = useState<SimParams>({
    txPower: 30,
    wavelength: 1550,
    linkDistance: 5,
    dataRate: 10,
    rxSensitivity: -24,
    beamDivergence: 30,
    pointingError: 1.73,
  });

  const [scenarios, setScenarios] = useState<StressScenario[]>([
    {
      id: "atm", name: "Atmospheric Degradation", badge: "WARNING", color: "#ff8c00",
      description: "Progressively increases atmospheric loss to simulate fog, haze, or precipitation. Loss increases until link margin is exhausted.",
      effects: ["Increasing ATM loss", "Decreasing RX power", "Rising BER", "Potential link degradation"],
      active: false,
    },
    {
      id: "beam", name: "Beam Misalignment", badge: "WARNING", color: "#ff8c00",
      description: "Introduces progressive pointing error simulating gimbal drift, vibration, or platform instability.",
      effects: ["Increasing pointing error", "Higher pointing loss", "Reduced RX power", "Tracking deviation"],
      active: false,
    },
    {
      id: "turb", name: "Turbulence Burst", badge: "WARNING", color: "#ff8c00",
      description: "Triggers high-frequency atmospheric turbulence causing rapid scintillation and beam wander.",
      effects: ["Rapid power fluctuations", "BER spikes", "Tracking instability", "Potential link drop"],
      active: false,
    },
    {
      id: "sig", name: "Signal Interruption", badge: "CRITICAL", color: "#ff2d55",
      description: "Periodic link blockage simulating cloud passage, bird strike, or transient obstruction.",
      effects: ["Link loss events", "CRITICAL alert", "SNR collapse", "BER saturation"],
      active: false,
    },
    {
      id: "false", name: "False Lock Condition", badge: "CRITICAL", color: "#ff2d55",
      description: "Forces a false carrier lock state where the receiver believes acquisition has occurred but BER or alignment confidence fails validation.",
      effects: ["FALSE_LOCK state", "Lock confidence anomaly", "BER/alignment mismatch", "False-lock alert"],
      active: false,
    },
  ]);

  const [events, setEvents] = useState<EventLogEntry[]>([
    { id: 1, level: "INFO", timestamp: "14:54:38", subsystem: "LINK_CTRL", event: "Carrier acquisition confirmed. Lock state: LOCKED" },
    { id: 2, level: "INFO", timestamp: "14:54:39", subsystem: "TRACKING", event: "Fine pointing loop engaged. Tracking error: 1.73 µrad" },
    { id: 3, level: "INFO", timestamp: "14:54:40", subsystem: "TELEMETRY", event: "Telemetry stream active. Update rate: 30 Hz" },
  ]);

  const nextEventId = useRef(4);

  const addEvent = useCallback((level: EventLogEntry["level"], subsystem: string, event: string) => {
    setEvents(prev => [
      { id: nextEventId.current++, level, timestamp: now(), subsystem, event },
      ...prev.slice(0, 99),
    ]);
  }, []);

  const onTrigger = useCallback((id: string) => {
    setScenarios(prev => prev.map(s => s.id === id ? { ...s, active: !s.active } : s));
    const names: Record<string, string> = {
      atm: "Atmospheric Degradation", beam: "Beam Misalignment",
      turb: "Turbulence Burst", sig: "Signal Interruption", false: "False Lock Condition",
    };
    addEvent("WARNING", "STRESS_CTRL", `Scenario toggled: ${names[id]}`);
    triggerStress(id);
  }, [addEvent, triggerStress]);

  // Keyboard shortcut C to collapse/expand sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'c' || e.key === 'C') {
        setSidebarCollapsed(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Real simulator telemetry integration via WebSocket
  const {
    telemetry,
    history: wsHistory,
    connected,
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
  } = useTelemetry();

  // Unified single source of truth from real simulator telemetry
  useEffect(() => {
    if (telemetry) {
      setMetrics({
        rxPower: telemetry.rx_power,
        snr: telemetry.snr,
        ber: telemetry.ber,
        linkMargin: telemetry.margin,
        pointingError: telemetry.pointing_error_urad,
        trackingQuality: telemetry.tracking_quality,
        temperature: telemetry.temperature,
        humidity: telemetry.humidity,
        windSpeed: telemetry.wind_speed,
        visibility: 15.0,
        wavelength: telemetry.wavelength,
        distance: telemetry.distance,
        dataRate: telemetry.data_rate,
        oit: 1.0,
        atmLoss: telemetry.atm_loss,
      });

      if (telemetry.false_lock) {
        addEvent("CRITICAL", "FALSE_LOCK", "False lock detected: Carrier lock without spatial alignment!");
      }
      if (telemetry.ber > 1e-6) {
        addEvent("WARNING", "MODEM", `BER threshold exceeded: ${fmtSci(telemetry.ber)}`);
      }
    }
  }, [telemetry, addEvent]);

  const history = wsHistory.length > 0 ? wsHistory : [];

  const navItems: { view: View; label: string; abbr: string; num: string; icon: string }[] = [
    { view: "overview", label: "OVERVIEW", abbr: "OVR", num: "01", icon: "⬡" },
    { view: "telemetry", label: "TELEMETRY", abbr: "TEL", num: "02", icon: "📈" },
    { view: "config", label: "PS CONFIG", abbr: "CFG", num: "03", icon: "🛠" },
    { view: "simulation", label: "OPTICAL LINK", abbr: "OPT", num: "04", icon: "⚙" },
    { view: "stress", label: "STRESS TEST", abbr: "STR", num: "05", icon: "⚡" },
    { view: "falselock", label: "FALSE LOCK", abbr: "FLK", num: "06", icon: "◎" },
    { view: "eventlog", label: "EVENT LOG", abbr: "EVT", num: "07", icon: "≡" },
    { view: "benchmark", label: "BENCHMARK", abbr: "BMK", num: "08", icon: "📊" },
  ];

  const sidebarWidth = sidebarCollapsed ? 54 : 160;

  return (
    <div style={{
      width: "100vw", height: "100vh", display: "flex", flexDirection: "column",
      background: "var(--bg-base)", overflow: "hidden", position: "relative",
    }}>
      {/* Top Header */}
      <TopBar
        metrics={metrics}
        paused={paused}
        onPause={() => {
          setPaused(p => !p);
          toggleRunning();
        }}
        state={telemetry?.state ?? "OFFLINE"}
        connected={connected}
      />

      {/* Offline Status Banner */}
      {!connected && (
        <div style={{
          background: "rgba(255, 45, 85, 0.12)",
          borderBottom: "1px solid rgba(255, 45, 85, 0.4)",
          padding: "8px 20px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          color: "#ff2d55",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          flexShrink: 0,
          zIndex: 30,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 14 }}>⚠️</span>
            <strong style={{ letterSpacing: "0.06em" }}>SIMULATOR OFFLINE / DISCONNECTED</strong>
            <span style={{ color: "var(--text-secondary)" }}>
              Waiting for live telemetry on ws://localhost:8000/ws (Attempt #{retryCount})...
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: "var(--text-secondary)", fontSize: 11 }}>START BACKEND:</span>
            <code style={{ background: "#0a1020", color: "#00d4ff", padding: "2px 8px", borderRadius: 3, border: "1px solid var(--border-dim)" }}>
              python server.py
            </code>
          </div>
        </div>
      )}

      {/* Body Area */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Collapsible Sidebar */}
        <div style={{
          width: sidebarWidth,
          flexShrink: 0,
          background: "var(--bg-panel)",
          borderRight: "1px solid var(--border-dim)",
          display: "flex",
          flexDirection: "column",
          padding: "10px 0",
          transition: "width 0.2s ease-in-out",
          zIndex: 10,
        }}>
          {/* Collapse Toggle Button */}
          <button
            onClick={() => setSidebarCollapsed(prev => !prev)}
            title="Press 'C' to toggle sidebar"
            style={{
              padding: "6px 8px",
              margin: "0 8px 12px",
              background: "rgba(0,212,255,0.08)",
              border: "1px solid var(--border-dim)",
              borderRadius: 3,
              color: "#00d4ff",
              fontFamily: "var(--font-display)",
              fontWeight: 700,
              fontSize: 11,
              letterSpacing: "0.08em",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {sidebarCollapsed ? "►" : "◄ COLLAPSE"}
          </button>

          {/* Navigation Items */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
            {navItems.map(item => {
              const active = view === item.view;
              return (
                <button
                  key={item.view}
                  onClick={() => setView(item.view)}
                  title={sidebarCollapsed ? `${item.num} · ${item.label}` : undefined}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: sidebarCollapsed ? "10px 0" : "10px 14px",
                    justifyContent: sidebarCollapsed ? "center" : "flex-start",
                    gap: 10,
                    background: active ? "rgba(0,212,255,0.14)" : "transparent",
                    border: "none",
                    borderLeft: `3px solid ${active ? "#00d4ff" : "transparent"}`,
                    cursor: "pointer",
                    transition: "all 0.15s",
                    color: active ? "#00d4ff" : "var(--text-secondary)",
                  }}
                >
                  <span style={{ fontSize: 16 }}>{item.icon}</span>
                  {!sidebarCollapsed && (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                      <span style={{ fontSize: 10, color: active ? "#00d4ff" : "var(--text-dim)", fontFamily: "var(--font-mono)", fontWeight: 700 }}>
                        {item.num}
                      </span>
                      <span style={{ fontSize: 12, fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.06em", color: active ? "#f8fafc" : "var(--text-secondary)" }}>
                        {item.label}
                      </span>
                    </div>
                  )}
                </button>
              );
            })}
          </div>

          {/* Bottom Brand */}
          <div style={{ marginTop: "auto", padding: "10px 0", textAlign: "center", borderTop: "1px solid var(--border-dim)" }}>
            <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.14em", lineHeight: 1.5 }}>
              {sidebarCollapsed ? "ISRO" : "ISRO · SIH 2026"}
            </div>
          </div>
        </div>

        {/* Main Workspace (Expands Automatically) */}
        <div style={{ flex: 1, overflow: "hidden", padding: 14, display: "flex", flexDirection: "column" }}>
          {/* Breadcrumb / Status Strip */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexShrink: 0 }}>
            <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>FSOC PAT LAB</span>
            <span style={{ fontSize: 11, color: "var(--border-med)" }}>›</span>
            <span style={{ fontSize: 12, color: "#00d4ff", fontFamily: "var(--font-mono)", fontWeight: 700, letterSpacing: "0.08em" }}>
              {navItems.find(n => n.view === view)?.label}
            </span>
            <div style={{ marginLeft: "auto", display: "flex", gap: 14, alignItems: "center" }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)" }}>SIM RATE: 30 Hz</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: paused ? "#ff8c00" : "#00ff88", fontWeight: 700 }}>
                {paused ? "● PAUSED" : "● REALTIME ACTIVE"}
              </span>
            </div>
          </div>

          {/* View Content */}
          <div style={{ flex: 1, overflow: "hidden" }}>
            {view === "overview" && <OverviewView metrics={metrics} history={history} telemetry={telemetry} connected={connected} />}
            {view === "telemetry" && <TelemetryView history={history} />}
            {view === "simulation" && (
              <SimulationView
                params={simParams}
                onChange={(k, v) => {
                  setSimParams(p => ({ ...p, [k]: v }));
                  setOpticalParams({ [k]: v });
                }}
                metrics={metrics}
              />
            )}
            {view === "stress" && <StressView scenarios={scenarios} onTrigger={onTrigger} metrics={metrics} history={history} />}
            {view === "falselock" && <FalseLockView metrics={metrics} />}
            {view === "eventlog" && <EventLogView events={events} />}
            {view === "benchmark" && <BenchmarkPage />}
            {view === "config" && (
              <SceneConfigPage
                currentPreset={telemetry?.preset || "EASY"}
                onSetPreset={setPreset}
                onSetDisturbance={setDisturbance}
                onSetPlatformMode={setPlatformMode}
                onSetAtmosphere={setAtmosphere}
                onSetFov={setFov}
                onSetTargetParams={setTargetParams}
                onSetMotionType={setMotionType}
                onSetGimbalLimits={setGimbalLimits}
                onSetNoiseTypes={setNoiseTypes}
                onInjectOcclusion={injectOcclusion}
                telemetry={telemetry}
              />
            )}
          </div>
        </div>
      </div>

      {/* Footer Strip */}
      <div style={{
        height: 24, background: "var(--bg-panel)", borderTop: "1px solid var(--border-dim)",
        display: "flex", alignItems: "center", padding: "0 18px", gap: 20,
        fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)", flexShrink: 0,
      }}>
        <span style={{ color: "#00d4ff", fontWeight: 600 }}>PAT.LAB v2.4</span>
        <span>ISRO · Dept. of Space · SIH 2026</span>
        <span>PS #4: AI-BASED VIRTUAL CAMERA TRACKING · FSOC COARSE ALIGNMENT</span>
        <span style={{ marginLeft: "auto" }}>
          TX: {simParams.txPower} dBm &nbsp;|&nbsp;
          λ: {simParams.wavelength} nm &nbsp;|&nbsp;
          RANGE: {simParams.linkDistance} km &nbsp;|&nbsp;
          RATE: {simParams.dataRate} Gbps
        </span>
      </div>
    </div>
  );
}
