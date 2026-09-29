import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "urbanium" / "core"


def test_core_does_not_import_city_specific_packages() -> None:
    forbidden_prefixes = ("urbanium.cities", "cities.berlin", "cities.mainz")
    violations: list[str] = []

    for path in CORE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden_prefixes):
                        violations.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(forbidden_prefixes):
                    violations.append(f"{path}: from {node.module}")

    assert not violations, "city-specific imports leaked into core: " + "; ".join(violations)


def test_core_does_not_depend_on_rdf_projection_libraries() -> None:
    forbidden_prefixes = ("rdflib", "pyshacl", "urbanium.semantics")
    violations: list[str] = []

    for path in CORE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden_prefixes):
                        violations.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(forbidden_prefixes):
                    violations.append(f"{path}: from {node.module}")

    assert not violations, "semantic projection imports leaked into core: " + "; ".join(violations)
