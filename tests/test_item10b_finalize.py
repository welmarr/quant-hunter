"""Hostile tests for the governed Item 10B owner-facing launcher."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from quant_hunter.isolation import HostBoundaryEvidenceError
from quant_hunter.isolation.windows_host import item10b_capture_failure_diagnostic

ROOT = Path(__file__).parents[1].resolve()
LAUNCHER = ROOT / "scripts" / "windows" / "item10b_finalize.py"


def _load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("item10b_finalize_test", LAUNCHER)
    if spec is None or spec.loader is None:
        raise AssertionError("launcher could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_precedes_foreign_pythonpath_with_its_checkout(tmp_path: Path) -> None:
    """The launcher imports its own source even when PYTHONPATH names a foreign package."""
    foreign = tmp_path / "foreign"
    package = foreign / "quant_hunter"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "raise RuntimeError('FOREIGN_PACKAGE_IMPORTED')\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(foreign)
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and governed launcher
        [sys.executable, str(LAUNCHER), "--help"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0
    assert "FOREIGN_PACKAGE_IMPORTED" not in output
    assert "--repository-root" in output


def test_repository_binding_failure_is_sanitized_before_host_setup(
    tmp_path: Path,
) -> None:
    """The observed mismatch exits safely without traceback, paths, or authority."""
    private_candidate = tmp_path / "Users" / "private-owner" / "candidate"
    foreign_repository = tmp_path / "foreign-repository"
    evidence = private_candidate / "host-evidence" / "evidence-000001.json"
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and governed launcher
        [
            sys.executable,
            str(LAUNCHER),
            "--repository-root",
            str(foreign_repository),
            "--candidate-root",
            str(private_candidate),
            "--canonical-evidence",
            str(evidence),
            "--authorize-setup",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "ITEM10B_CAPTURE_FAILED" in completed.stderr
    assert "phase=REPOSITORY_BINDING" in completed.stderr
    assert "type=HostBoundaryEvidenceError" in completed.stderr
    assert "reason=Governed repository binding verification failed" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert str(tmp_path) not in completed.stderr
    assert "private-owner" not in completed.stderr
    assert not evidence.exists()


def test_schema_override_cannot_spoof_governed_checkout(tmp_path: Path) -> None:
    """Caller-controlled schemas cannot weaken the checkout-bound validation path."""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and governed launcher
        [
            sys.executable,
            str(LAUNCHER),
            "--repository-root",
            str(ROOT),
            "--candidate-root",
            str(tmp_path / "candidate"),
            "--canonical-evidence",
            str(tmp_path / "evidence.json"),
            "--schema-directory",
            str(tmp_path / "foreign-schemas"),
            "--authorize-setup",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode != 0
    assert "phase=REPOSITORY_BINDING" in completed.stderr
    assert str(tmp_path) not in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize("phase", ["PREFLIGHT", "SETUP", "VERIFICATION", "PUBLICATION"])
def test_known_capture_failure_preserves_governed_phase(phase: str) -> None:
    """Known failures keep their useful governed phase in bounded output."""
    diagnostic = item10b_capture_failure_diagnostic(
        HostBoundaryEvidenceError("Synthetic governed failure", phase=phase)
    )
    assert f"phase={phase}" in diagnostic
    assert "reason=Synthetic governed failure" in diagnostic
    assert len(diagnostic) <= 512


def test_repository_failure_diagnostic_redacts_real_windows_paths() -> None:
    """The observed repository mismatch never reflects owner paths."""
    diagnostic = item10b_capture_failure_diagnostic(
        HostBoundaryEvidenceError(
            r"D:\quant-hunter did not match D:\Users\private-owner\.venv",
            phase="REPOSITORY_BINDING",
        )
    )
    assert diagnostic == "\n".join(
        (
            "ITEM10B_CAPTURE_FAILED",
            "phase=REPOSITORY_BINDING",
            "type=HostBoundaryEvidenceError",
            "reason=Governed repository binding verification failed",
        )
    )
    assert "D:\\" not in diagnostic
    assert "private-owner" not in diagnostic


@pytest.mark.parametrize(
    "label",
    [
        "password",
        "passwd",
        "token",
        "secret",
        "credential",
        "api_key",
        "api-key",
        "access_key",
        "private_key",
        "client_secret",
        "client-secret",
    ],
)
@pytest.mark.parametrize("separator", ["=", ": "])
def test_unknown_diagnostic_redacts_generic_secret_value(
    label: str, separator: str
) -> None:
    """Generic secret assignments retain context but never expose their value."""
    sensitive_value = f"hidden-{label.replace('_', '-')}"
    diagnostic = item10b_capture_failure_diagnostic(
        RuntimeError(
            f"Authentication failed; {label}{separator}{sensitive_value}; retry denied"
        )
    )
    assert "phase=UNEXPECTED" in diagnostic
    assert "type=RuntimeError" in diagnostic
    assert "Authentication failed" in diagnostic
    assert "retry denied" in diagnostic
    assert f"{label}{separator}[REDACTED]" in diagnostic
    assert sensitive_value not in diagnostic
    assert "Traceback" not in diagnostic


@pytest.mark.parametrize(
    ("path", "forbidden_fragments"),
    [
        (
            r"C:\Users\Private Owner\Documents\secret file.json",
            ("Private Owner", r"Owner\Documents\secret file.json"),
        ),
        (
            r"D:\Some Folder\Nested Folder\file.txt",
            ("Some Folder", r"Folder\Nested Folder\file.txt"),
        ),
    ],
)
def test_unknown_diagnostic_redacts_unquoted_windows_path_with_spaces(
    path: str, forbidden_fragments: tuple[str, ...]
) -> None:
    """An unquoted absolute Windows path is removed as one complete value."""
    diagnostic = item10b_capture_failure_diagnostic(
        OSError(f"Cannot open {path}; file inspection failed")
    )
    assert "Cannot open <REDACTED_PATH>; file inspection failed" in diagnostic
    assert path not in diagnostic
    assert all(fragment not in diagnostic for fragment in forbidden_fragments)


def test_unknown_diagnostic_redacts_quoted_windows_path_with_spaces() -> None:
    """Quoted user-profile paths are removed without losing the error meaning."""
    path = r"C:\Users\Private Owner\Documents\secret file.json"
    diagnostic = item10b_capture_failure_diagnostic(
        OSError(f'Cannot read "{path}"; access was denied')
    )
    assert "Cannot read <REDACTED_PATH>; access was denied" in diagnostic
    assert path not in diagnostic
    assert "Private Owner" not in diagnostic


def test_unknown_diagnostic_redacts_multiple_secrets_and_path_together() -> None:
    """One hostile exception cannot leak any of its independent sensitive values."""
    path = r"C:\Users\Private Owner\Documents\secret file.json"
    diagnostic = item10b_capture_failure_diagnostic(
        RuntimeError(
            f"Upload failed for {path}; password=alpha-value; token: beta-value; "
            "access_key=gamma-value; governed retry remains available"
        )
    )
    assert "Upload failed for <REDACTED_PATH>" in diagnostic
    assert "governed retry remains available" in diagnostic
    assert "password=[REDACTED]" in diagnostic
    assert "token: [REDACTED]" in diagnostic
    assert "access_key=[REDACTED]" in diagnostic
    for forbidden in (
        path,
        "Private Owner",
        r"Owner\Documents\secret file.json",
        "alpha-value",
        "beta-value",
        "gamma-value",
        "Traceback",
    ):
        assert forbidden not in diagnostic


def test_unknown_diagnostic_strips_controls_preserves_meaning_and_is_bounded() -> None:
    """Unknown failures retain safe meaning after control stripping and truncation."""
    diagnostic = item10b_capture_failure_diagnostic(
        RuntimeError(
            "\x1b[31mUseful governed validation failed\x1b[0m\x00\x07; "
            f"detail={'x' * 2000}"
        )
    )
    assert "Useful governed validation failed" in diagnostic
    assert "phase=UNEXPECTED" in diagnostic
    assert "type=RuntimeError" in diagnostic
    assert "Traceback" not in diagnostic
    assert "\x1b" not in diagnostic
    assert "\x00" not in diagnostic
    assert "\x07" not in diagnostic
    assert len(diagnostic) <= 512


def test_unexpected_launcher_failure_keeps_meaning_but_redacts_and_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unexpected errors remain useful without exposing attacker-controlled content."""
    launcher = cast(Any, _load_launcher())
    environment_value = "opaque-environment-value"
    monkeypatch.setenv("ITEM10B_PRIVATE_VALUE", environment_value)
    private_path = tmp_path / "Users" / "private-owner" / "private.json"
    attack = (
        f"Cannot open '{private_path}'; Authorization: Bearer secret-token; "
        "BitLocker recovery password: 111111-222222-333333-444444; "
        f"environment={environment_value}; \x1b[31mterminal\x1b[0m; "
        f"object=<object at 0x1234>; {'x' * 2000}"
    )

    def fail(arguments: object) -> str:
        raise FileNotFoundError(attack)

    monkeypatch.setattr(launcher, "_execute", fail)
    exit_code = launcher.main(
        [
            "--repository-root",
            str(ROOT),
            "--candidate-root",
            str(tmp_path / "candidate"),
            "--canonical-evidence",
            str(tmp_path / "evidence.json"),
            "--authorize-setup",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "ITEM10B_CAPTURE_FAILED" in captured.err
    assert "phase=UNEXPECTED" in captured.err
    assert "type=FileNotFoundError" in captured.err
    assert "Cannot open" in captured.err
    assert "Traceback" not in captured.err
    for forbidden in (
        str(private_path),
        "private-owner",
        "secret-token",
        "111111-222222",
        environment_value,
        "\x1b",
        "0x1234",
    ):
        assert forbidden not in captured.err
    assert "<REDACTED_PATH>" in captured.err
    assert len(captured.err) <= 513
