import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

interface TelemetryPageProps {
  telemetry: any
}

const nominalData = Array.from({ length: 60 }, (_, i) => {
  const t = i * 0.5;
  return {
    time: i,
    rxPower: -11.4 - Math.sin(t * 0.1) * 0.8,
    snr: 73.6 + Math.cos(t * 0.15) * 1.2,
    ber: 1e-12,
    pointError: 1.5 + Math.sin(t * 0.08) * 0.4,
  };
});

export default function TelemetryPage({ telemetry }: TelemetryPageProps) {
  return (
    <div className="h-full w-full p-4 overflow-auto">
      <div className="grid grid-cols-2 gap-4">
        {/* RX Power vs Margin */}
        <div className="panel p-4">
          <div className="panel-header">Optical Power – RX vs Margin</div>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={telemetry?.history && telemetry.history.length > 0 ? telemetry.history : nominalData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #00d4aa' }} />
              <Line type="monotone" dataKey="rxPower" stroke="#00d4aa" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* BER Log Scale */}
        <div className="panel p-4">
          <div className="panel-header">Bit Error Rate – Log Scale</div>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={telemetry?.history && telemetry.history.length > 0 ? telemetry.history : nominalData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#64748b" />
              <YAxis stroke="#64748b" scale="log" />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #00d4aa' }} />
              <Line type="monotone" dataKey="ber" stroke="#7c3aed" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* SNR */}
        <div className="panel p-4">
          <div className="panel-header">Signal-to-Noise Ratio</div>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={telemetry?.history && telemetry.history.length > 0 ? telemetry.history : nominalData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #00d4aa' }} />
              <Line type="monotone" dataKey="snr" stroke="#00ff00" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Pointing Error */}
        <div className="panel p-4">
          <div className="panel-header">Pointing Error & Atmospheric Loss</div>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={telemetry?.history && telemetry.history.length > 0 ? telemetry.history : nominalData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #00d4aa' }} />
              <Line type="monotone" dataKey="pointError" stroke="#ffa500" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
