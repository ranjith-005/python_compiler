// Trainer dashboard (SRS §2): overview counts, review queue, pending work,
// deadlines, student progress, plus exercise creation and submission review.
(function () {
  const D = window.Dash;
  const { el, pill, fill } = D;

  let data = null;

  const RESULT_TONES = {
    accepted: "green",
    wrong_answer: "red",
    runtime_error: "red",
    syntax_error: "red",
    pending: "grey",
  };
  const STATUS_LABELS = {
    assigned: ["Assigned", "grey"],
    in_progress: ["In progress", "blue"],
    changes_requested: ["Changes requested", "amber"],
    submitted: ["Submitted", "blue"],
    approved: ["Approved", "green"],
    completed: ["Completed", "green"],
  };

  function label(value) {
    return String(value || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  }

  // ── overview cards ────────────────────────────────────────────────────────

  function renderStats() {
    const s = data.stats;
    // Requirement 1: only the two cards a trainer acts on. The API still
    // reports students/exercises/completed; they are shown in their own pages.
    const cards = [
      {
        label: "Pending submissions",
        value: s.pending,
        sub: s.overdue ? `${s.overdue} past due` : "Assigned, not yet in",
        tone: s.overdue ? "bad" : "",
        jump: "pending-panel",
      },
      {
        label: "Awaiting review",
        value: s.awaiting_review,
        sub: "Submitted, needs your verdict",
        tone: s.awaiting_review ? "warn" : "",
        jump: "review-panel",
      },
    ];

    const host = document.getElementById("stats");
    host.textContent = "";
    cards.forEach((c) => {
      const card = el(
          "button",
          {
            class: `stat ${c.tone || ""}`,
            type: "button",
            "data-jump": c.jump || null,
          },
          el("span", { class: "accent" }),
          el("span", { class: "label" }, c.label),
          el("span", { class: "value" }, c.value),
          el("span", { class: "sub" }, c.sub)
        );
      host.append(card);
    });
  }

  // ── submissions awaiting review (§13) ─────────────────────────────────────

  function renderReview() {
    const list = document.getElementById("review-list");
    const items = data.review_queue;
    document.getElementById("review-count").textContent = data.review_queue.length;

    fill(
      list,
      items.map((r) => {
        const passed = r.tests_total && r.tests_passed === r.tests_total;
        return el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, r.exercise),
            el(
              "div",
              { class: "meta" },
              el("span", {}, r.display),
              pill(label(r.result), RESULT_TONES[r.result] || "grey"),
              el(
                "span",
                { class: `tests ${passed ? "pass" : "fail"}` },
                `${r.tests_passed}/${r.tests_total} tests`
              ),
              el("span", { class: "dot-sep" }, D.ago(r.submitted_at))
            )
          ),
          el(
            "div",
            { class: "actions" },
            el("a", { class: "cb-btn", href: `/trainer/submissions/${r.id}` }, "Review")
          )
        );
      }),
      "Nothing waiting — every submission has been reviewed."
    );
  }

  // ── pending submissions ───────────────────────────────────────────────────

  // Requirement 3: both panels filter on a date range, client side over data
  // the dashboard endpoint already returns.
  function inRange(iso, fromId, toId) {
    const from = document.getElementById(fromId).value;
    const to = document.getElementById(toId).value;
    if (!from && !to) return true;
    const day = (iso || "").slice(0, 10);
    if (!day) return false;
    if (from && day < from) return false;
    if (to && day > to) return false;
    return true;
  }

  function pendingInRange() {
    return data.pending.filter((p) => inRange(p.assigned_at, "pending-from", "pending-to"));
  }

  function exercisesInRange() {
    return data.exercises.filter((x) => inRange(x.updated_at, "exercise-from", "exercise-to"));
  }

  function renderPending() {
    const rows = pendingInRange();
    document.getElementById("pending-count").textContent = rows.length;
    fill(
      document.getElementById("pending-list"),
      rows.map((p) => {
        const [text, tone] = STATUS_LABELS[p.status] || [label(p.status), "grey"];
        return el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, p.exercise),
            el(
              "div",
              { class: "meta" },
              el("span", {}, p.display),
              pill(text, tone),
              el("span", { class: p.overdue ? "tests fail" : "" }, D.due(p.due_date))
            )
          ),
          el("div", { class: "actions" }, p.overdue ? pill("Overdue", "red") : null)
        );
      }),
      "No outstanding work — everything assigned has been submitted."
    );
  }

  // ── upcoming deadlines ────────────────────────────────────────────────────

  function renderDeadlines() {
    fill(
      document.getElementById("deadline-list"),
      data.deadlines.map((d) =>
        el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, d.title),
            el(
              "div",
              { class: "meta" },
              el("span", { class: d.overdue ? "tests fail" : "" }, D.due(d.due_date))
            )
          )
        )
      ),
      "No published exercise has a due date yet."
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

  // ── exercises (§5) ────────────────────────────────────────────────────────

  function renderExercises() {
    document.getElementById("exercise-count").textContent = exercisesInRange().length;
    fill(
      document.getElementById("exercise-list"),
      exercisesInRange().map((x) =>
        el(
          "div",
          {
            class: "row clickable",
            onclick: () => {
              window.location.href = `/trainer/exercises/${x.id}`;
            },
          },
          el(
            "div",
            {},
            el("div", { class: "title" }, x.title),
            el(
              "div",
              { class: "meta" },
              pill(label(x.status), x.status === "published" ? "green" : "grey"),
              el("span", {}, `${x.assigned} assigned`),
              el("span", { class: "dot-sep" }, `${x.tests} test cases`),
              el("span", { class: "dot-sep" }, D.due(x.due_date))
            )
          ),
          el(
            "div",
            { class: "actions" },
            el("span", { class: "tests" }, D.ago(x.updated_at)),
            el("span", { class: "chev" }, "›")
          )
        )
      ),
      "No exercises in this date range."
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
    renderReview();
    renderPending();
    renderDeadlines();
    renderExercises();
    D.renderNotifications(data.notifications, data.unread);
  }

  // Requirement 3: re-render when either date range changes.
  ["pending-from", "pending-to"].forEach((id) =>
    document.getElementById(id).addEventListener("change", renderPending)
  );
  ["exercise-from", "exercise-to"].forEach((id) =>
    document.getElementById(id).addEventListener("change", renderExercises)
  );

  D.initChrome(load);
  load();
})();
