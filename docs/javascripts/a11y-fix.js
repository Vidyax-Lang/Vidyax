document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.querySelector('div.md-search[role="dialog"]');
  if (dialog && !dialog.hasAttribute("aria-label")) {
    dialog.setAttribute("aria-label", "Search");
  }
});