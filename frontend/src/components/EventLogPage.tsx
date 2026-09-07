import { useState, useEffect, useRef } from "react";
import type { Telemetry, TrackState, HistoryPoint } from "@/hooks/useTelemetry";

interface Props {
  telemetry: Telemetry | null;
  history: HistoryPoint[];
}

interface Event {
  id: string;
  time: string;
  t: number;
  type: "STATE_CHANGE" | "FALSE_LOCK" | "CANDIDATE" | "ACQUISITION" | "LOSS" | "REACQ" | "INFO";
  from?: TrackState;
  to?: TrackState;
  message: string;
  value?: string;
}

const STATE_COLOR: Record<string, string> = {
  SEARCHING:"#f0a500", TENTATIVE:"#4a9eff", LOCKED:"#00d4aa",
  DEGRADED_LOCK:"#5aeb96", COASTING:"#48dcff", REACQUIRING:"#be82ff", LOST:"#ff3c3c",
};

const EVT_COLOR: Record<string, string> = {
  STATE_CHANGE:"#4a9eff", FALSE_LOCK:"#ff3c3c", CANDIDATE:"#7a8aaa",
  ACQUISITION:"#00d4aa", LOSS:"#ff3c3c", REACQ:"#be82ff", INFO:"#3d4f6e",
};

function fmtTime(t: number): string {
  const d = new Date();
  return d.toISOString().slice(11, 23);
}

export default function EventLogPage({ telemetry, history }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const prevStateRef = useRef<TrackState | null>(null);
  const prevFalseLock = useRef(false);
  const eventCounter = useRef(0);

  // Track state transitions
  useEffect(() => {
    if (!telemetry) return;
    const curState = telemetry.state;
    const prevState = prevStateRef.current;

    if (prevState !== null && prevState !== curState) {
      const id = `evt-${++eventCounter.current}`;
      let type: Event["type"] = "STATE_CHANGE";
      if ((curState === "LOCKED" || curState === "DEGRADED_LOCK") &&
          (prevState === "SEARCHING" || prevState === "TENTATIVE")) type = "ACQUISITION";
      else if (curState === "LOST" || (curState === "SEARCHING" && prevState !== "TENTATIVE")) type = "LOSS";
      else if (curState === "REACQUIRING") type = "REACQ";

      const msgs: Record<string, string> = {
        ACQUISITION: `Beacon acquired — transitioning ${prevState} → ${curState}`,
        LOSS: `Track lost — beacon ${telemetry.beacon_visible ? "visible but misidentified" : "not visible"}`,
        REACQ: `Re-acquisition ladder activated — σ=${telemetry.sigma_px.toFixed(1)} px`,
        STATE_CHANGE: `State transition: ${prevState} → ${curState}`,
      };

      const evt: Event = {
        id, type,
        time: new Date().toISOString().slice(11, 23),
        t: telemetry.t,
        from: prevState,
        to: curState,
        message: msgs[type] ?? msgs.STATE_CHANGE,
        value: `conf=${(telemetry.confidence*100).toFixed(0)}% σ=${telemetry.sigma_px.toFixed(1)}px`,
      };
      setEvents(prev => [evt, ...prev].slice(0, 200));
    }

    if (telemetry.false_lock && !prevFalseLock.current) {
      const evt: Event = {
        id: `fl-${++eventCounter.current}`, type:"FALSE_LOCK",
        time: new Date().toISOString().slice(11, 23), t: telemetry.t,
        message: `False lock detected — est_err=${(telemetry.est_err_deg*160).toFixed(1)} px while ${curState}`,
        value: `point=${(telemetry.pointing_err_deg*160).toFixed(1)}px`,
      };
      setEvents(prev => [evt, ...prev].slice(0, 200));
    }

    prevStateRef.current = curState;
    prevFalseLock.current = telemetry.false_lock;
  }, [telemetry?.state, telemetry?.false_lock]);

  const totals = {
    acquisitions: events.filter(e => e.type === "ACQUISITION").length,
    losses: events.filter(e => e.type === "LOSS").length,
    falseLocks: events.filter(e => e.type === "FALSE_LOCK").length,
    stateChanges: events.filter(e => e.type === "STATE_CHANGE").length,
  };

  const sessionDuration = telemetry ? telemetry.t : 0;
  const lockedFrames = history.filter(h => h.state === "LOCKED" || h.state === "DEGRADED_LOCK").length;
  const retention = history.length > 0 ? lockedFrames / history.length : 0;

  return (
    <div className="p-4 overflow-y-auto h-full flex flex-col gap-3">

      {/* Summary row */}
      <div className="grid gap-3" style={{ gridTemplateColumns:"repeat(6,1fr)" }}>
        {[
          { label:"SESSION TIME", value:`${sessionDuration.toFixed(1)} s`, color:"#7a8aaa" },
          { label:"FRAMES", value:history.length.toString(), color:"#7a8aaa" },
          { label:"ACQUISITIONS", value:totals.acquisitions.toString(), color:"#00d4aa" },
          { label:"TRACK LOSSES", value:totals.losses.toString(), color: totals.losses > 0 ? "#f0a500" : "#00d4aa" },
          { label:"FALSE LOCKS", value:totals.falseLocks.toString(), color: totals.falseLocks > 0 ? "#ff3c3c" : "#00d4aa" },
          { label:"LOCK RETENTION", value:`${(retention*100).toFixed(1)}%`, color: retention >= 0.95 ? "#00d4aa" : "#f0a500" },
        ].map(s => (
          <div key={s.label} className="panel-dark rounded p-3">
            <div className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>{s.label}</div>
            <div className="font-data font-medium" style={{ fontSize:18, color:s.color, lineHeight:1.2 }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* State timeline visual */}
      {history.length > 1 && (
        <div className="panel rounded p-3">
          <div className="font-data mb-2" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em" }}>TRACK STATE TIMELINE</div>
          <div style={{ height:20, display:"flex", borderRadius:2, overflow:"hidden" }}>
            {history.map((h, i) => (
              <div key={i} style={{
                flex:1,
                background: STATE_COLOR[h.state] ?? "#1a2340",
                opacity: h.state === "LOCKED" ? 0.9 : h.state === "DEGRADED_LOCK" ? 0.7 : 0.5,
              }}/>
            ))}
          </div>
          <div className="flex items-center gap-4 mt-2">
            {Object.entries(STATE_COLOR).map(([s, c]) => (
              <div key={s} className="flex items-center gap-1">
                <div style={{ width:8, height:8, background:c, borderRadius:1, opacity:0.8 }}/>
                <span className="font-data" style={{ fontSize:7.5, color:"#5a6a88" }}>{s.replace(/_/g," ")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Event log table */}
      <div className="panel rounded flex-1 overflow-hidden flex flex-col">
        <div className="flex items-center px-4 py-2.5" style={{ borderBottom:"1px solid #131d30", background:"#0a0f1c" }}>
          <span className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em", width:90 }}>TIME</span>
          <span className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em", width:100 }}>TYPE</span>
          <span className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em", flex:1 }}>EVENT</span>
          <span className="font-data" style={{ fontSize:8, color:"#3d4f6e", letterSpacing:"0.08em", width:160 }}>VALUES</span>
        </div>
        <div className="overflow-y-auto flex-1">
          {events.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12" style={{ color:"#2d3f5e" }}>
              <svg width="36" height="36" viewBox="0 0 36 36" fill="none" style={{ opacity:0.3, marginBottom:10 }}>
                <circle cx="18" cy="18" r="15" stroke="#3d4f6e" strokeWidth="2"/>
                <path d="M12 18l4 4 8-8" stroke="#3d4f6e" strokeWidth="2" strokeLinecap="round"/>
              </svg>
              <div className="font-data text-xs" style={{ letterSpacing:"0.08em" }}>NO EVENTS YET</div>
              <div className="text-xs mt-1" style={{ color:"#1a2340" }}>Events appear when state transitions or false locks occur</div>
            </div>
          ) : (
            events.map(evt => {
              const color = EVT_COLOR[evt.type] ?? "#7a8aaa";
              return (
                <div key={evt.id} className="flex items-center px-4 py-2"
                  style={{ borderBottom:"1px solid #0a0f1c" }}>
                  <span className="font-data shrink-0" style={{ fontSize:9, color:"#3d4f6e", width:90 }}>
                    {evt.time} <span style={{ color:"#2d3f5e" }}>+{evt.t.toFixed(1)}s</span>
                  </span>
                  <div className="shrink-0" style={{ width:100 }}>
                    <span className="font-data" style={{ fontSize:9, color, letterSpacing:"0.05em",
                      background:`${color}12`, border:`1px solid ${color}30`,
                      padding:"1px 6px", borderRadius:2 }}>
                      {evt.type.replace(/_/g," ")}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    {evt.from && evt.to && (
                      <span className="font-data mr-2" style={{ fontSize:9 }}>
                        <span style={{ color: STATE_COLOR[evt.from] ?? "#7a8aaa" }}>{evt.from.replace(/_/g," ")}</span>
                        <span style={{ color:"#3d4f6e" }}> → </span>
                        <span style={{ color: STATE_COLOR[evt.to] ?? "#7a8aaa" }}>{evt.to.replace(/_/g," ")}</span>
                      </span>
                    )}
                    <span style={{ fontSize:10, color:"#7a8aaa" }}>{evt.message}</span>
                  </div>
                  {evt.value && (
                    <span className="font-data shrink-0" style={{ fontSize:9, color:"#5a6a88", width:160, textAlign:"right" }}>
                      {evt.value}
                    </span>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
