import { useState, useEffect, useRef, useCallback } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

// ─── Types ───────────────────────────────────────────────────────────────────

type View = "overview" | "telemetry" | "simulation" | "stress" | "falselock" | "eventlog";

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
  badge: string;
  color: string;
  description: string;
  effects: string[];
  active: boolean;
}

interface EventLogEntry {
  id: number;
  level: "CRITICAL" | "WARNING" | "INFO";
  timestamp: string;
  subsystem: string;
  event: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const rnd = (base: number, delta: number) => base + (Math.random() - 0.5) * 2 * delta;
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

// ─── Nav Icons ────────────────────────────────────────────────────────────────

const NavIcon = ({ view, active, onClick, label, children }: {
  view: View; active: boolean; onClick: (v: View) => void; label: string; children: React.ReactNode;
}) => (
  <button
    onClick={() => onClick(view)}
    title={label}
    style={{
      width: "100%",
      padding: "10px 0",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 4,
      background: active ? "rgba(0,212,255,0.08)" : "transparent",
      border: "none",
      borderLeft: active ? "2px solid #00d4ff" : "2px solid transparent",
      cursor: "pointer",
      transition: "all 0.2s",
      color: active ? "#00d4ff" : "#3d5a72",
    }}
    onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.color = "#6a9fc0"; }}
    onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.color = "#3d5a72"; }}
  >
    {children}
    <span style={{ fontSize: 9, letterSpacing: "0.08em", fontFamily: "var(--font-display)", fontWeight: 600, lineHeight: 1 }}>
      {label}
    </span>
  </button>
);

// ─── Metric Card ──────────────────────────────────────────────────────────────

const MetricCard = ({ label, value, unit, sub, color = "#00d4ff", warn = false }: {
  label: string; value: string; unit?: string; sub?: string; color?: string; warn?: boolean;
}) => (
  <div className="metric-card" style={{
    background: "var(--bg-card)",
    border: `1px solid ${warn ? "rgba(255,45,85,0.3)" : "var(--border-dim)"}`,
    borderRadius: 4,
    padding: "10px 14px",
    transition: "all 0.2s",
  }}>
    <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--text-dim)", fontFamily: "var(--font-display)", fontWeight: 700, marginBottom: 4, textTransform: "uppercase" }}>
      {label}
    </div>
    <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 600, color, lineHeight: 1 }}>
        {value}
      </span>
      {unit && <span style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>{unit}</span>}
    </div>
    {sub && <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 3, fontFamily: "var(--font-mono)" }}>{sub}</div>}
  </div>
);

// ─── Section Header ───────────────────────────────────────────────────────────

const SectionHeader = ({ children, accent = "#00d4ff" }: { children: React.ReactNode; accent?: string }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
    <div style={{ width: 3, height: 14, background: accent, borderRadius: 2, boxShadow: `0 0 8px ${accent}` }} />
    <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 12, letterSpacing: "0.18em", textTransform: "uppercase", color: "var(--text-primary)" }}>
      {children}
    </span>
  </div>
);

// ─── Custom Tooltip ───────────────────────────────────────────────────────────

const ChartTooltip = ({ active, payload, label, unit }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: "#0a1220", border: "1px solid rgba(0,212,255,0.3)", borderRadius: 4, padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 11 }}>
      <div style={{ color: "#4a7090", marginBottom: 3 }}>t+{label}s</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(2) : p.value} {unit}
        </div>
      ))}
    </div>
  );
};

// ─── Gauge Ring ───────────────────────────────────────────────────────────────

const GaugeRing = ({ value, max = 100, size = 80, label, color = "#00d4ff" }: {
  value: number; max?: number; size?: number; label: string; color?: string;
}) => {
  const r = (size - 10) / 2;
  const circ = 2 * Math.PI * r;
  const pct = clamp(value / max, 0, 1);
  const dash = pct * circ;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(0,212,255,0.08)" strokeWidth={4} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={4}
          strokeDasharray={`${dash} ${circ - dash}`} strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 4px ${color})`, transition: "stroke-dasharray 0.5s ease" }}
        />
      </svg>
      <div style={{ marginTop: -size - 6, height: size, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 16, fontWeight: 600, color, lineHeight: 1 }}>{Math.round(value)}%</span>
      </div>
      <span style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.1em", fontFamily: "var(--font-display)", fontWeight: 700, textTransform: "uppercase" }}>{label}</span>
    </div>
  );
};

// ─── Top Bar ──────────────────────────────────────────────────────────────────

const TopBar = ({ metrics, paused, onPause }: { metrics: LiveMetrics; paused: boolean; onPause: () => void }) => {
  const [time, setTime] = useState(now());
  useInterval(() => setTime(now()), 1000);

  return (
    <div style={{
      height: 52,
      background: "var(--bg-panel)",
      borderBottom: "1px solid var(--border-dim)",
      display: "flex",
      alignItems: "center",
      padding: "0 16px",
      gap: 0,
      flexShrink: 0,
    }}>
      {/* Logo */}
      <div style={{ display: "flex", flexDirection: "column", marginRight: 20, minWidth: 120 }}>
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 16, letterSpacing: "0.08em", color: "#00d4ff", lineHeight: 1.1 }}>
          FSOC PAT LAB
        </div>
        <div style={{ fontSize: 8, color: "var(--text-dim)", letterSpacing: "0.18em", fontFamily: "var(--font-display)", fontWeight: 600 }}>
          FREE-SPACE OPTICAL COMMS
        </div>
      </div>

      {/* Status */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginRight: 24, padding: "4px 12px", border: "1px solid rgba(0,255,136,0.2)", borderRadius: 3, background: "rgba(0,255,136,0.05)" }}>
        <div className="status-dot-green" style={{ width: 7, height: 7, borderRadius: "50%", background: "#00ff88" }} />
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14, letterSpacing: "0.1em", color: "#00ff88" }}>ESTABLISHED</span>
      </div>

      {/* KPIs */}
      <div style={{ display: "flex", gap: 0, flex: 1 }}>
        {[
          { label: "RX POWER", value: `${fmt2(metrics.rxPower)}`, unit: "dBm" },
          { label: "SNR", value: `${fmt2(metrics.snr)}`, unit: "dB" },
          { label: "MARGIN", value: `${fmt2(metrics.linkMargin)}`, unit: "dB" },
          { label: "TRACKING", value: `${Math.round(metrics.trackingQuality)}`, unit: "%" },
        ].map(k => (
          <div key={k.label} style={{ padding: "0 14px", borderLeft: "1px solid var(--border-dim)", display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <div style={{ fontSize: 8, color: "var(--text-dim)", letterSpacing: "0.14em", fontFamily: "var(--font-display)", fontWeight: 700 }}>{k.label}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 600, color: "#00d4ff" }}>{k.value}</span>
              <span style={{ fontSize: 9, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>{k.unit}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Date/time */}
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)", marginRight: 14, textAlign: "right" }}>
        <div style={{ fontSize: 9, color: "var(--text-dim)" }}>2026-09-07</div>
        <div>{time}</div>
      </div>

      {/* Pause */}
      <button
        onClick={onPause}
        style={{
          fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 11, letterSpacing: "0.12em",
          padding: "5px 14px", border: `1px solid ${paused ? "#ff8c00" : "var(--border-med)"}`,
          borderRadius: 3, background: paused ? "rgba(255,140,0,0.1)" : "transparent",
          color: paused ? "#ff8c00" : "var(--text-secondary)", cursor: "pointer", transition: "all 0.2s",
        }}
      >
        {paused ? "RESUME" : "PAUSE"}
      </button>
    </div>
  );
};

// ─── Overview View ────────────────────────────────────────────────────────────

const OverviewView = ({ metrics, history }: { metrics: LiveMetrics; history: TelemetryPoint[] }) => {
  const recent = history.slice(-20);

  return (
    <div className="sweep-in" style={{ display: "grid", gridTemplateRows: "auto 1fr auto", gap: 12, height: "100%" }}>
      {/* Top KPI grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 8 }}>
        <MetricCard label="RX Optical Power" value={fmt2(metrics.rxPower)} unit="dBm" sub="TX: 30.0 dBm" color="#00d4ff" />
        <MetricCard label="Signal-to-Noise" value={fmt2(metrics.snr)} unit="dB" sub="Min: 20 dB" color="#00d4ff" />
        <MetricCard label="Bit Error Rate" value={fmtSci(metrics.ber)} sub="Threshold: 1e-9" color={metrics.ber > 1e-9 ? "#ff2d55" : "#00ff88"} warn={metrics.ber > 1e-9} />
        <MetricCard label="Link Margin" value={fmt2(metrics.linkMargin)} unit="dB" sub="Min: 6 dB" color="#00d4ff" />
        <MetricCard label="Pointing Error" value={fmt2(metrics.pointingError)} unit="µrad" sub="Max: 50 µrad" color={metrics.pointingError > 40 ? "#ff8c00" : "#00d4ff"} />
        <MetricCard label="Tracking Quality" value={`${Math.round(metrics.trackingQuality)}`} unit="%" sub="Target: ≥95%" color={metrics.trackingQuality >= 95 ? "#00ff88" : "#ff8c00"} />
      </div>

      {/* Mid: mini chart + link viz + diagnostics */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 220px", gap: 10, overflow: "hidden" }}>
        {/* Left: charts */}
        <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: 10, overflow: "hidden" }}>
          {/* RX Power mini chart */}
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "10px 12px" }}>
            <SectionHeader>RX Power — Live Feed</SectionHeader>
            <ResponsiveContainer width="100%" height="75%">
              <LineChart data={recent}>
                <CartesianGrid strokeDasharray="2 4" />
                <XAxis dataKey="t" hide />
                <YAxis domain={[-13, -10]} width={36} tickFormatter={v => `${v}`} />
                <Tooltip content={<ChartTooltip unit="dBm" />} />
                <Line type="monotone" dataKey="rxPower" name="RX Power" stroke="#00d4ff" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {/* SNR mini chart */}
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "10px 12px" }}>
            <SectionHeader accent="#00ff88">SNR — Live Feed</SectionHeader>
            <ResponsiveContainer width="100%" height="75%">
              <LineChart data={recent}>
                <CartesianGrid strokeDasharray="2 4" />
                <XAxis dataKey="t" hide />
                <YAxis domain={[70, 76]} width={36} />
                <Tooltip content={<ChartTooltip unit="dB" />} />
                <Line type="monotone" dataKey="snr" name="SNR" stroke="#00ff88" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Right: system diagnostics */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Lock confidence gauges */}
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "10px 12px", flex: 1 }}>
            <SectionHeader>Lock Confidence</SectionHeader>
            <div style={{ display: "flex", justifyContent: "space-around", padding: "6px 0" }}>
              <GaugeRing value={metrics.trackingQuality} label="Overall" color="#00ff88" size={68} />
              <GaugeRing value={clamp(metrics.snr / 80 * 100, 0, 100)} label="Signal" color="#00d4ff" size={68} />
            </div>
          </div>

          {/* Environment */}
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "10px 12px" }}>
            <SectionHeader accent="#bf5af2">Environment</SectionHeader>
            {[
              { l: "Temperature", v: `${fmt2(metrics.temperature)} °C` },
              { l: "Humidity", v: `${Math.round(metrics.humidity)} %` },
              { l: "Wind Speed", v: `${fmt2(metrics.windSpeed)} m/s` },
              { l: "Visibility", v: `${metrics.visibility} km` },
              { l: "Wavelength", v: `${metrics.wavelength} nm` },
              { l: "Distance", v: `${metrics.distance} km` },
            ].map(row => (
              <div key={row.l} style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid var(--border-dim)" }}>
                <span style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "var(--font-display)", fontWeight: 600, letterSpacing: "0.05em" }}>{row.l}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#00d4ff" }}>{row.v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Bottom: power budget breakdown */}
      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "10px 16px" }}>
        <SectionHeader>Power Budget Breakdown</SectionHeader>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6 }}>
          {[
            { label: "TX Power", value: "30.0", unit: "dBm", color: "#00d4ff" },
            { label: "FSS Loss", value: "-40.8", unit: "dB", color: "#ff2d55" },
            { label: "Atm Loss", value: `-${fmt2(metrics.atmLoss ?? 1.5)}`, unit: "dB", color: "#ff8c00" },
            { label: "Point Loss", value: `-${fmt2(metrics.pointingError * 0.003)}`, unit: "dB", color: "#ff8c00" },
            { label: "TX Gain", value: "+40.0", unit: "dBi", color: "#00ff88" },
            { label: "RX Gain", value: "+3.0", unit: "dBi", color: "#00ff88" },
            { label: "RX Power", value: fmt2(metrics.rxPower), unit: "dBm", color: "#00d4ff" },
          ].map(b => (
            <div key={b.label} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 8, color: "var(--text-dim)", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700, marginBottom: 3 }}>{b.label}</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600, color: b.color }}>{b.value}<span style={{ fontSize: 9, marginLeft: 2 }}>{b.unit}</span></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── Telemetry View ───────────────────────────────────────────────────────────

const TelemetryView = ({ history, metrics }: { history: TelemetryPoint[]; metrics: LiveMetrics }) => {
  const data = history.slice(-60);

  const charts = [
    {
      title: "Optical Power — RX vs Margin",
      color: "#00d4ff",
      accent: "#00d4ff",
      dataKey: "rxPower",
      name: "RX Power",
      unit: "dBm",
      domain: [-14, -10] as [number, number],
    },
    {
      title: "Bit Error Rate — Log Scale",
      color: "#ff2d55",
      accent: "#ff2d55",
      dataKey: "ber",
      name: "BER",
      unit: "",
      domain: [0, 5e-12] as [number, number],
    },
    {
      title: "Signal-to-Noise Ratio",
      color: "#00ff88",
      accent: "#00ff88",
      dataKey: "snr",
      name: "SNR",
      unit: "dB",
      domain: [70, 76] as [number, number],
    },
    {
      title: "Pointing Error & Atmospheric Loss",
      color: "#ff8c00",
      accent: "#ff8c00",
      dataKey: "pointingError",
      name: "Pointing Error",
      unit: "µrad",
      domain: [0, 6] as [number, number],
    },
  ];

  return (
    <div className="sweep-in" style={{ display: "grid", gridTemplateRows: "1fr 1fr", gridTemplateColumns: "1fr 1fr", gap: 10, height: "100%" }}>
      {charts.map(c => (
        <div key={c.title} style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 14px", display: "flex", flexDirection: "column" }}>
          <SectionHeader accent={c.accent}>{c.title}</SectionHeader>
          <div style={{ flex: 1 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data}>
                <CartesianGrid strokeDasharray="2 4" />
                <XAxis dataKey="t" tickFormatter={v => `${v}s`} interval={9} />
                <YAxis domain={c.domain} width={42} />
                <Tooltip content={<ChartTooltip unit={c.unit} />} />
                {c.dataKey === "pointingError" && (
                  <Line type="monotone" dataKey="atmLoss" name="Atm Loss" stroke="#bf5af2" strokeWidth={1} dot={false} isAnimationActive={false} />
                )}
                <Line type="monotone" dataKey={c.dataKey} name={c.name} stroke={c.color} strokeWidth={1.5} dot={false} isAnimationActive={false}
                  style={{ filter: `drop-shadow(0 0 2px ${c.color})` }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ))}

      {/* Telemetry table overlaid as a bottom strip - use absolute positioning within one of the panels is not right, so we'll add it below the grid */}
    </div>
  );
};

// ─── Simulation View ──────────────────────────────────────────────────────────

const SimulationView = ({ params, onChange, metrics }: {
  params: SimParams;
  onChange: (k: keyof SimParams, v: number) => void;
  metrics: LiveMetrics;
}) => {
  const sliders: { key: keyof SimParams; label: string; desc: string; min: number; max: number; unit: string; step: number }[] = [
    { key: "txPower", label: "TX Optical Power", desc: "Laser output power", min: 0, max: 40, unit: "dBm", step: 0.1 },
    { key: "wavelength", label: "Wavelength", desc: "Operating wavelength", min: 800, max: 1600, unit: "nm", step: 1 },
    { key: "linkDistance", label: "Link Distance", desc: "Transmitter-receiver separation", min: 0.1, max: 20, unit: "km", step: 0.1 },
    { key: "dataRate", label: "Data Rate", desc: "Target channel throughput", min: 0.1, max: 100, unit: "Gbps", step: 0.1 },
    { key: "rxSensitivity", label: "RX Sensitivity", desc: "Minimum detectable power", min: -80, max: -20, unit: "dBm", step: 0.5 },
    { key: "beamDivergence", label: "Beam Divergence", desc: "Half-angle beam spread", min: 0.1, max: 10, unit: "mrad", step: 0.1 },
    { key: "pointingError", label: "Pointing Error", desc: "Static alignment offset", min: 0, max: 50, unit: "µrad", step: 1 },
  ];

  return (
    <div className="sweep-in" style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 12, height: "100%" }}>
      <div style={{ overflowY: "auto", paddingRight: 4 }}>
        <SectionHeader>Transmitter & Link Parameters</SectionHeader>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {sliders.map(s => {
            const pct = ((params[s.key] - s.min) / (s.max - s.min)) * 100;
            return (
              <div key={s.key} style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 14px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 4 }}>
                  <div>
                    <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 13, letterSpacing: "0.06em", color: "var(--text-primary)" }}>{s.label}</div>
                    <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 1 }}>{s.desc}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 16, fontWeight: 600, color: "#00d4ff" }}>{params[s.key].toFixed(s.step < 1 ? 1 : 0)}</span>
                    <span style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>{s.unit}</span>
                  </div>
                </div>
                <input
                  type="range" min={s.min} max={s.max} step={s.step} value={params[s.key]}
                  onChange={e => onChange(s.key, parseFloat(e.target.value))}
                  style={{ "--pct": `${pct}%` } as any}
                />
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 3 }}>
                  <span style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{s.min} {s.unit}</span>
                  <span style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{s.max} {s.unit}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Right panel: system response */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, overflowY: "auto" }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 14px" }}>
          <SectionHeader>System Response</SectionHeader>
          {[
            { l: "RX Optical Power", v: `${fmt2(metrics.rxPower)} dBm`, c: "#00d4ff" },
            { l: "BER", v: fmtSci(metrics.ber), c: metrics.ber > 1e-9 ? "#ff2d55" : "#00ff88" },
            { l: "SNR", v: `${fmt2(metrics.snr)} dB`, c: "#00d4ff" },
            { l: "Link Margin", v: `${fmt2(metrics.linkMargin)} dB`, c: "#00d4ff" },
            { l: "OTm Loss", v: `${fmt2(1.5 + (params.linkDistance - 5) * 0.2)} dB`, c: "#ff8c00" },
            { l: "Geo Loss", v: "-40.8 dB", c: "#ff8c00" },
            { l: "Pointing Loss", v: `-${fmt2(params.pointingError * 0.004)} dB`, c: "#ff8c00" },
            { l: "Total Loss", v: `${fmt2(30 - Math.abs(metrics.rxPower))} dB`, c: "#ff2d55" },
          ].map(row => (
            <div key={row.l} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border-dim)" }}>
              <span style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "var(--font-display)", fontWeight: 600 }}>{row.l}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: row.c }}>{row.v}</span>
            </div>
          ))}
        </div>

        {/* Loss breakdown bar */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 14px" }}>
          <SectionHeader accent="#ff8c00">Link Budget Breakdown</SectionHeader>
          {[
            { l: "TX Power", v: params.txPower, max: 40, c: "#00d4ff" },
            { l: "ATM Loss", v: -(1.5 + (params.linkDistance - 5) * 0.2), max: 5, c: "#ff2d55" },
            { l: "Geo Loss", v: -40.8, max: 50, c: "#ff2d55" },
            { l: "Pointing Loss", v: -(params.pointingError * 0.004), max: 2, c: "#ff8c00" },
            { l: "RX Power", v: metrics.rxPower, max: 0, c: "#00ff88" },
          ].map(b => (
            <div key={b.l} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                <span style={{ fontSize: 9, color: "var(--text-secondary)", letterSpacing: "0.08em" }}>{b.l}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: b.c }}>{b.v.toFixed(1)} dB</span>
              </div>
              <div style={{ height: 3, background: "var(--border-dim)", borderRadius: 2 }}>
                <div style={{
                  height: "100%",
                  width: `${Math.min(100, Math.abs(b.v) / Math.max(Math.abs(b.max), 1) * 100)}%`,
                  background: b.c,
                  borderRadius: 2,
                  boxShadow: `0 0 4px ${b.c}`,
                }} />
              </div>
            </div>
          ))}
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid rgba(0,212,255,0.15)", borderRadius: 4, padding: "10px 14px" }}>
          <div style={{ fontSize: 9, color: "#00d4ff", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700, marginBottom: 6 }}>CAUSE → EFFECT</div>
          <div style={{ fontSize: 10, color: "var(--text-secondary)", lineHeight: 1.6 }}>
            Adjust TX Power, Distance, or Visibility to see immediate changes in RX Power, BER, and Link Margin. Higher Turbulence increases fading. Larger pointing error reduces received flux.
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Stress View ──────────────────────────────────────────────────────────────

const StressView = ({ scenarios, onTrigger, metrics }: {
  scenarios: StressScenario[];
  onTrigger: (id: string) => void;
  metrics: LiveMetrics;
}) => {
  const [triggered, setTriggered] = useState<string | null>(null);

  const handle = (id: string) => {
    setTriggered(id);
    onTrigger(id);
    setTimeout(() => setTriggered(null), 600);
  };

  return (
    <div className="sweep-in" style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 12, height: "100%" }}>
      <div style={{ overflowY: "auto" }}>
        <SectionHeader>Stress Scenario Control</SectionHeader>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {scenarios.map(s => (
            <div
              key={s.id}
              className={triggered === s.id ? "trigger-flash" : ""}
              style={{
                background: s.active ? `rgba(${s.color === "#ff8c00" ? "255,140,0" : s.color === "#ff2d55" ? "255,45,85" : "191,90,242"},0.06)` : "var(--bg-card)",
                border: `1px solid ${s.active ? s.color + "40" : "var(--border-dim)"}`,
                borderRadius: 4,
                padding: "14px 16px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: 16,
                transition: "all 0.3s",
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: s.active ? s.color : "var(--text-dim)", boxShadow: s.active ? `0 0 6px ${s.color}` : "none" }} />
                  <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14, letterSpacing: "0.08em", color: "var(--text-primary)" }}>{s.name}</span>
                  <span style={{ fontSize: 9, fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.1em", padding: "1px 6px", borderRadius: 2, background: s.color + "20", color: s.color, border: `1px solid ${s.color}40` }}>
                    {s.badge}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 8, lineHeight: 1.5 }}>{s.description}</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {s.effects.map(e => (
                    <span key={e} style={{ fontSize: 9, color: "var(--text-dim)", background: "var(--border-dim)", borderRadius: 2, padding: "2px 7px", fontFamily: "var(--font-mono)" }}>
                      {e}
                    </span>
                  ))}
                </div>
              </div>
              <button
                onClick={() => handle(s.id)}
                style={{
                  fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 11, letterSpacing: "0.14em",
                  padding: "6px 16px", border: `1px solid ${s.color}`,
                  borderRadius: 3, background: s.active ? s.color + "20" : "transparent",
                  color: s.color, cursor: "pointer", transition: "all 0.2s", whiteSpace: "nowrap",
                  boxShadow: s.active ? `0 0 10px ${s.color}40` : "none",
                }}
              >
                {s.active ? "ACTIVE" : "TRIGGER"}
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Right: live system response */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 14px" }}>
          <SectionHeader>System Response</SectionHeader>
          {[
            { l: "Link State", v: "ESTABLISHED", c: "#00ff88" },
            { l: "RX Power", v: `${fmt2(metrics.rxPower)} dBm`, c: "#00d4ff" },
            { l: "BER", v: fmtSci(metrics.ber), c: metrics.ber > 1e-9 ? "#ff2d55" : "#00d4ff" },
            { l: "SNR", v: `${fmt2(metrics.snr)} dB`, c: "#00d4ff" },
            { l: "Link Margin", v: `${fmt2(metrics.linkMargin)} dB`, c: "#00d4ff" },
          ].map(row => (
            <div key={row.l} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border-dim)" }}>
              <span style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "var(--font-display)", fontWeight: 600 }}>{row.l}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: row.c }}>{row.v}</span>
            </div>
          ))}
        </div>

        {/* RX Power mini chart */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "12px 14px", flex: 1 }}>
          <SectionHeader>RX Power — Live</SectionHeader>
          <div style={{ height: 120 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={metrics ? [metrics] : []}>
                <CartesianGrid strokeDasharray="2 4" />
                <XAxis hide />
                <YAxis domain={[-14, -10]} width={30} />
                <Line type="monotone" dataKey="rxPower" stroke="#00d4ff" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Demo guidance */}
        <div style={{ background: "var(--bg-card)", border: "1px solid rgba(0,212,255,0.12)", borderRadius: 4, padding: "10px 14px" }}>
          <div style={{ fontSize: 9, color: "#00d4ff", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700, marginBottom: 8 }}>DEMO SEQUENCE</div>
          {[
            "Start: wait for ESTABLISHED link",
            "Trigger Atmospheric Degradation — watch SNR fall",
            "Observe DEGRADED — alert response",
            "Trigger False Lock — demonstrate detection",
            "Clear stress — show system recovery",
          ].map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 8, padding: "4px 0", borderBottom: "1px solid var(--border-dim)" }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "#00d4ff", minWidth: 16 }}>{i + 1}.</span>
              <span style={{ fontSize: 10, color: "var(--text-secondary)", lineHeight: 1.4 }}>{s}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── False Lock View ──────────────────────────────────────────────────────────

const FalseLockView = ({ metrics }: { metrics: LiveMetrics }) => {
  const lockConfidence = clamp(metrics.trackingQuality, 0, 100);
  const alignConf = clamp(100 - metrics.pointingError * 2, 0, 100);
  const signalConf = clamp(metrics.snr / 80 * 100, 0, 100);

  const criteria = [
    { label: "BER within valid-lock threshold", pass: metrics.ber < 1e-9, measured: fmtSci(metrics.ber), threshold: "1e-9", desc: "High BER with apparent carrier lock indicates false acquisition" },
    { label: "SNR above minimum", pass: metrics.snr > 20, measured: `${fmt2(metrics.snr)} dB`, threshold: "20 dB", desc: "Low SNR with claimed lock suggests carrier false alarm" },
    { label: "Alignment confidence sufficient", pass: metrics.pointingError < 10, measured: `${fmt2(metrics.pointingError)} µrad`, threshold: "10 µrad", desc: "Excessive pointing error invalidates lock confidence" },
    { label: "Tracking stability acceptable", pass: metrics.trackingQuality > 90, measured: `${fmt2(metrics.trackingQuality)}%`, threshold: "90%", desc: "Unstable tracking with claimed lock is a false-lock indicator" },
    { label: "False-lock state not asserted", pass: true, measured: "0.868", threshold: "<1.0", desc: "Explicit false-lock detection from anomaly correlation engine" },
  ];

  const algorithms = [
    { name: "BER Threshold Monitor", desc: "Continuous BER measurement against acquisition validity window" },
    { name: "Alignment Confidence Engine", desc: "Pointing error vs. beam divergence ratio analysis" },
    { name: "Signal Persistence Checker", desc: "Power stability and carrier frequency validation" },
    { name: "Multi-parameter Correlation", desc: "Cross-correlation of BER, SNR, pointing, and tracking metrics" },
    { name: "Anomaly State Machine", desc: "State transition monitoring for false-lock pattern recognition" },
  ];

  const signatures = [
    { type: "Type I: BER Mismatch", desc: "BER exceeds 1e-6 threshold while carrier lock indicator is asserted. Indicates receiver AHE threshold misalignment or value floor shift." },
    { type: "Type II: Alignment Confidence Failure", desc: "Pointing error exceeds valid-lock envelope (20 µrad) while receiver claims tracking. Often caused by platform vibration or gimbal backlash." },
    { type: "Type III: Carrier Noise Lock", desc: "High RCP-apparent acquisition with degraded RCS indicates receiver locked to noise rather than signal carrier." },
  ];

  return (
    <div className="sweep-in" style={{ height: "100%", overflowY: "auto" }}>
      {/* Header banner */}
      <div style={{ background: "rgba(0,255,136,0.05)", border: "1px solid rgba(0,255,136,0.2)", borderRadius: 4, padding: "12px 16px", marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 16, letterSpacing: "0.1em", color: "#00ff88", marginBottom: 2 }}>LOCK VALID</div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>All lock validation criteria satisfied. Carrier acquisition confirmed with acceptable BER, SNR, and alignment confidence.</div>
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-dim)" }}>2026-09-07 14:55:38 UTC</div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {/* Confidence gauges */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "14px 16px" }}>
          <SectionHeader>Lock Confidence Metrics</SectionHeader>
          <div style={{ display: "flex", justifyContent: "space-around", padding: "12px 0 8px" }}>
            <GaugeRing value={lockConfidence} label="Overall" color="#00ff88" size={82} />
            <GaugeRing value={alignConf} label="Alignment" color="#00d4ff" size={82} />
            <GaugeRing value={signalConf} label="Signal" color="#bf5af2" size={82} />
          </div>
          <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 10, lineHeight: 1.6 }}>
            Lock validated against BER, SNR, alignment deviation, and tracking stability thresholds.
          </div>
        </div>

        {/* Criteria checklist */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "14px 16px" }}>
          <SectionHeader>Lock Validation Criteria</SectionHeader>
          {criteria.map(c => (
            <div key={c.label} style={{ borderBottom: "1px solid var(--border-dim)", padding: "7px 0", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                  <span style={{ fontSize: 10, color: c.pass ? "#00ff88" : "#ff2d55", fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.08em" }}>
                    {c.pass ? "PASS" : "FAIL"}
                  </span>
                  <span style={{ fontSize: 10, color: "var(--text-primary)" }}>{c.label}</span>
                </div>
                <div style={{ fontSize: 9, color: "var(--text-dim)", lineHeight: 1.4 }}>{c.desc}</div>
              </div>
              <div style={{ textAlign: "right", minWidth: 80 }}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: c.pass ? "#00d4ff" : "#ff2d55" }}>{c.measured}</div>
                <div style={{ fontSize: 9, color: "var(--text-dim)" }}>thr: {c.threshold}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Detection algorithms */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "14px 16px" }}>
          <SectionHeader>Detection Algorithms</SectionHeader>
          {algorithms.map(a => (
            <div key={a.name} style={{ display: "flex", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--border-dim)" }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#00d4ff", marginTop: 4, flexShrink: 0, boxShadow: "0 0 4px #00d4ff" }} />
              <div>
                <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 11, letterSpacing: "0.06em", color: "var(--text-primary)", marginBottom: 2 }}>{a.name}</div>
                <div style={{ fontSize: 10, color: "var(--text-secondary)" }}>{a.desc}</div>
              </div>
            </div>
          ))}
        </div>

        {/* False lock signatures */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, padding: "14px 16px" }}>
          <SectionHeader accent="#ff2d55">False Lock Signatures</SectionHeader>
          {signatures.map(s => (
            <div key={s.type} style={{ padding: "8px 0", borderBottom: "1px solid var(--border-dim)" }}>
              <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 11, color: "#ff8c00", letterSpacing: "0.06em", marginBottom: 4 }}>{s.type}</div>
              <div style={{ fontSize: 10, color: "var(--text-secondary)", lineHeight: 1.5 }}>{s.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── Event Log View ───────────────────────────────────────────────────────────

const EventLogView = ({ events }: { events: EventLogEntry[] }) => {
  const [filter, setFilter] = useState<"ALL" | "CRITICAL" | "WARNING" | "INFO">("ALL");

  const filtered = filter === "ALL" ? events : events.filter(e => e.level === filter);

  const levelColor = (l: string) => l === "CRITICAL" ? "#ff2d55" : l === "WARNING" ? "#ff8c00" : "#00d4ff";

  const counts = {
    CRITICAL: events.filter(e => e.level === "CRITICAL").length,
    WARNING: events.filter(e => e.level === "WARNING").length,
    INFO: events.filter(e => e.level === "INFO").length,
  };

  return (
    <div className="sweep-in" style={{ height: "100%", display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Summary row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
        {(["CRITICAL", "WARNING", "INFO"] as const).map(l => (
          <div key={l} style={{ background: "var(--bg-card)", border: `1px solid ${levelColor(l)}20`, borderRadius: 4, padding: "10px 14px", textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 600, color: levelColor(l), lineHeight: 1 }}>{counts[l]}</div>
            <div style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.12em", fontFamily: "var(--font-display)", fontWeight: 700, marginTop: 4 }}>{l}</div>
          </div>
        ))}
      </div>

      {/* Filter strip */}
      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
        {(["ALL", "CRITICAL", "WARNING", "INFO"] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 10, letterSpacing: "0.1em",
              padding: "4px 12px", border: `1px solid ${filter === f ? levelColor(f) || "#00d4ff" : "var(--border-dim)"}`,
              borderRadius: 2, background: filter === f ? `${levelColor(f) || "#00d4ff"}15` : "transparent",
              color: filter === f ? (levelColor(f) || "#00d4ff") : "var(--text-dim)", cursor: "pointer", transition: "all 0.15s",
            }}
          >
            {f === "ALL" ? "● ALL" : `● ${f}`}
          </button>
        ))}
        <span style={{ marginLeft: 8, fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
          CRITICAL — Immediate intervention required &nbsp;|&nbsp; WARNING — Potential degradation, monitor &nbsp;|&nbsp; INFO — Nominal operational information
        </span>
      </div>

      {/* Table */}
      <div style={{ flex: 1, background: "var(--bg-card)", border: "1px solid var(--border-dim)", borderRadius: 4, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {/* Table header */}
        <div style={{ display: "grid", gridTemplateColumns: "80px 110px 120px 1fr", padding: "8px 16px", borderBottom: "1px solid var(--border-med)", background: "var(--bg-panel)" }}>
          {["LEVEL", "TIMESTAMP", "SUBSYSTEM", "EVENT"].map(h => (
            <span key={h} style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.14em", fontFamily: "var(--font-display)", fontWeight: 700 }}>{h}</span>
          ))}
        </div>

        {/* Table body */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {filtered.length === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 10 }}>
              <div style={{ fontSize: 24, color: "var(--border-dim)" }}>◎</div>
              <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 13, letterSpacing: "0.1em", color: "var(--text-dim)" }}>NO ACTIVE EVENTS</div>
              <div style={{ fontSize: 10, color: "var(--text-dim)" }}>All systems nominal</div>
            </div>
          ) : (
            filtered.map(e => (
              <div key={e.id} style={{
                display: "grid", gridTemplateColumns: "80px 110px 120px 1fr",
                padding: "8px 16px", borderBottom: "1px solid var(--border-dim)",
                transition: "background 0.15s",
              }}
                onMouseEnter={ev => (ev.currentTarget as HTMLElement).style.background = "var(--bg-card-2)"}
                onMouseLeave={ev => (ev.currentTarget as HTMLElement).style.background = "transparent"}
              >
                <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 10, letterSpacing: "0.08em", color: levelColor(e.level), display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: levelColor(e.level), display: "inline-block" }} />
                  {e.level}
                </span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-secondary)" }}>{e.timestamp}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-dim)" }}>{e.subsystem}</span>
                <span style={{ fontSize: 11, color: "var(--text-primary)" }}>{e.event}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [paused, setPaused] = useState(false);
  const tickRef = useRef(0);

  const [metrics, setMetrics] = useState<LiveMetrics>({
    rxPower: -11.7, snr: 73.3, ber: 1.0e-12, linkMargin: 38.3,
    pointingError: 1.73, trackingQuality: 96,
    temperature: 22.2, humidity: 59, windSpeed: 4.2,
    visibility: 15, wavelength: 1550, distance: 5, dataRate: 10, oit: 0,
    atmLoss: 1.5,
  } as any);

  const [history, setHistory] = useState<TelemetryPoint[]>(() =>
    Array.from({ length: 60 }, (_, i) => ({
      t: i,
      rxPower: rnd(-11.7, 0.3),
      snr: rnd(73.3, 0.5),
      ber: Math.max(1e-14, rnd(1e-12, 2e-13)),
      pointingError: rnd(1.73, 0.2),
      atmLoss: rnd(1.5, 0.1),
    }))
  );

  const [simParams, setSimParams] = useState<SimParams>({
    txPower: 30, wavelength: 1550, linkDistance: 5,
    dataRate: 10, rxSensitivity: -50,
    beamDivergence: 1.5, pointingError: 5,
  });

  const [scenarios, setScenarios] = useState<StressScenario[]>([
    {
      id: "atm", name: "Atmospheric Degradation", badge: "RANGING", color: "#ff8c00",
      description: "Progressively increases atmospheric loss to simulate fog, haze, or precipitation. Loss increases until link margin is exhausted.",
      effects: ["Increasing ATM loss", "Decreasing RX power", "Rising BER", "Potential link degradation"],
      active: false,
    },
    {
      id: "beam", name: "Beam Misalignment", badge: "RANGING", color: "#ff8c00",
      description: "Introduces progressive pointing error simulating gimbal drift, vibration, or platform instability.",
      effects: ["Increasing pointing error", "Higher pointing loss", "Reduced RX power", "Tracking deviation"],
      active: false,
    },
    {
      id: "turb", name: "Turbulence Burst", badge: "CRITICAL", color: "#ff2d55",
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
    { id: 1, level: "INFO", timestamp: "14:54:38", subsystem: "LINK_CTRL", event: "Carrier acquisition confirmed. Lock state: ESTABLISHED" },
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
    addEvent("WARNING", "STRESS_CTRL", `Scenario triggered: ${names[id]}`);
  }, [addEvent]);

  // Live simulation tick
  useInterval(() => {
    if (paused) return;
    tickRef.current += 1;
    const t = tickRef.current;

    const activeIds = scenarios.filter(s => s.active).map(s => s.id);
    const hasTurb = activeIds.includes("turb");
    const hasAtm = activeIds.includes("atm");
    const hasBeam = activeIds.includes("beam");
    const hasSig = activeIds.includes("sig");

    const turbMult = hasTurb ? 3 : 1;
    const atmExtra = hasAtm ? Math.sin(t * 0.05) * 1.5 + 1.0 : 0;
    const beamExtra = hasBeam ? Math.min(t * 0.01, 8) : 0;
    const sigDrop = hasSig && t % 40 < 6 ? -8 : 0;

    const rxPower = clamp(rnd(-11.7 - atmExtra * 0.4 + sigDrop, 0.15 * turbMult) - beamExtra * 0.05, -18, -10);
    const snr = clamp(rnd(73.3 - atmExtra * 0.8 + sigDrop * 4, 0.2 * turbMult), 15, 80);
    const ber = Math.max(1e-15, rnd(1e-12, 2e-13 * turbMult) * (hasSig && t % 40 < 6 ? 1e4 : 1));
    const pointingError = clamp(rnd(1.73 + beamExtra * 0.5, 0.1 * turbMult), 0, 50);
    const linkMargin = clamp(38.3 + rxPower - (-11.7), 0, 50);
    const trackingQuality = clamp(rnd(96 - beamExtra * 2 - (hasTurb ? 5 : 0), 0.5), 40, 100);
    const atmLoss = clamp(1.5 + atmExtra * 0.4, 0.5, 8);

    setMetrics(prev => ({
      ...prev, rxPower, snr, ber, linkMargin, pointingError, trackingQuality, atmLoss,
      temperature: clamp(rnd(prev.temperature, 0.02), 15, 40),
      humidity: clamp(rnd(prev.humidity, 0.3), 30, 90),
      windSpeed: clamp(rnd(prev.windSpeed, 0.05), 0, 20),
    }));

    setHistory(prev => {
      const next = [...prev.slice(-119), { t, rxPower, snr, ber, pointingError, atmLoss }];
      return next;
    });

    // Event generation
    if (ber > 1e-9 && Math.random() < 0.05) addEvent("WARNING", "MODEM", `BER threshold exceeded: ${fmtSci(ber)}`);
    if (linkMargin < 6 && Math.random() < 0.1) addEvent("CRITICAL", "LINK_CTRL", `Link margin critical: ${fmt2(linkMargin)} dB`);
  }, 250);

  const navItems: { view: View; label: string; icon: string }[] = [
    { view: "overview", label: "OVERVIEW", icon: "⬡" },
    { view: "telemetry", label: "TELEMETRY", icon: "⌒" },
    { view: "simulation", label: "SIMULATE", icon: "⚙" },
    { view: "stress", label: "STRESS", icon: "⚡" },
    { view: "falselock", label: "LOCK VAL", icon: "◎" },
    { view: "eventlog", label: "EVENT LOG", icon: "≡" },
  ];

  return (
    <div style={{
      width: "100vw", height: "100vh", display: "flex", flexDirection: "column",
      background: "var(--bg-base)", overflow: "hidden", position: "relative",
    }}>
      {/* Top bar */}
      <TopBar metrics={metrics} paused={paused} onPause={() => setPaused(p => !p)} />

      {/* Body */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Sidebar */}
        <div style={{
          width: 58, flexShrink: 0, background: "var(--bg-panel)",
          borderRight: "1px solid var(--border-dim)",
          display: "flex", flexDirection: "column", padding: "8px 0",
        }}>
          {navItems.map(n => (
            <NavIcon key={n.view} view={n.view} active={view === n.view} onClick={setView} label={n.label}>
              <span style={{ fontSize: 16 }}>{n.icon}</span>
            </NavIcon>
          ))}

          {/* Bottom: ISRO logo text */}
          <div style={{ marginTop: "auto", padding: "8px 0", textAlign: "center" }}>
            <div style={{ fontSize: 7, color: "var(--text-dim)", fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.12em", lineHeight: 1.6 }}>
              ISRO<br />SIH<br />2026
            </div>
          </div>
        </div>

        {/* Main content */}
        <div style={{ flex: 1, overflow: "hidden", padding: 12, display: "flex", flexDirection: "column" }}>
          {/* Breadcrumb */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10, flexShrink: 0 }}>
            <span style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>FSOC PAT LAB</span>
            <span style={{ fontSize: 9, color: "var(--border-med)" }}>›</span>
            <span style={{ fontSize: 9, color: "#00d4ff", fontFamily: "var(--font-mono)", letterSpacing: "0.08em" }}>
              {navItems.find(n => n.view === view)?.label}
            </span>
            <div style={{ marginLeft: "auto", display: "flex", gap: 12 }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-dim)" }}>SIM RATE: 4 Hz</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: paused ? "#ff8c00" : "#00ff88" }}>
                {paused ? "● PAUSED" : "● LIVE"}
              </span>
            </div>
          </div>

          {/* View content */}
          <div style={{ flex: 1, overflow: "hidden" }}>
            {view === "overview" && <OverviewView metrics={metrics} history={history} />}
            {view === "telemetry" && <TelemetryView history={history} metrics={metrics} />}
            {view === "simulation" && (
              <SimulationView
                params={simParams}
                onChange={(k, v) => setSimParams(p => ({ ...p, [k]: v }))}
                metrics={metrics}
              />
            )}
            {view === "stress" && <StressView scenarios={scenarios} onTrigger={onTrigger} metrics={metrics} />}
            {view === "falselock" && <FalseLockView metrics={metrics} />}
            {view === "eventlog" && <EventLogView events={events} />}
          </div>
        </div>
      </div>

      {/* Bottom status strip */}
      <div style={{
        height: 22, background: "var(--bg-panel)", borderTop: "1px solid var(--border-dim)",
        display: "flex", alignItems: "center", padding: "0 16px", gap: 20,
        fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-dim)", flexShrink: 0,
      }}>
        <span style={{ color: "#00d4ff" }}>PAT.LAB v2.4.1</span>
        <span>ISRO · Dept. of Space · SIH 2026</span>
        <span>PS #4: AI-BASED VIRTUAL CAMERA TRACKING · FSOC COARSE ALIGNMENT</span>
        <span style={{ marginLeft: "auto" }}>
          TX: {simParams.txPower} dBm &nbsp;|&nbsp;
          λ: {simParams.wavelength} nm &nbsp;|&nbsp;
          D: {simParams.linkDistance} km &nbsp;|&nbsp;
          DATA: {simParams.dataRate} Gbps
        </span>
      </div>
    </div>
  );
}
