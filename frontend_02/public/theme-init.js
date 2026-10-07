/* Pre-paint theme (A-14: a file, not an inline script, so CSP can forbid inline scripts).
   Same rule as hooks/useTheme.ts, applied before React mounts so there is no light-to-dark flash. */
(function () {
  var theme = "light";
  try {
    var stored = window.localStorage.getItem("graphrec.theme");
    if (stored === "light" || stored === "dark") theme = stored;
    else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) theme = "dark";
  } catch (e) {
    try { if (window.matchMedia("(prefers-color-scheme: dark)").matches) theme = "dark"; } catch (e2) { /* ignore */ }
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
