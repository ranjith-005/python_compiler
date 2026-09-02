// The trainer's student roster. Every row is built with el() from
// dashboard_common.js — never innerHTML — because a name here is
// student-authored (`display`, never a raw email) and reaches the trainer's
// browser as data.
(function () {
  const D = window.Dash;
  const { api, el, fill, pill } = D;
  const list = document.getElementById("student-list");
  const count = document.getElementById("student-count");
  const search = document.getElementById("student-search");
  let students = [];

  function row(s) {
    return el(
      "a",
      { class: "row student-row clickable", href: `/trainer/students/${s.id}` },
      el(
        "div",
        { class: "who" },
        el("span", { class: "avatar" }, s.display.slice(0, 2).toUpperCase()),
        el(
          "div",
          {},
          el("div", { class: "title" }, s.display),
          el(
            "div",
            { class: "meta" },
            el("span", {}, `${s.assigned} assigned`),
            el("span", { class: "dot-sep" }, `${s.completed} completed`),
            s.awaiting ? pill(`${s.awaiting} awaiting review`, "amber") : null
          )
        )
      ),
      el("span", { class: "chev" }, "›")
    );
  }

  function render() {
    const term = search.value.trim().toLowerCase();
    const visible = students.filter(
      (s) => !term || `${s.display} ${s.email}`.toLowerCase().includes(term)
    );
    count.textContent = students.length;
    fill(list, visible.map(row), "No students match your search.");
  }

  async function load() {
    const data = await api("/api/dashboard/trainer");
    students = data.students || [];
    render();
  }

  search.addEventListener("input", render);
  load().catch(() => fill(list, [], "Unable to load students."));
})();
