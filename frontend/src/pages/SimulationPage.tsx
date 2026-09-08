import { useState } from 'react'
import CameraViewport from '../components/CameraViewport'

interface SimulationPageProps {
  telemetry: any
}

export default function SimulationPage({ telemetry }: SimulationPageProps) {
  const [frameData] = useState(null)

  return (
    <div className="h-full w-full p-4 flex flex-col gap-4">
      <div className="flex-1 rounded glow-border overflow-hidden bg-black/50">
        <CameraViewport frameData={frameData} />
      </div>
      
      <div className="grid grid-cols-6 gap-3 h-24">
        <div className="panel p-3 relative">
          <div className="accent-stripe"></div>
          <div className="metric-label pl-4">State</div>
          <div className="metric-value text-green-400 mt-1 pl-4">LOCKED</div>
        </div>
        <div className="panel p-3 relative">
          <div className="accent-stripe"></div>
          <div className="metric-label pl-4">Point Error</div>
          <div className="metric-value text-cyan-400 mt-1 pl-4">1.50 µrad</div>
        </div>
        <div className="panel p-3 relative">
          <div className="accent-stripe"></div>
          <div className="metric-label pl-4">Confidence</div>
          <div className="metric-value text-cyan-400 mt-1 pl-4">95.0 %</div>
        </div>
        <div className="panel p-3 relative">
          <div className="accent-stripe"></div>
          <div className="metric-label pl-4">Elapsed</div>
          <div className="metric-value text-cyan-400 mt-1 pl-4">45.2 s</div>
        </div>
        <div className="panel p-3 relative">
          <div className="accent-stripe"></div>
          <div className="metric-label pl-4">FPS</div>
          <div className="metric-value text-green-400 mt-1 pl-4">30.0</div>
        </div>
        <div className="panel p-3 relative">
          <div className="accent-stripe"></div>
          <div className="metric-label pl-4">Acq Time</div>
          <div className="metric-value text-cyan-400 mt-1 pl-4">0.23 s</div>
        </div>
      </div>
    </div>
  )
}
