// Phase B detail pages. Every template sets window.PAGE = { kind, ...ids };
// this dispatches on that kind so the seven pages share one set of helpers.
(function () {
  const D = window.Dash;
  const { api, el, fill, pill, flash } = D;
  const PAGE = window.PAGE || {};
  const $ = (id) => document.getElementById(id);

  const STATUS = {
    assigned: ["Assigned", "grey"],
    in_progress: ["In progress", "blue"],
    submitted: ["Submitted", "amber"],
    changes_requested: ["Changes requested", "amber"],
    completed: ["Completed", "green"],
  };
  const SEVERITY = { note: "grey", warning: "amber", urgent: "red" };

  function statusPill(value) {
    const [text, tone] = STATUS[value] || [value || "—", "grey"];
    return pill(text, tone);
  }

  // A card the trainer can act on is an <a>; a card that is only a figure is a
  // <div>. Requirement: on-time rate, average tests passed and last active go
  // nowhere, everything else opens the matching view.
  function stat(label, value, sub, tone, opts) {
    const { icon = "•", href = null, active = false } = opts || {};
    const classes = `stat ${tone || ""} ${active ? "active" : ""}`.trim();
    return el(
      href ? "a" : "div",
      href ? { class: classes, href } : { class: classes },
      el("span", { class: "stat-icon" }, icon),
      el("span", { class: "value" }, value),
      el("span", { class: "label" }, label),
      el("span", { class: "sub" }, sub)
    );
  }

  function row(title, metaNodes, right, onClick) {
    return el(
      "div",
      { class: `row${onClick ? " clickable" : ""}`, onclick: onClick || null },
      el("div", {}, el("div", { class: "title" }, title), el("div", { class: "meta" }, metaNodes)),
      right || null
    );
  }

  // A search box that filters an already-rendered list of {node, text} pairs.
  function wireSearch(inputId, items, host, emptyMessage, countId) {
    const input = $(inputId);
    function apply() {
      const q = (input.value || "").trim().toLowerCase();
      const shown = q ? items.filter((i) => i.text.toLowerCase().includes(q)) : items;
      if (countId) $(countId).textContent = shown.length;
      fill(host, shown.map((i) => i.node), q ? "Nothing matches that search." : emptyMessage);
    }
    input.addEventListener("input", apply);
    apply();
  }

  // ── requirement 2: one student ───────────────────────────────────────────

  // Which assignment rows each clickable card narrows the list to.
  const CARD_FILTERS = {
    all: () => true,
    completed: (e) => e.status === "completed",
    open: (e) => ["assigned", "in_progress", "changes_requested"].includes(e.status),
    submitted: (e) => e.status === "submitted",
    late: (e) => e.late,
  };
  const CARD_TITLES = {
    all: "every exercise",
    completed: "completed exercises",
    open: "exercises still open",
    submitted: "exercises awaiting your review",
    late: "exercises submitted late",
  };

  async function studentDetail() {
    const data = await api(`/api/students/${PAGE.studentId}`);
    const s = data.student;
    $("student-name").textContent = s.display;
    $("student-sub").textContent = s.email;
    $("personal-link").href = `/trainer/students/${PAGE.studentId}/profile`;

    const requested = new URLSearchParams(window.location.search).get("view");
    const view = CARD_FILTERS[requested] ? requested : "all";
    const card = (key) => `/trainer/students/${PAGE.studentId}?view=${key}`;

    fill($("stats"), [
      stat("Assigned", data.assigned, "Exercises from you", "", {
        icon: "📘", href: card("all"), active: view === "all" }),
      stat("Completed", data.completed, "Marked done", "good", {
        icon: "✅", href: card("completed"), active: view === "completed" }),
      stat("Pending", data.pending, "Still open", "", {
        icon: "⏳", href: card("open"), active: view === "open" }),
      stat("Awaiting review", data.awaiting, "Submitted, not yet reviewed", "", {
        icon: "📤", href: card("submitted"), active: view === "submitted" }),
      stat("Late", data.late, "Submitted after the due date", data.late ? "bad" : "", {
        icon: "⏰", href: card("late"), active: view === "late" }),
      // The three figures below are read-only by requirement: no href, so
      // nothing about them invites a click.
      stat("On-time rate", `${data.on_time_rate}%`, "Of what was submitted", "", { icon: "🎯" }),
      stat("Avg tests passed", `${data.avg_tests}%`, "Across graded submissions", "", { icon: "🧪" }),
      stat("Last active", data.last_active ? D.when(data.last_active) : "Never",
           "Most recent activity", "", { icon: "🕑" }),
    ]);

    $("ex-heading").textContent =
      view === "all" ? "Assigned exercises" : `Assigned exercises · ${CARD_TITLES[view]}`;

    const items = data.exercises.filter(CARD_FILTERS[view]).map((e) => ({
      text: `${e.title} ${e.status}`,
      node: row(
        e.title,
        [
          statusPill(e.status),
          el("span", {}, `Assigned ${D.when(e.assigned_at)}`),
          e.submitted_at ? el("span", {}, `Submitted ${D.when(e.submitted_at)}`) : null,
          e.late ? pill("Late", "red") : null,
          e.tests_total
            ? el(
                "span",
                { class: `tests ${e.tests_passed === e.tests_total ? "" : "fail"}` },
                `${e.tests_passed}/${e.tests_total} tests`
              )
            : null,
        ],
        el("span", { class: "chev" }, "›"),
        // Requirement 2: clicking a course row opens that student's full
        // progress on it.
        () => {
          window.location.href = `/trainer/students/${PAGE.studentId}/exercises/${e.exercise_id}`;
        }
      ),
    }));
    wireSearch(
      "ex-search",
      items,
      $("ex-list"),
      view === "all" ? "Nothing assigned yet." : `Nothing here — no ${CARD_TITLES[view]}.`,
      "ex-count"
    );

    $("q-count").textContent = data.queries.length;
    fill(
      $("q-list"),
      data.queries.map((q) =>
        row(q.exercise, [
          pill(q.severity, SEVERITY[q.severity] || "grey"),
          el("span", {}, q.message),
          q.reply ? el("span", {}, `Replied: ${q.reply}`) : el("span", {}, "No reply yet"),
        ])
      ),
      "No queries raised for this student."
    );
  }

  async function studentPersonal() {
    const data = await api(`/api/students/${PAGE.studentId}`);
    const s = data.student;
    $("student-name").textContent = s.display;
    $("back-link").href = `/trainer/students/${PAGE.studentId}`;

    // Identity first, then the fields as a card grid — the old two-column
    // key/value strip ran names and emails together and read as a dump.
    const parts = String(s.display || "?").trim().split(/\s+/);
    const initials = (
      (parts[0][0] || "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")
    ).toUpperCase();

    fill($("hero"), [
      el("span", { class: "avatar" }, initials),
      el(
        "div",
        {},
        el("h2", {}, s.display),
        el("div", { class: "sub" }, s.email)
      ),
      el("span", { class: "spacer" }),
      pill(s.is_active ? "Active" : "Disabled", s.is_active ? "green" : "grey"),
    ]);

    const field = (label, value) =>
      el("div", { class: "info-item" },
        el("span", { class: "k" }, label),
        el("span", { class: "v" }, value || "—"));
    fill($("fields"), [
      field("First name", s.first_name || s.full_name),
      field("Last name", s.last_name),
      field("Email", s.email),
      field("Phone", s.phone),
      field("Account status", s.is_active ? "Active" : "Disabled"),
      field("Joined", D.when(s.created_at)),
      field("Exercises assigned", String(data.assigned)),
      field("Exercises completed", String(data.completed)),
    ]);
  }

  async function studentExercise() {
    const data = await api(`/api/students/${PAGE.studentId}`);
    const e = data.exercises.find((x) => x.exercise_id === PAGE.exerciseId);
    $("back-link").href = `/trainer/students/${PAGE.studentId}`;
    if (!e) {
      $("title").textContent = "Not assigned";
      fill($("timeline"), [], "This exercise is not assigned to this student.");
      fill($("submission"), [], "");
      return;
    }

    $("title").textContent = e.title;
    $("subtitle").textContent = `${data.student.display} · ${
      (STATUS[e.status] || [e.status])[0]
    }`;

    const step = (label, value) => row(label, [el("span", {}, value)]);
    fill(
      $("timeline"),
      [
        step("Assigned", D.when(e.assigned_at)),
        step("Due", e.due_date ? D.when(e.due_date) : "No due date"),
        step("First opened", e.last_opened_at ? D.when(e.last_opened_at) : "Not opened yet"),
        step("Submitted", e.submitted_at ? D.when(e.submitted_at) : "Not submitted"),
        step("Reviewed", e.reviewed_at ? D.when(e.reviewed_at) : "Not reviewed"),
      ],
      ""
    );

    if (!e.submission_id) {
      fill($("submission"), [], "Nothing submitted yet.");
      return;
    }
    fill(
      $("submission"),
      [
        row("Result", [
          pill(e.result || "—", e.result === "passed" ? "green" : "amber"),
          el("span", { class: "tests" }, `${e.tests_passed}/${e.tests_total} tests passed`),
          pill(e.review_status || "pending", e.review_status === "approved" ? "green" : "grey"),
        ]),
        e.comment ? row("Your comment", [el("span", {}, e.comment)]) : null,
        row(
          "Open the full review",
          [el("span", {}, "See the submitted code and change your verdict")],
          el("span", { class: "chev" }, "›"),
          () => {
            window.location.href = `/trainer/submissions/${e.submission_id}`;
          }
        ),
      ].filter(Boolean),
      ""
    );
  }

  // ── requirement 8: one exercise ──────────────────────────────────────────

  // No confirm() — browser dialogs block this environment. A first click arms
  // the button; a second click within a few seconds deletes. Clicking
  // anything else, or the timeout firing, disarms it again.
  function wireDelete(btn, exerciseId) {
    let armed = false;
    let timer = null;

    function disarm() {
      armed = false;
      btn.textContent = "Delete exercise";
      btn.classList.remove("danger");
      clearTimeout(timer);
      timer = null;
    }

    btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!armed) {
        armed = true;
        btn.textContent = "Click again to confirm";
        btn.classList.add("danger");
        timer = setTimeout(disarm, 4000);
        return;
      }
      try {
        await api(`/api/exercises/${exerciseId}`, { method: "DELETE" });
        window.location.href = "/trainer/exercises";
      } catch (err) {
        flash(err.message, "error");
        disarm();
      }
    });

    document.addEventListener("click", (event) => {
      if (armed && event.target !== btn) disarm();
    });
  }

  async function exerciseDetail() {
    const x = await api(`/api/exercises/${PAGE.exerciseId}`);
    $("title").textContent = x.title;
    $("subtitle").textContent = `${x.status} · created ${D.when(x.created_at)}`;
    wireDelete($("delete-exercise-btn"), x.id);

    const block = (label, value) =>
      value ? el("div", { class: "qblock" }, el("h3", {}, label), el("pre", {}, value)) : null;
    fill(
      $("question"),
      [
        block("Problem statement", x.problem_statement),
        block("Sample input", x.sample_input),
        block("Sample output", x.sample_output),
        block("Explanation", x.explanation),
      ].filter(Boolean),
      "This exercise has no question text."
    );

    $("test-count").textContent = x.test_cases.length;
    fill(
      $("tests"),
      x.test_cases.map((t, i) =>
        row(`Test ${i + 1}`, [
          t.is_hidden ? pill("hidden", "grey") : pill("visible", "blue"),
          el("span", {}, `in: ${t.stdin || "—"}`),
          el("span", {}, `out: ${t.expected_output || "—"}`),
        ])
      ),
      "No test cases."
    );

    $("student-count").textContent = x.students.length;
    fill(
      $("students"),
      x.students.map((s) =>
        row(
          s.display,
          [statusPill(s.status), el("span", {}, `Assigned ${D.when(s.assigned_at)}`)],
          el("span", { class: "chev" }, "›"),
          () => {
            window.location.href = `/trainer/students/${s.id}/exercises/${x.id}`;
          }
        )
      ),
      "Not assigned to anyone yet."
    );

    $("sub-count").textContent = x.submissions.length;
    fill(
      $("submissions"),
      x.submissions.map((s) =>
        row(
          s.display,
          [
            el("span", {}, D.when(s.submitted_at)),
            el(
              "span",
              { class: `tests ${s.tests_passed === s.tests_total ? "" : "fail"}` },
              `${s.tests_passed}/${s.tests_total} tests`
            ),
            pill(s.review_status || "pending", s.review_status === "approved" ? "green" : "grey"),
          ],
          el("span", { class: "chev" }, "›"),
          () => {
            window.location.href = `/trainer/submissions/${s.id}`;
          }
        )
      ),
      "Nothing submitted yet."
    );
  }

  // ── requirement 6: drafts, and assigning from here ───────────────────────

  async function drafts() {
    const [list, students] = await Promise.all([
      api("/api/exercises?status=draft"),
      api("/api/students"),
    ]);

    const items = list.map((x) => ({
      text: x.title,
      node: row(
        x.title,
        [
          pill("draft", "grey"),
          el("span", {}, x.problem_statement || "No statement yet"),
          el("span", {}, `Updated ${D.when(x.updated_at)}`),
        ],
        el(
          "div",
          { class: "row-actions" },
          el("a", { class: "cb-btn", href: `/trainer/exercises/${x.id}` }, "Open"),
          el(
            "button",
            {
              class: "cb-btn primary",
              onclick: async (event) => {
                event.stopPropagation();
                const picked = prompt(
                  `Assign "${x.title}" to which students?\n\n` +
                    students.map((s) => `${s.id}: ${s.display}`).join("\n") +
                    "\n\nEnter ids separated by commas, or 'all'.",
                  "all"
                );
                if (picked === null) return;
                const ids =
                  picked.trim().toLowerCase() === "all"
                    ? students.map((s) => s.id)
                    : picked
                        .split(",")
                        .map((n) => parseInt(n.trim(), 10))
                        .filter((n) => !isNaN(n));
                if (!ids.length) return flash("No students chosen", "error");
                try {
                  const res = await api(`/api/exercises/${x.id}/assign`, {
                    method: "POST",
                    body: JSON.stringify({ assign_to: ids }),
                  });
                  flash(`Published and assigned to ${res.assigned} student(s)`, "success");
                  setTimeout(() => window.location.reload(), 900);
                } catch (err) {
                  flash(err.message, "error");
                }
              },
            },
            "Assign"
          )
        )
      ),
    }));
    wireSearch("draft-search", items, $("draft-list"), "No drafts.", "draft-count");
  }

  // ── requirement 13: the review page ──────────────────────────────────────

  async function review() {
    const data = await api("/api/dashboard/trainer");
    const s = (data.review_queue || []).find((r) => r.id === PAGE.submissionId);
    if (!s) {
      $("subtitle").textContent = "This submission is no longer awaiting review.";
      fill($("meta"), [], "Nothing to review.");
      return;
    }
    $("title").textContent = s.exercise;
    $("subtitle").textContent = `${s.display} · submitted ${D.when(
      s.submitted_at
    )}`;
    fill($("meta"), [
      row("Outcome", [
        pill(s.result || "—", s.result === "passed" ? "green" : "amber"),
        el(
          "span",
          { class: `tests ${s.tests_passed === s.tests_total ? "" : "fail"}` },
          `${s.tests_passed}/${s.tests_total} tests passed`
        ),
      ]),
    ]);
    $("code").textContent = s.code || "";

    async function verdict(action) {
      try {
        await api(`/api/submissions/${s.id}/review`, {
          method: "POST",
          body: JSON.stringify({ action, comment: $("comment").value }),
        });
        flash(action === "approve" ? "Reviewed — approved" : "Reviewed — changes requested", "success");
        setTimeout(() => (window.location.href = "/trainer"), 800);
      } catch (err) {
        flash(err.message, "error");
      }
    }
    $("approve-btn").addEventListener("click", () => verdict("approve"));
    $("request-changes").addEventListener("click", () => verdict("request_changes"));
  }

  // ── requirement 13: the new-exercise page ────────────────────────────────

  async function exerciseForm() {
    const students = await api("/api/students");
    const picker = $("student-picker");
    students.forEach((s) => {
      picker.append(
        el(
          "label",
          { class: "pick" },
          el("input", { type: "checkbox", value: s.id }),
          el("span", {}, s.display)
        )
      );
    });
    $("pick-all").addEventListener("click", () => {
      const boxes = picker.querySelectorAll("input");
      const turnOn = [...boxes].some((b) => !b.checked);
      boxes.forEach((b) => (b.checked = turnOn));
    });

    const rows = $("test-rows");
    function addTest() {
      rows.append(
        el(
          "div",
          { class: "test-row" },
          el("input", { placeholder: "stdin" }),
          el("input", { placeholder: "expected output" }),
          el("label", { class: "pick" }, el("input", { type: "checkbox" }), el("span", {}, "hidden"))
        )
      );
    }
    $("add-test").addEventListener("click", addTest);
    addTest();

    const value = (id) => $(id).value.trim();
    $("save-exercise").addEventListener("click", async () => {
      if (!value("ex-title")) return flash("A title is required", "error");
      const test_cases = [...rows.querySelectorAll(".test-row")].map((r) => {
        const inputs = r.querySelectorAll("input");
        return {
          stdin: inputs[0].value,
          expected_output: inputs[1].value,
          is_hidden: inputs[2].checked,
        };
      });
      try {
        await api("/api/exercises", {
          method: "POST",
          body: JSON.stringify({
            title: value("ex-title"),
            problem_statement: value("ex-statement"),
            sample_input: value("ex-sample-in"),
            sample_output: value("ex-sample-out"),
            due_date: $("ex-due").value || null,
            status: $("ex-status").value,
            test_cases,
            assign_to: [...picker.querySelectorAll("input:checked")].map((b) => Number(b.value)),
          }),
        });
        flash($("ex-status").value === "draft" ? "Draft saved" : "Exercise created", "success");
        setTimeout(() => (window.location.href = "/trainer"), 800);
      } catch (err) {
        flash(err.message, "error");
      }
    });
  }

  const ROUTES = {
    student_detail: studentDetail,
    student_personal: studentPersonal,
    student_exercise: studentExercise,
    exercise_detail: exerciseDetail,
    drafts: drafts,
    review: review,
    exercise_form: exerciseForm,
  };

  const run = ROUTES[PAGE.kind];
  if (run) {
    run().catch((err) => flash(err.message || "Unable to load this page", "error"));
  }
})();
