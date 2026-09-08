interface OpticalSystemPageProps {
  telemetry: any
}

const opticalParams = [
  { label: 'Beam Divergence', value: '1.5 mrad', description: 'Half-angle beam spread', min: '0.1 mrad', max: '5 mrad' },
  { label: 'Pointing Error', value: '5 µrad', description: 'Static alignment offset', min: '0 µrad', max: '100 µrad' },
]

const atmosphericParams = [
  { label: 'Atmospheric Visibility', value: '15.0 km', description: 'Meteorological optical range' },
  { label: 'Turbulence Strength (Cn²)', value: '2.00 ×10⁻¹⁵', description: 'Index of refraction structure' },
  { label: 'Temperature', value: '22.6 °C', description: '' },
  { label: 'Humidity', value: '58 %', description: '' },
  { label: 'Wind Speed', value: '4.0 m/s', description: '' },
  { label: 'Wavelength', value: '1550 nm', description: '' },
  { label: 'Distance', value: '5 km', description: '' },
  { label: 'Latency', value: '16.7 µs', description: '' },
]

export default function OpticalSystemPage({ telemetry }: OpticalSystemPageProps) {
  return (
    <div className="h-full w-full p-4 overflow-auto">
      <div className="space-y-4">
        {/* Optical System */}
        <div className="panel p-6">
          <div className="panel-header mb-6">Optical System</div>
          <div className="space-y-6">
            {opticalParams.map((param, idx) => (
              <div key={idx}>
                <div className="flex justify-between mb-3">
                  <div>
                    <div className="metric-label">{param.label}</div>
                    <p className="text-xs text-slate-500 mt-1">{param.description}</p>
                  </div>
                  <span className="text-cyan-400 font-bold text-lg">CTRL {param.value}</span>
                </div>
                <div className="hbar">
                  <div className="hbar-fill" style={{ width: '60%' }}></div>
                </div>
                <div className="flex justify-between text-xs text-slate-500 mt-2">
                  <span>{param.min}</span>
                  <span>{param.max}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Atmospheric Conditions */}
        <div className="panel p-6">
          <div className="panel-header mb-6">Atmospheric Conditions</div>
          <div className="grid grid-cols-2 gap-4">
            {atmosphericParams.map((param, idx) => (
              <div key={idx} className="border-l-2 border-cyan-500/30 pl-3">
                <div className="metric-label mb-1">{param.label}</div>
                <div className="metric-value text-cyan-400 text-lg">{param.value}</div>
                {param.description && <p className="text-xs text-slate-500 mt-1">{param.description}</p>}
              </div>
            ))}
          </div>
        </div>

        {/* Cause & Effect */}
        <div className="panel p-6 border-amber-500/30">
          <div className="panel-header text-amber-400 border-amber-500/20 mb-4">Cause – Effect</div>
          <p className="text-sm text-slate-300 leading-relaxed">
            Adjust TX Power, Distance, or Visibility to see immediate changes in RX Power, BER, and Link Margin. Higher turbulence increases fading. Larger pointing error reduces received flux.
          </p>
        </div>
      </div>
    </div>
  )
}
