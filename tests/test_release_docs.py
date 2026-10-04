"""Keep release documentation references tied to files in the checkout."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE_DOCS = (
    "README.md",
    "docs/architecture/README.md",
    "docs/release-checklist.md",
    "docs/screenshots.md",
    "docs/release-evaluation.md",
    "docs/kronos-workflow.md",
)


@pytest.mark.parametrize("name", RELEASE_DOCS)
def test_release_document_relative_links_exist(name):
    document = ROOT / name
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text())
    assert links, f"{name} should link to its implementation or verification guidance"
    for link in links:
        if "://" in link or link.startswith("#"):
            continue
        target = (document.parent / link.split("#", 1)[0]).resolve()
        assert target.is_relative_to(ROOT), f"Outside-repository link in {name}: {link}"
        assert target.is_file(), f"Broken reference in {name}: {link}"


def test_readme_feature_rows_link_to_supporting_material():
    readme = (ROOT / "README.md").read_text()
    section = readme.split("## Feature status and evidence", 1)[1].split("## Screenshots", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ")][2:]
    assert rows
    for row in rows:
        assert re.search(r"\[[^\]]+\]\([^)]+\)", row), row
