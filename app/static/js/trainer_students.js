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


  // ── enrolling a student ───────────────────────────────────────────────────
  //
  // The password is generated on the server and the field is read-only: a
  // trainer inventing one by hand is how "Welcome123" ends up on four
  // accounts. Generating is also what makes the welcome email possible at
  // all -- the plaintext exists only here, between generating it and sending
  // it, because what is stored is a bcrypt hash.

  const sheet = "enrol-sheet";
  const form = document.getElementById("enrol-form");
  const passwordField = document.getElementById("enrol-password");
  const note = document.getElementById("enrol-note");
  const saveBtn = document.getElementById("enrol-save");

  function say(text, kind) {
    note.textContent = text;
    note.className = `field-note wide${kind ? " " + kind : ""}`;
    note.hidden = !text;
  }

  async function generate() {
    try {
      const { password } = await api("/api/students/new-password");
      passwordField.value = password;
      return password;
    } catch (err) {
      say(err.message || "Could not generate a password.", "bad");
      return "";
    }
  }

  document.getElementById("generate-btn").addEventListener("click", generate);

  document.getElementById("enrol-btn").addEventListener("click", async () => {
    form.reset();
    say("");
    D.openSheet(sheet);
    // One ready to use the moment the sheet opens: the trainer should never
    // meet an empty required field they are not allowed to type into.
    await generate();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form).entries());
    if (!values.password) {
      say("Press Generate to create a password first.", "bad");
      return;
    }

    saveBtn.disabled = true;
    say("Enrolling…");
    try {
      const created = await api("/api/students", {
        method: "POST",
        body: JSON.stringify({
          email: values.email.trim(),
          password: values.password,
          first_name: (values.first_name || "").trim(),
          last_name: (values.last_name || "").trim(),
          phone: (values.phone || "").trim(),
          course: (values.course || "").trim(),
          send_welcome: document.getElementById("send-welcome").checked,
        }),
      });

      const welcome = created.welcome;
      if (welcome && welcome.sent) {
        D.flash(`${created.display} enrolled, and the welcome was emailed.`, "ok");
      } else if (welcome) {
        // No mail server here. Rather than lose the message, hand the trainer
        // the same one already filled in, to send from their own client.
        D.flash(`${created.display} enrolled. Opening your mail app to send the details.`, "ok");
        window.location.href = welcome.mailto;
      } else {
        D.flash(`${created.display} enrolled.`, "ok");
      }

      D.closeSheet(sheet);
      await load();
    } catch (err) {
      say(err.message || "Could not enrol that student.", "bad");
    } finally {
      saveBtn.disabled = false;
    }
  });

  search.addEventListener("input", render);
  load().catch(() => {
    body.textContent = "";
    emptyHost.textContent = "";
    emptyHost.append(empty("Unable to load students."));
  });
})();
