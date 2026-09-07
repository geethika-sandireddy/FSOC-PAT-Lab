# FSOC-PAT Web Mission Control

React + Vite web frontend for the FSOC-PAT simulation system.
Connects to `server.py` (FastAPI WebSocket) to receive live telemetry.
Falls back to demo mode automatically when the server is not running.

## Quick Start

```bash
# 1. Install backend server dependencies (once)
pip install fastapi uvicorn websockets

# 2. Start the telemetry server (in the repo root)
python server.py --preset EASY

# 3. Install frontend dependencies and start dev server
cd frontend
pnpm install      # or npm install
pnpm dev          # serves at http://localhost:5173

# 4. Open http://localhost:5173 in a browser
```

## Production Build

```bash
cd frontend
pnpm build        # outputs to frontend/dist/
pnpm preview      # serves the production build locally
```

## Pages

| Page | Description |
|------|-------------|
| **Mission Overview** | Live AzEl radar plot, state banner, Phase 2 confidence decomposition, trust manager, session KPIs |
| **Live Telemetry** | Recharts time-series: pointing error, estimate error, confidence, σ, confidence sub-scores |
| **Scene & Config** | Preset switcher, live disturbance sliders, PS 26169 parameter reference |
| **Benchmark** | Canonical results table (Benchmark-1 synthetic, Benchmark-2 MP4), Phase 2 trust improvements |
| **Event Log** | State transition timeline, false-lock events, session statistics |

## Architecture

```
server.py           FastAPI + WebSocket — wraps core.simulator.Simulator headlessly
  └── /ws           WebSocket endpoint: streams JSON telemetry @ 30 Hz
  └── /preset/:name POST — change difficulty preset (resets sim)
  └── /reset        POST — reset with current preset
  └── /pause        POST — toggle running
  └── /disturbance  POST — live disturbance override

frontend/src/
  hooks/useTelemetry.ts   WebSocket client, demo-mode fallback, state management
  components/
    CommandBar.tsx         Top bar: state, confidence, preset, running toggle
    SideNav.tsx            Icon navigation
    AzElPlot.tsx           SVG radar: truth beacon, gimbal estimate, FOV, σ circle
    OverviewPage.tsx       Main HUD with all live metrics
    TelemetryPage.tsx      Time-series charts via Recharts
    SceneConfigPage.tsx    Preset + disturbance controls + PS parameter reference
    BenchmarkPage.tsx      Benchmark-1/2 results + Phase 2 improvements
    EventLogPage.tsx       State-transition event log + timeline strip
```
