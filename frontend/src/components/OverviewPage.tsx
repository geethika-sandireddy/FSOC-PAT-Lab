import { useMemo } from "react";
import type { Telemetry, HistoryPoint } from "@/hooks/useTelemetry";
import AzElPlot from "./AzElPlot";

interface Props { telemetry: Telemetry | null; history: HistoryPoint[]; }

const STATE_COLOR: Record<string, string> = {
  SEARCHING:"var(--state-SEARCHING)", TENTATIVE:"var(--state-TENTATIVE)",
  LOCKED:"var(--state-LOCKED)", DEGRADED_LOCK:"var(--state-DEGRADED_LOCK)",
  COASTING:"var(--state-COASTING)", REACQUIRING:"var(--state-REACQUIRING)",
  LOST:"var(--state-LOST)",
};
const STATE_BG: Record<string, string> = {
  SEARCHING:"#30240012", TENTATIVE:"#00284a12", LOCKED:"#00301812",
  DEGRADED_LOCK:"#002410,10", COASTING:"#001e3012",
  REACQUIRING:"#1e0e4012", LOST:"#300a0a12",
};
const STATE_DESC: Record<string, string> = {
  SEARCHING:"Scanning — no beacon acquired",
  TENTATIVE:"Candidate found — validating",
  LOCKED:"Tracking confirmed — all PS criteria met",
  DEGRADED_LOCK:"Lock held at reduced confidence",
  COASTING:"Predictive coast — beacon obscured",
  REACQUIRING:"Re-acquisition active",
  LOST:"Track lost — blind search initiated",
};

/* ── Small reusable components ─────────────────────────────────────── */

function SectionLabel({ children }: { children: string }) {
  return (
    <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:8 }}>
      <div style={{ width:3, height:12, background:"var(--c-cyan)", borderRadius:1 }}/>
      <span className="font-data" style={{ fontSize:8, letterSpacing:"0.12em", color:"var(--c-faint)", textTransform:"uppercase" }}>
        {children}
      </span>
    </div>
  );
}

function BigKPI({ label, value, sub, color = "var(--c-text)" }:
  { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{
      background:"var(--c-panel-2)", border:"1px solid var(--c-border)",
      padding:"10px 14px", display:"flex", flexDirection:"column", gap:3,
    }}>
      <div className="font-data" style={{ fontSize:7.5, letterSpacing:"0.11em", color:"var(--c-faint)", textTransform:"uppercase" }}>
        {label}
      </div>
      <div className="font-data" style={{ fontSize:20, fontWeight:500, color, lineHeight:1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize:9, color:"var(--c-faint)" }}>{sub}</div>}
    </div>
  );
}

function HBar({ value, color, label }: { value: number; color: string; label?: string }) {
  return (
    <div>
      {label && <div style={{ fontSize:9, color:"var(--c-dim)", marginBottom:3 }}>{label}</div>}
      <div className="hbar-track" style={{ height:5 }}>
        <div className="hbar-fill" style={{ width:`${Math.min(100, value * 100)}%`, background:color }}/>
      </div>
    </div>
  );
}

function ArcGauge({ value, color, label, size = 60 }:
  { value: number; color: string; label: string; size?: number }) {
  const pct = value * 100;
  return (
    <div style={{ display:"flex", flexDirection:"column", alignItems:"center", gap:4 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size/2} cy={size/2} r={size/2 - 5}
          stroke="var(--c-panel-3)" strokeWidth="5" fill="none"/>
        <circle cx={size/2} cy={size/2} r={size/2 - 5}
          stroke={color} strokeWidth="5" fill="none"
          strokeDasharray={`${pct * (Math.PI * (size - 10)) / 100} ${Math.PI * (size - 10)}`}
          strokeDashoffset={Math.PI * (size - 10) * 0.25}
          strokeLinecap="round"
          style={{ transition:"stroke-dasharray 0.5s ease" }}
        />
        <text x={size/2} y={size/2 + 5} textAnchor="middle"
          fill={color} fontSize={size < 50 ? 9 : 11} fontWeight="600" fontFamily="DM Mono">
          {pct.toFixed(0)}
        </text>
      </svg>
      <span className="font-data" style={{ fontSize:7.5, color:"var(--c-faint)", letterSpacing:"0.08em", textAlign:"center" }}>
        {label}
      </span>
    </div>
  );
}

function SpecRow({ label, ok, value, spec }: { label: string; ok: boolean; value: string; spec: string }) {
  return (
    <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"7px 0", borderBottom:"1px solid var(--c-panel-3)" }}>
      <div style={{ display:"flex", alignItems:"center", gap:7 }}>
        <span className={`status-dot ${ok ? "dot-locked" : "dot-warning"}`}/>
        <span style={{ fontSize:10, color:"var(--c-dim)" }}>{label}</span>
        <span style={{ fontSize:8.5, color:"var(--c-faint)" }}>({spec})</span>
      </div>
      <span className="font-data" style={{ fontSize:10, fontWeight:500, color: ok ? "var(--c-green)" : "var(--c-amber)" }}>
        {value}
      </span>
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────────── */

export default function OverviewPage({ telemetry, history }: Props) {
  if (!telemetry) {
    return (
      <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:"100%", flexDirection:"column", gap:12 }}>
        <svg width="36" height="36" viewBox="0 0 36 36" fill="none" style={{ opacity:0.3 }}>
          <circle cx="18" cy="18" r="7" stroke="var(--c-cyan)" strokeWidth="2"/>
          <circle cx="18" cy="18" r="15" stroke="var(--c-cyan)" strokeWidth="1" strokeOpacity="0.4"/>
          <line x1="18" y1="2" x2="18" y2="8"  stroke="var(--c-cyan)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="18" y1="28" x2="18" y2="34" stroke="var(--c-cyan)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="2" y1="18" x2="8" y2="18"   stroke="var(--c-cyan)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="28" y1="18" x2="34" y2="18" stroke="var(--c-cyan)" strokeWidth="2" strokeLinecap="round"/>
        </svg>
        <div className="font-data" style={{ fontSize:10, letterSpacing:"0.1em", color:"var(--c-faint)" }}>
          ACQUIRING TELEMETRY...
        </div>
      </div>
    );
  }

  const t = telemetry;
  const stCol = STATE_COLOR[t.state] ?? "var(--c-dim)";
  const px    = t.pointing_err_deg * 160;
  const pxCol = px <= 10 ? "var(--c-green)" : px <= 20 ? "var(--c-amber)" : "var(--c-red)";

  const stats = useMemo(() => {
    if (history.length < 2) return null;
    const locked = history.filter(h => h.state === "LOCKED" || h.state === "DEGRADED_LOCK");
    const errs   = locked.map(h => h.pointing_err);
    const acqIdx = history.findIndex(h => h.state === "LOCKED" || h.state === "DEGRADED_LOCK");
    return {
      acqTime:   acqIdx >= 0 ? history[acqIdx].t - history[0].t : null,
      retention: history.length > 0 ? locked.length / history.length : 0,
      meanErr:   errs.length > 0 ? errs.reduce((a, b) => a + b, 0) / errs.length * 160 : 0,
      maxErr:    errs.length > 0 ? Math.max(...errs) * 160 : 0,
    };
  }, [history]);

  const acqOk  = stats?.acqTime != null && stats.acqTime <= 2;
  const retOk  = stats != null && stats.retention >= 0.95;
  const errOk  = px <= 10;

  return (
    <div style={{ display:"grid", gridTemplateColumns:"1fr 340px", gridTemplateRows:"auto 1fr", gap:1, height:"100%", overflow:"hidden", background:"var(--c-bg)" }}>

      {/* ── TOP BAND: State hero + KPI grid ──────────────────────────── */}
      <div style={{ gridColumn:"1/-1", display:"flex", gap:1, padding:1 }}>
        {/* State hero card */}
        <div style={{
          flex:"0 0 auto", minWidth:340, padding:"14px 20px",
          background:STATE_BG[t.state] ?? "var(--c-panel)",
          border:`1px solid ${stCol}40`,
          borderLeft:`4px solid ${stCol}`,
          display:"flex", flexDirection:"column", gap:6,
          transition:"border-color 0.4s, background 0.5s",
        }}>
          <div className="font-data" style={{ fontSize:8, letterSpacing:"0.12em", color:stCol, opacity:0.7, textTransform:"uppercase" }}>
            Track State
          </div>
          <div className="font-data" style={{ fontSize:26, fontWeight:700, color:stCol, lineHeight:1, letterSpacing:"0.03em" }}>
            {t.state.replace(/_/g, " ")}
          </div>
          <div style={{ fontSize:11, color:"var(--c-dim)" }}>{STATE_DESC[t.state]}</div>
          <div style={{ display:"flex", gap:16, marginTop:4 }}>
            <div>
              <div className="font-data" style={{ fontSize:7, color:"var(--c-faint)", letterSpacing:"0.1em" }}>BEACON</div>
              <div className="font-data" style={{ fontSize:11, color: t.beacon_visible ? "var(--c-green)" : "var(--c-red)", marginTop:1 }}>
                {t.beacon_visible ? "VISIBLE" : "OBSCURED"}
              </div>
            </div>
            <div>
              <div className="font-data" style={{ fontSize:7, color:"var(--c-faint)", letterSpacing:"0.1em" }}>IN FOV</div>
              <div className="font-data" style={{ fontSize:11, color: t.in_fov ? "var(--c-green)" : "var(--c-amber)", marginTop:1 }}>
                {t.in_fov ? "YES" : "NO"}
              </div>
            </div>
            <div>
              <div className="font-data" style={{ fontSize:7, color:"var(--c-faint)", letterSpacing:"0.1em" }}>CANDIDATES</div>
              <div className="font-data" style={{ fontSize:11, color: t.candidates > 0 ? "var(--c-cyan)" : "var(--c-faint)", marginTop:1 }}>
                {t.candidates}
              </div>
            </div>
            {t.false_lock && (
              <div style={{ display:"flex", alignItems:"center", padding:"2px 8px", background:"#ff2c2c14", border:"1px solid #ff2c2c50", color:"var(--c-red)" }}>
                <span className="font-data" style={{ fontSize:9, letterSpacing:"0.06em" }}>⚠ FALSE LOCK</span>
              </div>
            )}
          </div>
        </div>

        {/* KPI grid */}
        <div style={{ flex:1, display:"grid", gridTemplateColumns:"repeat(5, 1fr)", gap:1 }}>
          <BigKPI label="Pointing Error" value={`${px.toFixed(1)}`}
            sub="px (spec ≤ 10)" color={pxCol}/>
          <BigKPI label="Confidence" value={`${(t.confidence*100).toFixed(0)}%`}
            sub={t.trust_mode} color={t.confidence > 0.8 ? "var(--c-green)" : "var(--c-amber)"}/>
          <BigKPI label="Uncertainty σ" value={`${t.sigma_px.toFixed(1)}`}
            sub="px" color={t.sigma_px < 10 ? "var(--c-green)" : t.sigma_px < 18 ? "var(--c-amber)" : "var(--c-red)"}/>
          <BigKPI label="Estimate Error" value={`${(t.est_err_deg*160).toFixed(1)}`}
            sub="px" color="var(--c-cyan)"/>
          <BigKPI label="Sim Time" value={`${t.t.toFixed(1)}`} sub="seconds" color="var(--c-dim)"/>
        </div>
      </div>

      {/* ── MAIN LEFT COLUMN ─────────────────────────────────────────── */}
      <div style={{ display:"flex", flexDirection:"column", gap:1, overflow:"auto", padding:1 }}>

        {/* Phase 2: Unified confidence decomposition */}
        <div style={{ background:"var(--c-panel)", border:"1px solid var(--c-border)", padding:"14px 18px" }}>
          <SectionLabel>Phase 2 — Confidence Decomposition</SectionLabel>
          <div style={{ display:"flex", gap:24, justifyContent:"space-around", marginBottom:14 }}>
            <ArcGauge value={t.id_conf}   color="var(--c-green)"  label="IDENTITY"   size={62}/>
            <ArcGauge value={t.pos_conf}  color="var(--c-cyan)"   label="POSITION"   size={62}/>
            <ArcGauge value={t.pred_conf} color="var(--c-purple)" label="PREDICTION" size={62}/>
            <ArcGauge value={t.pt_conf}   color="var(--c-amber)"  label="POINTING"   size={62}/>
          </div>
          <div style={{ borderTop:"1px solid var(--c-panel-3)", paddingTop:10, display:"flex", flexDirection:"column", gap:8 }}>
            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:2 }}>
              <span style={{ fontSize:10, color:"var(--c-dim)" }}>Trust Mode</span>
              <span className="font-data" style={{ fontSize:10, fontWeight:500,
                color: t.trust_mode === "VISION_DOMINANT" ? "var(--c-cyan)" : t.trust_mode === "MODEL_DOMINANT" ? "var(--c-purple)" : "var(--c-dim)" }}>
                {t.trust_mode}
              </span>
            </div>
            <HBar value={t.vision_trust} color="var(--c-cyan)"   label={`VISION TRUST  ${(t.vision_trust*100).toFixed(0)}%`}/>
            <HBar value={t.model_trust}  color="var(--c-purple)" label={`MODEL TRUST   ${(t.model_trust*100).toFixed(0)}%`}/>
          </div>
        </div>

        {/* AzEl radar + gimbal */}
        <div style={{ display:"flex", gap:1, flex:1 }}>
          <div style={{ background:"var(--c-panel)", border:"1px solid var(--c-border)", padding:"14px 18px", display:"flex", flexDirection:"column" }}>
            <SectionLabel>Az/El Tracking Plot</SectionLabel>
            <div style={{ flex:1, display:"flex", alignItems:"center", justifyContent:"center" }}>
              <AzElPlot telemetry={t} history={history} size={220}/>
            </div>
          </div>

          <div style={{ flex:1, background:"var(--c-panel)", border:"1px solid var(--c-border)", padding:"14px 18px" }}>
            <SectionLabel>Gimbal / Actuator</SectionLabel>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10 }}>
              {[
                { label:"EST AZIMUTH",   val:`${t.est_az.toFixed(2)}°`, col:"var(--c-cyan)" },
                { label:"EST ELEVATION", val:`${t.est_el.toFixed(2)}°`, col:"var(--c-cyan)" },
                { label:"PAN SAT",   val:`${((t.gimbal_sat_pan ?? 0)*100).toFixed(0)}%`,
                  col:(t.gimbal_sat_pan ?? 0) > 0.7 ? "var(--c-red)" : "var(--c-dim)" },
                { label:"TILT SAT",  val:`${((t.gimbal_sat_tilt ?? 0)*100).toFixed(0)}%`,
                  col:(t.gimbal_sat_tilt ?? 0) > 0.7 ? "var(--c-red)" : "var(--c-dim)" },
              ].map(r => (
                <div key={r.label}>
                  <div className="font-data" style={{ fontSize:7.5, letterSpacing:"0.1em", color:"var(--c-faint)", marginBottom:3 }}>{r.label}</div>
                  <div className="font-data" style={{ fontSize:18, fontWeight:600, color:r.col, lineHeight:1 }}>{r.val}</div>
                </div>
              ))}
            </div>

            <div style={{ marginTop:14 }}>
              <div style={{ marginBottom:6 }}>
                <div style={{ display:"flex", justifyContent:"space-between", marginBottom:4 }}>
                  <span style={{ fontSize:9, color:"var(--c-dim)" }}>Pan Saturation</span>
                  <span className="font-data" style={{ fontSize:9, color:(t.gimbal_sat_pan??0)>0.7?"var(--c-red)":"var(--c-dim)" }}>
                    {((t.gimbal_sat_pan??0)*100).toFixed(0)}%
                  </span>
                </div>
                <HBar value={t.gimbal_sat_pan ?? 0} color={(t.gimbal_sat_pan??0)>0.7?"var(--c-red)":"var(--c-cyan)"}/>
              </div>
              <div>
                <div style={{ display:"flex", justifyContent:"space-between", marginBottom:4 }}>
                  <span style={{ fontSize:9, color:"var(--c-dim)" }}>Tilt Saturation</span>
                  <span className="font-data" style={{ fontSize:9, color:(t.gimbal_sat_tilt??0)>0.7?"var(--c-red)":"var(--c-dim)" }}>
                    {((t.gimbal_sat_tilt??0)*100).toFixed(0)}%
                  </span>
                </div>
                <HBar value={t.gimbal_sat_tilt ?? 0} color={(t.gimbal_sat_tilt??0)>0.7?"var(--c-red)":"var(--c-cyan)"}/>
              </div>
            </div>
          </div>
        </div>

        {/* Disturbances */}
        <div style={{ background:"var(--c-panel)", border:"1px solid var(--c-border)", padding:"14px 18px" }}>
          <SectionLabel>Current Disturbances</SectionLabel>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:"6px 20px" }}>
            {Object.entries(t.disturbances).map(([k, v]) => (
              <div key={k}>
                <div style={{ display:"flex", justifyContent:"space-between", marginBottom:3 }}>
                  <span style={{ fontSize:9.5, color:"var(--c-dim)", textTransform:"capitalize" }}>{k.replace(/_/g," ")}</span>
                  <span className="font-data" style={{ fontSize:9, color: v > 60 ? "var(--c-red)" : v > 30 ? "var(--c-amber)" : "var(--c-green)" }}>{v}</span>
                </div>
                <HBar value={v / 100} color={v > 60 ? "var(--c-red)" : v > 30 ? "var(--c-amber)" : "var(--c-cyan)"}/>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── RIGHT COLUMN ─────────────────────────────────────────────── */}
      <div style={{ display:"flex", flexDirection:"column", gap:1, overflow:"auto", padding:"1px 1px 1px 0" }}>

        {/* PS Spec compliance */}
        <div style={{ background:"var(--c-panel)", border:"1px solid var(--c-border)", padding:"14px 18px" }}>
          <SectionLabel>PS 26169 Spec Compliance</SectionLabel>
          <SpecRow label="Pointing ≤ 10 px"  ok={errOk}         value={`${px.toFixed(1)} px`}     spec="≤ 10 px"/>
          <SpecRow label="Acquisition ≤ 2 s"  ok={acqOk}         value={stats?.acqTime != null ? `${stats.acqTime.toFixed(2)} s` : "—"} spec="≤ 2 s"/>
          <SpecRow label="Retention ≥ 95%"    ok={retOk}         value={stats ? `${(stats.retention*100).toFixed(1)}%` : "—"} spec="≥ 95%"/>
          <SpecRow label="Beacon in FOV"       ok={t.in_fov}      value={t.in_fov ? "YES" : "NO"}  spec="required"/>
          <SpecRow label="False lock"          ok={!t.false_lock} value={t.false_lock ? "DETECTED" : "CLEAR"} spec="= 0"/>
          <SpecRow label="Gimbal headroom"     ok={(t.gimbal_sat_pan ?? 0) < 0.8} value={`${((t.gimbal_sat_pan ?? 0)*100).toFixed(0)}%`} spec="< 80%"/>
        </div>

        {/* Session performance */}
        <div style={{ background:"var(--c-panel)", border:"1px solid var(--c-border)", padding:"14px 18px", flex:1 }}>
          <SectionLabel>Session Performance</SectionLabel>
          {stats ? (
            <div style={{ display:"flex", flexDirection:"column", gap:0 }}>
              {[
                { label:"Acquisition time", val: stats.acqTime != null ? `${stats.acqTime.toFixed(2)} s` : "—", ok: acqOk },
                { label:"Lock retention",   val: `${(stats.retention*100).toFixed(1)}%`,  ok: retOk },
                { label:"Mean point. err",  val: `${stats.meanErr.toFixed(2)} px`,         ok: stats.meanErr <= 10 },
                { label:"Max point. err",   val: `${stats.maxErr.toFixed(2)} px`,          ok: stats.maxErr <= 15 },
                { label:"Frames tracked",   val: `${history.length}`,                      ok: true },
                { label:"Sim time",         val: `${t.t.toFixed(1)} s`,                   ok: true },
              ].map(row => (
                <div key={row.label} style={{ padding:"9px 0", borderBottom:"1px solid var(--c-panel-3)", display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                  <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                    <span className={`status-dot ${row.ok ? "dot-locked" : "dot-warning"}`}/>
                    <span style={{ fontSize:10, color:"var(--c-dim)" }}>{row.label}</span>
                  </div>
                  <span className="font-data" style={{ fontSize:11, fontWeight:500, color: row.ok ? "var(--c-green)" : "var(--c-amber)" }}>
                    {row.val}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="font-data" style={{ fontSize:9, color:"var(--c-faint)" }}>Accumulating data...</div>
          )}
        </div>

        {/* Trust mode visual */}
        <div style={{ background:"var(--c-panel)", border:"1px solid var(--c-border)", padding:"14px 18px" }}>
          <SectionLabel>Fusion Trust Mode</SectionLabel>
          <div style={{ display:"flex", gap:14, alignItems:"center" }}>
            <ArcGauge value={t.vision_trust} color="var(--c-cyan)"   label="VISION" size={52}/>
            <div style={{ flex:1 }}>
              <div className="font-data" style={{ fontSize:10, fontWeight:600,
                color: t.trust_mode === "VISION_DOMINANT" ? "var(--c-cyan)" : t.trust_mode === "MODEL_DOMINANT" ? "var(--c-purple)" : "var(--c-dim)",
                letterSpacing:"0.04em", marginBottom:6
              }}>
                {t.trust_mode}
              </div>
              <div style={{ fontSize:9, color:"var(--c-faint)", lineHeight:1.6 }}>
                Vision and model estimates are fused using adaptive weighting. The dominant channel drives the confidence score and re-acquisition timing.
              </div>
            </div>
            <ArcGauge value={t.model_trust} color="var(--c-purple)" label="MODEL" size={52}/>
          </div>
        </div>
      </div>
    </div>
  );
}
