"""Every test this repo's docs cite must exist.

These documents are the submission's evidence: COMPLIANCE.md says "here is the control,
and here is the test that demonstrates it", and BRIEF-COVERAGE.md maps the brief to it.
A citation to a test that no longer exists is worse than no citation - it reads as
verified, and the only way to find out is to try running it.

This has already happened twice. A refactor removed the data broker, and the documents
kept citing the tests that went with it: five dead names in BRIEF-COVERAGE.md, three in
COMPLIANCE.md. Both files read as fully evidenced the whole time.

So the rule is mechanical now: if a doc names a `test_...`, it has to be a real one.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SDK_TESTS = REPO.parent / "insights-sdk" / "tests"

# A citation is a bare test name in the prose or a table. Names ending in `.py` are
# file references and are checked as files instead.
CITATION = re.compile(r"\btest_[a-z0-9_]+\b")


def _documents() -> list[Path]:
    docs = [REPO / "COMPLIANCE.md", REPO / "README.md", REPO / "RUNBOOK.md", REPO / "ONBOARDING.md"]
    docs += sorted((REPO / "docs").rglob("*.md"))
    return [d for d in docs if d.exists()]


def _defined_tests() -> set[str]:
    names: set[str] = set()
    roots = [REPO / "tests"]
    if SDK_TESTS.is_dir():
        roots.append(SDK_TESTS)
    for root in roots:
        for module in root.rglob("test_*.py"):
            names.update(re.findall(r"^def (test_[a-z0-9_]+)", module.read_text(), re.M))
    return names


def _defined_files() -> set[str]:
    files: set[str] = set()
    for root in ([REPO / "tests"] + ([SDK_TESTS] if SDK_TESTS.is_dir() else [])):
        files.update(m.name for m in root.rglob("test_*.py"))
    return files


def test_every_test_a_doc_cites_actually_exists():
    if not SDK_TESTS.is_dir():
        pytest.skip(
            f"needs the SDK checked out next to this repo ({SDK_TESTS}); "
            "CI checks out both, so this is enforced there"
        )

    defined, files = _defined_tests(), _defined_files()
    dead: dict[str, set[str]] = {}

    for doc in _documents():
        text = doc.read_text()
        cited = set()
        for name in CITATION.findall(text):
            # `test_foo.py` in the text is a file reference, not a function reference
            if f"{name}.py" in text and name not in defined:
                if f"{name}.py" not in files:
                    cited.add(f"{name}.py")
                continue
            cited.add(name)
        missing = {c for c in cited if c not in defined and c not in files}
        if missing:
            dead[doc.relative_to(REPO).as_posix()] = missing

    assert not dead, "documents cite tests that do not exist:\n" + "\n".join(
        f"  {doc}\n    " + "\n    ".join(sorted(names)) for doc, names in sorted(dead.items())
    )
