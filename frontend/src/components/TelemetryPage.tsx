import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Bar
} from "recharts";
import type { Telemetry, HistoryPoint } from "@/hooks/useTelemetry";

interface Props { telemetry: Telemetry | null; history: HistoryPoint[]; }

const TIP_STYLE = {
  backgroundColor:"#0d1220", border:"1px solid #1a2340", borderRadius:4,
  color:"#dce3f0", fontFamily:"DM Mono, monospace", fontSize:10, padding:"6px 10px",
};

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel rounded p-4">
      <div className="font-data mb-3" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>{title}</div>
      {children}
    </div>
  );
}

function CustomTip({ active, payload, label, fmt }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TIP_STYLE}>
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {fmt ? fmt(p.value) : typeof p.value === "number" ? p.value.toFixed(3) : p.value}
        </div>
      ))}
    </div>
  );
}

const STATE_COLOR: Record<string, string> = {
  SEARCHING:"#f0a500", TENTATIVE:"#4a9eff", LOCKED:"#00d4aa",
  DEGRADED_LOCK:"#5aeb96", COASTING:"#48dcff", REACQUIRING:"#be82ff", LOST:"#ff3c3c",
};

export default function TelemetryPage({ telemetry, history }: Props) {
  const data = history.map(h => ({
    t: +h.t.toFixed(2),
    pointing_px: +(h.pointing_err * 160).toFixed(2),
    est_px: +(h.est_err * 160).toFixed(2),
    confidence: +(h.confidence * 100).toFixed(1),
  }));

  const current = telemetry;

  return (
    <div className="p-3 overflow-y-auto h-full flex flex-col gap-3">

      {/* Current values ribbon */}
      {current && (
        <div className="panel rounded px-4 py-3 flex items-center gap-8">
          {[
            { label:"POINTING ERR", value:`${(current.pointing_err_deg*160).toFixed(2)} px`, color: current.pointing_err_deg*160 <= 10 ? "#00d4aa" : "#f0a500" },
            { label:"ESTIMATE ERR (CV)", value:`${(current.est_err_deg*160).toFixed(2)} px`, color:"#4a9eff" },
            { label:"CONFIDENCE", value:`${(current.confidence*100).toFixed(1)}%`, color:"#00d4aa" },
            { label:"VISION TRUST", value:`${(current.vision_trust*100).toFixed(0)}%`, color:"#48dcff" },
            { label:"MODEL TRUST", value:`${(current.model_trust*100).toFixed(0)}%`, color:"#be82ff" },
            { label:"SIGMA σ", value:`${current.sigma_px.toFixed(1)} px`, color: current.sigma_px < 18 ? "#7a8aaa" : "#ff3c3c" },
            { label:"TRUTH AZ", value:`${current.truth_az.toFixed(3)}°`, color:"#7a8aaa" },
            { label:"TRUTH EL", value:`${current.truth_el.toFixed(3)}°`, color:"#7a8aaa" },
          ].map(m => (
            <div key={m.label}>
              <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.07em" }}>{m.label}</div>
              <div className="font-data font-medium" style={{ fontSize:14, color:m.color }}>{m.value}</div>
            </div>
          ))}
          <div style={{ marginLeft:"auto" }}>
            <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.07em" }}>STATE</div>
            <div className="font-data font-medium" style={{ fontSize:14, color: STATE_COLOR[current.state] ?? "#7a8aaa" }}>{current.state.replace(/_/g," ")}</div>
          </div>
        </div>
      )}

      <div className="grid gap-3 flex-1" style={{ gridTemplateColumns:"1fr 1fr", gridTemplateRows:"1fr 1fr" }}>

        {/* Pointing error chart */}
        <Panel title="POINTING ERROR vs TIME — BORESIGHT RESIDUAL (px)">
          <ResponsiveContainer width="100%" height={170}>
            <ComposedChart data={data} margin={{ top:4, right:8, bottom:0, left:0 }}>
              <CartesianGrid stroke="#1a2340" strokeDasharray="2 4"/>
              <XAxis dataKey="t" tickFormatter={v=>`${v}s`} tick={{ fill:"#3d4f6e", fontSize:8, fontFamily:"DM Mono" }}/>
              <YAxis tickFormatter={v=>`${v}px`} tick={{ fill:"#3d4f6e", fontSize:8, fontFamily:"DM Mono" }} width={38}/>
              <Tooltip content={<CustomTip fmt={(v:number)=>`${v.toFixed(2)} px`}/>}/>
              <ReferenceLine y={10} stroke="#f0a500" strokeDasharray="4 3" strokeOpacity={0.7}
                label={{ value:"10px spec", fill:"#f0a500", fontSize:8, fontFamily:"DM Mono" }}/>
              <ReferenceLine y={20} stroke="#ff3c3c" strokeDasharray="2 4" strokeOpacity={0.5}/>
              <defs>
                <linearGradient id="ptGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00d4aa" stopOpacity={0.2}/>
                  <stop offset="100%" stopColor="#00d4aa" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="pointing_px" stroke="#00d4aa" fill="url(#ptGrad)" strokeWidth={1.5} dot={false} name="Pointing err"/>
              <Line type="monotone" dataKey="est_px" stroke="#4a9eff" strokeWidth={1} dot={false} strokeDasharray="3 2" name="Estimate err"/>
            </ComposedChart>
          </ResponsiveContainer>
          <div className="flex items-center gap-4 mt-1.5">
            <div className="flex items-center gap-1.5"><div style={{ width:16, height:2, background:"#00d4aa" }}/><span className="font-data" style={{ fontSize:8, color:"#7a8aaa" }}>Boresight pointing error</span></div>
            <div className="flex items-center gap-1.5"><div style={{ width:16, height:1, borderTop:"1px dashed #4a9eff" }}/><span className="font-data" style={{ fontSize:8, color:"#7a8aaa" }}>CV estimate error</span></div>
            <div className="flex items-center gap-1.5"><div style={{ width:16, height:1, borderTop:"1px dashed #f0a500" }}/><span className="font-data" style={{ fontSize:8, color:"#7a8aaa" }}>10 px spec</span></div>
          </div>
        </Panel>

        {/* Confidence chart */}
        <Panel title="TRACKING CONFIDENCE (%) — LOCK BANDS">
          <ResponsiveContainer width="100%" height={170}>
            <AreaChart data={data} margin={{ top:4, right:8, bottom:0, left:0 }}>
              <CartesianGrid stroke="#1a2340" strokeDasharray="2 4"/>
              <XAxis dataKey="t" tickFormatter={v=>`${v}s`} tick={{ fill:"#3d4f6e", fontSize:8, fontFamily:"DM Mono" }}/>
              <YAxis domain={[0,100]} tickFormatter={v=>`${v}%`} tick={{ fill:"#3d4f6e", fontSize:8, fontFamily:"DM Mono" }} width={38}/>
              <Tooltip content={<CustomTip fmt={(v:number)=>`${v.toFixed(1)}%`}/>}/>
              <ReferenceLine y={70} stroke="#00d4aa" strokeDasharray="4 3" strokeOpacity={0.5}
                label={{ value:"LOCKED ≥70%", fill:"#00d4aa", fontSize:8, fontFamily:"DM Mono" }}/>
              <ReferenceLine y={55} stroke="#5aeb96" strokeDasharray="3 4" strokeOpacity={0.4}
                label={{ value:"DEGRADED ≥55%", fill:"#5aeb96", fontSize:8, fontFamily:"DM Mono" }}/>
              <defs>
                <linearGradient id="confGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#be82ff" stopOpacity={0.25}/>
                  <stop offset="100%" stopColor="#be82ff" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="confidence" stroke="#be82ff" fill="url(#confGrad)" strokeWidth={1.5} dot={false} name="Confidence"/>
            </AreaChart>
          </ResponsiveContainer>
        </Panel>

        {/* Error histogram over state */}
        <Panel title="POINTING ERROR DISTRIBUTION BY STATE">
          {data.length > 5 ? (
            <ResponsiveContainer width="100%" height={170}>
              <LineChart data={data} margin={{ top:4, right:8, bottom:0, left:0 }}>
                <CartesianGrid stroke="#1a2340" strokeDasharray="2 4"/>
                <XAxis dataKey="t" tickFormatter={v=>`${v}s`} tick={{ fill:"#3d4f6e", fontSize:8, fontFamily:"DM Mono" }}/>
                <YAxis tickFormatter={v=>`${v}px`} tick={{ fill:"#3d4f6e", fontSize:8, fontFamily:"DM Mono" }} width={38}/>
                <Tooltip content={<CustomTip fmt={(v:number)=>`${v.toFixed(2)} px`}/>}/>
                <Line type="monotone" dataKey="pointing_px" stroke="#f0a500" strokeWidth={1.5} dot={false} name="Pointing"/>
                <Line type="monotone" dataKey="est_px" stroke="#7a6aff" strokeWidth={1} dot={false} strokeDasharray="2 3" name="Estimate"/>
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-40 font-data text-xs" style={{ color:"#2d3f5e" }}>Accumulating frames...</div>
          )}
        </Panel>

        {/* Sigma / reacquisition threshold */}
        <Panel title="UNCERTAINTY σ (px) — RE-ACQUISITION THRESHOLD AT 18 px">
          {current ? (
            <div>
              <div className="flex items-center gap-6 mb-3">
                <div>
                  <div className="font-data" style={{ fontSize:8, color:"#3d4f6e" }}>CURRENT σ</div>
                  <div className="font-data font-medium" style={{ fontSize:22, color: current.sigma_px < 10 ? "#00d4aa" : current.sigma_px < 18 ? "#f0a500" : "#ff3c3c", lineHeight:1 }}>
                    {current.sigma_px.toFixed(1)}<span style={{ fontSize:11, color:"#7a8aaa" }}> px</span>
                  </div>
                </div>
                <div style={{ flex:1 }}>
                  <div style={{ height:6, background:"#131d30", borderRadius:3, position:"relative" }}>
                    <div style={{ width:`${Math.min(100, (current.sigma_px/24)*100)}%`, height:"100%", borderRadius:3,
                      background: current.sigma_px < 10 ? "#00d4aa" : current.sigma_px < 18 ? "#f0a500" : "#ff3c3c",
                      transition:"width 0.3s" }}/>
                    <div style={{ position:"absolute", left:`${(18/24)*100}%`, top:-2, bottom:-2, width:1, background:"#ff3c3c", opacity:0.7 }}/>
                  </div>
                  <div className="flex justify-between mt-1">
                    <span className="font-data" style={{ fontSize:8, color:"#3d4f6e" }}>0</span>
                    <span className="font-data" style={{ fontSize:8, color:"#ff3c3c" }}>18 (reacq)</span>
                    <span className="font-data" style={{ fontSize:8, color:"#3d4f6e" }}>24</span>
                  </div>
                </div>
              </div>
              <div className="grid gap-3" style={{ gridTemplateColumns:"repeat(3,1fr)" }}>
                {[
                  { label:"ID Confidence", value:current.id_conf, color:"#00d4aa" },
                  { label:"Position Conf.", value:current.pos_conf, color:"#4a9eff" },
                  { label:"Pred. Conf.", value:current.pred_conf, color:"#be82ff" },
                ].map(c => (
                  <div key={c.label} className="p-2 rounded" style={{ background:"#0a0f1c", border:"1px solid #131d30" }}>
                    <div className="font-data mb-1" style={{ fontSize:8, color:"#3d4f6e" }}>{c.label}</div>
                    <div style={{ height:3, background:"#1a2340", borderRadius:2 }}>
                      <div style={{ width:`${c.value*100}%`, height:"100%", borderRadius:2, background:c.color }}/>
                    </div>
                    <div className="font-data mt-1" style={{ fontSize:10, color:c.color }}>{(c.value*100).toFixed(0)}%</div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-40 font-data text-xs" style={{ color:"#2d3f5e" }}>No data</div>
          )}
        </Panel>

      </div>
    </div>
  );
}
