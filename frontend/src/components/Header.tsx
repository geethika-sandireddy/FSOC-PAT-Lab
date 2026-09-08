import React from 'react'

interface HeaderProps {
  isRunning: boolean
  onToggle: () => void
}

function useUTCTime() {
  const [time, setTime] = React.useState(new Date().toISOString())
  React.useEffect(() => {
    const timer = setInterval(() => setTime(new Date().toISOString()), 1000)
    return () => clearInterval(timer)
  }, [])
  return time
}

export default function Header({ isRunning, onToggle }: HeaderProps) {
  const utcTime = useUTCTime()

  return (
    <header className="border-b border-cyan-500/30 bg-gradient-to-r from-slate-950 via-slate-900 to-slate-950 px-6 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-8">
          <div>
            <h1 className="text-2xl font-bold text-cyan-400 tracking-wider">FSOC-PAT</h1>
            <p className="text-xs text-slate-400 uppercase tracking-widest mt-1">Mission Control · SIH 2026 · PS 26169</p>
          </div>
          
          <div className="h-12 w-px bg-gradient-to-b from-cyan-500/0 via-cyan-500/50 to-cyan-500/0"></div>
          
          <div className="flex gap-6 text-center">
            <div>
              <p className="text-xs text-slate-400 uppercase tracking-wider">Link State</p>
              <p className="text-lg font-bold text-green-400 mt-1 pulse-glow">● ESTABLISHED</p>
            </div>
            <div>
              <p className="text-xs text-slate-400 uppercase tracking-wider">RX Power</p>
              <p className="text-lg font-bold text-cyan-400 mt-1">-11.4 dBm</p>
            </div>
            <div>
              <p className="text-xs text-slate-400 uppercase tracking-wider">SNR</p>
              <p className="text-lg font-bold text-cyan-400 mt-1">73.6 dB</p>
            </div>
            <div>
              <p className="text-xs text-slate-400 uppercase tracking-wider">Margin</p>
              <p className="text-lg font-bold text-cyan-400 mt-1">38.6 dB</p>
            </div>
            <div>
              <p className="text-xs text-slate-400 uppercase tracking-wider">Tracking</p>
              <p className="text-lg font-bold text-green-400 mt-1">97 %</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-xs text-slate-400 uppercase tracking-wider">UTC</p>
            <p className="text-sm font-mono text-cyan-300 mt-1">{utcTime.split('T')[0]} {utcTime.split('T')[1].slice(0, 8)}</p>
          </div>
          
          <button
            onClick={onToggle}
            className={`px-4 py-2 rounded border-2 font-bold uppercase tracking-wider transition-all ${
              isRunning
                ? 'border-amber-500/50 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20'
                : 'border-cyan-500/50 bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20'
            }`}
          >
            {isRunning ? '⏸ PAUSE' : '▶ RESUME'}
          </button>
        </div>
      </div>
    </header>
  )
}
