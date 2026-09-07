import { useMemo } from "react";
import type { Telemetry, HistoryPoint } from "@/hooks/useTelemetry";

interface Props {
  telemetry: Telemetry;
  history: HistoryPoint[];
  size?: number;
}

const STATE_COLOR: Record<string, string> = {
  SEARCHING: "#f0a500",
  TENTATIVE: "#4a9eff",
  LOCKED: "#00d4aa",
  DEGRADED_LOCK: "#5aeb96",
  COASTING: "#48dcff",
  REACQUIRING: "#be82ff",
  LOST: "#ff3c3c",
};

export default function AzElPlot({ telemetry, history, size = 260 }: Props) {
  const cx = size / 2, cy = size / 2;
  const maxDeg = 3.5; // display ±3.5° on each axis

  function toXY(az: number, el: number) {
    return {
      x: cx + (az / maxDeg) * (size / 2 - 18),
      y: cy - (el / maxDeg) * (size / 2 - 18),
    };
  }

  const truth = toXY(telemetry.truth_az, telemetry.truth_el);
  const est = toXY(telemetry.est_az, telemetry.est_el);
  const stateColor = STATE_COLOR[telemetry.state] ?? "#7a8aaa";

  // FOV rectangle
  const fovHalf = { az: 2.0, el: 1.5 };
  const fovTL = toXY(-fovHalf.az, fovHalf.el);
  const fovBR = toXY(fovHalf.az, -fovHalf.el);

  // Trail (last 60 history points)
  const trail = useMemo(() => {
    const recent = history.slice(-60);
    return recent
      .map(h => {
        // approximate trail from pointing error — use truth direction
        return null; // we only have error magnitudes, not az/el per-history point
      })
      .filter(Boolean);
  }, [history]);

  // Grid rings at 1°, 2°, 3°
  const rings = [1, 2, 3];

  const fovW = fovBR.x - fovTL.x;
  const fovH = fovBR.y - fovTL.y;

  return (
    <div className="flex flex-col items-center">
      <div className="font-data mb-1.5" style={{ fontSize:9, color:"#3d4f6e", letterSpacing:"0.08em" }}>
        AZ/EL SKY PLOT · ±{maxDeg}°
      </div>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <radialGradient id="bgGrad" cx="50%" cy="50%">
            <stop offset="0%" stopColor="#0d1628" stopOpacity="1"/>
            <stop offset="100%" stopColor="#070b14" stopOpacity="1"/>
          </radialGradient>
          <clipPath id="plotClip">
            <circle cx={cx} cy={cy} r={size/2-4}/>
          </clipPath>
          <filter id="glowTruth">
            <feGaussianBlur stdDeviation="2.5" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="glowEst">
            <feGaussianBlur stdDeviation="1.5" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>

        {/* Background */}
        <circle cx={cx} cy={cy} r={size/2-2} fill="url(#bgGrad)" stroke="#1a2340" strokeWidth="1"/>

        <g clipPath="url(#plotClip)">
          {/* Grid rings */}
          {rings.map(r => {
            const pr = (r / maxDeg) * (size/2 - 18);
            return (
              <g key={r}>
                <circle cx={cx} cy={cy} r={pr} stroke="#1a2340" strokeWidth="0.8" fill="none"/>
                <text x={cx + pr + 2} y={cy - 2} fill="#2d3f5e" fontSize="7" fontFamily="DM Mono">{r}°</text>
              </g>
            );
          })}

          {/* Crosshairs */}
          <line x1={cx} y1={8} x2={cx} y2={size-8} stroke="#1a2340" strokeWidth="0.6"/>
          <line x1={8} y1={cy} x2={size-8} y2={cy} stroke="#1a2340" strokeWidth="0.6"/>

          {/* FOV rectangle */}
          <rect x={fovTL.x} y={fovTL.y} width={fovW} height={fovH}
            fill={telemetry.in_fov ? "#4a9eff08" : "#ff3c3c08"}
            stroke={telemetry.in_fov ? "#4a9eff40" : "#ff3c3c40"}
            strokeWidth="0.8" strokeDasharray="3 3"/>
          <text x={fovTL.x + 3} y={fovTL.y + 9} fill="#4a9eff" fontSize="6" fontFamily="DM Mono" fillOpacity="0.7">FOV 4°×3°</text>

          {/* Gimbal boresight (center cross) */}
          <line x1={cx-6} y1={cy} x2={cx+6} y2={cy} stroke="#00d4aa" strokeWidth="1" strokeOpacity="0.5"/>
          <line x1={cx} y1={cy-6} x2={cx} y2={cy+6} stroke="#00d4aa" strokeWidth="1" strokeOpacity="0.5"/>
          <circle cx={cx} cy={cy} r="2.5" fill="none" stroke="#00d4aa" strokeWidth="0.8" strokeOpacity="0.4"/>

          {/* Pointing error vector */}
          {(telemetry.state === "LOCKED" || telemetry.state === "DEGRADED_LOCK") && (
            <line x1={est.x} y1={est.y} x2={truth.x} y2={truth.y}
              stroke="#ff3c3c" strokeWidth="0.6" strokeOpacity="0.5" strokeDasharray="2 2"/>
          )}

          {/* Truth beacon */}
          <g filter="url(#glowTruth)">
            <circle cx={truth.x} cy={truth.y} r="5"
              fill={stateColor} fillOpacity="0.15"
              stroke={stateColor} strokeWidth="1"/>
            <circle cx={truth.x} cy={truth.y} r="2" fill={stateColor}/>
          </g>

          {/* Estimate */}
          {(telemetry.state !== "SEARCHING") && (
            <g filter="url(#glowEst)">
              <circle cx={est.x} cy={est.y} r="3.5"
                fill="none" stroke={stateColor} strokeWidth="1" strokeOpacity="0.7" strokeDasharray="3 2"/>
              <circle cx={est.x} cy={est.y} r="1.2" fill={stateColor} fillOpacity="0.8"/>
            </g>
          )}

          {/* Uncertainty sigma circle */}
          {telemetry.sigma_px > 0 && (telemetry.state === "LOCKED" || telemetry.state === "DEGRADED_LOCK") && (
            <circle cx={est.x} cy={est.y}
              r={Math.min(telemetry.sigma_px * 0.6, 30)}
              fill="none" stroke="#4a9eff" strokeWidth="0.6" strokeOpacity="0.3" strokeDasharray="2 3"/>
          )}
        </g>

        {/* Labels */}
        <text x={cx} y={12} fill="#2d3f5e" fontSize="7" textAnchor="middle" fontFamily="DM Mono">EL+</text>
        <text x={cx} y={size-4} fill="#2d3f5e" fontSize="7" textAnchor="middle" fontFamily="DM Mono">EL−</text>
        <text x={8} y={cy+3} fill="#2d3f5e" fontSize="7" textAnchor="middle" fontFamily="DM Mono">AZ−</text>
        <text x={size-6} y={cy+3} fill="#2d3f5e" fontSize="7" textAnchor="end" fontFamily="DM Mono">AZ+</text>
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-2">
        <div className="flex items-center gap-1.5">
          <div style={{ width:8, height:8, borderRadius:"50%", background: stateColor }}/>
          <span className="font-data" style={{ fontSize:8, color:"#7a8aaa" }}>TRUTH</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div style={{ width:8, height:8, borderRadius:"50%", border:`1px dashed ${stateColor}`, background:"transparent" }}/>
          <span className="font-data" style={{ fontSize:8, color:"#7a8aaa" }}>ESTIMATE</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div style={{ width:8, height:8, borderRadius:"50%", border:"1px dashed #4a9eff", background:"transparent" }}/>
          <span className="font-data" style={{ fontSize:8, color:"#7a8aaa" }}>σ UNCERT.</span>
        </div>
      </div>
    </div>
  );
}
