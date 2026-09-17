// Shared dashboard plumbing: fetch wrapper, toasts, dates, notifications,
// and the small sheet/dialog behaviour both portals use.
window.Dash = (function () {
  const toastEl = document.getElementById("toast");
  let toastTimer = null;

  function toast(message, isError) {
    toastEl.textContent = message;
    toastEl.classList.toggle("err", !!isError);
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toastEl.hidden = true), 2800);
  }

  const flashEl = document.getElementById("flash");
  let flashTimer = null;

  // Requirement: confirmation appears in the centre after an action, and is not
  // a pop-up. Non-modal, does not trap focus, does not block interaction.
  function flash(message, kind) {
    // toast() dereferences toastEl with no null guard, so this fallback would
    // throw on a page with neither a #flash nor a #toast region. No such page
    // exists today; keep both regions in sync if that ever changes.
    if (!flashEl) return toast(message, kind === "error");
    // Role before content: the element must already be a live region when the
    // text changes, or a screen reader can miss the first announcement — and
    // several call sites flash once and then navigate away.
    const isError = kind === "error";
    flashEl.setAttribute("role", isError ? "alert" : "status");
    flashEl.setAttribute("aria-live", isError ? "assertive" : "polite");
    flashEl.className = `flash ${kind || "success"}`;
    flashEl.textContent = message;
    flashEl.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => (flashEl.hidden = true), 3200);
  }
  if (flashEl) flashEl.addEventListener("click", () => (flashEl.hidden = true));

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
      ...options,
    });
    if (res.status === 401) {
      window.location.href = "/login";
      throw new Error("unauthenticated");
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
    }
    return data;
  }

  // Stored timestamps are UTC ISO; older rows may lack the offset.
  function parse(iso) {
    if (!iso) return null;
    const d = new Date(/[Z+]|-\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
    return isNaN(d) ? null : d;
  }

  function when(iso) {
    const d = parse(iso);
    if (!d) return "—";
    return d.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function ago(iso) {
    const d = parse(iso);
    if (!d) return "";
    const seconds = Math.round((Date.now() - d.getTime()) / 1000);
    const future = seconds < 0;
    const units = [
      ["year", 31536000],
      ["month", 2592000],
      ["day", 86400],
      ["hour", 3600],
      ["minute", 60],
    ];
    const abs = Math.abs(seconds);
    if (abs < 45) return future ? "in a moment" : "just now";
    for (const [name, size] of units) {
      if (abs >= size) {
        const n = Math.round(abs / size);
        const label = `${n} ${name}${n === 1 ? "" : "s"}`;
        return future ? `in ${label}` : `${label} ago`;
      }
    }
    return future ? "soon" : "just now";
  }

  function due(iso) {
    const d = parse(iso);
    if (!d) return "No due date";
    return `Due ${when(iso)} (${ago(iso)})`;
  }

  // el("div", {class: "row", onclick: fn}, child, child…)
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "html") node.innerHTML = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function pill(text, tone) {
    return el("span", { class: `pill ${tone || "grey"}` }, text);
  }

  function empty(message) {
    return el("p", { class: "empty-note" }, message);
  }

  function fill(container, nodes, emptyMessage) {
    container.textContent = "";
    if (!nodes.length) {
      container.append(empty(emptyMessage));
      return;
    }
    nodes.forEach((n) => container.append(n));
  }

  // ── sheets ───────────────────────────────────────────────────────────────

  function openSheet(id) {
    document.getElementById(id).hidden = false;
  }
  function closeSheet(id) {
    document.getElementById(id).hidden = true;
  }

  document.addEventListener("click", (event) => {
    const closer = event.target.closest("[data-close]");
    if (closer) closeSheet(closer.dataset.close);
    // Clicking the backdrop (but not the card) dismisses.
    if (event.target.classList && event.target.classList.contains("sheet")) {
      event.target.hidden = true;
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll(".sheet:not([hidden])").forEach((s) => (s.hidden = true));
    const panel = document.getElementById("bell-panel");
    if (panel) panel.hidden = true;
  });

  // ── notifications (SRS §17) ──────────────────────────────────────────────

  const ICONS = {};
  const TONES = {
    assigned: "blue",
    submitted: "blue",
    approve: "green",
    approved: "green",
    complete: "green",
    completed: "green",
    request_changes: "amber",
    changes_requested: "amber",
    created: "blue",
    reviewed: "blue",
    query: "amber",
  };

  // The bell lists every unread notification, newest first. The panel scrolls
  // when there are many, so nothing new hides behind an "N more" line.
  function renderNotifications(items, unread) {
    const list = document.getElementById("bell-list");
    const badge = document.getElementById("bell-badge");
    const foot = document.getElementById("bell-foot");
    badge.hidden = !unread;
    badge.textContent = String(unread || 0);

    const unreadItems = (items || []).filter(n => !n.read_at);
    const shown = unreadItems;

    list.textContent = "";
    if (!shown.length) {
      list.append(el("li", {}, el("span", { class: "meta" }, "No notifications.")));
      if (foot) foot.hidden = true;
      return;
    }
    shown.forEach((n) => {
      const li = el(
        "li",
        { class: "unread" },
        el("span", {}, `${ICONS[n.kind] || "•"} ${n.title}`),
        el("time", {}, ago(n.created_at))
      );
      if (n.link) {
        li.style.cursor = "pointer";
        li.addEventListener("click", () => (window.location.href = n.link));
      }
      list.append(li);
    });
    if (foot) foot.hidden = true;
  }

  function renderActivity(items) {
    const list = document.getElementById("activity-list");
    list.textContent = "";
    if (!items.length) {
      list.append(el("li", {}, "", el("span", { class: "meta" }, "No activity yet.")));
      return;
    }
    items.forEach((a) => {
      list.append(
        el(
          "li",
          {},
          el("span", { class: `icon ${TONES[a.kind] || ""}` }, ICONS[a.kind] || "•"),
          el("div", {}, el("div", {}, a.summary), el("time", {}, when(a.created_at)))
        )
      );
    });
  }

  // ── recent activity, fifteen at a time (both dashboards) ─────────────────

  const ACTIVITY_PAGE = 15;

  // "Nishanth (trainer) assigned ..." rather than a line with no author.
  // Most summaries already open with the actor's name, so the role is slipped
  // in after it; the rest ("Solution approved: X") get the actor as a tag
  // beside the timestamp instead, which is the only place it fits.
  function attribute(activity) {
    const actor = activity.actor || "";
    const role = activity.actor_role || "";
    if (!actor || !role) return { line: activity.summary, tag: "" };
    const label = `${actor} (${role})`;
    if (activity.summary.startsWith(actor + " ")) {
      return { line: label + activity.summary.slice(actor.length), tag: "" };
    }
    return { line: activity.summary, tag: label };
  }

  // Renders one page of activity into `listId` and drives the Prev/Next pair
  // in `pagerId`. The first page arrives with the dashboard payload, so the
  // panel paints without a second round trip; Next fetches from there on.
  //
  // The category filter is applied by the server, not over the fifteen rows
  // already on screen: an exercise that happened twenty events ago is still an
  // exercise, and filtering client-side would both hide it and leave the pager
  // counting a total for a different set of rows.
  function activityPager(listId, pagerId, firstPage, total) {
    const list = document.getElementById(listId);
    const pager = document.getElementById(pagerId);
    const range = pager.querySelector(".range");
    const prev = pager.querySelector("[data-prev]");
    const next = pager.querySelector("[data-next]");
    const filterSel = document.getElementById("activity-filter");
    let offset = 0;
    let busy = false;

    function getFilter() {
      return filterSel ? filterSel.value : "all";
    }

    const EMPTY = {
      all: "No activity yet.",
      exercise: "No exercise activity yet.",
      module: "No module activity yet.",
      submission: "No submission activity yet.",
    };

    function paint(items) {
      list.textContent = "";
      if (!items.length) {
        const filter = getFilter();
        list.append(el("li", { class: "empty-note" }, EMPTY[filter] || EMPTY.all));
      }
      items.forEach((a) => {
        const { line, tag } = attribute(a);
        list.append(
          el(
            "li",
            {},
            el("span", { class: `dot ${TONES[a.kind] || ""}` }),
            el(
              "div",
              {},
              el("div", { class: "line" }, line),
              el(
                "div",
                { class: "sub" },
                tag ? el("span", { class: "actor-tag" }, tag) : null,
                el("time", {}, when(a.created_at))
              )
            )
          )
        );
      });
      // "3 / 20" -- which page of how many, so a long history reads as a
      // countable thing rather than an endless scroll.
      const pages = Math.max(1, Math.ceil(total / ACTIVITY_PAGE));
      const current = Math.floor(offset / ACTIVITY_PAGE) + 1;
      range.textContent = total ? `${current} / ${pages}` : "Nothing yet";
      prev.disabled = busy || offset === 0;
      next.disabled = busy || offset + ACTIVITY_PAGE >= total;
      pager.hidden = total <= ACTIVITY_PAGE;
    }

    async function go(nextOffset) {
      if (busy) return;
      busy = true;
      prev.disabled = next.disabled = true;
      try {
        const page = await api(
          `/api/dashboard/activity?limit=${ACTIVITY_PAGE}&offset=${nextOffset}` +
            `&category=${encodeURIComponent(getFilter())}`
        );
        offset = page.offset;
        total = page.total;
        busy = false;
        paint(page.items);
      } catch (err) {
        busy = false;
        paint([]);
        toast(err.message, true);
      }
    }

    // Changing the filter asks for a new first page: the whole history is
    // re-selected, not the fifteen rows that happen to be on screen.
    if (filterSel) {
      filterSel.addEventListener("change", () => go(0));
    }
    prev.addEventListener("click", () => go(Math.max(0, offset - ACTIVITY_PAGE)));
    next.addEventListener("click", () => go(offset + ACTIVITY_PAGE));
    paint(firstPage || []);
  }

  let chromeInitialized = false;
  function initChrome() {
    if (chromeInitialized) return;
    chromeInitialized = true;
    
    const bell = document.getElementById("bell-btn");
    if (!bell) return;
    const panel = document.getElementById("bell-panel");
    bell.addEventListener("click", (event) => {
      event.stopPropagation();
      panel.hidden = !panel.hidden;
    });
    document.addEventListener("click", (event) => {
      if (!panel.hidden && !event.target.closest(".bell-wrap")) panel.hidden = true;
    });
    document.getElementById("mark-read").addEventListener("click", async () => {
      try {
        await api("/api/dashboard/notifications/read", { method: "POST" });
        const data = await api("/api/dashboard/notifications");
        renderNotifications(data.notifications, data.unread);
      } catch (err) {
        toast(err.message, true);
      }
    });

    // Fetch initial notifications for the badge
    api("/api/dashboard/notifications").then(data => {
      if (data) renderNotifications(data.notifications, data.unread);
    }).catch(() => {});
  }

  // Assignment list filters (trainer student detail, exercise detail, student
  // exercises): one definition for every page.
  //
  // Work the student has not submitted falls into exactly two buckets, and the
  // due date is what decides which: still in hand is "assigned", past the due
  // date is "pending". Whether they have opened it does not change the bucket,
  // so "in_progress" is no longer a filter of its own -- it is part of
  // assigned, and "open" stays as an alias for the same thing.
  const ASSIGNMENT_STATUSES = ["assigned", "pending", "submitted", "completed"];
  const PRE_SUBMIT = ["assigned", "in_progress", "pending"];

  function assignmentOverdue(row) {
    // `status` is authoritative once the server has swept it to pending; the
    // due date is the fallback for a row read before that sweep ran.
    if (row.status === "pending" || row.overdue) return true;
    const d = parse(row.due_date);
    return Boolean(d && d.getTime() < Date.now());
  }

  // Which of the four buckets a row belongs to, for labels as well as filters.
  function assignmentBucket(row) {
    if (row.status === "completed" || row.status === "submitted") return row.status;
    return assignmentOverdue(row) ? "pending" : "assigned";
  }

  function assignmentMatchesFilter(row, filter) {
    if (!filter || filter === "all") return true;
    if (filter === "in_progress" || filter === "open") filter = "assigned";
    if (filter === "assigned" || filter === "pending") {
      return PRE_SUBMIT.includes(row.status) && assignmentBucket(row) === filter;
    }
    return row.status === filter;
  }

  // Wording for each bucket, shared by every list that shows a status pill.
  const ASSIGNMENT_LABELS = {
    assigned: ["Assigned", "grey"],
    pending: ["Pending · past due", "red"],
    submitted: ["Submitted", "amber"],
    completed: ["Completed", "green"],
  };

  return {
    api,
    toast,
    flash,
    when,
    ago,
    due,
    el,
    pill,
    fill,
    empty,
    openSheet,
    closeSheet,
    initChrome,
    renderNotifications,
    renderActivity,
    activityPager,
    ACTIVITY_PAGE,
    ICONS,
    TONES,
    ASSIGNMENT_STATUSES,
    assignmentMatchesFilter,
    assignmentBucket,
    assignmentOverdue,
    ASSIGNMENT_LABELS,
  };
})();
