(function () {
  const STORAGE_KEY = "culvia.language";
  const DEFAULT_LANGUAGE = "zh-CN";
  const messages = window.CulviaI18nMessages || {};
  const supportedLanguages = Object.keys(messages);
  const storedLanguage = localStorage.getItem(STORAGE_KEY);
  const resolvedLanguage = storedLanguage || navigator.language || DEFAULT_LANGUAGE;
  let currentLanguage = normalizeLanguage(resolvedLanguage);

  function normalizeLanguage(language) {
    const value = String(language || "").trim();
    if (messages[value]) return value;
    const short = value.split("-")[0].toLowerCase();
    if (short === "zh") return "zh-CN";
    if (short === "en") return "en";
    return DEFAULT_LANGUAGE;
  }

  function format(template, params = {}) {
    return String(template || "").replace(/\{([A-Za-z0-9_]+)\}/g, (_match, key) => {
      return params[key] == null ? "" : String(params[key]);
    });
  }

  function t(key, params = {}, language = currentLanguage) {
    const dictionary = messages[normalizeLanguage(language)] || {};
    const fallback = messages[DEFAULT_LANGUAGE] || {};
    return format(dictionary[key] ?? fallback[key] ?? key, params);
  }

  function optionalT(key, fallback) {
    const value = t(key);
    return value === key ? fallback : value;
  }

  function languageName(language) {
    const normalized = normalizeLanguage(language);
    return optionalT(`settings.languageName.${normalized}`, normalized);
  }

  function languageShortName(language) {
    const normalized = normalizeLanguage(language);
    const fallback = normalized.split("-")[0].toUpperCase();
    return optionalT(`settings.languageShort.${normalized}`, fallback);
  }

  function languageBadge(language) {
    const normalized = normalizeLanguage(language);
    return optionalT(`settings.languageBadge.${normalized}`, languageShortName(normalized));
  }

  function languageFlag(language) {
    const normalized = normalizeLanguage(language);
    return optionalT(`settings.languageFlag.${normalized}`, "");
  }

  function availableLanguages() {
    return supportedLanguages.length ? supportedLanguages : [DEFAULT_LANGUAGE];
  }

  function applyText(root, selector, updater) {
    root.querySelectorAll(selector).forEach((element) => {
      const key = element.getAttribute(selector.slice(1, -1));
      if (key) updater(element, t(key));
    });
  }

  function apply(root = document) {
    document.documentElement.lang = currentLanguage;
    document.title = t("app.title");
    applyText(root, "[data-i18n]", (element, value) => {
      element.textContent = value;
    });
    applyText(root, "[data-i18n-title]", (element, value) => {
      element.dataset.uiTooltip = value;
      element.removeAttribute("title");
    });
    applyText(root, "[data-i18n-aria-label]", (element, value) => {
      element.setAttribute("aria-label", value);
    });
    applyText(root, "[data-i18n-placeholder]", (element, value) => {
      element.setAttribute("placeholder", value);
    });
    applyText(root, "[data-i18n-alt]", (element, value) => {
      element.setAttribute("alt", value);
    });
    applyText(root, "[data-i18n-tooltip]", (element, value) => {
      element.dataset.uiTooltip = value;
      element.removeAttribute("title");
      if (!element.getAttribute("aria-label")) {
        element.setAttribute("aria-label", value);
      }
    });
    syncLanguageControls();
  }

  function syncLanguageControls() {
    const languageSelect = document.querySelector("#languageSelect");
    if (languageSelect) {
      languageSelect.value = currentLanguage;
    }
    const currentText = document.querySelector("#languageCurrentText");
    if (currentText) {
      currentText.textContent = languageBadge(currentLanguage);
    }
    renderLanguageMenu();
  }

  function setLanguageMenuOpen(open) {
    const switcher = document.querySelector("[data-language-switch]");
    const button = document.querySelector("#languageMenuButton");
    const menu = document.querySelector("#languageMenu");
    if (!switcher || !button || !menu) return;
    switcher.classList.toggle("is-open", open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
    menu.hidden = !open;
  }

  function renderLanguageMenu() {
    const menu = document.querySelector("#languageMenu");
    if (!menu) return;
    menu.innerHTML = "";
    availableLanguages().forEach((language) => {
      const normalized = normalizeLanguage(language);
      const active = normalized === currentLanguage;
      const option = document.createElement("button");
      option.className = `language-option${active ? " is-active" : ""}`;
      option.type = "button";
      option.dataset.languageChoice = normalized;
      option.setAttribute("role", "menuitemradio");
      option.setAttribute("aria-checked", active ? "true" : "false");
      const badge = document.createElement("span");
      badge.className = "language-option-badge";
      badge.textContent = languageFlag(normalized) || languageShortName(normalized);
      const label = document.createElement("span");
      label.className = "language-option-label";
      label.textContent = languageName(normalized);
      const mark = document.createElement("span");
      mark.className = "language-option-mark";
      mark.setAttribute("aria-hidden", "true");
      option.append(badge, label, mark);
      menu.append(option);
    });
  }

  function setLanguage(language) {
    const nextLanguage = normalizeLanguage(language);
    if (nextLanguage === currentLanguage) {
      apply();
      return currentLanguage;
    }
    currentLanguage = nextLanguage;
    localStorage.setItem(STORAGE_KEY, currentLanguage);
    apply();
    window.dispatchEvent(new CustomEvent("culvia:languagechange", { detail: { language: currentLanguage } }));
    return currentLanguage;
  }

  function bindLanguageSelect() {
    const languageSelect = document.querySelector("#languageSelect");
    if (languageSelect) {
      languageSelect.value = currentLanguage;
      languageSelect.addEventListener("change", () => setLanguage(languageSelect.value));
    }
    const button = document.querySelector("#languageMenuButton");
    const menu = document.querySelector("#languageMenu");
    button?.addEventListener("click", (event) => {
      event.stopPropagation();
      setLanguageMenuOpen(button.getAttribute("aria-expanded") !== "true");
    });
    menu?.addEventListener("click", (event) => {
      const option = event.target.closest("[data-language-choice]");
      if (!option) return;
      setLanguage(option.dataset.languageChoice);
      setLanguageMenuOpen(false);
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest("[data-language-switch]")) setLanguageMenuOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setLanguageMenuOpen(false);
    });
    syncLanguageControls();
  }

  function ready() {
    bindLanguageSelect();
    apply();
  }

  window.CulviaI18n = {
    apply,
    language: () => currentLanguage,
    languageBadge,
    languageFlag,
    languageName,
    languageShortName,
    languages: () => supportedLanguages.slice(),
    normalizeLanguage,
    setLanguage,
    t,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready, { once: true });
  } else {
    ready();
  }
})();
