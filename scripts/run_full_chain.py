from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from agent_runtime.product.full_chain_manager import FullChainManager, ManagedService


REPO_ROOT = Path(__file__).resolve().parents[1]


def _log(msg: str) -> None:
    print(f"[run_full_chain] {msg}")


def _readable_path(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except Exception:
        return path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(str(path))

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        os.environ.setdefault(key, value)


def _memory_port_from_url(url: str, default_port: int = 8001) -> int:
    parsed = urlparse(url)
    if parsed.port:
        return int(parsed.port)
    return int(default_port)


def _run(cmd: list[str], *, cwd: Path, quiet: bool = False) -> subprocess.Popen[bytes]:
    stdout = subprocess.DEVNULL if quiet else None
    stderr = subprocess.DEVNULL if quiet else None
    return subprocess.Popen(cmd, cwd=str(cwd), stdout=stdout, stderr=stderr)


def _wait_http_ok(url: str, *, timeout_s: float = 0.3, attempts: int = 50, sleep_s: float = 0.2) -> None:
    import requests

    last_exc: Exception | None = None
    for _ in range(int(attempts)):
        try:
            resp = requests.get(url, timeout=float(timeout_s))
            if 200 <= int(resp.status_code) < 500:
                return
        except Exception as e:
            last_exc = e
        time.sleep(float(sleep_s))

    if last_exc is not None:
        raise RuntimeError(f"service not ready: {url} ({type(last_exc).__name__}: {last_exc})")
    raise RuntimeError(f"service not ready: {url}")


def _term(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except Exception:
        return


def _kill(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.kill()
    except Exception:
        return


@dataclass
class FullChainArgs:
    main_env: Path
    planner_env: Path
    distill_env: Path
    memory_url: str
    gateway_port: int
    no_planner: bool
    no_distill: bool
    no_demo: bool
    once: bool
    verbose: bool = False


def run_full_chain(args: FullChainArgs) -> int:
    manager = FullChainManager(repo_root=REPO_ROOT)

    def _cleanup(*_sig: object) -> None:
        _log("stopping child processes...")
        manager.stop_all()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    _log("starting infrastructure via ./start_services.sh start")
    # Use bash wrapper to keep behavior aligned with docs.
    subprocess.check_call(["./start_services.sh", "start"], cwd=str(REPO_ROOT))

    _log(f"loading env: {_readable_path(str(args.main_env))}")
    _load_env_file(args.main_env)

    if not args.no_planner and args.planner_env.exists():
        _log(f"loading env: {_readable_path(str(args.planner_env))}")
        _load_env_file(args.planner_env)

    os.environ.setdefault("MEMORY_SERVICE_URL", args.memory_url)
    memory_port = _memory_port_from_url(args.memory_url)

    _log("starting memory service (uvicorn create_app --factory)")
    manager.start(
        ManagedService(
            name="memory_service",
            cmd=[
                sys.executable,
                "-m",
                "uvicorn",
                "agent_memory_service.app:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                str(memory_port),
            ],
            cwd=REPO_ROOT,
            env={},
        ),
        quiet=not args.verbose,
    )

    _wait_http_ok(f"{args.memory_url.rstrip('/')}/health")

    _log("starting gateway (uvicorn)")
    manager.start(
        ManagedService(
            name="gateway",
            cmd=[
                sys.executable,
                "-m",
                "uvicorn",
                "agent_runtime.product.agent_gateway:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(args.gateway_port),
            ],
            cwd=REPO_ROOT,
            env={},
        ),
        quiet=not args.verbose,
    )

    _wait_http_ok(f"http://127.0.0.1:{args.gateway_port}/health")

    if not args.no_distill and args.distill_env.exists():
        _log(f"loading env: {_readable_path(str(args.distill_env))}")
        _load_env_file(args.distill_env)

        _log("starting distill worker")
        manager.start(
            ManagedService(
                name="distill_worker",
                cmd=[sys.executable, "-m", "scripts.memory_distill_worker"],
                cwd=REPO_ROOT,
                env={},
            ),
            quiet=not args.verbose,
        )

    if not args.no_demo:
        _log("running demo")
        subprocess.check_call(
            [sys.executable, "examples/project_management_demo_real.py"],
            cwd=str(REPO_ROOT),
        )

    if args.once:
        _log("--once completed")
        return 0

    _log("services are running (Ctrl+C to stop)")
    while True:
        time.sleep(5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local full-chain flow")
    parser.add_argument(
        "--main-env",
        default="config/openai_main.env",
        help="Env file for main reasoning LLM (default: config/openai_main.env)",
    )
    parser.add_argument(
        "--planner-env",
        default="config/context_planner.env",
        help="Env file for context planner (default: config/context_planner.env)",
    )
    parser.add_argument(
        "--distill-env",
        default="config/distill_worker.env",
        help="Env file for distill worker (default: config/distill_worker.env)",
    )
    parser.add_argument(
        "--memory-url",
        default="http://127.0.0.1:8001",
        help="Memory service URL (default: http://127.0.0.1:8001)",
    )
    parser.add_argument(
        "--gateway-port",
        type=int,
        default=8080,
        help="Gateway port (default: 8080)",
    )
    parser.add_argument("--no-planner", action="store_true")
    parser.add_argument("--no-distill", action="store_true")
    parser.add_argument("--no-demo", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="Do not suppress child process output")

    ns = parser.parse_args(argv)
    args = FullChainArgs(
        main_env=REPO_ROOT / ns.main_env,
        planner_env=REPO_ROOT / ns.planner_env,
        distill_env=REPO_ROOT / ns.distill_env,
        memory_url=str(ns.memory_url),
        gateway_port=int(ns.gateway_port),
        no_planner=bool(ns.no_planner),
        no_distill=bool(ns.no_distill),
        no_demo=bool(ns.no_demo),
        once=bool(ns.once),
        verbose=bool(ns.verbose),
    )
    if not args.main_env.exists():
        raise SystemExit(
            f"Missing main env file: {_readable_path(str(args.main_env))} (see docs/RUN_FULL_CHAIN.md)"
        )
    return run_full_chain(args)


if __name__ == "__main__":
    raise SystemExit(main())
