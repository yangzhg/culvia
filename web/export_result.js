window.CulviaExportResult = (() => {
  function t(key, params = {}, fallback = "") {
    const api = window.CulviaI18n;
    const value = api?.t ? api.t(key, params) : key;
    return value === key && fallback ? fallback : value;
  }

  function dataModule() {
    return window.CulviaExportResultData;
  }

  function renderMarkup(result, helpers) {
    if (!result) return "";
    const normalized = dataModule()?.normalize(result);
    if (!normalized) return "";
    const { copied, copiedFiles, destination, skipped, skippedDetails, skippedReasonSummary } = normalized;
    const tone = skipped ? "is-warning" : "is-ready";
    const title = skipped
      ? t("export.resultCopiedPartialTitle", { copied, skipped }, `已复制 ${copied} 张，${skipped} 张未复制`)
      : t("export.resultCopiedTitle", { copied }, `已复制 ${copied} 张`);
    const stateLabel = skipped ? t("export.resultPartial", {}, "部分完成") : t("export.resultReady", {}, "导出完成");
    const hasDetails = copiedFiles.length || skippedDetails.length;
    return `
      <div class="export-result ${tone}">
        <div class="export-result-card">
          <div class="export-result-status">
            <span class="export-result-badge">
              ${helpers.iconMarkup(skipped ? "circleHelp" : "check")}${helpers.escapeHtml(stateLabel)}
            </span>
            <strong>${helpers.escapeHtml(title)}</strong>
            ${
              destination
                ? `<small aria-label="${helpers.escapeHtml(destination)}" data-ui-tooltip="${helpers.escapeHtml(destination)}">${helpers.escapeHtml(t("export.resultDeliveryTo", { destination: helpers.pathName(destination) }, `交付到 ${helpers.pathName(destination)}`))}</small>`
                : ""
            }
          </div>
          <div class="export-result-metrics" aria-label="${helpers.escapeHtml(t("export.resultCountAria", {}, "导出数量"))}">
            ${renderMetric(copied, t("export.resultCopied", {}, "已复制"), helpers)}
            ${skipped ? renderMetric(skipped, t("export.resultNotCopied", {}, "未复制"), helpers) : ""}
          </div>
          ${destination ? renderDestination(destination, helpers) : ""}
          ${
            destination
              ? `
                <div class="export-result-actions">
                  ${renderCopyDestinationAction(helpers)}
                  ${renderRevealDestinationAction(helpers)}
                </div>
              `
              : ""
          }
        </div>
        ${skipped ? renderSkippedReasonSummary(skippedReasonSummary, helpers) : ""}
        ${
          hasDetails
            ? `
              <details class="export-result-details">
                <summary>${helpers.iconMarkup("chevronDown")}${helpers.escapeHtml(t("export.resultDetails", {}, "查看导出明细"))}</summary>
                <div class="export-result-grid">
                  ${copiedFiles.length ? renderFileGroup(t("export.resultCopied", {}, "已复制"), copiedFiles, helpers) : ""}
                  ${skippedDetails.length ? renderSkippedGroup(t("export.resultNotCopied", {}, "未复制"), skippedDetails, helpers) : ""}
                </div>
              </details>
            `
            : ""
        }
      </div>
    `;
  }

  function normalizeSkippedDetails(result) {
    return dataModule().normalizeSkippedDetails(result);
  }

  function normalizeSkippedReasonSummary(result, skippedDetails) {
    return dataModule().normalizeSkippedReasonSummary(result, skippedDetails);
  }

  function renderSkippedReasonSummary(summary, helpers) {
    if (!summary.length) return "";
    return `
      <div class="export-result-reasons" aria-label="${helpers.escapeHtml(t("export.resultReasonsAria", {}, "未复制原因"))}">
        <span>${helpers.escapeHtml(t("export.resultReasons", {}, "未复制原因"))}</span>
        ${summary
          .map(
            (item) => `
              <strong aria-label="${helpers.escapeHtml(item.reason || "")}" data-ui-tooltip="${helpers.escapeHtml(item.reason || "")}">
                ${helpers.escapeHtml(localizedSkippedLabel(item))}${item.count ? ` · ${helpers.escapeHtml(item.count)}` : ""}
              </strong>
            `,
          )
          .join("")}
      </div>
    `;
  }

  function renderMetric(value, label, helpers) {
    return `
      <span class="export-result-metric">
        <strong>${helpers.escapeHtml(value)}</strong>
        <small>${helpers.escapeHtml(label)}</small>
      </span>
    `;
  }

  function renderDestination(destination, helpers) {
    const destinationName = helpers.pathName(destination);
    return `
      <div class="export-result-destination">
        <span>${helpers.escapeHtml(t("export.resultDestination", {}, "目标目录"))}</span>
        <strong aria-label="${helpers.escapeHtml(destination)}" data-ui-tooltip="${helpers.escapeHtml(destination)}">${helpers.escapeHtml(destinationName)}</strong>
        <small aria-label="${helpers.escapeHtml(destination)}" data-ui-tooltip="${helpers.escapeHtml(destination)}">${helpers.escapeHtml(destination)}</small>
      </div>
    `;
  }

  function renderRevealDestinationAction(helpers) {
    if (helpers.canRevealDestination === false) {
      const hint = t("export.revealFailureDetail", {}, "当前环境无法直接打开文件管理器，请使用导出位置手动打开。");
      return `
        <span class="export-result-action is-unavailable" tabindex="0" role="note" aria-label="${helpers.escapeHtml(hint)}" data-ui-tooltip="${helpers.escapeHtml(hint)}">
          ${helpers.iconMarkup("circleHelp")}${helpers.escapeHtml(t("export.resultManualOpen", {}, "手动打开"))}
        </span>
      `;
    }
    const label = t("export.resultOpenFolder", {}, "打开目录");
    return `
      <button class="export-result-action" type="button" data-export-reveal-destination aria-label="${helpers.escapeHtml(label)}" data-ui-tooltip="${helpers.escapeHtml(label)}">
        ${helpers.iconMarkup("folder")}${helpers.escapeHtml(label)}
      </button>
    `;
  }

  function renderCopyDestinationAction(helpers) {
    const label = t("export.resultCopyPath", {}, "复制路径");
    return `
      <button class="export-result-action" type="button" data-export-copy-destination aria-label="${helpers.escapeHtml(label)}" data-ui-tooltip="${helpers.escapeHtml(label)}">
        ${helpers.iconMarkup("copy")}${helpers.escapeHtml(label)}
      </button>
    `;
  }

  function renderSkippedGroup(title, items, helpers) {
    return `
      <div class="export-result-group">
        <strong>${helpers.escapeHtml(title)}</strong>
        ${items.slice(0, 8).map((item) => renderSkippedPathRow(item, helpers)).join("")}
      </div>
    `;
  }

  function renderFileGroup(title, paths, helpers) {
    return `
      <div class="export-result-group">
        <strong>${helpers.escapeHtml(title)}</strong>
        ${paths.slice(0, 8).map((path) => renderPathRow(path, helpers)).join("")}
      </div>
    `;
  }

  function renderSkippedPathRow(item, helpers) {
    const text = String(item?.path || "");
    const label = localizedSkippedLabel(item);
    const resolveRef = window.CulviaCommandView?.resolveTextRef;
    const message = (resolveRef ? resolveRef(item?.messageText, "") : "") || String(item?.message || "");
    const detail = `${label}${message ? ` · ${message}` : ""}`;
    return `
      <div class="export-result-row">
        <span aria-label="${helpers.escapeHtml(text)}" data-ui-tooltip="${helpers.escapeHtml(text)}">${helpers.escapeHtml(helpers.pathName(text))}</span>
        <small aria-label="${helpers.escapeHtml(detail)}" data-ui-tooltip="${helpers.escapeHtml(detail)}">${helpers.escapeHtml(detail)}</small>
      </div>
    `;
  }

  function localizedSkippedLabel(item) {
    const reason = String(item?.reason || "");
    if (reason === "missing") return t("export.resultReasonMissing", {}, "源文件缺失");
    if (reason === "copy_failed") return t("export.resultReasonCopyFailed", {}, "复制失败");
    const text = String(item?.label || "");
    if (!text || text === "未复制") return t("export.resultNotCopied", {}, "未复制");
    if (text === "源文件缺失") return t("export.resultReasonMissing", {}, "源文件缺失");
    return text;
  }

  function renderPathRow(path, helpers) {
    const text = String(path || "");
    const parent = helpers.parentPath(text);
    return `
      <div class="export-result-row">
        <span aria-label="${helpers.escapeHtml(text)}" data-ui-tooltip="${helpers.escapeHtml(text)}">${helpers.escapeHtml(helpers.pathName(text))}</span>
        <small aria-label="${helpers.escapeHtml(parent)}" data-ui-tooltip="${helpers.escapeHtml(text)}">${helpers.escapeHtml(parent)}</small>
      </div>
    `;
  }

  return {
    normalizeSkippedDetails,
    normalizeSkippedReasonSummary,
    renderCopyDestinationAction,
    renderDestination,
    renderFileGroup,
    renderMarkup,
    renderMetric,
    renderPathRow,
    renderRevealDestinationAction,
    renderSkippedGroup,
    renderSkippedPathRow,
    renderSkippedReasonSummary,
  };
})();
