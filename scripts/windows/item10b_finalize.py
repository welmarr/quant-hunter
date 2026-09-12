"""Execute the governed Item 10B workflow and capture canonical evidence."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

_LAUNCHER_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER_SOURCE_ROOT = (_LAUNCHER_REPOSITORY_ROOT / "src").resolve()
if str(_LAUNCHER_SOURCE_ROOT) in sys.path:
    sys.path.remove(str(_LAUNCHER_SOURCE_ROOT))
sys.path.insert(0, str(_LAUNCHER_SOURCE_ROOT))

from quant_hunter.isolation import (  # noqa: E402 - checkout binding precedes import
    HostBoundaryEvidenceError,
    WindowsHostBoundaryProfile,
    WindowsHostBoundaryVerifier,
    item10b_capture_failure_diagnostic,
)


def _execute(arguments: argparse.Namespace) -> str:
    """Run the sole governed capture path after checkout binding succeeds."""
    requested_repository = arguments.repository_root.resolve()
    governed_schema_directory = (_LAUNCHER_REPOSITORY_ROOT / "schemas" / "v1").resolve()
    requested_schema_directory = arguments.schema_directory.resolve()
    if requested_repository != _LAUNCHER_REPOSITORY_ROOT:
        raise HostBoundaryEvidenceError(
            "Caller repository does not match the governed launcher checkout",
            phase="REPOSITORY_BINDING",
        )
    if requested_schema_directory != governed_schema_directory:
        raise HostBoundaryEvidenceError(
            "Schema directory does not match the governed launcher checkout",
            phase="REPOSITORY_BINDING",
        )
    candidate = arguments.candidate_root.resolve()
    try:
        profile = WindowsHostBoundaryProfile(
            candidate / "vault",
            candidate / "releases",
            candidate / "host-evidence",
        )
    except HostBoundaryEvidenceError as error:
        raise HostBoundaryEvidenceError(str(error), phase="PREFLIGHT") from error
    evidence = WindowsHostBoundaryVerifier(
        profile, governed_schema_directory
    ).capture_live_evidence(
        _LAUNCHER_REPOSITORY_ROOT,
        candidate,
        arguments.canonical_evidence,
        authorize_setup=arguments.authorize_setup,
    )
    return evidence.digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--canonical-evidence", type=Path, required=True)
    parser.add_argument("--authorize-setup", action="store_true", required=True)
    parser.add_argument(
        "--schema-directory",
        type=Path,
        default=_LAUNCHER_REPOSITORY_ROOT / "schemas" / "v1",
    )
    arguments = parser.parse_args(argv)
    try:
        digest = _execute(arguments)
    except Exception as error:
        print(item10b_capture_failure_diagnostic(error), file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
