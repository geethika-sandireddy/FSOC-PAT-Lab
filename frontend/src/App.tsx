import { useState } from "react";
import { useTelemetry } from "@/hooks/useTelemetry";
import MissionHeader from "@/components/MissionHeader";
import TopNav from "@/components/TopNav";
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

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"100vh", width:"100vw", overflow:"hidden" }}>
      <MissionHeader
        telemetry={telemetry}
        connected={connected}
        demoMode={demoMode}
        running={running}
        onToggleRunning={toggleRunning}
        onReset={resetSim}
      />
      <TopNav current={page} onChange={setPage} />
      <main style={{ flex:1, minHeight:0, overflow:"hidden" }}>
        {page === "overview"   && <OverviewPage  telemetry={telemetry}  history={history} />}
        {page === "telemetry"  && <TelemetryPage telemetry={telemetry}  history={history} />}
        {page === "scene"      && <SceneConfigPage currentPreset={preset} onSetPreset={setPreset} onSetDisturbance={setDisturbance} telemetry={telemetry} />}
        {page === "benchmark"  && <BenchmarkPage />}
        {page === "events"     && <EventLogPage  telemetry={telemetry}  history={history} />}
      </main>
    </div>
  );
}
