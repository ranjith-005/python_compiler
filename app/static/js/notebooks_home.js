// Notebook list page.
(function () {
  const rows = document.getElementById("nb-rows");
  const empty = document.getElementById("nb-empty");
  const toastEl = document.getElementById("toast");
  let toastTimer = null;

  function toast(message, isError) {
    toastEl.textContent = message;
    toastEl.classList.toggle("err", !!isError);
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toastEl.hidden = true), 2600);
  }

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

  function when(iso) {
    const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
    if (isNaN(d)) return "";
    return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  async function load() {
    let items = [];
    try {
      items = await api("/api/notebooks");
    } catch (err) {
      if (err.message !== "unauthenticated") toast(err.message, true);
      return;
    }
    rows.innerHTML = "";
    empty.hidden = items.length > 0;

    items.forEach((nb) => {
      const tr = document.createElement("tr");

      const nameCell = document.createElement("td");
      const link = document.createElement("a");
      link.className = "nb-link";
      link.href = `/nb/${nb.id}`;
      const icon = document.createElement("span");
      icon.className = "icon";
      icon.textContent = "◉";
      const label = document.createElement("span");
      label.textContent = nb.name;
      link.append(icon, label);
      nameCell.appendChild(link);

      const cellsCell = document.createElement("td");
      cellsCell.textContent = nb.cell_count;

      const timeCell = document.createElement("td");
      timeCell.textContent = when(nb.updated_at);

      const actions = document.createElement("td");
      actions.className = "row-actions";

      const dl = document.createElement("button");
      dl.textContent = "Download";
      dl.addEventListener("click", () => {
        window.location.href = `/api/notebooks/${nb.id}/export`;
      });

      const rename = document.createElement("button");
      rename.textContent = "Rename";
      rename.addEventListener("click", async () => {
        const name = window.prompt("Notebook name", nb.name);
        if (!name) return;
        try {
          await api(`/api/notebooks/${nb.id}`, { method: "PUT", body: JSON.stringify({ name }) });
          load();
        } catch (err) {
          toast(err.message, true);
        }
      });

      const del = document.createElement("button");
      del.className = "danger";
      del.textContent = "Delete";
      del.addEventListener("click", async () => {
        if (!window.confirm(`Delete "${nb.name}"? This cannot be undone.`)) return;
        try {
          await api(`/api/notebooks/${nb.id}`, { method: "DELETE" });
          toast("Notebook deleted");
          load();
        } catch (err) {
          toast(err.message, true);
        }
      });

      actions.append(dl, rename, del);
      tr.append(nameCell, cellsCell, timeCell, actions);
      rows.appendChild(tr);
    });
  }

  document.getElementById("new-btn").addEventListener("click", async () => {
    try {
      const nb = await api("/api/notebooks", {
        method: "POST",
        body: JSON.stringify({ name: "Untitled.ipynb" }),
      });
      window.location.href = `/nb/${nb.id}`;
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("upload-input").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const nb = await api("/api/notebooks/import", { method: "POST", body: form });
      window.location.href = `/nb/${nb.id}`;
    } catch (err) {
      toast(err.message, true);
      event.target.value = "";
    }
  });

  document.getElementById("logout-btn").addEventListener("click", async () => {
    try {
      await fetch("/auth/logout", { method: "POST" });
    } finally {
      window.location.href = "/login";
    }
  });

  load();
})();
