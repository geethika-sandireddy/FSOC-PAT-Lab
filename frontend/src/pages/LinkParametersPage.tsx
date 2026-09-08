import { useState } from 'react'

interface LinkParametersPageProps {
  telemetry: any
}

export default function LinkParametersPage({ telemetry }: LinkParametersPageProps) {
  const [params, setParams] = useState({
    txPower: 30,
    wavelength: 1550,
    linkDistance: 5,
    dataRate: 10,
    rxSensitivity: -50,
  })

  const handleSliderChange = (key: string, value: number) => {
    setParams({ ...params, [key]: value })
  }

  return (
    <div className="h-full w-full p-4 overflow-auto">
      <div className="max-w-2xl space-y-4">
        <div className="panel p-6">
          <div className="panel-header mb-6">Transmitter & Link Parameters</div>

          {/* TX Optical Power */}
          <div className="mb-8">
            <div className="flex justify-between mb-3">
              <div>
                <label className="metric-label block">TX Optical Power</label>
                <p className="text-xs text-slate-500 mt-1">Laser output power</p>
              </div>
              <span className="text-cyan-400 font-bold text-lg">CTRL {params.txPower.toFixed(1)} dBm</span>
            </div>
            <div className="hbar">
              <div
                className="hbar-fill"
                style={{ width: `${(params.txPower / 40) * 100}%` }}
              ></div>
            </div>
            <input
              type="range"
              min="0"
              max="40"
              value={params.txPower}
              onChange={(e) => handleSliderChange('txPower', parseFloat(e.target.value))}
              className="w-full mt-3 cursor-pointer"
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>0 dBm</span>
              <span>40 dBm</span>
            </div>
          </div>

          {/* Wavelength */}
          <div className="mb-8">
            <div className="flex justify-between mb-3">
              <div>
                <label className="metric-label block">Wavelength</label>
                <p className="text-xs text-slate-500 mt-1">Operating wavelength</p>
              </div>
              <span className="text-cyan-400 font-bold text-lg">CTRL {params.wavelength} nm</span>
            </div>
            <div className="hbar">
              <div
                className="hbar-fill"
                style={{ width: `${((params.wavelength - 890) / (1690 - 890)) * 100}%` }}
              ></div>
            </div>
            <input
              type="range"
              min="890"
              max="1690"
              value={params.wavelength}
              onChange={(e) => handleSliderChange('wavelength', parseFloat(e.target.value))}
              className="w-full mt-3 cursor-pointer"
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>890 nm</span>
              <span>1690 nm</span>
            </div>
          </div>

          {/* Link Distance */}
          <div className="mb-8">
            <div className="flex justify-between mb-3">
              <div>
                <label className="metric-label block">Link Distance</label>
                <p className="text-xs text-slate-500 mt-1">Transmitter-receiver separation</p>
              </div>
              <span className="text-cyan-400 font-bold text-lg">CTRL {params.linkDistance.toFixed(1)} km</span>
            </div>
            <div className="hbar">
              <div
                className="hbar-fill"
                style={{ width: `${(params.linkDistance / 50) * 100}%` }}
              ></div>
            </div>
            <input
              type="range"
              min="0.1"
              max="50"
              step="0.1"
              value={params.linkDistance}
              onChange={(e) => handleSliderChange('linkDistance', parseFloat(e.target.value))}
              className="w-full mt-3 cursor-pointer"
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>0.1 km</span>
              <span>50 km</span>
            </div>
          </div>

          {/* Data Rate */}
          <div className="mb-8">
            <div className="flex justify-between mb-3">
              <div>
                <label className="metric-label block">Data Rate</label>
                <p className="text-xs text-slate-500 mt-1">Target channel throughput</p>
              </div>
              <span className="text-cyan-400 font-bold text-lg">CTRL {params.dataRate.toFixed(1)} Gbps</span>
            </div>
            <div className="hbar">
              <div
                className="hbar-fill"
                style={{ width: `${(params.dataRate / 100) * 100}%` }}
              ></div>
            </div>
            <input
              type="range"
              min="0.1"
              max="100"
              step="0.1"
              value={params.dataRate}
              onChange={(e) => handleSliderChange('dataRate', parseFloat(e.target.value))}
              className="w-full mt-3 cursor-pointer"
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>0.1 Gbps</span>
              <span>100 Gbps</span>
            </div>
          </div>

          {/* RX Sensitivity */}
          <div className="mb-3">
            <div className="flex justify-between mb-3">
              <div>
                <label className="metric-label block">RX Sensitivity</label>
                <p className="text-xs text-slate-500 mt-1">Minimum detectable power</p>
              </div>
              <span className="text-cyan-400 font-bold text-lg">CTRL {params.rxSensitivity.toFixed(1)} dBm</span>
            </div>
            <div className="hbar">
              <div
                className="hbar-fill"
                style={{ width: `${((params.rxSensitivity + 70) / 50) * 100}%` }}
              ></div>
            </div>
            <input
              type="range"
              min="-70"
              max="-29"
              value={params.rxSensitivity}
              onChange={(e) => handleSliderChange('rxSensitivity', parseFloat(e.target.value))}
              className="w-full mt-3 cursor-pointer"
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>-70 dBm</span>
              <span>-29 dBm</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
