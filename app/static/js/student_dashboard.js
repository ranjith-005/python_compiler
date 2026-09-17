// Student dashboard (SRS §3): one card per assignment status, each a link
// into the exercises page pre-filtered, the deadlines still open and due, a
// placeholder for online sessions, and the activity feed ten at a time.
(function () {
  const D = window.Dash;
  const { el, pill, fill } = D;

  let data = null;

  // The filter mapping is fixed by spec: card -> ?filter= key on
  // /student/exercises -> the rows it matches there. One card per bucket, so
  // the figure and the list always agree.
  //
  // Unsubmitted work is one card, not two: whether it has been opened does not
  // change what the student owes, only the due date does. Everything still in
  // hand is Assigned; once the due date passes the same work is Pending.
  const CARDS = [
    {
      count: (s) => s.assigned + s.in_progress,
      label: "Assigned",
      sub: "Due date still ahead",
      filter: "assigned",
      icon: "📘",
    },
    {
      count: (s) => s.pending,
      label: "Pending",
      sub: "Past due, not submitted",
      filter: "pending",
      tone: "bad",
      icon: "⏰",
    },
    {
      count: (s) => s.submitted,
      label: "Awaiting review",
      sub: "Submitted to your trainer",
      filter: "submitted",
      tone: "warn",
      icon: "📤",
    },
    {
      count: (s) => s.completed,
      label: "Completed",
      sub: "Approved by your trainer",
      filter: "completed",
      tone: "good",
      icon: "✅",
    },
  ];

  // Work the student still owes, including anything past due.
  const OPEN = ["assigned", "in_progress", "pending"];

  function renderStats() {
    const s = data.stats;
    const host = document.getElementById("stats");
    host.textContent = "";
    CARDS.forEach((c) => {
      const value = c.count(s);
      const tone = c.tone === "warn" || c.tone === "bad" ? (value ? c.tone : "") : c.tone || "";
      host.append(
        el(
          "a",
          { class: `stat ${tone}`, href: `/student/exercises?filter=${c.filter}` },
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
      "No upcoming deadlines."
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
  load().then(() => {
    if (!data) return;
    // Wired once: the pager owns its own paging from here, so a later reload
    // of the cards must not stack a second set of click handlers on it.
    D.activityPager("activity-list", "activity-pager", data.activity, data.activity_total);
  });
})();
