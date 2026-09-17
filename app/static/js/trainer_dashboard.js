// Trainer dashboard (SRS §2): five linked overview cards, the activity feed
// ten at a time, and the placeholder for online sessions. Everything the
// cards used to show inline lives on its own page (students, pending, queue,
// exercises, queries) -- the reopen-requests panel included, which the Query
// raised card now answers on its own page with the history behind a button.
(function () {
  const D = window.Dash;
  const { el } = D;

  let data = null;

  // ── overview cards ────────────────────────────────────────────────────────

  function renderStats() {
    const s = data.stats;
    const cards = [
      { label: "Students", value: s.students, sub: "On your roster",
        href: "/trainer/students", icon: "👥" },
      { label: "Pending submissions", value: s.pending,
        sub: s.overdue ? `${s.overdue} past due` : "Assigned, not yet in",
        tone: s.overdue ? "bad" : "", href: "/trainer/pending", icon: "⏳" },
      { label: "Awaiting review", value: s.awaiting_review,
        sub: "Submitted, needs your verdict",
        tone: s.awaiting_review ? "warn" : "", href: "/trainer/queue", icon: "📝" },
      // No Exercises card: the top bar already links the Exercises module,
      // so a fifth card would just duplicate that navigation.
      // ?? 0: a server still running the previous payload must not render
      // "undefined" on the dashboard while it waits for a restart.
      { label: "Query raised", value: s.new_queries ?? 0,
        sub: "New queries from students",
        tone: s.new_queries ? "warn" : "", href: "/trainer/queries", icon: "❓" },
    ];

    const host = document.getElementById("stats");
    host.textContent = "";
    cards.forEach((c) =>
      host.append(
        el("a", { class: `stat ${c.tone || ""}`, href: c.href },
          el("span", { class: "label", text: c.label }),
          el("strong", { class: "value", text: String(c.value) }),
          el("span", { class: "sub", text: c.sub })
        )
      )
    );
  }

  // ── upcoming deadlines ────────────────────────────────────────────────────

  function renderDeadlines() {
    const items = data.deadlines || [];
    D.fill(
      document.getElementById("deadline-list"),
      items.map((d) =>
        el("div", { class: "row" },
          el("div", {},
            el("div", { class: "title" }, d.title),
            el("div", { class: "meta" },
              d.overdue ? D.pill("Overdue", "red") : null,
              el("span", { class: d.overdue ? "tests fail" : "tests" }, D.due(d.due_date)),
              el("span", {}, `${d.outstanding} of ${d.assigned} still to come in`)
            )
          ),
          el("div", { class: "actions" },
            el("a", { class: "cb-btn", href: `/trainer/exercises/${d.id}` }, "Open")
          )
        )
      ),
      "No upcoming deadlines."
    );
  }

  // Reopen requests no longer render here: the Query raised card links to
  // /trainer/queries, where the new ones wait and the answered ones live
  // behind the History button.

  async function load() {
    try {
      data = await D.api("/api/dashboard/trainer");
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
