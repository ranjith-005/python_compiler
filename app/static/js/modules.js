// Learning modules: the trainer's upload/review pages and the student player.
// Templates set window.PAGE = { kind, ... }; this dispatches on it.
(function () {
  const D = window.Dash;
  const { api, el, fill, pill, flash } = D;
  const PAGE = window.PAGE || {};
  const $ = (id) => document.getElementById(id);

  // ── a deliberately small markdown subset ─────────────────────────────────
  // Module text is written by the trainer, but it still goes through the DOM
  // as text, never as HTML, so a stray < in a lesson cannot become markup.
  function markdown(source) {
    const host = el("div", { class: "lesson" });
    let list = null;

    for (const raw of source.split("\n")) {
      const line = raw.trimEnd();
      const heading = /^(#{1,4})\s+(.*)$/.exec(line);
      const bullet = /^[-*]\s+(.*)$/.exec(line);

      if (!bullet && list) {
        host.append(list);
        list = null;
      }
      if (heading) {
        host.append(el(`h${Math.min(heading[1].length + 1, 5)}`, {}, inline(heading[2])));
      } else if (bullet) {
        list = list || el("ul", {});
        list.append(el("li", {}, inline(bullet[1])));
      } else if (line.trim()) {
        host.append(el("p", {}, inline(line)));
      }
    }
    if (list) host.append(list);
    return host;
  }

  // `code` spans, everything else literal text.
  function inline(text) {
    const frag = document.createDocumentFragment();
    text.split(/(`[^`]+`)/).forEach((part) => {
      if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
        frag.append(el("code", {}, part.slice(1, -1)));
      } else if (part) {
        frag.append(document.createTextNode(part));
      }
    });
    return frag;
  }

  function wireSearch(inputId, items, host, emptyMessage, countId) {
    const input = $(inputId);
    function apply() {
      const q = (input.value || "").trim().toLowerCase();
      const shown = q ? items.filter((i) => i.text.toLowerCase().includes(q)) : items;
      if (countId) $(countId).textContent = shown.length;
      fill(host, shown.map((i) => i.node), q ? "Nothing matches that search." : emptyMessage);
    }
    input.addEventListener("input", apply);
    apply();
  }

  function progressBar(percent) {
    return el(
      "div",
      { class: `bar ${percent === 100 ? "done" : ""}` },
      el("span", { style: `width:${percent}%` })
    );
  }

  // ── trainer: upload and list (reqs 14, 15) ───────────────────────────────

  async function trainerModules() {
    async function refresh() {
      const list = await api("/api/modules");
      const items = list.map((m) => ({
        text: `${m.title} ${m.description || ""}`,
        node: el(
          "div",
          {
            class: "row clickable",
            onclick: () => {
              window.location.href = `/trainer/modules/${m.id}`;
            },
          },
          el(
            "div",
            {},
            el("div", { class: "title" }, m.title),
            el(
              "div",
              { class: "meta" },
              el("span", {}, m.description || "No description"),
              el("span", {}, `${m.code_blocks} practice sections`),
              el("span", {}, `${m.assigned} assigned`)
            )
          ),
          el("span", { class: "chev" }, "›")
        ),
      }));
      wireSearch("m-search", items, $("m-list"), "No modules yet — upload one above.", "m-count");
    }

    $("m-upload").addEventListener("click", async () => {
      const file = $("m-file").files[0];
      if (!file) return flash("Choose a .ipynb file first", "error");
      const form = new FormData();
      form.append("file", file);
      form.append("title", $("m-title").value.trim());
      form.append("description", $("m-desc").value.trim());
      try {
        const res = await api("/api/modules", { method: "POST", body: form });
        flash(`Uploaded "${res.title}" — ${res.code_blocks} practice sections`, "success");
        $("m-title").value = $("m-desc").value = "";
        $("m-file").value = "";
        refresh();
      } catch (err) {
        flash(err.message, "error");
      }
    });

    await refresh();
  }

  // ── trainer: one module's contents and who is where (req 17) ─────────────

  async function moduleReview() {
    const m = await api(`/api/modules/${PAGE.moduleId}`);
    $("m-title").textContent = m.title;
    $("m-sub").textContent = `${m.description || "No description"} · ${m.code_blocks} practice sections`;

    $("s-count").textContent = m.students.length;
    fill(
      $("s-list"),
      m.students.map((s) =>
        el(
          "div",
          {
            class: "row clickable",
            onclick: () => {
              window.location.href = `/trainer/students/${s.id}`;
            },
          },
          el(
            "div",
            {},
            el("div", { class: "title" }, s.display),
            el(
              "div",
              { class: "meta" },
              el("span", {}, `${s.completed_blocks}/${m.code_blocks} sections run`),
              pill(`${s.progress}%`, s.progress === 100 ? "green" : "grey")
            )
          ),
          progressBar(s.progress)
        )
      ),
      "Not assigned to anyone yet."
    );

    $("b-count").textContent = m.blocks.length;
    fill(
      $("b-list"),
      m.blocks.map((b, i) =>
        el(
          "div",
          { class: "row" },
          el(
            "div",
            {},
            el("div", { class: "title" }, `${i + 1}. ${b.kind === "code" ? "Practice" : "Lesson"}`),
            el("div", { class: "meta" }, el("span", {}, b.source.slice(0, 90)))
          ),
          pill(b.kind, b.kind === "code" ? "blue" : "grey")
        )
      ),
      "This module is empty."
    );

    $("assign-btn").addEventListener("click", async () => {
      const students = await api("/api/students");
      const picked = prompt(
        `Assign "${m.title}" to which students?\n\n` +
          students.map((s) => `${s.id}: ${s.display}`).join("\n") +
          "\n\nEnter ids separated by commas, or 'all'.",
        "all"
      );
      if (picked === null) return;
      const ids =
        picked.trim().toLowerCase() === "all"
          ? students.map((s) => s.id)
          : picked.split(",").map((n) => parseInt(n.trim(), 10)).filter((n) => !isNaN(n));
      if (!ids.length) return flash("No students chosen", "error");
      try {
        const res = await api(`/api/modules/${m.id}/assign`, {
          method: "POST",
          body: JSON.stringify({ assign_to: ids }),
        });
        flash(`Assigned to ${res.assigned} student(s)`, "success");
        setTimeout(() => window.location.reload(), 900);
      } catch (err) {
        flash(err.message, "error");
      }
    });
  }

  // ── student: the list of what they have been given ───────────────────────

  async function studentModules() {
    const list = await api("/api/modules");
    const items = list.map((m) => ({
      text: `${m.title} ${m.description || ""}`,
      node: el(
        "div",
        {
          class: "row clickable",
          onclick: () => {
            window.location.href = `/student/modules/${m.id}`;
          },
        },
        el(
          "div",
          {},
          el("div", { class: "title" }, m.title),
          el(
            "div",
            { class: "meta" },
            el("span", {}, m.description || "No description"),
            el("span", {}, `${m.completed_blocks}/${m.code_blocks} sections done`),
            pill(`${m.progress}%`, m.progress === 100 ? "green" : "grey")
          )
        ),
        progressBar(m.progress)
      ),
    }));
    wireSearch("m-search", items, $("m-list"), "No modules assigned yet.", "m-count");
  }

  // ── student: the player (req 14, student reqs 1 and 2) ───────────────────

  async function modulePlayer() {
    const m = await api(`/api/modules/${PAGE.moduleId}`);
    $("m-title").textContent = m.title;
    $("m-sub").textContent = m.description || "";

    function setProgress(percent, done) {
      $("p-bar").style.width = `${percent}%`;
      $("p-label").textContent = `${percent}%`;
      $("p-help").textContent =
        percent === 100
          ? "Every practice section in this module runs. Nicely done."
          : `${done} of ${m.code_blocks} practice sections run without an error.`;
    }
    setProgress(m.progress, m.completed_blocks);

    const host = $("blocks");
    host.textContent = "";
    let practiceNumber = 0;

    m.blocks.forEach((b) => {
      if (b.kind === "content") {
        host.append(el("section", { class: "panel lesson-panel" }, el("div", { class: "panel-body" }, markdown(b.source))));
        return;
      }

      practiceNumber += 1;
      const editor = el("textarea", { class: "code-editor", spellcheck: "false" });
      editor.value = b.last_code || b.source;
      // Tab should indent, not leave the editor.
      editor.addEventListener("keydown", (e) => {
        if (e.key !== "Tab") return;
        e.preventDefault();
        const { selectionStart: a, selectionEnd: z, value } = editor;
        editor.value = value.slice(0, a) + "    " + value.slice(z);
        editor.selectionStart = editor.selectionEnd = a + 4;
      });

      const output = el("pre", { class: "code-output", hidden: true });
      const doneTick = el("span", { class: "tick" }, b.ran_ok ? "✓ run" : "");
      const runBtn = el("button", { class: "cb-btn primary" }, "▶ Run");

      runBtn.addEventListener("click", async () => {
        runBtn.disabled = true;
        runBtn.textContent = "Running…";
        try {
          const res = await api(`/api/modules/${m.id}/blocks/${b.id}/run`, {
            method: "POST",
            body: JSON.stringify({ code: editor.value }),
          });
          output.hidden = false;
          output.className = `code-output ${res.ok ? "" : "err"}`;
          output.textContent = (res.stdout || "") + (res.stderr || "") || "(no output)";
          if (res.ok) doneTick.textContent = "✓ run";
          setProgress(res.progress, res.completed_blocks);
        } catch (err) {
          output.hidden = false;
          output.className = "code-output err";
          output.textContent = err.message;
        } finally {
          runBtn.disabled = false;
          runBtn.textContent = "▶ Run";
        }
      });

      host.append(
        el(
          "section",
          { class: "panel practice-panel" },
          el(
            "header",
            {},
            el("h2", {}, `Practice ${practiceNumber}`),
            el("span", { class: "spacer" }),
            doneTick
          ),
          el(
            "div",
            { class: "panel-body" },
            editor,
            el("div", { class: "row-actions practice-actions" }, runBtn),
            output
          )
        )
      );
    });

    if (!m.blocks.length) {
      host.append(el("p", { class: "empty-note" }, "This module has no content yet."));
    }
  }

  const ROUTES = {
    trainer_modules: trainerModules,
    module_review: moduleReview,
    student_modules: studentModules,
    module_player: modulePlayer,
  };

  const run = ROUTES[PAGE.kind];
  if (run) run().catch((err) => flash(err.message || "Unable to load this page", "error"));
})();
