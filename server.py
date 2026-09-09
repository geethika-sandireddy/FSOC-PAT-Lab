"""
server.py — FSOC-PAT WebSocket telemetry server
================================================
Runs the existing Simulator headlessly and streams rich JSON telemetry to any
connected web client at ~30 Hz. The web frontend at frontend/ connects to
ws://localhost:8000/ws and sends back JSON control commands.

Full Pipeline:
  REAL SIMULATOR -> OpticalLinkModel + PerformanceTracker -> WebSocket -> useTelemetry -> React UI

Usage:
    pip install fastapi uvicorn websockets
    python server.py                    # default EASY preset
    python server.py --preset MODERATE  # pick starting preset
"""

import os
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
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

import config
from core.simulator import Simulator
from ui.mission_pages import OpticalLinkModel, StressTestManager
from metrics.performance import PerformanceTracker

app = FastAPI(title="FSOC-PAT Telemetry Server · SIH 2026")

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
    "optical_params": {
        "tx_power": 30.0,
        "wavelength": 1550.0,
        "distance": 5.0,
        "data_rate": 10.0,
        "rx_sensitivity": -50.0,
        "beam_divergence": 1.5,
        "pointing_error": 1.64,
    },
    "last_telemetry": None,
    "history": deque(maxlen=180),
}

_sim: Simulator | None = None
_perf: PerformanceTracker | None = None
_optical: OpticalLinkModel | None = None
_stress: StressTestManager | None = None
_connected_clients: list[WebSocket] = []
_broadcast_queue: asyncio.Queue = None
_loop_fps: float = 30.0


def _make_sim(preset="EASY", seed=None):
    s = Simulator(preset_name=preset, seed=seed or int(time.time()) % 9999)
    p = PerformanceTracker()
    o = OpticalLinkModel()
    params = SIM_STATE["optical_params"]
    o.tx_power_dbm = params["tx_power"]
    o.wavelength_nm = params["wavelength"]
    o.distance_km = params["distance"]
    o.data_rate_gbps = params["data_rate"]
    o.rx_sensitivity_dbm = params["rx_sensitivity"]
    o.beam_divergence_mrad = params["beam_divergence"]
    st = StressTestManager()
    return s, p, o, st


def _run_sim_loop():
    """Background thread: step the simulator at ~30 Hz, push telemetry."""
    global _sim, _perf, _optical, _stress, _loop_fps
    _sim, _perf, _optical, _stress = _make_sim(SIM_STATE["preset"])
    dt = 1.0 / 30.0
    frame_times = deque(maxlen=30)

    while True:
        loop_start = time.perf_counter()

        with SIM_LOCK:
            if not SIM_STATE["running"]:
                time.sleep(0.05)
                continue

            sim = _sim
            perf = _perf
            optical = _optical
            stress = _stress

            if sim is not None:
                d = SIM_STATE["disturbances"]
                de = sim.disturbance
                de.turbulence = d["turbulence"]
                de.vibration = d["vibration"]
                de.sensor_noise = d["sensor_noise"]
                de.jerk_prob = d["jerk_prob"] / 100.0
                de.beacon_fade = d["beacon_fade"] / 100.0

            if optical is not None:
                op = SIM_STATE["optical_params"]
                optical.tx_power_dbm = op.get("tx_power", optical.tx_power_dbm)
                optical.wavelength_nm = op.get("wavelength", optical.wavelength_nm)
                optical.distance_km = op.get("distance", optical.distance_km)
                optical.data_rate_gbps = op.get("data_rate", optical.data_rate_gbps)
                optical.rx_sensitivity_dbm = op.get("rx_sensitivity", optical.rx_sensitivity_dbm)
                optical.beam_divergence_mrad = op.get("beam_divergence", optical.beam_divergence_mrad)

        if sim is None:
            time.sleep(0.05)
            continue

        try:
            result = sim.step()
        except Exception as e:
            print(f"[sim] step error: {e}")
            time.sleep(0.1)
            continue

        if perf is not None:
            perf.record_frame(sim)

        if optical is not None:
            optical.update_from_sim(result, stress)

        telemetry = _build_telemetry(result, sim, perf, optical, stress, _loop_fps)

        with SIM_LOCK:
            SIM_STATE["last_telemetry"] = telemetry
            SIM_STATE["history"].append({
                "t": telemetry["t"],
                "pointing_err": telemetry["pointing_err_deg"],
                "est_err": telemetry["est_err_deg"],
                "confidence": telemetry["confidence"],
                "rxPower": telemetry["rx_power"],
                "snr": telemetry["snr"],
                "ber": telemetry["ber"],
                "atmLoss": telemetry["atm_loss"],
                "state": telemetry["state"],
            })

        if _broadcast_queue is not None:
            try:
                _broadcast_queue.put_nowait(telemetry)
            except asyncio.QueueFull:
                pass

        elapsed = time.perf_counter() - loop_start
        frame_times.append(elapsed)
        if len(frame_times) >= 5:
            avg_elapsed = sum(frame_times) / len(frame_times)
            _loop_fps = min(60.0, 1.0 / max(1e-4, avg_elapsed))
        sleep = max(0.0, dt - elapsed)
        time.sleep(sleep)


def _build_telemetry(result: dict, sim: Simulator, perf: PerformanceTracker, optical: OpticalLinkModel, stress: StressTestManager, loop_fps: float) -> dict:
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

    state = result["state"]
    false_lock = (
        state in ("LOCKED", "DEGRADED_LOCK")
        and result.get("beacon_visible", True)
        and (result.get("est_err_deg", 0.0) or 0.0) > 0.35
    )

    perf_stats = perf.live_stats() if perf else {}
    acq_t = perf_stats.get("acquisition_time_s")
    ret_pct = perf_stats.get("retention_total_pct", 0.0)

    cam_canvas = sim.sensor._canvas_xy(sim.gimbal.pan, sim.gimbal.tilt)
    b_u, b_v = sim.sensor._viewport_px(sim.scene.beacon.az_deg, sim.scene.beacon.el_deg, cam_canvas)
    beacon_uv = [round(float(b_u), 1), round(float(b_v), 1)] if (0 <= b_u <= 640 and 0 <= b_v <= 480 and result.get("beacon_visible", True)) else None

    distractors_uv = []
    for d in getattr(sim.scene, "distractors", []):
        du, dv = sim.sensor._viewport_px(d.az, d.el, cam_canvas)
        if -40 <= du <= 680 and -40 <= dv <= 520:
            distractors_uv.append([round(float(du), 1), round(float(dv), 1), round(float(d.mod_freq), 1)])

    cand_list_uv = []
    for c in result.get("cand_list", []):
        cand_list_uv.append([round(float(c.u), 1), round(float(c.v), 1)])

    v_pan = getattr(sim.gimbal, "v_pan", 0.0)
    v_tilt = getattr(sim.gimbal, "v_tilt", 0.0)
    slew_spd = math.hypot(v_pan, v_tilt)

    rx_power = round(getattr(optical, "rx_power_dbm", -11.4), 2)
    snr = round(getattr(optical, "snr_db", 73.6), 2)
    margin = round(getattr(optical, "margin_db", 38.6), 2)
    ber = float(getattr(optical, "ber", 1e-15))
    pt_urad = round(getattr(optical, "pointing_error_urad", result["pointing_err_deg"] * 17453.3), 2)
    atm_loss = round(getattr(optical, "atm_loss", 1.5), 2)
    stab_pct = round(getattr(optical, "tracking_stability_pct", 96.0), 1)

    if optical.history and len(optical.history) > 0:
        latest = optical.history[-1]
        rx_power = round(latest.get("rx_power", rx_power), 2)
        snr = round(latest.get("snr", snr), 2)
        margin = round(latest.get("link_margin", margin), 2)
        ber = float(latest.get("ber", ber))
        atm_loss = round(latest.get("atm_loss", atm_loss), 2)
        stab_pct = round(latest.get("stability", stab_pct), 1)

    return {
        "t": round(result["t"], 3),
        "state": state,
        "preset": sim.preset_name,
        "confidence": round(result["confidence"], 3),
        "pointing_err_deg": round(result["pointing_err_deg"], 4),
        "est_err_deg": round(result["est_err_deg"] or 0.0, 4),
        "truth_az": round(result["truth_az"], 3),
        "truth_el": round(result["truth_el"], 3),
        "est_az": round(result["est_az"] or 0.0, 3),
        "est_el": round(result["est_el"] or 0.0, 3),
        "candidates": result["candidates"],
        "beacon_visible": result["beacon_visible"],
        "in_fov": result["in_fov"],
        "gimbal_sat_pan": round(result.get("gimbal_sat_pan", 0.0), 3),
        "gimbal_sat_tilt": round(result.get("gimbal_sat_tilt", 0.0), 3),
        "gimbal_pan": round(sim.gimbal.pan, 3),
        "gimbal_tilt": round(sim.gimbal.tilt, 3),
        "v_pan": round(v_pan, 3),
        "v_tilt": round(v_tilt, 3),
        "slew_spd": round(slew_spd, 3),
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
        "rx_power": rx_power,
        "snr": snr,
        "margin": margin,
        "ber": ber,
        "pointing_error_urad": pt_urad,
        "atm_loss": atm_loss,
        "tracking_quality": stab_pct,
        "temperature": optical.temperature_c,
        "humidity": optical.humidity_pct,
        "wind_speed": optical.wind_speed_ms,
        "tx_power": optical.tx_power_dbm,
        "wavelength": optical.wavelength_nm,
        "distance": optical.distance_km,
        "data_rate": optical.data_rate_gbps,
        "beacon_uv": beacon_uv,
        "distractors_uv": distractors_uv,
        "cand_list_uv": cand_list_uv,
        "candidates_detail": result.get("candidates_detail", []),
        "screen_w": config.SCREEN_SIZE_W,
        "screen_h": config.SCREEN_SIZE_H,
        "cam_center_uv": [config.SCREEN_CANVAS_CX, config.SCREEN_CANVAS_CY],
        "hfov_deg": round(config.HFOV_DEG, 2),
        "vfov_deg": round(config.VFOV_DEG, 2),
        "platform_mode": getattr(sim, "platform_mode", None) or "SATELLITE_SATELLITE",
        "atmosphere_name": getattr(sim, "atmosphere_name", "CLEAR"),
        "atmosphere_allowed": getattr(sim, "atmosphere_allowed", True),
        "target_shape": getattr(sim.scene.beacon, "shape", "SQUARE"),
        "target_size": getattr(sim.scene.beacon, "size_px", 10),
        "target_count": getattr(sim.scene, "num_targets", 1),
        "motion_type": getattr(sim.scene.orbit, "_motion_type", "straight_line"),
        "gimbal_max_pan": round(getattr(sim.gimbal, "max_pan_deg_s", 5.0), 1),
        "gimbal_max_tilt": round(getattr(sim.gimbal, "max_tilt_deg_s", 5.0), 1),
        "noise_types": list(getattr(sim.disturbance, "noise_types", ["gaussian"])),
        "last_reacq_s": perf_stats.get("last_reacq_s"),
        "mean_reacq_s": perf_stats.get("mean_reacq_s"),
        "fps": round(loop_fps, 1),
        "acq_time": round(acq_t, 2) if acq_t is not None else None,
        "retention_pct": round(ret_pct, 1),
        "connected": True,
    }


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/presets")
def list_presets():
    return {"presets": list(config.DIFFICULTY_PRESETS.keys())}


@app.post("/preset/{name}")
def set_preset(name: str):
    global _sim, _perf, _optical, _stress
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
    _sim, _perf, _optical, _stress = _make_sim(name)
    return {"ok": True, "preset": name}


@app.post("/reset")
def reset_sim():
    global _sim, _perf, _optical, _stress
    with SIM_LOCK:
        preset = SIM_STATE["preset"]
    _sim, _perf, _optical, _stress = _make_sim(preset)
    return {"ok": True}


@app.post("/pause")
def pause_sim():
    with SIM_LOCK:
        SIM_STATE["running"] = not SIM_STATE["running"]
    return {"running": SIM_STATE["running"]}


@app.post("/disturbance")
async def set_disturbance(body: dict):
    with SIM_LOCK:
        for k, v in body.items():
            if k in SIM_STATE["disturbances"]:
                SIM_STATE["disturbances"][k] = v
    return {"ok": True}


@app.post("/optical_params")
async def set_optical_params(body: dict):
    with SIM_LOCK:
        for k, v in body.items():
            if k in SIM_STATE["optical_params"]:
                SIM_STATE["optical_params"][k] = float(v)
    return {"ok": True, "params": SIM_STATE["optical_params"]}


@app.get("/history")
def get_history():
    with SIM_LOCK:
        return {"history": list(SIM_STATE["history"])}


@app.get("/benchmark/summary")
def get_benchmark_summary():
    """Return latest multi-preset benchmark summary JSON."""
    json_path = os.path.join(config.LOG_DIR, "benchmark_summary.json")
    if os.path.isfile(json_path):
        with open(json_path, "r") as f:
            return json.load(f)
    return {"error": "Benchmark summary not found. Run benchmark suite first."}


@app.get("/benchmark/list-videos")
def list_benchmark_videos():
    """List available MP4 videos in logs/ and workspace root."""
    videos = []
    root = os.path.dirname(os.path.abspath(__file__))
    dirs_to_check = [config.LOG_DIR, root]
    seen = set()
    for d in dirs_to_check:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.lower().endswith(".mp4") and fn not in seen:
                seen.add(fn)
                full_path = os.path.join(d, fn)
                truth_csv = os.path.splitext(full_path)[0] + "_truth.csv"
                has_truth = os.path.isfile(truth_csv)
                try:
                    size_mb = os.path.getsize(full_path) / (1024 * 1024)
                except Exception:
                    size_mb = 0.0
                videos.append({
                    "filename": fn,
                    "path": full_path,
                    "has_truth": has_truth,
                    "truth_csv": truth_csv if has_truth else None,
                    "size_mb": round(size_mb, 2),
                })
    return {"videos": videos}


@app.post("/benchmark/run-mp4")
def run_mp4_benchmark_endpoint(body: dict):
    """Run Benchmark-2 MP4 bypass and return comprehensive evaluation metrics."""
    from metrics.mp4_bypass import run_bypass
    video_path = body.get("video_path")
    if not video_path or not os.path.isfile(video_path):
        # Fallback search in logs/
        cand = [os.path.join(config.LOG_DIR, f) for f in os.listdir(config.LOG_DIR) if f.endswith(".mp4")] if os.path.isdir(config.LOG_DIR) else []
        if cand:
            video_path = cand[0]
        else:
            return {"error": f"Video file not found: {video_path}"}

    truth_path = body.get("truth_path")
    stats = run_bypass(video_path, truth_path=truth_path, verbose=False)
    return stats


@app.post("/benchmark/generate-synthetic")
def generate_synthetic_video_endpoint(body: dict):
    """Generate a synthetic benchmark MP4 with ground truth sidecar CSV."""
    from metrics.synthetic_video import generate
    motion = body.get("motion", "figure_eight")
    noise = body.get("noise", ["gaussian"])
    seconds = float(body.get("seconds", 5.0))
    fps = int(body.get("fps", 30))
    out_name = f"bench_{motion}_{int(time.time())}.mp4"
    out_path = os.path.join(config.LOG_DIR, out_name)
    v_path, t_path = generate(out_path, width=640, height=480, fps=fps, seconds=seconds,
                              motion=motion, noise=noise, beacon_size=10)
    return {"video_path": v_path, "truth_path": t_path, "filename": out_name}


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
        if ws in _connected_clients:
            _connected_clients.remove(ws)


async def _handle_command(cmd: dict):
    global _sim, _perf, _optical, _stress
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
            _sim, _perf, _optical, _stress = _make_sim(name)
    elif action == "reset":
        with SIM_LOCK:
            preset = SIM_STATE["preset"]
        _sim, _perf, _optical, _stress = _make_sim(preset)
    elif action == "pause":
        with SIM_LOCK:
            SIM_STATE["running"] = not SIM_STATE["running"]
    elif action == "set_disturbance":
        with SIM_LOCK:
            for k, v in cmd.items():
                if k != "action" and k in SIM_STATE["disturbances"]:
                    SIM_STATE["disturbances"][k] = v
    elif action == "set_optical_params":
        with SIM_LOCK:
            for k, v in cmd.items():
                if k in SIM_STATE["optical_params"]:
                    SIM_STATE["optical_params"][k] = float(v)
    elif action == "trigger_stress":
        sid = cmd.get("scenario_id")
        if _stress and sid in _stress.scenarios:
            _stress.toggle(sid)
    elif action == "set_platform":
        pm = cmd.get("platform", "SATELLITE_SATELLITE")
        with SIM_LOCK:
            if _sim is not None:
                _sim.set_platform_mode(pm)
    elif action == "set_atmosphere":
        atm = cmd.get("atmosphere", "CLEAR")
        with SIM_LOCK:
            if _sim is not None:
                _sim.set_atmosphere(atm)
    elif action == "set_fov":
        hfov = float(cmd.get("hfov", 4.0))
        vfov = float(cmd.get("vfov", 3.0)) if "vfov" in cmd else None
        with SIM_LOCK:
            if _sim is not None:
                _sim.set_fov(hfov, vfov)
    elif action == "set_screen_size":
        w = int(cmd.get("w", 2000))
        h = int(cmd.get("h", 2000))
        with SIM_LOCK:
            if _sim is not None:
                _sim.set_screen_size(w, h)
    elif action == "set_motion":
        m = cmd.get("motion", "straight_line")
        with SIM_LOCK:
            if _sim is not None:
                _sim.set_motion_type(m)
    elif action == "set_target":
        shape = cmd.get("shape")
        size = cmd.get("size")
        count = cmd.get("count")
        initial = cmd.get("initial")
        with SIM_LOCK:
            if _sim is not None:
                _sim.set_target_params(shape=shape, size_px=size, count=count, initial=initial)
    elif action == "set_gimbal":
        pan = cmd.get("max_pan")
        tilt = cmd.get("max_tilt")
        with SIM_LOCK:
            if _sim is not None:
                _sim.set_gimbal_limits(max_pan=pan, max_tilt=tilt)
    elif action == "set_noise_types":
        ntypes = cmd.get("noise_types", ["gaussian"])
        with SIM_LOCK:
            if _sim is not None:
                _sim.set_noise_types(ntypes)
    elif action == "inject_occlusion":
        dur = float(cmd.get("duration", 1.0))
        with SIM_LOCK:
            if _sim is not None:
                _sim.inject_target_loss(duration_s=dur)


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
# Static frontend mounting (if frontend/dist exists)
# ---------------------------------------------------------------------------
dist_path = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(dist_path) and os.path.isfile(os.path.join(dist_path, "index.html")):
    assets_dir = os.path.join(dist_path, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    
    @app.get("/")
    def serve_frontend_index():
        return FileResponse(os.path.join(dist_path, "index.html"))


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

    print("===============================================================")
    print("FSOC-PAT REALTIME TELEMETRY SERVER - SIH 2026")
    print("===============================================================")
    print(f"API & Status:   http://{args.host}:{args.port}")
    print(f"WebSocket Feed: ws://{args.host}:{args.port}/ws")
    print(f"Active Preset:  {args.preset}")
    print("---------------------------------------------------------------")
    uvicorn.run(app, host=args.host, port=args.port)
