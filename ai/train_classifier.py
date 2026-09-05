"""
ai/train_classifier.py
----------------------
Offline trainer for detection/classifier.py.

Collects REAL candidate-blob features by running the actual rendering +
detection pipeline across every difficulty preset (several seeds), labels
each blob as beacon (within 0.1 deg of ground truth) or decoy, then trains
a standardized logistic regression by gradient descent, entirely in NumPy
(reproducible, no ML framework required).

Usage:
    python -m ai.train_classifier

The learned means / stds / weights are printed and should be pasted into
ai/classifier.py.  A training-accuracy report is printed as evidence the
appearance channel genuinely separates beacon from decoy.
"""

import math

import numpy as np

import config
from core.simulator import Simulator


BEACON_RADIUS_DEG = 0.10   # blob within this LOS of truth counts as beacon


def collect_real_dataset(presets=None, seed=2026, seconds=8.0):
    """Run the sim end-to-end and record (features, is_beacon) per blob."""
    if presets is None:
        presets = config.PRESET_ORDER
    feats, labels = [], []
    for p in presets:
        sim = Simulator(preset_name=p, seed=seed, dt=1.0 / config.FPS)
        n_frames = int(seconds / sim.dt)
        for _ in range(n_frames):
            r = sim.step()
            truth_az, truth_el = r["truth_az"], r["truth_el"]
            for c in r["cand_list"]:
                d = math.hypot(c.los_az - truth_az, c.los_el - truth_el)
                feats.append([c.area_norm, c.circularity, c.snr, c.hue_dist_n])
                labels.append(1.0 if d < BEACON_RADIUS_DEG else 0.0)
    return np.array(feats, dtype=np.float64), np.array(labels, dtype=np.float64)


def standardize(X):
    mean = X.mean(axis=0)
    std = X.std(axis=0) + 1e-9
    return (X - mean) / std, mean, std


def train(X, y, iters=6000, lr=0.5):
    """Gradient-descent logistic regression on standardized features."""
    Xs, mean, std = standardize(X)
    Xs = np.column_stack([np.ones(len(Xs)), Xs])
    w = np.zeros(Xs.shape[1])
    n = len(y)
    for it in range(iters):
        z = Xs @ w
        p = 1.0 / (1.0 + np.exp(-z))
        grad = Xs.T @ (p - y) / n
        w -= lr * grad
        if it % 1000 == 0:
            loss = -np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9))
            print(f"  iter {it:5d} loss {loss:.4f}")
    return w, mean, std


def evaluate(w, mean, std, X, y):
    Xs = (X - mean) / std
    Xs = np.column_stack([np.ones(len(Xs)), Xs])
    p = 1.0 / (1.0 + np.exp(-(Xs @ w)))
    pred = p >= 0.5
    acc = (pred == y).mean()
    tp = ((pred == 1) & (y == 1)).sum()
    fn = ((pred == 0) & (y == 1)).sum()
    fp = ((pred == 1) & (y == 0)).sum()
    tn = ((pred == 0) & (y == 0)).sum()
    return dict(acc=acc, recall=tp / max(1, tp + fn), precision=tp / max(1, tp + fp),
                fp=fp, fn=fn, tp=tp, tn=tn)


def main():
    print("Collecting real candidate features from the simulator (all presets)...")
    X, y = collect_real_dataset()
    print(f"  collected {len(y)} blobs ({int(y.sum())} beacon, "
          f"{int((1 - y).sum())} decoy)")

    iidx = np.random.default_rng(1).permutation(len(y))
    split = int(0.8 * len(y))
    Xtr, ytr = X[iidx[:split]], y[iidx[:split]]
    Xte, yte = X[iidx[split:]], y[iidx[split:]]

    print("Training logistic regression...")
    w, mean, std = train(Xtr, ytr)

    print("\nValidation report:")
    for name, (Xv, yv) in [("train", (Xtr, ytr)), ("val", (Xte, yte))]:
        rep = evaluate(w, mean, std, Xv, yv)
        print(f"  {name:6s} acc={rep['acc']*100:.2f}%  "
              f"beacon recall={rep['recall']*100:.2f}%  "
              f"precision={rep['precision']*100:.2f}%  "
              f"false-positives={rep['fp']}")

    print("\nPaste into ai/classifier.py:")
    np.set_printoptions(precision=8, suppress=True)
    print(f"_FEATURE_MEAN = np.array({np.array2string(mean, separator=', ')})")
    print(f"_FEATURE_STD  = np.array({np.array2string(std, separator=', ')})")
    print(f"_WEIGHTS      = np.array({np.array2string(w, separator=', ')})")


if __name__ == "__main__":
    main()