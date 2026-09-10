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

  const ICONS = {
    assigned: "📌",
    submitted: "📤",
    approve: "✅",
    approved: "✅",
    complete: "🏁",
    completed: "🏁",
    request_changes: "✏️",
    changes_requested: "✏️",
    created: "✨",
    reviewed: "🔍",
    query: "❓",
  };
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

  // The bell shows five, newest first. The server already orders unread ahead
  // of read, so slicing here can never hide something new behind old noise.
  const NOTIFICATION_LIMIT = 5;

  function renderNotifications(items, unread) {
    const list = document.getElementById("bell-list");
    const badge = document.getElementById("bell-badge");
    const foot = document.getElementById("bell-foot");
    badge.hidden = !unread;
    badge.textContent = String(unread || 0);

    const shown = (items || []).slice(0, NOTIFICATION_LIMIT);
    list.textContent = "";
    if (!shown.length) {
      list.append(el("li", {}, el("span", { class: "meta" }, "Nothing yet.")));
      if (foot) foot.hidden = true;
      return;
    }
    shown.forEach((n) => {
      const li = el(
        "li",
        { class: n.read_at ? "" : "unread" },
        el("span", {}, `${ICONS[n.kind] || "•"} ${n.title}`),
        el("time", {}, ago(n.created_at))
      );
      if (n.link) {
        li.style.cursor = "pointer";
        li.addEventListener("click", () => (window.location.href = n.link));
      }
      list.append(li);
    });
    // The bell holds five. Everything older lives on the history page, and
    // this footer is the only route to it from the chrome.
    if (foot) {
      foot.hidden = false;
      foot.textContent = "";
      const link = el("a", { href: "/notifications" }, "See all notifications");
      foot.append(link);
    }
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
          el("div", {}, el("div", {}, a.summary), el("time", {}, ago(a.created_at)))
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
  function activityPager(listId, pagerId, firstPage, total) {
    const list = document.getElementById(listId);
    const pager = document.getElementById(pagerId);
    const range = pager.querySelector(".range");
    const prev = pager.querySelector("[data-prev]");
    const next = pager.querySelector("[data-next]");
    let offset = 0;
    let busy = false;

    function paint(items) {
      list.textContent = "";
      if (!items.length) {
        list.append(el("li", { class: "empty-note" }, "No activity yet."));
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
                el("time", {}, ago(a.created_at))
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
          `/api/dashboard/activity?limit=${ACTIVITY_PAGE}&offset=${nextOffset}`
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

    prev.addEventListener("click", () => go(Math.max(0, offset - ACTIVITY_PAGE)));
    next.addEventListener("click", () => go(offset + ACTIVITY_PAGE));
    paint(firstPage || []);
  }

  function initChrome(reload) {
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
        reload();
      } catch (err) {
        toast(err.message, true);
      }
    });
  }

  // Month grid with a dot on any date carrying a deadline. Deliberately not a
  // list: deadlines are actionable on the Exercises page, and here they are
  // only a glance at where the month is busy.
  function renderCalendar(hostId, deadlines, monthDate, linkFor) {
    const host = document.getElementById(hostId);
    if (!host) return;
    const base = monthDate || new Date();
    const year = base.getFullYear();
    const month = base.getMonth();

    const byDay = new Map();
    (deadlines || []).forEach((d) => {
      const due = new Date(d.due_date);
      if (due.getFullYear() !== year || due.getMonth() !== month) return;
      const day = due.getDate();
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(d);
    });

    const label = document.getElementById("cal-label");
    if (label) {
      label.textContent = base.toLocaleDateString(undefined, {
        month: "long", year: "numeric",
      });
    }

    const first = new Date(year, month, 1).getDay();
    const days = new Date(year, month + 1, 0).getDate();
    const today = new Date();
    const isThisMonth =
      today.getFullYear() === year && today.getMonth() === month;

    host.textContent = "";
    const grid = el("div", { class: "cal-grid" });
    ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach((d) =>
      grid.append(el("span", { class: "cal-head" }, d))
    );
    for (let i = 0; i < first; i += 1) grid.append(el("span", { class: "cal-pad" }));

    for (let day = 1; day <= days; day += 1) {
      const hits = byDay.get(day) || [];
      const cell = el(
        "span",
        {
          class:
            "cal-day" +
            (isThisMonth && today.getDate() === day ? " today" : "") +
            (hits.length ? " has-due" : ""),
        },
        String(day)
      );
      if (hits.length) {
        cell.append(el("i", { class: "cal-dot", "aria-hidden": "true" }));
        cell.title = hits.map((h) => h.title).join(", ");
        cell.style.cursor = "pointer";
        cell.addEventListener("click", () => {
          if (linkFor) window.location.href = linkFor(hits[0]);
        });
      }
      grid.append(cell);
    }
    host.append(grid);
  }

  // Header search. Debounced because it fires per keystroke, and a query per
  // character would put a request in flight for every letter of a word.
  //
  // Wired at module level rather than inside initChrome(), which returns early
  // on any page with no bell -- the search box is in the header of all of them.
  (function wireSearch() {
    const input = document.getElementById("global-search");
    if (!input) return;
    const panel = document.getElementById("search-results");
    let timer = null;

    async function run() {
      const q = input.value.trim();
      if (!q) { panel.hidden = true; return; }
      try {
        const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
        panel.textContent = "";
        if (!data.results.length) {
          panel.append(el("div", { class: "search-empty" }, "Nothing found."));
        }
        data.results.forEach((r) => {
          const row = el(
            "a",
            { class: "search-hit", href: r.link },
            el("span", { class: "hit-label" }, r.label),
            el("span", { class: "hit-sub" }, r.sub)
          );
          panel.append(row);
        });
        panel.hidden = false;
      } catch (err) {
        panel.hidden = true;
      }
    }

    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(run, 220);
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".header-search")) panel.hidden = true;
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") panel.hidden = true;
    });
  })();

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
    renderCalendar,
    activityPager,
    ACTIVITY_PAGE,
    ICONS,
    TONES,
  };
})();
