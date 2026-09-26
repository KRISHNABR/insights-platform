"""CI gates - rules that must never SHIP.

Everything here is a rule the SDK cannot enforce, because it is about the shape of the
repository rather than about what the code does at runtime. ADR-004's placement test is
"could this be caught earlier?" - and for each of these the answer is no:

  * the manifest schema      -> the generator gets it right, but people edit afterwards
  * declaring classification -> config.py rejects it at runtime too; CI stops it shipping
  * an unsupported SDK floor -> only knowable against the platform's support window
  * secrets in the repo      -> nothing at runtime can un-leak a committed secret
  * a pinned base image tag  -> `:latest` breaks the one-rebuild CVE story

Deliberately NOT here: anything about data access. Entitlement and grants are checked
here AND at runtime, because CI can be bypassed and the runtime cannot.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

try:  # in CI the SDK is pip-installed, which is the path that matters
    from insights_sdk import SUPPORTED_VERSIONS, config
    from insights_sdk.errors import InsightsError
except ModuleNotFoundError:  # locally the four repos just sit side by side
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "insights-sdk" / "src"))
    from insights_sdk import SUPPORTED_VERSIONS, config
    from insights_sdk.errors import InsightsError

SECRET_PATTERNS = [
    re.compile(r"(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

#: Directories the secret scan never descends into: not written by the team, and
#: scanning them is both slow and a source of false positives.
SCAN_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist", "build", ".uv",
})

#: Binary-ish files a text secret scan cannot say anything useful about.
SCAN_SKIP_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".db", ".sqlite",
    ".so", ".dylib", ".whl", ".zip", ".gz", ".lock",
})


def fail(message: str) -> None:
    print(f"::error::{message}")
    globals()["FAILURES"] = globals().get("FAILURES", 0) + 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--manifest", default="app.yaml")
    parser.add_argument("--dockerfile", default="Dockerfile")
    args = parser.parse_args()

    globals()["FAILURES"] = 0

    # 1. manifest loads, and its name matches what CI was told to build
    try:
        manifest = config.load_manifest(args.manifest)
    except InsightsError as exc:
        fail(f"manifest: {exc}")
        return 1
    if manifest.app != args.app:
        fail(f"manifest says app '{manifest.app}' but the workflow was called with '{args.app}'")

    # 2. every declared dataset exists, and restricted ones are granted
    catalog, grants = config.load_catalog(), config.load_grants()
    for request in manifest.datasets:
        try:
            resolved = catalog.resolve(request.dataset)
        except InsightsError as exc:
            fail(f"dataset {request.dataset}: {exc}")
            continue
        if resolved.restricted and not grants.for_identity(request.dataset, manifest.service_identity):
            fail(
                f"{request.dataset} is restricted and not granted to {manifest.service_identity}. "
                f"We cannot grant it here - {resolved.dataset.owner} owns the data and grants it "
                f"in the data platform. This gate only checks that they already did."
            )

    # 3. the SDK floor is inside the support window (ADR-001, N-2)
    #
    # This gate is the enforcement point for the whole reuse/upgrade story, so it
    # has to actually be able to fail. An earlier version ended in `or True`, which
    # meant `>=9.9,<10` and even `>=banana` passed. Now it resolves the declared
    # range against the versions we actually support.
    floor = manifest.sdk_floor
    try:
        supported = SpecifierSet(floor)
    except InvalidSpecifier:
        fail(f"runtime.sdk {floor!r} is not a valid version range")
    else:
        if not any(supported.contains(Version(v)) for v in SUPPORTED_VERSIONS):
            fail(
                f"runtime.sdk {floor} matches no supported version. The platform supports "
                f"{', '.join(SUPPORTED_VERSIONS)} (current major plus two). See ADR-001."
            )

    # 4. no secrets committed
    #
    # Scan what the TEAM wrote, not what their tools downloaded. An earlier version
    # walked everything, which meant it scanned .venv/ - tens of thousands of files,
    # and site-packages ships test fixtures containing literal private keys, so the
    # gate would fail a clean repo because of a dependency's test data.
    for path in Path(".").rglob("*"):
        if any(part in SCAN_SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in SCAN_SKIP_SUFFIXES:
            continue
        try:
            if not path.is_file():
                continue
            text = path.read_text(errors="ignore")
        except OSError:
            # Unreadable (permissions, a broken symlink, a vanished temp file) is not
            # a finding. Note `is_file()` is INSIDE the try: it stats, so it raises too,
            # and having it outside meant one unreadable file crashed the whole gate.
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                fail(f"possible secret in {path}")
                break

    # 5. a tenant repo must NOT contain a Dockerfile
    #
    # Inverted from an earlier version, which checked the CONTENTS of a tenant
    # Dockerfile. There is no such file: the platform renders the image from
    # runtime.base at build time, which is what makes "runs as non-root", "built on
    # a supported base" and "SDK matches the manifest" true rather than checked.
    # A Dockerfile appearing here means someone is trying to take that back.
    if Path("Dockerfile").is_file():
        fail(
            "this repo contains a Dockerfile. The platform renders the image from "
            "runtime.base in app.yaml - run `insights build --show` to see it. A "
            "hand-written Dockerfile would make the platform's guarantees unenforceable."
        )

    failures = globals()["FAILURES"]
    print(f"platform gates: {'PASS' if not failures else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
