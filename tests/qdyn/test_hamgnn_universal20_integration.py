"""Opt-in integration test for the installed universal2.0 checkpoint."""

import os
from pathlib import Path

import pytest

_CHECKPOINT_ENV = "QDYN_TEST_UNIVERSAL20_CHECKPOINT"

if not os.environ.get(_CHECKPOINT_ENV):
    pytest.skip(
        f"Set {_CHECKPOINT_ENV} to run the real checkpoint load probe.",
        allow_module_level=True,
    )

import numpy as np
import torch
from torch_geometric.data import Data

from qdyn.input import HamGNNInputT
from qdyn.ml_tools.hamgnn_wrapper import HamGNNWrapper


def test_real_universal20_checkpoint_strict_loads_on_hamgnn21():
    checkpoint_path = Path(os.environ[_CHECKPOINT_ENV]).expanduser().resolve()
    assert checkpoint_path.is_file()

    wrapper = HamGNNWrapper(
        HamGNNInputT(use_pretrained_model=True, model_name="universal2.0"),
        model_path=str(checkpoint_path),
        device="cpu",
    )

    graph = Data(
        z=torch.tensor([6, 1], dtype=torch.long),
        cell=torch.eye(3, dtype=torch.float32) * 20.0,
        pos=torch.tensor(
            [[0.0, 0.0, 0.0], [1.1, 0.0, 0.0]],
            dtype=torch.float32,
        ),
        node_counts=torch.tensor([2], dtype=torch.long),
        edge_index=torch.tensor([[0, 1], [1, 0]], dtype=torch.long),
        inv_edge_idx=torch.tensor([1, 0], dtype=torch.long),
        nbr_shift=torch.zeros((2, 3), dtype=torch.float32),
        cell_shift=torch.zeros((2, 3), dtype=torch.long),
        hamiltonian=torch.tensor(0.0, dtype=torch.float32),
        overlap=torch.tensor(0.0, dtype=torch.float32),
    )
    prediction = wrapper.predict([graph], batch_size=1)

    assert prediction.shape == (4, 26**2)
    assert prediction.dtype == np.float32
    assert np.isfinite(prediction).all()
