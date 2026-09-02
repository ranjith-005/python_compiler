// Student dashboard (SRS §3): five overview cards, each a link into the
// exercises page pre-filtered, plus the deadlines still open and due.
(function () {
  const D = window.Dash;
  const { el, pill, fill } = D;

  let data = null;

  // The filter mapping is fixed by spec: card -> ?filter= key on
  // /student/exercises -> assignment status(es) it matches there.
  const CARDS = [
    { key: "assigned", label: "Assigned", sub: "Exercises given to you", filter: "all" },
    {
      key: "in_progress",
      label: "In progress",
      sub: "Opened, not submitted",
      filter: "in_progress",
    },
    {
      key: "submitted",
      label: "Awaiting review",
      sub: "Submitted to your trainer",
      filter: "submitted",
      tone: "warn",
    },
    {
      key: "changes_requested",
      label: "Changes requested",
      sub: "Needs a fix and resubmit",
      filter: "changes_requested",
      tone: "bad",
    },
    {
      key: "completed",
      label: "Completed",
      sub: "Approved by your trainer",
      filter: "completed",
      tone: "good",
    },
  ];

  // Statuses that mean "the student still owes work on this assignment".
  const OPEN = ["assigned", "in_progress", "changes_requested"];

  function renderStats() {
    const s = data.stats;
    const host = document.getElementById("stats");
    host.textContent = "";
    CARDS.forEach((c) => {
      const value = s[c.key];
      const tone = c.tone === "warn" || c.tone === "bad" ? (value ? c.tone : "") : c.tone || "";
      host.append(
        el(
          "a",
          { class: `stat ${tone}`, href: `/student/exercises?filter=${c.filter}` },
          el("span", { class: "accent" }),
          el("span", { class: "label" }, c.label),
          el("span", { class: "value" }, value),
          el("span", { class: "sub" }, c.sub)
        )
      );
    });
  }

  // ── upcoming deadlines ──────────────────────────────────────────────────

  function renderDeadlines() {
    // Open work with a due date; `assignments` is already ordered soonest
    // due date first (nulls last), so filtering keeps that order.
    const items = data.assignments.filter((a) => OPEN.includes(a.status) && a.due_date);

    fill(
      document.getElementById("deadline-list"),
      items.map((a) =>
        el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, a.title),
            el(
              "div",
              { class: "meta" },
              a.overdue ? pill("Overdue", "red") : null,
              el("span", { class: a.overdue ? "tests fail" : "tests" }, D.due(a.due_date))
            )
          ),
          el(
            "div",
            { class: "actions" },
            el(
              "a",
              { class: "cb-btn primary", href: `/student/assignments/${a.id}/solve` },
              a.status === "assigned" ? "Start" : "Continue"
            )
          )
        )
      ),
      "Nothing due — you're all caught up."
    );
  }

  // ── load ─────────────────────────────────────────────────────────────────

  async function load() {
    try {
      data = await D.api("/api/dashboard/student");
    } catch (err) {
      if (err.message !== "unauthenticated") D.flash(err.message, "error");
      return;
    }
    renderStats();
    renderDeadlines();
    D.renderNotifications(data.notifications, data.unread);
  }

  D.initChrome(load);
  load();
})();
