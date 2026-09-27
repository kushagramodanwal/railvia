"""Guards the architectural boundary declared in PROJECT_BRIEF.md section 10.

The claim "real feeds plug in here" is only true while the optimiser depends
on the DataSource interface rather than on the generator. This test fails the
build the moment that stops being true.
"""

from __future__ import annotations

import pathlib

import pytest

from src.adapters import REAL_FEED_ADAPTERS, DataSource, NotYetIntegrated, SyntheticDataSource

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

# Packages that consume planning data and must go through the adapter layer.
DOWNSTREAM_PACKAGES = ("optimiser", "ml", "api", "baseline")


def _imports_generator(path: pathlib.Path) -> bool:
    """True if the file actually imports the generator.

    Matches import statements only — the boundary docs are allowed to name
    the generator in prose.
    """
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith(("import ", "from ")):
            continue
        if "src.generator" in stripped or "from src import generator" in stripped:
            return True
    return False


def test_downstream_never_imports_the_generator():
    offenders = []
    for package in DOWNSTREAM_PACKAGES:
        for path in (SRC / package).rglob("*.py"):
            if _imports_generator(path):
                offenders.append(path.relative_to(SRC).as_posix())
    assert not offenders, (
        "these files import the generator directly, breaking the adapter "
        f"boundary: {offenders}"
    )


def test_only_the_adapter_layer_knows_the_generator():
    """Knowledge of the generator is confined to the adapter layer.

    These are the composition roots: they are allowed to assemble generated
    data. Everything downstream sees only DataSource.
    """
    knowers = sorted(
        p.name for p in (SRC / "adapters").rglob("*.py") if _imports_generator(p)
    )
    assert knowers == ["history.py", "hybrid.py", "synthetic.py"]


def test_synthetic_source_satisfies_the_interface():
    source = SyntheticDataSource()
    assert isinstance(source, DataSource)
    assert source.is_synthetic is True
    assert source.is_connected is True
    assert "SYNTHETIC" in source.describe()


@pytest.mark.parametrize("adapter_cls", REAL_FEED_ADAPTERS)
def test_real_feed_stubs_refuse_to_fake_data(adapter_cls):
    adapter = adapter_cls()
    assert isinstance(adapter, DataSource)
    with pytest.raises(NotYetIntegrated):
        adapter.load()


@pytest.mark.parametrize("adapter_cls", REAL_FEED_ADAPTERS)
def test_unconnected_stubs_never_label_themselves_live(adapter_cls):
    """A stub claiming [LIVE] is exactly the credibility failure section 3 warns about."""
    description = adapter_cls().describe()
    assert "[NOT CONNECTED]" in description
    assert "[LIVE]" not in description


def test_json_round_trip(tmp_path):
    from src.adapters import JSONFileDataSource

    original = SyntheticDataSource().load()
    path = tmp_path / "instance.json"
    path.write_text(original.model_dump_json(indent=2))
    replayed = JSONFileDataSource(str(path)).load()
    assert replayed.model_dump_json() == original.model_dump_json()
