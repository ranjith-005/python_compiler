// Trainer dashboard (SRS §2): five linked overview cards. Everything the
// cards used to show inline now lives on its own page (students, pending,
// queue, exercises, completed).
(function () {
  const D = window.Dash;
  const { el } = D;

  let data = null;

  // ── overview cards ────────────────────────────────────────────────────────

  function renderStats() {
    const s = data.stats;
    const cards = [
      { label: "Students", value: s.students, sub: "On your roster",
        href: "/trainer/students" },
      { label: "Pending submissions", value: s.pending,
        sub: s.overdue ? `${s.overdue} past due` : "Assigned, not yet in",
        tone: s.overdue ? "bad" : "", href: "/trainer/pending" },
      { label: "Awaiting review", value: s.awaiting_review,
        sub: "Submitted, needs your verdict",
        tone: s.awaiting_review ? "warn" : "", href: "/trainer/queue" },
      { label: "Exercises", value: s.exercises,
        sub: `${s.published} published · ${s.drafts} draft`,
        href: "/trainer/exercises" },
      { label: "Completed", value: s.completed, sub: "Finished by your students",
        tone: "good", href: "/trainer/completed" },
    ];

    const host = document.getElementById("stats");
    host.textContent = "";
    cards.forEach((c) =>
      host.append(
        el("a", { class: `stat ${c.tone || ""}`, href: c.href },
          el("span", { class: "accent" }),
          el("span", { class: "label", text: c.label }),
          el("strong", { class: "value", text: String(c.value) }),
          el("span", { class: "sub", text: c.sub })
        )
      )
    );
  }

  async function load() {
    try {
      data = await D.api("/api/dashboard/trainer");
    } catch (err) {
      if (err.message !== "unauthenticated") D.toast(err.message, true);
      return;
    }
    renderStats();
    D.renderNotifications(data.notifications, data.unread);
  }

  D.initChrome(load);
  load();
})();
