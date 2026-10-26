#!/usr/bin/env python3
"""Minion-bar classifier: is a find_bars 'minion' candidate a real minion bar (vs turret segment / effect / HUD)?
Features: HOG of the 72x16 bar crop (grey) + HSV histogram of the crop + context (fill, bordered, row siblings, distance to Garen,
distance to the screen edge, own/foe colour). Model: standardised linear SVM, binary minion vs not (4-class labels kept for the report).
    train:   python3 elite_bar_classifier.py train <labels_dir> <model.npz>     (split = 'train' rows; report on 'val' rows = other game)
Runtime: load(model) -> predict(img_rgb, cand, ctx) -> True/False. numpy + cv2 only at runtime (weights stored in the npz)."""
import json, os, sys
import cv2, numpy as np

_HOG = cv2.HOGDescriptor((72, 16), (16, 16), (8, 8), (8, 8), 9)

def crop_bar(img, x, by):
    """72x16 RGB crop centred on the bar (pads at the screen edge)."""
    a = np.asarray(img); H, W = a.shape[:2]
    out = np.zeros((16, 72, 3), np.uint8)
    x0, y0 = int(x) - 36, int(by) - 8
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + 72), min(H, y0 + 16)
    if sx1 > sx0 and sy1 > sy0: out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = a[sy0:sy1, sx0:sx1]
    return out

def features(bar_rgb, ctx):
    g = cv2.cvtColor(bar_rgb, cv2.COLOR_RGB2GRAY)
    hog = _HOG.compute(g).flatten()
    hsv = cv2.cvtColor(bar_rgb, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256]).flatten(); hist = hist / (hist.sum() + 1e-6)
    # row profile: real bars have a dark border row above/below and a uniform fill row
    rows = g.mean(axis=1) / 255.0
    c = [ctx["hp_frac"], float(ctx["bordered"]), min(ctx["siblings"], 6) / 6.0, min(ctx["dist_garen"], 1500) / 1500.0,
         min(ctx["hud_edge"], 400) / 400.0, {"own": 1.0, "foe": 0.0}.get(ctx.get("colour"), 0.5)]
    return np.concatenate([hog, hist, rows, np.array(c, np.float32)]).astype(np.float32)

def train(labels_dir, out):
    from sklearn.svm import LinearSVC
    from sklearn.preprocessing import StandardScaler
    C = [json.loads(l) for l in open(os.path.join(labels_dir, "candidates.jsonl"))]
    L = json.load(open(os.path.join(labels_dir, "labels.json")))
    X, Y, S, K = [], [], [], []
    for i, c in enumerate(C):
        lab = L.get(str(i))
        if lab is None: continue
        bar = cv2.cvtColor(cv2.imread(os.path.join(labels_dir, "crops", c["id"] + "_bar.png")), cv2.COLOR_BGR2RGB)
        X.append(features(bar, c)); Y.append(1 if lab == "minion" else 0); S.append(c["split"]); K.append(lab)
    X, Y, S = np.array(X), np.array(Y), np.array(S)
    tr, va = S == "train", S == "val"
    if "--all" in sys.argv: tr = np.ones(len(S), bool)  # final model: every labelled game (threshold chosen by leave-one-game-out CV)
    sc = StandardScaler().fit(X[tr]); best = None
    for Cc in (0.01, 0.03, 0.1, 0.3, 1.0):
        m = LinearSVC(C=Cc, class_weight="balanced", max_iter=20000).fit(sc.transform(X[tr]), Y[tr])
        acc = (m.predict(sc.transform(X[va])) == Y[va]).mean() if va.any() else 0
        print(f"C={Cc}: val acc {acc:.3f}")
        if best is None or acc > best[0]: best = (acc, Cc, m)
    acc, Cc, m = best
    p = m.predict(sc.transform(X[va])); y = Y[va]
    tp, fp, fn, tn = int(((p == 1) & (y == 1)).sum()), int(((p == 1) & (y == 0)).sum()), int(((p == 0) & (y == 1)).sum()), int(((p == 0) & (y == 0)).sum())
    print(f"chosen C={Cc}  val (other game): acc {acc:.3f}  minion precision {tp / max(1, tp + fp):.3f} recall {tp / max(1, tp + fn):.3f}  (tp {tp} fp {fp} fn {fn} tn {tn})")
    np.savez(out, mean=sc.mean_, scale=sc.scale_, w=m.coef_[0], b=m.intercept_[0], C=Cc)
    return acc

class BarClassifier:
    def __init__(self, path):
        z = np.load(path); self.mean, self.scale, self.w, self.b = z["mean"], z["scale"], z["w"], float(z["b"])
    def score(self, img, x, by, ctx):
        f = features(crop_bar(img, x, by), ctx)
        return float(((f - self.mean) / self.scale) @ self.w + self.b)
    def is_minion(self, img, x, by, ctx):
        return self.score(img, x, by, ctx) > 0

if __name__ == "__main__":
    if sys.argv[1] == "train": train(sys.argv[2], sys.argv[3])
