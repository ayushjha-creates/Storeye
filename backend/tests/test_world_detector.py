"""M32: open-vocabulary product detection (YOLO-World) unit tests.

No real model runs here: `ultralytics.YOLOWorld` is replaced by a stub so the
prompt-encoding and result-parsing paths stay deterministic and CI-friendly.
A separate `real_ai` test can exercise the actual weights on a machine that
has `models/shelf/yolov8s-worldv2.pt` + `backend/weights/clip/ViT-B-32.pt`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services.vision.world_detector import (
    WorldProductDetector,
    _clean_prompts,
)

pytestmark = [pytest.mark.no_db]


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------
class _Arr:
    def __init__(self, values):
        self._values = np.asarray(values)

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class _Boxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = _Arr(xyxy)
        self.conf = _Arr(conf)
        self.cls = _Arr(cls)

    def __len__(self):
        return len(self._values_len())

    def _values_len(self):
        return self.xyxy.numpy()


class _Result:
    def __init__(self, boxes, names):
        self.boxes = boxes
        self.names = names


class _FakeWorld:
    def __init__(self, results=None):
        self.names = {0: "default"}
        self.task = "detect"
        self.set_calls = []
        self.predict_calls = 0
        self._results = results or []

    def set_classes(self, classes):
        self.set_calls.append(list(classes))
        self.names = {i: c for i, c in enumerate(classes)}

    def predict(self, **kwargs):
        self.predict_calls += 1
        return self._results


def _bare_detector(model=None) -> WorldProductDetector:
    det = object.__new__(WorldProductDetector)
    det.model_path = Path("nonexistent.pt")
    det.device = "cpu"
    det._model = model if model is not None else _FakeWorld()
    det._prompts = []
    det._names = {}
    return det


def _result(boxes, names):
    return [_Result(_Boxes(**boxes), names)]


# ---------------------------------------------------------------------------
# Prompt handling
# ---------------------------------------------------------------------------
def test_clean_prompts_strips_and_dedupes_case_insensitively():
    assert _clean_prompts([" Biscuit ", "biscuit", "", None, "Milk"]) == [
        "Biscuit",
        "Milk",
    ]
    assert _clean_prompts(None) == []
    assert _clean_prompts("not-a-list") == []


def test_set_prompts_encodes_into_model_and_keeps_names():
    det = _bare_detector()
    det.set_prompts(["biscuit packet", "milk carton"])
    assert det.prompts == ["biscuit packet", "milk carton"]
    assert det._model.set_calls == [["biscuit packet", "milk carton"]]
    assert det.class_names == {0: "biscuit packet", 1: "milk carton"}


def test_set_prompts_empty_clears_without_calling_model():
    det = _bare_detector()
    det.set_prompts(["biscuit packet"])
    det.set_prompts([])
    assert det.prompts == []
    assert det._model.set_calls == [["biscuit packet"]]


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------
def test_detect_without_prompts_is_a_noop():
    det = _bare_detector()
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    result = det.detect(frame)
    assert result.detections == []
    assert det._model.predict_calls == 0


def test_detect_parses_pixels_into_detections():
    fake = _FakeWorld(
        results=_result(
            boxes=dict(
                xyxy=[[1, 2, 30, 40], [5, 6, 20, 25]],
                conf=[0.9, 0.4],
                cls=[0, 1],
            ),
            names={0: "biscuit packet", 1: "milk carton"},
        )
    )
    det = _bare_detector(model=fake)
    det.set_prompts(["biscuit packet", "milk carton"])
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    result = det.detect(frame, conf=0.25)
    assert [d.class_name for d in result.detections] == [
        "biscuit packet",
        "milk carton",
    ]
    assert result.detections[0].bbox_xyxy == [1.0, 2.0, 30.0, 40.0]
    assert result.detections[1].confidence == pytest.approx(0.4)


def test_detect_rejects_frameless_input():
    det = _bare_detector()
    det.set_prompts(["biscuit packet"])
    assert det.detect(None).detections == []


# ---------------------------------------------------------------------------
# Edge adapter
# ---------------------------------------------------------------------------
class _StubDetector:
    def __init__(self, model_path=None):
        self._model = object()
        self.model_path = model_path
        self.prompt_calls = []

    def set_prompts(self, prompts):
        self.prompt_calls.append(list(prompts))

    def detect(self, frame, conf=0.25):
        from app.services.vision.shelf_detector import Detection, DetectionResult

        return DetectionResult(
            img_shape=[10, 10],
            detections=[
                Detection(
                    class_id=0,
                    class_name="biscuit packet",
                    confidence=0.8,
                    bbox_xyxy=[1, 2, 3, 4],
                )
            ],
        )


def test_world_product_detector_model_maps_frame_results(monkeypatch):
    import app.services.vision.world_detector as wd

    monkeypatch.setattr(wd, "WorldProductDetector", _StubDetector)
    from app.edge.models.product_detector import WorldProductDetectorModel

    model = WorldProductDetectorModel(prompts=["biscuit packet"])
    assert model.initialized
    assert model.prompts == ["biscuit packet"]
    out = model.detect_frame(np.zeros((10, 10, 3), dtype=np.uint8))
    assert len(out) == 1
    assert out[0].class_name == "biscuit packet"
    assert out[0].bbox_xyxy == [1, 2, 3, 4]


def test_world_product_detector_model_empty_prompts_noops(monkeypatch):
    import app.services.vision.world_detector as wd

    monkeypatch.setattr(wd, "WorldProductDetector", _StubDetector)
    from app.edge.models.product_detector import WorldProductDetectorModel

    model = WorldProductDetectorModel(prompts=[])
    assert model.detect_frame(np.zeros((10, 10, 3), dtype=np.uint8)) == []
    model.set_prompts(["soap bar"])
    assert model.prompts == ["soap bar"]


# ---------------------------------------------------------------------------
# Registry selection
# ---------------------------------------------------------------------------
def test_registry_new_product_detector_selects_world_and_shelf(monkeypatch):
    import app.edge.models.product_detector as pd

    class _Sentinel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(pd, "WorldProductDetectorModel", _Sentinel)
    monkeypatch.setattr(pd, "ProductDetectorModel", _Sentinel)
    from app.edge.models.registry import ModelRegistry

    reg = ModelRegistry()
    world = reg.new_product_detector(
        detector="world", prompts=["biscuit packet"], conf=0.3
    )
    assert world.kwargs["prompts"] == ["biscuit packet"]
    assert world.kwargs["conf"] == 0.3
    # Same vocabulary -> one shared instance (bounded memory).
    assert reg.new_product_detector(detector="world", prompts=["biscuit packet"]) is world
    # Different vocabulary -> a separate instance.
    assert reg.new_product_detector(detector="world", prompts=["soap bar"]) is not world
    shelf = reg.new_product_detector(detector="shelf", conf=0.1)
    assert shelf.kwargs["conf"] == 0.1


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
def test_pipeline_config_rejects_unknown_product_detector():
    from app.edge.config import PipelineConfig

    with pytest.raises(ValueError):
        PipelineConfig(product_detector="bogus").validate()


def test_pipeline_config_defaults_to_world_with_no_prompts():
    from app.edge.config import PipelineConfig

    cfg = PipelineConfig()
    assert cfg.product_detector == "world"
    assert cfg.product_prompts == []
