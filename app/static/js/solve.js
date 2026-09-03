// The exercise solve page: description on top, editor left, input and output
// right. Replaces the notebook for graded work.
//
// The editor is Monaco (code_editor.js), which mirrors everything typed into
// the #code textarea — so the save, run and submit paths below still read one
// value, whether Monaco loaded or the textarea fallback is in use.
(function () {
  const D = window.Dash;
  const { el } = D;
  const id = window.ASSIGNMENT_ID;

  const code = document.getElementById("code");
  const stdin = document.getElementById("stdin");
  const output = document.getElementById("output");
  const saveState = document.getElementById("save-state");
  const runBtn = document.getElementById("run-btn");
  const submitBtn = document.getElementById("submit-btn");
  const closedNote = document.getElementById("closed-note");
  let saveTimer = null;
  let dirty = false;

  const editorReady = window.CodeEditor.mount({
    host: document.getElementById("editor-host"),
    textarea: code,
    language: "python",
    onChange: () => markDirty(),
  }).then((editor) => {
    document.getElementById("editor-kind").textContent = editor.monaco
      ? "Python · Monaco"
      : "Python";
    return editor;
  });

  function field(label, value) {
    if (!value) return null;
    return el("div", { class: "field-block" },
      el("span", { class: "label", text: label }),
      el("pre", { class: "sample", text: value })
    );
  }

  async function load() {
    const [a, editor] = await Promise.all([D.api(`/api/assignments/${id}`), editorReady]);
    const ex = a.exercise || {};
    document.getElementById("ex-title").textContent = ex.title;
    // D.due() already reads "Due <when> (<in x>)", or "No due date".
    document.getElementById("ex-meta").textContent = D.due(a.due_date);
    document.getElementById("ex-status").textContent = (a.status || "").replace(/_/g, " ");

    const body = document.getElementById("problem-body");
    body.textContent = "";
    body.append(el("p", { class: "statement", text: ex.problem_statement || "" }));
    [field("Sample input", ex.sample_input), field("Sample output", ex.sample_output),
     field("Explanation", ex.explanation)].forEach((n) => n && body.append(n));

    editor.setValue(a.solution_code || ex.starter_code || "");
    stdin.value = a.last_stdin || ex.sample_input || "";
    // setValue fires the editor's change handler, which marks the page dirty
    // over code the server just gave us. Clear that here, after the write.
    clearTimeout(saveTimer);
    dirty = false;
    saveState.textContent = "Saved";

    const closed = a.status === "approved" || a.status === "completed";
    editor.setReadOnly(closed);
    runBtn.disabled = closed;
    submitBtn.disabled = closed;
    closedNote.hidden = !closed;

    D.api(`/api/assignments/${id}/open`, { method: "POST" }).catch(() => {});
  }

  // Actual save. Throws on failure so a caller (Submit) can refuse to
  // proceed on stale/unsaved code rather than silently grading whatever
  // is already in the database.
  async function save() {
    if (!dirty) return;
    const sentCode = code.value;
    const sentStdin = stdin.value;
    try {
      await D.api(`/api/assignments/${id}/code`, {
        method: "PATCH",
        keepalive: true, // survives a navigation/tab-close that fires this from visibilitychange
        body: JSON.stringify({ code: sentCode, stdin: sentStdin }),
      });
      if (code.value === sentCode && stdin.value === sentStdin) {
        dirty = false;
        saveState.textContent = "Saved";
      } else {
        // Changed while the request was in flight: still unsaved, go again.
        // markDirty() (not queueSave()) so a fast typist can't recurse the chain.
        markDirty();
      }
    } catch (err) {
      saveState.textContent = "Not saved";
      throw err;
    }
  }

  // Every save path funnels through here so requests are always issued in
  // order — a slow earlier save can never land after a newer one and
  // clobber it (the PATCH is a blind UPDATE with no version guard).
  let saveChain = Promise.resolve();

  function queueSave() {
    saveChain = saveChain.then(save, save);
    return saveChain;
  }

  function markDirty() {
    dirty = true;
    saveState.textContent = "Saving…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => queueSave().catch(() => {}), 900);
  }

  stdin.addEventListener("input", markDirty);
  // A refresh or a closed tab must not lose work.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") queueSave().catch(() => {});
  });

  runBtn.addEventListener("click", async () => {
    output.textContent = "Running…";
    output.classList.remove("err");
    // Wait out any in-flight save so the run can't race it and read a
    // pre-save value while a newer one is still on the wire.
    await saveChain.catch(() => {});
    const sent = code.value;
    const sentStdin = stdin.value;
    try {
      const r = await D.api(`/api/assignments/${id}/run`, {
        method: "POST",
        body: JSON.stringify({ code: sent, stdin: sentStdin }),
      });
      let text = (r.stdout || "") + (r.stderr ? `\n${r.stderr}` : "");
      if (r.truncated) text += "\n[output truncated]";
      if (r.timed_out) text += "\n[timed out]";
      output.textContent = text || "(no output)";
      output.classList.toggle("err", Boolean(r.stderr) || r.timed_out);
      document.getElementById("run-time").textContent = `${r.duration_ms} ms`;
      // A run can take up to 15s; only clear dirty if nothing changed
      // underneath it, or a pending edit's save would silently no-op.
      if (code.value === sent && stdin.value === sentStdin) {
        dirty = false;
        saveState.textContent = "Saved";
      }
    } catch (err) {
      output.textContent = err.message;
      output.classList.add("err");
    }
  });

  submitBtn.addEventListener("click", async () => {
    try {
      await queueSave();
    } catch (err) {
      D.flash(
        "Could not save your code, so it was not submitted. Check your connection and try again.",
        "error"
      );
      return;
    }
    try {
      const v = await D.api(`/api/assignments/${id}/submit`, { method: "POST" });
      D.flash(
        v.result === "accepted"
          ? `Submitted — ${v.passed}/${v.total} tests passed`
          : `Submitted — ${v.passed}/${v.total} tests passed (${v.result.replace(/_/g, " ")})`,
        v.result === "accepted" ? "success" : "info"
      );
      load();
    } catch (err) {
      D.flash(err.message, "error");
    }
  });

  load().catch((err) => D.flash(err.message || "Unable to load this exercise.", "error"));
})();
