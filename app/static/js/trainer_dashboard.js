// Trainer dashboard (SRS §2): overview counts, review queue, pending work,
// deadlines, student progress, plus exercise creation and submission review.
(function () {
  const D = window.Dash;
  const { el, pill, fill } = D;

  let data = null;
  let students = [];
  let reviewing = null;
  let reviewFilter = "";

  const RESULT_TONES = {
    accepted: "green",
    wrong_answer: "red",
    runtime_error: "red",
    syntax_error: "red",
    pending: "grey",
  };
  const STATUS_LABELS = {
    assigned: ["Assigned", "grey"],
    in_progress: ["In progress", "blue"],
    changes_requested: ["Changes requested", "amber"],
    submitted: ["Submitted", "blue"],
    approved: ["Approved", "green"],
    completed: ["Completed", "green"],
  };

  function label(value) {
    return String(value || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  }

  // ── overview cards ────────────────────────────────────────────────────────

  function renderStats() {
    const s = data.stats;
    const cards = [
      { label: "Students", value: s.students, sub: "Active accounts", jump: "students-panel" },
      {
        label: "Coding exercises",
        value: s.exercises,
        sub: `${s.published} published · ${s.drafts} draft`,
        jump: "exercises-panel",
      },
      {
        label: "Pending submissions",
        value: s.pending,
        sub: s.overdue ? `${s.overdue} past due` : "Assigned, not yet in",
        tone: s.overdue ? "bad" : "",
        jump: "pending-panel",
      },
      {
        label: "Awaiting review",
        value: s.awaiting_review,
        sub: "Submitted, needs your verdict",
        tone: s.awaiting_review ? "warn" : "",
        jump: "review-panel",
      },
      { label: "Completed", value: s.completed, sub: "Marked done", tone: "good" },
    ];

    const host = document.getElementById("stats");
    host.textContent = "";
    cards.forEach((c) => {
      host.append(
        el(
          "button",
          {
            class: `stat ${c.tone || ""}`,
            type: "button",
            "data-jump": c.jump || null,
          },
          el("span", { class: "accent" }),
          el("span", { class: "label" }, c.label),
          el("span", { class: "value" }, c.value),
          el("span", { class: "sub" }, c.sub)
        )
      );
    });
  }

  // ── submissions awaiting review (§13) ─────────────────────────────────────

  function renderReview() {
    const list = document.getElementById("review-list");
    const term = reviewFilter.toLowerCase();
    const items = data.review_queue.filter(
      (r) =>
        !term ||
        (r.student || "").toLowerCase().includes(term) ||
        (r.student_email || "").toLowerCase().includes(term) ||
        (r.exercise || "").toLowerCase().includes(term)
    );
    document.getElementById("review-count").textContent = data.review_queue.length;

    fill(
      list,
      items.map((r) => {
        const passed = r.tests_total && r.tests_passed === r.tests_total;
        return el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, r.exercise),
            el(
              "div",
              { class: "meta" },
              el("span", {}, r.student || r.student_email),
              pill(label(r.result), RESULT_TONES[r.result] || "grey"),
              el(
                "span",
                { class: `tests ${passed ? "pass" : "fail"}` },
                `${r.tests_passed}/${r.tests_total} tests`
              ),
              el("span", { class: "dot-sep" }, D.ago(r.submitted_at))
            )
          ),
          el(
            "div",
            { class: "actions" },
            el("button", { class: "cb-btn", onclick: () => openReview(r) }, "Review")
          )
        );
      }),
      "Nothing waiting — every submission has been reviewed."
    );
  }

  // ── pending submissions ───────────────────────────────────────────────────

  function renderPending() {
    document.getElementById("pending-count").textContent = data.pending.length;
    fill(
      document.getElementById("pending-list"),
      data.pending.map((p) => {
        const [text, tone] = STATUS_LABELS[p.status] || [label(p.status), "grey"];
        return el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, p.exercise),
            el(
              "div",
              { class: "meta" },
              el("span", {}, p.student || p.student_email),
              pill(text, tone),
              el("span", { class: p.overdue ? "tests fail" : "" }, D.due(p.due_date))
            )
          ),
          el("div", { class: "actions" }, p.overdue ? pill("Overdue", "red") : null)
        );
      }),
      "No outstanding work — everything assigned has been submitted."
    );
  }

  // ── upcoming deadlines ────────────────────────────────────────────────────

  function renderDeadlines() {
    fill(
      document.getElementById("deadline-list"),
      data.deadlines.map((d) => {
        const done = d.assigned ? Math.round((100 * d.submitted) / d.assigned) : 0;
        return el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, d.title),
            el(
              "div",
              { class: "meta" },
              el("span", { class: d.overdue ? "tests fail" : "" }, D.due(d.due_date)),
              el("span", {}, `${d.submitted}/${d.assigned} submitted`)
            )
          ),
          el(
            "div",
            { class: `bar ${done === 100 ? "done" : ""}` },
            el("span", { style: `width:${done}%` })
          )
        );
      }),
      "No published exercise has a due date yet."
    );
  }

  // ── student progress (§16) ────────────────────────────────────────────────

  function renderStudents() {
    document.getElementById("student-count").textContent = data.students.length;
    fill(
      document.getElementById("student-list"),
      data.students.map((s) => {
        const name = s.name || s.email;
        return el(
          "div",
          { class: "row student-row" },
          el(
            "div",
            { class: "who" },
            el("span", { class: "avatar" }, name.slice(0, 2).toUpperCase()),
            el(
              "div",
              {},
              el("div", { class: "title" }, name),
              el(
                "div",
                { class: "meta" },
                el("span", {}, `${s.assigned} assigned`),
                el("span", { class: "dot-sep" }, `${s.completed} done`),
                s.awaiting ? pill(`${s.awaiting} to review`, "amber") : null,
                s.is_active ? null : pill("Inactive", "red")
              )
            )
          ),
          el("span", { class: "tests" }, `${s.progress}%`),
          el(
            "div",
            { class: `bar ${s.progress === 100 ? "done" : ""}` },
            el("span", { style: `width:${s.progress}%` })
          )
        );
      }),
      "No students registered yet."
    );
  }

  // ── exercises (§5) ────────────────────────────────────────────────────────

  function renderExercises() {
    document.getElementById("exercise-count").textContent = data.exercises.length;
    fill(
      document.getElementById("exercise-list"),
      data.exercises.map((x) =>
        el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, x.title),
            el(
              "div",
              { class: "meta" },
              pill(label(x.status), x.status === "published" ? "green" : "grey"),
              el("span", {}, `${x.assigned} assigned`),
              el("span", { class: "dot-sep" }, `${x.tests} test cases`),
              el("span", { class: "dot-sep" }, D.due(x.due_date))
            )
          ),
          el("div", { class: "actions" }, el("span", { class: "tests" }, D.ago(x.updated_at)))
        )
      ),
      "No exercises yet — create your first one."
    );
  }

  // ── review sheet (§13) ────────────────────────────────────────────────────

  function openReview(submission) {
    reviewing = submission;
    document.getElementById("review-title").textContent = submission.exercise;
    const meta = document.getElementById("review-meta");
    meta.textContent = "";
    meta.append(
      el("span", { class: "title" }, submission.student || submission.student_email),
      pill(label(submission.result), RESULT_TONES[submission.result] || "grey"),
      el(
        "span",
        { class: "tests" },
        `${submission.tests_passed}/${submission.tests_total} tests passed`
      ),
      el("span", { class: "tests" }, D.when(submission.submitted_at))
    );
    document.getElementById("review-code").textContent =
      submission.code || "(no code submitted)";
    document.getElementById("review-comment").value = "";
    D.openSheet("review-sheet");
  }

  async function submitReview(action) {
    if (!reviewing) return;
    const comment = document.getElementById("review-comment").value.trim();
    if (action === "request_changes" && !comment) {
      D.toast("Add a comment so the student knows what to change.", true);
      return;
    }
    try {
      await D.api(`/api/submissions/${reviewing.id}/review`, {
        method: "POST",
        body: JSON.stringify({ action, comment }),
      });
      D.closeSheet("review-sheet");
      D.toast(action === "request_changes" ? "Modifications requested" : "Submission approved");
      reviewing = null;
      load();
    } catch (err) {
      D.toast(err.message, true);
    }
  }

  // ── new exercise sheet (§5, §6, §10) ──────────────────────────────────────

  function addTestRow(test) {
    const row = el(
      "div",
      { class: "test-row" },
      el("textarea", { class: "t-in", rows: "2", placeholder: "Input (stdin)" }),
      el("textarea", { class: "t-out", rows: "2", placeholder: "Expected output" }),
      el(
        "label",
        { class: "hidden-toggle" },
        el("input", { type: "checkbox", class: "t-hidden" }),
        "Hidden"
      )
    );
    if (test) {
      row.querySelector(".t-in").value = test.stdin || "";
      row.querySelector(".t-out").value = test.expected_output || "";
    }
    document.getElementById("test-rows").append(row);
  }

  function renderPicker() {
    const picker = document.getElementById("student-picker");
    picker.textContent = "";
    if (!students.length) {
      picker.append(el("p", { class: "help" }, "No students registered yet."));
      return;
    }
    students.forEach((s) => {
      picker.append(
        el(
          "label",
          {},
          el("input", { type: "checkbox", value: s.id, disabled: !s.is_active }),
          `${s.name || s.email} (${s.email})${s.is_active ? "" : " — inactive"}`
        )
      );
    });
  }

  async function saveExercise() {
    const value = (id) => document.getElementById(id).value.trim();
    const title = value("ex-title");
    if (!title) {
      D.toast("Give the exercise a title.", true);
      return;
    }

    const tests = [...document.querySelectorAll("#test-rows .test-row")]
      .map((row) => ({
        stdin: row.querySelector(".t-in").value,
        expected_output: row.querySelector(".t-out").value,
        is_hidden: row.querySelector(".t-hidden").checked,
      }))
      .filter((t) => t.stdin.trim() || t.expected_output.trim());

    const assign_to = [...document.querySelectorAll("#student-picker input:checked")].map((i) =>
      Number(i.value)
    );

    const btn = document.getElementById("save-exercise");
    btn.disabled = true;
    try {
      const result = await D.api("/api/exercises", {
        method: "POST",
        body: JSON.stringify({
          title,
          problem_statement: value("ex-statement"),
          input_format: value("ex-input"),
          output_format: value("ex-output"),
          sample_input: value("ex-sample-in"),
          sample_output: value("ex-sample-out"),
          constraints: value("ex-constraints"),
          due_date: value("ex-due") || null,
          status: document.getElementById("ex-status").value,
          test_cases: tests,
          assign_to,
        }),
      });
      D.closeSheet("exercise-sheet");
      D.toast(`Exercise created and assigned to ${result.assigned} student(s)`);
      resetSheet();
      load();
    } catch (err) {
      D.toast(err.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  function resetSheet() {
    ["ex-title", "ex-statement", "ex-input", "ex-output", "ex-sample-in", "ex-sample-out",
      "ex-constraints", "ex-due"].forEach((id) => (document.getElementById(id).value = ""));
    document.getElementById("ex-status").value = "published";
    document.getElementById("test-rows").textContent = "";
    addTestRow();
    renderPicker();
  }

  // ── load ──────────────────────────────────────────────────────────────────

  async function load() {
    try {
      data = await D.api("/api/dashboard/trainer");
    } catch (err) {
      if (err.message !== "unauthenticated") D.toast(err.message, true);
      return;
    }
    renderStats();
    renderReview();
    renderPending();
    renderDeadlines();
    renderStudents();
    renderExercises();
    D.renderNotifications(data.notifications, data.unread);
    D.renderActivity(data.activity);
  }

  document.getElementById("new-exercise-btn").addEventListener("click", async () => {
    try {
      students = await D.api("/api/students");
    } catch (err) {
      students = [];
    }
    resetSheet();
    D.openSheet("exercise-sheet");
    document.getElementById("ex-title").focus();
  });
  document.getElementById("add-test").addEventListener("click", () => addTestRow());
  document.getElementById("pick-all").addEventListener("click", () => {
    document
      .querySelectorAll("#student-picker input:not([disabled])")
      .forEach((i) => (i.checked = true));
  });
  document.getElementById("save-exercise").addEventListener("click", saveExercise);
  document.getElementById("approve-btn").addEventListener("click", () => submitReview("approve"));
  document
    .getElementById("request-changes")
    .addEventListener("click", () => submitReview("request_changes"));
  document.getElementById("review-search").addEventListener("input", (event) => {
    reviewFilter = event.target.value;
    renderReview();
  });

  D.initChrome(load);
  load();
})();
