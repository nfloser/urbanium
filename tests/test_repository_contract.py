from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_architecture_baseline_documents_exist() -> None:
    required = [
        "docs/index.md",
        "docs/architecture/overview.md",
        "docs/adr/0001-modular-monorepo.md",
        "docs/adr/0002-city-adapter-boundary.md",
        "docs/adr/0003-semantic-layer.md",
        "docs/research/reference-architectures.md",
        "docs/research/source-landscape.md",
        "docs/development/roadmap.md",
    ]
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert not missing, f"missing required architecture documents: {missing}"


def test_readme_states_platform_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "not as a dashboard application" in readme
    assert "berlin and mainz are the first reference deployments" in readme
