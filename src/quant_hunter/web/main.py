"""Native loopback entry point. No broker or live-money capability exists here."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

import uvicorn

from quant_hunter.sources import list_sources
from quant_hunter.web.api import create_app
from quant_hunter.web.lease import RuntimeLease
from quant_hunter.web.runtime import Runtime, fixture_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--private-root", type=Path)
    args = parser.parse_args()
    repository, runtime = args.repository.resolve(), args.runtime.resolve()
    lease = RuntimeLease(runtime)
    lease.acquire()
    try:
        runner = Runtime(
            runtime, repository, args.code_revision, private_root=args.private_root
        )
        runner.recover()
        app = create_app(
            runtime,
            repository,
            process_job=runner.process_one,
            get_run=runner.lab.get_run,
            fixtures=fixture_catalog(),
            data=runner.data,
            sources=[asdict(source) for source in list_sources()],
            connections=runner.connections,
            instruments=runner.instruments,
        )
        uvicorn.run(
            app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning"
        )
    finally:
        lease.release()


if __name__ == "__main__":
    main()
