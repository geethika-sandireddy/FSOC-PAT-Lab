import { useState } from 'react'
import SideNav from './components/SideNav'
import Header from './components/Header'
import SimulationPage from './pages/SimulationPage'
import TelemetryPage from './pages/TelemetryPage'
import LinkParametersPage from './pages/LinkParametersPage'
import SystemResponsePage from './pages/SystemResponsePage'
import OpticalSystemPage from './pages/OpticalSystemPage'
import EventLogPage from './pages/EventLogPage'
import { useTelemetry } from './hooks/useTelemetry'

type Page = 'simulation' | 'telemetry' | 'link' | 'system' | 'optical' | 'events'

function App() {
  const [currentPage, setCurrentPage] = useState<Page>('simulation')
  const [isRunning, setIsRunning] = useState(true)
  const telemetry = useTelemetry()

  const pages: Record<Page, React.ComponentType<any>> = {
    simulation: SimulationPage,
    telemetry: TelemetryPage,
    link: LinkParametersPage,
    system: SystemResponsePage,
    optical: OpticalSystemPage,
    events: EventLogPage,
  }

  const CurrentPage = pages[currentPage]

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 flex flex-col">
      <Header isRunning={isRunning} onToggle={() => setIsRunning(!isRunning)} />
      
      <div className="flex flex-1 overflow-hidden gap-1 p-1">
        <SideNav currentPage={currentPage} onPageChange={setCurrentPage} />
        
        <main className="flex-1 overflow-auto bg-black/20 rounded border border-cyan-500/20">
          <CurrentPage telemetry={telemetry} />
        </main>
      </div>
    </div>
  )
}

export default App
