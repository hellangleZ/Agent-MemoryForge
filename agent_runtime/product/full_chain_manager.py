from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

def _pid_exists(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate_pid(pid: int) -> None:
    os.kill(int(pid), signal.SIGTERM)


def _kill_pid(pid: int) -> None:
    os.kill(int(pid), signal.SIGKILL)


@dataclass(frozen=True)
class ManagedService:
    name: str
    cmd: List[str]
    cwd: Path
    env: Dict[str, str]


@dataclass
class ProcessInfo:
    name: str
    pid: int
    started_at_s: float
    cmd: List[str]
    log_path: Optional[Path]


class FullChainManager:
    """Start/stop full-chain processes and track their state.

    This is designed to be reusable from:
    - Python runner scripts
    - Product CLI
    - Product Gateway API endpoints
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        logs_dir: Optional[Path] = None,
        pid_dir: Optional[Path] = None,
    ) -> None:
        self._repo_root = repo_root
        self._logs_dir = logs_dir or (repo_root / "logs" / "full_chain")
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._procs: Dict[str, subprocess.Popen[bytes]] = {}
        self._info: Dict[str, ProcessInfo] = {}

        self._pid_files_dir = pid_dir or (repo_root / ".runtime" / "full_chain")
        self._pid_files_dir.mkdir(parents=True, exist_ok=True)

        self._known_services = ["memory_service", "gateway", "distill_worker"]

    def known_services(self) -> List[str]:
        return list(self._known_services)

    def _pid_file(self, service_name: str) -> Path:
        return self._pid_files_dir / f"{service_name}.pid"

    def _write_pid_file(self, service_name: str, pid: int) -> None:
        self._pid_file(service_name).write_text(f"{int(pid)}\n", encoding="utf-8")

    def _read_pid_file(self, service_name: str) -> Optional[int]:
        path = self._pid_file(service_name)
        if not path.exists():
            return None
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except Exception:
            return None

    def _unlink_pid_file(self, service_name: str) -> None:
        try:
            self._pid_file(service_name).unlink(missing_ok=True)
        except Exception:
            return

    def status(self) -> Dict[str, ProcessInfo]:
        names = set(self._known_services)
        out: Dict[str, ProcessInfo] = {}
        with self._lock:
            out.update({k: v for k, v in self._info.items() if k in names})

        for name in names:
            pid = self._read_pid_file(name)
            if not pid:
                continue
            if not _pid_exists(pid):
                self._unlink_pid_file(name)
                continue
            if name in out:
                continue
            out[name] = ProcessInfo(
                name=name,
                pid=pid,
                started_at_s=0.0,
                cmd=[],
                log_path=self._logs_dir / f"{name}.log",
            )
        return out

    def logs_path(self, service_name: str) -> Optional[Path]:
        with self._lock:
            info = self._info.get(service_name)
            if info and info.log_path:
                return info.log_path

        candidate = self._logs_dir / f"{service_name}.log"
        if candidate.exists():
            return candidate
        return None

    def start(self, service: ManagedService, *, quiet: bool = True) -> ProcessInfo:
        with self._lock:
            existing = self._procs.get(service.name)
            if existing is not None and existing.poll() is None:
                return self._info[service.name]

            existing_pid = self._read_pid_file(service.name)
            if existing_pid and _pid_exists(existing_pid):
                return ProcessInfo(
                    name=service.name,
                    pid=int(existing_pid),
                    started_at_s=0.0,
                    cmd=list(service.cmd),
                    log_path=(self._logs_dir / f"{service.name}.log") if quiet else None,
                )

            env = dict(os.environ)
            env.update(service.env)

            log_path: Optional[Path] = None
            stdout = None
            stderr = None
            log_file = None
            if quiet:
                log_path = self._logs_dir / f"{service.name}.log"
                log_file = open(log_path, "ab", buffering=0)
                stdout = log_file
                stderr = log_file

            try:
                proc = subprocess.Popen(
                    service.cmd,
                    cwd=str(service.cwd),
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                )
            finally:
                # Popen dups the fd into the child; close the parent handle so
                # we don't leak a file descriptor on every start().
                if log_file is not None:
                    log_file.close()

            info = ProcessInfo(
                name=service.name,
                pid=int(proc.pid),
                started_at_s=time.time(),
                cmd=list(service.cmd),
                log_path=log_path,
            )
            self._procs[service.name] = proc
            self._info[service.name] = info
            self._write_pid_file(service.name, info.pid)
            return info

    def start_group(
        self,
        services: Sequence[ManagedService],
        *,
        quiet: bool = True,
        health_checks: Optional[Dict[str, Callable[[], bool]]] = None,
        health_timeout_s: float = 10.0,
        rollback_on_failure: bool = True,
    ) -> Dict[str, ProcessInfo]:
        """Start multiple services in order.

        If `health_checks` provides a check for a service name, this method will
        wait until it returns True or times out.

        If `rollback_on_failure` is True and a later service fails to start or
        becomes healthy, already-started services are stopped in reverse order.
        """

        health_checks = health_checks or {}

        out: Dict[str, ProcessInfo] = {}
        started_names: List[str] = []

        def _wait_healthy(name: str) -> None:
            check = health_checks.get(name)
            if not check:
                return
            deadline = time.time() + float(health_timeout_s)
            last_exc: Exception | None = None
            while time.time() < deadline:
                try:
                    if bool(check()):
                        return
                except Exception as exc:
                    last_exc = exc
                time.sleep(0.1)
            if last_exc is not None:
                raise RuntimeError(f"health check failed for {name}: {type(last_exc).__name__}: {last_exc}")
            raise RuntimeError(f"health check failed for {name}")

        try:
            for svc in services:
                info = self.start(svc, quiet=quiet)
                out[svc.name] = info
                started_names.append(svc.name)
                _wait_healthy(svc.name)
            return out
        except Exception:
            if rollback_on_failure:
                for name in reversed(started_names):
                    try:
                        self.stop(name)
                    except Exception:
                        continue
            raise

    def stop(self, service_name: str, *, timeout_s: float = 2.0) -> bool:
        with self._lock:
            proc = self._procs.get(service_name)
            if proc is None:
                pid = self._read_pid_file(service_name)
                if not pid:
                    return False
                try:
                    _terminate_pid(int(pid))
                except Exception:
                    self._unlink_pid_file(service_name)
                    return False

                deadline = time.time() + float(timeout_s)
                while time.time() < deadline:
                    if not _pid_exists(int(pid)):
                        self._unlink_pid_file(service_name)
                        return True
                    time.sleep(0.05)
                try:
                    _kill_pid(int(pid))
                    self._unlink_pid_file(service_name)
                    return True
                except Exception:
                    return False
            if proc.poll() is not None:
                self._unlink_pid_file(service_name)
                return False
            try:
                proc.terminate()
            except Exception:
                return False

        deadline = time.time() + float(timeout_s)
        while time.time() < deadline:
            with self._lock:
                proc = self._procs.get(service_name)
                if proc is None or proc.poll() is not None:
                    self._unlink_pid_file(service_name)
                    return True
            time.sleep(0.05)

        with self._lock:
            proc = self._procs.get(service_name)
            if proc is None or proc.poll() is not None:
                self._unlink_pid_file(service_name)
                return True
            try:
                proc.kill()
                self._unlink_pid_file(service_name)
                return True
            except Exception:
                return False

    def stop_all(self) -> None:
        for name in list(self.status().keys()):
            self.stop(name)
