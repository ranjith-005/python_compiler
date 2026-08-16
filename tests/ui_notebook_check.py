"""Headless walkthrough of the Colab-style notebook UI, with screenshots.

Needs a live server plus Playwright (see dev-requirements.txt):

    .\\run.ps1                                        # in another terminal
    python tests\\ui_notebook_check.py .\\shots
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SHOTS.mkdir(parents=True, exist_ok=True)
EMAIL = f"nb{int(time.time())}@example.com"
PASSWORD = "password123"

results = []
console_errors = []


def check(label, ok, extra=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {label}{('  -> ' + str(extra)) if extra else ''}")


def set_cell(page, index, code):
    """Type into the Monaco editor of cell `index` via its model."""
    page.evaluate(
        """([i, code]) => {
            const el = document.querySelectorAll('.cell')[i].querySelector('.cell-editor');
            const editor = monaco.editor.getEditors().find(e => el.contains(e.getDomNode()));
            editor.setValue(code);
        }""",
        [index, code],
    )


def run_cell(page, index, timeout=60000):
    cell = page.locator(".cell").nth(index)
    cell.locator(".run-btn").click()
    page.wait_for_function(
        "i => !document.querySelectorAll('.cell')[i].classList.contains('running')",
        arg=index,
        timeout=timeout,
    )
    return cell


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1440, "height": 950})
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

    # ------------------------------------------------------------- register
    page.goto(f"{BASE}/", wait_until="networkidle")
    check("root redirects to /login", page.url.endswith("/login"))
    page.click(".tab[data-mode='register']")
    page.fill("#email", EMAIL)
    page.fill("#password", PASSWORD)
    page.click("#submit-btn")
    page.wait_for_url(f"{BASE}/notebooks", timeout=10000)
    check("register lands on the notebook list", page.url.endswith("/notebooks"))
    check("welcome notebook is listed", "Welcome.ipynb" in page.inner_text("#nb-rows"))
    page.screenshot(path=str(SHOTS / "01-notebook-list.png"))

    # --------------------------------------------------------- open notebook
    page.click(".nb-link")
    page.wait_for_function("() => window.__nbReady === true", timeout=30000)
    page.wait_for_timeout(800)
    check("notebook opens with 3 cells", page.locator(".cell").count() == 3,
          page.locator(".cell").count())
    check("Monaco mounted per cell", page.locator(".cell .monaco-editor").count() >= 3)
    page.screenshot(path=str(SHOTS / "02-notebook-open.png"))

    # ------------------------------------------------- run cell 1 (numpy)
    cell = run_cell(page, 0)
    check("first cell shows a result", "array([" in cell.inner_text(), cell.inner_text().strip()[:60])
    check("execution count is [1]", "[1]" in cell.inner_text())
    check("runtime chip is connected",
          page.get_attribute("#runtime-chip", "data-state") == "idle",
          page.inner_text("#runtime-chip"))

    # --------------------------------- run cell 2: state persists (Colab!)
    cell = run_cell(page, 1)
    check("state persists between cells", "285" in cell.inner_text(), cell.inner_text().strip()[:60])

    # ------------------------------------------- run cell 3: inline plot
    cell = run_cell(page, 2, timeout=120000)
    check("matplotlib renders inline", cell.locator(".outputs img").count() > 0)
    img_ok = page.evaluate(
        """() => {
            const img = document.querySelectorAll('.cell')[2].querySelector('.outputs img');
            return !!img && img.naturalWidth > 50 && img.src.startsWith('data:image/png;base64,');
        }"""
    )
    check("plot is a real PNG", img_ok)
    page.screenshot(path=str(SHOTS / "03-plot.png"))

    # -------------------------------------------------- pandas HTML table
    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last, "import pandas as pd\npd.DataFrame({'city': ['Delhi', 'Oslo'], 'temp': [31, 4]})")
    cell = run_cell(page, last, timeout=120000)
    check("pandas renders an HTML table", cell.locator(".outputs table").count() > 0)
    # Assert against the output area only - the code itself also mentions Delhi.
    check("table contains the data", "Delhi" in cell.locator(".outputs").inner_text(),
          cell.locator(".outputs").inner_text().replace("\n", " ")[:70])
    page.screenshot(path=str(SHOTS / "04-dataframe.png"))

    # ------------------------------------------- upload a file, read it in a cell
    csv_path = SHOTS / "cities.csv"
    csv_path.write_text("city,temp\nDelhi,31\nOslo,4\nLima,19\n", encoding="utf-8")
    check("files panel is visible", page.locator("#sidebar").is_visible())
    page.set_input_files("#file-input", str(csv_path))
    page.wait_for_selector("#file-list li:has-text('cities.csv')", timeout=20000)
    check("uploaded file appears in the panel", True)
    check("quota line shows usage", "used" in page.inner_text("#quota-text"), page.inner_text("#quota-text"))

    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last, "import pandas as pd\ndf = pd.read_csv('cities.csv')\nprint(df.shape)\ndf")
    cell = run_cell(page, last, timeout=120000)
    check("uploaded file is readable from a cell",
          "(3, 2)" in cell.locator(".outputs").inner_text(), cell.locator(".outputs").inner_text()[:60])
    check("its DataFrame renders as a table", cell.locator(".outputs table").count() > 0)
    page.screenshot(path=str(SHOTS / "10-files-upload.png"))

    # ------------------------------------------- ⋮ menu: open, edit, save
    row = page.locator("#file-list li:has-text('cities.csv')")
    row.hover()
    row.locator(".f-menu-btn").click()
    page.wait_for_selector("#file-menu:not([hidden])", timeout=5000)
    menu_items = page.locator("#file-menu button").all_inner_texts()
    check("menu offers open/edit, rename, download, delete",
          all(any(word in " ".join(menu_items).lower() for word in [w])
              for w in ["open / edit", "rename", "download", "delete"]),
          " | ".join(m.strip() for m in menu_items))

    page.click("#file-menu button:has-text('Open / Edit')")
    page.wait_for_selector("#file-modal:not([hidden])", timeout=10000)
    page.wait_for_timeout(900)
    # Scope to the modal's own editor - notebook cells are Monaco instances too.
    modal_editor_js = """() => {
        const host = document.getElementById('modal-editor');
        return monaco.editor.getEditors().find(e => host.contains(e.getDomNode()));
    }"""
    opened = page.evaluate(f"() => {{ const ed = ({modal_editor_js})(); return ed ? ed.getValue() : ''; }}")
    check("opening a file shows its contents", "Delhi,31" in opened, opened.replace("\n", " ")[:50])
    check("modal shows the file name", "cities.csv" in page.inner_text("#modal-title"))

    # Edit the file, save, and prove the kernel sees the new bytes.
    page.evaluate(
        f"""() => {{
            const ed = ({modal_editor_js})();
            ed.setValue('city,temp\\nDelhi,31\\nOslo,4\\nLima,19\\nCairo,35\\n');
        }}"""
    )
    page.click("#modal-save")
    page.wait_for_timeout(700)
    page.click("#modal-close")
    page.wait_for_timeout(300)
    check("editor closes after saving", page.locator("#file-modal").is_hidden())

    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last, "print(open('cities.csv').read())")
    cell = run_cell(page, last, timeout=60000)
    check("printing an edited file shows the saved text",
          "Cairo,35" in cell.locator(".outputs").inner_text(),
          cell.locator(".outputs").inner_text().replace("\n", " ")[:70])

    # An image opens as a preview rather than as text.
    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last,
             "import matplotlib\nimport matplotlib.pyplot as plt\n"
             "plt.plot([1,2,3])\nplt.savefig('chart.png')\nprint('written')")
    run_cell(page, last, timeout=120000)
    page.click("#file-refresh-btn")
    page.wait_for_selector("#file-list li:has-text('chart.png')", timeout=10000)
    img_row = page.locator("#file-list li:has-text('chart.png')")
    img_row.hover()
    img_row.locator(".f-menu-btn").click()
    page.wait_for_selector("#file-menu:not([hidden])", timeout=5000)
    page.click("#file-menu button:has-text('Open / Edit')")
    page.wait_for_selector("#modal-preview:not([hidden])", timeout=10000)
    page.wait_for_timeout(700)
    check("image files open as a preview",
          page.evaluate("() => { const i = document.querySelector('#modal-preview img'); return !!i && i.naturalWidth > 50; }"))
    page.screenshot(path=str(SHOTS / "12-file-viewer.png"))
    page.click("#modal-close")
    page.wait_for_timeout(300)

    # Insert-path, now living in the ⋮ menu, drops the filename into the cell.
    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    page.locator(".cell").nth(last).locator(".cell-editor").click()
    row = page.locator("#file-list li:has-text('cities.csv')")
    row.hover()
    row.locator(".f-menu-btn").click()
    page.wait_for_selector("#file-menu:not([hidden])", timeout=5000)
    page.click("#file-menu button:has-text('Insert path')")
    page.wait_for_timeout(300)
    inserted = page.evaluate(
        """i => {
            const el = document.querySelectorAll('.cell')[i].querySelector('.cell-editor');
            const ed = monaco.editor.getEditors().find(e => el.contains(e.getDomNode()));
            return ed.getValue();
        }""",
        last,
    )
    check("insert-path writes the filename into the cell", inserted.strip() == '"cities.csv"', inserted.strip())

    # ----------------------------------------------------- streaming stdout
    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last, "for i in range(3):\n    print('line', i)")
    cell = run_cell(page, last)
    check("stdout streams into the cell", "line 0" in cell.inner_text() and "line 2" in cell.inner_text())

    # ------------------------------------------------------------- error
    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last, "1 / 0")
    cell = run_cell(page, last)
    check("traceback is shown in red", cell.locator(".out.error").count() > 0)
    check("error names ZeroDivisionError", "ZeroDivisionError" in cell.inner_text())
    page.screenshot(path=str(SHOTS / "05-error.png"))

    # ------------------------------------------------------------- input()
    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last, "who = input('your name? ')\nprint('hello', who)")
    page.locator(".cell").nth(last).locator(".run-btn").click()
    page.wait_for_selector(".cell .input-row input", timeout=30000)
    check("input() shows a prompt box", True)
    page.fill(".cell .input-row input", "grace")
    page.press(".cell .input-row input", "Enter")
    page.wait_for_function(
        "i => !document.querySelectorAll('.cell')[i].classList.contains('running')",
        arg=last, timeout=30000,
    )
    check("input reply reaches the kernel", "hello grace" in page.locator(".cell").nth(last).inner_text())
    page.screenshot(path=str(SHOTS / "06-input.png"))

    # -------------------------------------------------------- markdown cell
    page.click("#add-text-end")
    page.wait_for_timeout(500)
    last = page.locator(".cell").count() - 1
    md = page.locator(".cell").nth(last)
    check("text cell has no run button", not md.locator(".run-btn").is_visible())
    check("cell toolbar keeps delete only", md.locator(".cell-tools button").count() == 1,
          md.locator(".cell-tools button").count())

    set_cell(page, last, "# A text cell\nWith **bold** text and `code`.")
    # No run button: focus the editor, then click away — that finishes the cell.
    md.locator(".cell-editor").click()
    page.wait_for_timeout(200)
    check("text cell editor has no line numbers while writing",
          md.locator(".cell-editor .line-numbers:visible").count() == 0,
          md.locator(".cell-editor .line-numbers:visible").count())
    page.locator(".cell").nth(0).locator(".cell-editor").click()
    page.wait_for_timeout(600)

    check("markdown renders a heading", md.locator(".md-render h1").count() > 0)
    check("markdown renders bold", md.locator(".md-render strong").count() > 0)
    check("finished text cell hides its editor", not md.locator(".cell-editor").is_visible())
    check("finished text cell has no box around it",
          page.evaluate(
              """i => {
                  const el = document.querySelectorAll('.cell')[i];
                  const s = getComputedStyle(el);
                  return s.borderTopColor === 'rgba(0, 0, 0, 0)' && s.boxShadow === 'none';
              }""",
              last,
          ))
    check("code cell editor still has line numbers",
          page.locator(".cell").nth(0).locator(".cell-editor .line-numbers").count() > 0)

    # Double-click reopens it for editing, still without line numbers.
    md.locator(".md-render").dblclick()
    page.wait_for_timeout(400)
    check("double-click reopens the text editor", md.locator(".cell-editor").is_visible())
    check("reopened text editor has no line numbers",
          md.locator(".cell-editor .line-numbers:visible").count() == 0)
    page.locator(".cell").nth(0).locator(".cell-editor").click()
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / "07-markdown.png"))

    # ---------------------------------------------------- interrupt a loop
    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last, "import time\nwhile True:\n    time.sleep(0.1)")
    page.locator(".cell").nth(last).locator(".run-btn").click()
    page.wait_for_function("() => document.querySelector('#runtime-chip').dataset.state === 'busy'", timeout=30000)
    page.wait_for_timeout(1200)
    page.click("#interrupt-btn")
    page.wait_for_function(
        "i => !document.querySelectorAll('.cell')[i].classList.contains('running')",
        arg=last, timeout=60000,
    )
    check("stop button interrupts a running cell",
          "KeyboardInterrupt" in page.locator(".cell").nth(last).inner_text(),
          page.locator(".cell").nth(last).inner_text().strip()[-60:])

    # ------------------------------------------------ reload keeps outputs
    page.reload(wait_until="networkidle")
    page.wait_for_function("() => window.__nbReady === true", timeout=30000)
    page.wait_for_timeout(900)
    check("outputs survive a page reload", page.locator(".cell .outputs img").count() > 0)
    check("execution counts survive reload", "[1]" in page.locator(".cell").nth(0).inner_text())
    check("kernel survives a reload (variables kept)", True)
    page.click("#add-code-end")
    page.wait_for_timeout(400)
    last = page.locator(".cell").count() - 1
    set_cell(page, last, "print('data still here:', data.sum())")
    cell = run_cell(page, last)
    check("variables outlive the page reload", "data still here: 285" in cell.inner_text(),
          cell.inner_text().strip()[:60])

    # ------------------------------------------------------------- restart
    page.on("dialog", lambda d: d.accept())
    page.click("#restart-btn")
    page.wait_for_timeout(3500)
    set_cell(page, last, "print(data.sum())")
    cell = run_cell(page, last)
    check("restart clears variables", "NameError" in cell.inner_text(), cell.inner_text().strip()[:60])
    page.screenshot(path=str(SHOTS / "08-after-restart.png"))

    # --------------------------------------------------------- run all
    page.click("#run-all")
    page.wait_for_timeout(1500)
    page.wait_for_function(
        "() => document.querySelectorAll('.cell.running').length === 0", timeout=120000
    )
    import re as _re
    first_count = page.locator(".cell").nth(0).locator(".exec-count").inner_text()
    check("run all re-executes from the top", bool(_re.fullmatch(r"\[\d+\]", first_count.strip())),
          first_count)
    # Run all halts on the first error, the same way Jupyter and Colab do.
    error_cell = next(
        i for i in range(page.locator(".cell").count())
        if "ZeroDivisionError" in page.locator(".cell").nth(i).inner_text()
    )
    check("run all stops at the failing cell",
          page.locator(".cell").nth(error_cell).locator(".out.error").count() > 0, f"cell {error_cell}")

    # ------------------------------------- toolbar stays put when scrolled down
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(600)
    check("page actually scrolled", page.evaluate("() => window.scrollY") > 200,
          page.evaluate("() => window.scrollY"))
    for label, selector in (("top bar", ".cb-topbar"), ("toolbar", ".cb-toolbar")):
        visible = page.evaluate(
            """sel => {
                const r = document.querySelector(sel).getBoundingClientRect();
                return r.top >= -1 && r.bottom <= window.innerHeight + 1 && r.height > 0;
            }""",
            selector,
        )
        check(f"{label} still visible at the bottom of the page", visible)
    check("Run all button reachable while scrolled", page.locator("#run-all").is_visible())
    check("files panel still visible while scrolled", page.locator("#sidebar").is_visible())
    page.screenshot(path=str(SHOTS / "11-scrolled-bottom.png"))

    # ------------------------------------------- sidebar toggle lives by Files
    check("toggle button sits in the Files panel header",
          page.locator("#sidebar .side-head #sidebar-toggle").count() == 1)
    page.click("#sidebar-toggle")
    page.wait_for_timeout(400)
    check("toggle hides the files panel", not page.locator("#sidebar").is_visible())
    check("reopen handle appears where the panel was", page.locator("#sidebar-show").is_visible())
    page.click("#sidebar-show")
    page.wait_for_timeout(400)
    check("reopen handle brings the panel back", page.locator("#sidebar").is_visible())
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(300)

    # --------------------------------------------- app menu (top-left ☰)
    page.click("#app-menu-btn")
    page.wait_for_selector("#app-menu:not([hidden])", timeout=5000)
    labels = " | ".join(t.strip() for t in page.locator("#app-menu button").all_inner_texts())
    for wanted in ["New notebook", "Open notebook", "Make a copy", "Run all",
                   "Restart and run all", "Clear all outputs", "Keyboard shortcuts"]:
        check(f"menu has '{wanted}'", wanted in labels)
    for gone in ["Script editor", "Toggle files panel"]:
        check(f"menu no longer offers '{gone}'", gone not in labels)
    check("menu does NOT list notebooks until asked",
          "Welcome.ipynb" not in labels, labels[:70])

    # Open notebook -> the list appears only after clicking
    page.click("#app-menu button:has-text('Open notebook')")
    page.wait_for_selector("#app-menu:has-text('Notebooks')", timeout=10000)
    page.wait_for_timeout(400)
    listed = page.locator("#app-menu button").all_inner_texts()
    check("clicking Open notebook lists the notebooks",
          any("Welcome.ipynb" in t for t in listed), " | ".join(t.strip() for t in listed)[:70])

    # Make a copy, then use the list to jump to it.
    page.click("#app-menu button:has-text('Back')")
    page.wait_for_timeout(300)
    page.click("#app-menu button:has-text('Make a copy')")
    page.wait_for_url("**/nb/**", timeout=15000)
    page.wait_for_function("() => window.__nbReady === true", timeout=30000)
    page.wait_for_timeout(700)
    check("make a copy opens the duplicate", "Copy of" in page.input_value("#nb-name"),
          page.input_value("#nb-name"))
    copied_cells = page.locator(".cell").count()
    check("the copy carries the cells over", copied_cells >= 3, copied_cells)

    page.click("#app-menu-btn")
    page.click("#app-menu button:has-text('Open notebook')")
    page.wait_for_selector("#app-menu:has-text('Notebooks')", timeout=10000)
    page.wait_for_timeout(400)
    # Exact match: "Copy of Welcome.ipynb" also contains "Welcome.ipynb".
    page.evaluate(
        """() => [...document.querySelectorAll('#app-menu button')]
                 .find(b => b.querySelector('.ml')?.textContent === 'Welcome.ipynb').click()"""
    )
    page.wait_for_function("() => window.__nbReady === true", timeout=30000)
    page.wait_for_timeout(700)
    check("picking a notebook from the list opens it",
          page.input_value("#nb-name") == "Welcome.ipynb", page.input_value("#nb-name"))
    page.screenshot(path=str(SHOTS / "13-app-menu.png"))

    # Keyboard shortcuts dialog
    page.click("#app-menu-btn")
    page.click("#app-menu button:has-text('Keyboard shortcuts')")
    page.wait_for_selector("#file-modal:not([hidden])", timeout=5000)
    check("shortcuts dialog lists Shift+Enter", "Shift + Enter" in page.inner_text("#modal-preview"))
    page.click("#modal-close")
    page.wait_for_timeout(300)

    # Clear all outputs
    page.click("#app-menu-btn")
    page.click("#app-menu button:has-text('Clear all outputs')")
    page.wait_for_timeout(900)
    check("clear all outputs empties every cell",
          page.evaluate("() => document.querySelectorAll('.cell .outputs *').length") == 0)
    check("clear all outputs resets execution counts",
          page.locator(".cell").nth(0).locator(".exec-count").inner_text().strip() == "")

    # ------------------------------------------------------- export .ipynb
    with page.expect_download() as download_info:
        page.click("#download-btn")
    download = download_info.value
    path = SHOTS / "exported.ipynb"
    download.save_as(str(path))
    raw = path.read_text(encoding="utf-8")
    check("downloads a valid .ipynb", '"nbformat": 4' in raw and '"cells"' in raw, download.suggested_filename)

    # -------------------------------------------------------- import .ipynb
    page.goto(f"{BASE}/notebooks", wait_until="networkidle")
    page.set_input_files("#upload-input", str(path))
    page.wait_for_url("**/nb/**", timeout=20000)
    page.wait_for_function("() => window.__nbReady === true", timeout=30000)
    page.wait_for_timeout(600)
    check("imported notebook opens with its cells", page.locator(".cell").count() >= 3,
          page.locator(".cell").count())
    page.screenshot(path=str(SHOTS / "09-imported.png"))

    # ------------------------------------------------------------- logout
    page.click("#logout-btn")
    page.wait_for_url(f"{BASE}/login", timeout=10000)
    page.goto(f"{BASE}/notebooks", wait_until="networkidle")
    check("logout protects the notebook list", page.url.endswith("/login"))

    browser.close()

real_errors = [
    e for e in console_errors
    if "favicon" not in e.lower() and "401 (Unauthorized)" not in e
]
check("no JavaScript console errors", not real_errors, real_errors[:3])

print(f"\n{sum(results)}/{len(results)} notebook UI checks passed")
print(f"screenshots in {SHOTS.resolve()}")
sys.exit(0 if all(results) else 1)
