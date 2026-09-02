// Student exercises (moved off the dashboard, SRS §3): the full assignments
// list, its search box and six filter tabs, and the trainer-queries sidebar.
(function () {
  const D = window.Dash;
  const { el, pill, fill } = D;

  let data = null;
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
  const TAB_FILTERS = ["all", "open", "in_progress", "submitted", "changes_requested", "completed"];

  function label(value) {
    return String(value || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  }

  // The dashboard's cards link here with ?filter=<key>; default to "all"
  // for a bare visit or an unrecognised value.
  function initialFilter() {
    const requested = new URLSearchParams(window.location.search).get("filter");
    return TAB_FILTERS.includes(requested) ? requested : "all";
  }

  let filter = initialFilter();

  // ── overview cards' filter mapping, mirrored here as the tab logic ─────────

  function matches(a) {
    if (search && !a.title.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "all") return true;
    if (filter === "open") return OPEN.includes(a.status);
    if (filter === "completed") return a.status === "approved" || a.status === "completed";
    return a.status === filter;
  }

  function setFilter(next) {
    filter = next;
    document
      .querySelectorAll("#filters button")
      .forEach((b) => b.classList.toggle("active", b.dataset.filter === filter));
    renderAssignments();
  }

  // ── assignment list ───────────────────────────────────────────────────────

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
              closed ? "View" : a.status === "assigned" ? "Start" : "Continue"
            ),
            !closed && a.status !== "assigned"
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
      await D.api(`/api/assignments/${a.id}/open`, { method: "POST" });
      window.location.href = `/student/assignments/${a.id}/solve`;
    } catch (err) {
      D.flash(err.message, "error");
    }
  }

  async function submit(a) {
    if (!window.confirm(`Submit your solution for "${a.title}"?`)) return;
    D.flash("Running your solution against the test cases…", "info");
    try {
      const result = await D.api(`/api/assignments/${a.id}/submit`, { method: "POST" });
      showResult(a, result);
      load();
    } catch (err) {
      D.flash(err.message, "error");
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
              if (!box.value.trim()) return D.flash("Write a reply first", "error");
              try {
                await D.api(`/api/queries/${q.id}/reply`, {
                  method: "POST",
                  body: JSON.stringify({ reply: box.value.trim() }),
                });
                D.flash("Reply sent", "success");
                load();
              } catch (err) {
                D.flash(err.message, "error");
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

  // ── load ──────────────────────────────────────────────────────────────────

  async function load() {
    try {
      data = await D.api("/api/dashboard/student");
    } catch (err) {
      if (err.message !== "unauthenticated") D.flash(err.message, "error");
      return;
    }
    renderAssignments();
    renderQueries();
  }

  document
    .querySelectorAll("#filters button")
    .forEach((b) => b.classList.toggle("active", b.dataset.filter === filter));
  document.querySelectorAll("#filters button").forEach((b) =>
    b.addEventListener("click", () => setFilter(b.dataset.filter))
  );
  document.getElementById("assign-search").addEventListener("input", (event) => {
    search = event.target.value;
    renderAssignments();
  });

  load();
})();
