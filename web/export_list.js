window.CulviaExportList = (() => {
  const DEFAULT_LIMIT = 80;

  function t(key, params = {}, fallback = "") {
    const api = window.CulviaI18n;
    const value = api?.t ? api.t(key, params) : key;
    return value === key && fallback ? fallback : value;
  }

  function safeText(value, fallback = "") {
    const text = String(value ?? "").trim();
    return text || fallback;
  }

  function itemMarkup(photo, index, helpers) {
    const escapeHtml = helpers.escapeHtml;
    const name = safeText(helpers.pathName(photo?.path), t("export.listUnnamed", {}, "未命名照片"));
    const scoreText = safeText(photo?.recommendationText || photo?.overallText, t("export.listNoRecommendation", {}, "暂无推荐"));
    const localizedLevel = helpers.localizedScoreLevel ? helpers.localizedScoreLevel(photo?.level) : photo?.level;
    const level = safeText(localizedLevel, t("export.listUnrated", {}, "未评级"));
    const fullPath = safeText(photo?.path, name);
    const revealSupported = helpers.canRevealFile !== false;
    const revealHint = revealSupported ? t("viewer.revealSupported", {}, "在文件管理器中定位") : t("viewer.revealUnsupported", {}, "当前环境不支持定位文件");
    return `
      <div class="export-item">
        <img src="${escapeHtml(photo?.thumb || "")}" alt="${escapeHtml(t("export.listThumbAlt", { name }, `${name} 缩略图`))}" loading="lazy" />
        <div>
          <strong aria-label="${escapeHtml(fullPath)}" data-ui-tooltip="${escapeHtml(fullPath)}">${escapeHtml(name)}</strong>
          <p>${helpers.manualBadgeMarkup(photo?.manual)} ${escapeHtml(scoreText)} · ${escapeHtml(level)}</p>
        </div>
        <button
          class="button secondary reveal-list ${revealSupported ? "" : "is-unavailable"}"
          type="button"
          data-export-list-index="${index}"
          aria-label="${escapeHtml(revealHint)}"
          data-ui-tooltip="${escapeHtml(revealHint)}"
          ${revealSupported ? "" : 'aria-disabled="true"'}
        >
          ${helpers.iconMarkup("folder")}${escapeHtml(t("export.listReveal", {}, "定位"))}
        </button>
      </div>
    `;
  }

  function emptyMarkup(helpers) {
    return `
      <div class="empty-state compact">
        <div class="empty-symbol">${helpers.iconMarkup("check", "empty-icon")}</div>
        <h2>${helpers.escapeHtml(t("export.listEmptyTitle", {}, "还没有入选照片"))}</h2>
        <p>${helpers.escapeHtml(t("export.listEmptyText", {}, "在选片台标记入选，或采纳当前筛选结果。"))}</p>
      </div>
    `;
  }

  function renderMarkup(photos = [], helpers = {}, options = {}) {
    const limit = Number(options.limit || DEFAULT_LIMIT);
    if (!(photos || []).length) return emptyMarkup(helpers);
    return (photos || [])
      .slice(0, limit)
      .map((photo, index) => itemMarkup(photo, index, helpers))
      .join("");
  }

  function photoForReveal(photos = [], indexValue) {
    const index = Number(indexValue);
    if (!Number.isInteger(index) || index < 0) return null;
    return photos[index] || null;
  }

  return {
    photoForReveal,
    renderMarkup,
  };
})();
