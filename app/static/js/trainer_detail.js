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
    pending: ["Pending", "red"],
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
    const { href = null, active = false } = opts || {};
    const classes = `stat ${tone || ""} ${active ? "active" : ""}`.trim();
    return el(
      href ? "a" : "div",
      href ? { class: classes, href } : { class: classes },
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

  const { assignmentMatchesFilter } = D;

  // Which assignment rows each card -- and each dropdown value -- narrows the
  // list to. "open" stays as an alias for in_progress; it is not a status.
  const CARD_FILTERS = {
    all: () => true,
    assigned: (e) => assignmentMatchesFilter(e, "assigned"),
    in_progress: (e) => assignmentMatchesFilter(e, "in_progress"),
    open: (e) => assignmentMatchesFilter(e, "in_progress"),
    submitted: (e) => assignmentMatchesFilter(e, "submitted"),
    pending: (e) => assignmentMatchesFilter(e, "pending"),
    completed: (e) => assignmentMatchesFilter(e, "completed"),
    late: (e) => e.late,
  };
  const CARD_TITLES = {
    all: "every exercise",
    assigned: "exercises not opened yet",
    in_progress: "exercises still in progress",
    open: "exercises still in progress",
    submitted: "exercises awaiting your review",
    pending: "exercises past due without a submission",
    completed: "completed exercises",
    late: "exercises submitted late",
  };

  async function studentDetail() {
    const data = await api(`/api/students/${PAGE.studentId}`);
    $("student-name").textContent = data.full_name;
    $("student-sub").textContent = `Their progress on everything you have assigned.`;
    $("personal-link").href = `/trainer/students/${PAGE.studentId}/personal`;

    const urlParams = new URLSearchParams(window.location.search);
    const view = urlParams.get('view') || 'all';

    const card = (key) => `?view=${key}`;

    fill($("stats"), [
      stat("Assigned", data.assigned, "Exercises from you", "", {
        href: card("all"), active: view === "all" }),
      stat("Completed", data.completed, "Marked done", "good", {
        href: card("completed"), active: view === "completed" }),
      stat("Pending", data.pending, "Past due, not submitted", data.pending ? "bad" : "", {
        href: card("pending"), active: view === "pending" }),
      stat("Awaiting review", data.awaiting, "Submitted, not yet reviewed", "", {
        href: card("submitted"), active: view === "submitted" }),
      stat("Late", data.late, "Submitted after the due date", data.late ? "bad" : "", {
        href: card("late"), active: view === "late" }),
      // The three figures below are read-only by requirement: no href, so
      // nothing about them invites a click.
      stat("On-time rate", `${data.on_time_rate}%`, "Of what was submitted", ""),
      stat("Avg tests passed", `${data.avg_tests}%`, "Across graded submissions", ""),
      // Real clock stamp of when this student was last on the platform -
      // when() renders the actual date and time, and logout always refreshes
      // the stamp, so the card shows the true last-seen / logged-out moment.
      stat("Last active", data.last_active ? D.when(data.last_active) : "Never",
           data.last_active ? "Last seen — logout included" : "No sessions recorded", ""),
    ]);

    $("ex-heading").textContent = "Assigned exercises";

    function renderExercises(viewKey) {
      const match = CARD_FILTERS[viewKey] || CARD_FILTERS.all;
      const filteredExercises = data.exercises.filter(match);
      const items = filteredExercises.map((e) => ({
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
          () => {
            window.location.href = `/trainer/students/${PAGE.studentId}/exercises/${e.exercise_id}`;
          }
        ),
      }));
      wireSearch(
        "ex-search",
        items,
        $("ex-list"),
        viewKey === "all" ? "Nothing assigned yet." : `Nothing here — no ${CARD_TITLES[viewKey]}.`,
        "ex-count"
      );
    }
    
    renderExercises(view);
    const exFilterSel = document.getElementById("ex-filter");
    if (exFilterSel) {
      exFilterSel.value = view; // initialize dropdown from URL if present
      exFilterSel.addEventListener("change", (ev) => renderExercises(ev.target.value));
    }

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
      fill($("query-access"), [], "");
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

    // ── query access (replaces the old submission panel) ───────────────────
    // The student's ask to reopen a pending exercise, in the same design as
    // the queries page behind the Query raised card, so access can be granted
    // here too — for this one student, not the whole exercise.
    const QUERY_STATUS = {
      pending: ["Waiting on you", "amber"],
      approved: ["Access granted", "green"],
      rejected: ["Declined", "red"],
    };

    async function decideQuery(action) {
      const who = data.student.display;
      const prompt_ = action === "approve"
        ? `Message to ${who} (optional):`
        : `Why are you declining ${who}? They will see this:`;
      const message = window.prompt(prompt_, "");
      if (message === null) return;
      try {
        await api(`/api/access-requests/${e.query_id}/decide`, {
          method: "POST",
          body: JSON.stringify({ action, message }),
        });
        flash(action === "approve" ? "Access granted" : "Query declined", "success");
        await studentExercise(); // redraw with the decision applied
      } catch (err) {
        flash(err.message, "error");
      }
    }

    const host = $("query-access");
    if (!e.query_id) {
      const note = e.status === "pending"
        ? "No query raised yet — this student can ask for access from their solve page."
        : "Queries appear here once the deadline passes without a submission.";
      fill(host, [], note);
      return;
    }

    const state = QUERY_STATUS[e.query_status] || [e.query_status, "grey"];
    const exerciseState = STATUS[e.status] || [e.status, "grey"];
    fill(
      host,
      [
        el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el(
              "div",
              { class: "meta" },
              pill(state[0], state[1]),
              pill(exerciseState[0], exerciseState[1]),
              el("span", {}, `Raised ${D.ago(e.query_created_at)}`)
            ),
            e.query_message
              ? el("div", { class: "request-quote", text: e.query_message })
              : null,
            e.query_decision
              ? el("div", { class: "request-quote answer", text: `You replied: ${e.query_decision}` })
              : null
          ),
          e.query_status === "pending"
            ? el(
                "div",
                { class: "actions" },
                el("button", { class: "cb-btn", onclick: () => decideQuery("reject") }, "Decline"),
                el("button", { class: "cb-btn primary", onclick: () => decideQuery("approve") },
                   "Grant access")
              )
            : null
        ),
      ],
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

    const allTests = x.test_cases;

    function applyTestFilter(filter) {
      const filtered = filter === "all"
        ? allTests
        : allTests.filter((t) => (filter === "hidden" ? t.is_hidden : !t.is_hidden));
      $("test-count").textContent = filtered.length;
      fill(
        $("tests"),
        filtered.map((t, i) =>
          row(`Test ${i + 1}`, [
            t.is_hidden ? pill("hidden", "grey") : pill("visible", "blue"),
            el("span", {}, `in: ${t.stdin || "—"}`),
            el("span", {}, `out: ${t.expected_output || "—"}`),
          ])
        ),
        filter === "all" ? "No test cases." : `No ${filter} test cases.`
      );
    }

    applyTestFilter("all");
    const testFilterSel = document.getElementById("test-filter");
    if (testFilterSel) {
      testFilterSel.addEventListener("change", (ev) => {
        applyTestFilter(ev.target.value);
      });
    }

    // Check if this is a pending view (from pending submissions page)
    const urlParams = new URLSearchParams(window.location.search);
    const isPendingView = urlParams.get('view') === 'pending';

    // Update the header based on view
    const studentHeader = document.querySelector('#students').closest('section').querySelector('header h2');
    if (studentHeader) {
      studentHeader.textContent = isPendingView ? 'Pending Students' : 'Assigned to';
    }

    // Hide the filter dropdown in pending view
    const studentFilterWrap = document.querySelector('#student-filter').closest('.activity-filter-wrap');
    if (studentFilterWrap && isPendingView) {
      studentFilterWrap.style.display = 'none';
    }

    // All students — store and filter on tab clicks
    const allStudents = x.students;

    function applyStudentFilter(filter) {
      const filtered =
        filter === "all"
          ? allStudents
          : allStudents.filter((s) => assignmentMatchesFilter(s, filter));
      $("student-count").textContent = filtered.length;
      D.fill(
        $("students"),
        filtered.map((s) =>
          row(
            s.display,
            [statusPill(s.status), el("span", {}, `Assigned ${D.when(s.assigned_at)}`)],
            el("span", { class: "chev" }, "›"),
            () => {
              window.location.href = `/trainer/students/${s.id}/exercises/${x.id}`;
            }
          )
        ),
        filter === "all" ? "Not assigned to anyone yet." : `No students with status "${filter}".`
      );
    }

    // If pending view, show only pending students by default
    if (isPendingView) {
      const pendingStudents = allStudents.filter((s) => assignmentMatchesFilter(s, "pending"));
      $("student-count").textContent = pendingStudents.length;
      D.fill(
        $("students"),
        pendingStudents.map((s) =>
          row(
            s.display,
            [statusPill(s.status), el("span", {}, `Assigned ${D.when(s.assigned_at)}`)],
            el("span", { class: "chev" }, "›"),
            () => {
              window.location.href = `/trainer/students/${s.id}/exercises/${x.id}`;
            }
          )
        ),
        "No pending students for this exercise."
      );
    } else {
      $("student-count").textContent = allStudents.length;
      applyStudentFilter("all");

      const studentFilterSel = document.getElementById("student-filter");
      if (studentFilterSel) {
        studentFilterSel.addEventListener("change", (ev) => {
          applyStudentFilter(ev.target.value);
        });
      }
    }
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
