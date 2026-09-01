// Student dashboard (SRS §3): assigned exercises, status, due dates,
// notifications, activity, and continuing from where you left off.
(function () {
  const D = window.Dash;
  const { el, pill, fill } = D;

  let data = null;
  let filter = "all";
  let search = "";

  const STATUS = {
    assigned: ["Not started", "grey"],
    in_progress: ["In progress", "blue"],
    submitted: ["Submitted · awaiting review", "blue"],
    changes_requested: ["Changes requested", "amber"],
    approved: ["Approved", "green"],
    completed: ["Completed", "green"],
  };
  const RESULT_TONES = {
    accepted: "green",
    wrong_answer: "red",
    runtime_error: "red",
    syntax_error: "red",
    pending: "grey",
  };
  const OPEN = ["assigned", "in_progress", "changes_requested"];

  function label(value) {
    return String(value || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  }

  // ── continue where you left off ───────────────────────────────────────────

  function renderResume() {
    const host = document.getElementById("resume");
    host.hidden = false;
    host.textContent = "";
    const a = data.resume;

    if (!a) {
      host.className = "resume empty-state";
      host.append(
        el(
          "div",
          { class: "grow" },
          el("div", { class: "eyebrow" }, "All caught up"),
          el("h2", {}, "Nothing waiting on you"),
          el("p", {}, "Every exercise assigned to you has been submitted or completed.")
        )
      );
      return;
    }

    host.className = "resume";
    const parts = [
      el(
        "div",
        { class: "grow" },
        el(
          "div",
          { class: "eyebrow" },
          a.last_opened_at ? "Continue where you left off" : "Start your next exercise"
        ),
        el("h2", {}, a.title),
        el(
          "p",
          {},
          a.status === "changes_requested"
            ? "Your trainer asked for modifications — update your solution and resubmit."
            : D.due(a.due_date)
        )
      ),
      el(
        "button",
        { class: "cb-btn", onclick: () => openAssignment(a) },
        a.notebook_id ? "Continue in the editor" : "Open editor"
      ),
    ];
    if (OPEN.includes(a.status) && a.notebook_id) {
      parts.push(
        el("button", { class: "cb-btn hollow", onclick: () => submit(a) }, "Submit solution")
      );
    }
    parts.forEach((node) => host.append(node));
  }

  // ── overview cards ────────────────────────────────────────────────────────

  function renderStats() {
    const s = data.stats;
    const cards = [
      { label: "Assigned", value: s.assigned, sub: "Exercises given to you", filter: "all" },
      { label: "In progress", value: s.in_progress, sub: "Opened, not submitted", filter: "open" },
      {
        label: "Awaiting review",
        value: s.submitted,
        sub: "Submitted to your trainer",
        filter: "submitted",
        tone: s.submitted ? "warn" : "",
      },
      {
        label: "Changes requested",
        value: s.changes_requested,
        sub: "Needs a fix and resubmit",
        filter: "changes_requested",
        tone: s.changes_requested ? "bad" : "",
      },
      { label: "Completed", value: s.completed, sub: "Approved by your trainer", filter: "completed", tone: "good" },
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
            "aria-pressed": filter === c.filter ? "true" : "false",
            onclick: () => setFilter(c.filter),
          },
          el("span", { class: "accent" }),
          el("span", { class: "label" }, c.label),
          el("span", { class: "value" }, c.value),
          el("span", { class: "sub" }, c.sub)
        )
      );
    });
  }

  function setFilter(next) {
    filter = next;
    document
      .querySelectorAll("#filters button")
      .forEach((b) => b.classList.toggle("active", b.dataset.filter === filter));
    renderStats();
    renderAssignments();
  }

  // ── assignment list ───────────────────────────────────────────────────────

  function matches(a) {
    if (search && !a.title.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "all") return true;
    if (filter === "open") return OPEN.includes(a.status);
    if (filter === "completed") return a.status === "approved" || a.status === "completed";
    return a.status === filter;
  }

  function renderAssignments() {
    const items = data.assignments.filter(matches);
    document.getElementById("assign-count").textContent = data.assignments.length;

    fill(
      document.getElementById("assign-list"),
      items.map((a) => {
        const [text, tone] = STATUS[a.status] || [label(a.status), "grey"];
        const closed = a.status === "approved" || a.status === "completed";
        const card = el(
          "div",
          { class: "assign-card" },
          el(
            "div",
            {},
            el("h3", {}, a.title),
            a.preview ? el("p", { class: "preview" }, a.preview) : null,
            el(
              "div",
              { class: "tags" },
              pill(text, tone),
              a.overdue ? pill("Overdue", "red") : null,
              el("span", { class: a.overdue ? "tests fail" : "tests" }, D.due(a.due_date)),
              a.submission_id
                ? pill(label(a.result), RESULT_TONES[a.result] || "grey")
                : null,
              a.submission_id
                ? el(
                    "span",
                    {
                      class: `tests ${
                        a.tests_total && a.tests_passed === a.tests_total ? "pass" : "fail"
                      }`,
                    },
                    `${a.tests_passed}/${a.tests_total} tests`
                  )
                : null
            )
          ),
          el(
            "div",
            { class: "actions" },
            el(
              "button",
              { class: "cb-btn primary", onclick: () => openAssignment(a) },
              closed ? "View" : a.notebook_id ? "Continue" : "Start"
            ),
            !closed && a.notebook_id
              ? el("button", { class: "cb-btn", onclick: () => submit(a) }, "Submit")
              : null
          )
        );

        // Trainer feedback on the latest submission (SRS §14).
        if (a.comment) {
          card.append(
            el(
              "div",
              { class: `feedback ${a.review_status === "approved" ? "approved" : ""}` },
              el(
                "strong",
                {},
                `${a.review_status === "approved" ? "Approved" : "Modifications requested"} by ${
                  a.trainer || "your trainer"
                } · ${D.ago(a.reviewed_at)}`
              ),
              a.comment
            )
          );
        }
        return card;
      }),
      filter === "all"
        ? "No exercises assigned to you yet."
        : "Nothing in this view — try another filter."
    );
  }

  // ── actions ───────────────────────────────────────────────────────────────

  async function openAssignment(a) {
    try {
      const result = await D.api(`/api/assignments/${a.id}/open`, { method: "POST" });
      window.location.href = `/nb/${result.notebook_id}`;
    } catch (err) {
      D.toast(err.message, true);
    }
  }

  async function submit(a) {
    if (!window.confirm(`Submit your solution for "${a.title}"?`)) return;
    D.toast("Running your solution against the test cases…");
    try {
      const result = await D.api(`/api/assignments/${a.id}/submit`, { method: "POST" });
      showResult(a, result);
      load();
    } catch (err) {
      D.toast(err.message, true);
    }
  }

  function showResult(a, result) {
    document.getElementById("result-title").textContent = a.title;
    const body = document.getElementById("result-body");
    const allPassed = result.total && result.passed === result.total;
    body.textContent = "";
    body.append(
      el(
        "div",
        { class: "review-meta" },
        pill(label(result.result), RESULT_TONES[result.result] || "grey"),
        el(
          "span",
          { class: `tests ${allPassed ? "pass" : "fail"}` },
          `${result.passed} of ${result.total} test cases passed`
        )
      ),
      el(
        "p",
        { class: "help" },
        result.detail ||
          (allPassed
            ? "All test cases passed. Your trainer will review it shortly."
            : "Some test cases failed — you can fix your solution and resubmit.")
      ),
      el(
        "p",
        { class: "help" },
        "Hidden test cases are included in the verdict but their details are not shown."
      )
    );
    D.openSheet("result-sheet");
  }

  // ── load ──────────────────────────────────────────────────────────────────

  // ── requirement 12: the trainer's queries, and one reply each ───────────

  const SEVERITY = { note: "grey", warning: "amber", urgent: "red" };

  function renderQueries() {
    const rows = data.queries || [];
    document.getElementById("query-count").textContent = rows.length;
    fill(
      document.getElementById("query-list"),
      rows.map((q) => {
        const body = el(
          "div",
          { class: "query-row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, q.exercise),
            el(
              "div",
              { class: "meta" },
              pill(q.severity, SEVERITY[q.severity] || "grey"),
              el("span", {}, D.ago(q.created_at))
            )
          ),
          el("div", {}, q.message)
        );

        if (q.reply) {
          body.append(el("div", { class: "meta" }, `You replied: ${q.reply}`));
          return el("div", { class: "row" }, body);
        }

        const box = el("textarea", { placeholder: "Reply to your trainer…" });
        const send = el(
          "button",
          {
            class: "cb-btn primary",
            onclick: async () => {
              if (!box.value.trim()) return D.toast("Write a reply first", true);
              try {
                await D.api(`/api/queries/${q.id}/reply`, {
                  method: "POST",
                  body: JSON.stringify({ reply: box.value.trim() }),
                });
                D.toast("Reply sent");
                load();
              } catch (err) {
                D.toast(err.message, true);
              }
            },
          },
          "Send"
        );
        body.append(el("div", { class: "query-reply" }, box, send));
        return el("div", { class: "row" }, body);
      }),
      "Nothing from your trainer right now."
    );
  }

  async function load() {
    try {
      data = await D.api("/api/dashboard/student");
    } catch (err) {
      if (err.message !== "unauthenticated") D.toast(err.message, true);
      return;
    }
    renderResume();
    renderStats();
    renderAssignments();
    renderQueries();
    D.renderNotifications(data.notifications, data.unread);
  }

  document.querySelectorAll("#filters button").forEach((b) =>
    b.addEventListener("click", () => setFilter(b.dataset.filter))
  );
  document.getElementById("assign-search").addEventListener("input", (event) => {
    search = event.target.value;
    renderAssignments();
  });

  D.initChrome(load);
  load();
})();
