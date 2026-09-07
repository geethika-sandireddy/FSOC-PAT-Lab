import { useMemo } from "react";
import type { Telemetry, HistoryPoint } from "@/hooks/useTelemetry";
import AzElPlot from "./AzElPlot";

interface Props {
  telemetry: Telemetry | null;
  history: HistoryPoint[];
}

const STATE_COLOR: Record<string, string> = {
  SEARCHING: "#f0a500", TENTATIVE: "#4a9eff", LOCKED: "#00d4aa",
  DEGRADED_LOCK: "#5aeb96", COASTING: "#48dcff", REACQUIRING: "#be82ff", LOST: "#ff3c3c",
};
const STATE_DESC: Record<string, string> = {
  SEARCHING: "Scanning — no beacon acquired",
  TENTATIVE: "Candidate under validation",
  LOCKED: "Tracking confirmed — all criteria met",
  DEGRADED_LOCK: "Lock held — reduced confidence band",
  COASTING: "Predictive coast — beacon temporarily obscured",
  REACQUIRING: "Re-acquisition ladder active",
  LOST: "Track lost — initiating blind search",
};

function KPI({ label, value, sub, color = "#dce3f0" }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="panel-dark rounded p-3 flex flex-col gap-1">
      <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>{label}</div>
      <div className="font-data font-medium" style={{ fontSize:17, color, lineHeight:1 }}>{value}</div>
      {sub && <div className="font-data" style={{ fontSize:8, color:"#3d4f6e" }}>{sub}</div>}
    </div>
  );
}

function TrustBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="font-data" style={{ fontSize:9, color:"#7a8aaa" }}>{label}</span>
        <span className="font-data font-medium" style={{ fontSize:10, color }}>{(value*100).toFixed(0)}%</span>
      </div>
      <div style={{ height:4, background:"#131d30", borderRadius:2 }}>
        <div style={{ width:`${value*100}%`, height:"100%", borderRadius:2, background:color, transition:"width 0.4s ease" }}/>
      </div>
    </div>
  );
}

function ConfBlock({ label, value, color }: { label: string; value: number; color: string }) {
  const pct = value * 100;
  return (
    <div className="flex flex-col items-center gap-1">
      <div style={{ position:"relative", width:40, height:40 }}>
        <svg width="40" height="40" viewBox="0 0 40 40">
          <circle cx="20" cy="20" r="16" stroke="#131d30" strokeWidth="4" fill="none"/>
          <circle cx="20" cy="20" r="16"
            stroke={color} strokeWidth="4" fill="none"
            strokeDasharray={`${pct * 1.005} ${100.5 - pct * 1.005}`}
            strokeDashoffset="25" strokeLinecap="round"
            style={{ transition:"stroke-dasharray 0.5s ease" }}/>
          <text x="20" y="24" textAnchor="middle" fill={color} fontSize="9" fontWeight="600" fontFamily="DM Mono">
            {pct.toFixed(0)}
          </text>
        </svg>
      </div>
      <span className="font-data" style={{ fontSize:7.5, color:"#5a6a88", letterSpacing:"0.06em", textAlign:"center" }}>{label}</span>
    </div>
  );
}

export default function OverviewPage({ telemetry, history }: Props) {
  if (!telemetry) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="font-data text-sm mb-2" style={{ color:"#3d4f6e", letterSpacing:"0.08em" }}>ACQUIRING TELEMETRY</div>
          <div className="font-data text-xs" style={{ color:"#1a2340" }}>Connecting to simulation engine...</div>
        </div>
      </div>
    );
  }

  const t = telemetry;
  const stateColor = STATE_COLOR[t.state] ?? "#7a8aaa";

  // Compute running stats from history
  const stats = useMemo(() => {
    if (history.length < 2) return null;
    const lockedPts = history.filter(h => h.state === "LOCKED" || h.state === "DEGRADED_LOCK");
    const errs = lockedPts.map(h => h.pointing_err);
    const acqFrame = history.findIndex(h => h.state === "LOCKED" || h.state === "DEGRADED_LOCK");
    const acqTime = acqFrame >= 0 ? (history[acqFrame].t - history[0].t) : null;
    const retention = history.length > 0 ? lockedPts.length / history.length : 0;
    const meanErr = errs.length > 0 ? errs.reduce((a, b) => a + b, 0) / errs.length : 0;
    const maxErr = errs.length > 0 ? Math.max(...errs) : 0;
    return { acqTime, retention, meanErr, maxErr };
  }, [history]);

  const pointing_px = t.pointing_err_deg * 160; // 160 px/°
  const est_px = t.est_err_deg * 160;

  return (
    <div className="flex flex-col gap-3 p-3 h-full overflow-y-auto">

      {/* Top row: state banner + KPIs */}
      <div className="grid gap-3" style={{ gridTemplateColumns:"1fr auto" }}>
        {/* State card */}
        <div className="panel rounded p-4 flex items-center gap-4"
          style={{ borderLeft:`3px solid ${stateColor}` }}>
          <div>
            <div className="font-data font-medium mb-1" style={{ fontSize:18, color:stateColor, letterSpacing:"0.05em" }}>
              {t.state.replace(/_/g," ")}
            </div>
            <div style={{ color:"#7a8aaa", fontSize:12 }}>{STATE_DESC[t.state]}</div>
          </div>
          <div style={{ marginLeft:"auto" }} className="flex items-center gap-6">
            <div className="text-center">
              <div className="font-data font-medium" style={{ fontSize:20, color: pointing_px <= 10 ? "#00d4aa" : pointing_px <= 20 ? "#f0a500" : "#ff3c3c" }}>
                {pointing_px.toFixed(1)}<span style={{ fontSize:11, color:"#7a8aaa", marginLeft:2 }}>px</span>
              </div>
              <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.07em" }}>POINTING ERR</div>
            </div>
            <div style={{ width:1, height:36, background:"#1a2340" }}/>
            <div className="text-center">
              <div className="font-data font-medium" style={{ fontSize:20, color: t.candidates > 0 ? "#4a9eff" : "#3d4f6e" }}>
                {t.candidates}<span style={{ fontSize:11, color:"#7a8aaa", marginLeft:2 }}>cand</span>
              </div>
              <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.07em" }}>DETECTION</div>
            </div>
            <div style={{ width:1, height:36, background:"#1a2340" }}/>
            <div className="text-center">
              <div className="font-data font-medium" style={{ fontSize:20, color: t.beacon_visible ? "#00d4aa" : "#ff3c3c" }}>
                {t.beacon_visible ? "VISIBLE" : "OBSCURED"}
              </div>
              <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.07em" }}>BEACON</div>
            </div>
            {t.false_lock && (
              <>
                <div style={{ width:1, height:36, background:"#1a2340" }}/>
                <div className="font-data font-medium px-3 py-1 rounded"
                  style={{ background:"#ff3c3c12", border:"1px solid #ff3c3c50", color:"#ff3c3c", fontSize:11, letterSpacing:"0.06em" }}>
                  ⚠ FALSE LOCK
                </div>
              </>
            )}
          </div>
        </div>

        {/* PS spec compliance */}
        <div className="panel rounded p-3" style={{ minWidth:180 }}>
          <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>PS SPEC COMPLIANCE</div>
          {[
            { label:"Pointing ≤ 10 px", ok: pointing_px <= 10, val: `${pointing_px.toFixed(1)}px` },
            { label:"Beacon in FOV", ok: t.in_fov, val: t.in_fov ? "YES" : "NO" },
            { label:"Candidates ≥ 1", ok: t.candidates >= 1 || t.state === "LOCKED", val: `${t.candidates}` },
            { label:"Gimbal sat.", ok: t.gimbal_sat_pan < 0.8, val: t.gimbal_sat_pan > 0.5 ? "SATURATED" : "OK" },
          ].map(r => (
            <div key={r.label} className="flex items-center justify-between py-1" style={{ borderBottom:"1px solid #0d1220" }}>
              <div className="flex items-center gap-1.5">
                <span className={`status-dot ${r.ok ? "dot-locked" : "dot-warning"}`} style={{ width:5, height:5 }}/>
                <span style={{ fontSize:10, color:"#5a6a88" }}>{r.label}</span>
              </div>
              <span className="font-data" style={{ fontSize:10, color: r.ok ? "#00d4aa" : "#f0a500" }}>{r.val}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Main content: radar + panels */}
      <div className="grid gap-3 flex-1 min-h-0" style={{ gridTemplateColumns:"auto 1fr auto" }}>

        {/* AzEl Plot */}
        <div className="panel rounded p-3 flex flex-col items-center justify-center">
          <AzElPlot telemetry={t} history={history} size={268} />
        </div>

        {/* Center column */}
        <div className="flex flex-col gap-3">
          {/* KPI grid */}
          <div className="grid gap-2" style={{ gridTemplateColumns:"repeat(4, 1fr)" }}>
            <KPI label="POINTING ERROR"
              value={`${pointing_px.toFixed(1)}`} sub="pixels (spec ≤10)"
              color={pointing_px <= 10 ? "#00d4aa" : pointing_px <= 20 ? "#f0a500" : "#ff3c3c"}/>
            <KPI label="ESTIMATE ERROR"
              value={`${est_px.toFixed(1)}`} sub="pixels (CV metric)"
              color={est_px <= 10 ? "#00d4aa" : "#f0a500"}/>
            <KPI label="CONFIDENCE"
              value={`${(t.confidence*100).toFixed(0)}%`} sub={`${t.trust_mode}`}
              color={t.confidence > 0.8 ? "#00d4aa" : t.confidence > 0.55 ? "#5aeb96" : "#f0a500"}/>
            <KPI label="UNCERTAINTY σ"
              value={`${t.sigma_px.toFixed(1)}`} sub="px (≤18 reacq)"
              color={t.sigma_px < 10 ? "#00d4aa" : t.sigma_px < 18 ? "#f0a500" : "#ff3c3c"}/>
          </div>

          {/* Phase 2: Confidence breakdown */}
          <div className="panel rounded p-4 flex flex-col gap-3">
            <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>PHASE 2 — UNIFIED CONFIDENCE DECOMPOSITION</div>
            <div className="flex items-center justify-around">
              <ConfBlock label="IDENTITY" value={t.id_conf} color="#00d4aa"/>
              <ConfBlock label="POSITION" value={t.pos_conf} color="#4a9eff"/>
              <ConfBlock label="PREDICTION" value={t.pred_conf} color="#be82ff"/>
              <ConfBlock label="POINTING" value={t.pt_conf} color="#f0a500"/>
            </div>
            <div style={{ borderTop:"1px solid #131d30", paddingTop:8 }}>
              <div className="flex items-center justify-between mb-1">
                <span style={{ fontSize:10, color:"#7a8aaa" }}>Trust mode</span>
                <span className="font-data font-medium" style={{ fontSize:10, color: t.trust_mode === "VISION_DOMINANT" ? "#48dcff" : t.trust_mode === "MODEL_DOMINANT" ? "#be82ff" : "#7a8aaa" }}>
                  {t.trust_mode}
                </span>
              </div>
              <TrustBar label="VISION TRUST" value={t.vision_trust} color="#48dcff"/>
              <div style={{ height:6 }}/>
              <TrustBar label="MODEL TRUST" value={t.model_trust} color="#be82ff"/>
            </div>
          </div>

          {/* Disturbance snapshot */}
          <div className="panel rounded p-3">
            <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>CURRENT DISTURBANCES</div>
            <div className="grid gap-x-6 gap-y-1" style={{ gridTemplateColumns:"1fr 1fr" }}>
              {Object.entries(t.disturbances).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between py-1" style={{ borderBottom:"1px solid #0d1220" }}>
                  <span style={{ fontSize:10, color:"#5a6a88", textTransform:"capitalize" }}>{k.replace(/_/g," ")}</span>
                  <div className="flex items-center gap-2">
                    <div style={{ width:40, height:3, background:"#131d30", borderRadius:1.5 }}>
                      <div style={{ width:`${Math.min(100, v)}%`, height:"100%", borderRadius:1.5, background: v > 60 ? "#ff3c3c" : v > 30 ? "#f0a500" : "#00d4aa" }}/>
                    </div>
                    <span className="font-data" style={{ fontSize:9, color:"#7a8aaa", minWidth:20 }}>{v}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right column: session stats */}
        <div className="panel rounded p-4 flex flex-col gap-4" style={{ minWidth:190 }}>
          <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>SESSION PERFORMANCE</div>
          {stats ? (
            <div className="flex flex-col gap-0">
              {[
                { label:"Acquisition time", value: stats.acqTime != null ? `${stats.acqTime.toFixed(2)} s` : "—", spec:"≤ 2 s", ok: stats.acqTime != null && stats.acqTime <= 2 },
                { label:"Lock retention", value: `${(stats.retention*100).toFixed(1)}%`, spec:"≥ 95%", ok: stats.retention >= 0.95 },
                { label:"Mean point. err.", value: `${(stats.meanErr*160).toFixed(2)} px`, spec:"≤ 10 px", ok: stats.meanErr*160 <= 10 },
                { label:"Max point. err.", value: `${(stats.maxErr*160).toFixed(2)} px`, spec:"≤ 10 px (nom)", ok: stats.maxErr*160 <= 15 },
                { label:"Sim time", value: `${t.t.toFixed(1)} s`, spec:"—", ok: true },
                { label:"Frames tracked", value: `${history.length}`, spec:"—", ok: true },
              ].map((row, i) => (
                <div key={row.label} className="py-2.5" style={{ borderBottom:"1px solid #0d1220" }}>
                  <div className="flex items-center justify-between mb-0.5">
                    <span style={{ fontSize:10, color:"#5a6a88" }}>{row.label}</span>
                    <span className="font-data font-medium" style={{ fontSize:11, color: row.ok ? "#00d4aa" : "#f0a500" }}>{row.value}</span>
                  </div>
                  <div style={{ fontSize:9, color:"#2d3f5e" }}>spec: {row.spec}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="font-data text-xs" style={{ color:"#2d3f5e" }}>Accumulating data...</div>
          )}

          {/* Gimbal saturation */}
          <div style={{ borderTop:"1px solid #131d30", paddingTop:12 }}>
            <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>GIMBAL SATURATION</div>
            <div className="mb-2">
              <div className="flex justify-between mb-1">
                <span style={{ fontSize:9, color:"#7a8aaa" }}>PAN</span>
                <span className="font-data" style={{ fontSize:9, color: t.gimbal_sat_pan > 0.7 ? "#ff3c3c" : "#7a8aaa" }}>
                  {(t.gimbal_sat_pan*100).toFixed(0)}%
                </span>
              </div>
              <div style={{ height:3, background:"#131d30", borderRadius:2 }}>
                <div style={{ width:`${t.gimbal_sat_pan*100}%`, height:"100%", borderRadius:2, background: t.gimbal_sat_pan > 0.7 ? "#ff3c3c" : "#4a9eff" }}/>
              </div>
            </div>
            <div>
              <div className="flex justify-between mb-1">
                <span style={{ fontSize:9, color:"#7a8aaa" }}>TILT</span>
                <span className="font-data" style={{ fontSize:9, color: t.gimbal_sat_tilt > 0.7 ? "#ff3c3c" : "#7a8aaa" }}>
                  {(t.gimbal_sat_tilt*100).toFixed(0)}%
                </span>
              </div>
              <div style={{ height:3, background:"#131d30", borderRadius:2 }}>
                <div style={{ width:`${t.gimbal_sat_tilt*100}%`, height:"100%", borderRadius:2, background: t.gimbal_sat_tilt > 0.7 ? "#ff3c3c" : "#4a9eff" }}/>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
