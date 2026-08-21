"""Load Caruna helpers/client without importing Home Assistant."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

import pytest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "caruna"
PACKAGE = "caruna_under_test"


def _load(name: str, filename: str):
    spec = spec_from_file_location(
        f"{PACKAGE}.{name}",
        COMPONENT / filename,
        submodule_search_locations=[],
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[f"{PACKAGE}.{name}"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def caruna_modules():
    """const, helpers, and client as a fake package."""
    pkg = types.ModuleType(PACKAGE)
    pkg.__path__ = [str(COMPONENT)]
    sys.modules[PACKAGE] = pkg
    const = _load("const", "const.py")
    helpers = _load("helpers", "helpers.py")
    client = _load("client", "client.py")
    return types.SimpleNamespace(const=const, helpers=helpers, client=client)
