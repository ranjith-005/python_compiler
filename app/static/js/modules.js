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
    let p = null;

    for (const raw of (source || "").split("\n")) {
      const line = raw.trimEnd();
      const heading = /^(#{1,4})\s+(.*)$/.exec(line);
      const bullet = /^\s*[-*]\s+(.*)$/.exec(line);

      if (!bullet && list) {
        host.append(list);
        list = null;
      }
      
      if (!line.trim() && p) {
        host.append(p);
        p = null;
      }

      if (heading) {
        if (p) { host.append(p); p = null; }
        host.append(el(`h${Math.min(heading[1].length + 1, 5)}`, {}, inline(heading[2])));
      } else if (bullet) {
        if (p) { host.append(p); p = null; }
        list = list || el("ul", {});
        list.append(el("li", {}, inline(bullet[1])));
      } else if (line.trim()) {
        if (!p) {
          p = el("p", {});
        } else {
          p.append(document.createTextNode(" "));
        }
        p.append(inline(line));
      }
    }
    if (list) host.append(list);
    if (p) host.append(p);
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
    const container = el("div", { class: "editor-container" });
    const gutter = el("div", { class: "editor-gutter" });
    const editor = el("textarea", { class: "code-editor", spellcheck: "false", wrap: "off" });
    editor.value = value || "";

    function updateLines() {
      const lines = editor.value.split('\n').length;
      let html = '';
      for (let i = 1; i <= lines; i++) {
        html += `<div>${i}</div>`;
      }
      gutter.innerHTML = html;
    }

    editor.addEventListener("input", updateLines);
    editor.addEventListener("scroll", () => { gutter.scrollTop = editor.scrollTop; });

    editor.addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      e.preventDefault();
      const { selectionStart: a, selectionEnd: z, value: text } = editor;
      editor.value = text.slice(0, a) + "    " + text.slice(z);
      editor.selectionStart = editor.selectionEnd = a + 4;
      updateLines();
    });

    container.append(gutter, editor);
    updateLines();

    Object.defineProperty(container, 'value', {
      get: () => editor.value,
      set: (v) => { editor.value = v; updateLines(); }
    });
    return container;
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
            style: "overflow: visible;",
            onclick: () => {
              window.location.href = `/trainer/modules/${m.id}?mode=view`;
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
          el(
            "div",
            { class: "row-actions", style: "display: flex; align-items: center; gap: 8px;" },
            pill(m.status, m.status === "published" ? "green" : "grey"),
            el(
              "button",
              {
                class: "cb-btn small",
                onclick: (e) => {
                  e.stopPropagation();
                  window.open(`/api/modules/${m.id}/source`, "_blank");
                },
              },
              "Original Material"
            ),
            el(
              "div",
              { style: "position: relative;" },
              el("button", {
                class: "cb-btn small",
                style: "padding: 0 10px; font-weight: bold; font-size: 1.2em; line-height: 1;",
                onclick: (e) => {
                  e.stopPropagation();
                  // Close any open menus
                  document.querySelectorAll(".three-dot-menu").forEach(m => m.remove());
                  // Build a fixed-position menu so it escapes overflow:hidden panels
                  const btn = e.currentTarget;
                  const rect = btn.getBoundingClientRect();
                  const menu = el(
                    "div",
                    {
                      class: "three-dot-menu",
                      style: `position: fixed; right: ${window.innerWidth - rect.right}px; top: ${rect.bottom + 4}px; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 6px; display: flex; flex-direction: column; z-index: 9999; min-width: 120px; box-shadow: var(--shadow-card);`,
                    },
                    el("button", { style: "padding: 9px 14px; text-align:left; background:transparent; border:none; cursor:pointer; font-size:13px; border-radius: 6px 6px 0 0;", onmouseover: (ev) => ev.target.style.background="var(--cell-bg,#f5f5f5)", onmouseout: (ev) => ev.target.style.background="transparent", onclick: (ev) => { ev.stopPropagation(); menu.remove(); window.location.href = `/trainer/modules/${m.id}?mode=edit`; } }, "Edit"),
                    el("button", { style: "padding: 9px 14px; text-align:left; background:transparent; border:none; cursor:pointer; font-size:13px;", onmouseover: (ev) => ev.target.style.background="var(--cell-bg,#f5f5f5)", onmouseout: (ev) => ev.target.style.background="transparent", onclick: (ev) => { ev.stopPropagation(); menu.remove(); window.location.href = `/trainer/modules/${m.id}?mode=update`; } }, "Update"),
                    el("button", { style: "padding: 9px 14px; text-align:left; background:transparent; border:none; cursor:pointer; font-size:13px; color: var(--red, #e53e3e); border-radius: 0 0 6px 6px;", onmouseover: (ev) => ev.target.style.background="var(--cell-bg,#f5f5f5)", onmouseout: (ev) => ev.target.style.background="transparent", onclick: async (ev) => { ev.stopPropagation(); menu.remove(); if (!confirm(`Delete "${m.title}"?`)) return; try { await api(`/api/modules/${m.id}`, { method: "DELETE" }); flash("Module deleted", "success"); refresh(); } catch (err) { flash(err.message, "error"); } } }, "Delete")
                  );
                  document.body.appendChild(menu);
                  // Auto-close on next outside click
                  setTimeout(() => {
                    document.addEventListener("click", () => menu.remove(), { once: true });
                  }, 0);
                },
              }, "⋮")
            )
          )
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
          window.location.href = `/trainer/modules/${job.module_id}?mode=view`;
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
    const urlParams = new URLSearchParams(window.location.search);
    let isEditMode = urlParams.get("mode") === "edit";
    let isUpdateMode = urlParams.get("mode") === "update";
    let m = await api(`/api/modules/${id}`);

    function updateMode() {
      document.querySelectorAll(".edit-only").forEach(el => el.hidden = !isEditMode);
      document.querySelectorAll(".update-only").forEach(el => el.hidden = !isUpdateMode);
      document.querySelectorAll(".hide-on-update").forEach(el => el.hidden = isUpdateMode);
      // active-mode-only: visible in both edit AND update mode, hidden in view mode.
      const isActionMode = isEditMode || isUpdateMode;
      document.querySelectorAll(".active-mode-only").forEach(el => el.hidden = !isActionMode);
      
      if (!isEditMode) {
        const valPanel = $("validation-panel");
        if (valPanel) valPanel.hidden = true;
      }
    }

    async function validateModule() {
      if (!isEditMode) return true;
      try {
        const res = await api(`/api/modules/${id}/validate`);
        const panel = $("validation-panel");
        const list = $("validation-list");
        if (res.valid) {
          panel.hidden = true;
        } else {
          panel.hidden = false;
          fill(list, res.errors.map(err => el("div", { class: "validation-error", style: "margin-bottom: 8px;" }, 
            el("strong", {}, err.section_title + ": "),
            el("span", {}, err.message + " "),
            el("button", { class: "cb-btn small", onclick: () => {
              const sec = document.getElementById(`section-${err.section_id}`);
              if (sec) {
                sec.scrollIntoView({ behavior: "smooth", block: "start" });
                sec.style.outline = "2px solid var(--red)";
                setTimeout(() => sec.style.outline = "", 2000);
              }
            }}, "Fix issue")
          )));
        }
        return res.valid;
      } catch (err) {
        console.error(err);
        return true;
      }
    }

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

      const content = el("div", { class: "section-content lesson-content", contentEditable: "true", style: "overflow-y: auto;" });
      content.innerHTML = section.content || "";
      content.addEventListener("blur", () => patch({ content: content.innerHTML }));

      const practiceBody = el("div", { class: "practice-fields" });
      const question = el("textarea", { class: "section-question", rows: "2" });
      question.value = section.code_question || "";
      question.addEventListener("change", () => patch({ code_question: question.value }));
      // Two code fields, and the difference matters (module req 23):
      // reference is the worked example the student reads and may run;
      // starter is what their editor opens with, normally left empty.
      const reference = codeEditor(section.reference_code);
      reference.addEventListener("change", () =>
        patch({ reference_code: reference.value })
      );
      const starter = codeEditor(section.starter_code);
      starter.addEventListener("change", () => patch({ starter_code: starter.value }));
      practiceBody.append(
        el("label", { class: "sub-label" }, "Coding question"),
        question,
        el("label", { class: "sub-label" }, "Reference example (read-only for students)"),
        reference,
        el("label", { class: "sub-label" }, "Starter code (leave empty so students write their own)"),
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
              const lines = (content.innerHTML || "").split("\n").length;
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
      if (isEditMode) {
        fill(
          $("b-list"),
          m.sections.map(sectionCard),
          "This module has no sections yet — add one above."
        );
        validateModule();
      } else {
        fill(
          $("b-list"),
          m.sections.map(previewCard),
          "This module has no sections yet."
        );
      }
    }

    function previewCard(section, index) {
      const card = el("section", {
        class: `section-panel`,
        id: `section-${section.id}`,
      });
      card.append(
        el(
          "header",
          {},
          el("h2", { class: "section-name" }, section.title)
        )
      );
      const body = el("div", { class: "panel-body" });
      const contentDiv = el("div", { class: "lesson-content" });
      contentDiv.innerHTML = section.content || "";
      body.append(contentDiv);
      if (section.reference_code) {
        const refCode = el("pre", { class: "reference-code" });
        refCode.innerHTML = (section.reference_code || "").split("\n").map(l => `<div class="line">${l || " "}</div>`).join("");
        body.append(
          el("div", { class: "reference-block" },
            el("div", { class: "practice-head" }, el("h3", {}, "Example")),
            refCode
          )
        );
      }
      if (section.has_code_practice) {
        const practice = el("div", { class: "code-practice" },
          el("div", { class: "practice-head" }, el("h3", {}, "Code practice"))
        );
        if (section.code_question) {
          practice.append(el("p", { class: "practice-question" }, section.code_question));
        }
        const pre = el("pre", { class: "code-editor" });
        pre.innerHTML = (section.starter_code || "(student editor area)").split("\n").map(l => `<div class="line">${l || " "}</div>`).join("");
        practice.append(pre);
        body.append(practice);
      }
      card.append(body);
      return card;
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
              { style: "flex: 1;" },
              el("div", { class: "title" }, s.display),
              el(
                "div",
                { class: "meta" },
                el("span", {}, `${s.completed_sections} of ${s.total_sections} sections completed`)
              )
            ),
            el(
              "div",
              { style: "display: flex; align-items: center; gap: 10px; width: 180px;" },
              el("div", { style: "flex: 1; margin: 0;" }, progressBar(s.progress)),
              el("span", { style: "font-weight: 600; min-width: 40px; text-align: right; font-size: 14px;" }, `${s.progress}%`)
            )
          )
        ),
        "Not assigned to anyone yet."
      );
    }

    updateMode();
    header();
    renderSections();
    renderStudents();

    $("re-upload-btn").addEventListener("click", async () => {
      const file = $("re-file").files[0];
      if (!file) return flash("Choose a PDF, PPT or PPTX file first", "error");
      
      const form = new FormData();
      form.append("file", file);
      
      const btn = $("re-upload-btn");
      const resMsg = $("re-result");
      btn.disabled = true;
      btn.textContent = "Uploading...";
      resMsg.hidden = true;
      
      try {
        const started = await api(`/api/modules/${id}/reupload`, { method: "POST", body: form });
        
        async function poll(jobId) {
          for (;;) {
            const job = await api(`/api/modules/jobs/${jobId}`);
            if (job.state === "done") return job;
            if (job.state === "error") throw new Error(job.message);
            await new Promise((r) => setTimeout(r, 400));
          }
        }
        
        await poll(started.job_id);
        resMsg.hidden = false;
        resMsg.className = "help process-result ok";
        resMsg.textContent = "Re-upload complete. Draft sections have been replaced.";
        flash("Re-upload successful", "success");
        await reload();
      } catch (err) {
        resMsg.hidden = false;
        resMsg.className = "help process-result err";
        resMsg.textContent = err.message;
      } finally {
        btn.disabled = false;
        btn.textContent = "Upload and replace";
        $("re-file").value = "";
      }
    });

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
      if (isEditMode) {
        const isValid = await validateModule();
        if (!isValid) {
          if (!confirm("This module has validation issues. Are you sure you want to publish it anyway?")) {
            return;
          }
        }
      }
      try {
        const res = await api(`/api/modules/${id}/publish`, { method: "POST" });
        
        // Auto-assign to all students after publish
        const students = await api("/api/students");
        const ids = students.map(s => s.id);
        if (ids.length) {
          await api(`/api/modules/${id}/assign`, {
            method: "POST",
            body: JSON.stringify({ assign_to: ids }),
          });
        }
        
        flash(`Published and assigned to all students`, "success");
        await reload();
      } catch (err) {
        flash(err.message, "error");
      }
    });

    const progBtn = $("student-progress-btn");
    if (progBtn) {
      progBtn.addEventListener("click", () => {
        const panel = $("student-progress-panel");
        panel.hidden = !panel.hidden;
      });
    }
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
            m.completed ? pill("✓ Completed", "green") : ""
          )
        ),
        el(
          "div",
          { style: "display: flex; align-items: center; gap: 12px; width: auto; max-width: 300px; flex-shrink: 0;" },
          el("div", { style: "flex: 1; min-width: 100px;" }, progressBar(m.progress)),
          el(
            "button",
            {
              class: "cb-btn small",
              style: "white-space: nowrap;",
              onclick: (e) => {
                e.stopPropagation();
                const target = m.next_section_id ? `#section-${m.next_section_id}` : "";
                window.location.href = `/student/modules/${m.id}${target}`;
              },
            },
            m.completed ? "Review" : (m.progress > 0 ? "Continue learning" : "Start learning")
          )
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
        class: `section-panel ${section.completed ? "completed" : ""}`,
        id: `section-${section.id}`,
      });

      const tick = el("span", { class: "tick" }, section.completed ? "✓ Completed" : "");
      card.append(
        el(
          "header",
          {},
          el("h2", { class: "section-name" }, section.title),
          el("span", { class: "spacer" }),
          tick
        )
      );

      const body = el("div", { class: "panel-body" });
      // Content is unconditional: a section without code practice still shows
      // everything the trainer wrote (module reqs 2, 4, 20).
      const contentDiv = el("div", { class: "lesson-content" });
      contentDiv.innerHTML = section.content || "";
      body.append(contentDiv);

      // The worked example from the upload, read-only (module req 23). It has
      // its own Run button so the student can see what it does before writing
      // anything, but it is never the editor they type in. Runs go through the
      // same endpoint as practice, so nothing new executes on the server.
      if (section.reference_code) {
        const refOut = el("pre", { class: "code-output", hidden: true });
        const refRun = el("button", { class: "cb-btn" }, "▶ Run");
        const refCode = el("pre", { class: "reference-code" });
        refCode.innerHTML = (section.reference_code || "").split("\n").map(l => `<div class="line">${l || " "}</div>`).join("");

        refRun.addEventListener("click", async () => {
          refRun.disabled = true;
          refRun.textContent = "Running…";
          try {
            const res = await api(
              `/api/modules/${m.id}/sections/${section.id}/run`,
              // The server runs the stored reference; kind says which code.
              { method: "POST", body: JSON.stringify({ kind: "reference" }) }
            );
            refOut.hidden = false;
            refOut.className = `code-output ${res.ok ? "" : "err"}`;
            refOut.textContent = (res.stdout || "") + (res.stderr || "") || "(no output)";
          } catch (err) {
            refOut.hidden = false;
            refOut.className = "code-output err";
            refOut.textContent = err.message;
          } finally {
            refRun.disabled = false;
            refRun.textContent = "▶ Run";
          }
        });

        body.append(
          el(
            "div",
            { class: "reference-block" },
            el(
              "div",
              { class: "practice-head" },
              el("h3", {}, "Example"),
              el("span", { class: "hint" }, "read-only"),
              el("span", { class: "spacer" }),
              refRun
            ),
            refCode,
            el("div", { class: "output-label" }, "Output:"),
            refOut
          )
        );
      }

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
