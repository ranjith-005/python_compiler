(function () {
  const list = document.getElementById("student-list");
  const count = document.getElementById("student-count");
  const search = document.getElementById("student-search");
  let students = [];

  function logout() { fetch("/auth/logout", { method: "POST" }).finally(() => { window.location.href = "/login"; }); }
  function render() {
    const term = search.value.trim().toLowerCase();
    const visible = students.filter((s) => !term || `${s.name} ${s.email}`.toLowerCase().includes(term));
    count.textContent = students.length;
    list.textContent = "";
    if (!visible.length) { list.innerHTML = '<p class="empty-note">No students match your search.</p>'; return; }
    visible.forEach((s) => {
      const name = s.name || s.email;
      const row = document.createElement("div"); row.className = "row student-row";
      row.innerHTML = `<div class="who"><span class="avatar"></span><div><div class="title"></div><div class="meta"><span>${s.assigned} assigned</span><span class="dot-sep">${s.completed} completed</span>${s.awaiting ? `<span class="pill amber">${s.awaiting} awaiting review</span>` : ""}</div></div></div><span class="tests">${s.progress}%</span><div class="bar ${s.progress === 100 ? "done" : ""}"><span></span></div>`;
      row.querySelector(".avatar").textContent = name.slice(0, 2).toUpperCase();
      row.querySelector(".title").textContent = name;
      row.querySelector(".bar span").style.width = `${s.progress}%`;
      list.appendChild(row);
    });
  }
  async function load() {
    const response = await fetch("/api/dashboard/trainer");
    if (response.status === 401) { window.location.href = "/login"; return; }
    const data = await response.json(); students = data.students || []; render();
  }
  document.getElementById("logout-btn").addEventListener("click", logout);
  search.addEventListener("input", render);
  load().catch(() => { list.innerHTML = '<p class="empty-note">Unable to load students.</p>'; });
})();
