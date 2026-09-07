type Page = "overview" | "telemetry" | "scene" | "benchmark" | "events";

interface Props { current: Page; onChange: (p: Page) => void; }

const TABS: { id: Page; label: string; abbr: string; icon: string }[] = [
  { id:"overview",   label:"Mission Overview",  abbr:"OVW", icon:"⊞" },
  { id:"telemetry",  label:"Live Telemetry",    abbr:"TEL", icon:"∿" },
  { id:"scene",      label:"Scene & Config",    abbr:"CFG", icon:"⚙" },
  { id:"benchmark",  label:"Benchmark",         abbr:"BNK", icon:"▦" },
  { id:"events",     label:"Event Log",         abbr:"EVT", icon:"◎" },
];

export default function TopNav({ current, onChange }: Props) {
  return (
    <nav style={{
      display:"flex", alignItems:"stretch",
      height:34,
      background:"var(--c-panel-2)",
      borderBottom:"1px solid var(--c-border)",
      paddingLeft:8,
      gap:0,
    }}>
      {TABS.map(tab => (
        <button
          key={tab.id}
          className={`tab-btn${current === tab.id ? " active" : ""}`}
          onClick={() => onChange(tab.id)}
          title={tab.label}
        >
          <span style={{ opacity:0.6, fontSize:11 }}>{tab.icon}</span>
          <span>{tab.abbr}</span>
          <span style={{ fontSize:9, color:"inherit", opacity:0.5 }}>—</span>
          <span style={{ fontSize:9, letterSpacing:"0.05em" }}>{tab.label}</span>
        </button>
      ))}
      {/* Right side: keyboard hints */}
      <div style={{
        marginLeft:"auto", display:"flex", alignItems:"center",
        paddingRight:16, gap:8,
      }}>
        <span className="font-data" style={{ fontSize:8, color:"var(--c-faint)", letterSpacing:"0.06em" }}>
          FSOC-PAT  ·  ISRO SIH 2026  ·  PS 26169
        </span>
      </div>
    </nav>
  );
}
