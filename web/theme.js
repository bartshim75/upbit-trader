"use strict";

(function initializeTheme() {
  const storageKey = "upbit-dashboard-theme";
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const allowed = new Set(["light", "dark", "system"]);

  function savedPreference() {
    try {
      const saved = window.localStorage.getItem(storageKey);
      return allowed.has(saved) ? saved : "light";
    } catch (_) {
      return "light";
    }
  }

  function apply(preference, persist = true) {
    const selected = allowed.has(preference) ? preference : "light";
    const resolved = selected === "system" ? (media.matches ? "dark" : "light") : selected;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themePreference = selected;
    document.documentElement.style.colorScheme = resolved;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      resolved === "dark" ? "#0b0d0f" : "#f2f1e9",
    );
    if (persist) {
      try { window.localStorage.setItem(storageKey, selected); } catch (_) { /* Storage may be unavailable. */ }
    }
    window.dispatchEvent(new CustomEvent("dashboardthemechange", { detail: { preference: selected, resolved } }));
  }

  media.addEventListener("change", () => {
    if (savedPreference() === "system") apply("system", false);
  });

  window.dashboardTheme = {
    apply,
    preference: savedPreference,
  };
  apply(savedPreference(), false);
})();
