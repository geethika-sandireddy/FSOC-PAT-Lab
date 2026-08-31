"""
ai/classifier.py
----------------
The explainable "AI" component: a 4-input logistic-regression classification
of whether a detected blob is the true FSOC beacon vs a decoy, based purely
on appearance:

    features = [area_norm, circularity, snr, hue_dist_n]

* area_norm    - blob area relative to the beacon's expected footprint
* circularity  - compactness (4*pi*area / perimeter^2), robust to warp
* snr          - peak intensity over local background (brightness contrast)
* hue_dist_n   - circular hue distance from the known beacon hue

The weights are produced offline by ai/train_classifier.py on synthetic
candidate-feature distributions (see that file for the exact generative
model + training method).  Logistic regression is chosen deliberately:
it runs in microseconds per frame, is fully interpretable line-by-line in
the technical report, and provides calibrated probabilities for the sensor
fusion stage.  Swap for a CNN without touching any other module.
"""

import numpy as np

# Learned parameters (see ai/train_classifier.py) - refreshed by running it.
_FEATURE_MEAN = np.array([1.17591991, 0.6511591, 5.72471713, 0.25292002])
_FEATURE_STD = np.array([0.69355799, 0.2498922, 4.41623934, 0.29196224])
_WEIGHTS = np.array([-4.16831474, -1.16525745, 1.80856165, 1.3297355, -8.37318269])


def score_features(features):
    """Logistic-regression probability that a blob is the true beacon."""
    x = np.asarray(features, dtype=np.float64)
    xs = (x - _FEATURE_MEAN) / _FEATURE_STD
    xb = np.concatenate([[1.0], xs])
    z = float(_WEIGHTS @ xb)
    return 1.0 / (1.0 + np.exp(-z))