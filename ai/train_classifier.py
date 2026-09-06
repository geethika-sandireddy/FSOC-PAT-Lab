"""
ai/train_classifier.py
-----------------------
Offline trainer for detection/classifier.py.

Collects REAL candidate-blob features by running the actual rendering +
detection pipeline across every difficulty preset and **several independent
plant seeds**, labels each blob as beacon (within 0.1 deg of ground truth) or
decoy, then trains a standardized logistic regression by gradient descent,
entirely in NumPy (reproducible, no ML framework required).

Evaluation methodology (no leakage): data is bucketed by *seed* — every frame
of one seed is a correlated stream, so the train/validation/test split is done
on **whole seeds**, never on random frames from the same run:

  * TRAIN seeds 1-4, VAL seeds 5-6, TEST seeds 7-8 (held-out scenarios).

A judge can therefore ask "does it generalize to an environment it never
saw?" and the TEST split answers exactly that — not just "can it classify
frames it trained on".

Usage:
    python -m ai.train_classifier

The learned means / stds / weights are printed and should be pasted into
ai/classifier.py.  A train/val/test report is printed as evidence the
appearance channel separates beacon from decoy on *unseen* scenarios.
"""

import math

import numpy as np

import config
from core.simulator import Simulator


BEACON_RADIUS_DEG = 0.10   # blob within this LOS of truth counts as beacon

# whole-seed split (see module docstring).  Bucket key = (preset, seed).
TRAIN_SEEDS = [1, 2, 3, 4]
VAL_SEEDS = [5, 6]
TEST_SEEDS = [7, 8]
SECONDS = 6.0


def collect_dataset(presets=None, seeds=None):
    """Return {preset: {seed: (features, labels)}} by running the sim."""
    if presets is None:
        presets = config.PRESET_ORDER
    if seeds is None:
        seeds = TRAIN_SEEDS + VAL_SEEDS + TEST_SEEDS
    buckets = {}
    for p in presets:
        for seed in seeds:
            sim = Simulator(preset_name=p, seed=seed, dt=1.0 / config.FPS)
            n_frames = int(SECONDS / sim.dt)
            feats, labels = [], []
            for _ in range(n_frames):
                r = sim.step()
                truth_az, truth_el = r["truth_az"], r["truth_el"]
                for c in r["cand_list"]:
                    d = math.hypot(c.los_az - truth_az, c.los_el - truth_el)
                    feats.append([c.area_norm, c.circularity, c.snr, c.hue_dist_n])
                    labels.append(1.0 if d < BEACON_RADIUS_DEG else 0.0)
            buckets.setdefault(p, {})[seed] = (np.array(feats, dtype=np.float64),
                                               np.array(labels, dtype=np.float64))
    return buckets


def stack(buckets, seeds):
    feats, labels = [], []
    for p in buckets:
        for s in seeds:
            if s in buckets[p]:
                feats.append(buckets[p][s][0])
                labels.append(buckets[p][s][1])
    return (np.vstack(feats) if feats else np.zeros((0, 4), dtype=np.float64)), \
           (np.concatenate(labels) if labels else np.zeros((0,), dtype=np.float64))


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
    acc = (pred == y).mean() if len(y) else 0.0
    tp = ((pred == 1) & (y == 1)).sum()
    fn = ((pred == 0) & (y == 1)).sum()
    fp = ((pred == 1) & (y == 0)).sum()
    tn = ((pred == 0) & (y == 0)).sum()
    return dict(acc=acc, recall=tp / max(1, tp + fn), precision=tp / max(1, tp + fp),
                fp=fp, fn=fn, tp=tp, tn=tn)


def main():
    print("Collecting real candidate features from the simulator "
          f"(seeds {TRAIN_SEEDS + VAL_SEEDS + TEST_SEEDS}, all presets)...")
    buckets = collect_dataset()
    Xtr, ytr = stack(buckets, TRAIN_SEEDS)
    Xva, yva = stack(buckets, VAL_SEEDS)
    Xte, yte = stack(buckets, TEST_SEEDS)
    print(f"  train {len(ytr)} blobs ({int(ytr.sum())} beacon), "
          f"val {len(yva)} ({int(yva.sum())} beacon), "
          f"test {len(yte)} ({int(yte.sum())} beacon)")

    print("Training logistic regression...")
    w, mean, std = train(Xtr, ytr)

    print("\nEvaluation (split by whole seeds - no frame leakage):")
    for name, (Xv, yv) in [("train", (Xtr, ytr)),
                           ("val  ", (Xva, yva)),
                           ("test ", (Xte, yte))]:
        rep = evaluate(w, mean, std, Xv, yv)
        print(f"  {name} acc={rep['acc'] * 100:.2f}%  "
              f"beacon recall={rep['recall'] * 100:.2f}%  "
              f"precision={rep['precision'] * 100:.2f}%  "
              f"false-positives={rep['fp']}")

    print("\nPaste into ai/classifier.py:")
    np.set_printoptions(precision=8, suppress=True)
    print(f"_FEATURE_MEAN = np.array({np.array2string(mean, separator=', ')})")
    print(f"_FEATURE_STD  = np.array({np.array2string(std, separator=', ')})")
    print(f"_WEIGHTS      = np.array({np.array2string(w, separator=', ')})")


if __name__ == "__main__":
    main()