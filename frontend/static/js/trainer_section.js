// One page for every trainer list: exercises, review queue, pending work,
// completed work and the queries students raise. Which one is decided by
// window.SECTION.
//
// Rows are built with el(), never by assembling raw HTML strings: these
// render trainer-authored titles and student-authored names, both of which
// reach a trainer's browser.
(function () {
  const D = window.Dash;
  const { el, when, due } = D;
  const list = document.getElementById("section-list");
  const section = window.SECTION;

  // Restored date-range filters (req 3): only these two sections ever had
  // them, so only these two get the controls back. Filtering is client side
  // over `due_date`, which the dashboard endpoint already returns.
  const fromInput = document.getElementById("filter-from");
  const toInput = document.getElementById("filter-to");

  function dueInRange(dueDate) {
    if (!dueDate) return true; // no due date is never filtered out
    const from = fromInput ? fromInput.value : "";
    const to = toInput ? toInput.value : "";
    const day = dueDate.slice(0, 10);
    if (from && day < from) return false;
    if (to && day > to) return false;
    return true;
  }

  function row(title, metaParts, href) {
    const body = el(
      "div",
      {},
      el("div", { class: "title", text: title }),
      el("div", { class: "meta", text: metaParts.filter(Boolean).join(" · ") })
    );
    return href
      ? el("a", { class: "row", href }, body)
      : el("div", { class: "row" }, body);
  }

  function empty(message) {
    list.append(el("p", { class: "empty-note", text: message }));
  }

  const RENDER = {
    exercises(data) {
      const rows = (data.exercises || []).filter((x) => dueInRange(x.due_date));
      if (!rows.length) return empty("No exercises created yet.");
      rows.forEach((x) =>
        list.append(
          row(
            x.title,
            [x.status, `${x.assigned} assigned`, `${x.tests} test cases`,
             x.due_date ? due(x.due_date) : null],
            `/trainer/exercises/${x.id}`
          )
        )
      );
    },
    queue(data) {
      const rows = data.review_queue || [];
      if (!rows.length) return empty("Nothing is awaiting review.");
      rows.forEach((x) =>
        list.append(
          row(
            x.exercise,
            [x.display, `${x.tests_passed}/${x.tests_total} tests`, when(x.submitted_at)],
            `/trainer/submissions/${x.id}`
          )
        )
      );
    },
    pending(data) {
      // Everything not yet submitted: assigned, in progress or past due.
      // One row per exercise, however many students still owe it -- opening
      // the row is what names them, on the exercise's own pending view.
      const rows = (data.pending || []).filter((x) => dueInRange(x.due_date));
      if (!rows.length) return empty("Nothing outstanding — everything has been submitted.");

      const byExercise = new Map();
      rows.forEach((x) => {
        let group = byExercise.get(x.exercise_id);
        if (!group) {
          group = { exercise: x.exercise, exercise_id: x.exercise_id,
                    due_date: x.due_date, students: 0, overdue: 0 };
          byExercise.set(x.exercise_id, group);
        }
        group.students += 1;
        if (x.overdue) group.overdue += 1;
        // The soonest deadline across the class is the one the trainer acts on.
        if (x.due_date && (!group.due_date || x.due_date < group.due_date)) {
          group.due_date = x.due_date;
        }
      });

      byExercise.forEach((g) =>
        list.append(
          row(
            g.exercise,
            [`${g.students} student${g.students === 1 ? "" : "s"} pending`,
             g.due_date ? due(g.due_date) : null,
             g.overdue ? `${g.overdue} past due` : null],
            `/trainer/exercises/${g.exercise_id}?view=pending`
          )
        )
      );
    },
    completed(data) {
      const rows = data.completed || [];
      if (!rows.length) return empty("No completed work yet.");
      rows.forEach((x) =>
        list.append(
          row(
            x.exercise,
            [x.display,
             x.tests_total ? `${x.tests_passed}/${x.tests_total} tests` : null,
             when(x.submitted_at)],
            x.student_id ? `/trainer/students/${x.student_id}` : null
          )
        )
      );
    },
  };

  // ── queries section: students asking for a pending exercise back ──────────
  // New queries wait on the trainer's decision — granting access reopens that
  // one student's exercise and nobody else's. The answered ones stay behind
  // the History button on this same page. This section has its own endpoint,
  // because the full history does not ride along in the dashboard payload.

  const QUERY_STATUS = {
    pending: ["Waiting on you", "amber"],
    approved: ["Access granted", "green"],
    rejected: ["Declined", "red"],
  };
  // The four buckets, worded as everywhere else: unsubmitted work reads
  // "Assigned" until its due date passes, and "Pending" after it.
  const ASSIGNMENT_STATE = {
    ...D.ASSIGNMENT_LABELS,
    pending: ["Pending · past due", "red"],
  };

  let queries = null;
  let historyMode = false;
  const historyBtn = document.getElementById("history-toggle");

  async function decide(request, action, message) {
    // The message is written for this student on this query, so two students
    // asking about the same exercise can be answered differently.
    try {
      await D.api(`/api/access-requests/${request.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ action, message }),
      });
      D.flash(action === "approve" ? "Access granted" : "Query declined", "success");
      await loadQueries();
    } catch (err) {
      D.flash(err.message, "error");
    }
  }

  // The reply used to be typed into a window.prompt, which covered the query
  // the trainer was answering. It is written in a section of its own under
  // that query instead: the request stays on screen while it is answered.
  function decisionForm(r, action, close) {
    const approve = action === "approve";
    const box = el("textarea", {
      rows: "2",
      class: "decision-input",
      placeholder: approve
        ? `Message to ${r.student_display} (optional)`
        : `Why are you declining ${r.student_display}? They will see this.`,
    });
    const confirm = el(
      "button",
      {
        class: `cb-btn ${approve ? "primary" : ""}`,
        onclick: async () => {
          const message = box.value.trim();
          if (!approve && !message) {
            return D.flash("Write a reason before declining.", "error");
          }
          confirm.disabled = true;
          await decide(r, action, message);
        },
      },
      approve ? "Grant access" : "Decline query"
    );
    const form = el(
      "div",
      { class: `query-decision ${approve ? "approve" : "decline"}` },
      el(
        "div",
        { class: "decision-head" },
        approve
          ? `Reopen "${r.title}" for ${r.student_display}`
          : `Decline ${r.student_display}'s request`
      ),
      box,
      el(
        "div",
        { class: "decision-actions" },
        confirm,
        el("button", { class: "cb-btn", onclick: close }, "Cancel")
      )
    );
    setTimeout(() => box.focus(), 0);
    return form;
  }

  function queryRow(r) {
    const request = QUERY_STATUS[r.status] || [r.status, "grey"];
    const bucket = D.assignmentBucket({ status: r.assignment_status, due_date: r.due_date });
    const state = ASSIGNMENT_STATE[bucket] || [r.assignment_status, "grey"];
    const item = el("div", { class: "query-item" });
    const decision = el("div", { class: "decision-slot" });

    function openForm(action) {
      decision.textContent = "";
      decision.append(decisionForm(r, action, () => (decision.textContent = "")));
    }

    const body = el(
      "div",
      { class: "row" },
      el(
        "div",
        {},
        el("div", { class: "title", text: `${r.student_display} — ${r.title}` }),
        el(
          "div",
          { class: "meta" },
          D.pill(request[0], request[1]),
          D.pill(state[0], state[1]),
          r.due_date ? el("span", { class: "tests" }, due(r.due_date)) : null,
          el("span", {}, D.ago(r.created_at))
        ),
        r.message ? el("div", { class: "request-quote", text: r.message }) : null,
        r.decision_message
          ? el("div", { class: "request-quote answer", text: `You replied: ${r.decision_message}` })
          : null
      ),
      r.status === "pending"
        ? el(
            "div",
            { class: "actions" },
            el("a", { class: "cb-btn", href: `/trainer/exercises/${r.exercise_id}?view=pending` },
               "Exercise"),
            el("button", { class: "cb-btn", onclick: () => openForm("reject") }, "Decline"),
            el("button", { class: "cb-btn primary", onclick: () => openForm("approve") },
               "Grant access")
          )
        : null
    );

    item.append(body, decision);
    return item;
  }

  function renderQueries() {
    const heading = document.getElementById("queries-heading");
    const count = document.getElementById("query-count");
    const rows = historyMode
      ? (queries || [])
          .filter((r) => r.status !== "pending")
          .sort((a, b) =>
            String(b.decided_at || b.created_at)
              .localeCompare(String(a.decided_at || a.created_at)))
      : (queries || []).filter((r) => r.status === "pending");

    if (heading) heading.textContent = historyMode ? "Query history" : "Queries raised";
    if (count) count.textContent = String(rows.length);
    if (historyBtn) historyBtn.textContent = historyMode ? "New queries" : "History";

    list.textContent = "";
    if (!rows.length) {
      return empty(
        historyMode ? "No query history yet." : "No new queries — nothing is waiting on you."
      );
    }
    rows.forEach((r) => list.append(queryRow(r)));
  }

  function loadQueries() {
    return D.api("/api/access-requests")
      .then((rows) => {
        queries = rows;
        renderQueries();
      })
      .catch((err) => {
        list.textContent = "";
        empty(err.message || "Unable to load queries.");
      });
  }

  if (historyBtn) {
    historyBtn.addEventListener("click", () => {
      historyMode = !historyMode;
      renderQueries();
    });
  }

  let data = null;
  function render() {
    if (!data) return;
    list.textContent = "";
    (RENDER[section] || RENDER.exercises)(data);
  }

  if (section === "queries") {
    loadQueries();
  } else {
    D.api("/api/dashboard/trainer")
      .then((loaded) => {
        data = loaded;
        render();
      })
      .catch((err) => {
        list.textContent = "";
        empty(err.message || "Unable to load this page.");
      });
  }

  if (fromInput && toInput) {
    fromInput.addEventListener("input", render);
    toInput.addEventListener("input", render);
  }
})();
