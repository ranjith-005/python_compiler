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

  // The three not-yet-submitted statuses this worklist is made of.
  const OUTSTANDING = { assigned: "Assigned", in_progress: "In progress", pending: "Pending" };

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
      const rows = (data.pending || []).filter((x) => dueInRange(x.due_date));
      if (!rows.length) return empty("Nothing outstanding — everything has been submitted.");
      rows.forEach((x) =>
        list.append(
          row(
            x.exercise,
            [x.display, OUTSTANDING[x.status] || x.status,
             x.due_date ? due(x.due_date) : null,
             x.overdue ? "Past due" : null],
            `/trainer/exercises/${x.exercise_id}?view=pending`
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
  const ASSIGNMENT_STATE = {
    assigned: ["Assigned", "grey"],
    in_progress: ["In progress", "blue"],
    submitted: ["Submitted", "amber"],
    pending: ["Pending · past due", "red"],
    completed: ["Completed", "green"],
  };

  let queries = null;
  let historyMode = false;
  const historyBtn = document.getElementById("history-toggle");

  async function decide(request, action) {
    // The message is written for this student on this query, so two students
    // asking about the same exercise can be answered differently.
    const prompt_ = action === "approve"
      ? `Message to ${request.student_display} (optional):`
      : `Why are you declining ${request.student_display}? They will see this:`;
    const message = window.prompt(prompt_, "");
    if (message === null) return;
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

  function queryRow(r) {
    const request = QUERY_STATUS[r.status] || [r.status, "grey"];
    const state = ASSIGNMENT_STATE[r.assignment_status] || [r.assignment_status, "grey"];
    return el(
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
            el("button", { class: "cb-btn", onclick: () => decide(r, "reject") }, "Decline"),
            el("button", { class: "cb-btn primary", onclick: () => decide(r, "approve") },
               "Grant access")
          )
        : null
    );
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
