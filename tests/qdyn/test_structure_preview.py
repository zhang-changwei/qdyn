from ase import Atoms

from qdyn.frontend_api import preview as preview_mod
from qdyn.frontend_api import service
from qdyn.frontend_api.preview import (
    build_preview,
    build_preview_from_atoms,
)


def test_build_preview_includes_vasp_content_and_legacy_fields():
    preview = build_preview(
        "\n".join(
            [
                "Si",
                "1.0",
                "3.0 0.0 0.0",
                "0.0 3.0 0.0",
                "0.0 0.0 3.0",
                "Si",
                "2",
                "Direct",
                "0.0 0.0 0.0",
                "0.5 0.5 0.5",
            ]
        ),
        fmt="vasp",
    )

    assert preview.format == "vasp"
    assert preview.content
    assert "Direct" in preview.content
    assert preview.species == ["Si", "Si"]
    assert len(preview.cart_coords) == 2
    assert preview.lattice == [
        [3.0, 0.0, 0.0],
        [0.0, 3.0, 0.0],
        [0.0, 0.0, 3.0],
    ]
    assert preview.pbc == [True, True, True]


def test_enrich_with_layer_constraints_recomputes_content(monkeypatch):
    atoms = Atoms(
        "Si2",
        positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.5]],
        cell=[3.0, 3.0, 3.0],
        pbc=True,
    )
    preview = build_preview_from_atoms(atoms)
    assert preview.constraint_mask is None
    assert "Selective dynamics" not in preview.content

    monkeypatch.setattr(
        preview_mod,
        "_get_constraint_params_for_task",
        lambda task_id: {
            "constraint_layers": "1",
            "layer_direction": "001",
            "total_layers": 2,
        },
    )

    enriched = service._enrich_with_layer_constraints(preview, "task-1")

    assert enriched.constraint_mask == [True, False]
    assert "Selective dynamics" in enriched.content
