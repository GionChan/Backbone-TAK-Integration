"""Pluggable object detector for the EFDI edge-AI node.

Backends (env EDGE_DETECTOR):
  mock  (default) - real pixel-based blob detection of the synthetic red target
                    produced by frame_publisher.py. No neural net, no downloads,
                    air-gap friendly. Good enough to prove the pipeline.
  onnx            - YOLO-style ONNX model via onnxruntime. Set EDGE_MODEL to the
                    .onnx path and EDGE_LABELS to a newline label file (COCO by
                    default). This is the drop-in slot for a real model.

Every backend returns list[Detection] with pixel bboxes (x, y, w, h).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Detection:
    label: str
    conf: float
    bbox: tuple[float, float, float, float]  # x, y, w, h  (pixels, top-left origin)

    @property
    def cx(self) -> float:
        return self.bbox[0] + self.bbox[2] / 2.0

    @property
    def cy(self) -> float:
        return self.bbox[1] + self.bbox[3] / 2.0


class MockDetector:
    """Threshold + connected-extent detection of a saturated red object.

    frame_publisher.py draws the target in pure-ish red (R high, G/B low); this
    finds it the same way a cheap CV pipeline would. Confidence scales with how
    much of the frame the blob fills, clamped to a believable range.
    """

    name = "mock-red-blob/1"

    def __init__(self) -> None:
        import numpy as np  # noqa: F401  (import-time check)

        self.min_pixels = int(os.environ.get("EDGE_MOCK_MIN_PIXELS", "40"))
        self.label = os.environ.get("EDGE_MOCK_LABEL", "uav")

    def detect(self, rgb) -> list[Detection]:
        import numpy as np

        r = rgb[:, :, 0].astype(np.int16)
        g = rgb[:, :, 1].astype(np.int16)
        b = rgb[:, :, 2].astype(np.int16)
        mask = (r > 150) & (r - g > 60) & (r - b > 60)
        ys, xs = np.nonzero(mask)
        if xs.size < self.min_pixels:
            return []
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        w, h = (x1 - x0 + 1), (y1 - y0 + 1)
        fill = xs.size / float(max(1, w * h))          # how solid the blob is
        area_frac = xs.size / float(mask.size)
        conf = max(0.35, min(0.985, 0.55 + 1.6 * area_frac + 0.25 * fill))
        return [Detection(self.label, round(conf, 3), (x0, y0, w, h))]


class OnnxYoloDetector:
    """Minimal YOLOv5/8-style ONNX runner (single output, [n,85] or [n,6])."""

    name = "onnx-yolo/1"

    def __init__(self) -> None:
        import numpy as np  # noqa: F401
        import onnxruntime as ort

        model = os.environ["EDGE_MODEL"]
        self.sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name
        _, _, self.ih, self.iw = self.sess.get_inputs()[0].shape
        self.ih = int(self.ih or 640)
        self.iw = int(self.iw or 640)
        self.conf_th = float(os.environ.get("EDGE_CONF", "0.35"))
        lbl = os.environ.get("EDGE_LABELS")
        self.labels = (
            open(lbl).read().splitlines() if lbl and os.path.isfile(lbl) else _COCO
        )

    def detect(self, rgb) -> list[Detection]:
        import numpy as np
        from PIL import Image

        H, W = rgb.shape[:2]
        im = Image.fromarray(rgb).resize((self.iw, self.ih))
        x = np.asarray(im, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self.sess.run(None, {self.inp: x})[0]
        out = np.squeeze(out)
        if out.ndim != 2:
            return []
        # accept [n,6]=(x1,y1,x2,y2,conf,cls) or [n,85]=(cx,cy,w,h,obj,80cls)
        dets: list[Detection] = []
        sx, sy = W / self.iw, H / self.ih
        for row in out:
            if row.shape[0] >= 85:
                cx, cy, bw, bh, obj = row[:5]
                cls = int(np.argmax(row[5:]))
                conf = float(obj * row[5 + cls])
                x0, y0 = (cx - bw / 2), (cy - bh / 2)
            elif row.shape[0] >= 6:
                x0, y0, x2, y2, conf, cls = row[:6]
                bw, bh, cls = (x2 - x0), (y2 - y0), int(cls)
                conf = float(conf)
            else:
                continue
            if conf < self.conf_th:
                continue
            name = self.labels[cls] if 0 <= cls < len(self.labels) else str(cls)
            dets.append(
                Detection(name, round(conf, 3),
                          (float(x0 * sx), float(y0 * sy), float(bw * sx), float(bh * sy)))
            )
        return dets


def load_detector():
    kind = os.environ.get("EDGE_DETECTOR", "mock").lower()
    if kind == "onnx":
        return OnnxYoloDetector()
    return MockDetector()


_COCO = (
    "person bicycle car motorcycle airplane bus train truck boat traffic_light "
    "fire_hydrant stop_sign parking_meter bench bird cat dog horse sheep cow "
    "elephant bear zebra giraffe backpack umbrella handbag tie suitcase frisbee "
    "skis snowboard sports_ball kite baseball_bat baseball_glove skateboard "
    "surfboard tennis_racket bottle wine_glass cup fork knife spoon bowl banana "
    "apple sandwich orange broccoli carrot hot_dog pizza donut cake chair couch "
    "potted_plant bed dining_table toilet tv laptop mouse remote keyboard "
    "cell_phone microwave oven toaster sink refrigerator book clock vase "
    "scissors teddy_bear hair_drier toothbrush"
).split()
