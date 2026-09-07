import { useEffect, useState } from "react";
import type { Telemetry } from "@/hooks/useTelemetry";

const STATE_COLOR: Record<string, string> = {
  SEARCHING:    "var(--state-SEARCHING)",
  TENTATIVE:    "var(--state-TENTATIVE)",
  LOCKED:       "var(--state-LOCKED)",
  DEGRADED_LOCK:"var(--state-DEGRADED_LOCK)",
  COASTING:     "var(--state-COASTING)",
  REACQUIRING:  "var(--state-REACQUIRING)",
  LOST:         "var(--state-LOST)",
};
const STATE_DOT: Record<string, string> = {
  SEARCHING:"dot-warning", TENTATIVE:"dot-coast", LOCKED:"dot-locked",
  DEGRADED_LOCK:"dot-degraded", COASTING:"dot-coast",
  REACQUIRING:"dot-reacq", LOST:"dot-critical",
};
const STATE_BG: Record<string, string> = {
  SEARCHING:"#30240000", TENTATIVE:"#00244800", LOCKED:"#00302000",
  DEGRADED_LOCK:"#00241800", COASTING:"#00203000",
  REACQUIRING:"#20104000", LOST:"#30080800",
};

interface Props {
  telemetry: Telemetry | null;
  connected: boolean;
  demoMode: boolean;
  running: boolean;
  onToggleRunning: () => void;
  onReset: () => void;
}

function MetricBlock({ label, value, color, mono = true }:
  { label: string; value: string; color: string; mono?: boolean }) {
  return (
    <div style={{ display:"flex", flexDirection:"column", gap:2, padding:"0 18px" }}>
      <div className="font-data" style={{ fontSize:7, letterSpacing:"0.12em", color:"var(--c-faint)", textTransform:"uppercase" }}>
        {label}
      </div>
      <div className={mono ? "font-data" : ""} style={{ fontSize:16, fontWeight:600, color, lineHeight:1 }}>
        {value}
      </div>
    </div>
  );
}

export default function MissionHeader({ telemetry: t, connected, demoMode, running, onToggleRunning, onReset }: Props) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(n => n + 1), 500);
    return () => clearInterval(id);
  }, []);

  const st    = t?.state ?? "SEARCHING";
  const col   = STATE_COLOR[st] ?? "var(--c-dim)";
  const dotCls= STATE_DOT[st]   ?? "dot-inactive";
  const bg    = STATE_BG[st]    ?? "transparent";

  const px    = t ? t.pointing_err_deg * 160 : 0;
  const pxCol = px <= 10 ? "var(--c-green)" : px <= 20 ? "var(--c-amber)" : "var(--c-red)";
  const confPct = t ? t.confidence * 100 : 0;
  const confCol = confPct >= 80 ? "var(--c-green)" : confPct >= 55 ? "var(--c-amber)" : "var(--c-red)";

  return (
    <header style={{
      display:"flex", alignItems:"stretch",
      height:62,
      background:"var(--c-panel)",
      borderBottom:"1px solid var(--c-border-b)",
      position:"relative",
      overflow:"hidden",
    }}>
      {/* Top accent line */}
      <div style={{ position:"absolute", top:0, left:0, right:0, height:2, background:"var(--c-cyan)", opacity:0.8 }}/>

      {/* System identity */}
      <div style={{
        display:"flex", flexDirection:"column", justifyContent:"center",
        padding:"0 20px", borderRight:"1px solid var(--c-border)",
        background:"var(--c-panel-2)", minWidth:210,
      }}>
        <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:2 }}>
          {/* Target/crosshair icon */}
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <circle cx="9" cy="9" r="3" stroke="var(--c-cyan)" strokeWidth="1.5"/>
            <circle cx="9" cy="9" r="7" stroke="var(--c-cyan)" strokeWidth="0.6" opacity="0.4"/>
            <line x1="9" y1="1" x2="9" y2="5"  stroke="var(--c-cyan)" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="9" y1="13" x2="9" y2="17" stroke="var(--c-cyan)" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="1" y1="9" x2="5"  y2="9"  stroke="var(--c-cyan)" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="13" y1="9" x2="17" y2="9" stroke="var(--c-cyan)" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <span style={{ fontWeight:700, fontSize:12, letterSpacing:"0.06em", color:"var(--c-text)" }}>
            FSOC-PAT CONSOLE
          </span>
        </div>
        <div className="font-data" style={{ fontSize:7.5, letterSpacing:"0.1em", color:"var(--c-faint)" }}>
          AI VIRTUAL CAMERA TRACKING  ·  SIH 2026  ·  PS 26169
        </div>
      </div>

      {/* State block — state-reactive background */}
      <div style={{
        display:"flex", alignItems:"center", gap:14,
        padding:"0 22px",
        borderRight:"1px solid var(--c-border)",
        background:bg,
        borderLeft:`3px solid ${col}`,
        minWidth:230,
        transition:"background 0.5s, border-color 0.3s",
      }}>
        <span className={`status-dot ${dotCls}`} style={{ width:8, height:8 }}/>
        <div>
          <div className="font-data" style={{ fontSize:7, letterSpacing:"0.12em", color:"var(--c-faint)", marginBottom:2, textTransform:"uppercase" }}>
            Track State
          </div>
          <div className="font-data" style={{ fontSize:18, fontWeight:600, color: col, lineHeight:1, letterSpacing:"0.04em" }}>
            {st.replace(/_/g, " ")}
          </div>
        </div>
        {/* Confidence mini-arc */}
        <svg width="38" height="38" viewBox="0 0 38 38" style={{ marginLeft:4, flexShrink:0 }}>
          <circle cx="19" cy="19" r="14" stroke="var(--c-panel-3)" strokeWidth="4" fill="none"/>
          <circle cx="19" cy="19" r="14"
            stroke={col} strokeWidth="4" fill="none"
            strokeDasharray={`${confPct * 0.879} 87.96`}
            strokeDashoffset="22"
            strokeLinecap="round"
            style={{ transition:"stroke-dasharray 0.5s" }}
          />
          <text x="19" y="23" textAnchor="middle" fill={col} fontSize="9" fontWeight="600" fontFamily="DM Mono">
            {confPct.toFixed(0)}
          </text>
        </svg>
      </div>

      {/* Live metrics */}
      <div style={{ display:"flex", alignItems:"center", borderRight:"1px solid var(--c-border)" }}>
        <MetricBlock label="Pointing Error" value={t ? `${px.toFixed(1)} px` : "—"} color={pxCol} />
        <div style={{ width:1, height:36, background:"var(--c-border)" }}/>
        <MetricBlock label="Confidence" value={t ? `${confPct.toFixed(0)}%` : "—"} color={confCol} />
        <div style={{ width:1, height:36, background:"var(--c-border)" }}/>
        <MetricBlock label="Sim Time" value={t ? `${t.t.toFixed(1)} s` : "—"} color="var(--c-dim)" />
        <div style={{ width:1, height:36, background:"var(--c-border)" }}/>
        <MetricBlock label="Detections" value={t ? `${t.candidates}` : "—"} color={t && t.candidates > 0 ? "var(--c-cyan)" : "var(--c-faint)"} />
      </div>

      {/* Spacer */}
      <div style={{ flex:1 }}/>

      {/* False-lock alert */}
      {t?.false_lock && (
        <div style={{
          display:"flex", alignItems:"center", gap:8, padding:"0 16px",
          background:"#ff2c2c10", borderLeft:"2px solid var(--c-red)",
          color:"var(--c-red)",
        }}>
          <span className="font-data" style={{ fontSize:10, letterSpacing:"0.08em" }}>⚠ FALSE LOCK</span>
        </div>
      )}

      {/* Connection badge */}
      <div style={{
        display:"flex", alignItems:"center", gap:7, padding:"0 16px",
        borderLeft:"1px solid var(--c-border)",
      }}>
        <span className={`status-dot ${connected ? "dot-locked" : "dot-critical"}`}/>
        <div>
          <div className="font-data" style={{ fontSize:8, color: connected ? "var(--c-green)" : "var(--c-red)", letterSpacing:"0.08em" }}>
            {connected ? (demoMode ? "DEMO" : "LIVE") : "OFFLINE"}
          </div>
          <div className="font-data" style={{ fontSize:7, color:"var(--c-faint)" }}>
            {connected ? "WS" : "NO CONN"}
          </div>
        </div>
      </div>

      {/* Controls */}
      <div style={{ display:"flex", alignItems:"center", gap:8, padding:"0 16px", borderLeft:"1px solid var(--c-border)" }}>
        <button
          className={`ctrl-btn ${running ? "ctrl-btn-amber" : "ctrl-btn-green"}`}
          onClick={onToggleRunning}
          style={{ padding:"5px 14px" }}
        >
          {running ? "■ PAUSE" : "▶ RESUME"}
        </button>
        <button className="ctrl-btn ctrl-btn-cyan" onClick={onReset}>
          ↺ RESET
        </button>
      </div>
    </header>
  );
}
