// Student dashboard (SRS §3): five overview cards, each a link into the
// exercises page pre-filtered, a calendar carrying deadlines, the trainer's
// online sessions and the student's own marks, and the activity feed ten at
// a time.
(function () {
  const D = window.Dash;
  const { el } = D;

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
    },
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
          el("span", { class: "value" }, value),
          el("span", { class: "label" }, c.label),
          el("span", { class: "sub" }, c.sub)
        )
      );
    });
  }

  // -- calendar -----------------------------------------------------------

  // The student's calendar carries three things: the deadlines on their own
  // open work, the online sessions their trainer scheduled, and whatever they
  // marked for themselves. Only the first is derived here -- the payload
  // carries no `deadlines` array for a student, so open work with a due date
  // is read off `assignments`, exactly as the old list did. Those rows carry
  // an ASSIGNMENT id, so the link goes to the solve page.
  function deadlineMarks() {
    if (!data) return [];
    return data.assignments
      .filter((a) => OPEN.includes(a.status) && a.due_date)
      .map((a) => ({
        kind: "deadline",
        title: a.title,
        sub: D.when(a.due_date),
        date: a.due_date,
        link: `/student/assignments/${a.id}/solve`,
      }));
  }

  const calendar = D.initCalendar({ deadlinesFor: deadlineMarks });

  // ── load ─────────────────────────────────────────────────────────────────

  async function load() {
    try {
      data = await D.api("/api/dashboard/student");
    } catch (err) {
      if (err.message !== "unauthenticated") D.flash(err.message, "error");
      return;
    }
    renderStats();
    calendar.repaint();
    D.renderNotifications(data.notifications, data.unread);
  }

  D.initChrome(load);
  load().then(() => {
    if (!data) return;
    // Wired once: the pager owns its own paging from here, so a later reload
    // of the cards must not stack a second set of click handlers on it.
    D.activityPager("activity-list", "activity-pager", data.activity, data.activity_total);
    // The month buttons and the event dialog were wired once when the
    // calendar was built; this only fetches the rows they paint.
    calendar.reload();
  });
})();
