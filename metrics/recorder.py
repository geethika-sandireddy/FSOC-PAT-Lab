"""
metrics/recorder.py
-------------------
Records the virtual scene to an .mp4 video file for the optional 3-5 minute
demo deliverable.  Renders each simulation frame to a pygame surface, reads
the pixels, and writes via OpenCV.

Usage:
    python -m metrics.recorder --preset EASY --seconds 180 --output demo.mp4
    python -m metrics.recorder --preset MODERATE --seconds 30 --output quick_demo.mp4
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np
import pygame

import config


def record(preset_name="EASY", seconds=180, output_path="demo.mp4",
           seed=9, show_hud=True):
    """Record a simulation run to MP4.  Returns the output path."""
    # must init pygame off-screen for rendering
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    pygame.init()
    w, h = config.CAM_VIEW_W, config.CAM_VIEW_H
    screen = pygame.display.set_mode((w, h))

    from core.simulator import Simulator
    from core.scene import Scene3D
    from ui import view3d as v3d

    sim = Simulator(preset_name=preset_name, seed=seed)
    dt = 1.0 / config.FPS
    n_frames = int(seconds / dt)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, config.FPS, (w, h))
    t0 = time.time()

    for i in range(n_frames):
        sim.step()

        # render the scene into the pygame surface
        screen.fill((0, 0, 0))
        sim_frame = sim.last_result.get("frame")
        if sim_frame is not None:
            # frame is BGR float → convert to RGB uint8 for pygame
            rgb = np.clip(sim_frame[:, :, ::-1], 0, 255).astype(np.uint8)
            surf = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
            screen.blit(surf, (0, 0))

        if show_hud:
            _draw_hud(screen, sim)

        # read pixels from pygame and write to video
        px = pygame.surfarray.array3d(screen)
        bgr = np.transpose(px, (1, 0, 2))[:, :, ::-1]
        writer.write(bgr)

        if i % (config.FPS * 10) == 0 and i > 0:
            elapsed = time.time() - t0
            pct = i / n_frames * 100
            print(f"\r  recording {pct:.0f}% ({i}/{n_frames} frames, "
                  f"{elapsed:.1f}s wall)", end="", flush=True)

    writer.release()
    elapsed = time.time() - t0
    print(f"\n  recording complete: {output_path} "
          f"({n_frames} frames, {elapsed:.1f}s)")
    pygame.quit()
    return output_path


def _draw_hud(screen, sim):
    """Minimal HUD overlay on the recorded frame."""
    w, h = screen.get_size()
    res = sim.last_result
    err = res["pointing_err_deg"]
    state = res["state"]

    font = pygame.font.SysFont("consolas", 11)
    texts = [
        f"PS 26169 | {sim.preset_name} | {state}",
        f"err {err * 1000:.1f} mdeg | "
        f"t={sim.t:.1f}s | {sim.tracker.state}",
    ]
    y = 4
    for t in texts:
        surf = font.render(t, True, (0, 220, 100))
        screen.blit(surf, (6, y))
        y += 14


def main():
    ap = argparse.ArgumentParser(description="Record simulation demo to MP4")
    ap.add_argument("--preset", default="EASY")
    ap.add_argument("--seconds", type=float, default=180)
    ap.add_argument("--output", default=None)
    ap.add_argument("--seed", type=int, default=9)
    args = ap.parse_args()
    out = args.output or os.path.join(config.LOG_DIR,
                                      f"demo_{args.preset}.mp4")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    record(args.preset, args.seconds, out, args.seed)


if __name__ == "__main__":
    main()
