// Settings: appearance, personal details, password.
(function () {
  // The shared helpers are published as window.Dash; every page script aliases
  // it to D. dashboard_common.js must load first.
  const D = window.Dash;

  const choices = document.getElementById("theme-choices");
  const root = document.documentElement;

  function currentTheme() {
    try {
      return localStorage.getItem("theme") || "system";
    } catch (e) {
      return "system";
    }
  }

  function selectTheme(value) {
    const input = choices.querySelector(`input[value="${value}"]`);
    if (input) input.checked = true;
  }

  selectTheme(currentTheme());

  choices.addEventListener("change", async (event) => {
    const value = event.target.value;
    // Apply first: the preference is this browser's even if the save fails.
    root.setAttribute("data-theme", value);
    try {
      localStorage.setItem("theme", value);
    } catch (e) {}
    try {
      await D.api("/api/settings/theme", {
        method: "PATCH",
        body: JSON.stringify({ theme: value }),
      });
      D.toast("Theme saved");
    } catch (err) {
      D.toast(`Saved on this device only: ${err.message}`, true);
    }
  });

  const first = document.getElementById("first-name");
  const last = document.getElementById("last-name");
  const phone = document.getElementById("phone");

  D.api("/api/settings/profile")
    .then((me) => {
      first.value = me.first_name || "";
      last.value = me.last_name || "";
      phone.value = me.phone || "";
      selectTheme(me.theme || "system");
    })
    .catch(() => {});

  document.getElementById("save-profile").addEventListener("click", async () => {
    try {
      const saved = await D.api("/api/settings/profile", {
        method: "PATCH",
        body: JSON.stringify({
          first_name: first.value,
          last_name: last.value,
          phone: phone.value,
        }),
      });
      D.toast(`Saved — you appear as ${saved.display_name}`);
    } catch (err) {
      D.toast(err.message, true);
    }
  });

  const current = document.getElementById("current-password");
  const next = document.getElementById("new-password");
  const confirm = document.getElementById("confirm-password");

  document.getElementById("save-password").addEventListener("click", async () => {
    if (next.value !== confirm.value) return D.toast("The new passwords do not match.", true);
    if (next.value.length < 8) return D.toast("Use at least 8 characters.", true);
    try {
      await D.api("/auth/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: current.value,
          new_password: next.value,
          confirm_password: confirm.value,
        }),
      });
      current.value = next.value = confirm.value = "";
      D.toast("Password changed");
    } catch (err) {
      D.toast(err.message, true);
    }
  });
})();
