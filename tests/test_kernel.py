"""Kernel behaviour: the part that makes cells Colab-like."""

import asyncio

import pytest

from app.kernel import KernelSession, strip_ansi


async def run(session: KernelSession, code: str, timeout: int = 60) -> list[dict]:
    events = []
    async for event in session.execute(code, timeout=timeout):
        events.append(event)
    return events


def outputs(events: list[dict]) -> list[dict]:
    return [e["output"] for e in events if e["type"] == "output"]


def text_of(events: list[dict]) -> str:
    return "".join(
        o.get("text", "") for o in outputs(events) if o["output_type"] == "stream"
    )


@pytest.fixture(scope="module")
def kernel():
    session = KernelSession(user_id=999)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(session.start())
    yield session, loop
    loop.run_until_complete(session.shutdown())
    loop.close()


def test_state_persists_between_cells(kernel):
    session, loop = kernel
    loop.run_until_complete(run(session, "x = 21"))
    events = loop.run_until_complete(run(session, "print(x * 2)"))
    assert text_of(events).strip() == "42"


def test_execute_result_and_execution_count(kernel):
    session, loop = kernel
    events = loop.run_until_complete(run(session, "2 + 3"))
    results = [o for o in outputs(events) if o["output_type"] == "execute_result"]
    assert results and results[0]["data"]["text/plain"].strip() == "5"
    done = [e for e in events if e["type"] == "done"][0]
    assert done["execution_count"] and done["error"] is False


def test_error_output_carries_traceback(kernel):
    session, loop = kernel
    events = loop.run_until_complete(run(session, "1 / 0"))
    errors = [o for o in outputs(events) if o["output_type"] == "error"]
    assert errors and errors[0]["ename"] == "ZeroDivisionError"
    # ANSI colour codes are stripped so the browser can show plain text.
    assert "\x1b[" not in "".join(errors[0]["traceback"])
    assert [e for e in events if e["type"] == "done"][0]["error"] is True


def test_matplotlib_renders_inline_png(kernel):
    session, loop = kernel
    events = loop.run_until_complete(
        run(
            session,
            "import matplotlib\nmatplotlib.use('module://matplotlib_inline.backend_inline')\n"
            "import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\nplt.show()",
            timeout=120,
        )
    )
    images = [
        o for o in outputs(events)
        if o["output_type"] in ("display_data", "execute_result") and "image/png" in o.get("data", {})
    ]
    assert images, f"expected an inline PNG, got {[o['output_type'] for o in outputs(events)]}"


def test_pandas_renders_html_table(kernel):
    session, loop = kernel
    events = loop.run_until_complete(
        run(session, "import pandas as pd\npd.DataFrame({'a': [1, 2], 'b': [3, 4]})", timeout=120)
    )
    html = [
        o for o in outputs(events)
        if o["output_type"] == "execute_result" and "text/html" in o.get("data", {})
    ]
    assert html and "<table" in html[0]["data"]["text/html"]


def test_stdin_answers_input(kernel):
    session, loop = kernel

    async def answer(prompt, password):
        return "ada"

    async def go():
        events = []
        async for event in session.execute("name = input('who? ')\nprint('hi', name)", on_input_request=answer):
            events.append(event)
        return events

    events = loop.run_until_complete(go())
    assert "hi ada" in text_of(events)


def test_cell_timeout_interrupts_the_kernel(kernel):
    session, loop = kernel
    events = loop.run_until_complete(run(session, "while True:\n    pass", timeout=3))
    errors = [o for o in outputs(events) if o["output_type"] == "error"]
    assert any(e["ename"] in ("TimeoutError", "KeyboardInterrupt") for e in errors)
    # The kernel survives the interrupt and still works.
    assert text_of(loop.run_until_complete(run(session, "print('alive')"))).strip() == "alive"


def test_restart_clears_state(kernel):
    session, loop = kernel
    loop.run_until_complete(run(session, "marker = 'before restart'"))
    loop.run_until_complete(session.restart())
    events = loop.run_until_complete(run(session, "print(marker)"))
    errors = [o for o in outputs(events) if o["output_type"] == "error"]
    assert errors and errors[0]["ename"] == "NameError"


def test_strip_ansi():
    assert strip_ansi("\x1b[0;31mZeroDivisionError\x1b[0m") == "ZeroDivisionError"
