// Trainer dashboard (SRS §2): five linked overview cards. Everything the
// cards used to show inline now lives on its own page (students, pending,
// queue, exercises, completed).
(function () {
  const D = window.Dash;
  const { el, pill, fill } = D;

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
          el("span", { class: "stat-label", text: c.label }),
          el("strong", { class: "stat-value", text: String(c.value) }),
          el("span", { class: "stat-sub", text: c.sub })
        )
      )
    );
  }

  // ── student progress (§16) ────────────────────────────────────────────────

  function renderStudents() {
    document.getElementById("student-count").textContent = data.students.length;
    fill(
      document.getElementById("student-list"),
      data.students.map((s) => {
        const name = s.display;
        return el(
          "div",
          { class: "row student-row" },
          el(
            "div",
            { class: "who" },
            el("span", { class: "avatar" }, name.slice(0, 2).toUpperCase()),
            el(
              "div",
              {},
              el("div", { class: "title" }, name),
              el(
                "div",
                { class: "meta" },
                el("span", {}, `${s.assigned} assigned`),
                el("span", { class: "dot-sep" }, `${s.completed} done`),
                s.awaiting ? pill(`${s.awaiting} to review`, "amber") : null,
                s.is_active ? null : pill("Inactive", "red")
              )
            )
          ),
          el("span", { class: "tests" }, `${s.progress}%`),
          el(
            "div",
            { class: `bar ${s.progress === 100 ? "done" : ""}` },
            el("span", { style: `width:${s.progress}%` })
          )
        );
      }),
      "No students registered yet."
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
