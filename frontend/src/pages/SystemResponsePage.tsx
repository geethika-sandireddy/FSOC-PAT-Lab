interface SystemResponsePageProps {
  telemetry: any
}

const systemMetrics = [
  { label: 'RX Optical Power', value: '-11.4 dBm', color: 'cyan' },
  { label: 'BER', value: '<1e-12', color: 'cyan' },
  { label: 'SNR', value: '73.6 dB', color: 'green' },
  { label: 'Link Margin', value: '38.6 dB', color: 'green' },
]

const lossComponents = [
  { label: 'ATM Loss', value: '1.5 dB', width: 15 },
  { label: 'Geo Loss', value: '40.0 dB', width: 40 },
  { label: 'Pointing Loss', value: '0.0 dB', width: 0 },
  { label: 'Total Loss', value: '41.5 dB', width: 41.5 },
]

export default function SystemResponsePage({ telemetry }: SystemResponsePageProps) {
  return (
    <div className="h-full w-full p-4 overflow-auto">
      <div className="grid grid-cols-2 gap-4">
        {/* Current Telemetry */}
        <div className="panel p-6">
          <div className="panel-header mb-6">Current Telemetry Values</div>
          <div className="grid grid-cols-2 gap-4">
            {systemMetrics.map((metric, idx) => (
              <div key={idx} className="border-l-2 border-cyan-500/30 pl-3">
                <div className="metric-label mb-1">{metric.label}</div>
                <div className={`metric-value text-${metric.color}-400`}>{metric.value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Link Budget Breakdown */}
        <div className="panel p-6">
          <div className="panel-header mb-6">Link Budget Breakdown</div>
          <div className="space-y-4">
            {lossComponents.map((item, idx) => (
              <div key={idx}>
                <div className="flex justify-between mb-2">
                  <span className="metric-label">{item.label}</span>
                  <span className="text-cyan-400 font-bold">{item.value}</span>
                </div>
                <div className="hbar">
                  <div
                    className="hbar-fill"
                    style={{ width: `${Math.min(item.width / 50 * 100, 100)}%` }}
                  ></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
