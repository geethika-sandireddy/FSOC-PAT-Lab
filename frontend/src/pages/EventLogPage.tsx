interface EventLogPageProps {
  telemetry: any
}

const mockEvents = [
  { time: '0.23s', level: 'INFO', event: 'BEACON ACQUIRED', subsystem: 'Detection' },
  { time: '0.24s', level: 'INFO', event: 'State transition: SEARCHING → TENTATIVE', subsystem: 'Tracking' },
  { time: '0.45s', level: 'INFO', event: 'State transition: TENTATIVE → LOCKED', subsystem: 'Tracking' },
  { time: '5.12s', level: 'WARNING', event: 'Atmospheric degradation detected', subsystem: 'Disturbances' },
  { time: '15.34s', level: 'INFO', event: 'Pointing error nominal', subsystem: 'Gimbal' },
  { time: '32.67s', level: 'INFO', event: 'Lock confidence > 95%', subsystem: 'Trust' },
]

const subsystemHealth = [
  { name: 'Transmitter', status: 'NOMINAL', power: '30.0 dBm' },
  { name: 'Receiver', status: 'NOMINAL', power: '-11.4 dBm' },
  { name: 'Optical Link', status: 'NOMINAL', margin: '38.6 dB' },
  { name: 'Beam Alignment', status: 'OPTIMAL', error: '1.5 µrad' },
  { name: 'Tracking Loop', status: 'LOCKED', confidence: '97 %' },
  { name: 'Lock Detector', status: 'CLEAR', signal: 'OK' },
]

export default function EventLogPage({ telemetry }: EventLogPageProps) {
  return (
    <div className="h-full w-full p-4 overflow-auto">
      <div className="grid grid-cols-2 gap-4">
        {/* Event Timeline */}
        <div className="panel p-6">
          <div className="panel-header mb-4">Event Timeline</div>
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {mockEvents.map((event, idx) => (
              <div key={idx} className="flex gap-3 text-xs pb-2 border-b border-slate-700/50">
                <div className="text-cyan-400 font-mono min-w-fit">{event.time}</div>
                <div className="flex-1">
                  <div className={`font-bold ${
                    event.level === 'INFO' ? 'text-green-400' :
                    event.level === 'WARNING' ? 'text-amber-400' :
                    'text-red-400'
                  }`}>
                    {event.event}
                  </div>
                  <div className="text-slate-500 text-xs mt-1">{event.subsystem}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Subsystem Health */}
        <div className="panel p-6">
          <div className="panel-header mb-4">Subsystem Health</div>
          <div className="space-y-3">
            {subsystemHealth.map((subsystem, idx) => (
              <div key={idx} className="border-l-2 border-green-500/50 pl-3 pb-2 border-b border-slate-700/50">
                <div className="flex justify-between items-center mb-1">
                  <span className="metric-label">{subsystem.name}</span>
                  <span className="text-green-400 text-xs font-bold">● {subsystem.status}</span>
                </div>
                <div className="text-xs text-slate-400">
                  {Object.entries(subsystem)
                    .filter(([k]) => k !== 'name' && k !== 'status')
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(' · ')}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
