"""WebSocket bridge between the notebook UI and the user's kernel.

Streaming matters here: output appears as it is produced, a running cell can be
interrupted, and input() prompts round-trip to the browser.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .config import settings
from .db import get_conn, utcnow
from .kernel import registry
from .security import decode_token

router = APIRouter()

INPUT_WAIT_SEC = 600


class Connection:
    """Per-socket state: one kernel, one running cell at a time."""

    def __init__(self, websocket: WebSocket, user_id: int, notebook_id: int) -> None:
        self.ws = websocket
        self.user_id = user_id
        self.notebook_id = notebook_id
        self.send_lock = asyncio.Lock()
        self.pending_input: asyncio.Future[str] | None = None
        self.current: asyncio.Task | None = None

    async def send(self, payload: dict) -> None:
        async with self.send_lock:
            try:
                await self.ws.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                pass

    # --------------------------------------------------------------- stdin

    async def request_input(self, prompt: str, password: bool) -> str:
        loop = asyncio.get_running_loop()
        self.pending_input = loop.create_future()
        await self.send({"type": "input_request", "prompt": prompt, "password": password})
        try:
            return await asyncio.wait_for(self.pending_input, timeout=INPUT_WAIT_SEC)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return ""
        finally:
            self.pending_input = None

    def deliver_input(self, value: str) -> None:
        if self.pending_input is not None and not self.pending_input.done():
            self.pending_input.set_result(value)

    # ------------------------------------------------------------ execution

    def _save_cell(self, cell_id: int, outputs: list, execution_count: int | None) -> None:
        blob = json.dumps(outputs)
        if len(blob) > settings.MAX_OUTPUT_BYTES_PER_CELL:
            blob = json.dumps(
                [{"output_type": "stream", "name": "stderr", "text": "[output too large to store]"}]
            )
        with get_conn() as conn:
            conn.execute(
                "UPDATE cells SET outputs = ?, execution_count = ?, updated_at = ?"
                " WHERE id = ? AND notebook_id = ?",
                (blob, execution_count, utcnow(), cell_id, self.notebook_id),
            )
            conn.execute(
                "UPDATE notebooks SET updated_at = ? WHERE id = ?", (utcnow(), self.notebook_id)
            )

    async def run_cell(self, cell_id: int, code: str) -> None:
        session = await registry.get(self.user_id)
        outputs: list = []
        execution_count: int | None = None

        async with session.lock:
            if not session.alive:
                await self.send({"type": "status", "state": "starting"})
            try:
                await session.start()
            except Exception as exc:
                await self.send(
                    {"type": "kernel_error", "message": f"Could not start the runtime: {exc}"}
                )
                await self.send({"type": "done", "cell_id": cell_id, "error": True})
                return

            await self.send({"type": "status", "state": "busy"})
            await self.send({"type": "clear_output", "cell_id": cell_id})
            try:
                async for event in session.execute(code, on_input_request=self.request_input):
                    kind = event["type"]
                    if kind == "output":
                        outputs.append(event["output"])
                        await self.send({"type": "output", "cell_id": cell_id, "output": event["output"]})
                    elif kind == "execute_input":
                        execution_count = event["execution_count"]
                        await self.send(
                            {"type": "execute_input", "cell_id": cell_id, "execution_count": execution_count}
                        )
                    elif kind == "clear_output":
                        outputs.clear()
                        await self.send({"type": "clear_output", "cell_id": cell_id})
                    elif kind == "done":
                        execution_count = event.get("execution_count") or execution_count
                        self._save_cell(cell_id, outputs, execution_count)
                        await self.send(
                            {
                                "type": "done",
                                "cell_id": cell_id,
                                "execution_count": execution_count,
                                "error": event.get("error", False),
                                "interrupted": event.get("interrupted", False),
                            }
                        )
            except asyncio.CancelledError:
                self._save_cell(cell_id, outputs, execution_count)
                await self.send({"type": "done", "cell_id": cell_id, "error": True, "interrupted": True})
                raise
            except Exception as exc:
                await self.send({"type": "kernel_error", "message": str(exc)})
                await self.send({"type": "done", "cell_id": cell_id, "error": True})
            finally:
                await self.send({"type": "status", "state": "idle"})


@router.websocket("/ws/kernel/{notebook_id}")
async def kernel_socket(websocket: WebSocket, notebook_id: int) -> None:
    token = websocket.cookies.get(settings.COOKIE_NAME)
    user_id = decode_token(token) if token else None
    if user_id is None:
        await websocket.close(code=4401)
        return

    with get_conn() as conn:
        owned = conn.execute(
            "SELECT id FROM notebooks WHERE id = ? AND user_id = ?", (notebook_id, user_id)
        ).fetchone()
    if owned is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    conn_state = Connection(websocket, int(user_id), notebook_id)
    session = await registry.get(int(user_id))
    await conn_state.send({"type": "status", "state": "idle" if session.alive else "disconnected"})

    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")

            if kind == "execute":
                cell_id = int(message.get("cell_id", 0))
                code = message.get("code", "")
                if conn_state.current and not conn_state.current.done():
                    await conn_state.send(
                        {"type": "busy", "cell_id": cell_id, "message": "A cell is already running."}
                    )
                    continue
                conn_state.current = asyncio.create_task(conn_state.run_cell(cell_id, code))

            elif kind == "input_reply":
                conn_state.deliver_input(str(message.get("value", "")))

            elif kind == "interrupt":
                await session.interrupt()

            elif kind == "restart":
                if conn_state.current and not conn_state.current.done():
                    conn_state.current.cancel()
                await conn_state.send({"type": "status", "state": "starting"})
                try:
                    await session.restart()
                    await conn_state.send({"type": "restarted"})
                    await conn_state.send({"type": "status", "state": "idle"})
                except Exception as exc:
                    await conn_state.send({"type": "kernel_error", "message": str(exc)})

            elif kind == "shutdown":
                if conn_state.current and not conn_state.current.done():
                    conn_state.current.cancel()
                await registry.shutdown(int(user_id))
                await conn_state.send({"type": "status", "state": "disconnected"})

            elif kind == "ping":
                await conn_state.send({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # The kernel deliberately outlives the socket: a page reload keeps your
        # variables. The idle reaper is what eventually collects it.
        if conn_state.current and not conn_state.current.done():
            conn_state.current.cancel()
