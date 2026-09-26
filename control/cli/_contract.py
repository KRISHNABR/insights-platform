"""Shared helper for the deploy-step interface stubs.

These five scripts define the CONTRACT of a deploy without implementing it. That is
deliberate and it is stated everywhere they are referenced: this submission has no
cloud account, so a real implementation would be untested code that looks tested.

Each stub prints its inputs, its side effects, and what it would call in the target
environment, then exits 2. Exit 2 is the platform's "refused, not broken" code, so a
pipeline running these fails loudly rather than appearing to succeed.
"""

from __future__ import annotations

import sys


def declare(step: str, *, inputs: dict, effects: list[str], target: list[str]) -> int:
    width = max(len(k) for k in inputs) if inputs else 0
    print(f"\n  {step}\n  {'=' * len(step)}\n")
    print("  inputs")
    for key, value in inputs.items():
        print(f"    {key:<{width}}  {value}")
    print("\n  side effects")
    for line in effects:
        print(f"    - {line}")
    print("\n  in the target environment this would")
    for line in target:
        print(f"    - {line}")
    print(
        "\n  NOT IMPLEMENTED in this take-home: there is no cloud account to deploy to.\n"
        "  The contract above is the design artefact; see docs/ARCHITECTURE.md section 10.\n"
    )
    return 2


def arg(name: str, default: str = "") -> str:
    for i, token in enumerate(sys.argv):
        if token == f"--{name}" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if token.startswith(f"--{name}="):
            return token.split("=", 1)[1]
    return default
