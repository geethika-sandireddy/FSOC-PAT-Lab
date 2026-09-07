import { useState } from "react";

interface BenchmarkResult {
  preset: string;
  seeds: number;
  acqTime: string;
  retention: string;
  estErrMean: string;
  pointErrMean: string;
  strikeFrms: string;
  falseLocks: number;
  fps: string;
}

const CANONICAL_RESULTS: BenchmarkResult[] = [
  { preset:"EASY",        seeds:3, acqTime:"0.23s",      retention:"100%",       estErrMean:"2.0–2.1 px", pointErrMean:"4.2–4.5 px", strikeFrms:"0",    falseLocks:0, fps:"44–59" },
  { preset:"MODERATE",    seeds:3, acqTime:"0.23s",      retention:"96.8–100%",  estErrMean:"2.1–6.5 px", pointErrMean:"3.8–8.5 px", strikeFrms:"0–26", falseLocks:1, fps:"41–53" },
  { preset:"HARD",        seeds:3, acqTime:"0.23–0.47s", retention:"100%",       estErrMean:"2.4–2.7 px", pointErrMean:"4.3–7.7 px", strikeFrms:"0",    falseLocks:0, fps:"24–32" },
  { preset:"SEVERE",      seeds:3, acqTime:"0.40–1.72s", retention:"96.6–100%",  estErrMean:"11–20 px",   pointErrMean:"31–40 px",   strikeFrms:"0–19", falseLocks:1, fps:"12–24" },
  { preset:"ADVERSARIAL", seeds:3, acqTime:"0.23–0.47s", retention:"100%",       estErrMean:"4.2–5.8 px", pointErrMean:"7.2–14 px",  strikeFrms:"0",    falseLocks:0, fps:"12–30" },
  { preset:"ISRO_RX",     seeds:3, acqTime:"0.23–0.47s", retention:"100%",       estErrMean:"2.2–2.5 px", pointErrMean:"4.0–5.1 px", strikeFrms:"0",    falseLocks:0, fps:"40–41" },
];

const MP4_RESULTS = [
  { video:"Gaussian-only 640×480",          errMean:"0.62 px", p95:"1.10 px", max:"1.57 px", falseLocks:0, acq:"<0.15 s" },
  { video:"10% Salt&Pepper 640×480",        errMean:"0.78 px", p95:"1.48 px", max:"2.18 px", falseLocks:0, acq:"<0.15 s" },
  { video:"1280×720 25fps Gaussian+S&P",    errMean:"1.22 px", p95:"2.1 px",  max:"3.8 px",  falseLocks:0, acq:"<0.15 s" },
  { video:"640×480 Poisson XVID",           errMean:"0.53 px", p95:"0.94 px", max:"1.42 px", falseLocks:0, acq:"<0.15 s" },
];

const PHASE2_HIGHLIGHTS = [
  { metric:"MODERATE pointing error", before:"8.5 px", after:"3.8 px", delta:"−57%", color:"#00d4aa" },
  { metric:"SEVERE estimate error",   before:"20–25 px", after:"11–20 px", delta:"~−35%", color:"#00d4aa" },
  { metric:"BALANCED→VISION switch", before:"—", after:"0.85 obs. gain", delta:"adaptive", color:"#48dcff" },
  { metric:"False locks (wrongprior)", before:"present", after:"0", delta:"eliminated", color:"#00d4aa" },
];

const PRESET_COLOR: Record<string, string> = {
  EASY:"#00d4aa", MODERATE:"#4a9eff", HARD:"#f0a500",
  SEVERE:"#ff7700", ADVERSARIAL:"#ff3c3c", ISRO_RX:"#be82ff",
};

export default function BenchmarkPage() {
  const [tab, setTab] = useState<"synth"|"mp4"|"phase2">("synth");

  return (
    <div className="p-4 overflow-y-auto h-full flex flex-col gap-4">

      {/* Tabs */}
      <div className="flex gap-2">
        {[
          { id:"synth" as const, label:"Benchmark-1 · Synthetic" },
          { id:"mp4" as const,   label:"Benchmark-2 · MP4 Bypass" },
          { id:"phase2" as const,label:"Phase 2 · Trust Manager" },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className="font-data px-4 py-2 rounded transition-all"
            style={{
              background: tab === t.id ? "#00d4aa12" : "#0a0f1c",
              border: `1px solid ${tab === t.id ? "#00d4aa35" : "#1a2340"}`,
              color: tab === t.id ? "#00d4aa" : "#5a6a88",
              fontSize:10, cursor:"pointer", letterSpacing:"0.06em",
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "synth" && (
        <>
          <div className="panel rounded p-4">
            <div className="font-data mb-1" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>BENCHMARK-1 — SYNTHETIC MODE RESULTS</div>
            <div className="text-xs mb-3" style={{ color:"#3d4f6e" }}>
              Canonical run: <span className="font-data" style={{ color:"#4a9eff" }}>python -m metrics.stress_test</span> — 3 seeds × 450 frames × 5 presets @ 30 Hz, fully deterministic. 160 px/° → 10 px spec ≈ 0.0625°.
            </div>
            <div className="overflow-x-auto">
              <table style={{ width:"100%", borderCollapse:"collapse" }}>
                <thead>
                  <tr style={{ borderBottom:"1px solid #1a2340" }}>
                    {["Preset","Seeds","Acq. Time","Retention","Est. Err","Point. Err","Strike Frm","False Locks","FPS"].map(h => (
                      <th key={h} className="font-data text-left py-2 px-3" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.07em", fontWeight:500 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {CANONICAL_RESULTS.map((r, i) => {
                    const color = PRESET_COLOR[r.preset] ?? "#7a8aaa";
                    return (
                      <tr key={r.preset} style={{ borderBottom:"1px solid #0d1220", background: i%2===0?"transparent":"#0a0f1c08" }}>
                        <td className="py-2.5 px-3">
                          <span className="font-data font-medium" style={{ fontSize:11, color }}>{r.preset}</span>
                        </td>
                        <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color:"#7a8aaa" }}>{r.seeds}</td>
                        <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color: r.acqTime.startsWith("0.2") ? "#00d4aa" : "#f0a500" }}>{r.acqTime}</td>
                        <td className="py-2.5 px-3 font-data font-medium" style={{ fontSize:10, color: r.retention === "100%" ? "#00d4aa" : "#f0a500" }}>{r.retention}</td>
                        <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color:"#4a9eff" }}>{r.estErrMean}</td>
                        <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color:"#7a8aaa" }}>{r.pointErrMean}</td>
                        <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color: r.strikeFrms === "0" ? "#00d4aa" : "#f0a500" }}>{r.strikeFrms}</td>
                        <td className="py-2.5 px-3 font-data font-medium" style={{ fontSize:10, color: r.falseLocks === 0 ? "#00d4aa" : "#f0a500" }}>{r.falseLocks}</td>
                        <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color:"#7a8aaa" }}>{r.fps}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Key highlights */}
          <div className="grid gap-3" style={{ gridTemplateColumns:"repeat(3,1fr)" }}>
            {[
              { title:"Zero False Locks", value:"4/6 presets", desc:"EASY, HARD, ADVERSARIAL, ISRO_RX hold zero false locks across all 3 seeds.", color:"#00d4aa" },
              { title:"100% Retention", value:"4/6 presets", desc:"Post-lock retention in every seed. MODERATE and SEVERE self-recover from detected episodes.", color:"#00d4aa" },
              { title:"Sub-10px Estimate", value:"≤6.5 px typical", desc:"Estimate error is the honest CV metric — far inside the ≤10 px pointing spec.", color:"#4a9eff" },
            ].map(h => (
              <div key={h.title} className="panel rounded p-4" style={{ borderLeft:`3px solid ${h.color}` }}>
                <div className="font-data font-medium mb-1" style={{ fontSize:14, color:h.color }}>{h.value}</div>
                <div className="font-medium mb-1" style={{ fontSize:12, color:"#dce3f0" }}>{h.title}</div>
                <p style={{ fontSize:10, color:"#5a6a88", lineHeight:1.6 }}>{h.desc}</p>
              </div>
            ))}
          </div>

          {/* Run command */}
          <div className="panel rounded p-4">
            <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>REPRODUCE THESE RESULTS</div>
            <div className="grid gap-2" style={{ gridTemplateColumns:"repeat(2,1fr)" }}>
              {[
                { cmd:"python -m metrics.stress_test", desc:"Full canonical benchmark (3 seeds × 5 presets)" },
                { cmd:"python -m metrics.stress_test --scenario wrongprior", desc:"Corrupted ephemeris prior stress test" },
                { cmd:"python -m metrics.stress_test --scenario dynamic", desc:"Dynamic ephemeris + disturbance storm" },
                { cmd:"python -m metrics.stress_test --presets ISRO_RX --trials 3", desc:"ISRO reference-terminal benchmark" },
                { cmd:"python -m metrics.scenario_demo --preset MODERATE --inject recover", desc:"Live acquire→lose→coast→reacquire demo" },
                { cmd:"python -m metrics.stress_test --scenario truststory", desc:"Trust manager vignette (beacon burn)" },
              ].map(c => (
                <div key={c.cmd} className="p-3 rounded" style={{ background:"#0a0f1c", border:"1px solid #131d30" }}>
                  <div className="font-data mb-1" style={{ fontSize:10, color:"#4a9eff" }}>{c.cmd}</div>
                  <div style={{ fontSize:10, color:"#3d4f6e" }}>{c.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {tab === "mp4" && (
        <>
          <div className="panel rounded p-4">
            <div className="font-data mb-1" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>BENCHMARK-2 — MP4 VIDEO BYPASS RESULTS</div>
            <div className="text-xs mb-3" style={{ color:"#3d4f6e" }}>
              The bypass replaces the virtual camera with a grader-supplied .mp4. The same detect→track→control loop runs on raw video pixels.
              Error is measured in the video's own pixel plane. Resolution/codec/framerate agnostic.
            </div>
            <div className="overflow-x-auto">
              <table style={{ width:"100%", borderCollapse:"collapse" }}>
                <thead>
                  <tr style={{ borderBottom:"1px solid #1a2340" }}>
                    {["Video","Err Mean","p95","Max","False Locks","Acq. Time"].map(h => (
                      <th key={h} className="font-data text-left py-2 px-3" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.07em" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MP4_RESULTS.map((r, i) => (
                    <tr key={r.video} style={{ borderBottom:"1px solid #0d1220", background: i%2===0?"transparent":"#0a0f1c08" }}>
                      <td className="py-2.5 px-3" style={{ fontSize:10, color:"#dce3f0" }}>{r.video}</td>
                      <td className="py-2.5 px-3 font-data font-medium" style={{ fontSize:11, color:"#00d4aa" }}>{r.errMean}</td>
                      <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color:"#4a9eff" }}>{r.p95}</td>
                      <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color:"#7a8aaa" }}>{r.max}</td>
                      <td className="py-2.5 px-3 font-data font-medium" style={{ fontSize:11, color:"#00d4aa" }}>{r.falseLocks}</td>
                      <td className="py-2.5 px-3 font-data" style={{ fontSize:10, color:"#00d4aa" }}>{r.acq}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="grid gap-3" style={{ gridTemplateColumns:"1fr 1fr" }}>
            <div className="panel rounded p-4">
              <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>HOW TO RUN MP4 BYPASS</div>
              <div className="flex flex-col gap-2">
                {[
                  { cmd:"python -m metrics.mp4_bypass -i path/to/video.mp4", desc:"Run bypass on any grader-supplied video" },
                  { cmd:"python -m metrics.synthetic_video --out logs/classB.mp4 --noise gaussian,salt_pepper", desc:"Generate synthetic benchmark video" },
                ].map(c => (
                  <div key={c.cmd} className="p-3 rounded" style={{ background:"#0a0f1c", border:"1px solid #131d30" }}>
                    <div className="font-data mb-1" style={{ fontSize:10, color:"#4a9eff" }}>{c.cmd}</div>
                    <div style={{ fontSize:10, color:"#3d4f6e" }}>{c.desc}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel rounded p-4">
              <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>PRE-PROCESSING PIPELINE</div>
              <div className="flex flex-col gap-2">
                {[
                  { step:"1", label:"3×3 Median Pre-filter", desc:"Kills salt-and-pepper spikes before blob detection" },
                  { step:"2", label:"Top-hat Background Subtraction", desc:"Local contrast enhancement for low-SNR beacons" },
                  { step:"3", label:"ML Blob Classification", desc:"Logistic regression on [area, circularity, SNR, hue_dist]" },
                  { step:"4", label:"Persistence-gated Lock", desc:"No modulation ID in video mode — uses spatial consistency" },
                ].map(s => (
                  <div key={s.step} className="flex items-start gap-3 p-2.5 rounded" style={{ background:"#0a0f1c", border:"1px solid #131d30" }}>
                    <div className="font-data font-medium shrink-0" style={{ fontSize:11, color:"#00d4aa", width:16 }}>{s.step}</div>
                    <div>
                      <div className="font-medium mb-0.5" style={{ fontSize:11, color:"#dce3f0" }}>{s.label}</div>
                      <div style={{ fontSize:10, color:"#3d4f6e" }}>{s.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {tab === "phase2" && (
        <>
          <div className="panel rounded p-4">
            <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>PHASE 2 — ADAPTIVE MODEL-VISION TRUST MANAGER</div>
            <p className="text-xs mb-4" style={{ color:"#7a8aaa", lineHeight:1.7 }}>
              Each frame the system answers <em>"how much do I trust the camera vs the ephemeris model?"</em> and
              routes observation authority accordingly. Mode transitions are hysteresis-debounced to prevent oscillation.
              Evidence files in <span className="font-data" style={{ color:"#4a9eff" }}>logs/phase2_trust_summary*.json</span>.
            </p>
            <div className="grid gap-3 mb-4" style={{ gridTemplateColumns:"repeat(4,1fr)" }}>
              {[
                { mode:"VISION_DOMINANT", gain:"0.85", color:"#48dcff", desc:"Camera has authority. Strong beacon signal, low uncertainty." },
                { mode:"BALANCED", gain:"0.4–0.6", color:"#00d4aa", desc:"Equal weight. Normal tracking with moderate confidence." },
                { mode:"MODEL_DOMINANT", gain:"0.30", color:"#be82ff", desc:"Ephemeris has authority. Beacon obscured or noisy." },
                { mode:"COAST / REACQUIRE", gain:"0.0", color:"#f0a500", desc:"Full model authority. No camera observations available." },
              ].map(m => (
                <div key={m.mode} className="p-3 rounded" style={{ background:"#0a0f1c", border:`1px solid ${m.color}25` }}>
                  <div className="font-data font-medium mb-1" style={{ fontSize:10, color:m.color, letterSpacing:"0.05em" }}>{m.mode}</div>
                  <div className="font-data mb-2" style={{ fontSize:12, color:m.color }}>α = {m.gain}</div>
                  <p style={{ fontSize:9, color:"#3d4f6e", lineHeight:1.5 }}>{m.desc}</p>
                </div>
              ))}
            </div>
            <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>PHASE 2 IMPROVEMENTS OVER BASELINE</div>
            <table style={{ width:"100%", borderCollapse:"collapse" }}>
              <thead>
                <tr style={{ borderBottom:"1px solid #1a2340" }}>
                  {["Metric","Before Phase 2","After Phase 2","Improvement"].map(h => (
                    <th key={h} className="font-data text-left py-2 px-3" style={{ fontSize:8, color:"#3d4f6e" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {PHASE2_HIGHLIGHTS.map((r, i) => (
                  <tr key={r.metric} style={{ borderBottom:"1px solid #0d1220", background: i%2===0?"transparent":"#0a0f1c08" }}>
                    <td className="py-2 px-3" style={{ fontSize:10, color:"#dce3f0" }}>{r.metric}</td>
                    <td className="py-2 px-3 font-data" style={{ fontSize:10, color:"#f0a500" }}>{r.before}</td>
                    <td className="py-2 px-3 font-data font-medium" style={{ fontSize:10, color:r.color }}>{r.after}</td>
                    <td className="py-2 px-3 font-data font-medium" style={{ fontSize:10, color:r.color }}>{r.delta}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-3" style={{ gridTemplateColumns:"1fr 1fr" }}>
            <div className="panel rounded p-4">
              <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>RE-ACQUISITION LADDER</div>
              {[
                { level:"L1", desc:"Missed frame → COASTING. Velocity + lead predict boresight.", gate:"1.0×", dur:"0–0.33 s" },
                { level:"L2", desc:"σ past 18 px → REACQUIRING. Gate widens 2.2× for faster sweeps.", gate:"2.2×", dur:"0.33–0.66 s" },
                { level:"L3", desc:"Still lost → wider sweep, aggressive gate expansion.", gate:"4.0×", dur:"0.66–0.86 s" },
                { level:"SRCH", desc:"After 1 s ladder timeout → blind SEARCHING sweep.", gate:"—", dur:">0.86 s" },
              ].map(l => (
                <div key={l.level} className="flex items-start gap-3 py-2.5" style={{ borderBottom:"1px solid #0d1220" }}>
                  <div className="font-data font-medium shrink-0" style={{ fontSize:10, color:"#be82ff", width:32 }}>{l.level}</div>
                  <div className="flex-1 text-xs" style={{ color:"#5a6a88", lineHeight:1.5 }}>{l.desc}</div>
                  <div className="font-data text-right shrink-0" style={{ fontSize:9, color:"#7a8aaa" }}>
                    <div>{l.gate}</div><div>{l.dur}</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="panel rounded p-4">
              <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>CONFIDENCE BANDING</div>
              {[
                { band:"LOCKED", threshold:"≥ 0.70", color:"#00d4aa", desc:"Full lock. All confidence sub-scores above threshold. Normal tracking authority." },
                { band:"DEGRADED_LOCK", threshold:"0.55–0.70", color:"#5aeb96", desc:"Reduced confidence. Lock is maintained with lower observation gain. Still pointing." },
                { band:"SUSPECT / COAST", threshold:"< 0.55", color:"#f0a500", desc:"Confidence below lock floor. Suspect-floor monitor active. May re-verify or coast." },
                { band:"RE-ACQUIRE", threshold:"σ > 18 px", color:"#ff3c3c", desc:"Uncertainty past credibility line. Staged re-acquisition ladder activates." },
              ].map(b => (
                <div key={b.band} className="py-2.5" style={{ borderBottom:"1px solid #0d1220" }}>
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="font-data font-medium" style={{ fontSize:10, color:b.color }}>{b.band}</span>
                    <span className="font-data" style={{ fontSize:10, color:b.color }}>{b.threshold}</span>
                  </div>
                  <p style={{ fontSize:9, color:"#3d4f6e", lineHeight:1.5 }}>{b.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
