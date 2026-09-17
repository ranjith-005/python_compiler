// The exercise solve page.
//
//   problem     plain prose at the top, no panel around it
//   editor      Run and Submit on top of it, no heading
//   drawer      the test cases, on the right, opened by Run
//   console     a private scratch run with your own input, opened by 🚀
//
// Run and Submit both grade against the same test cases; the difference is
// that Submit records the attempt and tells the trainer. The console is
// neither: it is the student checking their own work, and nothing about it is
// stored as a submission.
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

  const drawer = document.getElementById("test-drawer");
  const scrim = document.getElementById("drawer-scrim");
  const verdictBox = document.getElementById("drawer-verdict");
  const drawerBody = document.getElementById("drawer-body");
  const consoleBlock = document.getElementById("console-block");

  let saveTimer = null;
  let dirty = false;
  let locked = false;
  let publicTests = [];
  let hiddenCount = 0;

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

  // ── the drawer ───────────────────────────────────────────────────────────

  function openDrawer() {
    drawer.hidden = false;
    scrim.hidden = false;
    document.getElementById("results-btn").setAttribute("aria-expanded", "true");
  }

  function closeDrawer() {
    drawer.hidden = true;
    scrim.hidden = true;
    document.getElementById("results-btn").setAttribute("aria-expanded", "false");
  }

  document.getElementById("drawer-close").addEventListener("click", closeDrawer);
  scrim.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !drawer.hidden) closeDrawer();
  });
  document.getElementById("results-btn").addEventListener("click", () => {
    if (drawer.hidden) {
      showTests();
      openDrawer();
    } else {
      closeDrawer();
    }
  });

  function block(label, value) {
    return el("div", { class: "case-field" },
      el("span", { class: "label" }, label),
      el("pre", {}, value === "" ? "(empty)" : value)
    );
  }

  // The drawer before anything has been run: the inputs the student is allowed
  // to see, and a count of the ones they are not.
  function showTests() {
    verdictBox.hidden = true;
    drawerBody.textContent = "";
    if (!publicTests.length && !hiddenCount) {
      drawerBody.append(el("p", { class: "empty-note" }, "This exercise has no test cases."));
      return;
    }
    publicTests.forEach((test, index) => {
      drawerBody.append(
        el("section", { class: "case" },
          el("header", {}, el("h3", {}, `Test ${index + 1}`)),
          block("Input", test.stdin || ""),
          block("Expected output", test.expected_output || "")
        )
      );
    });
    if (hiddenCount) {
      drawerBody.append(
        el("section", { class: "case hidden-case" },
          el("header", {}, el("h3", {}, `${hiddenCount} hidden test${hiddenCount > 1 ? "s" : ""}`)),
          el("p", { class: "case-note" },
            "These run against your code too. Their input is not shown, but you will be " +
            "told which ones fail.")
        )
      );
    }
  }

  // The drawer after a Run or a Submit.
  function showResults(v) {
    const all = v.passed === v.total && v.total > 0;
    verdictBox.hidden = false;
    verdictBox.className = `drawer-verdict ${all ? "ok" : "bad"}`;
    verdictBox.textContent = "";
    verdictBox.append(
      el("strong", {}, `${v.passed}/${v.total} test cases passed`),
      el("span", {},
        all
          ? "All test cases passed."
          : v.result === "syntax_error"
            ? `Your code did not compile: ${v.detail}`
            : `${v.total - v.passed} failed — see below.`)
    );

    drawerBody.textContent = "";
    const cases = v.cases || [];
    if (!cases.length) {
      drawerBody.append(el("p", { class: "empty-note" }, v.detail || "No test cases ran."));
      return;
    }

    cases.forEach((c) => {
      const card = el("section", {
        class: `case ${c.passed ? "pass" : "fail"}${c.hidden ? " hidden-case" : ""}`,
      });
      card.append(
        el("header", {},
          el("h3", {}, c.hidden ? `Hidden test ${c.number}` : `Test ${c.number}`),
          el("span", { class: "spacer" }),
          el("span", { class: `case-badge ${c.passed ? "pass" : "fail"}` },
            c.passed ? "✓ Passed" : "✕ Failed")
        )
      );
      if (c.hidden) {
        // Its input stays hidden whether it passed or failed; only the reason
        // it failed is reported.
        card.append(
          el("p", { class: "case-note" },
            c.passed ? "Passed — input not shown." : c.error || "Failed — input not shown.")
        );
      } else {
        if (!c.passed && c.error) {
          card.append(el("p", { class: "case-error" }, c.error));
        }
        card.append(block("Input", c.stdin || ""));
        card.append(block("Expected output", c.expected || ""));
        if (!c.passed) card.append(block("Your output", c.actual || ""));
      }
      drawerBody.append(card);
    });
  }

  // ── the console ──────────────────────────────────────────────────────────

  function setConsole(open) {
    consoleBlock.hidden = !open;
    document.getElementById("console-btn").setAttribute("aria-expanded", String(open));
    if (open) stdin.focus();
  }

  document.getElementById("console-btn").addEventListener("click", () =>
    setConsole(consoleBlock.hidden)
  );
  document.getElementById("console-close").addEventListener("click", () => setConsole(false));

  // ── loading ──────────────────────────────────────────────────────────────

  function paragraphs(host, text) {
    (text || "").split(/\n{2,}/).forEach((para) => {
      if (para.trim()) host.append(el("p", {}, para.trim()));
    });
  }

  function detail(host, label, value) {
    if (!value) return;
    host.append(
      el("div", { class: "problem-field" },
        el("span", { class: "label" }, label),
        el("pre", {}, value)
      )
    );
  }

  function paintLock(a) {
    const note = document.getElementById("locked-note");
    const actions = document.getElementById("locked-actions");
    const state = document.getElementById("request-state");
    const closed = a.status === "completed";

    if (!a.locked) {
      note.hidden = true;
      return;
    }
    note.hidden = false;

    if (closed) {
      // Reviewed and finished: not a deadline problem, and not reopenable here.
      document.getElementById("locked-title").textContent = "This exercise is closed.";
      document.getElementById("locked-detail").textContent =
        "Your trainer has finished reviewing it, so it is no longer editable.";
      actions.hidden = true;
      state.hidden = true;
      return;
    }

    const request = a.access_request;
    const pending = request && request.status === "pending";
    const approved = request && request.status === "approved";
    const rejected = request && request.status === "rejected";

    actions.hidden = Boolean(pending || approved);
    state.hidden = !request;
    if (request) {
      state.className = `request-state ${request.status}`;
      state.textContent = "";
      if (pending) {
        state.append(el("strong", {}, "Request sent"),
          el("span", {}, "Waiting for your trainer to review it."));
      } else if (rejected) {
        // The trainer's message is written for this student alone.
        state.append(el("strong", {}, "Request declined"),
          el("span", {}, request.decision_message || "Your trainer did not reopen this exercise."));
      } else if (approved) {
        state.append(el("strong", {}, "Reopened"),
          el("span", {}, request.decision_message || "Your trainer reopened this exercise."));
      }
    }
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
    paragraphs(body, ex.problem_statement);
    detail(body, "Input format", ex.input_format);
    detail(body, "Output format", ex.output_format);
    detail(body, "Sample input", ex.sample_input);
    detail(body, "Sample output", ex.sample_output);
    detail(body, "Explanation", ex.explanation);
    detail(body, "Constraints", ex.constraints);

    publicTests = a.public_tests || [];
    hiddenCount = a.hidden_tests || 0;
    showTests();

    editor.setValue(a.solution_code || ex.starter_code || "");
    stdin.value = a.last_stdin || ex.sample_input || "";
    // setValue fires the editor's change handler, which marks the page dirty
    // over code the server just gave us. Clear that here, after the write.
    clearTimeout(saveTimer);
    dirty = false;
    saveState.textContent = "Saved";

    locked = Boolean(a.locked);
    editor.setReadOnly(locked);
    runBtn.disabled = locked;
    submitBtn.disabled = locked;
    document.getElementById("console-run").disabled = locked;
    paintLock(a);

    if (!locked) D.api(`/api/assignments/${id}/open`, { method: "POST" }).catch(() => {});
  }

  // ── saving ───────────────────────────────────────────────────────────────

  // Actual save. Throws on failure so a caller (Submit) can refuse to
  // proceed on stale/unsaved code rather than silently grading whatever
  // is already in the database.
  async function save() {
    if (!dirty || locked) return;
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
    if (locked) return;
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

  // ── run, submit, console ─────────────────────────────────────────────────

  // Run grades against the test cases and opens the drawer with the result.
  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    runBtn.textContent = "Running…";
    openDrawer();
    verdictBox.hidden = false;
    verdictBox.className = "drawer-verdict";
    verdictBox.textContent = "Running the test cases…";
    drawerBody.textContent = "";
    // Wait out any in-flight save so the run can't race it and read a
    // pre-save value while a newer one is still on the wire.
    await saveChain.catch(() => {});
    const sent = code.value;
    const sentStdin = stdin.value;
    try {
      const v = await D.api(`/api/assignments/${id}/check`, {
        method: "POST",
        body: JSON.stringify({ code: sent, stdin: sentStdin }),
      });
      showResults(v);
      // A run can take up to 15s; only clear dirty if nothing changed
      // underneath it, or a pending edit's save would silently no-op.
      if (code.value === sent && stdin.value === sentStdin) {
        dirty = false;
        saveState.textContent = "Saved";
      }
    } catch (err) {
      verdictBox.className = "drawer-verdict bad";
      verdictBox.textContent = err.message;
    } finally {
      runBtn.disabled = locked;
      runBtn.textContent = "▶ Run";
    }
  });

  // The console runs the same code against whatever the student typed, and
  // reports stdout and stderr as they are. Nothing is graded or recorded.
  document.getElementById("console-run").addEventListener("click", async () => {
    const button = document.getElementById("console-run");
    button.disabled = true;
    output.textContent = "Running…";
    output.classList.remove("err");
    await saveChain.catch(() => {});
    try {
      const r = await D.api(`/api/assignments/${id}/run`, {
        method: "POST",
        body: JSON.stringify({ code: code.value, stdin: stdin.value }),
      });
      let text = (r.stdout || "") + (r.stderr ? `\n${r.stderr}` : "");
      if (r.truncated) text += "\n[output truncated]";
      if (r.timed_out) text += "\n[timed out]";
      output.textContent = text || "(no output)";
      output.classList.toggle("err", Boolean(r.stderr) || r.timed_out);
      document.getElementById("run-time").textContent = `${r.duration_ms} ms`;
    } catch (err) {
      output.textContent = err.message;
      output.classList.add("err");
    } finally {
      button.disabled = locked;
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
      showResults(v);
      openDrawer();
      D.flash(
        `Submitted — ${v.passed}/${v.total} test cases passed`,
        v.result === "accepted" ? "success" : "info"
      );
      load();
    } catch (err) {
      D.flash(err.message, "error");
    }
  });

  document.getElementById("request-btn").addEventListener("click", async () => {
    const message = document.getElementById("request-message").value.trim();
    try {
      await D.api(`/api/assignments/${id}/access-request`, {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      D.flash("Request sent to your trainer", "success");
      load();
    } catch (err) {
      D.flash(err.message, "error");
    }
  });

  load().catch((err) => D.flash(err.message || "Unable to load this exercise.", "error"));
})();
