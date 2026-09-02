// One page for every trainer list: exercises, review queue, pending work and
// completed work. Which one is decided by window.SECTION.
//
// Rows are built with el(), never by assembling raw HTML strings: these
// render trainer-authored titles and student-authored names, both of which
// reach a trainer's browser.
(function () {
  const D = window.Dash;
  const { el, when, due } = D;
  const list = document.getElementById("section-list");
  const section = window.SECTION;

  function row(title, metaParts, href) {
    const body = el(
      "div",
      {},
      el("div", { class: "title", text: title }),
      el("div", { class: "meta", text: metaParts.filter(Boolean).join(" · ") })
    );
    return href
      ? el("a", { class: "row", href }, body)
      : el("div", { class: "row" }, body);
  }

  function empty(message) {
    list.append(el("p", { class: "empty-note", text: message }));
  }

  const RENDER = {
    exercises(data) {
      const rows = data.exercises || [];
      if (!rows.length) return empty("No exercises created yet.");
      rows.forEach((x) =>
        list.append(
          row(
            x.title,
            [x.status, `${x.assigned} assigned`, `${x.tests} test cases`,
             x.due_date ? `Due ${due(x.due_date)}` : null],
            `/trainer/exercises/${x.id}`
          )
        )
      );
    },
    queue(data) {
      const rows = data.review_queue || [];
      if (!rows.length) return empty("Nothing is awaiting review.");
      rows.forEach((x) =>
        list.append(
          row(
            x.exercise,
            [x.display, `${x.tests_passed}/${x.tests_total} tests`, when(x.submitted_at)],
            `/trainer/submissions/${x.id}`
          )
        )
      );
    },
    pending(data) {
      const rows = data.pending || [];
      if (!rows.length) return empty("No outstanding work — everything assigned has been submitted.");
      rows.forEach((x) =>
        list.append(
          row(
            x.exercise,
            [x.display, x.due_date ? `Due ${due(x.due_date)}` : "No due date",
             x.overdue ? "Overdue" : null],
            null
          )
        )
      );
    },
    completed(data) {
      const rows = (data.students || []).filter((s) => s.completed > 0);
      if (!rows.length) return empty("No completed work yet.");
      rows.forEach((s) =>
        list.append(
          row(s.display, [`${s.completed} of ${s.assigned} completed`], `/trainer/students/${s.id}`)
        )
      );
    },
  };

  D.api("/api/dashboard/trainer")
    .then((data) => {
      list.textContent = "";
      (RENDER[section] || RENDER.exercises)(data);
    })
    .catch((err) => {
      list.textContent = "";
      empty(err.message || "Unable to load this page.");
    });
})();
