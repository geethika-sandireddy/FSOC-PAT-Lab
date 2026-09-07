type Page = "overview" | "telemetry" | "scene" | "benchmark" | "events";

interface Props { current: Page; onChange: (p: Page) => void; alertCount: number; }

const ITEMS = [
  { id: "overview" as Page, abbr: "OVW", title: "Mission Overview",
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <rect x="1" y="1" width="6" height="6" rx="0.5" stroke="currentColor" strokeWidth="1.2"/>
      <rect x="9" y="1" width="6" height="6" rx="0.5" stroke="currentColor" strokeWidth="1.2"/>
      <rect x="1" y="9" width="6" height="6" rx="0.5" stroke="currentColor" strokeWidth="1.2"/>
      <rect x="9" y="9" width="6" height="6" rx="0.5" stroke="currentColor" strokeWidth="1.2"/>
    </svg> },
  { id: "telemetry" as Page, abbr: "TEL", title: "Live Telemetry",
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <polyline points="1,12 4,8 7,10 10,4 13,7 15,2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
    </svg> },
  { id: "scene" as Page, abbr: "CFG", title: "Scene & Config",
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="3" stroke="currentColor" strokeWidth="1.2"/>
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M2.93 2.93l1.41 1.41M11.66 11.66l1.41 1.41M2.93 13.07l1.41-1.41M11.66 4.34l1.41-1.41" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
    </svg> },
  { id: "benchmark" as Page, abbr: "BNK", title: "Benchmark",
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <rect x="1" y="10" width="3" height="5" rx="0.5" stroke="currentColor" strokeWidth="1.2"/>
      <rect x="6" y="6" width="3" height="9" rx="0.5" stroke="currentColor" strokeWidth="1.2"/>
      <rect x="11" y="2" width="3" height="13" rx="0.5" stroke="currentColor" strokeWidth="1.2"/>
    </svg> },
  { id: "events" as Page, abbr: "EVT", title: "Event Log",
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 2C5.24 2 3 4.24 3 7v4l-1 1v1h12v-1l-1-1V7c0-2.76-2.24-5-5-5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
      <path d="M6 13a2 2 0 0 0 4 0" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
    </svg> },
];

export default function SideNav({ current, onChange, alertCount }: Props) {
  return (
    <div className="flex flex-col shrink-0"
      style={{ width:50, background:"#060a12", borderRight:"1px solid #1a2340", paddingTop:6, paddingBottom:6, gap:2 }}>
      {ITEMS.map(item => {
        const active = current === item.id;
        const hasAlert = item.id === "events" && alertCount > 0;
        return (
          <button key={item.id} onClick={() => onChange(item.id)} title={item.title}
            className="relative flex flex-col items-center justify-center gap-1 mx-1.5 py-2.5 rounded transition-all"
            style={{
              background: active ? "#00d4aa10" : "transparent",
              border: active ? "1px solid #00d4aa28" : "1px solid transparent",
              color: active ? "#00d4aa" : "#2d3f5e",
              cursor:"pointer",
            }}
            onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.color = "#7a8aaa"; }}
            onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.color = "#2d3f5e"; }}
          >
            {item.icon}
            <span className="font-data" style={{ fontSize:7, letterSpacing:"0.08em" }}>{item.abbr}</span>
            {hasAlert && (
              <span className="absolute top-1.5 right-1.5 rounded-full"
                style={{ background:"#ff3c3c", width:5, height:5 }}/>
            )}
          </button>
        );
      })}
    </div>
  );
}
