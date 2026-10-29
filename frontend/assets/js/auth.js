// frontend/assets/js/auth.js
const AUTH_KEY = "curavault_session";

function getSession() {
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function startGuestSession() {
  const guestUser = {
    mode: "guest",
    name: "Guest Explorer",
    email: "guest@curavault.local",
    started_at: new Date().toISOString(),
  };
  localStorage.setItem(AUTH_KEY, JSON.stringify(guestUser));
  window.location.href = "/dashboard";
}

function signInWithProfile(event) {
  event.preventDefault();
  const name = document.getElementById("loginName")?.value.trim() || "Member";
  const email = document.getElementById("loginEmail")?.value.trim() || "";
  const user = {
    mode: "member",
    name: name,
    email: email,
    started_at: new Date().toISOString(),
  };
  localStorage.setItem(AUTH_KEY, JSON.stringify(user));
  window.location.href = "/dashboard";
}

function logoutSession() {
  localStorage.removeItem(AUTH_KEY);
  window.location.href = "/login";
}

function requireAuthOrGuest() {
  let session = getSession();
  if (!session) {
    // Auto-create a guest trial session if user opens /dashboard directly
    session = {
      mode: "guest",
      name: "Guest User",
      email: "guest@curavault.local",
      started_at: new Date().toISOString(),
    };
    localStorage.setItem(AUTH_KEY, JSON.stringify(session));
  }
  const badge = document.getElementById("userSessionBadge");
  if (badge) {
    badge.innerHTML = session.mode === "guest"
      ? `⚡ Guest Mode`
      : `👤 ${session.name}`;
  }
}

// Register PWA Service Worker
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
}