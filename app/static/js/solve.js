// The exercise solve page: description on top, editor left, input and output
// right. Replaces the notebook for graded work.
(function () {
  const D = window.Dash;
  const { el } = D;
  const id = window.ASSIGNMENT_ID;

  const code = document.getElementById("code");
  const stdin = document.getElementById("stdin");
  const output = document.getElementById("output");
  const saveState = document.getElementById("save-state");
  let saveTimer = null;
  let dirty = false;

  function field(label, value) {
    if (!value) return null;
    return el("div", { class: "field-block" },
      el("span", { class: "label", text: label }),
      el("pre", { class: "sample", text: value })
    );
  }

  async function load() {
    const a = await D.api(`/api/assignments/${id}`);
    document.getElementById("ex-title").textContent = a.title;
    document.getElementById("ex-meta").textContent =
      a.due_date ? `Due ${D.due(a.due_date)}` : "No due date";
    document.getElementById("ex-status").textContent = (a.status || "").replace(/_/g, " ");

    const body = document.getElementById("problem-body");
    body.textContent = "";
    body.append(el("p", { class: "statement", text: a.problem_statement || "" }));
    [field("Sample input", a.sample_input), field("Sample output", a.sample_output),
     field("Explanation", a.explanation)].forEach((n) => n && body.append(n));

    code.value = a.solution_code || a.starter_code || "";
    stdin.value = a.last_stdin || a.sample_input || "";
    dirty = false;
    saveState.textContent = "Saved";
  }

  async function save() {
    if (!dirty) return;
    try {
      await D.api(`/api/assignments/${id}/code`, {
        method: "PATCH",
        body: JSON.stringify({ code: code.value, stdin: stdin.value }),
      });
      dirty = false;
      saveState.textContent = "Saved";
    } catch (err) {
      saveState.textContent = "Not saved";
    }
  }

  function markDirty() {
    dirty = true;
    saveState.textContent = "Saving…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 900);
  }

  code.addEventListener("input", markDirty);
  stdin.addEventListener("input", markDirty);
  // A refresh or a closed tab must not lose work.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") save();
  });

  // Tab indents rather than leaving the editor.
  code.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const start = code.selectionStart;
    code.setRangeText("    ", start, code.selectionEnd, "end");
    markDirty();
  });

  document.getElementById("run-btn").addEventListener("click", async () => {
    output.textContent = "Running…";
    try {
      const r = await D.api(`/api/assignments/${id}/run`, {
        method: "POST",
        body: JSON.stringify({ code: code.value, stdin: stdin.value }),
      });
      let text = (r.stdout || "") + (r.stderr ? `\n${r.stderr}` : "");
      if (r.truncated) text += "\n[output truncated]";
      if (r.timed_out) text += "\n[timed out]";
      output.textContent = text;
      output.classList.toggle("err", Boolean(r.stderr) || r.timed_out);
      document.getElementById("run-time").textContent = `${r.duration_ms} ms`;
      dirty = false;
      saveState.textContent = "Saved";
    } catch (err) {
      output.textContent = err.message;
      output.classList.add("err");
    }
  });

  document.getElementById("submit-btn").addEventListener("click", async () => {
    await save();
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
