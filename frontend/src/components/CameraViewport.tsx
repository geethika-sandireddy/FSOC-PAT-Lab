import { useRef, useEffect } from "react";
import type { Telemetry } from "@/hooks/useTelemetry";

interface CameraViewportProps {
  telemetry: Telemetry | null;
  connected: boolean;
}

export default function CameraViewport({ telemetry, connected }: CameraViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const cx = W / 2;
    const cy = H / 2;

    // 1. Deep space background
    ctx.fillStyle = "#040814";
    ctx.fillRect(0, 0, W, H);

    // Grid lines
    ctx.strokeStyle = "rgba(16, 32, 60, 0.4)";
    ctx.lineWidth = 0.5;
    for (let x = 40; x < W; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
      ctx.stroke();
    }
    for (let y = 40; y < H; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      ctx.stroke();
    }

    // Concentric range rings around center
    ctx.strokeStyle = "rgba(20, 44, 80, 0.35)";
    [60, 120, 180, 240].forEach((r) => {
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
    });

    if (!connected || !telemetry) {
      // Disconnected / Offline Standby Canvas
      ctx.fillStyle = "rgba(255, 45, 85, 0.08)";
      ctx.fillRect(0, 0, W, H);

      ctx.strokeStyle = "rgba(255, 45, 85, 0.5)";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(cx - 140, cy - 35, 280, 70);

      ctx.fillStyle = "#ff2d55";
      ctx.font = "bold 13px 'DM Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText("● SIMULATOR OFFLINE", cx, cy - 8);
      ctx.fillStyle = "#94a3b8";
      ctx.font = "11px 'DM Mono', monospace";
      ctx.fillText("WAITING FOR BACKEND FEED (ws://localhost:8000/ws)", cx, cy + 14);
      return;
    }

    const st = telemetry.state;
    const isLocked = st === "LOCKED" || st === "DEGRADED_LOCK";
    const stateCol = isLocked ? "#00ff88" : st === "SEARCHING" ? "#ff8c00" : "#00d4ff";

    // 2. Optical Boresight (Camera Center LOS)
    const boresightCol = isLocked ? "#00ff88" : "#3b82f6";
    const br = 20;

    ctx.strokeStyle = boresightCol;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(cx, cy, br, 0, Math.PI * 2);
    ctx.stroke();

    // 4 Sleek tick marks outside circle with open center
    const tStart = br + 4;
    const tEnd = br + 12;
    ctx.beginPath();
    ctx.moveTo(cx + tStart, cy);
    ctx.lineTo(cx + tEnd, cy);
    ctx.moveTo(cx - tStart, cy);
    ctx.lineTo(cx - tEnd, cy);
    ctx.moveTo(cx, cy + tStart);
    ctx.lineTo(cx, cy + tEnd);
    ctx.moveTo(cx, cy - tStart);
    ctx.lineTo(cx, cy - tEnd);
    ctx.stroke();

    // Slew Velocity Vector Arrow
    if (telemetry.slew_spd > 0.03) {
      const spd = telemetry.slew_spd;
      const len = Math.min(65, spd * 24);
      const dx = (telemetry.v_pan / spd) * len;
      const dy = -(telemetry.v_tilt / spd) * len;
      const tipX = cx + dx;
      const tipY = cy + dy;

      ctx.strokeStyle = "#00d4ff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(tipX, tipY);
      ctx.stroke();

      ctx.fillStyle = "#00d4ff";
      ctx.beginPath();
      ctx.arc(tipX, tipY, 3, 0, Math.PI * 2);
      ctx.fill();

      ctx.font = "bold 10px 'DM Mono', monospace";
      ctx.textAlign = "left";
      ctx.fillText(`SLEW ${spd.toFixed(2)}°/s`, tipX + 6, tipY - 4);
    }

    // Boresight label
    ctx.fillStyle = boresightCol;
    ctx.font = "bold 10px 'DM Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText(isLocked ? "BORESIGHT [CO-ALIGNED]" : "OPTICAL AXIS (0,0)", cx, cy + br + 16);

    // 3. Candidate Detections (Blobs)
    if (telemetry.cand_list_uv) {
      ctx.strokeStyle = "rgba(0, 212, 255, 0.4)";
      ctx.lineWidth = 1;
      telemetry.cand_list_uv.forEach(([cu, cv]) => {
        ctx.strokeRect(cu - 6, cv - 6, 12, 12);
      });
    }

    // 4. Distractor Decoys (Rejected by AI)
    if (telemetry.distractors_uv) {
      telemetry.distractors_uv.forEach(([du, dv, freq]) => {
        const dr = 14;
        ctx.strokeStyle = "#ff8c00";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(du, dv - dr);
        ctx.lineTo(du + dr, dv);
        ctx.lineTo(du, dv + dr);
        ctx.lineTo(du - dr, dv);
        ctx.closePath();
        ctx.stroke();

        ctx.fillStyle = "rgba(30, 20, 5, 0.85)";
        ctx.fillRect(du - 55, dv - dr - 20, 110, 16);
        ctx.strokeStyle = "#ff8c00";
        ctx.strokeRect(du - 55, dv - dr - 20, 110, 16);

        ctx.fillStyle = "#ff8c00";
        ctx.font = "bold 9px 'DM Mono', monospace";
        ctx.textAlign = "center";
        ctx.fillText(`[DECOY] ${freq.toFixed(0)} Hz [AI REJECTED]`, du, dv - dr - 8);
      });
    }

    // 5. Target Beacon (Active Optical Carrier)
    if (telemetry.beacon_uv) {
      const [bx, by] = telemetry.beacon_uv;
      const distPx = Math.hypot(bx - cx, by - cy);
      const isAligned = distPx < 10.0;
      const targetCol = isAligned ? "#00ff88" : isLocked ? "#00d4ff" : "#ff8c00";

      // Radial laser core glow
      const grad = ctx.createRadialGradient(bx, by, 2, bx, by, 22);
      grad.addColorStop(0, "rgba(255, 255, 255, 0.95)");
      grad.addColorStop(0.3, isAligned ? "rgba(0, 255, 136, 0.7)" : "rgba(0, 212, 255, 0.7)");
      grad.addColorStop(1, "transparent");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(bx, by, 22, 0, Math.PI * 2);
      ctx.fill();

      // Targeting Corner L-brackets
      const tr = 22;
      const arm = 8;
      ctx.strokeStyle = targetCol;
      ctx.lineWidth = 2;

      // 4 Corners
      [
        [-1, -1],
        [1, -1],
        [-1, 1],
        [1, 1],
      ].forEach(([sx, sy]) => {
        const px = bx + sx * tr;
        const py = by + sy * tr;
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(px - sx * arm, py);
        ctx.moveTo(px, py);
        ctx.lineTo(px, py - sy * arm);
        ctx.stroke();
      });

      // Target Tactical Callout Card
      const cardW = 230;
      const cardH = 50;
      const cardX = bx + tr + 20 + cardW < W ? bx + tr + 15 : bx - tr - cardW - 15;
      const cardY = Math.max(10, Math.min(H - cardH - 10, by - cardH / 2));

      // Leader line
      ctx.strokeStyle = targetCol;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(bx + (cardX > bx ? tr : -tr), by);
      ctx.lineTo(cardX > bx ? cardX : cardX + cardW, cardY + cardH / 2);
      ctx.stroke();

      // Card Body
      ctx.fillStyle = "rgba(4, 18, 14, 0.92)";
      ctx.fillRect(cardX, cardY, cardW, cardH);
      ctx.strokeStyle = targetCol;
      ctx.strokeRect(cardX, cardY, cardW, cardH);

      // Card Accent Bar
      ctx.fillStyle = targetCol;
      ctx.fillRect(cardX, cardY, 3, cardH);

      // Card Texts
      ctx.fillStyle = targetCol;
      ctx.font = "bold 11px 'DM Mono', monospace";
      ctx.textAlign = "left";
      ctx.fillText("[TARGET BEACON] · 15 Hz FSOC", cardX + 10, cardY + 16);

      ctx.fillStyle = "#f8fafc";
      ctx.font = "bold 10.5px 'DM Mono', monospace";
      ctx.fillText(`RESIDUAL: ${distPx.toFixed(1)} px (${(telemetry.pointing_err_deg * 1000).toFixed(1)} mdeg)`, cardX + 10, cardY + 31);

      ctx.fillStyle = isAligned ? "#00ff88" : "#ff8c00";
      ctx.font = "bold 9.5px 'DM Mono', monospace";
      ctx.fillText(`ISRO SPEC: ${isAligned ? "PASS < 10 px" : "ALIGNING..."} · CONF ${Math.round(telemetry.confidence * 100)}%`, cardX + 10, cardY + 44);
    }

    // 6. Viewport Corner Marks
    ctx.strokeStyle = "#475569";
    ctx.lineWidth = 1;
    [
      [15, 15, 1, 1],
      [W - 15, 15, -1, 1],
      [15, H - 15, 1, -1],
      [W - 15, H - 15, -1, -1],
    ].forEach(([x, y, sx, sy]) => {
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + sx * 20, y);
      ctx.moveTo(x, y);
      ctx.lineTo(x, y + sy * 20);
      ctx.stroke();
    });
  }, [telemetry, connected]);

  const st = telemetry?.state ?? "SEARCHING";
  const isLocked = st === "LOCKED" || st === "DEGRADED_LOCK";
  const confPct = telemetry ? Math.round(telemetry.confidence * 100) : 0;

  return (
    <div className="w-full h-full flex flex-col relative bg-[#040814] rounded overflow-hidden border border-[var(--border-dim)]">
      {/* Top Overlay Strip */}
      <div className="absolute top-2 left-3 right-3 flex justify-between items-center z-10 pointer-events-none">
        <div className="flex items-center gap-2 bg-[#060e1a]/90 border border-[var(--border-dim)] px-2.5 py-1 rounded">
          <span className="w-2 h-2 rounded-full" style={{ background: connected ? (isLocked ? "#00ff88" : "#00d4ff") : "#ff2d55" }} />
          <span className="font-mono text-xs font-bold text-slate-200 uppercase tracking-wider">
            {connected ? st : "DISCONNECTED"}
          </span>
          {connected && (
            <span className="font-mono text-xs text-cyan-400 border-l border-slate-700 pl-2">
              CONF: {confPct}%
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 bg-[#060e1a]/90 border border-[var(--border-dim)] px-2.5 py-1 rounded font-mono text-xs text-slate-400">
          <span>FOV: 2.4° × 1.8°</span>
          <span className="text-cyan-400">640×480 @ {telemetry?.fps ?? 30} FPS</span>
        </div>
      </div>

      {/* Main Interactive Canvas */}
      <div className="flex-1 flex items-center justify-center relative overflow-hidden">
        <canvas
          ref={canvasRef}
          width={640}
          height={480}
          className="max-w-full max-h-full object-contain"
          style={{ imageRendering: "pixelated" }}
        />
      </div>

      {/* Bottom Telemetry Bar */}
      <div className="h-8 bg-[#060e1a] border-t border-[var(--border-dim)] flex items-center justify-between px-3 font-mono text-xs z-10">
        <div className="flex items-center gap-3">
          <span className="text-slate-500">BEARING:</span>
          <span className="text-cyan-400 font-bold">
            PAN {telemetry?.gimbal_pan?.toFixed(2) ?? "0.00"}° · TILT {telemetry?.gimbal_tilt?.toFixed(2) ?? "0.00"}°
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-slate-500">ISRO SPEC:</span>
          <span className={telemetry && telemetry.pointing_err_deg * 160 < 10 ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
            {telemetry ? `${(telemetry.pointing_err_deg * 160).toFixed(1)} px / ${(telemetry.pointing_err_deg * 1000).toFixed(1)} mdeg` : "--"}
          </span>
        </div>
      </div>
    </div>
  );
}
