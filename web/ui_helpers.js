(function () {
  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function percentValue(value) {
    return `${Math.round(Number(value || 0) * 100)}%`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function textHintAttributes(value) {
    const text = String(value ?? "").trim();
    return text ? ` aria-label="${escapeHtml(text)}" data-ui-tooltip="${escapeHtml(text)}"` : "";
  }

  function iconMarkup(name, className = "") {
    const paths = (window.CulviaIconPaths || {})[name];
    if (!paths) return "";
    const extraClasses = String(className || "")
      .split(/\s+/)
      .filter((item) => item && item !== "icon");
    const classes = ["icon", ...extraClasses, ...(name === "loader" ? ["is-spinning"] : [])].join(" ");
    return `<span class="${classes}" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false">${paths.join("")}</svg></span>`;
  }

  function renderStaticIcons(root = document) {
    root.querySelectorAll("[data-icon]").forEach((node) => {
      const name = node.dataset.icon;
      const paths = (window.CulviaIconPaths || {})[name];
      if (!paths) return;
      node.innerHTML = `<svg viewBox="0 0 24 24" focusable="false">${paths.join("")}</svg>`;
    });
  }

  window.CulviaUiHelpers = {
    clamp,
    percentValue,
    escapeHtml,
    textHintAttributes,
    iconMarkup,
    renderStaticIcons,
  };
})();
