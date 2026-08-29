// Colab-style notebook: Monaco cells over a live IPython kernel.
(function () {
  const CONFIG = JSON.parse(document.getElementById("nb-config").textContent);
  const NB = CONFIG.notebookId;
  const CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs";

  const cellsEl = document.getElementById("cells");
  const chip = document.getElementById("runtime-chip");
  const chipLabel = document.getElementById("runtime-label");
  const toastEl = document.getElementById("toast");

  let monacoApi = null;
  let socket = null;
  let socketReady = null;
  let reconnectDelay = 500;
  const cells = new Map(); // id -> {data, dom, editor, outputsEl, pendingResolve}
  let order = [];
  let selectedId = null;
  let runningCellId = null;

  /* ─────────────────────────────── utils ─────────────────────────────── */

  let toastTimer = null;
  function toast(message, isError) {
    toastEl.textContent = message;
    toastEl.classList.toggle("err", !!isError);
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toastEl.hidden = true), 3000);
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (res.status === 401) {
      window.location.href = "/login";
      throw new Error("unauthenticated");
    }
    const data = res.status === 204 ? null : await res.json().catch(() => null);
    if (!res.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
    }
    return data;
  }

  function setRuntime(state, label) {
    chip.dataset.state = state;
    chipLabel.textContent = label;
  }

  // If a CDN library is unavailable, degrade to plain text rather than
  // rendering nothing (or throwing and taking the whole notebook down).
  function renderRichHtml(container, html) {
    if (window.DOMPurify) {
      container.innerHTML = DOMPurify.sanitize(html, { USE_PROFILES: { html: true, svg: true } });
    } else {
      container.textContent = html;
    }
  }

  function renderMarkdownInto(container, source) {
    if (window.marked) {
      renderRichHtml(container, marked.parse(source));
    } else {
      container.textContent = source;
    }
  }

  /* ──────────────────────────── websocket ────────────────────────────── */

  function connect() {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${window.location.host}/ws/kernel/${NB}`);
    socketReady = new Promise((resolve) => {
      socket.addEventListener("open", () => {
        reconnectDelay = 500;
        resolve();
      }, { once: true });
    });

    socket.addEventListener("message", (event) => handleMessage(JSON.parse(event.data)));
    socket.addEventListener("close", (event) => {
      setRuntime("disconnected", "Not connected");
      if (event.code === 4401) {
        window.location.href = "/login";
        return;
      }
      if (runningCellId !== null) finishCell(runningCellId, true);
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    });
    socket.addEventListener("error", () => setRuntime("error", "Connection error"));
  }

  async function send(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      await socketReady;
    }
    socket.send(JSON.stringify(payload));
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case "status":
        if (msg.state === "busy") setRuntime("busy", "Running");
        else if (msg.state === "starting") setRuntime("starting", "Connecting to runtime…");
        else if (msg.state === "idle") setRuntime("idle", "Connected");
        else setRuntime("disconnected", "Not connected");
        break;
      case "execute_input": {
        const cell = cells.get(msg.cell_id);
        if (cell) setExecCount(cell, msg.execution_count);
        break;
      }
      case "clear_output": {
        const cell = cells.get(msg.cell_id);
        if (cell) cell.outputsEl.innerHTML = "";
        break;
      }
      case "output": {
        const cell = cells.get(msg.cell_id);
        if (cell) renderOutput(cell.outputsEl, msg.output);
        break;
      }
      case "input_request":
        promptForInput(msg.prompt, msg.password);
        break;
      case "done":
        finishCell(msg.cell_id, msg.error, msg.execution_count);
        break;
      case "busy":
        toast(msg.message || "A cell is already running.", true);
        break;
      case "restarted":
        cells.forEach((cell) => setExecCount(cell, null));
        toast("Runtime restarted — all variables cleared");
        break;
      case "kernel_error":
        toast(msg.message, true);
        setRuntime("error", "Runtime error");
        break;
    }
  }

  function promptForInput(prompt, password) {
    const cell = cells.get(runningCellId);
    if (!cell) return;
    const row = document.createElement("div");
    row.className = "input-row";
    const label = document.createElement("span");
    label.className = "prompt";
    label.textContent = prompt || "Input:";
    const input = document.createElement("input");
    input.type = password ? "password" : "text";
    const submit = () => {
      send({ type: "input_reply", value: input.value });
      label.textContent = `${prompt || "Input:"} ${password ? "••••" : input.value}`;
      row.replaceChildren(label);
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        submit();
      }
    });
    row.append(label, input);
    cell.outputsEl.appendChild(row);
    input.focus();
  }

  /* ───────────────────────────── rendering ───────────────────────────── */

  function renderOutput(container, output) {
    const kind = output.output_type;

    if (kind === "stream") {
      const last = container.lastElementChild;
      const cls = output.name === "stderr" ? "out stderr" : "out stream";
      if (last && last.className === cls) {
        last.textContent += output.text;
        return;
      }
      const pre = document.createElement("div");
      pre.className = cls;
      pre.textContent = output.text;
      container.appendChild(pre);
      return;
    }

    if (kind === "error") {
      const box = document.createElement("div");
      box.className = "out error";
      const trace = (output.traceback || []).join("\n");
      box.textContent = trace || `${output.ename}: ${output.evalue}`;
      container.appendChild(box);
      return;
    }

    const data = output.data || {};
    if (data["image/png"] || data["image/jpeg"]) {
      const wrap = document.createElement("div");
      wrap.className = "out";
      const img = document.createElement("img");
      const mime = data["image/png"] ? "image/png" : "image/jpeg";
      const raw = data["image/png"] || data["image/jpeg"];
      img.src = `data:${mime};base64,${String(raw).replace(/\s/g, "")}`;
      wrap.appendChild(img);
      container.appendChild(wrap);
      return;
    }
    if (data["image/svg+xml"]) {
      const wrap = document.createElement("div");
      wrap.className = "out";
      renderRichHtml(wrap, data["image/svg+xml"]);
      container.appendChild(wrap);
      return;
    }
    if (data["text/html"]) {
      const wrap = document.createElement("div");
      wrap.className = "out html";
      renderRichHtml(wrap, data["text/html"]);
      container.appendChild(wrap);
      return;
    }
    if (data["text/markdown"]) {
      const wrap = document.createElement("div");
      wrap.className = "out html";
      renderMarkdownInto(wrap, data["text/markdown"]);
      container.appendChild(wrap);
      return;
    }
    if (data["text/plain"]) {
      const pre = document.createElement("div");
      pre.className = "out";
      pre.textContent = data["text/plain"];
      container.appendChild(pre);
    }
  }

  function setExecCount(cell, count) {
    cell.data.execution_count = count ?? null;
    if (cell.countEl) {
      cell.countEl.textContent = count ? `[${count}]` : "";
    }
  }

  /* ─────────────────────────────── cells ─────────────────────────────── */

  function fitEditor(cell) {
    if (!cell.editor) return;
    const height = Math.max(cell.editor.getContentHeight(), 19) + 14;
    cell.editorEl.style.height = `${height}px`;
    cell.editor.layout({ width: cell.editorEl.clientWidth, height });
  }

  const saveState = document.getElementById("save-state");
  let saveStateTimer = null;
  function showSaveState(text, sticky) {
    saveState.textContent = text;
    clearTimeout(saveStateTimer);
    if (!sticky) saveStateTimer = setTimeout(() => (saveState.textContent = ""), 1800);
  }

  const saveTimers = new Map();
  function scheduleSave(cellId) {
    clearTimeout(saveTimers.get(cellId));
    showSaveState("Editing…", true);
    saveTimers.set(
      cellId,
      setTimeout(async () => {
        const cell = cells.get(cellId);
        if (!cell) return;
        const source = cell.editor ? cell.editor.getValue() : cell.data.source;
        cell.data.source = source;
        try {
          await api(`/api/notebooks/${NB}/cells/${cellId}`, {
            method: "PUT",
            body: JSON.stringify({ source }),
          });
          showSaveState("Saved");
        } catch (err) {
          if (err.message !== "unauthenticated") {
            showSaveState("Not saved", true);
            toast(`Could not save: ${err.message}`, true);
          }
        }
      }, 700)
    );
  }

  function selectCell(cellId) {
    selectedId = cellId;
    cells.forEach((cell, id) => cell.dom.classList.toggle("selected", id === cellId));
  }

  function buildCell(data) {
    const dom = document.createElement("div");
    dom.className = `cell ${data.cell_type}`;
    dom.dataset.id = String(data.id);

    const isMarkdown = data.cell_type === "markdown";

    const gutter = document.createElement("div");
    gutter.className = "cell-gutter";
    const runBtn = document.createElement("button");
    runBtn.className = "run-btn";
    runBtn.title = "Run cell (Shift+Enter)";
    runBtn.textContent = "▶";
    // Text cells have nothing to run - they render when you click away.
    if (isMarkdown) runBtn.hidden = true;
    const countEl = document.createElement("span");
    countEl.className = "exec-count";
    countEl.textContent = data.execution_count ? `[${data.execution_count}]` : "";
    gutter.append(runBtn, countEl);

    const body = document.createElement("div");
    body.className = "cell-body";
    const editorEl = document.createElement("div");
    editorEl.className = "cell-editor";
    const rendered = document.createElement("div");
    rendered.className = "md-render";
    const outputsEl = document.createElement("div");
    outputsEl.className = "outputs";
    body.append(editorEl, rendered, outputsEl);

    const tools = document.createElement("div");
    tools.className = "cell-tools";
    const del = document.createElement("button");
    del.className = "danger"; del.textContent = "🗑"; del.title = "Delete cell";
    tools.append(del);

    dom.append(gutter, body, tools);

    const cell = { data, dom, editorEl, rendered, outputsEl, countEl, editor: null, editing: false };
    cells.set(data.id, cell);

    runBtn.addEventListener("click", () => runCell(data.id));
    del.addEventListener("click", () => deleteCell(data.id));
    dom.addEventListener("mousedown", () => selectCell(data.id));

    (data.outputs || []).forEach((output) => renderOutput(outputsEl, output));

    if (isMarkdown) {
      renderMarkdown(cell);
      rendered.addEventListener("dblclick", () => editMarkdown(cell));
    } else {
      mountEditor(cell);
      rendered.style.display = "none";
    }
    return cell;
  }

  function mountEditor(cell) {
    // Text cells are prose, not code: no line numbers or gutter.
    const isMarkdown = cell.data.cell_type === "markdown";
    const language = isMarkdown ? "markdown" : "python";
    cell.editor = monacoApi.editor.create(cell.editorEl, {
      value: cell.data.source || "",
      language,
      theme: "colab-light",
      automaticLayout: false,
      fontFamily: '"Roboto Mono", "Cascadia Mono", Consolas, monospace',
      fontSize: 13.5,
      lineHeight: 20,
      tabSize: 4,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      lineNumbers: isMarkdown ? "off" : "on",
      lineNumbersMinChars: isMarkdown ? 0 : 3,
      lineDecorationsWidth: isMarkdown ? 0 : 10,
      glyphMargin: false,
      folding: false,
      renderLineHighlight: "none",
      overviewRulerLanes: 0,
      scrollbar: { vertical: "hidden", alwaysConsumeMouseWheel: false },
      padding: { top: 8, bottom: 8 },
      wordWrap: "on",
    });
    cell.editor.onDidContentSizeChange(() => fitEditor(cell));
    cell.editor.onDidChangeModelContent(() => scheduleSave(cell.data.id));
    cell.editor.onDidFocusEditorText(() => selectCell(cell.data.id));
    if (isMarkdown) {
      // Clicking away finishes a text cell - there is no run button to press.
      cell.editor.onDidBlurEditorText(() => {
        cell.data.source = cell.editor.getValue();
        renderMarkdown(cell);
      });
    }
    cell.editor.addCommand(monacoApi.KeyMod.Shift | monacoApi.KeyCode.Enter, () =>
      runCellAndAdvance(cell.data.id)
    );
    cell.editor.addCommand(monacoApi.KeyMod.CtrlCmd | monacoApi.KeyCode.Enter, () =>
      runCell(cell.data.id)
    );
    fitEditor(cell);
  }

  function renderMarkdown(cell) {
    const source = cell.data.source || "";
    if (source.trim()) {
      renderMarkdownInto(cell.rendered, source);
    } else {
      cell.rendered.innerHTML = '<span class="md-empty">Empty text cell — double-click to edit</span>';
    }
    cell.rendered.style.display = "";
    cell.editorEl.style.display = "none";
    cell.editing = false;
    cell.dom.classList.remove("editing");
  }

  function editMarkdown(cell) {
    cell.editorEl.style.display = "";
    cell.rendered.style.display = "none";
    cell.editing = true;
    cell.dom.classList.add("editing");
    if (!cell.editor) mountEditor(cell);
    fitEditor(cell);
    cell.editor.focus();
  }

  /* ───────────────────────────── execution ───────────────────────────── */

  function finishCell(cellId, error, executionCount) {
    const cell = cells.get(cellId);
    if (cell) {
      cell.dom.classList.remove("running");
      if (executionCount) setExecCount(cell, executionCount);
      if (cell.pendingResolve) {
        cell.pendingResolve(!error);
        cell.pendingResolve = null;
      }
    }
    if (runningCellId === cellId) runningCellId = null;
  }

  function runCell(cellId) {
    const cell = cells.get(cellId);
    if (!cell) return Promise.resolve(false);

    if (cell.data.cell_type === "markdown") {
      cell.data.source = cell.editor ? cell.editor.getValue() : cell.data.source;
      scheduleSave(cellId);
      renderMarkdown(cell);
      return Promise.resolve(true);
    }

    const code = cell.editor ? cell.editor.getValue() : cell.data.source;
    cell.data.source = code;
    scheduleSave(cellId);
    cell.outputsEl.innerHTML = "";
    cell.dom.classList.add("running");
    cell.countEl.textContent = "[*]";
    runningCellId = cellId;

    const done = new Promise((resolve) => {
      cell.pendingResolve = resolve;
    });
    send({ type: "execute", cell_id: cellId, code });
    return done;
  }

  async function runCellAndAdvance(cellId) {
    await runCell(cellId);
    const index = order.indexOf(cellId);
    const next = order[index + 1];
    if (next !== undefined) {
      selectCell(next);
      const cell = cells.get(next);
      if (cell && cell.editor && cell.editorEl.style.display !== "none") cell.editor.focus();
    } else {
      addCell("code");
    }
  }

  async function runAll() {
    for (const cellId of [...order]) {
      const cell = cells.get(cellId);
      if (!cell || cell.data.cell_type !== "code") continue;
      const ok = await runCell(cellId);
      if (!ok) {
        toast("Run all stopped — a cell raised an error", true);
        break;
      }
    }
  }

  /* ─────────────────────────── cell management ───────────────────────── */

  /** Hover strip between cells: Colab's "+ Code / + Text" affordance. */
  function refreshInsertStrips() {
    cellsEl.querySelectorAll(".cell-insert").forEach((node) => node.remove());
    order.forEach((cellId, index) => {
      const strip = document.createElement("div");
      strip.className = "cell-insert";
      const code = document.createElement("button");
      code.textContent = "+ Code";
      code.addEventListener("click", () => addCell("code", index));
      const text = document.createElement("button");
      text.textContent = "+ Text";
      text.addEventListener("click", () => addCell("markdown", index));
      strip.append(code, text);
      cellsEl.insertBefore(strip, cells.get(cellId).dom);
    });
  }

  async function addCell(cellType, position) {
    try {
      const insertAt =
        position !== undefined
          ? position
          : selectedId !== null
          ? order.indexOf(selectedId) + 1
          : order.length;
      const data = await api(`/api/notebooks/${NB}/cells`, {
        method: "POST",
        body: JSON.stringify({ cell_type: cellType, source: "", position: insertAt }),
      });
      const cell = buildCell({ ...data, outputs: [] });
      const referenceId = order[insertAt];
      cellsEl.insertBefore(cell.dom, referenceId !== undefined ? cells.get(referenceId).dom : null);
      order.splice(insertAt, 0, data.id);
      refreshInsertStrips();
      selectCell(data.id);
      if (cellType === "markdown") editMarkdown(cell);
      else if (cell.editor) cell.editor.focus();
      fitEditor(cell);
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  async function deleteCell(cellId) {
    if (order.length === 1) return toast("A notebook needs at least one cell.", true);
    try {
      await api(`/api/notebooks/${NB}/cells/${cellId}`, { method: "DELETE" });
      const cell = cells.get(cellId);
      if (cell) {
        if (cell.editor) cell.editor.dispose();
        cell.dom.remove();
      }
      cells.delete(cellId);
      order = order.filter((id) => id !== cellId);
      refreshInsertStrips();
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  async function moveCell(cellId, delta) {
    const index = order.indexOf(cellId);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= order.length) return;
    order.splice(index, 1);
    order.splice(target, 0, cellId);
    const cell = cells.get(cellId);
    const afterId = order[target + 1];
    cellsEl.insertBefore(cell.dom, afterId !== undefined ? cells.get(afterId).dom : null);
    refreshInsertStrips();
    try {
      await api(`/api/notebooks/${NB}/reorder`, {
        method: "POST",
        body: JSON.stringify({ cell_ids: order }),
      });
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  /* ──────────────────────────── files panel ──────────────────────────── */

  const fileEls = {
    sidebar: document.getElementById("sidebar"),
    list: document.getElementById("file-list"),
    empty: document.getElementById("file-empty"),
    crumbs: document.getElementById("file-crumbs"),
    input: document.getElementById("file-input"),
    quotaFill: document.getElementById("quota-fill"),
    quotaText: document.getElementById("quota-text"),
    overlay: document.getElementById("drop-overlay"),
  };
  let filePath = "";

  function humanSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB"];
    let value = bytes / 1024;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
  }

  function renderCrumbs() {
    fileEls.crumbs.innerHTML = "";
    const parts = filePath ? filePath.split("/") : [];
    const root = document.createElement("button");
    root.textContent = "workspace";
    root.addEventListener("click", () => loadFiles(""));
    fileEls.crumbs.appendChild(root);
    parts.forEach((part, index) => {
      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = "/";
      const btn = document.createElement("button");
      btn.textContent = part;
      const target = parts.slice(0, index + 1).join("/");
      btn.addEventListener("click", () => loadFiles(target));
      fileEls.crumbs.append(sep, btn);
    });
  }

  async function loadFiles(path) {
    try {
      const data = await api(`/api/files?path=${encodeURIComponent(path ?? filePath)}`);
      filePath = data.path;
      renderCrumbs();
      fileEls.list.innerHTML = "";
      fileEls.empty.hidden = data.entries.length > 0;

      data.entries.forEach((entry) => {
        const li = document.createElement("li");
        li.className = entry.is_dir ? "dir" : "file";

        const icon = document.createElement("span");
        icon.className = `f-icon${entry.is_dir ? " dir" : ""}`;
        icon.textContent = entry.is_dir ? "📁" : "📄";

        const name = document.createElement("span");
        name.className = "f-name";
        name.textContent = entry.name;
        name.title = entry.path;
        if (entry.is_dir) name.addEventListener("click", () => loadFiles(entry.path));

        const size = document.createElement("span");
        size.className = "f-size";
        size.textContent = entry.is_dir ? "" : humanSize(entry.size);

        if (!entry.is_dir) {
          name.style.cursor = "pointer";
          name.addEventListener("click", () => openFile(entry));
        }

        const menuBtn = document.createElement("button");
        menuBtn.className = "f-menu-btn";
        menuBtn.title = "More actions";
        menuBtn.textContent = "⋮";
        menuBtn.addEventListener("click", (event) => {
          event.stopPropagation();
          openFileMenu(entry, li, menuBtn);
        });

        li.append(icon, name, size, menuBtn);
        fileEls.list.appendChild(li);
      });

      const pct = data.quota_bytes ? Math.min(100, (data.used_bytes / data.quota_bytes) * 100) : 0;
      fileEls.quotaFill.style.width = `${pct}%`;
      fileEls.quotaText.textContent = `${humanSize(data.used_bytes)} of ${humanSize(data.quota_bytes)} used`;
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  /* ── ⋮ menu ─────────────────────────────────────────────────────────── */

  const menuEl = document.getElementById("file-menu");

  function closeFileMenu() {
    menuEl.hidden = true;
    menuEl.innerHTML = "";
    fileEls.list.querySelectorAll("li.menu-open").forEach((li) => li.classList.remove("menu-open"));
  }

  function openFileMenu(entry, row, anchor) {
    closeFileMenu();
    row.classList.add("menu-open");

    const items = [];
    if (!entry.is_dir) {
      items.push({ icon: "✎", label: "Open / Edit", run: () => openFile(entry) });
      items.push({ icon: "↵", label: "Insert path", run: () => insertPath(entry.path) });
      items.push({
        icon: "⬇",
        label: "Download",
        run: () => {
          window.location.href = `/api/files/download?path=${encodeURIComponent(entry.path)}`;
        },
      });
    } else {
      items.push({ icon: "🗀", label: "Open folder", run: () => loadFiles(entry.path) });
    }
    items.push({ icon: "✏", label: "Rename", run: () => renameEntry(entry) });
    items.push({ sep: true });
    items.push({ icon: "🗑", label: "Delete", danger: true, run: () => deleteEntry(entry) });

    items.forEach((item) => {
      if (item.sep) {
        const sep = document.createElement("div");
        sep.className = "menu-sep";
        menuEl.appendChild(sep);
        return;
      }
      const button = document.createElement("button");
      if (item.danger) button.className = "danger";
      const glyph = document.createElement("span");
      glyph.className = "mi";
      glyph.textContent = item.icon;
      const label = document.createElement("span");
      label.textContent = item.label;
      button.append(glyph, label);
      button.addEventListener("click", () => {
        closeFileMenu();
        item.run();
      });
      menuEl.appendChild(button);
    });

    menuEl.hidden = false;
    const box = anchor.getBoundingClientRect();
    const height = menuEl.offsetHeight;
    const top = Math.min(box.bottom + 4, window.innerHeight - height - 8);
    menuEl.style.top = `${Math.max(8, top)}px`;
    menuEl.style.left = `${Math.min(box.left, window.innerWidth - menuEl.offsetWidth - 8)}px`;
  }

  document.addEventListener("click", (event) => {
    if (!menuEl.hidden && !menuEl.contains(event.target)) closeFileMenu();
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeFileMenu();
  });

  async function renameEntry(entry) {
    const newName = window.prompt("New name", entry.name);
    if (!newName || newName === entry.name) return;
    try {
      await api("/api/files/rename", {
        method: "POST",
        body: JSON.stringify({ path: entry.path, new_name: newName }),
      });
      toast(`Renamed to ${newName}`);
      loadFiles();
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function deleteEntry(entry) {
    const what = entry.is_dir ? "folder and everything in it" : "file";
    if (!window.confirm(`Delete the ${what} "${entry.name}"?`)) return;
    try {
      await api(`/api/files?path=${encodeURIComponent(entry.path)}`, { method: "DELETE" });
      toast(`Deleted ${entry.name}`);
      loadFiles();
    } catch (err) {
      toast(err.message, true);
    }
  }

  /* ── file viewer / editor ────────────────────────────────────────────── */

  const modal = {
    root: document.getElementById("file-modal"),
    title: document.getElementById("modal-title"),
    meta: document.getElementById("modal-meta"),
    save: document.getElementById("modal-save"),
    close: document.getElementById("modal-close"),
    editorEl: document.getElementById("modal-editor"),
    preview: document.getElementById("modal-preview"),
  };
  let modalEditor = null;
  let modalPath = null;

  const LANGUAGES = {
    py: "python", txt: "plaintext", md: "markdown", json: "json", csv: "plaintext",
    js: "javascript", ts: "typescript", html: "html", css: "css", yml: "yaml",
    yaml: "yaml", xml: "xml", sql: "sql", sh: "shell", ini: "ini", log: "plaintext",
  };

  function closeModal() {
    modal.root.hidden = true;
    modal.preview.hidden = true;
    modal.editorEl.hidden = true;
    modal.save.hidden = true;
    modal.preview.innerHTML = "";
    modalPath = null;
    if (modalEditor) {
      modalEditor.dispose();
      modalEditor = null;
    }
  }

  modal.close.addEventListener("click", closeModal);
  modal.root.addEventListener("click", (event) => {
    if (event.target === modal.root) closeModal();
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.root.hidden) closeModal();
  });

  async function openFile(entry) {
    let info;
    try {
      info = await api(`/api/files/content?path=${encodeURIComponent(entry.path)}`);
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
      return;
    }

    modalPath = entry.path;
    modal.title.textContent = info.name;
    modal.meta.textContent = humanSize(info.size);
    modal.root.hidden = false;

    if (info.kind === "text") {
      modal.editorEl.hidden = false;
      modal.save.hidden = false;
      const ext = (info.name.split(".").pop() || "").toLowerCase();
      modalEditor = monacoApi.editor.create(modal.editorEl, {
        value: info.content,
        language: LANGUAGES[ext] || "plaintext",
        theme: "colab-light",
        automaticLayout: true,
        fontFamily: '"Roboto Mono", "Cascadia Mono", Consolas, monospace',
        fontSize: 13.5,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: "on",
      });
      modalEditor.addCommand(monacoApi.KeyMod.CtrlCmd | monacoApi.KeyCode.KeyS, saveModalFile);
      modalEditor.focus();
      return;
    }

    modal.preview.hidden = false;
    if (info.kind === "image") {
      const img = document.createElement("img");
      img.src = `/api/files/raw?path=${encodeURIComponent(entry.path)}`;
      img.alt = info.name;
      modal.preview.appendChild(img);
      return;
    }
    const note = document.createElement("p");
    note.className = "note";
    note.textContent =
      info.kind === "large"
        ? `${info.name} is ${humanSize(info.size)} — too large to open here.\nDownload it instead.`
        : `${info.name} is a binary file, so it can't be shown as text.\nDownload it instead.`;
    modal.preview.appendChild(note);
  }

  async function saveModalFile() {
    if (!modalEditor || !modalPath) return;
    try {
      await api("/api/files/content", {
        method: "PUT",
        body: JSON.stringify({ path: modalPath, content: modalEditor.getValue() }),
      });
      toast(`Saved ${modal.title.textContent}`);
      loadFiles();
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  modal.save.addEventListener("click", saveModalFile);

  function insertPath(path) {
    const cell = cells.get(selectedId);
    if (!cell || !cell.editor) return toast("Select a cell first", true);
    const quoted = `"${path}"`;
    const selection = cell.editor.getSelection();
    cell.editor.executeEdits("files", [{ range: selection, text: quoted, forceMoveMarkers: true }]);
    cell.editor.focus();
    toast(`Inserted ${quoted}`);
  }

  async function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const form = new FormData();
    [...fileList].forEach((file) => form.append("files", file));
    toast(`Uploading ${fileList.length} file${fileList.length > 1 ? "s" : ""}…`);
    try {
      const res = await fetch(`/api/files/upload?path=${encodeURIComponent(filePath)}`, {
        method: "POST",
        body: form,
      });
      if (res.status === 401) {
        window.location.href = "/login";
        return;
      }
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error((data && data.detail) || `Upload failed (${res.status})`);
      toast(`Uploaded ${data.saved.map((f) => f.name).join(", ")}`);
      loadFiles();
    } catch (err) {
      toast(err.message, true);
    }
  }

  document.getElementById("file-upload-btn").addEventListener("click", () => fileEls.input.click());
  fileEls.input.addEventListener("change", (event) => {
    uploadFiles(event.target.files);
    event.target.value = "";
  });
  document.getElementById("file-refresh-btn").addEventListener("click", () => loadFiles());
  document.getElementById("file-mkdir-btn").addEventListener("click", async () => {
    const name = window.prompt("Folder name");
    if (!name) return;
    try {
      await api("/api/files/mkdir", {
        method: "POST",
        body: JSON.stringify({ path: filePath, name }),
      });
      loadFiles();
    } catch (err) {
      toast(err.message, true);
    }
  });

  let dragDepth = 0;
  fileEls.sidebar.addEventListener("dragenter", (event) => {
    event.preventDefault();
    dragDepth += 1;
    fileEls.overlay.hidden = false;
  });
  fileEls.sidebar.addEventListener("dragover", (event) => event.preventDefault());
  fileEls.sidebar.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) fileEls.overlay.hidden = true;
  });
  fileEls.sidebar.addEventListener("drop", (event) => {
    event.preventDefault();
    dragDepth = 0;
    fileEls.overlay.hidden = true;
    uploadFiles(event.dataTransfer.files);
  });

  const SIDEBAR_KEY = "pycompiler.sidebar";
  const sidebarShow = document.getElementById("sidebar-show");
  function applySidebar(hidden) {
    fileEls.sidebar.classList.toggle("hidden", hidden);
    sidebarShow.hidden = !hidden;
    try {
      localStorage.setItem(SIDEBAR_KEY, hidden ? "hidden" : "shown");
    } catch (_) { /* storage disabled */ }
    cells.forEach(fitEditor);
  }
  document.getElementById("sidebar-toggle").addEventListener("click", () => applySidebar(true));
  sidebarShow.addEventListener("click", () => applySidebar(false));

  /* ─────────────────────────────── app menu ──────────────────────────── */

  const appMenu = document.getElementById("app-menu");
  const appMenuBtn = document.getElementById("app-menu-btn");
  const ipynbInput = document.getElementById("ipynb-input");

  function closeAppMenu() {
    appMenu.hidden = true;
    appMenu.innerHTML = "";
  }

  function buildMenu(container, items) {
    container.innerHTML = "";
    items.forEach((item) => {
      if (item.sep) {
        const sep = document.createElement("div");
        sep.className = "menu-sep";
        container.appendChild(sep);
        return;
      }
      if (item.heading) {
        const heading = document.createElement("div");
        heading.className = "menu-heading";
        heading.textContent = item.heading;
        container.appendChild(heading);
        return;
      }
      const button = document.createElement("button");
      if (item.danger) button.className = "danger";
      const glyph = document.createElement("span");
      glyph.className = "mi";
      glyph.textContent = item.icon || "";
      const label = document.createElement("span");
      label.className = "ml";
      label.textContent = item.label;
      button.append(glyph, label);
      if (item.hint) {
        const hint = document.createElement("span");
        hint.className = "mk";
        hint.textContent = item.hint;
        button.appendChild(hint);
      }
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        if (item.keepOpen) item.run();
        else {
          closeAppMenu();
          item.run();
        }
      });
      container.appendChild(button);
    });
  }

  function positionAppMenu() {
    const box = appMenuBtn.getBoundingClientRect();
    appMenu.style.top = `${box.bottom + 6}px`;
    appMenu.style.left = `${box.left}px`;
  }

  async function showNotebookList() {
    buildMenu(appMenu, [{ icon: "…", label: "Loading notebooks…", run: () => {} }]);
    let items = [];
    try {
      items = await api("/api/notebooks");
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
      closeAppMenu();
      return;
    }
    const entries = [
      { icon: "‹", label: "Back", keepOpen: true, run: showMainMenu },
      { heading: `Notebooks (${items.length})` },
    ];
    items.forEach((nb) => {
      entries.push({
        icon: nb.id === NB ? "●" : "◉",
        label: nb.name,
        hint: `${nb.cell_count} cell${nb.cell_count === 1 ? "" : "s"}`,
        run: () => {
          if (nb.id !== NB) window.location.href = `/nb/${nb.id}`;
        },
      });
    });
    if (!items.length) entries.push({ icon: "", label: "No notebooks yet", run: () => {} });
    buildMenu(appMenu, entries);
    appMenu.classList.add("scrolly");
    positionAppMenu();
  }

  function showMainMenu() {
    appMenu.classList.remove("scrolly");
    buildMenu(appMenu, [
      { heading: "Notebook" },
      { icon: "＋", label: "New notebook", run: createNotebook },
      { icon: "◉", label: "Open notebook", keepOpen: true, run: showNotebookList },
      { icon: "⧉", label: "Make a copy", run: duplicateNotebook },
      { sep: true },
      { icon: "⬆", label: "Upload .ipynb", run: () => ipynbInput.click() },
      { icon: "⬇", label: "Download .ipynb", run: () => {
          window.location.href = `/api/notebooks/${NB}/export`;
      } },
      { sep: true },
      { heading: "Runtime" },
      { icon: "▶", label: "Run all", hint: "", run: runAll },
      { icon: "↻", label: "Restart and run all", run: restartAndRunAll },
      { icon: "■", label: "Interrupt", run: () => send({ type: "interrupt" }) },
      { icon: "⌫", label: "Clear all outputs", run: clearAllOutputs },
      { sep: true },
      { heading: "View" },
      { icon: "⌨", label: "Keyboard shortcuts", run: showShortcuts },
      { sep: true },
      { icon: "🗑", label: "Delete this notebook", danger: true, run: deleteNotebook },
    ]);
    positionAppMenu();
  }

  appMenuBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    if (!appMenu.hidden) {
      closeAppMenu();
      return;
    }
    closeFileMenu();
    appMenu.hidden = false;
    showMainMenu();
  });
  document.addEventListener("click", (event) => {
    if (!appMenu.hidden && !appMenu.contains(event.target)) closeAppMenu();
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAppMenu();
  });

  async function createNotebook() {
    try {
      const nb = await api("/api/notebooks", {
        method: "POST",
        body: JSON.stringify({ name: "Untitled.ipynb" }),
      });
      window.location.href = `/nb/${nb.id}`;
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  async function duplicateNotebook() {
    try {
      const copy = await api(`/api/notebooks/${NB}/duplicate`, { method: "POST" });
      window.location.href = `/nb/${copy.id}`;
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  async function deleteNotebook() {
    if (!window.confirm(`Delete "${nameInput.value}"? This cannot be undone.`)) return;
    try {
      await api(`/api/notebooks/${NB}`, { method: "DELETE" });
      window.location.href = "/notebooks";
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  async function clearAllOutputs() {
    try {
      await api(`/api/notebooks/${NB}/clear-outputs`, { method: "POST" });
      cells.forEach((cell) => {
        cell.outputsEl.innerHTML = "";
        setExecCount(cell, null);
      });
      toast("Cleared all outputs");
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
    }
  }

  async function restartAndRunAll() {
    if (!window.confirm("Restart the runtime and run every cell from the top?")) return;
    send({ type: "restart" });
    await new Promise((resolve) => setTimeout(resolve, 2500));
    await runAll();
  }

  ipynbInput.addEventListener("change", async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/notebooks/import", { method: "POST", body: form });
      if (res.status === 401) {
        window.location.href = "/login";
        return;
      }
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error((data && data.detail) || `Import failed (${res.status})`);
      window.location.href = `/nb/${data.id}`;
    } catch (err) {
      toast(err.message, true);
    }
  });

  const SHORTCUTS = [
    ["Shift + Enter", "Run cell, then select the next one"],
    ["Ctrl + Enter", "Run cell and stay on it"],
    ["Ctrl + S", "Save the file open in the file editor"],
    ["Esc", "Close a menu or dialog"],
    ["Double-click", "Reopen a finished text cell for editing"],
    ["Click away", "Finish a text cell"],
  ];

  function showShortcuts() {
    modal.title.textContent = "Keyboard shortcuts";
    modal.meta.textContent = "";
    modal.save.hidden = true;
    modal.editorEl.hidden = true;
    modal.preview.hidden = false;
    modal.preview.innerHTML = "";

    const table = document.createElement("table");
    table.className = "shortcuts";
    SHORTCUTS.forEach(([keys, what]) => {
      const tr = document.createElement("tr");
      const kbd = document.createElement("td");
      kbd.innerHTML = "";
      const key = document.createElement("kbd");
      key.textContent = keys;
      kbd.appendChild(key);
      const desc = document.createElement("td");
      desc.textContent = what;
      tr.append(kbd, desc);
      table.appendChild(tr);
    });
    modal.preview.appendChild(table);
    modal.root.hidden = false;
  }

  /* ────────────────────────────── boot ───────────────────────────────── */

  document.getElementById("add-code").addEventListener("click", () => addCell("code"));
  document.getElementById("add-text").addEventListener("click", () => addCell("markdown"));
  document.getElementById("add-code-end").addEventListener("click", () => addCell("code", order.length));
  document.getElementById("add-text-end").addEventListener("click", () => addCell("markdown", order.length));
  document.getElementById("run-all").addEventListener("click", runAll);
  document.getElementById("interrupt-btn").addEventListener("click", () => send({ type: "interrupt" }));
  document.getElementById("restart-btn").addEventListener("click", () => {
    if (window.confirm("Restart the runtime? All variables will be cleared.")) {
      send({ type: "restart" });
    }
  });
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try {
      await fetch("/auth/logout", { method: "POST" });
    } finally {
      window.location.href = "/login";
    }
  });
  document.getElementById("back-btn").addEventListener("click", () => {
    if (window.history.length > 1) window.history.back();
    else window.location.href = "/student";
  });

  const nameInput = document.getElementById("nb-name");
  let nameTimer = null;
  nameInput.addEventListener("input", () => {
    clearTimeout(nameTimer);
    nameTimer = setTimeout(async () => {
      const name = nameInput.value.trim();
      if (!name) return;
      try {
        await api(`/api/notebooks/${NB}`, { method: "PUT", body: JSON.stringify({ name }) });
        document.title = `${name} · PyCompiler`;
      } catch (err) {
        if (err.message !== "unauthenticated") toast(err.message, true);
      }
    }, 600);
  });

  window.addEventListener("resize", () => cells.forEach(fitEditor));

  require.config({ paths: { vs: CDN } });
  require(["vs/editor/editor.main"], async () => {
    monacoApi = window.monaco;
    monacoApi.editor.defineTheme("colab-light", {
      base: "vs",
      inherit: true,
      rules: [
        { token: "comment", foreground: "5f6368", fontStyle: "italic" },
        { token: "keyword", foreground: "1967d2" },
        { token: "string", foreground: "188038" },
        { token: "number", foreground: "b06000" },
      ],
      colors: {
        "editor.background": "#f7f7f7",
        "editorGutter.background": "#f7f7f7",
        "editorLineNumber.foreground": "#a0a4a8",
        "editor.lineHighlightBackground": "#f7f7f7",
      },
    });

    let notebook;
    try {
      notebook = await api(`/api/notebooks/${NB}`);
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
      return;
    }

    order = notebook.cells.map((c) => c.id);
    notebook.cells.forEach((data) => {
      const cell = buildCell(data);
      cellsEl.appendChild(cell.dom);
    });
    refreshInsertStrips();
    cells.forEach(fitEditor);
    if (order.length) selectCell(order[0]);

    let sidebarHidden = false;
    try {
      sidebarHidden = localStorage.getItem(SIDEBAR_KEY) === "hidden";
    } catch (_) { /* storage disabled */ }
    applySidebar(sidebarHidden);
    loadFiles("");

    connect();
    window.__nbReady = true;
  });
})();
