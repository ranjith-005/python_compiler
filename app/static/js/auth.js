// Sign-in page. Accounts are not self-served: a trainer enrols each student
// and hands over the credentials, so this page only signs people in.
(function () {
  const form = document.getElementById("auth-form");
  const emailEl = document.getElementById("email");
  const passwordEl = document.getElementById("password");
  const errorEl = document.getElementById("form-error");
  const submitBtn = document.getElementById("submit-btn");

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

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideError();

    const email = emailEl.value.trim();
    const password = passwordEl.value;
    if (!email) return showError("Enter your email address.");
    if (password.length < 8) return showError("Password must be at least 8 characters.");

    submitBtn.disabled = true;
    submitBtn.textContent = "Signing in…";
    try {
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
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
      submitBtn.textContent = "Sign in";
    }
  });
})();
