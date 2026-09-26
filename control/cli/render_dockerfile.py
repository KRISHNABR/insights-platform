#!/usr/bin/env python3
"""Render the image definition from the manifest.

Unlike its four siblings this one IS implemented - it is the same code path as
`insights build --show`, because an image a tenant cannot inspect is an image they
cannot debug.
"""
import sys
from pathlib import Path

try:  # in CI the SDK is pip-installed, which is the path that matters
    from insights_sdk import config
    from insights_sdk.cli import scaffold
except ModuleNotFoundError:  # locally the four repos just sit side by side
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "insights-sdk" / "src"))
    from insights_sdk import config
    from insights_sdk.cli import scaffold

from _contract import arg                            # noqa: E402

manifest = config.load_manifest(arg("manifest", "app.yaml"))
rendered = scaffold.render_dockerfile(manifest)

out = arg("out")
if out:
    Path(out).write_text(rendered)
    print(f"rendered {manifest.app} ({manifest.base}) -> {out}")
else:
    print(rendered)
