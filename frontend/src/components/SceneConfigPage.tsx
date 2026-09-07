import { useState } from "react";

interface Props {
  currentPreset: string;
  onSetPreset: (p: string) => void;
  onSetDisturbance: (k: string, v: number) => void;
  telemetry: any;
}

const PRESETS = ["EASY", "MODERATE", "HARD", "SEVERE", "ADVERSARIAL", "ISRO_RX"];

const PRESET_DESC: Record<string, string> = {
  EASY: "No distractors or obstacles. Low noise. Ideal for baseline demonstration.",
  MODERATE: "1 distractor, 1 obstacle. Moderate turbulence. Realistic operational scenario.",
  HARD: "2 distractors, 2 obstacles. High turbulence and vibration. Tests algorithm robustness.",
  SEVERE: "4 distractors, 3 obstacles. Beyond-design-basis conditions. Stress exposure test.",
  ADVERSARIAL: "4 distractors, 4 obstacles. Maximum difficulty. Algorithm breaking point.",
  ISRO_RX: "ISRO reference-terminal preset. Matches SIH evaluation terminal parameters.",
};

const PRESET_COLORS: Record<string, string> = {
  EASY:"#00d4aa", MODERATE:"#4a9eff", HARD:"#f0a500", SEVERE:"#ff7700", ADVERSARIAL:"#ff3c3c", ISRO_RX:"#be82ff",
};

const PRESET_TABLE: Record<string, { turb:number; vib:number; noise:number; fade:number; dist:number; obs:number; acq:string; ret:string }> = {
  EASY:       { turb:5,  vib:2,  noise:5,  fade:0,  dist:0, obs:0, acq:"0.23s", ret:"100%" },
  MODERATE:   { turb:20, vib:8,  noise:10, fade:10, dist:1, obs:1, acq:"0.23s", ret:"96.8–100%" },
  HARD:       { turb:40, vib:18, noise:18, fade:30, dist:2, obs:2, acq:"0.23–0.47s", ret:"100%" },
  SEVERE:     { turb:65, vib:32, noise:28, fade:45, dist:4, obs:3, acq:"0.40–1.72s", ret:"96.6–100%" },
  ADVERSARIAL:{ turb:85, vib:45, noise:38, fade:60, dist:4, obs:4, acq:"0.23–0.47s", ret:"100%" },
  ISRO_RX:    { turb:25, vib:10, noise:12, fade:5,  dist:2, obs:1, acq:"0.23–0.47s", ret:"100%" },
};

interface SliderRowProps {
  label: string; desc: string; paramKey: string; min: number; max: number;
  value: number; onChange: (k: string, v: number) => void;
}

function SliderRow({ label, desc, paramKey, min, max, value, onChange }: SliderRowProps) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className="py-3" style={{ borderBottom:"1px solid #131d30" }}>
      <div className="flex items-center justify-between mb-1.5">
        <div>
          <span className="text-xs font-medium" style={{ color:"#dce3f0" }}>{label}</span>
          <span className="text-xs ml-2" style={{ color:"#3d4f6e" }}>{desc}</span>
        </div>
        <span className="font-data font-medium" style={{ fontSize:13, color:"#dce3f0", minWidth:40, textAlign:"right" }}>{value}</span>
      </div>
      <input type="range" min={min} max={max} step={1} value={value}
        onChange={e => onChange(paramKey, parseInt(e.target.value))}
        style={{ background:`linear-gradient(to right, #00d4aa ${pct}%, #1a2340 ${pct}%)` }}/>
      <div className="flex justify-between mt-0.5">
        <span className="font-data" style={{ fontSize:8, color:"#2d3f5e" }}>{min}</span>
        <span className="font-data" style={{ fontSize:8, color:"#2d3f5e" }}>{max}</span>
      </div>
    </div>
  );
}

export default function SceneConfigPage({ currentPreset, onSetPreset, onSetDisturbance, telemetry }: Props) {
  const [localDist, setLocalDist] = useState({
    turbulence: telemetry?.disturbances?.turbulence ?? 5,
    vibration: telemetry?.disturbances?.vibration ?? 2,
    sensor_noise: telemetry?.disturbances?.sensor_noise ?? 5,
    jerk_prob: telemetry?.disturbances?.jerk_prob ?? 0,
    beacon_fade: telemetry?.disturbances?.beacon_fade ?? 0,
  });

  function handleDist(k: string, v: number) {
    setLocalDist(prev => ({ ...prev, [k]: v }));
    onSetDisturbance(k, v);
  }

  const pt = PRESET_TABLE[currentPreset];

  return (
    <div className="p-4 overflow-y-auto h-full flex flex-col gap-4">

      {/* Preset selector */}
      <div className="panel rounded p-4">
        <div className="font-data mb-3" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>DIFFICULTY PRESET</div>
        <div className="flex gap-2 flex-wrap mb-4">
          {PRESETS.map(p => {
            const active = p === currentPreset;
            const color = PRESET_COLORS[p];
            return (
              <button key={p} onClick={() => onSetPreset(p)}
                className="font-data px-4 py-2 rounded transition-all"
                style={{
                  background: active ? `${color}18` : "#0a0f1c",
                  border: `1px solid ${active ? color+"50" : "#1a2340"}`,
                  color: active ? color : "#5a6a88",
                  fontSize:11, cursor:"pointer", letterSpacing:"0.06em", fontWeight: active ? 600 : 400,
                }}>
                {p}
              </button>
            );
          })}
        </div>
        <div className="flex items-start gap-6">
          <div style={{ flex:1 }}>
            <div className="text-xs mb-2" style={{ color:"#7a8aaa" }}>{PRESET_DESC[currentPreset]}</div>
            {pt && (
              <div className="grid gap-x-8 gap-y-1" style={{ gridTemplateColumns:"repeat(4,1fr)" }}>
                {[
                  ["Turbulence", pt.turb], ["Vibration", pt.vib],
                  ["Noise", pt.noise], ["Beacon fade", `${pt.fade}%`],
                  ["Distractors", pt.dist], ["Obstacles", pt.obs],
                  ["Acq. time", pt.acq], ["Retention", pt.ret],
                ].map(([k, v]) => (
                  <div key={k as string} className="flex items-center justify-between py-1" style={{ borderBottom:"1px solid #0d1220" }}>
                    <span style={{ fontSize:10, color:"#5a6a88" }}>{k}</span>
                    <span className="font-data font-medium" style={{ fontSize:10, color:"#7a8aaa" }}>{v}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-4" style={{ gridTemplateColumns:"1fr 1fr" }}>
        {/* Disturbance controls */}
        <div className="panel rounded p-4">
          <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>DISTURBANCE CONTROLS — LIVE OVERRIDE</div>
          <div className="text-xs mb-3" style={{ color:"#2d3f5e" }}>
            Adjustments take effect immediately on the running simulation. Switching preset resets all values.
          </div>
          <SliderRow label="Turbulence" desc="Atmospheric scintillation" paramKey="turbulence" min={0} max={100} value={localDist.turbulence} onChange={handleDist}/>
          <SliderRow label="Vibration" desc="Platform vibration amplitude" paramKey="vibration" min={0} max={60} value={localDist.vibration} onChange={handleDist}/>
          <SliderRow label="Sensor Noise" desc="Image noise level (σ)" paramKey="sensor_noise" min={0} max={50} value={localDist.sensor_noise} onChange={handleDist}/>
          <SliderRow label="Jerk Probability" desc="% probability of frame jerk" paramKey="jerk_prob" min={0} max={20} value={localDist.jerk_prob} onChange={handleDist}/>
          <SliderRow label="Beacon Fade" desc="% of frames with fade" paramKey="beacon_fade" min={0} max={80} value={localDist.beacon_fade} onChange={handleDist}/>
        </div>

        {/* System parameters reference */}
        <div className="panel rounded p-4">
          <div className="font-data mb-3" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>SYSTEM PARAMETERS — PS 26169 DEFAULTS</div>
          <div className="flex flex-col gap-0">
            {[
              { param:"Screen Size", value:"2000 × 2000 px", spec:"min 2000×2000", ok:true },
              { param:"Camera Resolution", value:"640 × 480 px", spec:"default", ok:true },
              { param:"Camera FOV", value:"4° × 3°", spec:"user-defined", ok:true },
              { param:"Camera Update Rate", value:"30–60 Hz", spec:"≥30 Hz", ok:true },
              { param:"Pixels per Degree", value:"160 px/°", spec:"derived", ok:true },
              { param:"Max Pan Speed", value:"5 °/s", spec:"5–10 °/s", ok:true },
              { param:"Max Tilt Speed", value:"5 °/s", spec:"5–10 °/s", ok:true },
              { param:"Target Shape", value:"Square", spec:"default", ok:true },
              { param:"Target Size", value:"10 × 10 px", spec:"5–20 px", ok:true },
              { param:"Acquisition Time", value:"≤0.47 s (typical)", spec:"≤2 s", ok:true },
              { param:"Tracking Error", value:"2–6 px (EASY–MOD)", spec:"≤10 px", ok:true },
              { param:"Re-acquisition Time", value:"≤0.86 s", spec:"≤1 s", ok:true },
              { param:"Processing Speed", value:"41–59 fps (light)", spec:"≥20 fps", ok:true },
              { param:"False Locks", value:"0 (EASY/HARD/ADV)", spec:"minimise", ok:true },
            ].map(r => (
              <div key={r.param} className="flex items-center justify-between py-1.5" style={{ borderBottom:"1px solid #0d1220" }}>
                <div className="flex items-center gap-2">
                  <span className={`status-dot ${r.ok ? "dot-locked" : "dot-warning"}`} style={{ width:5, height:5 }}/>
                  <span style={{ fontSize:10, color:"#5a6a88" }}>{r.param}</span>
                </div>
                <div className="text-right">
                  <div className="font-data" style={{ fontSize:10, color:"#00d4aa" }}>{r.value}</div>
                  <div className="font-data" style={{ fontSize:8, color:"#2d3f5e" }}>spec: {r.spec}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Noise types */}
      <div className="panel rounded p-4">
        <div className="font-data mb-3" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>SUPPORTED DISTURBANCE TYPES — PS 26169</div>
        <div className="grid gap-3" style={{ gridTemplateColumns:"repeat(4,1fr)" }}>
          {[
            { name:"Gaussian Noise", desc:"Additive Gaussian noise on all pixels. Σ user-defined.", active:true, color:"#4a9eff" },
            { name:"Salt & Pepper", desc:"~10% pixel spikes. Removed by 3×3 median pre-filter.", active:true, color:"#f0a500" },
            { name:"Poisson Noise", desc:"Photon shot noise. Simulates low-light sensor behavior.", active:true, color:"#be82ff" },
            { name:"Atmospheric Turbulence", desc:"Scintillation + beam wander from refractive-index structure.", active:true, color:"#00d4aa" },
            { name:"Platform Vibration", desc:"Frame-to-frame jitter from mechanical disturbances.", active:true, color:"#48dcff" },
            { name:"Camera Jerk", desc:"Large random frame displacement. Models hard shocks.", active:true, color:"#5aeb96" },
            { name:"Beacon Fade", desc:"Periodic beacon amplitude reduction. Models path loss.", active:true, color:"#7a8aaa" },
            { name:"Obstacle Occlusion", desc:"Partial path blockage by moving obstacles.", active:true, color:"#ff7700" },
          ].map(d => (
            <div key={d.name} className="p-3 rounded" style={{ background:"#0a0f1c", border:"1px solid #131d30" }}>
              <div className="flex items-center gap-2 mb-1">
                <span className="status-dot dot-locked" style={{ width:5, height:5, background:d.color, boxShadow:"none" }}/>
                <span className="font-medium" style={{ fontSize:11, color:"#dce3f0" }}>{d.name}</span>
              </div>
              <p style={{ fontSize:10, color:"#3d4f6e", lineHeight:1.5 }}>{d.desc}</p>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
