// Notification history. The bell shows "3 minutes ago" because recency is what
// matters there; a history shows the real date and time, because "6 days ago"
// is useless when you are trying to remember which day something arrived.
(function () {
  const D = window.Dash;
  const ICONS = {
    assigned: "📌", approve: "✅", request_changes: "✏️",
    submitted: "📝", reopen: "🔓",
  };
  let offset = 0;

  function stamp(iso) {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  }

  async function load() {
    const data = await D.api(`/api/dashboard/notifications?offset=${offset}`);
    const list = document.getElementById("notification-list");
    if (!offset) list.textContent = "";

    if (!data.items.length && !offset) {
      list.append(D.el("li", {}, D.el("span", { class: "meta" }, "Nothing yet.")));
    }
    data.items.forEach((n) => {
      const li = D.el(
        "li",
        { class: n.read_at ? "" : "unread" },
        D.el("span", {}, `${ICONS[n.kind] || "•"} ${n.title}`),
        D.el("time", { title: n.created_at }, stamp(n.created_at))
      );
      if (n.link) {
        li.style.cursor = "pointer";
        li.addEventListener("click", () => (window.location.href = n.link));
      }
      list.append(li);
    });

    offset += data.items.length;
    document.getElementById("notification-pager").hidden = offset >= data.total;
  }

  document.getElementById("notification-more").addEventListener("click", () =>
    load().catch((e) => D.flash(e.message, "error"))
  );
  load().catch((e) => D.flash(e.message, "error"));
})();
