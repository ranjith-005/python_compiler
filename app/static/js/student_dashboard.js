// Student dashboard (SRS §3): four overview cards, each a link into the
// exercises page pre-filtered, the deadlines still open and due, a placeholder
// for online sessions, and the activity feed ten at a time.
(function () {
  const D = window.Dash;
  const { el, pill, fill } = D;

  let data = null;

  // The filter mapping is fixed by spec: card -> ?filter= key on
  // /student/exercises -> assignment status(es) it matches there.
  //
  // "Changes requested" is deliberately absent: the requirement removed both
  // that card and its filter tab, so a card pointing at a tab that no longer
  // exists would land on an unfiltered list.
  const CARDS = [
    {
      // First card by requirement: what is closing in, before what merely
      // exists. Its value is counted, not read off `stats`, because it must
      // equal the length of the list it opens -- same predicate, same clock.
      key: "upcoming",
      label: "Upcoming deadlines",
      sub: "Open work due in 7 days",
      filter: "open",
      deadline: "week",
      tone: "warn",
      icon: "⏰",
      count: (d) =>
        d.assignments.filter(
          (a) => OPEN.includes(a.status) && D.matchesDeadline(a, "week")
        ).length,
    },
    {
      key: "assigned",
      label: "Assigned",
      sub: "Exercises given to you",
      filter: "all",
      icon: "📘",
    },
    {
      key: "in_progress",
      label: "In progress",
      sub: "Opened, not submitted",
      filter: "in_progress",
      icon: "✍️",
    },
    {
      key: "submitted",
      label: "Awaiting review",
      sub: "Submitted to your trainer",
      filter: "submitted",
      tone: "warn",
      icon: "📤",
    },
    {
      key: "completed",
      label: "Completed",
      sub: "Approved by your trainer",
      filter: "completed",
      tone: "good",
      icon: "✅",
    },
  ];

  // Statuses that mean "the student still owes work on this assignment".
  const OPEN = ["assigned", "in_progress", "changes_requested"];

  function renderStats() {
    const s = data.stats;
    const host = document.getElementById("stats");
    host.textContent = "";
    host.classList.add("five"); // five cards, one row -- see .stat-grid.five
    CARDS.forEach((c) => {
      const value = c.count ? c.count(data) : s[c.key];
      const tone = c.tone === "warn" || c.tone === "bad" ? (value ? c.tone : "") : c.tone || "";
      const href = `/student/exercises?filter=${c.filter}` +
                   (c.deadline ? `&deadline=${c.deadline}` : "");
      host.append(
        el(
          "a",
          { class: `stat ${tone}`, href },
          el("span", { class: "stat-icon" }, c.icon),
          el("span", { class: "value" }, value),
          el("span", { class: "label" }, c.label),
          el("span", { class: "sub" }, c.sub)
        )
      );
    });
  }

  // ── calendar ────────────────────────────────────────────────────────────

  // Calendar replaces the deadline list (spec: deadlines are a glance here and
  // actionable on the Exercises page). Unlike the trainer's, the student
  // payload carries no `deadlines` array -- open work with a due date is
  // derived from `assignments`, exactly as the old list did. Those rows carry
  // an ASSIGNMENT id, so the link goes to the solve page.
  let calMonth = new Date();

  function paintCalendar() {
    if (!data) return;
    const due = data.assignments.filter((a) => OPEN.includes(a.status) && a.due_date);
    D.renderCalendar("calendar", due, calMonth,
                     (a) => `/student/assignments/${a.id}/solve`);
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
    paintCalendar();
    D.renderNotifications(data.notifications, data.unread);
  }

  D.initChrome(load);
  load().then(() => {
    if (!data) return;
    // Wired once: the pager owns its own paging from here, so a later reload
    // of the cards must not stack a second set of click handlers on it.
    D.activityPager("activity-list", "activity-pager", data.activity, data.activity_total);
    // Same once-only rule as the pager: the month buttons keep their own
    // state, so a card reload must not stack a second pair of handlers.
    document.getElementById("cal-prev").addEventListener("click", () => {
      calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() - 1, 1);
      paintCalendar();
    });
    document.getElementById("cal-next").addEventListener("click", () => {
      calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() + 1, 1);
      paintCalendar();
    });
  });
})();
