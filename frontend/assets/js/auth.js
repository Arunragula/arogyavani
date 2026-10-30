// frontend/assets/js/auth.js
const AUTH_KEY = "arogyavani_vault_session";

function escapeHtml(unsafe) {
  if (unsafe === null || unsafe === undefined) return "";
  return String(unsafe)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getSession() {
  try {
    const raw = sessionStorage.getItem(AUTH_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function getInviteCode() {
  const s = getSession();
  return s ? s.invite_code : "";
}

async function apiFetch(url, options = {}) {
  const code = getInviteCode();
  const headers = new Headers(options.headers || {});
  if (code) {
    headers.set("X-Invite-Code", code);
  }
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    localStorage.removeItem(AUTH_KEY);
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }
  return response;
}

async function submitInviteCodeLogin(event) {
  event.preventDefault();
  const codeInput = document.getElementById("inviteCodeInput");
  const consentBox = document.getElementById("betaConsentCheck");
  const errorBox = document.getElementById("loginErrorBox");
  const submitBtn = document.getElementById("loginSubmitBtn");

  const code = (codeInput?.value || "").trim();
  if (!code) return;
  if (consentBox && !consentBox.checked) {
    errorBox.textContent = "Please accept the Beta & Educational Use notice to continue.";
    errorBox.classList.remove("hidden");
    return;
  }

  errorBox.classList.add("hidden");
  submitBtn.disabled = true;
  submitBtn.textContent = "Verifying Code...";

  try {
    const res = await fetch("/api/v1/auth/me", {
      headers: { "X-Invite-Code": code },
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Invalid Invite Code.");
    }

    sessionStorage.setItem(
      AUTH_KEY,
      JSON.stringify({
        invite_code: code,
        role: data.role,
        label: data.label,
        allowed_member_id: data.allowed_member_id,
      })
    );
    window.location.href = "/dashboard";
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove("hidden");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Unlock Family Vault";
  }
}

function logoutSession() {
  sessionStorage.removeItem(AUTH_KEY);
  window.location.href = "/login";
}

function requireAuthOrRedirect() {
  const session = getSession();
  if (!session || !session.invite_code) {
    window.location.href = "/login";
    return null;
  }
  const badge = document.getElementById("userSessionBadge");
  if (badge) {
    const roleLabel =
      session.role === "owner"
        ? "👑 Owner"
        : session.role === "editor"
        ? "✍️ Editor"
        : "👁️ Viewer";
    badge.textContent = `${roleLabel} • ${session.label || "Vault"}`;
  }
  return session;
}

function startGuestSession() {
  const session = getSession();
  if (session && session.invite_code) {
    window.location.href = "/dashboard";
  } else {
    window.location.href = "/login";
  }
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
}