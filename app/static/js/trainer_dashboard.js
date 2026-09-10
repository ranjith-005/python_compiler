// Trainer dashboard (SRS §2): five linked overview cards, the activity feed
// ten at a time, and the placeholder for online sessions. Everything the
// cards used to show inline lives on its own page (students, pending, queue,
// exercises, completed).
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
      { label: "Exercises", value: s.exercises,
        sub: `${s.published} published · ${s.drafts} draft`,
        href: "/trainer/exercises", icon: "📚" },
      { label: "Completed", value: s.completed, sub: "Finished by your students",
        tone: "good", href: "/trainer/completed", icon: "🏁" },
    ];

    const host = document.getElementById("stats");
    host.textContent = "";
    cards.forEach((c) =>
      host.append(
        el("a", { class: `stat ${c.tone || ""}`, href: c.href },
          el("span", { class: "stat-icon" }, c.icon),
          el("strong", { class: "value", text: String(c.value) }),
          el("span", { class: "label", text: c.label }),
          el("span", { class: "sub", text: c.sub })
        )
      )
    );
  }

  // ── calendar ──────────────────────────────────────────────────────────────

  // Calendar replaces the deadline list (spec: deadlines are a glance here and
  // actionable on the Exercises page). The trainer's deadline rows carry an
  // EXERCISE id, so the link differs from the student's.
  let calMonth = new Date();

  function paintCalendar() {
    if (!data) return;
    D.renderCalendar("calendar", data.deadlines, calMonth,
                     (d) => `/trainer/exercises/${d.id}`);
  }

  // ── reopen requests ───────────────────────────────────────────────────────

  async function decide(request, action) {
    // The message is written for this student on this request, so two people
    // asking about the same exercise can be answered differently.
    const prompt_ = action === "approve"
      ? `Message to ${request.display} (optional):`
      : `Why are you declining ${request.display}? They will see this:`;
    const message = window.prompt(prompt_, "");
    if (message === null) return;
    try {
      await D.api(`/api/access-requests/${request.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ action, message }),
      });
      D.flash(action === "approve" ? "Exercise reopened" : "Request declined", "success");
      await load();
    } catch (err) {
      D.flash(err.message, "error");
    }
  }

  function renderRequests() {
    const items = data.access_requests || [];
    const panel = document.getElementById("requests-panel");
    panel.hidden = items.length === 0;
    if (!items.length) return;

    document.getElementById("request-count").textContent =
      items.filter((r) => r.status === "pending").length;

    D.fill(
      document.getElementById("request-list"),
      items.map((r) => {
        const row = el("div", { class: "row" },
          el("div", {},
            el("div", { class: "title" }, `${r.display} — ${r.exercise}`),
            el("div", { class: "meta" },
              r.status === "pending"
                ? D.pill("Waiting", "amber")
                : D.pill(r.status === "approved" ? "Reopened" : "Declined",
                         r.status === "approved" ? "green" : "red"),
              el("span", {}, D.ago(r.created_at))
            ),
            r.message ? el("div", { class: "request-quote" }, r.message) : null,
            r.decision_message
              ? el("div", { class: "request-quote answer" }, `You replied: ${r.decision_message}`)
              : null
          ),
          r.status === "pending"
            ? el("div", { class: "actions" },
                el("button", { class: "cb-btn", onclick: () => decide(r, "reject") }, "Decline"),
                el("button", { class: "cb-btn primary", onclick: () => decide(r, "approve") },
                   "Reopen")
              )
            : null
        );
        return row;
      }),
      "No reopen requests."
    );
  }

  async function load() {
    try {
      data = await D.api("/api/dashboard/trainer");
    } catch (err) {
      if (err.message !== "unauthenticated") D.flash(err.message, "error");
      return;
    }
    renderStats();
    paintCalendar();
    renderRequests();
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
