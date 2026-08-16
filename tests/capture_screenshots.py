"""Build a demo notebook and capture the screenshots used in README.md.

The notebook is assembled over the REST API (deterministic), then the browser
only signs in, runs it, and takes the pictures.

Needs a live server plus Playwright (see dev-requirements.txt):

    .\\run.ps1                                   # in another terminal
    python tests\\capture_screenshots.py docs\\screenshots
"""

import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
EMAIL = f"demo{int(time.time())}@example.com"
PASSWORD = "password123"

SALES_CSV = (
    "month,region,revenue\n"
    "Jan,North,18400\nJan,South,15200\nFeb,North,21050\nFeb,South,16800\n"
    "Mar,North,19700\nMar,South,20400\nApr,North,24300\nApr,South,22150\n"
)

CELLS = [
    ("markdown", "# Sales analysis\nQuarterly revenue, read straight from an uploaded CSV."),
    ("code", "import pandas as pd\n\ndf = pd.read_csv('sales.csv')\ndf.head()"),
    ("code", "totals = df.groupby('region')['revenue'].sum()\nprint(totals)\n"
             "print('grand total:', df.revenue.sum())"),
    ("code", "import matplotlib.pyplot as plt\n\n"
             "pivot = df.pivot(index='month', columns='region', values='revenue')\n"
             "pivot.plot(marker='o', figsize=(7, 3.2))\n"
             "plt.title('Monthly revenue by region')\nplt.ylabel('revenue')\n"
             "plt.tight_layout()\nplt.show()"),
]

# ---------------------------------------------------------------- set-up over the API

with httpx.Client(base_url=BASE, timeout=30) as api:
    assert api.post("/auth/register", json={"email": EMAIL, "password": PASSWORD}).status_code == 201
    api.post("/api/files/upload", files={"files": ("sales.csv", SALES_CSV, "text/csv")})
    api.post("/api/files/mkdir", json={"name": "data"})

    notebook = api.post("/api/notebooks", json={"name": "Sales analysis.ipynb"}).json()
    nb_id = notebook["id"]
    starter = notebook["cells"][0]["id"]
    for cell_type, source in CELLS:
        api.post(f"/api/notebooks/{nb_id}/cells", json={"cell_type": cell_type, "source": source})
    api.delete(f"/api/notebooks/{nb_id}/cells/{starter}")

    # A second notebook so the list page looks lived-in.
    api.post("/api/notebooks", json={"name": "Scratch.ipynb"})

    cells = api.get(f"/api/notebooks/{nb_id}").json()["cells"]
    assert [c["cell_type"] for c in cells] == [t for t, _ in CELLS], cells

# ------------------------------------------------------------------- screenshots

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)

    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "01-login.png"))

    page.fill("#email", EMAIL)
    page.fill("#password", PASSWORD)
    page.click("#submit-btn")
    page.wait_for_url(f"{BASE}/notebooks", timeout=15000)

    page.goto(f"{BASE}/nb/{nb_id}", wait_until="networkidle")
    page.wait_for_function("() => window.__nbReady === true", timeout=30000)
    page.wait_for_timeout(900)

    page.click("#run-all")
    page.wait_for_timeout(1500)
    page.wait_for_function(
        "() => document.querySelectorAll('.cell.running').length === 0", timeout=180000
    )
    page.wait_for_timeout(1200)
    errors = page.locator(".out.error").count()
    assert errors == 0, f"demo notebook raised {errors} error(s)"

    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "03-notebook.png"))

    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "04-rich-output.png"))
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(400)

    page.click("#app-menu-btn")
    page.wait_for_selector("#app-menu:not([hidden])", timeout=5000)
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "05-menu.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    row = page.locator("#file-list li:has-text('sales.csv')")
    row.hover()
    row.locator(".f-menu-btn").click()
    page.wait_for_selector("#file-menu:not([hidden])", timeout=5000)
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "06-files.png"))

    page.click("#file-menu button:has-text('Open / Edit')")
    page.wait_for_selector("#file-modal:not([hidden])", timeout=10000)
    page.wait_for_timeout(1000)
    page.screenshot(path=str(OUT / "07-file-editor.png"))
    page.click("#modal-close")
    page.wait_for_timeout(400)

    page.goto(f"{BASE}/notebooks", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "02-notebooks.png"))

    browser.close()

print(f"screenshots written to {OUT.resolve()}")
for shot in sorted(OUT.glob("*.png")):
    print(f"  {shot.name}  {shot.stat().st_size // 1024} KB")
