"""Pluggable appearance-embedding providers for anonymous Re-ID (M19).

Contract
--------
* A provider turns ONE person crop (BGR numpy frame region, HxWx3) into a
  L2-normalized `PersonEmbedding`. `encode()` returns None if the provider is
  unavailable or the crop is unusable — the caller degrades gracefully
  (local-only tracking continues).
* NO provider may download weights at runtime. Weights must already exist on
  disk (see docs/m19-anonymous-journeys.md); otherwise `available()` is False
  and a helpful log explains how to fetch them.

Providers
---------
* StubReIDProvider   — deterministic content-hash embedding, for tests/demo.
* TorchReIDProvider  — default real provider: torchvision ResNet18 ImageNet
                       penultimate features (512-d), weights loaded from the
                       local torch hub cache (zero-download, zero new deps).
* OpenVINOReIDProvider— optional: Intel OMZ person-reidentification-retail-0287
                       (256-d, Apache-2.0) loaded from models/reid/. Requires
                       `pip install openvino` + the two weight files.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from .models import PersonEmbedding

logger = logging.getLogger("storeye.journeys.reid.providers")


class PersonReIDModel:
    """Interface every embedding provider implements."""

    name: str = "base"
    dimensions: int = 0

    def available(self) -> bool:
        raise NotImplementedError

    def encode(self, image) -> Optional[PersonEmbedding]:
        raise NotImplementedError

    def encode_crops(self, crops: Sequence) -> List[Optional[PersonEmbedding]]:
        return [self.encode(c) for c in crops]


# ---------------------------------------------------------------------------
# Stub
# ---------------------------------------------------------------------------

def _stub_hash_path(image) -> "np.ndarray":
    """Resample a frame to 8x8x3 via nearest sampling (pure numpy)."""
    import numpy as np

    arr = np.asarray(image)
    if arr.size == 0:
        return np.zeros((8, 8, 3), dtype=np.float64)
    if arr.ndim == 2:
        arr = arr[..., None]
    arr = arr[..., :3].astype(np.float64)
    h, w = arr.shape[:2]
    if h == 0 or w == 0:
        return np.zeros((8, 8, 3), dtype=np.float64)
    ys = (np.arange(8) * h / 8).astype(int)
    xs = (np.arange(8) * w / 8).astype(int)
    return arr[np.ix_(ys, xs, np.arange(3))]


class StubReIDProvider(PersonReIDModel):
    """Deterministic embedding for tests/demos.

    Identical crops produce identical embeddings (cosine 1.0); different crops
    produce near-orthogonal ones. NEVER use for production identity matching.
    """

    name = "stub"
    dimensions = 64

    def __init__(self, dimensions: int = 64):
        self.dimensions = int(dimensions)

    def available(self) -> bool:
        return True

    def encode(self, image) -> Optional[PersonEmbedding]:
        import numpy as np

        small = _stub_hash_path(image)
        quantized = np.clip(np.rint(small * 4.0), 0, 255).astype(np.uint8)
        digest = hashlib.sha256(quantized.tobytes()).hexdigest()
        seed = int(digest[:16], 16)
        rng = np.random.default_rng(seed)
        vec = rng.normal(size=self.dimensions).astype(np.float64)
        norm = np.linalg.norm(vec)
        if norm <= 1e-9:
            return None
        return PersonEmbedding((vec / norm).tolist(), provider=self.name)


# ---------------------------------------------------------------------------
# Torch (default)
# ---------------------------------------------------------------------------

def _default_torch_weights() -> Path:
    """Official torchvision cache location; env can override."""
    env = os.getenv("REID_TORCH_WEIGHTS_PATH")
    if env:
        return Path(env)
    return Path.home() / ".cache/torch/hub/checkpoints/resnet18-f37072fd.pth"


def _l2_normalize(values) -> List[float]:
    import numpy as np

    vec = np.asarray(values, dtype=np.float64).reshape(-1)
    norm = float(np.linalg.norm(vec))
    if norm <= 1e-9:
        return []
    return (vec / norm).tolist()


class TorchReIDProvider(PersonReIDModel):
    """ResNet18 RGB-penultimate features (512-d) from cached ImageNet weights.

    BSD-3 ImageNet weights, zero new dependencies. The weights file must
    already be present (torch's normal download cache or REID_TORCH_WEIGHTS_PATH);
    this provider NEVER initiates a download, so it degrades to
    `available() == False` on machines without the cached file.
    """

    name = "torch"
    dimensions = 512

    def __init__(self, weights_path: Optional[Path] = None, image_size: int = 224):
        self.weights_path = Path(weights_path) if weights_path else _default_torch_weights()
        self.image_size = int(image_size)
        self._model = None
        self._transform = None

    def available(self) -> bool:
        return self.weights_path.is_file()

    def _lazy_load(self) -> bool:
        if self._model is not None:
            return True
        if not self.available():
            logger.warning(
                "Torch Re-ID provider unavailable: weights not found at %s. "
                "Fetch once with `python -c \"import torch; print(torch.hub.load_state_dict_from_url("
                "'https://download.pytorch.org/models/resnet18-f37072fd.pth', progress=True))\"` "
                "or set REID_TORCH_WEIGHTS_PATH.",
                self.weights_path,
            )
            return False
        try:
            import torch  # noqa: F401
            import torchvision
            import torch.nn as nn

            model = torchvision.models.resnet18(weights=None)
            model.fc = nn.Identity()  # expose the pooled 512-d penultimate features
            state = torch.load(str(self.weights_path), map_location="cpu")
            if isinstance(state, dict) and "model" in state:
                state = state["model"]
            model.load_state_dict(state, strict=False)
            model.eval()
            self._model = model
            return True
        except Exception:  # pragma: no cover - defensive (never crash inference)
            logger.exception("Failed to initialise torch Re-ID provider")
            return False

    def encode(self, image) -> Optional[PersonEmbedding]:
        if not self._lazy_load():
            return None
        try:
            import cv2
            import torch

            if image is None or getattr(image, "size", 0) == 0:
                return None
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(rgb, (self.image_size, self.image_size)) / 255.0
            tensor = (
                torch.from_numpy(resized)
                .permute(2, 0, 1)
                .unsqueeze(0)
                .float()
            )
            with torch.no_grad():
                features = self._model(tensor).reshape(-1)
            vec = _l2_normalize(features.numpy())
            if not vec:
                return None
            return PersonEmbedding(vec, provider=self.name)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Torch Re-ID encode failed")
            return None


# ---------------------------------------------------------------------------
# OpenVINO (optional)
# ---------------------------------------------------------------------------

def _default_ov_model() -> Path:
    env = os.getenv("REID_OV_MODEL_PATH")
    if env:
        return Path(env)
    # Repo-root models/reid (sibling of backend/).
    return Path(__file__).resolve().parents[4] / "models" / "reid" / "person-reidentification-retail-0287.xml"


class OpenVINOReIDProvider(PersonReIDModel):
    """Intel OMZ person-reidentification-retail-0287 (256-d, Apache-2.0).

    OpenAI LoopNet-style compact model: Market-1501 mAP 76.6% / top-1 92.9%.
    Requires `openvino` installed AND models/reid/person-reidentification-
    retail-0287.{xml,bin} present. Neither is a hard dependency: without them
    this provider reports unavailable and the system uses the torch provider
    (or disabled Re-ID).
    """

    name = "openvino-0287"
    dimensions = 256

    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = Path(model_path) if model_path else _default_ov_model()
        self._core = None
        self._compiled = None
        self._size = 256

    @property
    def _expected_bin(self) -> Path:
        return self.model_path.with_suffix(".bin")

    def available(self) -> bool:
        if not (self.model_path.is_file() and self._expected_bin.is_file()):
            return False
        try:
            import openvino  # noqa: F401
            return True
        except ImportError:
            return False

    def _lazy_load(self) -> bool:
        if self._compiled is not None:
            return True
        if not self.available():
            return False
        try:
            import openvino as ov
            import numpy as _np  # noqa: F401

            self._core = ov.Core()
            model = self._core.read_model(str(self.model_path))
            self._compiled = self._core.compile_model(model, "CPU")
            return True
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to initialise OpenVINO Re-ID provider")
            return False

    def encode(self, image) -> Optional[PersonEmbedding]:
        if not self._lazy_load():
            return None
        try:
            import cv2
            import numpy as np

            if image is None or getattr(image, "size", 0) == 0:
                return None
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(rgb, (self._size, self._size)).astype(np.float32) / 255.0
            # NCHW
            blob = resized.transpose(2, 0, 1)[None, ...]
            outputs = self._compiled([blob])
            result = list(outputs.values())[0]
            vec = _l2_normalize(np.asarray(result).reshape(-1))
            if not vec:
                return None
            return PersonEmbedding(vec, provider=self.name)
        except Exception:  # pragma: no cover - defensive
            logger.exception("OpenVINO Re-ID encode failed")
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY = {
    "stub": StubReIDProvider,
    "torch": TorchReIDProvider,
    "openvino": OpenVINOReIDProvider,
}


def build_reid_provider(name: str) -> PersonReIDModel:
    """Instantiate a provider by its configured name."""
    key = str(name or "").lower().strip()
    if key not in _PROVIDER_REGISTRY:
        raise ValueError(
            f"unknown REID_PROVIDER {name!r}; expected one of {sorted(_PROVIDER_REGISTRY)}"
        )
    provider = _PROVIDER_REGISTRY[key]()
    logger.info(
        "Re-ID provider %s ready (available=%s, dims=%s)",
        provider.name,
        provider.available(),
        provider.dimensions,
    )
    return provider