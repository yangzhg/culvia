window.CulviaExportPreflight = (() => {
  const actions = Object.freeze({
    pickFolder: "pickFolder",
    none: "",
  });

  function t(key, params = {}, fallback = "") {
    const api = window.CulviaI18n;
    const value = api?.t ? api.t(key, params) : key;
    return value === key && fallback ? fallback : value;
  }

  function currentKey(destination, photos) {
    const fileIds = (Array.isArray(photos) ? photos : []).map((photo) => photo?.fileId || photo?.path || "").join("|");
    return `${destination || ""}::${fileIds}`;
  }

  function renderMarkup(state, helpers) {
    const destination = state?.destination || "";
    if (!destination) return "";
    if (state?.loading) {
      return `<div class="export-preflight is-loading">${helpers.iconMarkup("loader")}${helpers.escapeHtml(t("export.preflightLoading", {}, "正在检查导出文件"))}</div>`;
    }
    if (state?.error) {
      return `
        <div class="export-preflight is-warning">
          ${helpers.iconMarkup("circleHelp")}
          <span>${helpers.escapeHtml(state.error)}</span>
          ${renderPickFolderAction(helpers)}
        </div>
      `;
    }
    const preflight = state?.preflight;
    if (!preflight) return "";
    const ready = Number(preflight.ready || 0);
    const missing = Number(preflight.missing || 0);
    const renamed = Number(preflight.renamed || 0);
    const total = Number(preflight.total || 0);
    const destinationIssue = String(preflight.destinationIssue || "");
    const tone = destinationIssue || missing ? "is-danger" : renamed ? "is-warning" : "is-ready";
    const summary = destinationIssue
      ? destinationIssue
      : missing
      ? t("export.preflightMissing", { count: missing }, `${missing} 张找不到原图`)
      : renamed
        ? t("export.preflightRenamed", { count: renamed }, `${renamed} 张会自动改名`)
        : total
          ? t("export.preflightPassed", {}, "导出前检查通过")
          : t("export.preflightEmpty", {}, "还没有入选照片");
    return `
      <div class="export-preflight ${tone}">
        ${helpers.iconMarkup(destinationIssue || missing ? "x" : renamed ? "circleHelp" : "check")}
        <span>${helpers.escapeHtml(summary)}</span>
        <span>${helpers.escapeHtml(t("export.preflightReady", { count: ready }, `${ready} 张可复制`))}</span>
        ${renamed ? `<span>${helpers.escapeHtml(t("export.preflightRenamedShort", { count: renamed }, `${renamed} 张改名`))}</span>` : ""}
        ${missing ? `<span>${helpers.escapeHtml(t("export.preflightMissingShort", { count: missing }, `${missing} 张缺失`))}</span>` : ""}
        ${destinationIssue ? renderPickFolderAction(helpers) : ""}
      </div>
      ${renderDetails(preflight, helpers)}
    `;
  }

  function renderPickFolderAction(helpers) {
    const label = t("export.preflightRepick", {}, "重新选择");
    return `
      <button class="export-preflight-action" type="button" data-export-pick-folder aria-label="${helpers.escapeHtml(label)}" data-ui-tooltip="${helpers.escapeHtml(label)}">
        ${helpers.iconMarkup("folder")}${helpers.escapeHtml(label)}
      </button>
    `;
  }

  function renderDetails(preflight, helpers) {
    const missingFiles = Array.isArray(preflight?.missingFiles) ? preflight.missingFiles : [];
    const renamedFiles = Array.isArray(preflight?.renamedFiles) ? preflight.renamedFiles : [];
    if (!missingFiles.length && !renamedFiles.length) return "";
    const missingMarkup = missingFiles.length
      ? `
        <div class="export-preflight-detail-group">
          <strong>${helpers.escapeHtml(t("export.preflightMissingGroup", {}, "缺失原图"))}</strong>
          ${missingFiles.slice(0, 5).map((path) => renderPathRow(path, helpers)).join("")}
        </div>
      `
      : "";
    const renamedMarkup = renamedFiles.length
      ? `
        <div class="export-preflight-detail-group">
          <strong>${helpers.escapeHtml(t("export.preflightRenamedGroup", {}, "自动改名"))}</strong>
          ${renamedFiles
            .slice(0, 5)
            .map((item) => {
              const source = String(item?.source || "");
              const target = String(item?.target || "");
              return `
                <div class="export-preflight-row">
                  <span aria-label="${helpers.escapeHtml(source)}" data-ui-tooltip="${helpers.escapeHtml(source)}">${helpers.escapeHtml(helpers.pathName(source))}</span>
                  <span aria-label="${helpers.escapeHtml(target)}" data-ui-tooltip="${helpers.escapeHtml(target)}">${helpers.escapeHtml(helpers.pathName(target))}</span>
                </div>
              `;
            })
            .join("")}
        </div>
      `
      : "";
    return `
      <details class="export-preflight-details">
        <summary>${helpers.iconMarkup("chevronDown")}${helpers.escapeHtml(t("export.preflightDetails", {}, "查看文件明细"))}</summary>
        <div class="export-preflight-detail-grid">
          ${missingMarkup}
          ${renamedMarkup}
        </div>
      </details>
    `;
  }

  function renderPathRow(path, helpers) {
    const text = String(path || "");
    const parent = helpers.parentPath(text);
    return `
      <div class="export-preflight-row">
        <span aria-label="${helpers.escapeHtml(text)}" data-ui-tooltip="${helpers.escapeHtml(text)}">${helpers.escapeHtml(helpers.pathName(text))}</span>
        <small aria-label="${helpers.escapeHtml(parent)}" data-ui-tooltip="${helpers.escapeHtml(text)}">${helpers.escapeHtml(parent)}</small>
      </div>
    `;
  }

  function actionFromEvent(event) {
    const target = event?.target;
    if (target?.closest?.("[data-export-pick-folder]")) return actions.pickFolder;
    return actions.none;
  }

  return {
    actionFromEvent,
    actions,
    currentKey,
    renderPickFolderAction,
    renderDetails,
    renderMarkup,
    renderPathRow,
  };
})();
