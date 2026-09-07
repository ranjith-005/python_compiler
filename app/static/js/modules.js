// Learning modules: the trainer's upload/review pages and the student player.
// Templates set window.PAGE = { kind, ... }; this dispatches on it.
(function () {
  const D = window.Dash;
  const { api, el, fill, pill, flash } = D;
  const PAGE = window.PAGE || {};
  const $ = (id) => document.getElementById(id);

  // ── a deliberately small markdown subset ─────────────────────────────────
  // Section content comes from an uploaded document, but it still goes through
  // the DOM as text, never as HTML, so a stray < in a slide cannot become
  // markup.
  function markdown(source) {
    const host = el("div", { class: "lesson" });
    let list = null;

    for (const raw of (source || "").split("\n")) {
      const line = raw.trimEnd();
      const heading = /^(#{1,4})\s+(.*)$/.exec(line);
      const bullet = /^\s*[-*]\s+(.*)$/.exec(line);

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

  // A textarea where Tab indents instead of leaving the field.
  function codeEditor(value) {
    const editor = el("textarea", { class: "code-editor", spellcheck: "false" });
    editor.value = value || "";
    editor.addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      e.preventDefault();
      const { selectionStart: a, selectionEnd: z, value: text } = editor;
      editor.value = text.slice(0, a) + "    " + text.slice(z);
      editor.selectionStart = editor.selectionEnd = a + 4;
    });
    return editor;
  }

  // ── trainer: upload and list (module reqs 1-4, 17) ───────────────────────

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
              el("span", {}, `${m.sections} sections`),
              el("span", {}, `${m.code_sections} with code practice`),
              el("span", {}, `${m.assigned} assigned`)
            )
          ),
          pill(m.status, m.status === "published" ? "green" : "grey"),
          el("span", { class: "chev" }, "›")
        ),
      }));
      wireSearch("m-search", items, $("m-list"), "No modules yet — upload one above.", "m-count");
    }

    const steps = $("m-steps");
    const result = $("m-result");
    const button = $("m-upload");

    // Module req 17: mark each stage as the worker reports reaching it.
    function showStep(step) {
      steps.hidden = false;
      const order = ["extract", "topics", "sections", "done"];
      const reached = order.indexOf(step);
      steps.querySelectorAll("li").forEach((li) => {
        const at = order.indexOf(li.dataset.step);
        li.classList.toggle("active", at === reached);
        li.classList.toggle("done", reached > at || step === "done");
      });
    }

    async function poll(jobId) {
      // The upload returns immediately; the document is read on a worker.
      for (;;) {
        const job = await api(`/api/modules/jobs/${jobId}`);
        showStep(job.step);
        if (job.state === "done") return job;
        if (job.state === "error") throw new Error(job.message);
        await new Promise((r) => setTimeout(r, 400));
      }
    }

    button.addEventListener("click", async () => {
      const file = $("m-file").files[0];
      if (!file) return flash("Choose a PDF, PPT or PPTX file first", "error");
      // Frontend validation; the backend checks the same thing (module req 3).
      if (!/\.(pdf|ppt|pptx)$/i.test(file.name)) {
        return flash("Unsupported file format. Please upload a PDF, PPT, or PPTX file.", "error");
      }

      const form = new FormData();
      form.append("file", file);
      form.append("title", $("m-title").value.trim());
      form.append("description", $("m-desc").value.trim());

      button.disabled = true;
      button.textContent = "Processing…";
      result.hidden = true;
      showStep("extract");
      try {
        const started = await api("/api/modules", { method: "POST", body: form });
        const job = await poll(started.job_id);
        result.hidden = false;
        result.className = "help process-result ok";
        result.textContent =
          `✓ ${job.units} pages/slides read · ${job.sections} sections created ` +
          `(${job.code_sections} with code practice). Your module draft is ready for review.`;
        $("m-title").value = $("m-desc").value = "";
        $("m-file").value = "";
        flash(`Draft "${job.title}" is ready for review`, "success");
        await refresh();
        setTimeout(() => {
          window.location.href = `/trainer/modules/${job.module_id}`;
        }, 1200);
      } catch (err) {
        steps.hidden = true;
        result.hidden = false;
        result.className = "help process-result err";
        result.textContent = err.message;
        flash(err.message, "error");
      } finally {
        button.disabled = false;
        button.textContent = "Upload module";
      }
    });

    await refresh();
  }

  // ── trainer: review and edit the draft (module reqs 12, 13) ──────────────

  async function moduleReview() {
    const id = PAGE.moduleId;
    let m = await api(`/api/modules/${id}`);

    function header() {
      $("m-title").textContent = m.title;
      $("m-sub").textContent =
        `${m.description || "No description"} · ${m.section_count} sections · ` +
        `${m.code_sections} with code practice` +
        (m.source_name ? ` · from ${m.source_name}` : "");
      const status = $("m-status");
      status.textContent = m.status;
      status.className = `pill ${m.status === "published" ? "green" : "grey"}`;
      $("e-title").value = m.title;
      $("e-desc").value = m.description || "";
      $("m-note").textContent =
        m.status === "published"
          ? `Students see the ${m.published_count} published sections. Edits below stay ` +
            `in the draft until you publish again.`
          : "This module is a draft. Students cannot see it until you publish it.";
      $("publish-btn").textContent = m.status === "published" ? "Publish changes" : "Publish";
    }

    async function reload() {
      m = await api(`/api/modules/${id}`);
      header();
      renderSections();
      renderStudents();
    }

    // One section's editing card. Every field writes back on blur, so the
    // trainer never has to hunt for a save button per field.
    function sectionCard(section, index) {
      const patch = async (body) => {
        try {
          await api(`/api/modules/${id}/sections/${section.id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          });
          Object.assign(section, body);
        } catch (err) {
          flash(err.message, "error");
        }
      };

      const title = el("input", { class: "section-title-input", value: section.title });
      title.addEventListener("change", () => patch({ title: title.value }));

      const content = el("textarea", { class: "section-content" });
      content.value = section.content || "";
      content.addEventListener("change", () => patch({ content: content.value }));

      const practiceBody = el("div", { class: "practice-fields" });
      const question = el("textarea", { class: "section-question", rows: "2" });
      question.value = section.code_question || "";
      question.addEventListener("change", () => patch({ code_question: question.value }));
      const starter = codeEditor(section.starter_code);
      starter.addEventListener("change", () => patch({ starter_code: starter.value }));
      practiceBody.append(
        el("label", { class: "sub-label" }, "Coding question"),
        question,
        el("label", { class: "sub-label" }, "Starter code"),
        starter
      );
      practiceBody.hidden = !section.has_code_practice;

      const toggle = el("input", { type: "checkbox", id: `code-${section.id}` });
      toggle.checked = !!section.has_code_practice;
      toggle.addEventListener("change", async () => {
        practiceBody.hidden = !toggle.checked;
        await patch({ has_code_practice: toggle.checked });
      });

      const act = (label, handler, cls) =>
        el("button", { class: `cb-btn ${cls || ""}`, onclick: handler }, label);

      const call = (path, body) => async () => {
        try {
          await api(`/api/modules/${id}/sections/${section.id}/${path}`, {
            method: "POST",
            body: JSON.stringify(body || {}),
          });
          await reload();
        } catch (err) {
          flash(err.message, "error");
        }
      };

      return el(
        "section",
        { class: "panel section-card" },
        el(
          "header",
          {},
          el("h2", {}, `Section ${index + 1}`),
          section.source_pages ? el("span", { class: "meta-tag" }, section.source_pages) : null,
          el("span", { class: "spacer" }),
          act("↑", call("move", { direction: "up" })),
          act("↓", call("move", { direction: "down" })),
          act("Merge next", call("merge")),
          act(
            "Split",
            () => {
              const lines = (content.value || "").split("\n").length;
              const at = prompt(
                `Split this section after which line? (1–${Math.max(lines - 1, 1)})`,
                "1"
              );
              if (at === null) return;
              const n = parseInt(at, 10);
              if (!n) return flash("Enter a line number", "error");
              call("split", { at_line: n, title: "" })();
            }
          ),
          act(
            "Delete",
            async () => {
              if (!confirm(`Delete section "${section.title}"? This cannot be undone.`)) return;
              try {
                await api(`/api/modules/${id}/sections/${section.id}`, { method: "DELETE" });
                await reload();
              } catch (err) {
                flash(err.message, "error");
              }
            },
            "danger"
          )
        ),
        el(
          "div",
          { class: "panel-body" },
          el("label", { class: "sub-label" }, "Section title"),
          title,
          el("label", { class: "sub-label" }, "Learning content"),
          content,
          el(
            "div",
            { class: "code-toggle" },
            toggle,
            el("label", { for: `code-${section.id}` }, "Code practice for this section")
          ),
          practiceBody
        )
      );
    }

    function renderSections() {
      $("b-count").textContent = m.section_count;
      fill(
        $("b-list"),
        m.sections.map(sectionCard),
        "This module has no sections yet — add one above."
      );
    }

    function renderStudents() {
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
                el("span", {}, `${s.completed_sections} of ${s.total_sections} sections completed`),
                pill(`${s.progress}%`, s.progress === 100 ? "green" : "grey")
              )
            ),
            progressBar(s.progress)
          )
        ),
        "Not assigned to anyone yet."
      );
    }

    header();
    renderSections();
    renderStudents();

    $("save-meta").addEventListener("click", async () => {
      try {
        await api(`/api/modules/${id}`, {
          method: "PATCH",
          body: JSON.stringify({
            title: $("e-title").value.trim(),
            description: $("e-desc").value.trim(),
          }),
        });
        flash("Details saved", "success");
        await reload();
      } catch (err) {
        flash(err.message, "error");
      }
    });

    $("add-section").addEventListener("click", async () => {
      try {
        await api(`/api/modules/${id}/sections`, {
          method: "POST",
          body: JSON.stringify({ title: "New section", content: "" }),
        });
        await reload();
      } catch (err) {
        flash(err.message, "error");
      }
    });

    $("publish-btn").addEventListener("click", async () => {
      try {
        const res = await api(`/api/modules/${id}/publish`, { method: "POST" });
        flash(`Published ${res.sections} sections to your students`, "success");
        await reload();
      } catch (err) {
        flash(err.message, "error");
      }
    });

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
        await reload();
      } catch (err) {
        flash(err.message, "error");
      }
    });
  }

  // ── student: the list of what they have been given (module req 17) ───────

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
            el("span", {}, `${m.completed_sections} of ${m.sections} sections completed`),
            m.completed
              ? pill("✓ Completed", "green")
              : pill(`${m.progress}%`, "grey")
          )
        ),
        progressBar(m.progress),
        el(
          "button",
          {
            class: "cb-btn",
            onclick: (e) => {
              e.stopPropagation();
              const target = m.next_section_id ? `#section-${m.next_section_id}` : "";
              window.location.href = `/student/modules/${m.id}${target}`;
            },
          },
          m.completed ? "Review" : "Continue learning"
        )
      ),
    }));
    wireSearch("m-search", items, $("m-list"), "No modules assigned yet.", "m-count");
  }

  // ── student: the player (module reqs 1-16, 20-28) ────────────────────────

  async function modulePlayer() {
    const m = await api(`/api/modules/${PAGE.moduleId}`);
    $("m-title").textContent = m.title;
    $("m-sub").textContent = m.description || "";

    // Progress is recomputed from the sections themselves, so it works for any
    // number of them and is never hard-coded (module reqs 12, 24).
    const total = m.section_count;
    let done = m.completed_sections;

    function setProgress() {
      const percent = total ? Math.round((100 * done) / total) : 0;
      $("p-bar").style.width = `${percent}%`;
      $("p-bar").parentElement.className = `bar ${percent === 100 ? "done" : ""}`;
      $("p-label").textContent = `${percent}%`;
      $("p-help").textContent =
        total && done === total
          ? `✓ Module completed — ${done} of ${total} sections completed`
          : `${done} of ${total} sections completed`;
      $("p-actions").hidden = !(total && done < total);
    }

    function firstIncomplete() {
      return m.sections.find((s) => !s.completed);
    }

    $("continue-btn").addEventListener("click", () => {
      const next = firstIncomplete();
      if (!next) return;
      const node = document.getElementById(`section-${next.id}`);
      if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    const host = $("sections");
    host.textContent = "";

    // Module req 25: render exactly the sections the trainer published, in
    // order. Nothing is added, removed or reordered here.
    m.sections.forEach((section, index) => {
      const card = el("section", {
        class: `panel section-panel ${section.completed ? "completed" : ""}`,
        id: `section-${section.id}`,
      });

      const tick = el("span", { class: "tick" }, section.completed ? "✓ Completed" : "");
      card.append(
        el(
          "header",
          {},
          el("h2", {}, `Section ${index + 1}`),
          el("span", { class: "section-name" }, section.title),
          el("span", { class: "spacer" }),
          tick
        )
      );

      const body = el("div", { class: "panel-body" });
      // Content is unconditional: a section without code practice still shows
      // everything the trainer wrote (module reqs 2, 4, 20).
      body.append(markdown(section.content));

      if (section.has_code_practice) {
        // Each section gets its own editor, its own Run button and its own
        // output pane, with no state shared between them (module reqs 5-7).
        const editor = codeEditor(section.starter_code);
        const output = el("pre", { class: "code-output", hidden: true });
        const runBtn = el("button", { class: "cb-btn primary" }, "▶ Run");

        runBtn.addEventListener("click", async () => {
          runBtn.disabled = true;
          runBtn.textContent = "Running…";
          try {
            const res = await api(
              `/api/modules/${m.id}/sections/${section.id}/run`,
              { method: "POST", body: JSON.stringify({ code: editor.value }) }
            );
            output.hidden = false;
            output.className = `code-output ${res.ok ? "" : "err"}`;
            output.textContent = (res.stdout || "") + (res.stderr || "") || "(no output)";
          } catch (err) {
            output.hidden = false;
            output.className = "code-output err";
            output.textContent = err.message;
          } finally {
            runBtn.disabled = false;
            runBtn.textContent = "▶ Run";
          }
        });

        const practice = el(
          "div",
          { class: "code-practice" },
          el(
            "div",
            { class: "practice-head" },
            el("h3", {}, "Code practice"),
            el("span", { class: "spacer" }),
            runBtn
          )
        );
        if (section.code_question) {
          practice.append(el("p", { class: "practice-question" }, section.code_question));
        }
        practice.append(editor, el("div", { class: "output-label" }, "Output:"), output);
        body.append(practice);
      }

      // Module req 13: only this button completes a section — never opening
      // it, and never running its code.
      const completeBtn = el("button", { class: "cb-btn" }, "");
      function paintComplete() {
        completeBtn.textContent = section.completed ? "✓ Completed" : "Mark as complete";
        completeBtn.className = `cb-btn ${section.completed ? "done" : "primary"}`;
        tick.textContent = section.completed ? "✓ Completed" : "";
        card.classList.toggle("completed", section.completed);
      }
      paintComplete();

      completeBtn.addEventListener("click", async () => {
        const next = !section.completed;
        completeBtn.disabled = true;
        try {
          const res = await api(
            `/api/modules/${m.id}/sections/${section.id}/complete`,
            { method: "POST", body: JSON.stringify({ completed: next }) }
          );
          section.completed = res.completed;
          done = res.completed_sections;
          paintComplete();
          setProgress();
          if (res.module_completed) flash("✓ Module completed — 100%", "success");
        } catch (err) {
          flash(err.message, "error");
        } finally {
          completeBtn.disabled = false;
        }
      });

      body.append(el("div", { class: "row-actions section-actions" }, completeBtn));
      card.append(body);
      host.append(card);
    });

    if (!m.sections.length) {
      host.append(el("p", { class: "empty-note" }, "This module has no sections yet."));
    }

    setProgress();

    // Arriving from "Continue learning" on the list page.
    if (window.location.hash) {
      const node = document.querySelector(window.location.hash);
      if (node) node.scrollIntoView({ block: "start" });
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
