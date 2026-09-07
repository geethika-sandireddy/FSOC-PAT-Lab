"""
server.py — FSOC-PAT WebSocket telemetry server
================================================
Runs the existing Simulator headlessly and streams JSON telemetry to any
connected web client at ~30 Hz.  The web frontend at frontend/ connects to
ws://localhost:8000/ws and sends back JSON control commands.

Usage:
    pip install fastapi uvicorn websockets
    python server.py                    # default EASY preset
    python server.py --preset MODERATE  # pick starting preset

The server wraps the same core.simulator.Simulator used by main.py, so every
number on the web dashboard is identical to what the pygame GUI would show.
"""

import asyncio
import json
import math
import time
import argparse
import threading
from collections import deque

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import config
from core.simulator import Simulator

app = FastAPI(title="FSOC-PAT Telemetry Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Shared simulation state (runs in a background thread)
# ---------------------------------------------------------------------------

SIM_LOCK = threading.Lock()
SIM_STATE = {
    "preset": "EASY",
    "running": True,
    "disturbances": {
        "turbulence": 5,
        "vibration": 2,
        "sensor_noise": 5,
        "jerk_prob": 0,
        "beacon_fade": 0,
    },
    "last_telemetry": None,
    "history": deque(maxlen=120),
}

_sim: Simulator | None = None
_connected_clients: list[WebSocket] = []
_broadcast_queue: asyncio.Queue = None  # set up in startup


def _make_sim(preset="EASY", seed=None) -> Simulator:
    return Simulator(preset_name=preset, seed=seed or int(time.time()) % 9999)


def _run_sim_loop():
    """Background thread: step the simulator at ~30 Hz, push telemetry."""
    global _sim
    _sim = _make_sim(SIM_STATE["preset"])
    dt = 1.0 / 30.0

    while True:
        loop_start = time.perf_counter()

        with SIM_LOCK:
            if not SIM_STATE["running"]:
                time.sleep(0.05)
                continue

            # Apply any pending disturbance overrides
            d = SIM_STATE["disturbances"]
            if _sim is not None:
                de = _sim.disturbance
                de.turbulence = d["turbulence"]
                de.vibration = d["vibration"]
                de.sensor_noise = d["sensor_noise"]
                de.jerk_prob = d["jerk_prob"] / 100.0
                de.beacon_fade = d["beacon_fade"] / 100.0

        # Step sim outside lock to avoid starving network thread
        try:
            result = _sim.step()
        except Exception as e:
            print(f"[sim] step error: {e}")
            time.sleep(0.1)
            continue

        telemetry = _build_telemetry(result, _sim)

        with SIM_LOCK:
            SIM_STATE["last_telemetry"] = telemetry
            SIM_STATE["history"].append({
                "t": telemetry["t"],
                "pointing_err": telemetry["pointing_err_deg"],
                "est_err": telemetry["est_err_deg"],
                "confidence": telemetry["confidence"],
                "candidates": telemetry["candidates"],
            })

        # Push to event queue for async broadcast
        if _broadcast_queue is not None:
            try:
                _broadcast_queue.put_nowait(telemetry)
            except asyncio.QueueFull:
                pass  # drop frame if clients are slow

        elapsed = time.perf_counter() - loop_start
        sleep = max(0.0, dt - elapsed)
        time.sleep(sleep)


def _build_telemetry(result: dict, sim: Simulator) -> dict:
    tr = sim.tracker
    trust = getattr(tr, "trust", None)
    conf_obj = getattr(tr, "conf", None)
    unc_obj = getattr(tr, "unc", None)

    sigma_px = 0.0
    if unc_obj is not None:
        raw_sigma = getattr(unc_obj, "sigma_px", 0.0)
        sigma_px = min(raw_sigma, 24.0)

    vision_trust = round(getattr(trust, "vision_trust", 0.0), 3) if trust else 0.0
    model_trust = round(getattr(trust, "model_trust", 0.0), 3) if trust else 0.0
    trust_mode = getattr(trust, "mode", "BALANCED") if trust else "BALANCED"

    id_conf = round(getattr(conf_obj, "identity", 0.0), 3) if conf_obj else 0.0
    pos_conf = round(getattr(conf_obj, "position", 0.0), 3) if conf_obj else 0.0
    pred_conf = round(getattr(conf_obj, "prediction", 0.0), 3) if conf_obj else 0.0
    pt_conf = round(getattr(conf_obj, "pointing", 0.0), 3) if conf_obj else 0.0

    # False-lock: locked but large estimate error while beacon visible
    state = result["state"]
    false_lock = (
        state in ("LOCKED", "DEGRADED_LOCK")
        and result.get("beacon_visible", True)
        and result.get("est_err_deg", 0.0) > 0.35
    )

    return {
        "t": round(result["t"], 3),
        "state": state,
        "preset": sim.preset_name,
        "confidence": round(result["confidence"], 3),
        "pointing_err_deg": round(result["pointing_err_deg"], 4),
        "est_err_deg": round(result["est_err_deg"], 4),
        "truth_az": round(result["truth_az"], 3),
        "truth_el": round(result["truth_el"], 3),
        "est_az": round(result["est_az"], 3),
        "est_el": round(result["est_el"], 3),
        "candidates": result["candidates"],
        "beacon_visible": result["beacon_visible"],
        "in_fov": result["in_fov"],
        "gimbal_sat_pan": round(result.get("gimbal_sat_pan", 0.0), 3),
        "gimbal_sat_tilt": round(result.get("gimbal_sat_tilt", 0.0), 3),
        "vision_trust": vision_trust,
        "model_trust": model_trust,
        "trust_mode": trust_mode,
        "id_conf": id_conf,
        "pos_conf": pos_conf,
        "pred_conf": pred_conf,
        "pt_conf": pt_conf,
        "sigma_px": round(sigma_px, 2),
        "false_lock": false_lock,
        "disturbances": dict(SIM_STATE["disturbances"]),
    }


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/presets")
def list_presets():
    return {"presets": list(config.DIFFICULTY_PRESETS.keys())}


@app.post("/preset/{name}")
def set_preset(name: str):
    global _sim
    if name not in config.DIFFICULTY_PRESETS:
        return {"error": "unknown preset"}
    with SIM_LOCK:
        SIM_STATE["preset"] = name
        p = config.DIFFICULTY_PRESETS[name]
        SIM_STATE["disturbances"].update({
            "turbulence": p.get("turbulence", 5),
            "vibration": p.get("vibration", 2),
            "sensor_noise": p.get("sensor_noise", 5),
            "jerk_prob": int(p.get("jerk_prob", 0) * 100),
            "beacon_fade": int(p.get("beacon_fade", 0) * 100),
        })
    _sim = _make_sim(name)
    return {"ok": True, "preset": name}


@app.post("/reset")
def reset_sim():
    global _sim
    with SIM_LOCK:
        preset = SIM_STATE["preset"]
    _sim = _make_sim(preset)
    return {"ok": True}


@app.post("/pause")
def pause_sim():
    with SIM_LOCK:
        SIM_STATE["running"] = not SIM_STATE["running"]
    return {"running": SIM_STATE["running"]}


@app.post("/disturbance")
async def set_disturbance(body: dict):
    with SIM_LOCK:
        SIM_STATE["disturbances"].update(body)
    return {"ok": True}


@app.get("/history")
def get_history():
    with SIM_LOCK:
        return {"history": list(SIM_STATE["history"])}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _connected_clients.append(ws)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=0.1)
                cmd = json.loads(msg)
                await _handle_command(cmd)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _connected_clients.remove(ws)


async def _handle_command(cmd: dict):
    global _sim
    action = cmd.get("action")
    if action == "set_preset":
        name = cmd.get("preset", "EASY")
        if name in config.DIFFICULTY_PRESETS:
            with SIM_LOCK:
                SIM_STATE["preset"] = name
                p = config.DIFFICULTY_PRESETS[name]
                SIM_STATE["disturbances"].update({
                    "turbulence": p.get("turbulence", 5),
                    "vibration": p.get("vibration", 2),
                    "sensor_noise": p.get("sensor_noise", 5),
                    "jerk_prob": int(p.get("jerk_prob", 0) * 100),
                    "beacon_fade": int(p.get("beacon_fade", 0) * 100),
                })
            _sim = _make_sim(name)
    elif action == "reset":
        with SIM_LOCK:
            preset = SIM_STATE["preset"]
        _sim = _make_sim(preset)
    elif action == "pause":
        with SIM_LOCK:
            SIM_STATE["running"] = not SIM_STATE["running"]
    elif action == "set_disturbance":
        with SIM_LOCK:
            for k, v in cmd.items():
                if k != "action" and k in SIM_STATE["disturbances"]:
                    SIM_STATE["disturbances"][k] = v


async def _broadcast_loop():
    """Pull frames from queue and push to all connected WebSocket clients."""
    while True:
        try:
            frame = await asyncio.wait_for(_broadcast_queue.get(), timeout=1.0)
            if _connected_clients:
                dead = []
                for ws in list(_connected_clients):
                    try:
                        await ws.send_text(json.dumps(frame))
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    if ws in _connected_clients:
                        _connected_clients.remove(ws)
        except asyncio.TimeoutError:
            continue


@app.on_event("startup")
async def startup():
    global _broadcast_queue
    _broadcast_queue = asyncio.Queue(maxsize=5)
    sim_thread = threading.Thread(target=_run_sim_loop, daemon=True)
    sim_thread.start()
    asyncio.create_task(_broadcast_loop())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", default="EASY")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    with SIM_LOCK:
        SIM_STATE["preset"] = args.preset
        p = config.DIFFICULTY_PRESETS.get(args.preset, {})
        SIM_STATE["disturbances"].update({
            "turbulence": p.get("turbulence", 5),
            "vibration": p.get("vibration", 2),
            "sensor_noise": p.get("sensor_noise", 5),
            "jerk_prob": int(p.get("jerk_prob", 0) * 100),
            "beacon_fade": int(p.get("beacon_fade", 0) * 100),
        })

    print(f"Starting FSOC-PAT telemetry server on http://{args.host}:{args.port}")
    print(f"WebSocket: ws://{args.host}:{args.port}/ws")
    print(f"Web frontend: open frontend/index.html or serve frontend/ directory")
    uvicorn.run(app, host=args.host, port=args.port)
