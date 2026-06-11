const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const llmConfigView = window.CulviaLlmConfigView;
const commandView = window.CulviaCommandView;
const resolveTextRef = (ref, fallback = "") => commandView.resolveTextRef(ref, fallback);
const galleryKeyboard = window.CulviaGalleryKeyboard;
const galleryView = window.CulviaGalleryView;
const viewerKeyboard = window.CulviaViewerKeyboard;
const viewerInspector = window.CulviaViewerInspector;
const manualStatus = window.CulviaManualStatus;
const manualStars = manualStatus.stars;
const i18n = window.CulviaI18n;
const apiClient = window.CulviaApi;
const {
  manualColorLabels,
  manualSourceKeys,
  metricLabelKeys,
  scoreLevelKeys,
  supportedTypes,
  technicalTagKeys,
} = window.CulviaAppConfig;
const {
  clamp,
  percentValue,
  escapeHtml,
  textHintAttributes,
  iconMarkup,
  renderStaticIcons,
} = window.CulviaUiHelpers;


let appState = null;
let networkMode = "direct";
let pollTimer = null;
let commandNotice = null;
let commandNoticeTimer = null;
let llmReviewConfirmedForSession = false;
let pendingScoringPayload = null;
let llmConfirmOpen = false;
let batchStatusConfirmOpen = false;
let dangerConfirmOpen = false;
let pendingBatchStatus = "";
let pendingBatchTarget = { scope: "filtered", fileIds: [], count: 0, label: "当前筛选" };
let batchStatusReturnSelector = "#galleryBatchPickBtn";
let pendingDangerConfirm = null;
let dangerConfirmReturnElement = null;
const VIEW_STORAGE_KEY = "culvia.activeView.v1";
const VIEW_NAMES = ["viewer", "gallery", "distribution", "export"];
let activeView = normalizeViewName(localStorage.getItem(VIEW_STORAGE_KEY));
const SIDEBAR_COLLAPSED_KEY = "culvia.sidebarCollapsed";
let sidebarCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
let settingsDrawerOpen = false;
let uiTooltipAnchor = null;
let uiTooltipRaf = 0;
let curationHistory = [];
let curationHistoryLoading = false;
let curationHistoryError = "";
let shortcutHelpOpen = false;
let markUpdateQueue = Promise.resolve();

const cullingFlow = window.CulviaCullingFlow;
const clipboard = window.CulviaClipboard;
const distributionModel = window.CulviaDistributionModel;
const distributionView = window.CulviaDistributionView;
const bucketWave = distributionModel.bucketWave;
const distributionLensOptions = distributionModel.lensOptions;
const distributionStats = distributionModel.stats;
const distributionTier = distributionModel.tier;
const numericValue = distributionModel.numericValue;
const scoreBuckets = distributionModel.scoreBuckets;
const {
  distributionDecision,
  distributionEntries,
  distributionLensConfig,
  distributionLensMeta,
  distributionTierMeta,
  renderDimensionStack,
  renderMetricRadar,
} = distributionView;

function normalizeViewName(view) {
  return VIEW_NAMES.includes(view) ? view : "viewer";
}

function persistActiveView(view) {
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, normalizeViewName(view));
  } catch (_error) {
    // Losing view memory is acceptable when storage is blocked.
  }
}

function postJson(url, data) {
  return apiClient.postJson(url, data);
}

function getJson(url) {
  return apiClient.getJson(url);
}

function errorMessage(error) {
  return apiClient.errorMessage(error);
}

function setText(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value;
}

function setTextWithHint(selector, value) {
  const node = $(selector);
  if (!node) return;
  node.textContent = value;
  const text = String(value ?? "").trim();
  if (!text) {
    node.removeAttribute("aria-label");
    delete node.dataset.uiTooltip;
    node.removeAttribute("title");
    return;
  }
  node.setAttribute("aria-label", text);
  node.dataset.uiTooltip = text;
  node.removeAttribute("title");
}

function t(key, params = {}) {
  return i18n?.t ? i18n.t(key, params) : key;
}

function tr(key, params = {}, fallback = "") {
  const value = t(key, params);
  return value === key && fallback ? fallback : value;
}

function applyI18n(root = document) {
  if (i18n?.apply) i18n.apply(root);
}

function ensureUiTooltipPortal() {
  let tooltip = $("#uiTooltipPortal");
  if (tooltip) return tooltip;
  tooltip = document.createElement("div");
  tooltip.id = "uiTooltipPortal";
  tooltip.className = "ui-tooltip-portal is-hidden";
  tooltip.setAttribute("role", "tooltip");
  document.body.appendChild(tooltip);
  document.body.classList.add("has-tooltip-portal");
  return tooltip;
}

function tooltipAnchorFromEventTarget(target) {
  return target?.closest?.("[data-ui-tooltip]") || null;
}

function positionUiTooltip() {
  if (!uiTooltipAnchor) return;
  const tooltip = ensureUiTooltipPortal();
  if (tooltip.classList.contains("is-hidden")) return;
  const anchorRect = uiTooltipAnchor.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();
  const margin = 10;
  const preferredTop = anchorRect.bottom + 8;
  const fallbackTop = anchorRect.top - tooltipRect.height - 8;
  const top = preferredTop + tooltipRect.height + margin <= window.innerHeight
    ? preferredTop
    : Math.max(margin, fallbackTop);
  const centeredLeft = anchorRect.left + anchorRect.width / 2 - tooltipRect.width / 2;
  const left = Math.max(margin, Math.min(centeredLeft, window.innerWidth - tooltipRect.width - margin));
  tooltip.style.left = `${Math.round(left)}px`;
  tooltip.style.top = `${Math.round(top)}px`;
  tooltip.dataset.placement = top < anchorRect.top ? "top" : "bottom";
}

function showUiTooltip(anchor) {
  const text = String(anchor?.dataset?.uiTooltip || "").trim();
  if (!text) return;
  uiTooltipAnchor = anchor;
  const tooltip = ensureUiTooltipPortal();
  tooltip.textContent = text;
  tooltip.classList.remove("is-hidden");
  window.cancelAnimationFrame(uiTooltipRaf);
  uiTooltipRaf = window.requestAnimationFrame(positionUiTooltip);
}

function hideUiTooltip(anchor = null) {
  if (anchor && uiTooltipAnchor !== anchor) return;
  uiTooltipAnchor = null;
  window.cancelAnimationFrame(uiTooltipRaf);
  uiTooltipRaf = 0;
  const tooltip = $("#uiTooltipPortal");
  if (!tooltip) return;
  tooltip.classList.add("is-hidden");
  tooltip.removeAttribute("style");
}

function bindUiTooltipPortal() {
  ensureUiTooltipPortal();
  document.addEventListener("pointerover", (event) => {
    const anchor = tooltipAnchorFromEventTarget(event.target);
    if (anchor) showUiTooltip(anchor);
  });
  document.addEventListener("pointerout", (event) => {
    const anchor = tooltipAnchorFromEventTarget(event.target);
    if (anchor && !anchor.contains(event.relatedTarget)) hideUiTooltip(anchor);
  });
  document.addEventListener("focusin", (event) => {
    const anchor = tooltipAnchorFromEventTarget(event.target);
    if (anchor) showUiTooltip(anchor);
  });
  document.addEventListener("focusout", (event) => {
    const anchor = tooltipAnchorFromEventTarget(event.target);
    if (anchor) hideUiTooltip(anchor);
  });
  window.addEventListener("scroll", () => {
    if (uiTooltipAnchor) positionUiTooltip();
  }, true);
  window.addEventListener("resize", () => hideUiTooltip());
}

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function focusableDialogElements(dialog) {
  if (!dialog) return [];
  return Array.from(dialog.querySelectorAll(focusableSelector)).filter((node) => {
    const style = window.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  });
}

function activeModalDialog() {
  if (dangerConfirmOpen) return $("#dangerConfirmDialog");
  if (llmConfirmOpen) return $("#llmConfirmDialog");
  if (batchStatusConfirmOpen) return $("#batchStatusConfirmDialog");
  if (shortcutHelpOpen) return $("#shortcutHelpDialog");
  if (settingsDrawerOpen) return $("#settingsDrawer");
  return null;
}

function trapActiveDialogFocus(event) {
  if (event.key !== "Tab") return false;
  const dialog = activeModalDialog();
  if (!dialog) return false;
  const focusables = focusableDialogElements(dialog);
  if (!focusables.length) {
    event.preventDefault();
    dialog.focus();
    return true;
  }
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  if (!dialog.contains(document.activeElement)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
    return true;
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
    return true;
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
    return true;
  }
  return false;
}

function isScoringJob(job = appState?.job) {
  return Boolean(job?.running) && (job.kind || "scoring") === "scoring";
}

function isLlmReviewJob(job = appState?.job) {
  return Boolean(job?.running) && job.kind === "llm_review";
}

function isCancellableJob(job = appState?.job) {
  return isScoringJob(job) || isLlmReviewJob(job);
}

function matchingSourcePreview(folders) {
  return sourcePanel.matchingPreview(folders);
}

function isSourcePreviewActive() {
  return sourcePanel.isPreviewActive();
}

function sourceInputSnapshot() {
  return sourcePanel.inputSnapshot();
}

function applySourceInputSnapshot(snapshot) {
  return sourcePanel.applyInputSnapshot(snapshot);
}

function pathName(path) {
  const normalized = String(path || "").replaceAll("\\", "/").replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).pop() || normalized || t("common.unknown");
}

function parentPath(path) {
  const normalized = String(path || "").replaceAll("\\", "/").replace(/\/+$/, "");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= 1) return normalized;
  return `/${parts.slice(0, -1).join("/")}`;
}

function hasSelectedSource() {
  return sourcePanel.hasSelectedSource();
}

function displayNetworkLabel(labelText) {
  return resolveTextRef(labelText, "") || t("network.directConnection");
}

function updatePathSummaries() {
  return sourcePanel.updatePathSummaries();
}

function scoreValue(value) {
  return value == null ? t("common.noData") : Number(value).toFixed(1);
}

function localizedScoreLevel(level) {
  const value = String(level || "").trim();
  return value ? tr(scoreLevelKeys[value] || "", {}, value) : t("scoreLevel.unrated");
}

function localizedMetricText(value, missing = t("common.noData")) {
  const text = String(value ?? "").trim();
  if (!text || text === "暂无") return missing;
  if (text === "未评分") return t("scoreLevel.unrated");
  if (text === "未判断") return t("manual.status.unreviewed");
  if (text === "未计算") return t("score.notCalculated");
  if (text === "未评审") return t("score.notReviewed");
  return text;
}

function localizedTechnicalTag(tag) {
  const value = String(tag || "").trim();
  return value ? tr(technicalTagKeys[value] || "", {}, value) : "";
}

function localizedManualSource(manual) {
  const source = String(manual?.source || "").trim();
  const label = String(manual?.sourceLabel || "").trim();
  return tr(manualSourceKeys[source] || manualSourceKeys[label] || "", {}, label || t("manual.sourceEmpty"));
}

function metricText(value, missing = t("common.noData")) {
  return localizedMetricText(value, missing);
}

function photoCountText(count) {
  const value = Number(count || 0);
  return tr("common.photoCount", { count: value }, `${value} 张`);
}

function hasMetric(value) {
  return Boolean(value && value !== "暂无");
}

function manualStatusLabel(status) {
  const normalized = manualStatus.normalizeStatus(status);
  if (normalized === "pick") return t("manual.status.pick");
  if (normalized === "hold") return t("manual.status.hold");
  if (normalized === "reject") return t("manual.status.reject");
  return t("manual.status.unreviewed");
}

function manualStatusClass(status) {
  return manualStatus.statusClass(status);
}

function manualStatusBadgeLabel(status, fallbackLabel) {
  if (manualStatus.normalizeStatus(status) === "hold") return t("manual.status.hold");
  return fallbackLabel;
}

function colorLabelMeta(value) {
  const item = manualColorLabels.find((candidate) => candidate.value === value) || manualColorLabels[0];
  return { ...item, label: tr(item.labelKey, {}, item.label) };
}

function localizedModelOptionLabel(option = {}) {
  return tr(`model.option.${option.key}.label`, {}, option.label || option.key || "");
}

function localizedModelOptionSubtitle(option = {}) {
  return tr(`model.option.${option.key}.subtitle`, {}, option.subtitle || "");
}

function localizedModelOptionState(option = {}) {
  const stateText = resolveTextRef(option.stateText, "");
  if (stateText) return stateText;
  if (option.requiresDownload) return option.downloaded ? t("model.ready") : t("model.firstUse");
  return t("model.localCompute");
}

function localizedListJoin(items = []) {
  const separator = i18n?.language?.() === "en" ? ", " : "、";
  return items.filter(Boolean).join(separator);
}

function localizedHistoryScope(scope) {
  if (scope === "selected") return t("history.scope.selected");
  if (scope === "filtered") return t("history.scope.filtered");
  if (scope === "current") return t("history.scope.current");
  return "";
}

function localizedHistoryKind(kind) {
  return tr(`history.action.${kind || "default"}`, {}, kind || t("history.action.default"));
}

function localizedHistoryStatus(status, fallback = "") {
  const normalized = String(status || "").trim();
  if (normalized) return manualStatusLabel(normalized);
  return fallback || t("manual.status.unreviewed");
}

function localizedHistorySummary(record = {}, kindLabel = localizedHistoryKind(record.kind)) {
  const payload = record.payload || {};
  const kind = String(record.kind || "");
  if (kind === "mark") return t("history.summary.mark", { count: Number(payload.marked || 1) });
  if (kind === "status") {
    return t("history.summary.status", {
      status: localizedHistoryStatus(payload.status, payload.statusLabel),
      count: Number(payload.marked || 0),
    });
  }
  if (kind === "color") {
    const count = Number(payload.colored || 0);
    const color = String(payload.colorLabel || "");
    if (!color) return t("history.summary.colorClear", { count });
    return t("history.summary.colorSet", { color: colorLabelMeta(color).label, count });
  }
  if (kind === "restore") return t("history.summary.restore", { count: Number(payload.restored || 0) });
  if (kind === "accept") {
    const source = payload.basis === "llm" ? t("filters.llm") : t("manual.acceptModel");
    return t("history.summary.accept", { source, count: Number(payload.accepted || 0) });
  }
  if (kind === "undo") {
    const target = payload.undoneKind ? localizedHistoryKind(payload.undoneKind) : t("history.recentAction");
    return t("history.summary.undo", { target });
  }
  return record.summary || kindLabel;
}

function localizedMetricLabel(field, labels = {}) {
  return tr(metricLabelKeys[field] || `sort.${field}_0_10`, {}, labels[field] || field);
}

function colorLabelTitle(item) {
  return `${item.label}${item.shortcut ? ` · ${item.shortcut.toUpperCase()}` : ""}`;
}

function galleryPhotoLabel(photo) {
  return pathName(photo?.path || photo?.filename || t("gallery.photoFallback"));
}

function gallerySelectLabel(photo, selected) {
  return selected
    ? t("gallery.deselectPhoto", { photo: galleryPhotoLabel(photo) })
    : t("gallery.selectPhoto", { photo: galleryPhotoLabel(photo) });
}

function galleryQuickActionLabel(photo, status) {
  const key = status === "pick" ? "gallery.markPick" : status === "reject" ? "gallery.markReject" : "gallery.markHold";
  return t(key, { photo: galleryPhotoLabel(photo) });
}

function colorLabelDot(value, className = "") {
  const meta = colorLabelMeta(value);
  if (!meta.value) return "";
  return `<i class="manual-color-dot is-${escapeHtml(meta.value)} ${className}" aria-label="${escapeHtml(meta.label)}"></i>`;
}

function manualBadgeMarkup(manual, compact = false) {
  const rating = Number(manual?.rating || 0);
  const status = manual?.status || "";
  const colorLabel = manual?.colorLabel || "";
  if (!rating && !status && !colorLabel) return "";
  const baseLabel = status ? manualStatusLabel(status) : rating ? t("manual.ratingStars", { count: rating }) : colorLabelMeta(colorLabel).label;
  const label = manualStatusBadgeLabel(status, baseLabel);
  const stars = rating ? manualStars(rating) : "";
  const badgeIcon = manualStatus.statusIcon(status);
  const badgeClasses = [
    "manual-badge",
    manualStatusClass(status),
    compact ? "is-compact" : "",
    status ? "has-status" : "",
    colorLabel ? "has-color" : "",
    rating ? "has-rating" : "",
  ].filter(Boolean).join(" ");
  return `
    <span class="${badgeClasses}">
      ${badgeIcon ? iconMarkup(badgeIcon, "badge-icon") : ""}
      ${colorLabelDot(colorLabel)}
      <span>${escapeHtml(label)}</span>
      ${stars && !compact ? `<strong>${stars}</strong>` : ""}
    </span>
  `;
}

function galleryColorBadgeMarkup(manual = {}) {
  const colorLabel = manual?.colorLabel || "";
  if (!colorLabel) return "";
  const meta = colorLabelMeta(colorLabel);
  const label = t("gallery.colorBadge", { color: meta.label });
  return `
    <span class="gallery-color-badge" aria-label="${escapeHtml(label)}" data-ui-tooltip="${escapeHtml(label)}">
      ${colorLabelDot(colorLabel)}
    </span>
  `;
}

const sourcePanel = window.CulviaSourcePanel.create({
  $,
  $$,
  t,
  tr,
  escapeHtml,
  iconMarkup,
  pathName,
  parentPath,
  setText,
  apiClient,
  postJson,
  errorMessage,
  showCommandNotice,
  supportedTypes,
  copyFileFolderPath: (folderPath) => copyFileFolderPath(folderPath),
  refreshSourceDependentControls: () => refreshSourceDependentControls(),
  render: () => render(),
  loadState: () => loadState(),
  syncPollTimer: () => syncPollTimer(),
  resetSelectedIndex: () => viewerPanel.resetSelectedIndex(),
  getAppState: () => appState,
  setAppState: (value) => {
    appState = value;
  },
});

const viewerPanel = window.CulviaViewerPanel.create({
  $,
  t,
  clamp,
  escapeHtml,
  textHintAttributes,
  pathName,
  setText,
  setButtonLabel,
  cullingFlow,
  viewerKeyboard,
  viewerInspector,
  manualColorLabels,
  metricLabelKeys,
  numericValue,
  manualBadgeMarkup,
  colorLabelMeta,
  colorLabelTitle,
  manualStatusLabel,
  manualStatusClass,
  localizedManualSource,
  localizedMetricText,
  localizedScoreLevel,
  copyFileFolderPath: (folderPath) => copyFileFolderPath(folderPath),
  updateManualMark: (changes, options) => updateManualMark(changes, options),
  acceptPhotoResult: (basis, scope, target) => acceptPhotoResult(basis, scope, target),
  revealPhoto: (photo) => revealPhoto(photo),
  openPhotoPreview: (photo) => openPhotoPreview(photo),
  getAppState: () => appState,
  getActiveView: () => activeView,
});

const filterPanel = window.CulviaFilterPanel.create({
  $,
  t,
  tr,
  i18n,
  escapeHtml,
  iconMarkup,
  percentValue,
  setText,
  colorLabelDot,
  colorLabelMeta,
  manualStatusLabel,
  postJson,
  errorMessage,
  showCommandNotice,
  render: () => render(),
  getAppState: () => appState,
  setAppState: (value) => {
    appState = value;
  },
  getCommandNotice: () => commandNotice,
  resetSelectedIndex: () => viewerPanel.resetSelectedIndex(),
});

function preserveSelectedPhoto(previousFileId, options = {}) {
  return viewerPanel.preserveSelectedPhoto(previousFileId, options);
}

function selectedPhoto() {
  return viewerPanel.selectedPhoto();
}

function renderViewer() {
  return viewerPanel.render();
}

function renderFilterScope() {
  return filterPanel.renderScope();
}

async function flushFilterUpdate() {
  return filterPanel.flushUpdate();
}

async function applyFilterUpdate() {
  return filterPanel.applyUpdate();
}

async function setNetworkMode(mode, sync = true) {
  if (sync && appState?.job?.running) return;
  networkMode = mode === "system" ? "system" : "direct";
  $$("[data-network]").forEach((button) => button.classList.toggle("is-active", button.dataset.network === networkMode));
  if (sync) {
    const sourceSnapshot = sourceInputSnapshot();
    appState = await postJson("/api/network", { mode: networkMode });
    applySourceInputSnapshot(sourceSnapshot);
    render();
  }
}

async function updateSelectedModels() {
  if (appState?.job?.running) {
    renderModelOptions();
    return;
  }
  const sourceSnapshot = sourceInputSnapshot();
  const selected = $$("#modelOptions [data-model-key]:checked").map((input) => input.dataset.modelKey);
  if (!selected.length) {
    await loadState();
    applySourceInputSnapshot(sourceSnapshot);
    render();
    return;
  }
  appState = await postJson("/api/models", { selected });
  applySourceInputSnapshot(sourceSnapshot);
  render();
}

function renderModel(model) {
  const dot = $("#modelDot");
  dot.className = `dot ${model.tone || ""}`.trim();
  const modelLabelText = resolveTextRef(model.labelText, "");
  if (modelLabelText) $("#modelLabel")?.removeAttribute("data-i18n");
  setText("#modelLabel", modelLabelText || t("topbar.modelStatus"));
  const modelReady = model.downloaded ? t("model.ready") : model.tone === "partial" ? t("model.preparing") : t("model.pending");
  const deviceText =
    resolveTextRef(model.runtimeDeviceText, "") || resolveTextRef(appState?.app?.deviceText, "") || t("common.currentDevice");
  const runtimeState = model.runtimeLoaded
    ? t("model.runtimeLoaded", { device: deviceText })
    : model.downloaded
      ? t("model.filesReady")
      : t("model.firstUse");
  const selectedOptions = (model.options || []).filter((option) => option.selected);
  const rows = [
    [t("model.components"), localizedListJoin(selectedOptions.map((option) => localizedModelOptionLabel(option))) || t("model.defaultCombo")],
    [t("model.status"), runtimeState],
    [t("model.coreAesthetic"), model.size || t("common.unknown")],
    [t("model.clipReference"), model.clipSize || t("common.unknown")],
    [t("model.device"), deviceText],
    [t("model.fileConnection"), displayNetworkLabel(model.proxyLabelText)],
  ];
  $("#modelTooltip").innerHTML = `
    <div class="model-tooltip-head">
      <div>
        <div class="model-tooltip-title">${escapeHtml(t("model.tooltipTitle"))}</div>
        <div class="model-tooltip-subtitle">${escapeHtml(t("model.tooltipSubtitle"))}</div>
      </div>
      <span class="model-tooltip-badge">${escapeHtml(modelReady)}</span>
    </div>
    <div class="model-tooltip-list">
      ${rows
        .map(
          ([label, value]) => `
            <div class="model-tooltip-row">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderModelOptions() {
  const container = $("#modelOptions");
  if (!container || !appState?.model?.options) return;
  const running = Boolean(appState.job?.running);
  const iconByKey = {
    rsinema_aesthetic: "sparkle",
    clip_iqa: "gauge",
    clip_aesthetic: "aperture",
    basic_technical: "cpu",
    llm_review: "brain",
  };
  container.innerHTML = appState.model.options
    .map((option) => {
      const label = localizedModelOptionLabel(option);
      const subtitle = localizedModelOptionSubtitle(option);
      const state = localizedModelOptionState(option);
      const disabled = running || option.disabled;
      const optionHint = `${label} · ${subtitle}`;
      return `
        <label class="model-option ${option.selected ? "is-selected" : ""} ${option.disabled ? "is-disabled" : ""}" data-model-option="${escapeHtml(option.key)}" aria-label="${escapeHtml(optionHint)}">
          <input
            type="checkbox"
            data-model-key="${escapeHtml(option.key)}"
            ${option.selected ? "checked" : ""}
            ${disabled ? "disabled" : ""}
          />
          <span class="model-option-icon">${iconMarkup(iconByKey[option.key] || "aperture")}</span>
          <span class="model-option-copy">
            <strong>${escapeHtml(label)}</strong>
            <small>${escapeHtml(subtitle)}</small>
          </span>
          <span class="model-option-side">
            <span class="model-option-state">${escapeHtml(state)}</span>
            <span class="model-option-toggle" aria-hidden="true"></span>
          </span>
        </label>
      `;
    })
    .join("");
  container.querySelectorAll("[data-model-key]").forEach((input) => {
    input.addEventListener("change", updateSelectedModels);
  });
}

const llmConfigPanel = window.CulviaLlmConfigPanel.create({
  $,
  t,
  setText,
  setTextWithHint,
  setButtonLabel,
  iconMarkup,
  llmConfigView,
  postJson,
  errorMessage,
  showCommandNotice,
  requestDangerConfirm: (options) => requestDangerConfirm(options),
  render: () => render(),
  getAppState: () => appState,
  setAppState: (value) => {
    appState = value;
  },
});

function selectedLlmModel() {
  return llmConfigPanel.selectedLlmModel();
}

function renderLlmConfig() {
  return llmConfigPanel.renderLlmConfig();
}

function loadLlmModels(options = {}) {
  return llmConfigPanel.loadLlmModels(options);
}

function toggleLlmModelMenu() {
  return llmConfigPanel.toggleLlmModelMenu();
}

function handleLlmModelSearchInput(event) {
  return llmConfigPanel.handleLlmModelSearchInput(event);
}

function handleLlmModelSearchKeydown(event) {
  return llmConfigPanel.handleLlmModelSearchKeydown(event);
}

function handleLlmModelDocumentClick(event) {
  return llmConfigPanel.handleLlmModelDocumentClick(event);
}

function openLlmConfigEditor() {
  return llmConfigPanel.openLlmConfigEditor();
}

function cancelLlmConfigEdit() {
  return llmConfigPanel.cancelLlmConfigEdit();
}

function resetLlmModelCatalogForConnectionChange() {
  return llmConfigPanel.resetLlmModelCatalogForConnectionChange();
}

function saveLlmConfig() {
  return llmConfigPanel.saveLlmConfig();
}

function clearLlmKey() {
  return llmConfigPanel.clearLlmKey();
}

function setButtonLabel(button, icon, label) {
  if (!button) return;
  const labelKey = button.dataset.i18nLabel || "";
  const resolvedLabel = labelKey ? t(labelKey) : label;
  const labelMarkup = labelKey
    ? `<span data-i18n="${escapeHtml(labelKey)}">${escapeHtml(resolvedLabel)}</span>`
    : escapeHtml(resolvedLabel);
  button.innerHTML = `${iconMarkup(icon)}${labelMarkup}`;
  button.setAttribute("aria-label", resolvedLabel);
  button.dataset.uiTooltip = resolvedLabel;
  button.removeAttribute("title");
}

function showCommandNotice(notice, duration = 2400) {
  window.clearTimeout(commandNoticeTimer);
  commandNotice = notice;
  render();
  if (duration > 0) {
    commandNoticeTimer = window.setTimeout(() => {
      commandNotice = null;
      render();
    }, duration);
  }
}

function applyCommandButtonPlan(buttonPlan) {
  const button = $(buttonPlan.selector);
  if (!button) return;
  if ("hidden" in buttonPlan) button.classList.toggle("is-hidden", buttonPlan.hidden);
  setButtonLabel(button, buttonPlan.icon, buttonPlan.label);
  button.disabled = buttonPlan.disabled;
}

function applyCommandDomPlan(plan) {
  const commandCenter = $(plan.center.selector);
  if (!commandCenter) return false;
  commandCenter.classList.toggle("is-running", plan.center.running);
  commandCenter.classList.toggle("is-compact", plan.center.compact);
  $(plan.dot.selector).className = plan.dot.className;
  plan.texts.forEach((item) => setText(item.selector, item.text));

  const commandProgress = $(plan.progress.selector);
  commandProgress.classList.toggle("is-hidden", plan.progress.hidden);
  if (!plan.progress.hidden) {
    setText(plan.progress.labelSelector, plan.progress.label);
    setText(plan.progress.detailSelector, plan.progress.detail);
    $(plan.progress.barSelector).style.width = plan.progress.width;
  }

  const currentPhoto = $(plan.currentPhoto.selector);
  currentPhoto.classList.toggle("is-hidden", plan.currentPhoto.hidden);
  if (plan.currentPhoto.hidden) {
    $(plan.currentPhoto.thumbSelector).removeAttribute("src");
    setText(plan.currentPhoto.fileSelector, "");
    setText(plan.currentPhoto.stageSelector, "");
    $(plan.currentPhoto.completedSelector).innerHTML = "";
  } else {
    $(plan.currentPhoto.thumbSelector).src = plan.currentPhoto.thumb;
    setText(plan.currentPhoto.fileSelector, plan.currentPhoto.file);
    setText(plan.currentPhoto.stageSelector, plan.currentPhoto.stage);
    const completed = plan.currentPhoto.completed;
    $(plan.currentPhoto.completedSelector).innerHTML = completed.length
      ? completed.map((item) => `<span>${escapeHtml(item)}</span>`).join("")
      : `<span class="is-pending">${escapeHtml(plan.currentPhoto.emptyText)}</span>`;
  }

  applyCommandButtonPlan(plan.buttons.mainScore);
  applyCommandButtonPlan(plan.buttons.noticeAction);
  applyCommandButtonPlan(plan.buttons.pause);
  applyCommandButtonPlan(plan.buttons.cancel);
  return true;
}

function renderCommand(model, job, summary) {
  const sourceReady = hasSelectedSource();
  const hasResults = (summary?.scored || 0) > 0 || (appState?.photos || []).length > 0;
  const viewState = commandView.commandViewState({
    commandNotice,
    hasResults,
    job,
    model,
    networkText: displayNetworkLabel(model?.proxyLabelText),
    sourceReady,
    summary,
    llmConfigured: Boolean(appState?.llm?.configured),
  });
  applyCommandDomPlan(commandView.commandDomPlan(viewState));
}

function refreshSourceDependentControls() {
  if (!appState) return;
  renderCommand(appState.model, appState.job, appState.summary);
  renderProgress(appState.job);
}

function renderProgress(job) {
  const running = Boolean(job?.running);
  const scoring = isScoringJob(job);
  const modelBox = $("#modelProgress");
  modelBox?.classList.add("is-hidden");

  const jobBox = $("#jobProgress");
  jobBox?.classList.add("is-hidden");

  $("#mainScoreBtn").disabled = running || Boolean(commandNotice?.loading) || !hasSelectedSource();
  $("#llmReviewBtn").disabled =
    running || Boolean(commandNotice?.loading) || !hasSelectedSource() || !appState?.llm?.configured;
  $("#clearLocalDataBtn").disabled = running || Boolean(commandNotice?.loading);
  $("#clearHistoryBtn").disabled = running || Boolean(commandNotice?.loading);
  $("#clearModelBtn").disabled = running || Boolean(commandNotice?.loading);
  $("#pauseJobBtn").disabled = !scoring || Boolean(commandNotice?.loading);
  $("#cancelJobBtn").disabled =
    !isCancellableJob(job) || appState.job?.phase === "cancelling" || Boolean(commandNotice?.loading);
  $("#editLlmConfigBtn").disabled = running || Boolean(commandNotice?.loading);
  $("#cancelLlmConfigBtn").disabled = running || Boolean(commandNotice?.loading);
  $("#saveLlmConfigBtn").disabled = running || Boolean(commandNotice?.loading);
  $("#clearLlmKeyBtn").disabled = running || Boolean(commandNotice?.loading) || !appState?.llm?.configured;
  $("#refreshLlmModelsBtn").disabled = running || llmConfigPanel.llmModelsLoading();
}

function renderStats(summary) {
  setText("#statScored", summary.scored ?? 0);
  setText("#statShowing", summary.showing ?? 0);
  setStatValue("#statBest", summary.best);
  setStatValue("#statAverage", summary.average);
}

function setStatValue(selector, value) {
  const el = $(selector);
  if (!el) return;
  el.textContent = value || t("stats.empty");
  el.classList.toggle("is-empty", !value);
  // applyI18n() would otherwise overwrite real values with the empty placeholder.
  if (value) el.removeAttribute("data-i18n");
  else el.setAttribute("data-i18n", "stats.empty");
}

function historyActionLabel(kind) {
  return localizedHistoryKind(kind);
}

function historyUndoStateMeta(state) {
  return (
    {
      available: { label: t("history.undo.available"), tone: "available" },
      undone: { label: t("history.undo.undone"), tone: "muted" },
      undo: { label: t("history.undo.undo"), tone: "undo" },
      unavailable: { label: t("history.undo.unavailable"), tone: "muted" },
    }[state] || { label: t("history.undo.unavailable"), tone: "muted" }
  );
}

function historyTimeText(createdAt) {
  const timestamp = Number(createdAt || 0) * 1000;
  if (!timestamp) return "";
  const diffSeconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (diffSeconds < 60) return t("history.time.justNow");
  if (diffSeconds < 3600) return t("history.time.minutesAgo", { count: Math.round(diffSeconds / 60) });
  if (diffSeconds < 86400) return t("history.time.hoursAgo", { count: Math.round(diffSeconds / 3600) });
  return new Date(timestamp).toLocaleString(i18n?.language?.() === "en" ? "en-US" : "zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderCurationHistory() {
  const list = $("#curationHistoryList");
  if (!list) return;
  if (curationHistoryLoading) {
    list.innerHTML = `<div class="curation-history-empty">${escapeHtml(t("history.loading"))}</div>`;
    return;
  }
  if (curationHistoryError) {
    list.innerHTML = `<div class="curation-history-empty is-error">${escapeHtml(curationHistoryError)}</div>`;
    return;
  }
  if (!curationHistory.length) {
    list.innerHTML = `<div class="curation-history-empty">${escapeHtml(t("history.empty"))}</div>`;
    return;
  }
  list.innerHTML = curationHistory
    .map((record) => {
      const kind = historyActionLabel(record.kind);
      const timeText = historyTimeText(record.createdAt);
      const undoState = historyUndoStateMeta(record.undoState);
      const summary = localizedHistorySummary(record, kind);
      const scopeLabel = localizedHistoryScope(record.scope);
      return `
        <article class="curation-history-item">
          <span class="curation-history-kind">${escapeHtml(kind)}</span>
          <div>
            <strong>${escapeHtml(summary || kind)}</strong>
            <small>${escapeHtml([scopeLabel, timeText].filter(Boolean).join(" · "))}</small>
          </div>
          <span class="curation-history-state is-${escapeHtml(undoState.tone)}">${escapeHtml(undoState.label)}</span>
        </article>
      `;
    })
    .join("");
}

const galleryPanel = window.CulviaGalleryPanel.create({
  $,
  $$,
  t,
  setText,
  escapeHtml,
  pathName,
  i18n,
  galleryView,
  galleryKeyboard,
  cullingFlow,
  manualStars,
  localizedManualSource,
  localizedMetricText,
  localizedScoreLevel,
  localizedTechnicalTag,
  manualStatusLabel,
  galleryColorBadgeMarkup,
  galleryQuickActionLabel,
  gallerySelectLabel,
  isSourcePreviewActive,
  matchingSourcePreview,
  updatePhotoMark: (fileId, changes, options) => updatePhotoMark(fileId, changes, options),
  statusToggleChanges: (changes, currentStatus) => statusToggleChanges(changes, currentStatus),
  openBatchStatusConfirm: (status) => openBatchStatusConfirm(status),
  switchView: (view) => switchView(view),
  renderViewer: () => renderViewer(),
  getAppState: () => appState,
  getActiveView: () => activeView,
  getSourceMode: () => sourcePanel.mode(),
  setSelectedIndex: (index) => viewerPanel.setSelectedIndex(index),
});

function visibleGallerySelection(photos = appState?.photos || []) {
  return galleryPanel.visibleGallerySelection(photos);
}

function galleryBatchTarget(photos = appState?.photos || []) {
  return galleryPanel.galleryBatchTarget(photos);
}

function renderBatchScopePill(rootSelector, labelSelector, target) {
  return galleryPanel.renderBatchScopePill(rootSelector, labelSelector, target);
}

function clearGallerySelection() {
  return galleryPanel.clearGallerySelection();
}

function selectVisibleGalleryPhotos() {
  return galleryPanel.selectVisibleGalleryPhotos();
}

function beginGalleryMarquee(event) {
  return galleryPanel.beginGalleryMarquee(event);
}

function renderGallery() {
  return galleryPanel.renderGallery();
}

function handleGalleryImageLoad(event) {
  return galleryPanel.handleGalleryImageLoad(event);
}

function handleGalleryImageError(event) {
  return galleryPanel.handleGalleryImageError(event);
}

function handleGalleryGridClick(event) {
  return galleryPanel.handleGalleryGridClick(event);
}

function handleGalleryTooltipIntent(event) {
  return galleryPanel.handleGalleryTooltipIntent(event);
}

function clearGalleryTooltipPlacement(event) {
  return galleryPanel.clearGalleryTooltipPlacement(event);
}

function handleGalleryShortcut(event) {
  return galleryPanel.handleGalleryShortcut(event);
}

const distributionPanel = window.CulviaDistributionPanel.create({
  $,
  t,
  tr,
  escapeHtml,
  iconMarkup,
  scoreValue,
  pathName,
  photos: () => appState?.photos || [],
  switchView: (view) => switchView(view),
  openViewerAt: (index) => {
    viewerPanel.setSelectedIndex(index);
    switchView("viewer");
    renderViewer();
  },
  distributionLensOptions,
  distributionStats,
  distributionTier,
  scoreBuckets,
  bucketWave,
  distributionDecision,
  distributionEntries,
  distributionLensConfig,
  distributionLensMeta,
  distributionTierMeta,
  renderDimensionStack,
  renderMetricRadar,
});

function renderDistribution() {
  distributionPanel.render();
}

const exportPanel = window.CulviaExportPanel.create({
  $,
  t,
  clamp,
  escapeHtml,
  iconMarkup,
  parentPath,
  pathName,
  setText,
  setTextWithHint,
  setButtonLabel,
  localizedScoreLevel,
  manualBadgeMarkup,
  colorLabelMeta,
  manualColorLabels,
  numericValue,
  clipboard,
  postJson,
  errorMessage,
  showCommandNotice,
  revealPhoto: (photo) => revealPhoto(photo),
  applyBatchColor: (colorLabel, target) => applyBatchColor(colorLabel, target),
  galleryBatchTarget: (photos) => galleryBatchTarget(photos),
  renderBatchScopePill: (rootSelector, labelSelector, target) => renderBatchScopePill(rootSelector, labelSelector, target),
  getAppState: () => appState,
  getActiveView: () => activeView,
});

function renderExportList() {
  return exportPanel.renderExportList();
}

function pickExportFolder() {
  return exportPanel.pickExportFolder();
}

function refreshExportPreflight(options = {}) {
  return exportPanel.refreshExportPreflight(options);
}

function exportSelectedPhotos() {
  return exportPanel.exportSelectedPhotos();
}

function handleExportResultClick(event) {
  return exportPanel.handleExportResultClick(event);
}

function handleExportPreflightClick(event) {
  return exportPanel.handleExportPreflightClick(event);
}

function renderControls() {
  if (!appState) return;
  $("#devicePill").innerHTML = `${iconMarkup("cpu")}${escapeHtml(appState.app.device)}`;
  sourcePanel.renderControls();
  renderLlmConfig();
  filterPanel.renderControls();
  setNetworkMode(appState.network?.mode || "direct", false);
  renderModelOptions();
}

function render() {
  if (!appState) return;
  applyWorkbenchMode();
  applySidebarMode();
  applyActiveViewState();
  renderControls();
  renderModel(appState.model);
  renderCommand(appState.model, appState.job, appState.summary);
  renderProgress(appState.job);
  renderStats(appState.summary);
  renderFilterScope();
  renderCurationHistory();
  renderActiveView();
  applyI18n();
}

function applyWorkbenchMode() {
  const shell = $(".app-shell");
  if (!shell) return;
  const hasResults = (appState?.summary?.scored || 0) > 0 || (appState?.photos || []).length > 0;
  shell.classList.toggle("has-results", hasResults);
  shell.classList.toggle("is-job-running", Boolean(appState?.job?.running));
}

function renderActiveView() {
  if (!appState) return;
  if (activeView === "gallery") {
    renderGallery();
    return;
  }
  if (activeView === "distribution") {
    renderDistribution();
    return;
  }
  if (activeView === "export") {
    renderExportList();
    return;
  }
  renderViewer();
}

function applySidebarMode() {
  $(".app-shell")?.classList.toggle("is-focus-mode", sidebarCollapsed);
  const button = $("#sidebarToggleBtn");
  if (!button) return;
  const label = sidebarCollapsed ? t("app.expandSidebar") : t("app.collapseSidebar");
  const tooltip = sidebarCollapsed ? t("app.expandSettings") : t("app.focusMode");
  button.setAttribute("aria-pressed", sidebarCollapsed ? "true" : "false");
  button.setAttribute("aria-label", label);
  button.dataset.uiTooltip = tooltip;
  button.removeAttribute("title");
}

function toggleSidebarMode() {
  sidebarCollapsed = !sidebarCollapsed;
  localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? "true" : "false");
  applySidebarMode();
}

function applySettingsDrawerState() {
  const drawer = $("#settingsDrawer");
  const scrim = $("#settingsScrim");
  const trigger = $("#openSettingsDrawerBtn");
  drawer?.classList.toggle("is-hidden", !settingsDrawerOpen);
  scrim?.classList.toggle("is-hidden", !settingsDrawerOpen);
  drawer?.setAttribute("aria-hidden", settingsDrawerOpen ? "false" : "true");
  trigger?.setAttribute("aria-expanded", settingsDrawerOpen ? "true" : "false");
  document.body.classList.toggle("is-settings-drawer-open", settingsDrawerOpen);
}

function openSettingsDrawer() {
  settingsDrawerOpen = true;
  applySettingsDrawerState();
  loadCurationHistory();
  window.setTimeout(() => $("#closeSettingsDrawerBtn")?.focus(), 0);
}

function closeSettingsDrawer() {
  if (!settingsDrawerOpen) return;
  settingsDrawerOpen = false;
  llmConfigPanel.setLlmModelMenuOpen(false);
  applySettingsDrawerState();
  $("#openSettingsDrawerBtn")?.focus();
}

function shortcutCatalog() {
  const catalog = window.CulviaShortcuts?.catalog;
  return Array.isArray(catalog) ? catalog : [];
}

function shortcutKeyHtml(keys) {
  return (Array.isArray(keys) ? keys : [])
    .map((key) => `<kbd>${escapeHtml(key)}</kbd>`)
    .join("");
}

function renderShortcutHelp() {
  const list = $("#shortcutHelpList");
  if (!list) return;
  const catalog = shortcutCatalog();
  list.innerHTML = catalog.length
    ? catalog
        .map(
          (group) => `
            <article class="shortcut-group">
              <h3>${escapeHtml(group.groupKey ? t(group.groupKey) : t("shortcuts.title"))}</h3>
              <div class="shortcut-items">
                ${(Array.isArray(group.items) ? group.items : [])
                  .map(
                    (item) => `
                      <div class="shortcut-item">
                        <span>${escapeHtml(item.actionKey ? t(item.actionKey) : "")}</span>
                        <div class="shortcut-keys">${shortcutKeyHtml(item.keys)}</div>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </article>
          `,
        )
        .join("")
    : `<div class="shortcut-empty">${escapeHtml(t("shortcuts.empty"))}</div>`;
}

function applyShortcutHelpState() {
  const dialog = $("#shortcutHelpDialog");
  const scrim = $("#shortcutHelpScrim");
  const trigger = $("#openShortcutHelpBtn");
  dialog?.classList.toggle("is-hidden", !shortcutHelpOpen);
  scrim?.classList.toggle("is-hidden", !shortcutHelpOpen);
  dialog?.setAttribute("aria-hidden", shortcutHelpOpen ? "false" : "true");
  trigger?.setAttribute("aria-expanded", shortcutHelpOpen ? "true" : "false");
  document.body.classList.toggle("is-shortcut-help-open", shortcutHelpOpen);
}

function openShortcutHelp() {
  shortcutHelpOpen = true;
  renderShortcutHelp();
  applyShortcutHelpState();
  window.setTimeout(() => $("#closeShortcutHelpBtn")?.focus(), 0);
}

function closeShortcutHelp() {
  if (!shortcutHelpOpen) return;
  shortcutHelpOpen = false;
  applyShortcutHelpState();
  $("#openShortcutHelpBtn")?.focus();
}

async function loadCurationHistory() {
  curationHistoryLoading = true;
  curationHistoryError = "";
  renderCurationHistory();
  try {
    const payload = await getJson("/api/curation/history?limit=8");
    curationHistory = Array.isArray(payload.actions) ? payload.actions : [];
  } catch (error) {
    curationHistory = [];
    curationHistoryError = t("history.error");
  } finally {
    curationHistoryLoading = false;
    renderCurationHistory();
  }
}

function refreshCurationHistoryIfOpen() {
  if (settingsDrawerOpen) {
    void loadCurationHistory();
  }
}

async function loadState() {
  const sourceSnapshot = sourcePanel.dirty() ? sourceInputSnapshot() : null;
  appState = await getJson("/api/state");
  await filterPanel.restoreSavedFiltersIfNeeded();
  if (sourceSnapshot) applySourceInputSnapshot(sourceSnapshot);
  filterPanel.persistCurrentFilters();
  viewerPanel.ensureSelectedIndex();
  render();
  sourcePanel.resumePendingPreviewIfReady();
  syncPollTimer();
}

function syncPollTimer() {
  if (appState?.job?.running && !pollTimer) {
    pollTimer = window.setInterval(loadState, 800);
    return;
  }
  if (!appState?.job?.running && pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

function selectedScoringModels() {
  return $$("#modelOptions [data-model-key]:checked").map((input) => input.dataset.modelKey);
}

function buildScoringPayload(selectedModels = selectedScoringModels()) {
  return {
    ...sourcePanel.buildScoringPayload(selectedModels),
    networkMode,
  };
}

function scoringNeedsLlmConfirmation(payload) {
  return Boolean(
    !llmReviewConfirmedForSession &&
      appState?.llm?.configured &&
      (payload?.selectedModels || []).includes("llm_review"),
  );
}

function applyLlmConfirmState() {
  $("#llmConfirmDialog")?.classList.toggle("is-hidden", !llmConfirmOpen);
  $("#llmConfirmScrim")?.classList.toggle("is-hidden", !llmConfirmOpen);
  $("#llmConfirmDialog")?.setAttribute("aria-hidden", llmConfirmOpen ? "false" : "true");
  document.body.classList.toggle("is-llm-confirm-open", llmConfirmOpen);
}

function openLlmConfirm(payload) {
  pendingScoringPayload = payload;
  llmConfirmOpen = true;
  setTextWithHint("#llmConfirmModel", appState?.llm?.model || t("llmConfirm.currentModel"));
  setTextWithHint("#llmConfirmEndpoint", appState?.llm?.endpoint || appState?.llm?.baseUrl || t("llmConfirm.currentEndpoint"));
  applyLlmConfirmState();
  window.setTimeout(() => $("#confirmLlmScoreBtn")?.focus(), 0);
}

function closeLlmConfirm({ restoreFocus = true } = {}) {
  if (!llmConfirmOpen) return;
  llmConfirmOpen = false;
  pendingScoringPayload = null;
  applyLlmConfirmState();
  if (restoreFocus) $("#mainScoreBtn")?.focus();
}

async function submitScoringPayload(payload) {
  sourcePanel.stopPreview();
  commandNotice = null;
  window.clearTimeout(commandNoticeTimer);
  await postJson("/api/score", payload);
  sourcePanel.markClean();
  await loadState();
}

async function startLlmReview() {
  if (!appState || appState.job?.running || !appState?.llm?.configured) return;
  const payload = buildScoringPayload(["llm_review"]);
  sourcePanel.stopPreview();
  commandNotice = null;
  window.clearTimeout(commandNoticeTimer);
  await postJson("/api/llm-review", payload);
  sourcePanel.markClean();
  await loadState();
}

async function startScoring() {
  if (!appState || appState.job?.running) return;
  const payload = buildScoringPayload();
  if (scoringNeedsLlmConfirmation(payload)) {
    openLlmConfirm(payload);
    return;
  }
  await submitScoringPayload(payload);
}

async function confirmLlmScoring() {
  if (!pendingScoringPayload || appState?.job?.running) return;
  const payload = pendingScoringPayload;
  llmReviewConfirmedForSession = true;
  closeLlmConfirm({ restoreFocus: false });
  await submitScoringPayload(payload);
}

async function startLocalOnlyScoring() {
  if (!pendingScoringPayload || appState?.job?.running) return;
  const localPayload = {
    ...pendingScoringPayload,
    selectedModels: (pendingScoringPayload.selectedModels || []).filter((modelKey) => modelKey !== "llm_review"),
  };
  closeLlmConfirm({ restoreFocus: false });
  await submitScoringPayload(localPayload);
}

function applyDangerConfirmState() {
  $("#dangerConfirmDialog")?.classList.toggle("is-hidden", !dangerConfirmOpen);
  $("#dangerConfirmScrim")?.classList.toggle("is-hidden", !dangerConfirmOpen);
  $("#dangerConfirmDialog")?.setAttribute("aria-hidden", dangerConfirmOpen ? "false" : "true");
  $("#dangerConfirmScrim")?.setAttribute("aria-hidden", dangerConfirmOpen ? "false" : "true");
  document.body.classList.toggle("is-danger-confirm-open", dangerConfirmOpen);
}

function requestDangerConfirm(options = {}) {
  dangerConfirmReturnElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  return new Promise((resolve) => {
    pendingDangerConfirm = {
      confirmIcon: options.confirmIcon || "trash",
      confirmLabel: options.confirmLabel || t("dangerConfirm.confirm"),
      detail: options.detail || t("dangerConfirm.detail"),
      resolve,
      title: options.title || t("dangerConfirm.title"),
    };
    dangerConfirmOpen = true;
    setText("#dangerConfirmTitle", pendingDangerConfirm.title);
    setTextWithHint("#dangerConfirmDetail", pendingDangerConfirm.detail);
    setButtonLabel($("#confirmDangerActionBtn"), pendingDangerConfirm.confirmIcon, pendingDangerConfirm.confirmLabel);
    applyDangerConfirmState();
    window.setTimeout(() => $("#confirmDangerActionBtn")?.focus(), 0);
  });
}

function closeDangerConfirm({ confirmed = false, restoreFocus = true } = {}) {
  if (!dangerConfirmOpen && !pendingDangerConfirm) return;
  const pending = pendingDangerConfirm;
  dangerConfirmOpen = false;
  pendingDangerConfirm = null;
  applyDangerConfirmState();
  if (pending && !confirmed) pending.resolve(false);
  if (restoreFocus) {
    const target = dangerConfirmReturnElement;
    dangerConfirmReturnElement = null;
    if (target?.isConnected) target.focus();
  } else {
    dangerConfirmReturnElement = null;
  }
}

function confirmDangerAction() {
  const pending = pendingDangerConfirm;
  if (!pending) return;
  closeDangerConfirm({ confirmed: true, restoreFocus: false });
  pending.resolve(true);
}

async function toggleJobPause() {
  if (!appState?.job?.running) return;
  const paused = Boolean(appState.job.paused) || appState.job.phase === "paused" || appState.job.phase === "pausing";
  try {
    appState = await postJson(paused ? "/api/job/resume" : "/api/job/pause", {});
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: paused ? t("command.resumeFailedState") : t("command.pauseFailedState"),
        title: paused ? t("command.resumeFailedTitle") : t("command.pauseFailedTitle"),
        detail: errorMessage(error),
      },
      3600,
    );
  }
}

async function cancelJob() {
  if (!isCancellableJob(appState?.job) || appState.job.phase === "cancelling") return;
  try {
    appState = await postJson("/api/job/cancel", {});
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("command.cancelFailedState"),
        title: t("command.cancelFailedTitle"),
        detail: errorMessage(error),
      },
      3600,
    );
  }
}

async function clearHistoryCache() {
  if (!appState || appState.job?.running) return;
  const cachePath = sourcePanel.cachePath();
  const ok = await requestDangerConfirm({
    confirmIcon: "trash",
    confirmLabel: t("maintenance.clearScores"),
    detail: t("maintenance.clearScoresConfirm"),
    title: t("maintenance.clearScoresConfirmTitle"),
  });
  if (!ok) return;
  try {
    appState = await postJson("/api/cache/clear", { cachePath });
    curationHistory = [];
    curationHistoryError = "";
    viewerPanel.resetSelectedIndex();
    showCommandNotice({
      tone: "ready",
      state: t("maintenance.clearScoresState"),
      title: t("maintenance.clearScoresTitle"),
      detail: t("maintenance.clearScoresDetail"),
    });
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("maintenance.clearScoresFailureState"),
        title: t("maintenance.clearScoresFailureTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  }
}

async function clearLocalData() {
  if (!appState || appState.job?.running) return;
  const cachePath = sourcePanel.cachePath();
  const ok = await requestDangerConfirm({
    confirmIcon: "trash",
    confirmLabel: t("maintenance.clearLocalData"),
    detail: t("maintenance.clearLocalDataConfirm"),
    title: t("maintenance.clearLocalDataConfirmTitle"),
  });
  if (!ok) return;
  try {
    appState = await postJson("/api/data/clear", { cachePath });
    curationHistory = [];
    curationHistoryError = "";
    galleryPanel.selectedGalleryIds().clear();
    galleryPanel.setGallerySelectionAnchorId("");
    viewerPanel.resetSelectedIndex();
    llmConfigPanel.setLlmModelOptions([]);
    llmConfigPanel.setLlmModelListMessage("");
    llmConfigPanel.setLlmSelectedModel(appState?.llm?.model || "");
    llmConfigPanel.setLlmConfigEditing(false);
    llmConfigPanel.setLlmModelMenuOpen(false);
    sourcePanel.markClean();
    showCommandNotice({
      tone: "ready",
      state: t("maintenance.clearLocalDataState"),
      title: t("maintenance.clearLocalDataTitle"),
      detail: t("maintenance.clearLocalDataDetail"),
    });
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("maintenance.clearLocalDataFailureState"),
        title: t("maintenance.clearLocalDataFailureTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  }
}

async function clearModelCache() {
  if (!appState || appState.job?.running) return;
  const ok = await requestDangerConfirm({
    confirmIcon: "archive",
    confirmLabel: t("maintenance.removeModels"),
    detail: t("maintenance.removeModelsConfirm"),
    title: t("maintenance.removeModelsConfirmTitle"),
  });
  if (!ok) return;
  try {
    appState = await postJson("/api/model/clear", {});
    showCommandNotice({
      tone: "partial",
      state: t("maintenance.removeModelsState"),
      title: t("maintenance.removeModelsTitle"),
      detail: t("maintenance.removeModelsDetail"),
    });
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("maintenance.removeModelsFailureState"),
        title: t("maintenance.removeModelsFailureTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  }
}

function applyActiveViewState() {
  const nextView = normalizeViewName(activeView);
  activeView = nextView;
  $$(".view-tab").forEach((button) => {
    const selected = button.dataset.view === nextView;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  $$(".view-panel").forEach((panel) => panel.classList.remove("is-active"));
  $(`#${nextView}View`)?.classList.add("is-active");
}

function switchView(view) {
  activeView = normalizeViewName(view);
  persistActiveView(activeView);
  applyActiveViewState();
  renderActiveView();
}

async function openManualStatusView(status, view = "gallery") {
  if (appState?.job?.running) return;
  filterPanel.setManualStatus(status);
  try {
    await applyFilterUpdate();
  } catch (_error) {
    return;
  }
  switchView(view);
}

async function performPhotoMarkUpdate(fileId, changes, options = {}) {
  if (appState?.job?.running) return;
  const photo = (appState?.photos || []).find((item) => item.fileId === fileId);
  if (!photo?.fileId) return;
  const previousFileId = photo.fileId;
  const previousIndex = viewerPanel.selectedIndex();
  try {
    appState = await postJson("/api/mark", {
      fileId: photo.fileId,
      ...changes,
    });
    preserveSelectedPhoto(previousFileId, { advance: options.advance, previousIndex });
    refreshCurationHistoryIfOpen();
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("manual.saveFailureState"),
        title: t("manual.saveFailureTitle"),
        detail: errorMessage(error),
      },
      3600,
    );
  }
}

function updatePhotoMark(fileId, changes, options = {}) {
  markUpdateQueue = markUpdateQueue.catch(() => undefined).then(() => performPhotoMarkUpdate(fileId, changes, options));
  return markUpdateQueue;
}

function statusToggleChanges(changes = {}, currentStatus = "") {
  if (!Object.prototype.hasOwnProperty.call(changes, "status")) return changes;
  return {
    ...changes,
    status: manualStatus.toggledStatus(currentStatus, changes.status),
  };
}

function updateManualMark(changes, options = {}) {
  if (appState?.job?.running) return markUpdateQueue;
  markUpdateQueue = markUpdateQueue.catch(() => undefined).then(() => {
    const photo = selectedPhoto();
    if (!photo?.fileId) return undefined;
    return performPhotoMarkUpdate(photo.fileId, statusToggleChanges(changes, photo.manual?.status || ""), options);
  });
  return markUpdateQueue;
}

async function acceptPhotoResult(basis, scope = "current", target = {}) {
  if (appState?.job?.running) return;
  const photo = selectedPhoto();
  if (scope === "current" && !photo?.fileId) return;
  const previousFileId = photo?.fileId || "";
  const requestScope = target.scope || scope;
  const fileIds = target.fileIds || [];
  try {
    const nextState = await postJson("/api/mark/accept", {
      basis,
      scope: requestScope,
      fileIds,
      fileId: previousFileId,
    });
    appState = nextState;
    preserveSelectedPhoto(previousFileId);
    const action = nextState.action || {};
    const noticeView = CulviaBatchActions.acceptNotice({ action, basis, scope: requestScope });
    showCommandNotice({
      ...noticeView.notice,
      action: restoreNoticeAction(action, { label: t("restore.context.accept") }),
    }, noticeView.duration);
    refreshCurationHistoryIfOpen();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("manual.acceptFailureState"),
        title: t("manual.acceptFailureTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  }
}

async function applyBatchColor(colorLabel, target = galleryBatchTarget(appState?.photos || [])) {
  if (appState?.job?.running) return;
  if (!target.count) return;
  const previousFileId = selectedPhoto()?.fileId || "";
  try {
    appState = await postJson("/api/mark/color", {
      scope: target.scope,
      fileIds: target.fileIds,
      colorLabel,
    });
    preserveSelectedPhoto(previousFileId);
    visibleGallerySelection(appState.photos || []);
    const label = colorLabelMeta(colorLabel).label;
    const count = appState.action?.colored || 0;
    const noticeView = CulviaBatchActions.colorNotice({ colorLabel, colorName: label, count, target });
    showCommandNotice({
      ...noticeView,
      action: restoreNoticeAction(appState.action || {}, { label: t("restore.context.color") }),
    }, 6200);
    refreshCurationHistoryIfOpen();
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("batch.colorFailureState"),
        title: t("batch.colorFailureTitle"),
        detail: errorMessage(error),
      },
      3600,
    );
  }
}

function applyBatchStatusConfirmState() {
  $("#batchStatusConfirmDialog")?.classList.toggle("is-hidden", !batchStatusConfirmOpen);
  $("#batchStatusConfirmScrim")?.classList.toggle("is-hidden", !batchStatusConfirmOpen);
  $("#batchStatusConfirmDialog")?.setAttribute("aria-hidden", batchStatusConfirmOpen ? "false" : "true");
  $("#batchStatusConfirmScrim")?.setAttribute("aria-hidden", batchStatusConfirmOpen ? "false" : "true");
  document.body.classList.toggle("is-batch-confirm-open", batchStatusConfirmOpen);
}

async function openBatchStatusConfirm(status) {
  if (appState?.job?.running) return;
  try {
    await flushFilterUpdate();
  } catch (_error) {
    return;
  }
  const visiblePhotos = appState?.photos || [];
  const target = galleryBatchTarget(visiblePhotos);
  if (!target.count) return;
  pendingBatchStatus = status || "";
  pendingBatchTarget = target;
  batchStatusReturnSelector = CulviaBatchActions.statusTriggerSelector(pendingBatchStatus);
  batchStatusConfirmOpen = true;
  const view = CulviaBatchActions.confirmView(pendingBatchStatus, target);
  const mark = $("#batchStatusConfirmMark");
  if (mark) {
    mark.className = `batch-confirm-mark is-${view.tone}`;
    mark.innerHTML = iconMarkup(view.icon);
  }
  setText("#batchStatusConfirmTitle", view.title);
  setText("#batchStatusConfirmDetail", view.detail);
  setTextWithHint("#batchStatusConfirmScope", view.scopeText);
  setTextWithHint("#batchStatusConfirmCount", view.countText);
  setTextWithHint("#batchStatusConfirmAction", view.actionLabel);
  setButtonLabel($("#confirmBatchStatusBtn"), view.icon, view.buttonLabel);
  applyBatchStatusConfirmState();
  window.setTimeout(() => $("#confirmBatchStatusBtn")?.focus(), 0);
}

function closeBatchStatusConfirm({ restoreFocus = true } = {}) {
  if (!batchStatusConfirmOpen) return;
  batchStatusConfirmOpen = false;
  pendingBatchStatus = "";
  pendingBatchTarget = CulviaBatchActions.emptyTarget();
  applyBatchStatusConfirmState();
  if (restoreFocus) $(batchStatusReturnSelector)?.focus();
}

async function confirmBatchStatus() {
  if (appState?.job?.running) return;
  const status = pendingBatchStatus;
  const target = pendingBatchTarget;
  closeBatchStatusConfirm({ restoreFocus: false });
  await applyBatchStatus(status, target);
}

async function restoreBatchMarks(actionOrMarks) {
  if (appState?.job?.running) return;
  const restoreAction = Array.isArray(actionOrMarks) ? { marks: actionOrMarks } : actionOrMarks || {};
  const marks = restoreAction.marks || [];
  const historyId = restoreAction.historyId || "";
  if ((!Array.isArray(marks) || !marks.length) && !historyId) return;
  const previousFileId = selectedPhoto()?.fileId || "";
  const contextLabel = restoreAction.contextLabel || t("restore.context.change");
  const restoringCount = Array.isArray(marks) && marks.length ? marks.length : 1;
  showCommandNotice(
    {
      tone: "partial",
      state: t("restore.restoringState"),
      title: restoreAction.restoringTitle || t("restore.restoringTitle", { context: contextLabel }),
      detail: historyId ? t("restore.readingHistory") : photoCountText(restoringCount),
      loading: true,
    },
    0,
  );
  try {
    appState = historyId ? await postJson("/api/curation/undo", { historyId }) : await postJson("/api/mark/restore", { marks });
    preserveSelectedPhoto(previousFileId);
    const restored = appState.action?.restored ?? restoringCount;
    showCommandNotice({
      tone: "ready",
      state: t("restore.restoredState"),
      title: restoreAction.restoredTitle || t("restore.restoredTitle", { context: contextLabel }),
      detail: photoCountText(restored),
    });
    refreshCurationHistoryIfOpen();
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("restore.failureState"),
        title: t("restore.failureTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  }
}

async function undoLatestCurationAction() {
  if (appState?.job?.running) return;
  const previousFileId = selectedPhoto()?.fileId || "";
  showCommandNotice(
    {
      tone: "partial",
      state: t("restore.restoringState"),
      title: t("restore.latestRestoringTitle"),
      detail: t("restore.readingLatest"),
      loading: true,
    },
    0,
  );
  try {
    appState = await postJson("/api/curation/undo", {});
    preserveSelectedPhoto(previousFileId);
    const restored = appState.action?.restored ?? 0;
    const summary = t("history.recentAction");
    showCommandNotice({
      tone: "ready",
      state: t("restore.restoredState"),
      title: t("restore.latestRestoredTitle"),
      detail: `${summary} · ${photoCountText(restored)}`,
    });
    refreshCurationHistoryIfOpen();
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "partial",
        state: t("restore.latestFailureState"),
        title: t("restore.latestFailureTitle"),
        detail: errorMessage(error),
      },
      3200,
    );
  }
}

function restoreNoticeAction(action, context = {}) {
  const contextLabel = context.label || t("restore.context.change");
  return action?.beforeMarks?.length
    ? {
        type: "restoreMarks",
        icon: "undo",
        label: t("command.undo"),
        contextLabel,
        restoringTitle: context.restoringTitle || t("restore.restoringTitle", { context: contextLabel }),
        restoredTitle: context.restoredTitle || t("restore.restoredTitle", { context: contextLabel }),
        historyId: action.historyId || "",
        marks: action.beforeMarks,
      }
    : null;
}

function isEditableShortcutTarget(target) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target?.isContentEditable;
}

function isUndoShortcut(event) {
  return !event.repeat && (event.metaKey || event.ctrlKey) && !event.shiftKey && !event.altKey && String(event.key || "").toLowerCase() === "z";
}

function isShortcutHelpKey(event) {
  return !event.repeat && !event.metaKey && !event.ctrlKey && !event.altKey && String(event.key || "") === "?";
}

function handleViewerShortcut(event) {
  return viewerPanel.handleShortcut(event);
}

async function applyBatchStatus(status, target = galleryBatchTarget(appState?.photos || [])) {
  if (appState?.job?.running) return;
  const visiblePhotos = appState?.photos || [];
  if (!target.count) return;
  const previousFileId = selectedPhoto()?.fileId || "";
  try {
    appState = await postJson("/api/mark/status", {
      scope: target.scope,
      fileIds: target.fileIds,
      status,
    });
    preserveSelectedPhoto(previousFileId);
    visibleGallerySelection(appState.photos || []);
    const action = appState.action || {};
    const count = action.marked || 0;
    const statusLabel = localizedHistoryStatus(status, action.statusLabel);
    showCommandNotice({
      tone: status === "reject" ? "danger" : status === "pick" ? "ready" : "partial",
      state: t("batch.statusMarkedState"),
      title: t("batch.statusMarkedTitle", { scope: target.label, status: statusLabel }),
      detail: photoCountText(count),
      action: restoreNoticeAction(action, { label: t("restore.context.manual") }),
    }, 6200);
    refreshCurationHistoryIfOpen();
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("batch.statusFailureState"),
        title: t("batch.statusFailureTitle"),
        detail: errorMessage(error),
      },
      3600,
    );
  }
}

async function revealPhoto(photo) {
  if (!photo?.path) return;
  await postJson("/api/reveal", { path: photo.path });
}

async function openPhotoPreview(photo) {
  if (!photo?.path) return;
  try {
    await postJson("/api/open-file", { path: photo.path });
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("viewer.previewFailedState"),
        title: t("viewer.previewFailedTitle"),
        detail: errorMessage(error) || t("viewer.previewFailedDetail"),
      },
      4200,
    );
  }
}

async function copyFileFolderPath(folderPath) {
  const path = String(folderPath || "").trim();
  if (!path) return;
  try {
    const copied = await clipboard.writeText(path);
    if (!copied) throw new Error("clipboard_unavailable");
    showCommandNotice(
      {
        tone: "ready",
        state: t("score.file.copyFolderSuccessState"),
        title: t("score.file.copyFolderSuccessTitle"),
        detail: path,
      },
      2600,
    );
  } catch (_error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("score.file.copyFolderFailureState"),
        title: t("score.file.copyFolderFailureTitle"),
        detail: t("score.file.copyFolderFailureDetail"),
      },
      4200,
    );
  }
}

function bindEvents() {
  sourcePanel.bindEvents();
  filterPanel.bindEvents();
  viewerPanel.bindEvents();

  $$("[data-network]").forEach((button) => button.addEventListener("click", () => setNetworkMode(button.dataset.network)));
  $$(".view-tab").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $("#sidebarToggleBtn").addEventListener("click", toggleSidebarMode);
  $("#openSettingsDrawerBtn").addEventListener("click", openSettingsDrawer);
  $("#closeSettingsDrawerBtn").addEventListener("click", closeSettingsDrawer);
  $("#settingsScrim").addEventListener("click", closeSettingsDrawer);
  $("#openShortcutHelpBtn").addEventListener("click", openShortcutHelp);
  $("#closeShortcutHelpBtn").addEventListener("click", closeShortcutHelp);
  $("#shortcutHelpScrim").addEventListener("click", closeShortcutHelp);

  $("#mainScoreBtn").addEventListener("click", startScoring);
  $("#llmReviewBtn").addEventListener("click", startLlmReview);
  $("#commandNoticeActionBtn").addEventListener("click", () => {
    if (commandNotice?.action?.type === "restoreMarks") {
      restoreBatchMarks(commandNotice.action);
    }
  });
  $("#confirmLlmScoreBtn").addEventListener("click", confirmLlmScoring);
  $("#localOnlyScoreBtn").addEventListener("click", startLocalOnlyScoring);
  $("#cancelLlmConfirmBtn").addEventListener("click", () => closeLlmConfirm());
  $("#llmConfirmScrim").addEventListener("click", () => closeLlmConfirm());
  $("#confirmDangerActionBtn").addEventListener("click", confirmDangerAction);
  $("#cancelDangerConfirmBtn").addEventListener("click", () => closeDangerConfirm());
  $("#dangerConfirmScrim").addEventListener("click", () => closeDangerConfirm());
  $("#pauseJobBtn").addEventListener("click", toggleJobPause);
  $("#cancelJobBtn").addEventListener("click", cancelJob);
  $("#clearLocalDataBtn").addEventListener("click", clearLocalData);
  $("#clearHistoryBtn").addEventListener("click", clearHistoryCache);
  $("#clearModelBtn").addEventListener("click", clearModelCache);
  $("#editLlmConfigBtn").addEventListener("click", openLlmConfigEditor);
  $("#cancelLlmConfigBtn").addEventListener("click", cancelLlmConfigEdit);
  $("#llmModelButton").addEventListener("click", toggleLlmModelMenu);
  $("#llmModelSearchInput").addEventListener("input", handleLlmModelSearchInput);
  $("#llmModelSearchInput").addEventListener("keydown", handleLlmModelSearchKeydown);
  document.addEventListener("click", handleLlmModelDocumentClick);
  $("#refreshLlmModelsBtn").addEventListener("click", () => loadLlmModels());
  $("#llmApiKeyInput").addEventListener("input", resetLlmModelCatalogForConnectionChange);
  $("#llmBaseUrlInput").addEventListener("input", resetLlmModelCatalogForConnectionChange);
  $("#saveLlmConfigBtn").addEventListener("click", saveLlmConfig);
  $("#clearLlmKeyBtn").addEventListener("click", clearLlmKey);
  const modelStatusPill = $("#modelStatusPill");
  ["mouseenter", "focus"].forEach((eventName) => {
    modelStatusPill.addEventListener(eventName, () => modelStatusPill.classList.add("is-tooltip-visible"));
  });
  ["mouseleave", "blur"].forEach((eventName) => {
    modelStatusPill.addEventListener(eventName, () => modelStatusPill.classList.remove("is-tooltip-visible"));
  });
  $("#acceptFilteredModelBtn").addEventListener("click", () => acceptPhotoResult("model", "filtered", galleryBatchTarget(appState?.photos || [])));
  $("#acceptFilteredLlmBtn").addEventListener("click", () => acceptPhotoResult("llm", "filtered", galleryBatchTarget(appState?.photos || [])));
  $("#deliveryReviewBtn").addEventListener("click", () => openManualStatusView("pending"));
  $("#deliverySelectedBtn").addEventListener("click", () => openManualStatusView("pick"));
  $("#galleryBatchPickBtn").addEventListener("click", () => openBatchStatusConfirm("pick"));
  $("#galleryBatchHoldBtn").addEventListener("click", () => openBatchStatusConfirm("hold"));
  $("#galleryBatchRejectBtn").addEventListener("click", () => openBatchStatusConfirm("reject"));
  $("#gallerySelectVisibleBtn").addEventListener("click", selectVisibleGalleryPhotos);
  $("#galleryClearSelectionBtn").addEventListener("click", clearGallerySelection);
  $("#galleryGrid").addEventListener("click", handleGalleryGridClick);
  $("#galleryGrid").addEventListener("load", handleGalleryImageLoad, true);
  $("#galleryGrid").addEventListener("error", handleGalleryImageError, true);
  $("#galleryGrid").addEventListener("pointerover", handleGalleryTooltipIntent);
  $("#galleryGrid").addEventListener("pointerout", clearGalleryTooltipPlacement);
  $("#galleryGrid").addEventListener("focusin", handleGalleryTooltipIntent);
  $("#galleryGrid").addEventListener("focusout", clearGalleryTooltipPlacement);
  $(".workspace").addEventListener("pointerdown", beginGalleryMarquee);
  $(".workspace").addEventListener("dragstart", (event) => event.preventDefault());
  $("#confirmBatchStatusBtn").addEventListener("click", confirmBatchStatus);
  $("#cancelBatchStatusConfirmBtn").addEventListener("click", () => closeBatchStatusConfirm());
  $("#batchStatusConfirmScrim").addEventListener("click", () => closeBatchStatusConfirm());
  $("#pickExportFolderBtn").addEventListener("click", pickExportFolder);
  $("#exportPreflight").addEventListener("click", handleExportPreflightClick);
  $("#exportResult").addEventListener("click", handleExportResultClick);
  $("#exportSelectedBtn").addEventListener("click", exportSelectedPhotos);
  window.addEventListener("culvia:languagechange", () => render());

  window.addEventListener("keydown", (event) => {
    if (trapActiveDialogFocus(event)) return;
    if (event.key === "Escape" && shortcutHelpOpen) {
      closeShortcutHelp();
      return;
    }
    if (shortcutHelpOpen) return;
    if (event.key === "Escape" && dangerConfirmOpen) {
      closeDangerConfirm();
      return;
    }
    if (dangerConfirmOpen) return;
    if (event.key === "Escape" && llmConfirmOpen) {
      closeLlmConfirm();
      return;
    }
    if (llmConfirmOpen) return;
    if (event.key === "Escape" && batchStatusConfirmOpen) {
      closeBatchStatusConfirm();
      return;
    }
    if (batchStatusConfirmOpen) return;
    if (event.key === "Escape" && settingsDrawerOpen) {
      closeSettingsDrawer();
      return;
    }
    if (settingsDrawerOpen) return;
    if (isEditableShortcutTarget(event.target)) return;
    if (isShortcutHelpKey(event)) {
      event.preventDefault();
      openShortcutHelp();
      return;
    }
    if (isUndoShortcut(event)) {
      event.preventDefault();
      undoLatestCurationAction();
      return;
    }
    if (handleGalleryShortcut(event)) return;
    if (handleViewerShortcut(event)) return;
  });
}

renderStaticIcons();
bindUiTooltipPortal();
bindEvents();
applySidebarMode();
applySettingsDrawerState();
applyShortcutHelpState();
applyLlmConfirmState();
applyBatchStatusConfirmState();
applyDangerConfirmState();
loadState();
