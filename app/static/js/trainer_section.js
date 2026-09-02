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

  // Restored date-range filters (req 3): only these two sections ever had
  // them, so only these two get the controls back. Filtering is client side
  // over `due_date`, which the dashboard endpoint already returns.
  const fromInput = document.getElementById("filter-from");
  const toInput = document.getElementById("filter-to");

  function dueInRange(dueDate) {
    if (!dueDate) return true; // no due date is never filtered out
    const from = fromInput ? fromInput.value : "";
    const to = toInput ? toInput.value : "";
    const day = dueDate.slice(0, 10);
    if (from && day < from) return false;
    if (to && day > to) return false;
    return true;
  }

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
      const rows = (data.exercises || []).filter((x) => dueInRange(x.due_date));
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
      const rows = (data.pending || []).filter((x) => dueInRange(x.due_date));
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
      const rows = data.completed || [];
      if (!rows.length) return empty("No completed work yet.");
      rows.forEach((x) =>
        list.append(
          row(
            x.exercise,
            [x.display,
             x.tests_total ? `${x.tests_passed}/${x.tests_total} tests` : null,
             when(x.submitted_at)],
            x.student_id ? `/trainer/students/${x.student_id}` : null
          )
        )
      );
    },
  };

  let data = null;
  function render() {
    if (!data) return;
    list.textContent = "";
    (RENDER[section] || RENDER.exercises)(data);
  }

  D.api("/api/dashboard/trainer")
    .then((loaded) => {
      data = loaded;
      render();
    })
    .catch((err) => {
      list.textContent = "";
      empty(err.message || "Unable to load this page.");
    });

  if (fromInput && toInput) {
    fromInput.addEventListener("input", render);
    toInput.addEventListener("input", render);
  }
})();
