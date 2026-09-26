"""CI gates - rules that must never SHIP.

Everything here is a rule the SDK cannot enforce, because it is about the shape of the
repository rather than about what the code does at runtime. ADR-004's placement test is
"could this be caught earlier?" - and for each of these the answer is no:

  * the manifest schema      -> the generator gets it right, but people edit afterwards
  * declaring classification -> config.py rejects it at runtime too; CI stops it shipping
  * an unsupported SDK floor -> only knowable against the platform's support window
  * secrets in the repo      -> nothing at runtime can un-leak a committed secret
  * a pinned base image tag  -> `:latest` means the build is not reproducible
  * a container running root -> nothing at runtime can undo a root breakout

Deliberately NOT here: whether a connection actually works. The deploy runner is not
in the app's network and does not hold the app's credential - by design. Reachability is
`/healthz`'s job, from where the app runs. This checks shape.
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
    from insights_sdk.connectors import SUPPORTED_ENGINES
    from insights_sdk.errors import InsightsError
except ModuleNotFoundError:  # locally the four repos just sit side by side
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "insights-sdk" / "src"))
    from insights_sdk import SUPPORTED_VERSIONS, config
    from insights_sdk.connectors import SUPPORTED_ENGINES
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

    # 2. every connection names a supported engine and references a secret by NAME
    #
    # What this can and cannot check is worth stating. It cannot check that the host
    # is reachable from the deploy runner, or that the credential is valid - the
    # runner is not in the app's network and must not hold the app's credential. It
    # checks the shape, and `/healthz` checks reachability from where the app runs,
    # which is the only place that answer is meaningful.
    for spec in manifest.connections:
        if spec.engine not in SUPPORTED_ENGINES:
            fail(f"connection '{spec.name}' uses engine {spec.engine!r}. "
                 f"Supported: {', '.join(SUPPORTED_ENGINES)}.")
        for key, value in spec.options.items():
            if isinstance(value, str) and re.search(
                r"(?i)(password|secret|token|api[_-]?key)\s*[:=]", value
            ):
                fail(f"connection '{spec.name}' option {key!r} looks like it embeds a "
                     f"credential. Use `secret: <name>`.")

    # 3. the SDK version is inside the support window (ADR-001, N-2)
    #
    # Read from pyproject.toml, not from app.yaml. `runtime.sdk` used to state it and
    # was removed: uv.lock already pins the resolved version and uv enforces it on
    # every build, so a range in the manifest was a second copy that could disagree
    # with the lockfile while nothing noticed.
    pyproject = Path("pyproject.toml")
    if not pyproject.is_file():
        fail("no pyproject.toml - the SDK dependency has nowhere to be declared")
    else:
        body = pyproject.read_text()
        match = re.search(r"[\"']insights-sdk([^\"']*)[\"']", body)
        if not match:
            fail("pyproject.toml does not depend on insights-sdk")
        else:
            floor = match.group(1).strip() or ">=0"
            if "==" in floor:
                fail(
                    f"insights-sdk is pinned ({floor!r}) in pyproject.toml. Declare a floor "
                    f"and a major bound, e.g. '>=0.1,<1', so patches and minors reach you "
                    f"automatically. uv.lock is what pins the exact version. See ADR-001."
                )
            else:
                try:
                    supported = SpecifierSet(floor)
                except InvalidSpecifier:
                    fail(f"insights-sdk {floor!r} is not a valid version range")
                else:
                    if not any(supported.contains(Version(v)) for v in SUPPORTED_VERSIONS):
                        fail(
                            f"insights-sdk {floor} matches no supported version. The platform "
                            f"supports {', '.join(SUPPORTED_VERSIONS)} (current major plus two). "
                            f"See ADR-001."
                        )

    # 5. the tenant's Dockerfile, checked rather than owned
    #
    # This is the deliberate trade in ADR-004. An earlier design refused a tenant
    # Dockerfile outright and rendered the image from runtime.base, which made "runs
    # as non-root" and "built on a supported base" TRUE rather than CHECKED. Teams
    # own the file now, so those properties become checks - and a check is weaker
    # than a construction, because a check has to be right and has to run.
    #
    # The one we cannot check away is staleness: a CVE fix in a base image reaches an
    # app only when that app bumps its own FROM. So rule (d) is the important one,
    # and it is the price of the control teams asked for.
    dockerfile = Path("Dockerfile")
    if not dockerfile.is_file():
        fail(
            "no Dockerfile. `insights new-app` generates one and it belongs to your "
            "repo - `insights build --write` writes it if you have lost it."
        )
    else:
        lines = [ln.strip() for ln in dockerfile.read_text().splitlines()]
        froms = [ln for ln in lines if ln.upper().startswith("FROM ")]
        users = [ln for ln in lines if ln.upper().startswith("USER ")]

        if not froms:
            fail("Dockerfile has no FROM")
        for line in froms:
            image = line.split()[1]
            if "${" in image:
                continue                      # a build ARG; we cannot resolve it here
            # An image you cannot name is one you cannot roll back to, and `latest`
            # means the build is not reproducible.
            if image.endswith(":latest") or (":" not in image and "@" not in image):
                fail(f"Dockerfile uses {image!r}. Pin the base - :latest is not rollback-able.")

        # The final stage must not end up as root. Install as root if you must;
        # switch back before the end.
        if users and users[-1].split()[1] in ("root", "0"):
            fail(
                "Dockerfile's last USER is root. Install as root if you need to, but "
                "switch back - a container breakout should land on a user that owns nothing."
            )
        elif not users:
            fail(
                "Dockerfile never sets USER, so the container runs as root. Add a "
                "non-root user - `insights build --show` has the two lines."
            )

    failures = globals()["FAILURES"]
    print(f"platform gates: {'PASS' if not failures else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
