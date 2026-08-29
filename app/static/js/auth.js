// Login / register page.
(function () {
  const form = document.getElementById("auth-form");
  const emailEl = document.getElementById("email");
  const passwordEl = document.getElementById("password");
  const errorEl = document.getElementById("form-error");
  const submitBtn = document.getElementById("submit-btn");
  const switchBtn = document.getElementById("switch-btn");
  const switchText = document.getElementById("switch-text");
  const tabs = document.querySelectorAll(".tab[data-mode]");
  const registerOnly = document.getElementById("register-only");
  const firstNameEl = document.getElementById("first-name");
  const lastNameEl = document.getElementById("last-name");
  const phoneEl = document.getElementById("phone");

  let mode = "login";
  const role = "student";

  function setMode(next) {
    mode = next;
    tabs.forEach((t) => t.classList.toggle("active", t.dataset.mode === mode));
    submitBtn.textContent = mode === "login" ? "Sign in" : "Create account";
    passwordEl.autocomplete = mode === "login" ? "current-password" : "new-password";
    switchText.textContent = mode === "login" ? "New here?" : "Already have an account?";
    switchBtn.textContent = mode === "login" ? "Create an account" : "Sign in";
    registerOnly.hidden = mode === "login";
    hideError();
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }
  function hideError() {
    errorEl.hidden = true;
  }

  function readError(data, fallback) {
    const detail = data && data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0];
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : "input";
      return `${field}: ${first.msg}`;
    }
    return fallback;
  }

  tabs.forEach((t) => t.addEventListener("click", () => setMode(t.dataset.mode)));
  switchBtn.addEventListener("click", () =>
    setMode(mode === "login" ? "register" : "login")
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideError();

    const email = emailEl.value.trim();
    const password = passwordEl.value;
    if (!email) return showError("Enter your email address.");
    if (mode === "register" && !firstNameEl.value.trim()) return showError("Enter your first name.");
    if (mode === "register" && !lastNameEl.value.trim()) return showError("Enter your last name.");
    if (mode === "register" && !phoneEl.value.trim()) return showError("Enter your phone number.");
    if (password.length < 8) return showError("Password must be at least 8 characters.");

    submitBtn.disabled = true;
    submitBtn.textContent = mode === "login" ? "Signing in…" : "Creating account…";
    try {
      const res = await fetch(`/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          mode === "register"
            ? { email, password, role, first_name: firstNameEl.value.trim(), last_name: lastNameEl.value.trim(), phone: phoneEl.value.trim() }
            : { email, password }
        ),
      });
      if (res.ok) {
        const body = await res.json().catch(() => ({}));
        // The server decides which portal this account belongs to (SRS §1).
        window.location.href = body.home || "/dashboard";
        return;
      }
      const data = await res.json().catch(() => ({}));
      showError(readError(data, "Something went wrong. Try again."));
    } catch (err) {
      showError("Cannot reach the server.");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = mode === "login" ? "Sign in" : "Create account";
    }
  });

  setMode("login");
})();
