import { useState } from "react";
import { useTelemetry } from "@/hooks/useTelemetry";
import CommandBar from "@/components/CommandBar";
import SideNav from "@/components/SideNav";
import OverviewPage from "@/components/OverviewPage";
import TelemetryPage from "@/components/TelemetryPage";
import SceneConfigPage from "@/components/SceneConfigPage";
import BenchmarkPage from "@/components/BenchmarkPage";
import EventLogPage from "@/components/EventLogPage";

type Page = "overview" | "telemetry" | "scene" | "benchmark" | "events";

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const {
    telemetry, history, connected, running, preset, demoMode,
    setPreset, resetSim, toggleRunning, setDisturbance,
  } = useTelemetry();

  const eventCount = 0; // EventLogPage tracks its own events internally

  return (
    <div className="flex flex-col" style={{ height:"100vh", width:"100vw", overflow:"hidden", background:"#060a12" }}>
      <CommandBar
        state={telemetry?.state ?? null}
        confidence={telemetry?.confidence ?? 0}
        preset={preset}
        connected={connected}
        demoMode={demoMode}
        running={running}
        falselock={telemetry?.false_lock ?? false}
        onToggleRunning={toggleRunning}
        onReset={resetSim}
      />
      <div className="flex flex-1 min-h-0">
        <SideNav current={page} onChange={setPage} alertCount={eventCount} />
        <main className="flex-1 min-w-0 overflow-hidden">
          {page === "overview"   && <OverviewPage telemetry={telemetry} history={history} />}
          {page === "telemetry"  && <TelemetryPage telemetry={telemetry} history={history} />}
          {page === "scene"      && <SceneConfigPage currentPreset={preset} onSetPreset={setPreset} onSetDisturbance={setDisturbance} telemetry={telemetry} />}
          {page === "benchmark"  && <BenchmarkPage />}
          {page === "events"     && <EventLogPage telemetry={telemetry} history={history} />}
        </main>
      </div>
    </div>
  );
}
