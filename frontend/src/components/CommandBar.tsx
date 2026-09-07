import { useState, useEffect } from "react";
import type { TrackState } from "@/hooks/useTelemetry";

interface Props {
  state: TrackState | null;
  confidence: number;
  preset: string;
  connected: boolean;
  demoMode: boolean;
  running: boolean;
  falselock: boolean;
  onToggleRunning: () => void;
  onReset: () => void;
}

const STATE_COLOR: Record<TrackState, string> = {
  SEARCHING: "#f0a500",
  TENTATIVE: "#4a9eff",
  LOCKED: "#00d4aa",
  DEGRADED_LOCK: "#5aeb96",
  COASTING: "#48dcff",
  REACQUIRING: "#be82ff",
  LOST: "#ff3c3c",
};

const STATE_DOT: Record<TrackState, string> = {
  SEARCHING: "dot-warning",
  TENTATIVE: "dot-coast",
  LOCKED: "dot-locked",
  DEGRADED_LOCK: "dot-degraded",
  COASTING: "dot-coast",
  REACQUIRING: "dot-reacq",
  LOST: "dot-critical",
};

export default function CommandBar({ state, confidence, preset, connected, demoMode, running, falselock, onToggleRunning, onReset }: Props) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const stateColor = state ? STATE_COLOR[state] : "#3d4f6e";
  const dotClass = state ? STATE_DOT[state] : "dot-inactive";

  return (
    <div className="flex items-center justify-between px-4 shrink-0"
      style={{ height: 46, background: "#060a12", borderBottom: "1px solid #1a2340", zIndex: 50 }}>

      {/* Identity */}
      <div className="flex items-center gap-3">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <circle cx="10" cy="10" r="3.5" stroke="#00d4aa" strokeWidth="1.5"/>
          <circle cx="10" cy="10" r="7.5" stroke="#00d4aa" strokeWidth="0.6" strokeOpacity="0.35"/>
          <line x1="10" y1="1.5" x2="10" y2="4.5" stroke="#00d4aa" strokeWidth="1.5" strokeLinecap="round"/>
          <line x1="18.5" y1="10" x2="15.5" y2="10" stroke="#00d4aa" strokeWidth="1.5" strokeLinecap="round"/>
          <line x1="10" y1="18.5" x2="10" y2="15.5" stroke="#00d4aa" strokeWidth="1.5" strokeLinecap="round"/>
          <line x1="1.5" y1="10" x2="4.5" y2="10" stroke="#00d4aa" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
        <div>
          <div className="font-semibold" style={{ color: "#dce3f0", letterSpacing:"0.06em", fontSize:11 }}>FSOC-PAT MISSION CONTROL</div>
          <div className="font-data" style={{ color:"#2d3f5e", fontSize:8, letterSpacing:"0.08em" }}>AI VIRTUAL CAMERA TRACKING · SIH 2026 · PS 26169</div>
        </div>

        <div style={{ width:1, height:28, background:"#1a2340", margin:"0 4px" }}/>

        <div className="flex items-center gap-1.5">
          <span className={`status-dot ${dotClass}`}/>
          <span className="font-data font-medium" style={{ color: stateColor, letterSpacing:"0.08em", fontSize:11 }}>
            {state?.replace(/_/g," ") ?? "—"}
          </span>
        </div>

        {state === "LOCKED" || state === "DEGRADED_LOCK" ? (
          <div className="flex items-center gap-1.5 ml-2">
            <div style={{ width:48, height:3, background:"#131d30", borderRadius:2 }}>
              <div style={{ width:`${confidence*100}%`, height:"100%", borderRadius:2, background: confidence>0.8?"#00d4aa":confidence>0.6?"#5aeb96":"#f0a500", transition:"width 0.3s" }}/>
            </div>
            <span className="font-data" style={{ fontSize:9, color:"#7a8aaa" }}>{(confidence*100).toFixed(0)}%</span>
          </div>
        ) : null}
      </div>

      {/* Center alerts */}
      <div className="flex items-center gap-3">
        {falselock && (
          <div className="flex items-center gap-2 px-3 py-1 rounded font-data"
            style={{ background:"#ff3c3c12", border:"1px solid #ff3c3c50", color:"#ff3c3c", fontSize:10, letterSpacing:"0.07em" }}>
            <span className="status-dot dot-critical"/>FALSE LOCK DETECTED
          </div>
        )}
        {demoMode && (
          <div className="font-data px-2 py-1 rounded" style={{ background:"#f0a50012", border:"1px solid #f0a50040", color:"#f0a500", fontSize:9, letterSpacing:"0.07em" }}>
            DEMO MODE — start server.py for live data
          </div>
        )}
        {connected && !demoMode && (
          <div className="flex items-center gap-1.5">
            <span className="status-dot dot-locked" style={{ width:5, height:5 }}/>
            <span className="font-data" style={{ fontSize:9, color:"#00d4aa", letterSpacing:"0.06em" }}>LIVE</span>
          </div>
        )}
      </div>

      {/* Right */}
      <div className="flex items-center gap-3">
        <div className="font-data" style={{ fontSize:9, color:"#3d4f6e", letterSpacing:"0.04em" }}>
          {now.toISOString().replace("T"," ").slice(0,19)} UTC
        </div>
        <div className="font-data px-2 py-0.5 rounded" style={{ background:"#4a9eff12", border:"1px solid #4a9eff30", color:"#4a9eff", fontSize:9, letterSpacing:"0.06em" }}>
          {preset}
        </div>
        <div style={{ width:1, height:26, background:"#1a2340" }}/>
        <button onClick={onReset}
          className="font-data px-2.5 py-1 rounded transition-all"
          style={{ background:"#131d30", border:"1px solid #1a2340", color:"#7a8aaa", fontSize:10, cursor:"pointer", letterSpacing:"0.06em" }}>
          RESET
        </button>
        <button onClick={onToggleRunning}
          className="font-data px-2.5 py-1 rounded transition-all"
          style={{ background: running?"#00d4aa12":"#ff3c3c12", border:`1px solid ${running?"#00d4aa35":"#ff3c3c35"}`, color: running?"#00d4aa":"#ff3c3c", fontSize:10, cursor:"pointer", letterSpacing:"0.06em" }}>
          {running ? "■ RUNNING" : "▶ PAUSED"}
        </button>
      </div>
    </div>
  );
}
