"""Every third-party import must be declared in requirements.txt.

A deployment installs only what the manifest lists. Anything pip-installed
during development and never written down works locally and dies on the
server with ModuleNotFoundError — which is exactly what happened with PyJWT
and supabase, one at a time, on Render.
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Import name -> distribution name, where they differ.
DISTRIBUTION = {
    "jwt": "pyjwt",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
}

LOCAL_PACKAGES = {"src", "tests"}


def third_party_imports(*roots: str) -> set[str]:
    found: set[str] = set()
    for root in roots:
        for path in (ROOT / root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.level == 0:
                        found.add(node.module.split(".")[0])
    return {
        m for m in found
        if m not in sys.stdlib_module_names and m not in LOCAL_PACKAGES
    }


def declared() -> set[str]:
    text = (ROOT / "requirements.txt").read_text()
    names = set()
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        for sep in (">=", "==", "<=", "~=", ">", "<", "["):
            if sep in line:
                line = line.split(sep)[0]
        names.add(line.strip().lower())
    return names


def test_every_import_is_declared():
    missing = sorted(
        module for module in third_party_imports("src", "scripts")
        if DISTRIBUTION.get(module, module).lower() not in declared()
    )
    assert not missing, (
        f"imported but not in requirements.txt: {missing}. "
        "These install fine locally and fail on a deployment."
    )


def test_test_only_dependencies_are_declared_too():
    """The suite runs in CI, which installs from the same manifest."""
    missing = sorted(
        module for module in third_party_imports("tests")
        if DISTRIBUTION.get(module, module).lower() not in declared()
    )
    assert not missing, f"imported by tests but not declared: {missing}"
