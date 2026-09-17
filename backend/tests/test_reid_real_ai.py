"""Milestone 19 real-AI smoke: TorchReIDProvider embedding on local ResNet18.

Runs the REAL TorchReID model (resnet18 penultimate 512-d) against a
synthetic BGR crop (numpy). No camera, no network, no face data. Proves:

  1. cached ImageNet weights load
  2. encode returns a valid L2-normalised 512-d embedding
  3. encode latency is measurable (no invented thresholds)

Marked `real_ai` (opt-in, slow) so the default suite stays fast. Skipped
when the cached resnet18 weights are absent.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

pytestmark = pytest.mark.real_ai


def _make_crop(size: int = 224) -> np.ndarray:
    """Random BGR crop matching a typical person-crop aspect."""
    rng = np.random.default_rng(42)
    return (rng.random((size, size, 3), dtype=np.float64) * 255).astype(np.uint8)


def _make_provider():
    from app.services.journeys.reid.providers import TorchReIDProvider

    provider = TorchReIDProvider()
    if not provider.available():
        pytest.skip(
            "Torch Re-ID weights not found. Fetch once: "
            'python -c "import torch; torch.hub.load_state_dict_from_url('
            "'https://download.pytorch.org/models/resnet18-f37072fd.pth',"
            ' progress=True)" '
            "or set REID_TORCH_WEIGHTS_PATH."
        )
    return provider


def test_torch_reid_encode_returns_512d_embedding():
    provider = _make_provider()
    crop = _make_crop()
    emb = provider.encode(crop)

    assert emb is not None
    assert len(emb.values) == 512
    assert emb.provider == "torch"

    norm = sum(v * v for v in emb.values) ** 0.5
    assert 0.999 <= norm <= 1.001, f"Embedding not L2-normalised: norm={norm}"


def test_torch_reid_encode_latency():
    provider = _make_provider()
    crop = _make_crop()

    # Warm up the lazy-load + first inference path.
    provider.encode(crop)

    t0 = time.perf_counter()
    n = 10
    for _ in range(n):
        emb = provider.encode(crop)
        assert emb is not None and len(emb.values) == 512
    elapsed = time.perf_counter() - t0

    avg_ms = (elapsed / n) * 1000
    print(f"\n  TorchReID average encode latency: {avg_ms:.1f} ms over {n} runs")
    # Assert only a sanity bound — the full pipeline has a 0.5s frame budget.
    assert avg_ms < 5000, f"Torch encode surprisingly slow: {avg_ms:.1f} ms"


def test_stub_reid_encode_baseline():
    """Stub provider as a fast reference for comparison."""
    from app.services.journeys.reid.providers import StubReIDProvider

    stub = StubReIDProvider()
    crop = _make_crop()

    t0 = time.perf_counter()
    n = 100
    for _ in range(n):
        emb = stub.encode(crop)
        assert emb is not None and len(emb.values) == 64
    elapsed = time.perf_counter() - t0

    avg_ms = (elapsed / n) * 1000
    print(f"\n  StubReID average encode latency: {avg_ms:.3f} ms over {n} runs")
