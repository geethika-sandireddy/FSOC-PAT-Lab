interface SideNavProps {
  currentPage: string
  onPageChange: (page: any) => void
}

const navItems = [
  { id: 'simulation', label: 'SIMULATION', icon: '□' },
  { id: 'telemetry', label: 'TELEMETRY', icon: '📈' },
  { id: 'link', label: 'LINK PARAMS', icon: '⚙' },
  { id: 'system', label: 'SYSTEM', icon: '◯' },
  { id: 'optical', label: 'OPTICAL', icon: '◈' },
  { id: 'events', label: 'EVENT LOG', icon: '▬' },
]

export default function SideNav({ currentPage, onPageChange }: SideNavProps) {
  return (
    <nav className="w-32 border-r border-cyan-500/30 bg-gradient-to-b from-slate-950 to-slate-900 overflow-y-auto flex flex-col gap-2 p-3">
      {navItems.map((item) => (
        <button
          key={item.id}
          onClick={() => onPageChange(item.id)}
          className={`text-left px-3 py-2 rounded text-xs font-bold uppercase tracking-wider transition-all border-l-2 ${
            currentPage === item.id
              ? 'border-cyan-400 bg-cyan-500/15 text-cyan-300'
              : 'border-slate-700/50 text-slate-400 hover:border-cyan-500/50 hover:bg-cyan-500/5'
          }`}
        >
          <div className="text-lg">{item.icon}</div>
          <div className="mt-1">{item.label}</div>
        </button>
      ))}
    </nav>
  )
}
