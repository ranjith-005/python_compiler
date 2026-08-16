"""One live IPython kernel per user - what makes cells behave like Colab.

State persists between cells because it is the same process; rich output
(matplotlib PNGs, pandas HTML) arrives as display_data messages.

Security: the kernel is a long-lived process running as the local OS user.
This is not a sandbox. See README.md.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from jupyter_client import AsyncKernelManager
from jupyter_client.kernelspec import KernelSpecManager

from .config import BASE_DIR, settings
from .workspace import workspace_dir

KERNEL_NAME = "pycompiler"
KERNEL_DIR = BASE_DIR / ".kernels"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def ensure_kernelspec() -> KernelSpecManager:
    """Write a kernelspec pinned to *this* interpreter (not a system one)."""
    spec_dir = KERNEL_DIR / KERNEL_NAME
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec = {
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "PyCompiler (venv)",
        "language": "python",
        # "signal" (the default) is the only mode ipykernel supports on Windows -
        # jupyter_client sends a Windows interrupt event; "message" is rejected.
        "interrupt_mode": "signal",
        "metadata": {},
    }
    (spec_dir / "kernel.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return KernelSpecManager(kernel_dirs=[str(KERNEL_DIR)])


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


class CellInterrupted(Exception):
    """Raised when a cell is stopped by the user or by the cell timeout."""


class KernelSession:
    """A single user's kernel. Executions are serialized by `lock`."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.km: AsyncKernelManager | None = None
        self.kc = None
        self.lock = asyncio.Lock()
        self.last_used = time.monotonic()
        self.starting = False
        # While the kernel waits on input(), the cell timeout must not fire.
        self.awaiting_input = False

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self.km is not None:
            return
        self.starting = True
        try:
            ksm = ensure_kernelspec()
            km = AsyncKernelManager(kernel_name=KERNEL_NAME, kernel_spec_manager=ksm)
            await km.start_kernel(cwd=str(self._workdir()))
            kc = km.client()
            kc.start_channels()
            await kc.wait_for_ready(timeout=settings.KERNEL_STARTUP_SEC)
            self.km, self.kc = km, kc
            self.last_used = time.monotonic()
        finally:
            self.starting = False

    def _workdir(self) -> Path:
        # Same folder the Files panel writes to, so uploads are readable by
        # relative name: pd.read_csv("data.csv").
        return workspace_dir(self.user_id)

    async def shutdown(self) -> None:
        if self.kc is not None:
            try:
                self.kc.stop_channels()
            except Exception:
                pass
        if self.km is not None:
            try:
                await self.km.shutdown_kernel(now=True)
            except Exception:
                pass
        self.km, self.kc = None, None

    async def restart(self) -> None:
        if self.km is None:
            await self.start()
            return
        await self.km.restart_kernel(now=True)
        await self.kc.wait_for_ready(timeout=settings.KERNEL_STARTUP_SEC)
        self.last_used = time.monotonic()

    async def interrupt(self) -> None:
        if self.km is not None:
            await self.km.interrupt_kernel()

    @property
    def alive(self) -> bool:
        return self.km is not None

    # ------------------------------------------------------------- execution

    async def execute(
        self,
        code: str,
        on_input_request: Callable[[str, bool], Awaitable[str]] | None = None,
        timeout: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run `code`, yielding protocol events until the kernel goes idle.

        Events: {"type": "execute_input"|"output"|"clear_output"|"done"}.
        Outputs use the nbformat shape, so they store and export unchanged.
        """
        if self.km is None:
            await self.start()
        timeout = timeout or settings.CELL_TIMEOUT_SEC
        self.last_used = time.monotonic()

        msg_id = self.kc.execute(code, store_history=True, allow_stdin=True)
        deadline = time.monotonic() + timeout
        execution_count: int | None = None
        errored = False
        interrupted = False

        stdin_task = asyncio.create_task(self._watch_stdin(msg_id, on_input_request))
        try:
            while True:
                if self.awaiting_input:
                    deadline = time.monotonic() + timeout  # user is typing; hold the clock
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    await self.interrupt()
                    interrupted = True
                    yield {
                        "type": "output",
                        "output": {
                            "output_type": "error",
                            "ename": "TimeoutError",
                            "evalue": f"cell exceeded {timeout}s and was interrupted",
                            "traceback": [f"Cell timed out after {timeout}s - the runtime was interrupted."],
                        },
                    }
                    errored = True
                    # Give the kernel a moment to report idle after the interrupt.
                    deadline = time.monotonic() + 10
                    continue

                try:
                    msg = await self.kc.get_iopub_msg(timeout=min(remaining, 1.0))
                except Exception:
                    continue  # timeout on the channel poll; re-check the deadline

                if msg.get("parent_header", {}).get("msg_id") != msg_id:
                    continue

                msg_type = msg["msg_type"]
                content = msg["content"]

                if msg_type == "status":
                    if content.get("execution_state") == "idle":
                        break
                elif msg_type == "execute_input":
                    execution_count = content.get("execution_count")
                    yield {"type": "execute_input", "execution_count": execution_count}
                elif msg_type == "stream":
                    yield {
                        "type": "output",
                        "output": {
                            "output_type": "stream",
                            "name": content.get("name", "stdout"),
                            "text": content.get("text", ""),
                        },
                    }
                elif msg_type in ("execute_result", "display_data", "update_display_data"):
                    output = {
                        "output_type": "execute_result" if msg_type == "execute_result" else "display_data",
                        "data": self._clean_data(content.get("data", {})),
                        "metadata": content.get("metadata", {}),
                    }
                    if msg_type == "execute_result":
                        output["execution_count"] = content.get("execution_count")
                    yield {"type": "output", "output": output}
                elif msg_type == "error":
                    errored = True
                    yield {
                        "type": "output",
                        "output": {
                            "output_type": "error",
                            "ename": content.get("ename", "Error"),
                            "evalue": content.get("evalue", ""),
                            "traceback": [strip_ansi(t) for t in content.get("traceback", [])],
                        },
                    }
                    if "KeyboardInterrupt" in content.get("ename", ""):
                        interrupted = True
                elif msg_type == "clear_output":
                    yield {"type": "clear_output"}
        finally:
            stdin_task.cancel()
            self.last_used = time.monotonic()

        yield {
            "type": "done",
            "execution_count": execution_count,
            "error": errored,
            "interrupted": interrupted,
        }

    @staticmethod
    def _clean_data(data: dict) -> dict:
        """Keep only the mime types the front end renders."""
        keep = ("image/png", "image/jpeg", "image/svg+xml", "text/html", "text/markdown", "text/plain")
        return {k: v for k, v in data.items() if k in keep}

    async def _watch_stdin(
        self, msg_id: str, on_input_request: Callable[[str, bool], Awaitable[str]] | None
    ) -> None:
        """Forward the kernel's input() prompts to the browser and reply."""
        while True:
            try:
                msg = await self.kc.get_stdin_msg(timeout=1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(0)
                continue
            if msg.get("msg_type") != "input_request":
                continue
            content = msg.get("content", {})
            prompt = content.get("prompt", "")
            password = bool(content.get("password", False))
            if on_input_request is None:
                self.kc.input("")  # no client to ask - behave like EOF
                continue
            self.awaiting_input = True
            try:
                value = await on_input_request(prompt, password)
            except Exception:
                value = ""
            finally:
                self.awaiting_input = False
            self.kc.input(value if value is not None else "")


class KernelRegistry:
    """Process-wide map of user_id -> KernelSession, with an idle reaper."""

    def __init__(self) -> None:
        self._sessions: dict[int, KernelSession] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None

    async def get(self, user_id: int) -> KernelSession:
        async with self._lock:
            session = self._sessions.get(user_id)
            if session is None:
                await self._evict_if_needed()
                session = KernelSession(user_id)
                self._sessions[user_id] = session
            return session

    async def _evict_if_needed(self) -> None:
        live = [s for s in self._sessions.values() if s.alive]
        while len(live) >= settings.MAX_LIVE_KERNELS:
            oldest = min(live, key=lambda s: s.last_used)
            await oldest.shutdown()
            self._sessions.pop(oldest.user_id, None)
            live = [s for s in self._sessions.values() if s.alive]

    async def shutdown(self, user_id: int) -> None:
        async with self._lock:
            session = self._sessions.pop(user_id, None)
        if session:
            await session.shutdown()

    async def shutdown_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.shutdown()

    def start_reaper(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_loop())

    def stop_reaper(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            self._reaper = None

    async def _reap_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(60)
                cutoff = time.monotonic() - settings.KERNEL_IDLE_TIMEOUT_SEC
                async with self._lock:
                    stale = [
                        s for s in self._sessions.values()
                        if s.alive and s.last_used < cutoff and not s.lock.locked()
                    ]
                    for session in stale:
                        self._sessions.pop(session.user_id, None)
                for session in stale:
                    await session.shutdown()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue


registry = KernelRegistry()
