# BUG-0833 — the deployed egg classifier is a structurally invalid ONNX, so egg_quality never runs

**Found** 2026-10-22 (owner, on `vpt-lenovo1`) · **Status** fixed · **Area** monitor / `egg_quality`

## What happened

Device 3 of `vpt-lenovo1` is "Synthetic eggs (egg_quality)", an `rtsp_video` device whose
`DEVICE3_VIDEO` is a local MP4 in loop. It has run with `DEVICE3_MONITOR_PROFILE=egg_quality` and
`MONITOR_EGG_MODEL=/var/lib/vpt_user/models/egg_good_bad.onnx` since 2026-10-22. The profile has
**never produced a single frame of output**: `vpt-monitor-img` logged the same error every 10 s,
forever, and the device's metadata folder (`capture3/hot/metadata/`) was **empty**.

```
[ERROR:0@25794.570] global onnx_importer.cpp:1042 handleNode DNN/ONNX: ERROR during processing
node with 2 inputs and 1 outputs: [MatMul]:(onnx_node_output_0!Y) from domain='ai.onnx'
> DNN/MatMul: invalid dimension K (expected: 'K_A == K_B'), where 'K_A' is 32 must be equal to 'K_B' is 2
```

`EggClassify.__init__` calls `cv2.dnn.readNetFromONNX`, which raises, so `PipelineAnalyzer.__init__`
never finishes and the profile is retried from scratch. The device's video played, its card looked
healthy, and there was nothing to show but no egg was ever inspected.

## Why the model is broken

Two separate faults in the same 24 681-byte file:

1. **Wrong input size.** `egg_classify.INPUT` is 64, and `crop_for_model` builds a 64x64 blob. The
   deployed graph declares `input: [1, 3, 32, 32]` — it is the old 32 px model the handover warns
   about (*"the only egg model found is the old 32 px one, the code feeds 64 px"*).
2. **The graph itself does not load**, in any runtime. Not only `cv2.dnn`, but
   `onnxruntime.InferenceSession` refuses it: `Incompatible dimensions for matrix multiplication`.
   Its final layer is a `Linear(32, 2)` exported with the weight transposed, which no runtime
   accepts. Retraining is the only fix; the file cannot be patched into shape.

Reproduced locally, so this is not a host quirk: copying the model off the box and running the
shipped profile over frames fails with the identical traceback.

## The fix

Retrained from the dataset the project already documents — *Good and Bad Eggs Identification Image
Dataset*, Md Mafiul Hasan Matin et al., Mendeley Data V1 2025, DOI 10.17632/mdty358x8m.1,
**CC BY 4.0**, `Original Images(Eggs).zip` 7 652 598 bytes (sha256
`c364a5c175897480b70b7040c3ded533501cccfb4b419e8f7e224c6a26dc1c05`), 500 good + 500 bad candling
shots — with `scripts/train_egg_classifier.py`:

* input `[1, 3, 64, 64]`, opset 12, **96 867 bytes**, sha256
  `4f584800a20f5df6396864334f4d24fec1d28ea75a70ece02f742ac038f17654`
* loads in **both** `cv2.dnn` and `onnxruntime`, `forward()` -> `[1, 2]`
* held-out test split: accuracy **0.985** (good P 0.98 R 1.00, bad P 1.00 R 0.97, 100 each),
  0 images missed by the detector — the same figure TASK-90 §6 recorded for the original model

Deployed to `/var/lib/vpt_user/models/egg_good_bad.onnx` on `vpt-lenovo1`.

**The download was gated** in `HANDOVER-lenovo-fleet-same-config.md` ("download not yet
approved"). The owner approved it on 2026-10-22 with "fix it all"; the licence is CC BY 4.0, the
dataset is login-free, and the data stays in `.local-data/` (git-ignored) as the profile requires.

## Prevention

* `tests/backend_host/test_egg_quality.py::test_real_model_loads_and_answers` already runs this check,
  but only when `MONITOR_EGG_MODEL` is set — it is skipped in CI, which is how a broken model reached a host.
* The profile now loads and runs end to end on `vpt-lenovo1`: `capture3/hot/metadata/` fills with
  per-frame JSON, and `ProfileOverlay` draws the eggs (see BUG-0834).