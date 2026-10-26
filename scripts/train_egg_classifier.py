#!/usr/bin/env python3
"""Train the small egg classifier used by the `egg_quality` profile (TASK-90 goal 9), locally, from a folder-per-class dataset.

    python3 scripts/train_egg_classifier.py --data ".local-data/eggs/mendeley1/orig/Original Images(Eggs)" \
        --classes "Good Eggs=good" "Bad Eggs=bad" --out .local-data/eggs/models/egg_good_bad.onnx

Tooling: PyTorch (BSD-3), onnx (Apache-2.0, only for the export; with numpy 1.x use onnx 1.16, newer ones pull numpy 2) and OpenCV (Apache-2.0). Crops come from the same `egg_detect` the monitor runs, through the
same `crop_for_model`, so training and running see the same pixels. The split is by file, seeded, stratified: 70 % train,
10 % validation, 20 % test; the test images are never used to pick anything. Writes `<out>` (ONNX with softmax) and
`<out>.metrics.json` (per-class precision/recall on the test split, misses of the detector counted as errors) and
`<out>.split.json` (which files are test, so a synthetic conveyor can be built from held-out images only).
"""
import argparse
import glob
import json
import os
import random
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path[:0] = [os.path.join(ROOT, 'backend_host', 'scripts'), ROOT]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', required=True)
    ap.add_argument('--classes', nargs='+', required=True, help='"folder name=class" pairs, in the order of the model outputs')
    ap.add_argument('--out', required=True)
    ap.add_argument('--epochs', type=int, default=40)
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()

    import torch
    import torch.nn as nn
    from monitor.analyzers.egg_classify import INPUT, crop_for_model
    from monitor.analyzers.egg_detect import EggDetect

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    pairs = [p.split('=') for p in args.classes]
    classes = [c for _, c in pairs]
    # the dataset IS candling shots (a bright egg on black), so the crops are cut with the `brightness` detector
    # even when the profile runs `blob` on live footage: the detector only proposes the box, `crop_for_model` (shared
    # with the monitor) decides the pixels the model sees. With `blob` here it misses 91-97 %% of these images.
    det = EggDetect()

    files = {}
    for folder, cls in pairs:
        fs = sorted(glob.glob(os.path.join(args.data, folder, '*.jpg')) + glob.glob(os.path.join(args.data, folder, '*.png')))
        random.Random(args.seed).shuffle(fs)
        n = len(fs)
        files[cls] = {'train': fs[:int(.7 * n)], 'val': fs[int(.7 * n):int(.8 * n)], 'test': fs[int(.8 * n):]}

    def crop_of(path):
        img = cv2.imread(path)
        ds = det.detect(img)
        if not ds:
            return None
        d = max(ds, key=lambda d: d.bbox[2] * d.bbox[3])
        return crop_for_model(img, d.bbox)

    data = {}
    misses = {}
    for split in ('train', 'val', 'test'):
        X, y = [], []
        for ci, cls in enumerate(classes):
            for p in files[cls][split]:
                c = crop_of(p)
                if c is None:
                    misses[(split, cls)] = misses.get((split, cls), 0) + 1
                    continue
                X.append(c)
                y.append(ci)
        data[split] = (np.array(X), np.array(y))
    print({k: len(v[1]) for k, v in data.items()}, 'detector misses', {f'{a}/{b}': n for (a, b), n in misses.items()})

    def tensor(X):
        return torch.from_numpy(X[..., ::-1].copy()).permute(0, 3, 1, 2).float() / 255.0     # BGR -> RGB, like swapRB in cv2.dnn

    def aug(X):
        out = []
        for im in X:
            if random.random() < 0.5:
                im = im[:, ::-1]
            a = random.uniform(-15, 15)
            s = random.uniform(0.9, 1.1)
            M = cv2.getRotationMatrix2D((INPUT / 2, INPUT / 2), a, s)
            out.append(cv2.warpAffine(np.ascontiguousarray(im), M, (INPUT, INPUT)))
        return np.array(out)

    net = nn.Sequential(
        nn.Conv2d(3, 16, 3, padding=1), nn.BatchNorm2d(16), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(16, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
        nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(64, len(classes)))
    opt = torch.optim.Adam(net.parameters(), 2e-3)
    loss_fn = nn.CrossEntropyLoss()
    Xtr, ytr = data['train']
    Xva, yva = data['val']
    best, best_state = -1, None
    for ep in range(args.epochs):
        net.train()
        idx = np.random.permutation(len(Xtr))
        for i in range(0, len(idx), 32):
            b = idx[i:i + 32]
            opt.zero_grad()
            loss = loss_fn(net(tensor(aug(Xtr[b]))), torch.from_numpy(ytr[b]))
            loss.backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            acc = (net(tensor(Xva)).argmax(1).numpy() == yva).mean()
        if acc >= best:
            best, best_state = acc, {k: v.clone() for k, v in net.state_dict().items()}
        if ep % 10 == 9:
            print(f'epoch {ep + 1} val acc {acc:.3f}')
    net.load_state_dict(best_state)
    net.eval()

    class WithSoftmax(nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, x):
            return torch.softmax(self.m(x), dim=1)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    torch.onnx.export(WithSoftmax(net), torch.zeros(1, 3, INPUT, INPUT), args.out, opset_version=12,
                      input_names=['input'], output_names=['probs'])      # needs `pip install onnx` (Apache-2.0)

    # test through the code the monitor runs (egg_detect + EggClassify on cv2.dnn), not through torch
    from monitor.analyzers.egg_classify import EggClassify
    clf = EggClassify(classes, model_path=args.out)
    conf = np.zeros((len(classes), len(classes) + 1), int)       # rows: truth; columns: predicted classes + "not detected"
    for ci, cls in enumerate(classes):
        for p in files[cls]['test']:
            img = cv2.imread(p)
            ds = det.detect(img)
            if not ds:
                conf[ci, -1] += 1
                continue
            d = max(ds, key=lambda d: d.bbox[2] * d.bbox[3])
            label, _ = clf.classify_det(img, d)
            conf[ci, classes.index(label)] += 1
    metrics = {'classes': classes, 'confusion_rows_truth_cols_pred_plus_missed': conf.tolist(), 'per_class': {}}
    for ci, cls in enumerate(classes):
        tp = conf[ci, ci]
        fp = conf[:, ci].sum() - tp
        support = conf[ci].sum()
        metrics['per_class'][cls] = {'precision': round(float(tp / max(1, tp + fp)), 3), 'recall': round(float(tp / max(1, support)), 3),
                                     'support': int(support), 'missed_by_detector': int(conf[ci, -1])}
    metrics['accuracy'] = round(float(np.trace(conf[:, :len(classes)]) / conf.sum()), 3)
    with open(args.out + '.metrics.json', 'w') as f:
        json.dump(metrics, f, indent=1)
    with open(args.out + '.split.json', 'w') as f:
        json.dump({cls: files[cls] for cls in classes}, f)
    print(json.dumps(metrics, indent=1))


if __name__ == '__main__':
    main()
