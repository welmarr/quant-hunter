"""Execute the governed Item 10B workflow and capture canonical evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_hunter.isolation import (
    WindowsHostBoundaryProfile,
    WindowsHostBoundaryVerifier,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--canonical-evidence", type=Path, required=True)
    parser.add_argument("--authorize-setup", action="store_true", required=True)
    parser.add_argument(
        "--schema-directory",
        type=Path,
        default=Path(__file__).parents[2] / "schemas" / "v1",
    )
    arguments = parser.parse_args()
    candidate = arguments.candidate_root.resolve()
    profile = WindowsHostBoundaryProfile(
        candidate / "vault",
        candidate / "releases",
        candidate / "host-evidence",
    )
    evidence = WindowsHostBoundaryVerifier(
        profile, arguments.schema_directory
    ).capture_live_evidence(
        arguments.repository_root,
        candidate,
        arguments.canonical_evidence,
        authorize_setup=arguments.authorize_setup,
    )
    print(evidence.digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
