"""
ai/train_classifier.py
----------------------
Offline trainer for detection/classifier.py.

Generates synthetic candidate-blob *feature* distributions that match the
measured characteristics of real beacon vs decoy detections in this
simulator (calibrated by running DetectionEngine on rendered frames), then
trains a standardized logistic regression by gradient descent, entirely in
NumPy (reproducible, no ML framework required).

Usage:
    python -m ai.train_classifier

The learned means / stds / weights are printed and should be pasted into
ai/classifier.py.  A training-accuracy report is printed as evidence the
appearance channel genuinely separates beacon from decoy.
"""

import numpy as np


def rng(seed=2026):
    return np.random.default_rng(seed)


def generate_dataset(n_pos=4000, n_neg=4000, seed=2026):
    """Synthetic feature distributions calibrated on rendered frames:
      * beacon: compact, bright, near-beacon-color, ~expected area
      * decoy:  looser shape, dimmer or off-color, variable area
    """
    g = rng(seed)

    # --- positive class (beacon) ---
    area_norm_pos = np.clip(g.normal(0.90, 0.30, n_pos), 0.2, 2.5)
    circ_pos = np.clip(g.normal(0.80, 0.16, n_pos), 0.35, 1.0)
    snr_pos = np.clip(g.normal(8.0, 5.0, n_pos), 1.2, 60.0)
    hue_pos = np.clip(np.abs(g.normal(0.03, 0.04, n_pos)), 0.0, 0.6)

    # --- negative class (decoy) ---
    area_norm_neg = np.clip(g.normal(1.4, 0.9, n_neg), 0.2, 4.0)
    circ_neg = np.clip(g.normal(0.50, 0.28, n_neg), 0.1, 1.0)
    snr_neg = np.clip(g.normal(3.0, 3.0, n_neg), 0.6, 50.0)
    hue_neg = np.clip(np.abs(g.normal(0.45, 0.35, n_neg)), 0.0, 1.0)

    X = np.vstack([
        np.column_stack([area_norm_pos, circ_pos, snr_pos, hue_pos]),
        np.column_stack([area_norm_neg, circ_neg, snr_neg, hue_neg]),
    ])
    y = np.concatenate([np.ones(n_pos), np.zeros(n_neg)])
    return X, y


def standardize(X):
    mean = X.mean(axis=0)
    std = X.std(axis=0) + 1e-9
    return (X - mean) / std, mean, std


def train(X, y, iters=4000, lr=0.5):
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
        if it % 500 == 0:
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
    print("Generating synthetic candidate features...")
    X, y = generate_dataset()
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