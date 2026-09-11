"""Finalize one live Item 10B report into canonical non-secret evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_hunter.isolation import (
    WindowsHostBoundaryProfile,
    WindowsHostBoundaryVerifier,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--canonical-evidence", type=Path, required=True)
    parser.add_argument(
        "--schema-directory",
        type=Path,
        default=Path(__file__).parents[2] / "schemas" / "v1",
    )
    arguments = parser.parse_args()
    profile = WindowsHostBoundaryProfile(
        arguments.vault_root,
        arguments.release_root,
        arguments.evidence_root,
    )
    evidence = WindowsHostBoundaryVerifier(
        profile, arguments.schema_directory
    ).finalize_live_report(arguments.live_report, arguments.canonical_evidence)
    print(evidence.digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
