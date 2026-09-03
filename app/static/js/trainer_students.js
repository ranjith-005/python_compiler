// The trainer's student roster, as the table in the reference design: who,
// their email, how far through their assigned work they are, and whether they
// are online right now.
//
// Every cell is built with el() from dashboard_common.js — never innerHTML —
// because a name here is student-authored (`display`, never a raw email) and
// reaches the trainer's browser as data.
(function () {
  const D = window.Dash;
  const { api, el, empty } = D;
  const body = document.getElementById("student-rows");
  const emptyHost = document.getElementById("student-empty");
  const count = document.getElementById("student-count");
  const search = document.getElementById("student-search");
  let students = [];

  function initials(display) {
    const parts = String(display || "?").trim().split(/\s+/);
    return ((parts[0][0] || "?") + (parts.length > 1 ? parts[parts.length - 1][0] : ""))
      .toUpperCase();
  }

  function row(s) {
    const href = `/trainer/students/${s.id}`;
    const bar = el("div", { class: "bar" }, el("span", {}));
    // Width is set on the node rather than passed as an attribute so the
    // percentage never travels through markup.
    bar.firstChild.style.width = `${s.progress}%`;
    if (s.progress === 100) bar.classList.add("done");

    return el(
      "tr",
      { onclick: () => (window.location.href = href) },
      el(
        "td",
        {},
        el(
          "div",
          { class: "who" },
          el("span", { class: "avatar" }, initials(s.display)),
          // A real link, so the roster is navigable by keyboard too.
          el("a", { class: "name", href }, s.display)
        )
      ),
      el("td", { class: "email" }, s.email),
      el("td", {}, bar),
      el(
        "td",
        {},
        el("span", { class: `presence ${s.online ? "online" : ""}` }, s.online ? "Online" : "Offline")
      )
    );
  }

  function render() {
    const term = search.value.trim().toLowerCase();
    const visible = students.filter(
      (s) => !term || `${s.display} ${s.email}`.toLowerCase().includes(term)
    );
    count.textContent = students.length;
    body.textContent = "";
    emptyHost.textContent = "";
    if (!visible.length) {
      emptyHost.append(
        empty(students.length ? "No students match your search." : "No students enrolled yet.")
      );
      return;
    }
    visible.forEach((s) => body.append(row(s)));
  }

  async function load() {
    const data = await api("/api/dashboard/trainer");
    students = data.students || [];
    render();
  }

  search.addEventListener("input", render);
  load().catch(() => {
    body.textContent = "";
    emptyHost.textContent = "";
    emptyHost.append(empty("Unable to load students."));
  });
})();
