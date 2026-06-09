const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const llmConfigView = window.CulviaLlmConfigView;
const commandView = window.CulviaCommandView;
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
let sourceMode = "folders";
let networkMode = "direct";
let selectedIndex = 0;
let pollTimer = null;
let filterTimer = null;
let filterUpdateInFlight = null;
let commandNotice = null;
let commandNoticeTimer = null;
let llmModelOptions = [];
let llmModelsLoading = false;
let llmModelListMessage = "";
let llmSelectedModel = "";
let llmModelMenuOpen = false;
let llmModelSearchQuery = "";
let llmConfigEditing = false;
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
let distributionLens = "overview";
const VIEW_STORAGE_KEY = "culvia.activeView.v1";
const VIEW_NAMES = ["viewer", "gallery", "distribution", "export"];
let activeView = normalizeViewName(localStorage.getItem(VIEW_STORAGE_KEY));
const SIDEBAR_COLLAPSED_KEY = "culvia.sidebarCollapsed";
let sidebarCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
let settingsDrawerOpen = false;
let exportDestination = "";
let exportStatusText = "";
let exportResult = null;
let exportPreflight = null;
let exportPreflightLoading = false;
let exportPreflightError = "";
let exportPreflightKey = "";
let showMissingScoreDetails = false;
let inspectorDetailTab = "overview";
let filterRestoreAttempted = false;
let selectedGalleryIds = new Set();
let gallerySelectionAnchorId = "";
let galleryMarqueeState = null;
let gallerySuppressNextCardClick = false;
let uiTooltipAnchor = null;
let uiTooltipRaf = 0;
let curationHistory = [];
let sourceInputsDirty = false;
let sourcePreviewTimer = null;
let sourcePreviewRequestId = 0;
let sourcePreviewLoading = false;
let sourcePreviewPending = false;
let desktopDropHandledUntil = 0;
let curationHistoryLoading = false;
let curationHistoryError = "";
let shortcutHelpOpen = false;
let markUpdateQueue = Promise.resolve();

const {
  FILTER_STORAGE_KEY,
  filterPayloadEquals,
  filtersAreDefault,
  normalizeFilterPayload,
  savedFilterPayload,
  persistFilterPayload,
  savedFilterPresets,
  saveFilterPreset,
  deleteFilterPreset,
  renameFilterPreset,
  updateFilterPreset,
} = window.CulviaFilterState;
const filterPresetView = window.CulviaFilterPresets;
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
let filterPresets = savedFilterPresets();
let renamingFilterPresetId = "";
const MARK_ADVANCE_STORAGE_KEY = "culvia.markAdvance.v1";
let markAdvanceEnabled = localStorage.getItem(MARK_ADVANCE_STORAGE_KEY) === "true";

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

function uniqueFolderList(items) {
  const source = Array.isArray(items) ? items : items == null ? [] : [items];
  const seen = new Set();
  return source
    .map((item) => String(item || "").trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false;
      seen.add(item);
      return true;
    });
}

function syncFolderInputFromList(folders) {
  const input = $("#folderInput");
  if (input) input.value = uniqueFolderList(folders).join("\n");
}

function folderEditorHasFocus() {
  return Boolean(document.activeElement?.closest?.(".manual-path-edit"));
}

function foldersFromInput() {
  const list = $("#folderList");
  if (list) {
    const values = Array.from(list.querySelectorAll("[data-folder-path]")).map((input) => input.value);
    return uniqueFolderList(values);
  }
  const input = $("#folderInput");
  return input ? uniqueFolderList(input.value.split("\n")) : [];
}

function folderListsEqual(left = [], right = []) {
  const a = uniqueFolderList(left);
  const b = uniqueFolderList(right);
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function matchingSourcePreview(folders = foldersFromInput()) {
  const preview = appState?.sourcePreview;
  if (!preview || preview.mode !== "folders" || preview.ready !== true) return null;
  return folderListsEqual(preview.folders || [], folders) && Number.isFinite(Number(preview.total)) ? preview : null;
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

function isSourcePreviewJob(job = appState?.job) {
  return Boolean(job?.running) && job.kind === "source_preview";
}

function isSourcePreviewActive() {
  return sourcePreviewLoading || isSourcePreviewJob();
}

function sourceInputSnapshot() {
  const cacheInput = $("#cacheInput");
  return {
    mode: sourceMode || appState?.source?.mode || "folders",
    folders: foldersFromInput(),
    cachePath: cacheInput ? cacheInput.value.trim() : appState?.source?.cachePath || "",
  };
}

function applySourceInputSnapshot(snapshot) {
  if (!snapshot || !appState) return;
  sourceMode = snapshot.mode || "folders";
  appState.source = {
    ...(appState.source || {}),
    mode: sourceMode,
    folders: uniqueFolderList(snapshot.folders || []),
    cachePath: snapshot.cachePath || "",
  };
  syncFolderInputFromList(appState.source.folders || []);
}

function markSourceInputsDirty() {
  sourceInputsDirty = true;
  syncFolderInputFromList(foldersFromInput());
  applySourceInputSnapshot(sourceInputSnapshot());
  refreshSourceDependentControls();
}

function folderValuesFromText(text) {
  return uniqueFolderList(String(text || "").split(/\r?\n/));
}

function setFolderList(folders, { dirty = true, previewDelay = 240 } = {}) {
  const nextFolders = uniqueFolderList(folders);
  syncFolderInputFromList(nextFolders);
  renderSourceFolderList(nextFolders, Boolean(appState?.job?.running));
  if (sourceMode !== "folders") setSourceMode("folders");
  if (dirty) {
    markSourceInputsDirty();
    updatePathSummaries();
    scheduleSourcePreview(previewDelay);
  }
}

function addFolderEntries(values, { previewDelay = 120 } = {}) {
  const additions = uniqueFolderList(values);
  if (!additions.length || appState?.job?.running) return;
  setFolderList([...foldersFromInput(), ...additions], { previewDelay });
  const addInput = $("#folderAddInput");
  if (addInput) addInput.value = "";
}

function renderSourceFolderList(folders = foldersFromInput(), busy = Boolean(appState?.job?.running)) {
  const list = $("#folderList");
  if (!list) return;
  const normalized = uniqueFolderList(folders);
  if (!normalized.length) {
    list.innerHTML = `<div class="source-folder-empty">${escapeHtml(t("source.noFolders"))}</div>`;
    return;
  }
  list.innerHTML = normalized
    .map(
      (folder, index) => `
        <div class="source-folder-row" data-folder-row>
          <input
            class="text-input source-folder-input"
            type="text"
            value="${escapeHtml(folder)}"
            data-folder-path
            data-folder-index="${index}"
            aria-label="${escapeHtml(t("source.folderPath"))}"
            data-ui-tooltip="${escapeHtml(folder)}"
            ${busy ? "disabled" : ""}
          />
          <button class="icon-button" type="button" data-copy-source-folder="${escapeHtml(folder)}" data-ui-tooltip="${escapeHtml(t("source.copyFolder"))}" aria-label="${escapeHtml(t("source.copyFolder"))}" ${busy ? "disabled" : ""}>
            ${iconMarkup("copy")}
          </button>
          <button class="icon-button" type="button" data-remove-source-folder="${index}" data-ui-tooltip="${escapeHtml(t("source.removeFolder"))}" aria-label="${escapeHtml(t("source.removeFolder"))}" ${busy ? "disabled" : ""}>
            ${iconMarkup("trash")}
          </button>
        </div>
      `,
    )
    .join("");
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
  return Boolean(foldersFromInput().length || appState?.source?.uploadedPaths?.length);
}

function displayNetworkLabel(label) {
  if (label === "跟随系统设置") return t("network.systemConnection");
  if (label === "普通连接") return t("network.directConnection");
  return label || t("network.directConnection");
}

function updatePathSummaries() {
  $("#folderSummary")?.removeAttribute("data-i18n");
  const folders = foldersFromInput();
  const preview = matchingSourcePreview(folders);
  const previewText = isSourcePreviewActive()
    ? ` · ${t("source.previewScanningState")}`
    : preview
      ? ` · ${t("source.previewCount", { count: Number(preview.total) })}`
      : "";
  if (!folders.length) {
    setText("#folderSummary", t("source.empty"));
  } else if (folders.length === 1) {
    setText("#folderSummary", `${pathName(folders[0])} · ${parentPath(folders[0])}${previewText}`);
  } else {
    setText(
      "#folderSummary",
      `${tr("source.folderCount", { count: folders.length }, `${folders.length} 个目录`)} · ${folders.slice(0, 2).map(pathName).join("、")}${previewText}`,
    );
  }
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
  const raw = String(option.state || "").trim();
  if (raw) {
    const normalized = raw.toLowerCase();
    if (["已配置", "configured", "ready", "ready locally"].includes(normalized)) return t("model.configured");
    if (["需配置", "未配置", "not configured", "needs config", "setup needed"].includes(normalized)) return t("model.needsConfig");
    return raw;
  }
  if (option.requiresDownload) return option.downloaded ? t("model.ready") : t("model.firstUse");
  return t("model.localCompute");
}

function localizedListJoin(items = []) {
  const separator = i18n?.language?.() === "en" ? ", " : "、";
  return items.filter(Boolean).join(separator);
}

function localizedSortOption(option = {}) {
  return tr(`sort.${option.value}`, {}, option.label || option.value || "");
}

function localizedWeightPreset(option = {}) {
  return tr(`weight.${option.value}`, {}, option.label || option.value || "");
}

function localizedAgreementOption(option = {}) {
  return tr(`agreement.${option.value}`, {}, option.label || option.value || "");
}

function localizedManualFilterOption(option = {}) {
  const value = String(option.value || "");
  if (value === "all") return t("manual.filter.all");
  if (value === "pending") return t("manual.filter.pending");
  return tr(`manual.status.${value}`, {}, option.label || manualStatusLabel(value));
}

function localizedColorFilterOption(option = {}) {
  const value = String(option.value || "");
  if (value === "all" || value === "labeled" || value === "none") return tr(`color.${value}`, {}, option.label || value);
  return colorLabelMeta(value).label;
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

function colorLabelFromShortcut(key) {
  const normalized = String(key || "").toLowerCase();
  const match = manualColorLabels.find((item) => item.shortcut === normalized);
  return match ? match.value : null;
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

function preserveSelectedPhoto(previousFileId) {
  if (!previousFileId || !appState?.photos?.length) {
    selectedIndex = 0;
    return;
  }
  selectedIndex = cullingFlow.nextIndexAfterMark(appState.photos, selectedIndex, previousFileId, false);
}

function persistMarkAdvanceMode() {
  try {
    if (markAdvanceEnabled) {
      localStorage.setItem(MARK_ADVANCE_STORAGE_KEY, "true");
    } else {
      localStorage.removeItem(MARK_ADVANCE_STORAGE_KEY);
    }
  } catch (_error) {
    // Convenience preference only; blocked storage should not interrupt culling.
  }
}

function toggleMarkAdvanceMode() {
  markAdvanceEnabled = !markAdvanceEnabled;
  persistMarkAdvanceMode();
  renderManualControls(selectedPhoto());
}

function setSourceMode(mode, { dirty = false } = {}) {
  if (dirty && appState?.job?.running) return;
  sourceMode = mode;
  $$("[data-source]").forEach((button) => button.classList.toggle("is-active", button.dataset.source === mode));
  $$("[data-source-view]").forEach((view) => {
    view.classList.toggle("is-active", view.dataset.sourceView === mode);
  });
  if (dirty) {
    markSourceInputsDirty();
    scheduleSourcePreview();
  }
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
  setText("#modelLabel", model.label || t("topbar.modelStatus"));
  const modelReady = model.downloaded ? t("model.ready") : model.tone === "partial" ? t("model.preparing") : t("model.pending");
  const runtimeState = model.runtimeLoaded
    ? t("model.runtimeLoaded", { device: model.runtimeDevice || appState?.app?.device || t("common.currentDevice") })
    : model.downloaded
      ? t("model.filesReady")
      : t("model.firstUse");
  const selectedOptions = (model.options || []).filter((option) => option.selected);
  const rows = [
    [t("model.components"), localizedListJoin(selectedOptions.map((option) => localizedModelOptionLabel(option))) || t("model.defaultCombo")],
    [t("model.status"), runtimeState],
    [t("model.coreAesthetic"), model.size || t("common.unknown")],
    [t("model.clipReference"), model.clipSize || t("common.unknown")],
    [t("model.device"), appState?.app?.device || model.runtimeDevice || t("common.currentDevice")],
    [t("model.fileConnection"), displayNetworkLabel(model.proxyLabel)],
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

function selectedLlmModel() {
  return llmSelectedModel || appState?.llm?.model || "";
}

function applyLlmModelPickerDomPlan(plan) {
  const button = $(plan.button.selector);
  const menu = $(plan.menu.selector);
  const list = $(plan.list.selector);
  if (!button || !menu || !list) return null;
  setTextWithHint(plan.button.textSelector, plan.button.text);
  setText(plan.button.metaSelector, plan.button.metaText);
  button.setAttribute("aria-expanded", plan.button.ariaExpanded);
  menu.classList.toggle("is-hidden", plan.menu.hidden);
  $(plan.picker.selector)?.classList.toggle("is-open", plan.picker.open);
  const searchInput = $(plan.searchInput.selector);
  if (searchInput && document.activeElement !== searchInput) searchInput.value = plan.searchInput.value;
  list.innerHTML = plan.list.html;
  return list;
}

function renderLlmModelPicker(llm) {
  if (!llmSelectedModel) llmSelectedModel = llm.model || "";
  const pickerState = llmConfigView.modelPickerState({
    currentModel: selectedLlmModel() || llm.model || "",
    fallbackModel: appState?.llm?.model || "gpt-4o-mini",
    providerOptions: llmModelOptions,
    selectedModel: selectedLlmModel(),
    searchQuery: llmModelSearchQuery,
  });
  const list = applyLlmModelPickerDomPlan(
    llmConfigView.modelPickerDomPlan(pickerState, {
      checkIcon: iconMarkup("check"),
      menuOpen: llmModelMenuOpen,
      searchQuery: llmModelSearchQuery,
    }),
  );
  if (!list) return;
  bindLlmModelOptionButtons(list);
}

function selectLlmModelOption(value) {
  llmSelectedModel = String(value || "");
  llmModelMenuOpen = false;
  llmModelSearchQuery = "";
  renderLlmConfig();
}

function bindLlmModelOptionButtons(list) {
  list.querySelectorAll("[data-model-value]").forEach((optionButton) => {
    optionButton.addEventListener("click", () => selectLlmModelOption(optionButton.dataset.modelValue || ""));
  });
}

function applyLlmPromptSelectionDomPlan(container, plan) {
  const input = $(plan.input.selector);
  if (input) input.value = plan.input.value;
  container.querySelectorAll(plan.options.selector).forEach((item) => {
    const active = item.dataset[plan.options.datasetKey] === plan.options.selectedValue;
    item.classList.toggle(plan.options.activeClass, active);
    item.setAttribute(plan.options.ariaAttribute, active ? "true" : "false");
  });
}

function applyLlmPromptOptionSelection(container, selectedButton) {
  applyLlmPromptSelectionDomPlan(
    container,
    llmConfigView.promptSelectionDomPlan(selectedButton.dataset.llmPrompt || "balanced"),
  );
  setTextWithHint("#llmPresetPromptPreview", selectedButton.dataset.llmPromptText || "");
}

function bindLlmPromptOptionButtons(container) {
  container.querySelectorAll("[data-llm-prompt]").forEach((button) => {
    button.addEventListener("click", () => applyLlmPromptOptionSelection(container, button));
  });
}

function renderLlmPromptOptions(llm) {
  const container = $("#llmPromptOptions");
  const input = $("#llmPromptPreset");
  if (!container) return;
  const selectedPrompt = llm.promptPreset || "balanced";
  if (input) input.value = selectedPrompt;
  container.innerHTML = llmConfigView.promptOptionsMarkup(llmConfigView.promptOptionViews(llm));
  setTextWithHint("#llmPresetPromptPreview", llmConfigView.promptPresetPrompt(llm, selectedPrompt));
  bindLlmPromptOptionButtons(container);
}

function focusLlmModelSearchSoon() {
  window.setTimeout(() => $("#llmModelSearchInput")?.focus(), 0);
}

function closeLlmModelMenu() {
  if (!llmModelMenuOpen) return;
  llmModelMenuOpen = false;
  renderLlmConfig();
}

async function toggleLlmModelMenu() {
  if (!llmModelMenuOpen && llmConfigEditing && !llmModelOptions.length && !llmModelsLoading) {
    const hasInputKey = Boolean($("#llmApiKeyInput")?.value?.trim());
    if (hasInputKey || appState?.llm?.configured) {
      const result = await loadLlmModels({ openMenu: true });
      if (result?.ok) focusLlmModelSearchSoon();
      return;
    }
  }
  llmModelMenuOpen = !llmModelMenuOpen;
  renderLlmConfig();
  if (llmModelMenuOpen) focusLlmModelSearchSoon();
}

function handleLlmModelSearchInput(event) {
  llmModelSearchQuery = event.target.value;
  renderLlmModelPicker(appState?.llm || {});
}

function handleLlmModelSearchKeydown(event) {
  if (event.key !== "Escape") return;
  closeLlmModelMenu();
  $("#llmModelButton")?.focus();
}

function handleLlmModelDocumentClick(event) {
  if (!llmModelMenuOpen) return;
  if (event.target?.closest?.("#llmModelPicker")) return;
  closeLlmModelMenu();
}

function applyLlmConfigDomPlan(plan) {
  const status = $(plan.status.selector);
  if (!status) return false;
  status.textContent = plan.status.text;
  status.classList.toggle("is-ready", plan.status.ready);
  const hintedTextSelectors = new Set([
    "#llmModelPreview",
    "#llmReadonlyKey",
    "#llmReadonlySource",
    "#llmReadonlyBaseUrl",
    "#llmReadonlyModel",
    "#llmReadonlyPrompt",
    "#llmConfigHint",
    "#llmModelListHint",
  ]);
  plan.texts.forEach((item) => {
    if (hintedTextSelectors.has(item.selector)) {
      setTextWithHint(item.selector, item.text);
    } else {
      setText(item.selector, item.text);
    }
  });
  plan.visibility.forEach((item) => {
    $(item.selector)?.classList.toggle("is-hidden", item.hidden);
  });
  plan.inputs.forEach((item) => {
    const input = $(item.selector);
    if (!input || document.activeElement === input) return;
    if (llmConfigEditing) return;
    if ("value" in item) input.value = item.value;
    if ("placeholder" in item) input.placeholder = item.placeholder;
  });
  const refreshButton = $(plan.refreshButton.selector);
  if (refreshButton) setButtonLabel(refreshButton, plan.refreshButton.icon, plan.refreshButton.label);
  const saveButton = $(plan.saveButton.selector);
  if (saveButton) setButtonLabel(saveButton, plan.saveButton.icon, plan.saveButton.label);
  return true;
}

function renderLlmConfig() {
  const llm = appState?.llm || {};
  const viewState = llmConfigView.configViewState(llm, {
    editing: llmConfigEditing,
    modelsLoading: llmModelsLoading,
    modelListMessage: llmModelListMessage,
  });
  const domPlan = llmConfigView.configDomUpdatePlan(viewState);
  if (!applyLlmConfigDomPlan(domPlan)) return;
  renderLlmPromptOptions(llm);
  renderLlmModelPicker(llm);
  const refreshButton = $(domPlan.refreshButton.selector);
  if (refreshButton) {
    refreshButton.disabled = Boolean(appState?.job?.running) || llmModelsLoading;
  }
  const saveButton = $(domPlan.saveButton.selector);
  if (saveButton) {
    saveButton.disabled = Boolean(appState?.job?.running) || llmModelsLoading;
  }
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
    networkText: displayNetworkLabel(model?.proxyLabel),
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
  $("#refreshLlmModelsBtn").disabled = running || llmModelsLoading;
}

function renderStats(summary) {
  setText("#statScored", summary.scored ?? 0);
  setText("#statShowing", summary.showing ?? 0);
  setText("#statBest", summary.best || t("stats.empty"));
  setText("#statAverage", summary.average || t("stats.empty"));
}

function filterPresetContext() {
  return {
    options: {
      manualStatusOptions: appState?.manualStatusOptions || [],
      colorLabelOptions: appState?.colorLabelOptions || [],
      modelAgreementOptions: appState?.modelAgreementOptions || [],
      sortOptions: appState?.sortOptions || [],
      weightPresets: appState?.weightPresets || [],
    },
    t,
    language: () => i18n?.language?.() || "zh-CN",
    manualStatusLabel,
    colorLabelMeta,
    optionLabel(group, option = {}) {
      if (group === "manual") return localizedManualFilterOption(option);
      if (group === "color") return localizedColorFilterOption(option);
      if (group === "agreement") return localizedAgreementOption(option);
      if (group === "sort") return localizedSortOption(option);
      if (group === "weight") return localizedWeightPreset(option);
      return option.label || option.value || "";
    },
  };
}

function activeFilterChips(filters = appState?.filters || {}) {
  return filterPresetView.activeFilterChips(filters, filterPresetContext());
}

function renderFilterScope() {
  const bar = $("#filterScopeBar");
  const container = $("#filterScopeChips");
  const clearButton = $("#clearFilterScopeBtn");
  if (!bar || !container || !clearButton) return;

  const chips = activeFilterChips(appState?.filters || {});
  bar.classList.toggle("is-hidden", !chips.length);
  container.innerHTML = chips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("");
  clearButton.disabled = Boolean(appState?.job?.running) || Boolean(commandNotice?.loading);
}

function filterPresetSuggestedName(filters = appState?.filters || {}) {
  return filterPresetView.suggestedName(filters, filterPresetContext());
}

function filterPresetSummary(filters = {}) {
  return filterPresetView.summary(filters, filterPresetContext());
}

function filterPresetUpdatedText(updatedAt) {
  return filterPresetView.updatedText(updatedAt);
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

function filterPresetMetaText(preset) {
  return filterPresetView.metaText(preset, filterPresetContext());
}

function renderFilterPresets() {
  const list = $("#filterPresetList");
  const input = $("#filterPresetNameInput");
  const saveButton = $("#saveFilterPresetBtn");
  const hint = $("#filterPresetHint");
  if (!list || !input || !saveButton) return;

  filterPresets = savedFilterPresets();
  if (renamingFilterPresetId && !filterPresets.some((preset) => preset.id === renamingFilterPresetId)) {
    renamingFilterPresetId = "";
  }
  const currentFilters = normalizeFilterPayload(appState?.filters || {});
  input.placeholder = renamingFilterPresetId ? t("filters.renamePlaceholder") : filterPresetSuggestedName(currentFilters);
  const saveIcon = renamingFilterPresetId ? "pencil" : "bookmark";
  const saveLabel = renamingFilterPresetId ? t("filters.confirmRename") : t("filters.saveView");
  saveButton.innerHTML = iconMarkup(saveIcon);
  saveButton.removeAttribute("title");
  saveButton.dataset.uiTooltip = saveLabel;
  saveButton.setAttribute("aria-label", saveLabel);
  saveButton.disabled = Boolean(appState?.job?.running) || Boolean(commandNotice?.loading);
  if (hint) {
    hint.textContent = renamingFilterPresetId ? t("filters.renaming") : t("filters.currentRange", { summary: filterPresetSummary(currentFilters) });
  }
  if (!filterPresets.length) {
    list.innerHTML = `<div class="saved-filter-empty">${escapeHtml(t("filters.noViews"))}</div>`;
    return;
  }
  list.innerHTML = filterPresets
    .map((preset) => {
      const active = filterPayloadEquals(preset.filters, currentFilters);
      const renaming = preset.id === renamingFilterPresetId;
      const summary = filterPresetSummary(preset.filters);
      const meta = filterPresetMetaText(preset);
      return `
        <div class="saved-filter-item ${active ? "is-active" : ""} ${renaming ? "is-renaming" : ""}">
          <button class="saved-filter-apply" type="button" data-filter-preset="${escapeHtml(preset.id)}" aria-label="${escapeHtml(`${preset.name} · ${summary}`)}" data-ui-tooltip="${escapeHtml(summary)}">
            <span>${escapeHtml(preset.name)}</span>
            <small>${escapeHtml(meta)}</small>
          </button>
          <button class="saved-filter-update" type="button" data-update-filter-preset="${escapeHtml(preset.id)}" aria-label="${escapeHtml(t("filters.updateView", { name: preset.name }))}" data-ui-tooltip="${escapeHtml(t("filters.updateConditions"))}">
            ${iconMarkup("refreshCw")}
          </button>
          <button class="saved-filter-rename" type="button" data-rename-filter-preset="${escapeHtml(preset.id)}" aria-label="${escapeHtml(t("filters.renameView", { name: preset.name }))}" data-ui-tooltip="${escapeHtml(t("filters.rename"))}">
            ${iconMarkup("pencil")}
          </button>
          <button class="saved-filter-delete" type="button" data-delete-filter-preset="${escapeHtml(preset.id)}" aria-label="${escapeHtml(t("filters.deleteView", { name: preset.name }))}" data-ui-tooltip="${escapeHtml(t("filters.deleteView", { name: preset.name }))}">
            ${iconMarkup("x")}
          </button>
        </div>
      `;
    })
    .join("");
  list.querySelectorAll("[data-filter-preset]").forEach((button) => {
    button.addEventListener("click", () => applyFilterPreset(button.dataset.filterPreset));
  });
  list.querySelectorAll("[data-update-filter-preset]").forEach((button) => {
    button.addEventListener("click", () => refreshFilterPreset(button.dataset.updateFilterPreset));
  });
  list.querySelectorAll("[data-rename-filter-preset]").forEach((button) => {
    button.addEventListener("click", () => beginRenameFilterPreset(button.dataset.renameFilterPreset));
  });
  list.querySelectorAll("[data-delete-filter-preset]").forEach((button) => {
    button.addEventListener("click", () => removeFilterPreset(button.dataset.deleteFilterPreset));
  });
}

function selectedPhoto() {
  if (!appState?.photos?.length) return null;
  selectedIndex = clamp(selectedIndex, 0, appState.photos.length - 1);
  return appState.photos[selectedIndex];
}

function renderScoreRows(photo) {
  const plan = viewerInspector.scoreRowsMarkup(photo, {
    activeTab: inspectorDetailTab,
    appState,
    showMissingScoreDetails,
  });
  inspectorDetailTab = plan.activeTab;
  const container = $("#scoreRows");
  if (!container) return;
  container.innerHTML = plan.html;
  container.querySelectorAll("[data-score-detail-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      inspectorDetailTab = button.dataset.scoreDetailTab || "overview";
      renderScoreRows(photo);
    });
  });
  container.querySelectorAll("[data-copy-file-folder]").forEach((button) => {
    button.addEventListener("click", () => {
      void copyFileFolderPath(button.dataset.copyFileFolder || "");
    });
  });
  $("#toggleMissingScoreDetails")?.addEventListener("click", () => {
    showMissingScoreDetails = !showMissingScoreDetails;
    renderScoreRows(photo);
  });
}

function fallbackScoreRowsMarkup(photo, error) {
  const scoreTexts = photo?.scoreTexts || {};
  const technicalTexts = photo?.technicalTexts || {};
  const modelQualityTexts = photo?.modelQualityTexts || {};
  const aestheticReferenceTexts = photo?.aestheticReferenceTexts || {};
  const llmReviewTexts = photo?.llmReviewTexts || {};
  const row = (field, text, missing = t("score.notCalculated")) => {
    const label = t(metricLabelKeys[field] || `sort.${field}_0_10`);
    const value = localizedMetricText(text, missing);
    return `
      <div class="score-row">
        <span class="score-name"${textHintAttributes(label)}>${escapeHtml(label)}</span>
        <span class="score-stars">☆☆☆☆☆</span>
        <span class="score-num ${text ? "" : "is-missing"}"${textHintAttributes(value)}>${escapeHtml(value)}</span>
      </div>
    `;
  };
  const group = (title, rows) => {
    const body = rows.filter(Boolean).join("");
    return body
      ? `
        <div class="score-group">
          <div class="score-group-title">
            <div><span>${escapeHtml(title)}</span></div>
          </div>
          ${body}
        </div>
      `
      : "";
  };
  const fileName = pathName(photo?.path || "");
  const errorText = error?.message || String(error || "");
  return `
    <div class="score-detail-toolbar">
      <span>${escapeHtml(t("score.detailTitle"))}</span>
      ${errorText ? `<small class="score-render-error">${escapeHtml(errorText)}</small>` : ""}
    </div>
    <div class="score-detail-panel" role="tabpanel">
      ${group(t("score.core.title"), [
        row("overall", photo?.overallText),
        row("quality", scoreTexts.quality),
        row("composition", scoreTexts.composition),
        row("lighting", scoreTexts.lighting),
        row("color", scoreTexts.color),
        row("depth_of_field", scoreTexts.depth_of_field),
        row("content", scoreTexts.content),
      ])}
      ${group(t("score.aestheticReference.title"), [
        row("clip_aesthetic", aestheticReferenceTexts.clip_aesthetic),
        row("clip_relevance", aestheticReferenceTexts.clip_relevance),
      ])}
      ${group(t("score.technical.title"), [
        row("clip_iqa_overall", modelQualityTexts.clip_iqa_overall),
        row("technical_overall", technicalTexts.technical_overall),
        row("exposure", technicalTexts.exposure),
        row("sharpness", technicalTexts.sharpness),
        row("noise", technicalTexts.noise),
      ])}
      ${group(t("score.llm.title"), [
        row("llm_review_overall", llmReviewTexts.llm_review_overall, t("score.notReviewed")),
        row("llm_aesthetic", llmReviewTexts.llm_aesthetic, t("score.notReviewed")),
        row("llm_technical", llmReviewTexts.llm_technical, t("score.notReviewed")),
      ])}
      <div class="score-group">
        <div class="score-group-title">
          <div><span>${escapeHtml(t("score.file.title"))}</span></div>
          <strong${textHintAttributes(fileName)}>${escapeHtml(fileName || t("score.noData"))}</strong>
        </div>
      </div>
    </div>
  `;
}

function renderScoreRowsFallback(photo, error) {
  const container = $("#scoreRows");
  if (!container) return;
  container.innerHTML = fallbackScoreRowsMarkup(photo, error);
}

function renderSignalChips(photo) {
  const container = $("#signalChips");
  if (!container) return;
  container.innerHTML = viewerInspector.signalChipsMarkup(photo, {
    llmModel: appState.llm?.model || "",
  });
}

function renderFilmstrip(photos, activeIndex) {
  const filmstrip = $("#filmstrip");
  if (!filmstrip) return;
  if (!photos.length) {
    filmstrip.innerHTML = "";
    return;
  }
  filmstrip.classList.remove("is-hidden");
  const windowRange = filmstripWindow(photos, activeIndex);
  const visibleThumbs = photos.slice(windowRange.start, windowRange.end);
  const leadingCount = windowRange.start;
  const trailingCount = photos.length - windowRange.end;
  filmstrip.innerHTML = `
    ${leadingCount ? `<div class="thumb-window-edge">${escapeHtml(t("viewer.beforeCount", { count: leadingCount }))}</div>` : ""}
    ${visibleThumbs
    .map(
      (item, offset) => {
        const index = windowRange.start + offset;
        const itemLevel = localizedScoreLevel(item.level);
        const thumbHint = `${itemLevel} · ${item.recommendationText || item.overallText}`;
        return `
        <button class="thumb ${index === activeIndex ? "is-active" : ""}" type="button" data-index="${index}" aria-label="${escapeHtml(thumbHint)}" data-ui-tooltip="${escapeHtml(thumbHint)}">
          <img src="${item.thumb}" alt="${escapeHtml(t("viewer.thumbAlt"))}" loading="lazy" />
          <span>${item.recommendationText || item.overallText}</span>
          ${manualBadgeMarkup(item.manual, true)}
        </button>
      `;
      },
    )
    .join("")}
    ${trailingCount ? `<div class="thumb-window-edge">${escapeHtml(t("viewer.afterCount", { count: trailingCount }))}</div>` : ""}
  `;
  filmstrip.querySelectorAll(".thumb").forEach((button) => {
    button.addEventListener("click", () => {
      selectedIndex = Number(button.dataset.index);
      renderViewer();
    });
  });
  syncActiveThumbnail(filmstrip);
}

function renderViewerInspector(photo) {
  try {
    renderManualControls(photo);
  } catch (error) {
    console.error("Failed to render manual controls", error);
  }
  try {
    renderSignalChips(photo);
  } catch (error) {
    console.error("Failed to render score signals", error);
  }
  try {
    renderScoreRows(photo);
  } catch (error) {
    console.error("Failed to render score details", error);
    renderScoreRowsFallback(photo, error);
  }
}

function syncActiveThumbnail(filmstrip, behavior = "auto") {
  const activeThumb = filmstrip?.querySelector(".thumb.is-active");
  if (!activeThumb) return;
  const targetLeft = activeThumb.offsetLeft - (filmstrip.clientWidth - activeThumb.offsetWidth) / 2;
  const maxLeft = Math.max(0, filmstrip.scrollWidth - filmstrip.clientWidth);
  filmstrip.scrollTo({
    left: clamp(targetLeft, 0, maxLeft),
    behavior,
  });
}

function renderManualControls(photo) {
  const manual = photo?.manual || {};
  const busy = Boolean(appState?.job?.running);
  const rating = Number(manual.rating || 0);
  const status = manual.status || "";
  const colorLabel = manual.colorLabel || "";
  setText("#manualStatusText", manualStatusLabel(status));
  $("#manualStatusText")?.classList.remove("is-picked", "is-rejected", "is-pending", "is-unreviewed");
  $("#manualStatusText")?.classList.add(manualStatusClass(status));
  $("#manualStars").innerHTML = [1, 2, 3, 4, 5]
    .map(
      (value) => `
        <button
          class="manual-star ${value <= rating ? "is-active" : ""}"
          type="button"
          data-manual-rating="${value}"
          aria-label="${escapeHtml(t("manual.ratingStars", { count: value }))}"
          ${busy ? "disabled" : ""}
        >★</button>
      `,
    )
    .join("");
  $("#manualStars").querySelectorAll("[data-manual-rating]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextRating = Number(button.dataset.manualRating);
      updateManualMark({ rating: nextRating === rating ? 0 : nextRating, source: "manual", acceptedScore: null }, { advance: markAdvanceEnabled });
    });
  });
  $("#manualColorLabels").innerHTML = manualColorLabels
    .map((item) => {
      const meta = colorLabelMeta(item.value);
      const title = colorLabelTitle(meta);
      return `
        <button
          class="manual-color-choice ${meta.value ? `is-${meta.value}` : "is-clear"} ${colorLabel === meta.value ? "is-active" : ""}"
          type="button"
          data-color-label="${escapeHtml(meta.value)}"
          aria-label="${escapeHtml(title)}"
          data-ui-tooltip="${escapeHtml(title)}"
          ${busy ? "disabled" : ""}
        >
          ${meta.value ? "" : "×"}
        </button>
      `;
    })
    .join("");
  $("#manualColorLabels").querySelectorAll("[data-color-label]").forEach((button) => {
    button.addEventListener("click", () => {
      updateManualMark({ colorLabel: button.dataset.colorLabel || "", source: "manual", acceptedScore: null });
    });
  });
  const statusButtons = [
    ["#manualPickBtn", "pick", "check", t("manual.pick")],
    ["#manualHoldBtn", "hold", "clock", t("manual.hold")],
    ["#manualRejectBtn", "reject", "x", t("manual.reject")],
  ];
  statusButtons.forEach(([selector, value, icon, label]) => {
    const button = $(selector);
    setButtonLabel(button, icon, label);
    button.classList.toggle("is-active", status === value);
    button.disabled = busy;
    button.classList.remove("is-picked", "is-rejected", "is-pending", "is-unreviewed");
    button.classList.add(manualStatusClass(value));
  });
  const sourceText = manual.sourceLabel
    ? `${localizedManualSource(manual)}${manual.acceptedScore != null ? ` · ${localizedMetricText(manual.acceptedScoreText, t("score.noData"))}` : ""}`
    : t("manual.sourceEmpty");
  setText("#manualSourceText", sourceText);
  const advanceToggle = $("#markAdvanceToggle");
  if (advanceToggle) {
    advanceToggle.classList.toggle("is-active", markAdvanceEnabled);
    advanceToggle.setAttribute("aria-pressed", markAdvanceEnabled ? "true" : "false");
    advanceToggle.disabled = busy;
  }
  const modelScore = numericValue(photo?.recommendation);
  const llmScore = numericValue(photo?.llmReviewScores?.llm_review_overall);
  $("#acceptModelBtn").disabled = busy || modelScore == null;
  $("#acceptLlmBtn").disabled = busy || llmScore == null;
}

function filmstripWindow(photos, index, maxItems = 84) {
  if (photos.length <= maxItems) return { start: 0, end: photos.length };
  const safeIndex = clamp(index, 0, photos.length - 1);
  const radius = Math.floor(maxItems / 2);
  let start = safeIndex - radius;
  start = clamp(start, 0, Math.max(0, photos.length - maxItems));
  return { start, end: Math.min(photos.length, start + maxItems) };
}

function renderViewer() {
  const photos = appState?.photos || [];
  const empty = $("#emptyState");
  const stage = $("#viewerStage");
  const filmstrip = $("#filmstrip");

  if (!photos.length) {
    empty.classList.remove("is-hidden");
    stage.classList.add("is-hidden");
    filmstrip.innerHTML = "";
    $("#prevBtn").disabled = true;
    $("#nextBtn").disabled = true;
    return;
  }

  empty.classList.add("is-hidden");
  stage.classList.remove("is-hidden");
  filmstrip.classList.remove("is-hidden");
  const photo = selectedPhoto();
  const mainImage = $("#mainImage");
  mainImage.onload = () => {
    $(".image-stage")?.classList.toggle("is-portrait", mainImage.naturalHeight > mainImage.naturalWidth);
  };
  mainImage.src = photo.preview;
  mainImage.alt = t("viewer.currentPhotoAlt");
  if (mainImage.complete) mainImage.onload();
  const currentLevel = localizedScoreLevel(photo.level);
  setText("#mainScore", photo.recommendationText || photo.overallText);
  setText("#mainStars", photo.recommendationStars || photo.stars);
  setText("#mainLevel", `${currentLevel} · ${selectedIndex + 1} / ${photos.length}`);
  $("#mainLevel").dataset.uiTooltip = `${currentLevel} · ${selectedIndex + 1} / ${photos.length}`;
  $("#mainLevel").removeAttribute("title");
  setText("#viewerCounter", `${selectedIndex + 1} / ${photos.length}`);
  setText("#viewerLevel", currentLevel);
  $("#viewerLevel").dataset.uiTooltip = currentLevel;
  $("#viewerLevel").removeAttribute("title");
  const previewLink = $("#previewLink");
  const nativePreviewSupported = appState?.capabilities?.nativeFilePreview === true;
  previewLink.href = photo.preview;
  previewLink.dataset.nativePreview = nativePreviewSupported ? "true" : "false";
  const previewTitle = nativePreviewSupported ? t("viewer.previewNativeSupported") : t("viewer.previewWebSupported");
  previewLink.setAttribute("aria-label", previewTitle);
  previewLink.dataset.uiTooltip = previewTitle;
  previewLink.removeAttribute("title");
  const revealSupported = appState?.capabilities?.revealInFileManager !== false;
  $("#revealBtn").disabled = !revealSupported;
  const revealTitle = revealSupported ? t("viewer.revealSupported") : t("viewer.revealUnsupported");
  $("#revealBtn").setAttribute("aria-label", revealTitle);
  $("#revealBtn").dataset.uiTooltip = revealTitle;
  $("#revealBtn").removeAttribute("title");
  $("#prevBtn").disabled = selectedIndex <= 0;
  $("#nextBtn").disabled = selectedIndex >= photos.length - 1;
  renderFilmstrip(photos, selectedIndex);
  renderViewerInspector(photo);
}

function moveSelection(delta) {
  const photos = appState?.photos || [];
  if (!photos.length) return;
  const nextIndex = cullingFlow.nextIndexByDelta(photos, selectedIndex, delta);
  if (nextIndex === selectedIndex) return;
  selectedIndex = nextIndex;
  renderViewer();
}

function visibleGallerySelection(photos = appState?.photos || []) {
  const selectedIds = CulviaBatchActions.visibleSelectedIds(photos, [...selectedGalleryIds]);
  if (selectedIds.length !== selectedGalleryIds.size) {
    selectedGalleryIds = new Set(selectedIds);
  }
  if (gallerySelectionAnchorId && !selectedIds.includes(gallerySelectionAnchorId)) {
    const visibleIds = new Set((photos || []).map((photo) => photo.fileId).filter(Boolean));
    if (visibleIds.has(gallerySelectionAnchorId)) return selectedIds;
    gallerySelectionAnchorId = selectedIds[selectedIds.length - 1] || "";
  }
  return selectedIds;
}

function galleryBatchTarget(photos = appState?.photos || []) {
  return CulviaBatchActions.targetFromSelection(photos, visibleGallerySelection(photos));
}

function renderBatchScopePill(rootSelector, labelSelector, target) {
  const root = $(rootSelector);
  if (!root) return;
  setText(labelSelector, CulviaBatchActions.scopeSummary(target));
  root.classList.toggle("is-selected", target.scope === "selected");
  root.classList.toggle("is-filtered", target.scope !== "selected");
  const title = CulviaBatchActions.scopeTitle(target);
  root.dataset.uiTooltip = title;
  root.setAttribute("aria-label", title);
  root.removeAttribute("title");
}

function renderGallerySelectionSummary(photos, selectedIds) {
  const root = $("#gallerySelectionSummary");
  if (!root) return;
  const selectedSet = new Set(selectedIds || []);
  const selectedEntries = (photos || []).map((photo, index) => ({ index, photo })).filter((entry) => selectedSet.has(entry.photo.fileId));
  if (!selectedEntries.length) {
    root.classList.add("is-hidden");
    root.innerHTML = "";
    return;
  }
  const previewLimit = 7;
  const previews = selectedEntries
    .slice(0, previewLimit)
    .map(
      (entry) => {
        const title = pathName(entry.photo.path || entry.photo.filename || t("gallery.photoFallback"));
        return `
          <button class="gallery-selection-thumb" type="button" data-gallery-summary-index="${entry.index}" aria-label="${escapeHtml(t("gallery.viewPhoto", { name: title }))}" data-ui-tooltip="${escapeHtml(title)}">
            <img src="${escapeHtml(entry.photo.thumb)}" alt="" loading="lazy" />
          </button>
        `;
      },
    )
    .join("");
  const overflow = selectedEntries.length > previewLimit ? `<span class="gallery-selection-overflow">+${selectedEntries.length - previewLimit}</span>` : "";
  root.classList.remove("is-hidden");
  root.innerHTML = `
    <div class="gallery-selection-summary-copy">
      <span>${escapeHtml(t("gallery.selectedPhotos"))}</span>
      <strong>${escapeHtml(t("common.photoCount", { count: selectedEntries.length }))}</strong>
    </div>
    <div class="gallery-selection-strip">${previews}${overflow}</div>
  `;
  root.querySelectorAll("[data-gallery-summary-index]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const index = Number(button.dataset.gallerySummaryIndex);
      if (!Number.isInteger(index) || index < 0 || index >= (appState?.photos || []).length) return;
      selectedIndex = index;
      switchView("viewer");
      renderViewer();
    });
  });
}

function renderGalleryBulkToolbar(photos) {
  const target = galleryBatchTarget(photos);
  const selectedIds = visibleGallerySelection(photos);
  const selectedCount = selectedIds.length;
  const allVisibleSelected = Boolean(photos.length) && selectedCount >= photos.length;
  const disabled = !target.count || Boolean(appState?.job?.running);
  setText("#galleryBulkCount", t("common.photoCount", { count: photos.length }));
  setText("#gallerySelectedCount", t("common.photoCount", { count: selectedCount }));
  renderBatchScopePill("#galleryBatchScopeText", "#galleryBatchScopeLabel", target);
  renderGallerySourceStatus();
  renderGalleryThumbnailProgress();
  renderGallerySelectionSummary(photos, selectedIds);
  const selectVisibleButton = $("#gallerySelectVisibleBtn");
  if (selectVisibleButton) selectVisibleButton.disabled = !photos.length || allVisibleSelected || Boolean(appState?.job?.running);
  const clearButton = $("#galleryClearSelectionBtn");
  if (clearButton) clearButton.disabled = !selectedGalleryIds.size || Boolean(appState?.job?.running);
  ["#galleryBatchPickBtn", "#galleryBatchHoldBtn", "#galleryBatchRejectBtn"].forEach((selector) => {
    const button = $(selector);
    if (button) button.disabled = disabled;
  });
}

function renderGallerySourceStatus() {
  const root = $("#gallerySourceStatus");
  if (!root) return;
  if (sourceMode !== "folders") {
    root.className = "gallery-source-status is-hidden";
    root.textContent = "";
    return;
  }
  if (isSourcePreviewActive()) {
    root.className = "gallery-source-status is-scanning";
    root.textContent = t("gallery.sourceScanning");
    return;
  }
  const preview = matchingSourcePreview();
  if (!preview) {
    root.className = "gallery-source-status is-hidden";
    root.textContent = "";
    return;
  }
  const total = Number(preview.total || 0);
  root.className = `gallery-source-status ${total > 0 ? "is-ready" : "is-empty"}`;
  root.textContent = total > 0 ? t("gallery.sourceCount", { count: total }) : t("gallery.sourceEmpty");
}

function galleryThumbnailStats() {
  const images = $$("#galleryGrid [data-gallery-thumb]");
  let loaded = 0;
  let failed = 0;
  images.forEach((image) => {
    const card = image.closest(".photo-card");
    if (card?.classList.contains("is-thumb-error")) {
      failed += 1;
      return;
    }
    if (card?.classList.contains("is-thumb-loaded") || (image.complete && image.naturalWidth > 0)) {
      loaded += 1;
    }
  });
  return {
    failed,
    loaded,
    pending: Math.max(images.length - loaded - failed, 0),
    total: images.length,
  };
}

function renderGalleryThumbnailProgress() {
  const root = $("#galleryThumbProgress");
  if (!root) return;
  const stats = galleryThumbnailStats();
  if (!stats.total || (!stats.pending && !stats.failed)) {
    root.classList.add("is-hidden");
    return;
  }
  const done = Math.min(stats.total, stats.loaded + stats.failed);
  const percent = stats.total ? Math.max(3, Math.min(100, (done / stats.total) * 100)) : 0;
  root.classList.remove("is-hidden");
  setText("#galleryThumbProgressLabel", stats.failed ? t("gallery.thumbProgressFailed", { count: stats.failed }) : t("gallery.thumbProgressLabel"));
  setText("#galleryThumbProgressCount", t("gallery.thumbProgressCount", { done, total: stats.total }));
  const bar = $("#galleryThumbProgressBar");
  if (bar) bar.style.width = `${percent}%`;
}

function syncGalleryThumbnailStates() {
  $$("#galleryGrid [data-gallery-thumb]").forEach((image) => {
    if (!image.complete) return;
    updateGalleryThumbState(image, !(image.naturalWidth > 0));
  });
  renderGalleryThumbnailProgress();
}

function scheduleGalleryThumbnailSync() {
  window.requestAnimationFrame(syncGalleryThumbnailStates);
}

function selectGalleryRange(fileId) {
  const rangeIds = cullingFlow.rangeFileIds(appState?.photos || [], gallerySelectionAnchorId, fileId);
  if (!rangeIds.length) return false;
  rangeIds.forEach((rangeFileId) => selectedGalleryIds.add(rangeFileId));
  gallerySelectionAnchorId = fileId;
  renderGallerySelectionState();
  return true;
}

function toggleGallerySelection(fileId, options = {}) {
  if (!fileId) return;
  if (options.range && gallerySelectionAnchorId && selectGalleryRange(fileId)) return;
  if (selectedGalleryIds.has(fileId)) {
    selectedGalleryIds.delete(fileId);
  } else {
    selectedGalleryIds.add(fileId);
  }
  gallerySelectionAnchorId = fileId;
  renderGallerySelectionState();
}

function clearGallerySelection() {
  if (!selectedGalleryIds.size) return;
  selectedGalleryIds.clear();
  gallerySelectionAnchorId = "";
  renderGallerySelectionState();
}

function selectVisibleGalleryPhotos() {
  const photos = appState?.photos || [];
  if (!photos.length) return;
  photos.forEach((photo) => {
    if (photo.fileId) selectedGalleryIds.add(photo.fileId);
  });
  gallerySelectionAnchorId = photos[photos.length - 1]?.fileId || gallerySelectionAnchorId;
  renderGallerySelectionState();
}

function galleryMarqueeRect(state) {
  const left = Math.min(state.startX, state.currentX);
  const top = Math.min(state.startY, state.currentY);
  const right = Math.max(state.startX, state.currentX);
  const bottom = Math.max(state.startY, state.currentY);
  return {
    bottom,
    height: bottom - top,
    left,
    right,
    top,
    width: right - left,
  };
}

function rectsIntersect(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function cacheGalleryMarqueeTargets() {
  if (!galleryMarqueeState) return;
  const cardByFileId = new Map();
  const cardRects = $$("#galleryGrid .photo-card")
    .map((card) => {
      const index = Number(card.dataset.index);
      const fileId = appState?.photos?.[index]?.fileId || "";
      if (!fileId) return null;
      const rect = card.getBoundingClientRect();
      cardByFileId.set(fileId, card);
      return { fileId, rect };
    })
    .filter(Boolean);
  galleryMarqueeState.cardByFileId = cardByFileId;
  galleryMarqueeState.cardRects = cardRects;
}

function galleryMarqueeTargetIds(rect) {
  const cachedRects = galleryMarqueeState?.cardRects;
  if (cachedRects?.length) {
    return cachedRects
      .filter((entry) => rectsIntersect(rect, entry.rect))
      .map((entry) => entry.fileId);
  }
  return $$("#galleryGrid .photo-card")
    .filter((card) => {
      const cardRect = card.getBoundingClientRect();
      return rectsIntersect(rect, cardRect);
    })
    .map((card) => {
      const index = Number(card.dataset.index);
      return appState?.photos?.[index]?.fileId || "";
    })
    .filter(Boolean);
}

function clearGalleryMarqueePreview() {
  const previewIds = galleryMarqueeState?.previewIds;
  const cardByFileId = galleryMarqueeState?.cardByFileId;
  if (previewIds?.size && cardByFileId?.size) {
    previewIds.forEach((fileId) => cardByFileId.get(fileId)?.classList.remove("is-marquee-target"));
    galleryMarqueeState.previewIds = new Set();
    return;
  }
  $$("#galleryGrid .photo-card.is-marquee-target").forEach((card) => card.classList.remove("is-marquee-target"));
}

function applyGalleryMarqueePreview(targetIds) {
  const targetSet = new Set(targetIds);
  const previousSet = galleryMarqueeState?.previewIds || new Set();
  const cardByFileId = galleryMarqueeState?.cardByFileId;
  if (cardByFileId?.size) {
    previousSet.forEach((fileId) => {
      if (!targetSet.has(fileId)) cardByFileId.get(fileId)?.classList.remove("is-marquee-target");
    });
    targetSet.forEach((fileId) => {
      if (!previousSet.has(fileId)) cardByFileId.get(fileId)?.classList.add("is-marquee-target");
    });
    galleryMarqueeState.previewIds = targetSet;
    return;
  }
  $$("#galleryGrid .photo-card").forEach((card) => {
    const index = Number(card.dataset.index);
    const fileId = appState?.photos?.[index]?.fileId || "";
    card.classList.toggle("is-marquee-target", targetSet.has(fileId));
  });
}

function updateGalleryMarqueeBox(rect) {
  const marquee = $("#gallerySelectionMarquee");
  if (!marquee) return;
  marquee.classList.toggle("is-hidden", rect.width < 1 || rect.height < 1);
  marquee.style.left = `${rect.left}px`;
  marquee.style.top = `${rect.top}px`;
  marquee.style.width = `${rect.width}px`;
  marquee.style.height = `${rect.height}px`;
}

function resetGalleryMarquee() {
  if (galleryMarqueeState?.raf) window.cancelAnimationFrame(galleryMarqueeState.raf);
  document.body.classList.remove("is-gallery-marquee-selecting");
  clearGalleryMarqueePreview();
  galleryMarqueeState = null;
  const marquee = $("#gallerySelectionMarquee");
  if (marquee) {
    marquee.classList.add("is-hidden");
    marquee.removeAttribute("style");
  }
}

function isGalleryMarqueeStartArea(event) {
  if (activeView !== "gallery") return false;
  const workspace = event.currentTarget?.closest?.(".workspace") || $(".workspace");
  const grid = $("#galleryGrid");
  const workspaceRect = workspace?.getBoundingClientRect();
  const gridRect = grid?.getBoundingClientRect();
  if (!workspaceRect || !gridRect || gridRect.width < 1 || gridRect.height < 1) return false;
  const top = gridRect.top - 36;
  return event.clientX >= workspaceRect.left
    && event.clientX <= workspaceRect.right
    && event.clientY >= top
    && event.clientY <= gridRect.bottom;
}

function beginGalleryMarquee(event) {
  if (event.button !== 0 || event.pointerType === "touch" || !appState?.photos?.length || appState?.job?.running) return;
  if (event.target?.closest?.("button, a, input, textarea, select, summary")) return;
  if (event.target?.closest?.(".topbar, .command-center, .stats-grid, .view-tabs, .filter-scope-bar, .gallery-bulk-toolbar, .gallery-selection-summary")) return;
  if (!isGalleryMarqueeStartArea(event)) return;
  galleryMarqueeState = {
    additive: Boolean(event.shiftKey || event.metaKey || event.ctrlKey),
    baseSelectedIds: new Set(selectedGalleryIds),
    cardByFileId: new Map(),
    cardRects: [],
    currentIds: [],
    currentX: event.clientX,
    currentY: event.clientY,
    dragging: false,
    pointerId: event.pointerId,
    previewIds: new Set(),
    raf: 0,
    startX: event.clientX,
    startY: event.clientY,
  };
  window.addEventListener("pointermove", updateGalleryMarquee, { passive: false });
  window.addEventListener("pointerup", finishGalleryMarquee, { once: true });
  window.addEventListener("pointercancel", cancelGalleryMarquee, { once: true });
}

function flushGalleryMarqueeUpdate() {
  if (!galleryMarqueeState) return;
  galleryMarqueeState.raf = 0;
  const rect = galleryMarqueeRect(galleryMarqueeState);
  galleryMarqueeState.currentIds = galleryMarqueeTargetIds(rect);
  updateGalleryMarqueeBox(rect);
  applyGalleryMarqueePreview(galleryMarqueeState.currentIds);
}

function updateGalleryMarquee(event) {
  if (!galleryMarqueeState || event.pointerId !== galleryMarqueeState.pointerId) return;
  galleryMarqueeState.currentX = event.clientX;
  galleryMarqueeState.currentY = event.clientY;
  const distance = Math.hypot(galleryMarqueeState.currentX - galleryMarqueeState.startX, galleryMarqueeState.currentY - galleryMarqueeState.startY);
  if (!galleryMarqueeState.dragging && distance < 6) return;
  if (!galleryMarqueeState.dragging) {
    galleryMarqueeState.dragging = true;
    document.body.classList.add("is-gallery-marquee-selecting");
    cacheGalleryMarqueeTargets();
  }
  event.preventDefault();
  if (!galleryMarqueeState.raf) {
    galleryMarqueeState.raf = window.requestAnimationFrame(flushGalleryMarqueeUpdate);
  }
}

function finishGalleryMarquee(event) {
  window.removeEventListener("pointermove", updateGalleryMarquee);
  window.removeEventListener("pointercancel", cancelGalleryMarquee);
  if (!galleryMarqueeState || event.pointerId !== galleryMarqueeState.pointerId) {
    resetGalleryMarquee();
    return;
  }
  if (!galleryMarqueeState.dragging) {
    resetGalleryMarquee();
    return;
  }
  event.preventDefault();
  if (galleryMarqueeState.raf) {
    window.cancelAnimationFrame(galleryMarqueeState.raf);
    flushGalleryMarqueeUpdate();
  }
  const nextSelected = galleryMarqueeState.additive ? new Set(galleryMarqueeState.baseSelectedIds) : new Set();
  galleryMarqueeState.currentIds.forEach((fileId) => nextSelected.add(fileId));
  selectedGalleryIds = nextSelected;
  gallerySelectionAnchorId = galleryMarqueeState.currentIds[galleryMarqueeState.currentIds.length - 1] || gallerySelectionAnchorId;
  gallerySuppressNextCardClick = true;
  window.setTimeout(() => {
    gallerySuppressNextCardClick = false;
  }, 160);
  resetGalleryMarquee();
  renderGallerySelectionState();
}

function cancelGalleryMarquee() {
  window.removeEventListener("pointermove", updateGalleryMarquee);
  window.removeEventListener("pointerup", finishGalleryMarquee);
  resetGalleryMarquee();
}

function galleryCardSignature(photo) {
  return galleryView.cardSignature(photo, i18n?.language?.() || "");
}

function galleryTooltipMarkup(photo) {
  return galleryView.tooltipMarkup(photo, {
    localizedManualSource,
    localizedMetricText,
    localizedScoreLevel,
    localizedTechnicalTag,
    manualStars,
    manualStatusLabel,
    t,
  });
}

function galleryCardMarkup(photo, index, selected, signature) {
  return galleryView.cardMarkup(photo, index, selected, signature, {
    disabled: Boolean(appState?.job?.running),
    galleryColorBadgeMarkup,
    galleryQuickActionLabel,
    gallerySelectLabel,
    localizedScoreLevel,
    t,
  });
}

function createGalleryCard(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  return template.content.firstElementChild;
}

function updateGalleryCardSelectionState(card, photo, index, selected) {
  galleryView.updateSelectionState(card, photo, index, selected, {
    disabled: Boolean(appState?.job?.running),
    gallerySelectLabel,
  });
}

function renderGallerySelectionState(photos = appState?.photos || []) {
  const grid = $("#galleryGrid");
  renderGalleryBulkToolbar(photos);
  if (!grid) return;
  const photosById = new Map((photos || []).map((photo, index) => [photo.fileId, { index, photo }]));
  grid.querySelectorAll(".photo-card[data-file-id]").forEach((card) => {
    const entry = photosById.get(card.dataset.fileId || "");
    if (!entry) return;
    updateGalleryCardSelectionState(card, entry.photo, entry.index, selectedGalleryIds.has(entry.photo.fileId));
  });
}

function renderGallery() {
  const photos = appState?.photos || [];
  const grid = $("#galleryGrid");
  renderGalleryBulkToolbar(photos);
  if (isSourcePreviewActive()) {
    grid.replaceChildren(createGalleryCard(galleryView.loadingStateMarkup({
      state: t("source.previewScanningState"),
      text: t("source.previewScanningDetail"),
      title: t("source.previewScanningTitle"),
    })));
    renderGalleryThumbnailProgress();
    return;
  }
  if (!photos.length) {
    grid.replaceChildren(createGalleryCard(galleryView.emptyStateMarkup({
      text: t("gallery.emptyText"),
      title: t("gallery.emptyTitle"),
    })));
    renderGalleryThumbnailProgress();
    return;
  }
  const orderedCards = Array.from(grid.querySelectorAll(".photo-card[data-file-id]"));
  const orderMatches = orderedCards.length === photos.length && orderedCards.every((card, index) => card.dataset.fileId === photos[index]?.fileId);
  if (orderMatches) {
    photos.forEach((photo, index) => {
      const selected = selectedGalleryIds.has(photo.fileId);
      const signature = galleryCardSignature(photo);
      const card = orderedCards[index];
      if (card.dataset.gallerySignature !== signature) {
        card.replaceWith(createGalleryCard(galleryCardMarkup(photo, index, selected, signature)));
        return;
      }
      updateGalleryCardSelectionState(card, photo, index, selected);
    });
    scheduleGalleryThumbnailSync();
    return;
  }
  const existingCards = new Map(
    Array.from(grid.querySelectorAll(".photo-card[data-file-id]")).map((card) => [card.dataset.fileId, card]),
  );
  const fragment = document.createDocumentFragment();
  photos.forEach((photo, index) => {
    const selected = selectedGalleryIds.has(photo.fileId);
    const signature = galleryCardSignature(photo);
    let card = existingCards.get(photo.fileId);
    if (!card || card.dataset.gallerySignature !== signature) {
      card = createGalleryCard(galleryCardMarkup(photo, index, selected, signature));
    } else {
      updateGalleryCardSelectionState(card, photo, index, selected);
    }
    fragment.appendChild(card);
  });
  grid.replaceChildren(fragment);
  scheduleGalleryThumbnailSync();
}

function updateGalleryThumbState(image, failed) {
  const card = image?.closest?.(".photo-card");
  if (!card) return;
  card.classList.toggle("is-thumb-error", failed);
  card.classList.toggle("is-thumb-loaded", !failed);
}

function handleGalleryImageLoad(event) {
  const image = event.target?.closest?.("[data-gallery-thumb]");
  if (!image) return;
  delete image.dataset.galleryRetry;
  updateGalleryThumbState(image, false);
  renderGalleryThumbnailProgress();
}

function handleGalleryImageError(event) {
  const image = event.target?.closest?.("[data-gallery-thumb]");
  if (!image) return;
  if (!image.dataset.galleryRetry) {
    image.dataset.galleryRetry = "1";
    window.setTimeout(() => {
      if (!image.isConnected) return;
      const retryUrl = new URL(image.currentSrc || image.src, window.location.href);
      retryUrl.searchParams.set("retry", String(Date.now()));
      image.src = retryUrl.pathname + retryUrl.search;
    }, 700);
    return;
  }
  updateGalleryThumbState(image, true);
  renderGalleryThumbnailProgress();
}

function handleGalleryGridClick(event) {
  const statusButton = event.target?.closest?.("[data-gallery-status]");
  if (statusButton) {
    if (appState?.job?.running) return;
    event.stopPropagation();
    const fileId = statusButton.dataset.fileId || "";
    const photo = (appState?.photos || []).find((item) => item?.fileId === fileId);
    updatePhotoMark(
      fileId,
      statusToggleChanges(
        { status: statusButton.dataset.galleryStatus || "", source: "manual", acceptedScore: null },
        photo?.manual?.status || "",
      ),
    );
    return;
  }
  const selectButton = event.target?.closest?.("[data-gallery-select]");
  if (selectButton) {
    if (appState?.job?.running) return;
    event.stopPropagation();
    toggleGallerySelection(selectButton.dataset.gallerySelect || "", { range: event.shiftKey });
    return;
  }
  const card = event.target?.closest?.("#galleryGrid .photo-card");
  if (!card) return;
  if (gallerySuppressNextCardClick) {
    gallerySuppressNextCardClick = false;
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  selectedIndex = Number(card.dataset.index);
  switchView("viewer");
  renderViewer();
}

function visibleElement(selector) {
  return Array.from(document.querySelectorAll(selector)).find((element) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }) || null;
}

function rectanglesIntersect(first, second) {
  return !!(first && second && !(
    first.right <= second.left ||
    first.left >= second.right ||
    first.bottom <= second.top ||
    first.top >= second.bottom
  ));
}

function ensureGalleryRatingTooltip(rating) {
  const card = rating?.closest?.("#galleryGrid .photo-card");
  if (!card) return null;
  card.classList.add("is-tooltip-open");
  let tooltip = rating.querySelector(".rating-tooltip");
  if (tooltip) return tooltip;
  const index = Number(card.dataset.index);
  const photo = appState?.photos?.[index];
  if (!photo) return null;
  const tooltipNode = createGalleryCard(galleryTooltipMarkup(photo));
  rating.appendChild(tooltipNode);
  return tooltipNode;
}

function placeGalleryRatingTooltip(rating) {
  const tooltip = ensureGalleryRatingTooltip(rating);
  if (!tooltip) return;
  tooltip.classList.remove("is-placement-below");
  const toolbar = visibleElement(".gallery-bulk-toolbar");
  if (!toolbar) return;
  const tooltipRect = tooltip.getBoundingClientRect();
  const toolbarRect = toolbar.getBoundingClientRect();
  const hitsToolbar = rectanglesIntersect(tooltipRect, toolbarRect);
  if (hitsToolbar || tooltipRect.top < toolbarRect.bottom + 8) {
    tooltip.classList.add("is-placement-below");
  }
}

function handleGalleryTooltipIntent(event) {
  const rating = event.target?.closest?.("#galleryGrid .gallery-rating");
  if (!rating) return;
  placeGalleryRatingTooltip(rating);
}

function clearGalleryTooltipPlacement(event) {
  const rating = event.target?.closest?.("#galleryGrid .gallery-rating");
  if (!rating) return;
  const nextTarget = event.relatedTarget;
  if (nextTarget && rating.contains(nextTarget)) return;
  rating.closest(".photo-card")?.classList.remove("is-tooltip-open");
  rating.querySelector(".rating-tooltip")?.remove();
}

function renderDistribution() {
  const container = $("#distributionChart");
  if (!container) return;
  const lens = distributionLensOptions.some((option) => option.value === distributionLens) ? distributionLens : "overview";
  const config = distributionLensConfig(lens);
  const allEntries = distributionEntries(appState?.photos || []);
  const entries = allEntries
    .map((entry) => ({ ...entry, score: config.primary(entry), x: config.x(entry), y: config.y(entry) }))
    .filter((entry) => entry.score != null);
  container.className = `distribution-studio lens-${lens}`;

  const lensControls = `
    <div class="distribution-lenses" role="tablist" aria-label="${escapeHtml(t("distribution.lensAria"))}">
      ${distributionLensOptions
        .map((option) => {
          const label = tr(option.labelKey, {}, option.label);
          const meta = distributionLensMeta(option.value, allEntries);
          return `
            <button
              class="distribution-lens ${option.value === lens ? "is-active" : ""}"
              type="button"
              role="tab"
              aria-selected="${option.value === lens ? "true" : "false"}"
              data-distribution-lens="${option.value}"
              data-ui-tooltip="${escapeHtml(`${label} · ${meta}`)}"
            >
              <span class="distribution-lens-icon">${iconMarkup(option.icon)}</span>
              <span class="distribution-lens-copy">
                <strong>${escapeHtml(label)}</strong>
                <small>${escapeHtml(meta)}</small>
              </span>
            </button>
          `;
        })
        .join("")}
    </div>
  `;

  if (!entries.length) {
    container.innerHTML = `
      ${renderMetricRadar(allEntries)}
      <div class="distribution-view-layout" aria-label="${escapeHtml(t("distribution.layoutAria"))}">
        ${lensControls}
        <section class="distribution-view-content" aria-label="${escapeHtml(t("distribution.contentAria"))}">
          <div class="distribution-empty is-compact">
            <div class="empty-symbol">${iconMarkup("barChart", "empty-icon")}</div>
            <h2>${escapeHtml(config.empty)}</h2>
            <p>${escapeHtml(t("distribution.switchHint"))}</p>
          </div>
        </section>
      </div>
    `;
    bindDistributionControls(container);
    return;
  }

  const values = entries.map((entry) => entry.score);
  const stats = distributionStats(values);
  const total = entries.length;
  const passCount = entries.filter((entry) => entry.score >= config.passThreshold).length;
  const topCount = entries.filter((entry) => entry.score >= config.topThreshold).length;
  const buckets = scoreBuckets(values, 24);
  const wave = bucketWave(buckets, 38);
  const peakBucket = wave.peak;
  const peakLabel = `${peakBucket.min.toFixed(1)}-${peakBucket.max.toFixed(1)}`;
  const topRatio = Math.round((topCount / total) * 100);

  const tierKeys = ["elite", "strong", "watch", "quiet"];
  const tiers = tierKeys
    .map((key) => {
      const meta = distributionTierMeta(key, lens);
      const items = entries.filter((entry) => distributionTier(entry.score, lens) === key).sort((a, b) => b.score - a.score);
      const ratio = Math.round((items.length / total) * 100);
      const previews = items.length
        ? items
            .slice(0, 4)
            .map(
              (entry) => `
                <button class="tier-thumb" type="button" data-photo-index="${entry.index}" aria-label="${escapeHtml(pathName(entry.photo.path))}" data-ui-tooltip="${escapeHtml(pathName(entry.photo.path))}">
                  <img src="${entry.photo.thumb}" alt="${escapeHtml(t("distribution.thumbAlt"))}" loading="lazy" />
                  <span>${scoreValue(entry.score)}</span>
                </button>
              `,
            )
            .join("")
        : `<div class="tier-empty">${escapeHtml(t("distribution.empty"))}</div>`;
      return `
        <article class="distribution-tier tone-${key}">
          <div class="tier-head">
            <span>${iconMarkup(meta.icon)}</span>
            <div>
              <strong>${meta.label}</strong>
              <small>${meta.range}</small>
            </div>
          </div>
          <div class="tier-count">
            <strong>${items.length}</strong>
            <span>${ratio}%</span>
          </div>
          <div class="tier-thumbs">${previews}</div>
          <p>${meta.copy}</p>
        </article>
      `;
    })
    .join("");

  container.innerHTML = `
    ${renderMetricRadar(allEntries)}

    <div class="distribution-view-layout" aria-label="${escapeHtml(t("distribution.layoutAria"))}">
      ${lensControls}
      <section class="distribution-view-content" aria-label="${escapeHtml(t("distribution.contentAria"))}">
        <div class="distribution-head is-compact">
          <div>
            <div class="section-kicker">${escapeHtml(config.kicker)}</div>
            <h2>${escapeHtml(config.title)}</h2>
            <p>${escapeHtml(t("distribution.viewSummary", { peak: peakLabel, ratio: topRatio, total }))}</p>
          </div>
          <div class="distribution-score">
            <span>${escapeHtml(config.summaryLabel)}</span>
            <strong>${scoreValue(stats.average)}</strong>
            <small>${escapeHtml(t("distribution.medianBest", { best: scoreValue(stats.best), median: scoreValue(stats.median) }))}</small>
          </div>
        </div>

        ${distributionDecision(lens, entries, allEntries, config, stats, passCount, topCount, peakLabel)}
        ${renderDimensionStack(lens, entries, config)}

        <section class="tier-board" aria-label="${escapeHtml(t("distribution.tierAria"))}">
          ${tiers}
        </section>
      </section>
    </div>
  `;

  bindDistributionControls(container);
}

function bindDistributionControls(container) {
  container.querySelectorAll("[data-distribution-lens]").forEach((button) => {
    button.addEventListener("click", () => {
      distributionLens = button.dataset.distributionLens || "overview";
      renderDistribution();
    });
  });
  container.querySelectorAll("[data-distribution-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.distributionAction || "";
      if (["gallery", "export", "viewer"].includes(action)) {
        switchView(action);
        return;
      }
      if (distributionLensOptions.some((option) => option.value === action)) {
        distributionLens = action;
        renderDistribution();
      }
    });
  });
  container.querySelectorAll("[data-photo-index]").forEach((node) => {
    node.addEventListener("click", () => {
      selectedIndex = Number(node.dataset.photoIndex);
      switchView("viewer");
      renderViewer();
    });
  });
}

function setMeterWidth(selector, value, total) {
  const node = $(selector);
  if (!node) return;
  const percent = total > 0 ? clamp(value / total, 0, 1) * 100 : 0;
  node.style.width = `${percent}%`;
}

function renderDeliveryOverview(all = {}, visible = {}) {
  const allTotal = Number(appState?.summary?.scored || 0);
  const visibleTotal = Number(appState?.summary?.showing || (appState?.photos || []).length || 0);
  const selected = Number(all.selected || 0);
  const rejected = Number(all.rejected || 0);
  const pending = Math.max(allTotal - selected - rejected, 0);
  const visiblePending = Math.max(visibleTotal - Number(visible.selected || 0) - Number(visible.rejected || 0), 0);
  const decided = selected + rejected;
  setText("#deliveryReadyCount", t("common.photoCount", { count: selected }));
  setText("#deliveryPickCount", selected);
  setText("#deliveryPendingCount", pending);
  setText("#deliveryRejectCount", rejected);
  setText("#deliveryVisiblePendingCount", visiblePending);
  const guidance = !allTotal
    ? t("export.guidanceEmpty")
    : selected
      ? t("export.guidanceReady", { pending, selected })
      : t("export.guidancePending", { pending });
  setText("#deliveryGuidance", guidance);
  setMeterWidth("#deliveryMeterPick", selected, allTotal);
  setMeterWidth("#deliveryMeterPending", pending, allTotal);
  setMeterWidth("#deliveryMeterReject", rejected, allTotal);
  $(".delivery-overview")?.classList.toggle("is-empty", !allTotal);
  $(".delivery-overview")?.classList.toggle("is-ready", selected > 0);
  $(".delivery-overview")?.classList.toggle("is-decided", allTotal > 0 && decided >= allTotal);
}

function exportPreflightMarkup() {
  return CulviaExportPreflight.renderMarkup(
    {
      destination: exportDestination,
      error: exportPreflightError,
      loading: exportPreflightLoading,
      preflight: exportPreflight,
    },
    {
      escapeHtml,
      iconMarkup,
      parentPath,
      pathName,
    },
  );
}

function currentExportPreflightKey() {
  return CulviaExportPreflight.currentKey(exportDestination, appState?.selectedPhotos || []);
}

function applyExportPreflightState(next) {
  if (!next) return;
  if (Object.prototype.hasOwnProperty.call(next, "preflight")) exportPreflight = next.preflight;
  if (Object.prototype.hasOwnProperty.call(next, "loading")) exportPreflightLoading = next.loading;
  if (Object.prototype.hasOwnProperty.call(next, "error")) exportPreflightError = next.error;
  if (Object.prototype.hasOwnProperty.call(next, "key")) exportPreflightKey = next.key;
}

function exportResultMarkup() {
  return CulviaExportResult.renderMarkup(exportResult, {
    canRevealDestination: appState?.capabilities?.revealInFileManager !== false,
    escapeHtml,
    iconMarkup,
    parentPath,
    pathName,
  });
}

function bindBatchColorChoices(container) {
  container.querySelectorAll("[data-batch-color]").forEach((button) => {
    button.addEventListener("click", () => applyBatchColor(button.dataset.batchColor || "", galleryBatchTarget(appState?.photos || [])));
  });
}

function renderExportBatchColorChoices(batchActions) {
  const container = $("#batchColorLabels");
  if (!container) return;
  const localizedColorLabels = manualColorLabels.map((item) => colorLabelMeta(item.value));
  container.innerHTML = CulviaBatchActions.colorChoiceViews(localizedColorLabels, {
    disabled: !batchActions.hasPhotos,
  })
    .map(
      (item) => `
        <button
          class="${escapeHtml(item.className)}"
          type="button"
          data-batch-color="${escapeHtml(item.value)}"
          aria-label="${escapeHtml(item.title)}"
          data-ui-tooltip="${escapeHtml(item.title)}"
          ${item.disabled ? "disabled" : ""}
        >${escapeHtml(item.text)}</button>
      `,
    )
    .join("");
  bindBatchColorChoices(container);
}

function bindExportListRevealActions(list, photos) {
  list.querySelectorAll(".reveal-list").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.getAttribute("aria-disabled") === "true") return;
      revealPhoto(CulviaExportList.photoForReveal(photos, button.dataset.exportListIndex));
    });
  });
}

function renderExportSelectedList(list, photos) {
  list.innerHTML = CulviaExportList.renderMarkup(photos, {
    canRevealFile: appState?.capabilities?.revealInFileManager !== false,
    escapeHtml,
    iconMarkup,
    localizedScoreLevel,
    manualBadgeMarkup,
    pathName,
  });
  bindExportListRevealActions(list, photos);
}

function isExportDestinationBlocked() {
  return CulviaExportPreflightState.exportBlocked({
    error: exportPreflightError,
    loading: exportPreflightLoading,
    preflight: exportPreflight,
  });
}

function updateExportActionControls(all, batchActions) {
  const busy = Boolean(appState?.job?.running);
  const exportAction = CulviaExportActions.primaryActionView({
    blocked: isExportDestinationBlocked(),
    destination: exportDestination,
    preflight: exportPreflight,
    preflightError: exportPreflightError,
    preflightLoading: exportPreflightLoading,
    selectedCount: all.selected,
    statusText: exportStatusText,
  });
  setButtonLabel($("#exportSelectedBtn"), exportAction.icon, exportAction.label);
  $("#exportSelectedBtn").disabled = busy || exportAction.disabled;
  setText("#exportSelectedHint", exportAction.hint);
  setButtonLabel($("#acceptFilteredModelBtn"), batchActions.model.icon, batchActions.model.label);
  setButtonLabel($("#acceptFilteredLlmBtn"), batchActions.llm.icon, batchActions.llm.label);
  $("#acceptFilteredModelBtn").disabled = busy || batchActions.model.disabled;
  $("#acceptFilteredLlmBtn").disabled = busy || batchActions.llm.disabled;
  const destinationButton = $("#pickExportFolderBtn");
  if (destinationButton) destinationButton.disabled = busy;
}

function renderExportList() {
  const photos = appState?.selectedPhotos || [];
  const visiblePhotos = appState?.photos || [];
  const batchTarget = galleryBatchTarget(visiblePhotos);
  const list = $("#exportList");
  const all = appState?.curation?.all || {};
  const visible = appState?.curation?.visible || {};
  const preflightKey = currentExportPreflightKey();
  if (
    CulviaExportPreflightState.shouldRefresh({
      activeView,
      currentKey: preflightKey,
      destination: exportDestination,
      loading: exportPreflightLoading,
      storedKey: exportPreflightKey,
    })
  ) {
    applyExportPreflightState({ key: preflightKey });
    void refreshExportPreflight({ key: preflightKey });
  }
  renderDeliveryOverview(all, visible);
  setText(
    "#curationSummaryText",
    t("export.curationSummary", {
      rated: all.rated || 0,
      selected: all.selected || 0,
      visibleSelected: visible.selected || 0,
    }),
  );
  const destinationText = exportDestination ? `${pathName(exportDestination)} · ${parentPath(exportDestination)}` : t("export.destinationEmpty");
  setTextWithHint("#exportDestinationText", destinationText);
  const preflightNode = $("#exportPreflight");
  if (preflightNode) preflightNode.innerHTML = exportPreflightMarkup();
  const exportResultNode = $("#exportResult");
  if (exportResultNode) exportResultNode.innerHTML = exportResultMarkup();
  renderBatchScopePill("#exportBatchScopeText", "#exportBatchScopeLabel", batchTarget);
  const batchActions = CulviaBatchActions.acceptControls(batchTarget, visiblePhotos, {
    hasLlmReview: (photo) => numericValue(photo.llmReviewScores?.llm_review_overall) != null,
  });
  updateExportActionControls(all, batchActions);
  renderExportBatchColorChoices(batchActions);
  renderExportSelectedList(list, photos);
}

function renderControls() {
  if (!appState) return;
  const capabilities = appState.capabilities || {};
  const busy = Boolean(appState.job?.running);
  $("#devicePill").innerHTML = `${iconMarkup("cpu")}${escapeHtml(appState.app.device)}`;
  const nativeFolderButton = $("#pickNativeFolderBtn");
  const nativeFolderSupported = capabilities.nativeFolderPicker !== false;
  const nativeFolderLabel = nativeFolderSupported ? t("source.pickFolder") : t("source.pathOnly");
  nativeFolderButton.disabled = !nativeFolderSupported || busy;
  nativeFolderButton.dataset.uiTooltip = nativeFolderLabel;
  nativeFolderButton.removeAttribute("title");
  nativeFolderButton.setAttribute("aria-label", nativeFolderLabel);
  nativeFolderButton.classList.toggle("is-unavailable", !nativeFolderSupported);
  const folderInput = $("#folderInput");
  if (folderInput) folderInput.disabled = busy;
  const folderAddInput = $("#folderAddInput");
  if (folderAddInput) folderAddInput.disabled = busy;
  $("#folderAddBtn").disabled = busy;
  $("#clearFoldersBtn").disabled = busy || !foldersFromInput().length;
  const cacheInput = $("#cacheInput");
  if (cacheInput) cacheInput.disabled = busy;
  ["#pickFilesBtn", "#pickFolderBtn", "#fileInput", "#folderPicker"].forEach((selector) => {
    const control = $(selector);
    if (control) control.disabled = busy;
  });
  $$("[data-source]").forEach((button) => {
    button.disabled = busy;
  });
  if (!sourceInputsDirty && !folderEditorHasFocus()) {
    syncFolderInputFromList(appState.source.folders || []);
    renderSourceFolderList(appState.source.folders || [], busy);
  } else {
    renderSourceFolderList(foldersFromInput(), busy);
  }
  if (!sourceInputsDirty && document.activeElement !== $("#cacheInput")) {
    $("#cacheInput").value = appState.source.cachePath || "";
  }
  updatePathSummaries();
  renderLlmConfig();
  const selectedSort = appState.filters.sortField || "recommendation_0_10";
  $("#sortField").value = selectedSort;
  $("#sortOptions").innerHTML = (appState.sortOptions || [])
    .map(
      (option) => `
        <button
          class="sort-option ${option.value === selectedSort ? "is-active" : ""}"
          type="button"
          role="radio"
          aria-checked="${option.value === selectedSort ? "true" : "false"}"
          data-sort="${option.value}"
        >${escapeHtml(localizedSortOption(option))}</button>
      `,
    )
    .join("");
  $("#sortOptions").querySelectorAll("[data-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#sortField").value = button.dataset.sort;
      scheduleFilterUpdate();
    });
  });
  const selectedPreset = appState.filters.weightPreset || "balanced";
  $("#weightPreset").value = selectedPreset;
  $("#weightPresetOptions").innerHTML = (appState.weightPresets || [])
    .map(
      (option) => `
        <button
          class="preference-option ${option.value === selectedPreset ? "is-active" : ""}"
          type="button"
          role="radio"
          aria-checked="${option.value === selectedPreset ? "true" : "false"}"
          data-preset="${option.value}"
        >${escapeHtml(localizedWeightPreset(option))}</button>
      `,
    )
    .join("");
  $("#weightPresetOptions").querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#weightPreset").value = button.dataset.preset;
      scheduleFilterUpdate();
    });
  });
  const customWeights = appState.filters.customWeights || {};
  $("#aestheticWeight").value = customWeights.aesthetic ?? 0.6;
  $("#technicalWeight").value = customWeights.technical ?? 0.25;
  $("#compositionLightWeight").value = customWeights.compositionLight ?? 0.15;
  setText("#aestheticWeightText", percentValue($("#aestheticWeight").value));
  setText("#technicalWeightText", percentValue($("#technicalWeight").value));
  setText("#compositionLightWeightText", percentValue($("#compositionLightWeight").value));
  $("#customWeights").classList.toggle("is-hidden", selectedPreset !== "custom");
  $("#minScore").value = appState.filters.minScore ?? 0;
  setText("#minScoreText", Number(appState.filters.minScore ?? 0).toFixed(1));
  $("#minModelQuality").value = appState.filters.minModelQuality ?? 0;
  setText("#minModelQualityText", Number(appState.filters.minModelQuality ?? 0).toFixed(1));
  $("#minAestheticReference").value = appState.filters.minAestheticReference ?? 0;
  setText("#minAestheticReferenceText", Number(appState.filters.minAestheticReference ?? 0).toFixed(1));
  $("#minTechnical").value = appState.filters.minTechnical ?? 0;
  setText("#minTechnicalText", Number(appState.filters.minTechnical ?? 0).toFixed(1));
  $("#minLlmReview").value = appState.filters.minLlmReview ?? 0;
  setText("#minLlmReviewText", Number(appState.filters.minLlmReview ?? 0).toFixed(1));
  const selectedAgreement = appState.filters.modelAgreement || "all";
  $("#modelAgreement").value = selectedAgreement;
  $("#modelAgreementOptions").innerHTML = (appState.modelAgreementOptions || [])
    .map(
      (option) => `
        <button
          class="filter-option ${option.value === selectedAgreement ? "is-active" : ""}"
          type="button"
          role="radio"
          aria-checked="${option.value === selectedAgreement ? "true" : "false"}"
          data-agreement="${option.value}"
        >${escapeHtml(localizedAgreementOption(option))}</button>
      `,
    )
    .join("");
  $("#modelAgreementOptions").querySelectorAll("[data-agreement]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#modelAgreement").value = button.dataset.agreement;
      scheduleFilterUpdate();
    });
  });
  const selectedManualStatus = appState.filters.manualStatus || "all";
  $("#manualStatusFilter").value = selectedManualStatus;
  $("#manualStatusOptions").innerHTML = (appState.manualStatusOptions || [])
    .map(
      (option) => `
        <button
          class="filter-option ${option.value === selectedManualStatus ? "is-active" : ""}"
          type="button"
          role="radio"
          aria-checked="${option.value === selectedManualStatus ? "true" : "false"}"
          data-manual-status="${option.value}"
        >${escapeHtml(localizedManualFilterOption(option))}</button>
      `,
    )
    .join("");
  $("#manualStatusOptions").querySelectorAll("[data-manual-status]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#manualStatusFilter").value = button.dataset.manualStatus;
      scheduleFilterUpdate();
    });
  });
  const selectedColorLabel = appState.filters.colorLabel || "all";
  $("#colorLabelFilter").value = selectedColorLabel;
  $("#colorLabelOptions").innerHTML = (appState.colorLabelOptions || [])
    .map(
      (option) => `
        <button
          class="filter-option color-filter-option ${option.value === selectedColorLabel ? "is-active" : ""}"
          type="button"
          role="radio"
          aria-checked="${option.value === selectedColorLabel ? "true" : "false"}"
          data-color-filter="${escapeHtml(option.value)}"
        >
          ${colorLabelDot(option.value)}
          <span>${escapeHtml(localizedColorFilterOption(option))}</span>
        </button>
      `,
    )
    .join("");
  $("#colorLabelOptions").querySelectorAll("[data-color-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#colorLabelFilter").value = button.dataset.colorFilter;
      scheduleFilterUpdate();
    });
  });
  $("#limitInput").value = appState.filters.limit ?? 80;
  setSourceMode(sourceInputsDirty ? sourceMode : appState.source.mode || sourceMode);
  setNetworkMode(appState.network?.mode || "direct", false);
  renderModelOptions();
  renderFilterPresets();
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
  llmModelMenuOpen = false;
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
  const sourceSnapshot = sourceInputsDirty ? sourceInputSnapshot() : null;
  appState = await getJson("/api/state");
  if (!filterRestoreAttempted && !appState.job?.running) {
    filterRestoreAttempted = true;
    const savedFilters = savedFilterPayload();
    if (savedFilters && !filtersAreDefault(savedFilters) && filtersAreDefault(appState.filters)) {
      try {
        appState = await postJson("/api/filter", savedFilters);
      } catch (_error) {
        localStorage.removeItem(FILTER_STORAGE_KEY);
      }
    }
  }
  if (sourceSnapshot) applySourceInputSnapshot(sourceSnapshot);
  persistFilterPayload(appState.filters);
  if (selectedIndex >= (appState.photos || []).length) selectedIndex = 0;
  render();
  if (sourcePreviewPending && sourceMode === "folders" && !appState.job?.running) {
    scheduleSourcePreview(80);
  }
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

function uploadFileName(file) {
  return file?.webkitRelativePath || file?.relativePath || file?.name || "upload";
}

function hasRelativeUploadPath(file) {
  return Boolean(file?.webkitRelativePath || file?.relativePath);
}

function annotateDroppedFile(file, relativePath) {
  if (!relativePath || file.webkitRelativePath) return file;
  try {
    Object.defineProperty(file, "relativePath", { value: relativePath, configurable: true });
  } catch (_error) {
    // A plain file name is still safe if the browser does not allow annotation.
  }
  return file;
}

function readEntryFile(entry, relativePath = "") {
  return new Promise((resolve) => {
    entry.file(
      (file) => resolve([annotateDroppedFile(file, relativePath || entry.fullPath?.replace(/^\/+/, "") || file.name)]),
      () => resolve([]),
    );
  });
}

async function readDirectoryEntry(entry, prefix = "") {
  const reader = entry.createReader();
  const files = [];
  const readBatch = () =>
    new Promise((resolve) => {
      reader.readEntries(resolve, () => resolve([]));
    });
  while (true) {
    const entries = await readBatch();
    if (!entries.length) break;
    for (const child of entries) {
      const childPath = `${prefix}${entry.name}/${child.name}`;
      if (child.isFile) {
        files.push(...(await readEntryFile(child, childPath)));
      } else if (child.isDirectory) {
        files.push(...(await readDirectoryEntry(child, `${prefix}${entry.name}/`)));
      }
    }
  }
  return files;
}

async function filesFromDataTransfer(dataTransfer) {
  const items = Array.from(dataTransfer?.items || []);
  if (!items.length) return Array.from(dataTransfer?.files || []);
  const files = [];
  for (const item of items) {
    const entry = item.webkitGetAsEntry?.();
    if (entry?.isFile) {
      files.push(...(await readEntryFile(entry)));
    } else if (entry?.isDirectory) {
      files.push(...(await readDirectoryEntry(entry)));
    } else {
      const file = item.getAsFile?.();
      if (file) files.push(file);
    }
  }
  return files.length ? files : Array.from(dataTransfer?.files || []);
}

async function loadUploadedSourcePreview(savedPaths) {
  const uploadedPaths = uniqueFolderList(savedPaths || []);
  if (!uploadedPaths.length || appState?.job?.running) return;
  sourcePreviewRequestId += 1;
  sourcePreviewLoading = true;
  sourcePreviewPending = false;
  sourceMode = "uploads";
  if (appState?.source) {
    appState.source = {
      ...(appState.source || {}),
      mode: "uploads",
      uploadedPaths,
    };
  }
  render();
  try {
    appState = await postJson("/api/source/preview", {
      mode: "uploads",
      folders: foldersFromInput(),
      cachePath: $("#cacheInput").value.trim(),
      uploadedPaths,
    });
    sourceInputsDirty = false;
    selectedIndex = 0;
    syncPollTimer();
    await loadState();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("source.previewFailedState"),
        title: t("source.previewFailedTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  } finally {
    sourcePreviewLoading = false;
    render();
    syncPollTimer();
  }
}

async function uploadFiles(fileList) {
  if (appState?.job?.running) return;
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const containsDirectoryUpload = files.some(hasRelativeUploadPath);
  const form = new FormData();
  files.forEach((file) => form.append("files", file, uploadFileName(file)));
  $("#uploadHint").textContent = containsDirectoryUpload ? t("source.uploadingFolder") : t("source.uploading");
  const result = await apiClient.uploadForm("/api/upload", form);
  $("#uploadHint").textContent = t("source.uploadedCount", { count: Number(result.count || 0) });
  if ((result.saved || []).length) {
    await loadUploadedSourcePreview(result.saved || []);
  } else {
    await loadState();
  }
}

function handleDesktopDroppedPaths(paths) {
  const droppedPaths = uniqueFolderList(paths || []);
  if (!droppedPaths.length || appState?.job?.running) return;
  desktopDropHandledUntil = Date.now() + 1500;
  addFolderEntries(droppedPaths, { previewDelay: 80 });
  showCommandNotice(
    {
      tone: "ready",
      state: t("source.desktopDropState"),
      title: t("source.desktopDropTitle"),
      detail: t("source.desktopDropDetail", { count: droppedPaths.length }),
    },
    2600,
  );
}

function sourcePreviewPayload() {
  return {
    mode: sourceMode,
    folders: foldersFromInput(),
    cachePath: $("#cacheInput").value.trim(),
    uploadedPaths: appState?.source?.uploadedPaths || [],
  };
}

function scheduleSourcePreview(delay = 240) {
  window.clearTimeout(sourcePreviewTimer);
  const requestId = ++sourcePreviewRequestId;
  if (!appState) {
    sourcePreviewPending = true;
    sourcePreviewLoading = false;
    return;
  }
  if (appState.job?.running || sourceMode !== "folders") {
    sourcePreviewLoading = false;
    return;
  }
  sourcePreviewPending = false;
  const payload = sourcePreviewPayload();
  const hasFolders = Boolean((payload.folders || []).length);
  sourcePreviewTimer = window.setTimeout(() => {
    void loadSourcePreview(payload, requestId, { showLoading: hasFolders });
  }, hasFolders ? delay : 0);
}

async function loadSourcePreview(payload = sourcePreviewPayload(), requestId = ++sourcePreviewRequestId, options = {}) {
  const mode = payload.mode || "folders";
  if (!appState || appState.job?.running || !["folders", "uploads"].includes(mode)) return;
  const hasSource = mode === "uploads" ? Boolean((payload.uploadedPaths || []).length) : Boolean((payload.folders || []).length);
  const sourceSnapshot = mode === "folders" ? sourceInputSnapshot() : null;
  const showLoading = options.showLoading !== false && hasSource;
  sourcePreviewLoading = showLoading;
  if (showLoading) {
    render();
  }
  try {
    const response = await postJson("/api/source/preview", payload);
    if (requestId !== sourcePreviewRequestId) return;
    appState = response;
    if (sourceSnapshot) applySourceInputSnapshot(sourceSnapshot);
    selectedIndex = 0;
    sourcePreviewLoading = false;
    syncPollTimer();
  } catch (error) {
    if (requestId !== sourcePreviewRequestId) return;
    showCommandNotice(
      {
        tone: "danger",
        state: t("source.previewFailedState"),
        title: t("source.previewFailedTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  } finally {
    if (requestId === sourcePreviewRequestId) {
      sourcePreviewLoading = false;
      render();
      syncPollTimer();
    }
  }
}

function selectedScoringModels() {
  return $$("#modelOptions [data-model-key]:checked").map((input) => input.dataset.modelKey);
}

function buildScoringPayload(selectedModels = selectedScoringModels()) {
  return {
    mode: sourceMode,
    folders: foldersFromInput(),
    cachePath: $("#cacheInput").value.trim(),
    uploadedPaths: appState?.source?.uploadedPaths || [],
    networkMode,
    selectedModels,
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
  sourcePreviewRequestId += 1;
  sourcePreviewLoading = false;
  window.clearTimeout(sourcePreviewTimer);
  commandNotice = null;
  window.clearTimeout(commandNoticeTimer);
  await postJson("/api/score", payload);
  sourceInputsDirty = false;
  await loadState();
}

async function startLlmReview() {
  if (!appState || appState.job?.running || !appState?.llm?.configured) return;
  const payload = buildScoringPayload(["llm_review"]);
  sourcePreviewRequestId += 1;
  sourcePreviewLoading = false;
  window.clearTimeout(sourcePreviewTimer);
  commandNotice = null;
  window.clearTimeout(commandNoticeTimer);
  await postJson("/api/llm-review", payload);
  sourceInputsDirty = false;
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
  const cachePath = $("#cacheInput").value.trim();
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
    selectedIndex = 0;
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
  const cachePath = $("#cacheInput").value.trim();
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
    selectedGalleryIds.clear();
    gallerySelectionAnchorId = "";
    selectedIndex = 0;
    llmModelOptions = [];
    llmModelListMessage = "";
    llmSelectedModel = appState?.llm?.model || "";
    llmConfigEditing = false;
    llmModelMenuOpen = false;
    sourceInputsDirty = false;
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

async function loadLlmModels({ payloadOverrides = {}, openMenu = false, announce = true } = {}) {
  if (!appState || appState.job?.running || llmModelsLoading) return;
  llmModelsLoading = true;
  llmModelListMessage = "";
  renderLlmConfig();
  try {
    const result = await postJson("/api/llm-models", llmConnectionPayload(payloadOverrides));
    llmModelOptions = result.models || [];
    llmModelListMessage = llmConfigView.modelListResultMessage(llmModelOptions);
    if (!llmSelectedModel) {
      llmSelectedModel = result.currentModel || llmModelOptions[0]?.value || appState?.llm?.model || "";
    }
    if (openMenu && llmModelOptions.length > 0) {
      llmConfigEditing = true;
      llmModelMenuOpen = true;
      llmModelSearchQuery = "";
    }
    renderLlmConfig();
    if (announce) {
      showCommandNotice({
        tone: "ready",
        state: t("llm.modelsLoadedState"),
        title: t("llm.modelsLoadedTitle"),
        detail: llmModelListMessage,
      });
    }
    return { ok: true, models: llmModelOptions, message: llmModelListMessage };
  } catch (error) {
    llmModelListMessage = errorMessage(error);
    renderLlmConfig();
    showCommandNotice(
      {
        tone: "danger",
        state: t("llm.modelsLoadFailureState"),
        title: t("llm.modelsLoadFailureTitle"),
        detail: llmModelListMessage,
      },
      4200,
    );
    return { ok: false, message: llmModelListMessage };
  } finally {
    llmModelsLoading = false;
    renderLlmConfig();
  }
}

function openLlmConfigEditor() {
  if (appState?.job?.running) return;
  llmConfigEditing = true;
  llmSelectedModel = appState?.llm?.model || llmSelectedModel;
  renderLlmConfig();
}

function cancelLlmConfigEdit() {
  if (appState?.job?.running) return;
  llmConfigEditing = false;
  llmModelMenuOpen = false;
  llmModelSearchQuery = "";
  llmSelectedModel = appState?.llm?.model || "";
  const keyInput = $("#llmApiKeyInput");
  if (keyInput) keyInput.value = "";
  renderLlmConfig();
}

function llmConfigRawValues(overrides = {}) {
  return {
    apiKey: $("#llmApiKeyInput").value,
    baseUrl: $("#llmBaseUrlInput").value,
    model: selectedLlmModel(),
    promptPreset: $("#llmPromptPreset").value,
    customPrompt: $("#llmCustomPromptInput").value,
    persist: $("#persistLlmConfig").checked,
    cachePath: $("#cacheInput").value,
    ...overrides,
  };
}

function llmConnectionPayload(overrides = {}) {
  return llmConfigView.connectionPayload(llmConfigRawValues(overrides));
}

function llmConfigFormPayload(overrides = {}) {
  return llmConfigView.configFormPayload(llmConfigRawValues(overrides));
}

function resetLlmModelCatalogForConnectionChange() {
  if (!llmModelOptions.length && !llmModelListMessage) return;
  llmModelOptions = [];
  llmModelMenuOpen = false;
  llmModelSearchQuery = "";
  llmModelListMessage = t("llm.connectionChanged");
  renderLlmConfig();
}

async function saveLlmConfig() {
  if (!appState || appState.job?.running) return;
  const payload = llmConfigFormPayload();
  try {
    appState = await postJson("/api/llm-config", payload);
    llmModelMenuOpen = false;
    llmModelSearchQuery = "";
    llmSelectedModel = appState?.llm?.model || payload.model;
    llmConfigEditing = false;
    showCommandNotice({
      tone: appState.llm?.configured ? "ready" : "partial",
      state: appState.llm?.configured ? t("llm.saveState") : t("llm.needsConfigState"),
      title: appState.llm?.configured ? t("llm.connectedTitle") : t("llm.paramsSavedTitle"),
      detail: appState.llm?.configured
        ? (payload.persist ? t("llm.persistedDetail") : t("llm.sessionDetail"))
        : t("llm.needsKeyDetail"),
    });
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("llm.saveFailureState"),
        title: t("llm.saveFailureTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  }
}

async function clearLlmKey() {
  if (appState?.job?.running || !appState?.llm?.configured) return;
  const ok = await requestDangerConfirm({
    confirmIcon: "brain",
    confirmLabel: t("llm.clearKeyAction"),
    detail: t("llm.clearKeyConfirm"),
    title: t("llm.clearKeyConfirmTitle"),
  });
  if (!ok) return;
  try {
    const payload = llmConfigFormPayload({
      clearKey: true,
      persist: true,
    });
    appState = await postJson("/api/llm-config", payload);
    llmConfigEditing = false;
    llmModelMenuOpen = false;
    llmSelectedModel = appState?.llm?.model || "";
    llmModelOptions = [];
    llmModelListMessage = "";
    showCommandNotice({
      tone: "partial",
      state: t("llm.clearKeyState"),
      title: t("llm.clearKeyTitle"),
      detail: t("llm.clearKeyDetail"),
    });
    render();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("llm.clearKeyFailureState"),
        title: t("llm.clearKeyFailureTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  }
}

function filterPayloadFromInputs() {
  return {
    sortField: $("#sortField").value,
    minScore: Number($("#minScore").value),
    minModelQuality: Number($("#minModelQuality").value),
    minAestheticReference: Number($("#minAestheticReference").value),
    minTechnical: Number($("#minTechnical").value),
    minLlmReview: Number($("#minLlmReview").value),
    modelAgreement: $("#modelAgreement").value,
    manualStatus: $("#manualStatusFilter").value,
    colorLabel: $("#colorLabelFilter").value,
    limit: Number($("#limitInput").value),
    weightPreset: $("#weightPreset").value,
    customWeights: {
      aesthetic: Number($("#aestheticWeight").value),
      technical: Number($("#technicalWeight").value),
      compositionLight: Number($("#compositionLightWeight").value),
    },
  };
}

function applyFilterPayloadToInputs(filters = {}) {
  const payload = normalizeFilterPayload(filters);
  $("#sortField").value = payload.sortField;
  $("#minScore").value = payload.minScore;
  $("#minModelQuality").value = payload.minModelQuality;
  $("#minAestheticReference").value = payload.minAestheticReference;
  $("#minTechnical").value = payload.minTechnical;
  $("#minLlmReview").value = payload.minLlmReview;
  $("#modelAgreement").value = payload.modelAgreement;
  $("#manualStatusFilter").value = payload.manualStatus;
  $("#colorLabelFilter").value = payload.colorLabel;
  $("#limitInput").value = payload.limit;
  $("#weightPreset").value = payload.weightPreset;
  $("#aestheticWeight").value = payload.customWeights.aesthetic;
  $("#technicalWeight").value = payload.customWeights.technical;
  $("#compositionLightWeight").value = payload.customWeights.compositionLight;
}

async function applyFilterUpdate() {
  window.clearTimeout(filterTimer);
  filterTimer = null;
  filterUpdateInFlight = (async () => {
    appState = await postJson("/api/filter", filterPayloadFromInputs());
    persistFilterPayload(appState.filters);
    selectedIndex = 0;
    render();
    return appState;
  })();
  try {
    return await filterUpdateInFlight;
  } finally {
    filterUpdateInFlight = null;
  }
}

async function clearFilterScope() {
  applyFilterPayloadToInputs();
  try {
    await applyFilterUpdate();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("filters.clearFailureState"),
        title: t("filters.clearFailureTitle"),
        detail: errorMessage(error),
      },
      4200,
    );
  }
}

async function saveCurrentFilterPreset() {
  if (!appState) return;
  const input = $("#filterPresetNameInput");
  if (renamingFilterPresetId) {
    const preset = savedFilterPresets().find((item) => item.id === renamingFilterPresetId);
    const presetName = input.value.trim();
    if (!preset || !presetName) {
      renamingFilterPresetId = "";
      input.value = "";
      renderFilterPresets();
      return;
    }
    filterPresets = renameFilterPreset(renamingFilterPresetId, presetName);
    renamingFilterPresetId = "";
    input.value = "";
    renderFilterPresets();
    showCommandNotice({
      tone: "ready",
      state: t("filters.renameState"),
      title: t("filters.renameTitle", { name: presetName }),
      detail: filterPresetSummary(preset.filters),
    }, 2400);
    return;
  }
  try {
    await flushFilterUpdate();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("filters.saveFailureState"),
        title: t("filters.saveFailureTitle"),
        detail: errorMessage(error),
      },
      3600,
    );
    return;
  }
  const presetName = input.value.trim() || filterPresetSuggestedName(appState.filters);
  filterPresets = saveFilterPreset(presetName, appState.filters);
  input.value = "";
  renderFilterPresets();
  showCommandNotice({
    tone: "ready",
    state: t("filters.saveState"),
    title: t("filters.saveTitle", { name: presetName }),
    detail: filterPresetSummary(appState.filters),
  }, 2600);
}

function beginRenameFilterPreset(presetId) {
  const preset = savedFilterPresets().find((item) => item.id === presetId);
  if (!preset) return;
  renamingFilterPresetId = preset.id;
  const input = $("#filterPresetNameInput");
  input.value = preset.name;
  renderFilterPresets();
  window.setTimeout(() => {
    input.focus();
    input.select();
  }, 0);
}

function cancelRenameFilterPreset() {
  if (!renamingFilterPresetId) return;
  renamingFilterPresetId = "";
  $("#filterPresetNameInput").value = "";
  renderFilterPresets();
}

async function refreshFilterPreset(presetId) {
  const preset = savedFilterPresets().find((item) => item.id === presetId);
  if (!preset) return;
  cancelRenameFilterPreset();
  try {
    await flushFilterUpdate();
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("filters.updateFailureState"),
        title: t("filters.updateFailureTitle"),
        detail: errorMessage(error),
      },
      3600,
    );
    return;
  }
  filterPresets = updateFilterPreset(presetId, appState.filters);
  renderFilterPresets();
  showCommandNotice({
    tone: "ready",
    state: t("filters.updateState"),
    title: t("filters.updateTitle", { name: preset.name }),
    detail: filterPresetSummary(appState.filters),
  }, 2600);
}

async function applyFilterPreset(presetId) {
  const preset = savedFilterPresets().find((item) => item.id === presetId);
  if (!preset) return;
  cancelRenameFilterPreset();
  applyFilterPayloadToInputs(preset.filters);
  try {
    await applyFilterUpdate();
    showCommandNotice({
      tone: "ready",
      state: t("filters.applyState"),
      title: t("filters.applyTitle", { name: preset.name }),
      detail: filterPresetSummary(preset.filters),
    }, 2600);
  } catch (error) {
    showCommandNotice(
      {
        tone: "danger",
        state: t("filters.applyFailureState"),
        title: t("filters.applyFailureTitle"),
        detail: errorMessage(error),
      },
      3600,
    );
  }
}

function removeFilterPreset(presetId) {
  const preset = savedFilterPresets().find((item) => item.id === presetId);
  if (renamingFilterPresetId === presetId) renamingFilterPresetId = "";
  filterPresets = deleteFilterPreset(presetId);
  renderFilterPresets();
  if (preset) {
    showCommandNotice({
      tone: "partial",
      state: t("filters.deleteState"),
      title: t("filters.deleteTitle", { name: preset.name }),
      detail: t("filters.remainingViews", { count: filterPresets.length }),
    }, 2200);
  }
}

function scheduleFilterUpdate() {
  window.clearTimeout(filterTimer);
  filterTimer = window.setTimeout(() => {
    applyFilterUpdate().catch((error) => {
      showCommandNotice(
        {
          tone: "danger",
          state: t("filters.updateFilterFailureState"),
          title: t("filters.updateFilterFailureTitle"),
          detail: errorMessage(error),
        },
        3600,
      );
    });
  }, 140);
}

async function flushFilterUpdate() {
  if (filterTimer) return applyFilterUpdate();
  if (filterUpdateInFlight) return filterUpdateInFlight;
  return appState;
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
  $("#manualStatusFilter").value = status;
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
  const previousIndex = selectedIndex;
  try {
    appState = await postJson("/api/mark", {
      fileId: photo.fileId,
      ...changes,
    });
    if (options.advance) {
      selectedIndex = cullingFlow.nextIndexAfterMark(appState.photos || [], previousIndex, previousFileId, true);
    } else {
      preserveSelectedPhoto(previousFileId);
    }
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

async function pickExportFolder() {
  if (appState?.job?.running) return;
  try {
    const result = await postJson("/api/pick-export-folder", {});
    if (result.folder) {
      exportDestination = result.folder;
      exportStatusText = "";
      exportResult = null;
      applyExportPreflightState({ error: "", preflight: null });
      await refreshExportPreflight();
    }
  } catch (_error) {
    // Folder picker cancellation should stay quiet.
  }
}

async function refreshExportPreflight(options = {}) {
  if (appState?.job?.running) return;
  if (!exportDestination) {
    applyExportPreflightState(CulviaExportPreflightState.emptyState());
    renderExportList();
    return;
  }
  const requestKey = options.key || currentExportPreflightKey();
  applyExportPreflightState(CulviaExportPreflightState.beginRequest(requestKey));
  renderExportList();
  try {
    const payload = await postJson("/api/export/preflight", { destination: exportDestination });
    if (!CulviaExportPreflightState.isCurrent(exportPreflightKey, requestKey)) return;
    applyExportPreflightState(CulviaExportPreflightState.successState(payload));
  } catch (error) {
    if (!CulviaExportPreflightState.isCurrent(exportPreflightKey, requestKey)) return;
    applyExportPreflightState(CulviaExportPreflightState.failureState(errorMessage(error)));
  } finally {
    if (!CulviaExportPreflightState.isCurrent(exportPreflightKey, requestKey)) return;
    applyExportPreflightState(CulviaExportPreflightState.finishRequest());
    renderExportList();
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

function handleGalleryShortcut(event) {
  const selectedCount = visibleGallerySelection(appState?.photos || []).length;
  const shortcut = galleryKeyboard.shortcutActionFromEvent(event, { activeView, selectedCount });
  if (shortcut.action === galleryKeyboard.actions.none) return false;
  if (shortcut.action === galleryKeyboard.actions.selectVisible) {
    event.preventDefault();
    selectVisibleGalleryPhotos();
    return true;
  }
  if (shortcut.action === galleryKeyboard.actions.clearSelection) {
    event.preventDefault();
    clearGallerySelection();
    return true;
  }
  if (shortcut.action === galleryKeyboard.actions.batchStatus) {
    event.preventDefault();
    void openBatchStatusConfirm(shortcut.status);
    return true;
  }
  return false;
}

function handleViewerShortcut(event) {
  const shortcut = viewerKeyboard.shortcutActionFromEvent(event, {
    activeView,
    hasSelectedPhoto: Boolean(selectedPhoto()),
  });
  if (shortcut.action === viewerKeyboard.actions.none) return false;
  event.preventDefault();
  if (shortcut.action === viewerKeyboard.actions.navigate) {
    if (shortcut.direction < 0) $("#prevBtn").click();
    if (shortcut.direction > 0) $("#nextBtn").click();
    return true;
  }
  if (shortcut.action === viewerKeyboard.actions.rating) {
    updateManualMark({ rating: shortcut.rating, source: "manual", acceptedScore: null }, { advance: markAdvanceEnabled });
    return true;
  }
  if (shortcut.action === viewerKeyboard.actions.status) {
    updateManualMark({ status: shortcut.status, source: "manual", acceptedScore: null }, { advance: markAdvanceEnabled });
    return true;
  }
  if (shortcut.action === viewerKeyboard.actions.color) {
    updateManualMark({ colorLabel: shortcut.colorLabel, source: "manual" });
    return true;
  }
  return false;
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

async function exportSelectedPhotos() {
  if (appState?.job?.running) return;
  if (!exportDestination) return;
  try {
    $("#exportSelectedBtn").disabled = true;
    exportResult = null;
    renderExportList();
    const result = await postJson("/api/export/selected-files", { destination: exportDestination });
    exportResult = result;
    exportStatusText = CulviaExportActions.exportStatusText(result);
    showCommandNotice(CulviaExportActions.successNotice(result, { pathName }));
    renderExportList();
    await refreshExportPreflight();
  } catch (error) {
    exportResult = null;
    const failure = CulviaExportActions.failureState(errorMessage(error));
    exportStatusText = failure.statusText;
    showCommandNotice(failure.notice, failure.duration);
    renderExportList();
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

async function revealExportDestination() {
  const destination = CulviaExportActions.destinationFromResult(exportResult, exportDestination);
  if (!destination) return;
  try {
    await postJson("/api/reveal", CulviaExportActions.revealDestinationPayload(destination));
  } catch (error) {
    showCommandNotice(CulviaExportActions.revealFailureNotice(errorMessage(error)), 4200);
  }
}

async function copyExportDestination() {
  const destination = CulviaExportActions.destinationFromResult(exportResult, exportDestination);
  if (!destination) return;
  try {
    const copied = await clipboard.writeText(destination);
    if (!copied) throw new Error("clipboard_unavailable");
    showCommandNotice(CulviaExportActions.copyDestinationSuccessNotice(destination, { pathName }), 2600);
  } catch (error) {
    showCommandNotice(CulviaExportActions.copyDestinationFailureNotice(errorMessage(error)), 4200);
  }
}

function handleExportResultClick(event) {
  const resultActions = CulviaExportActions.resultActions;
  const action = CulviaExportActions.resultActionFromEvent(event);
  if (action === resultActions.copyDestination) {
    void copyExportDestination();
    return;
  }
  if (action === resultActions.revealDestination) {
    void revealExportDestination();
  }
}

function handleExportPreflightClick(event) {
  const action = CulviaExportPreflight.actionFromEvent(event);
  if (action === CulviaExportPreflight.actions.pickFolder) {
    void pickExportFolder();
  }
}

function bindEvents() {
  $("#fileInput").setAttribute("accept", supportedTypes.join(","));
  $("#folderPicker").setAttribute("accept", supportedTypes.join(","));

  $$("[data-source]").forEach((button) =>
    button.addEventListener("click", () => setSourceMode(button.dataset.source, { dirty: true })),
  );
  $$("[data-network]").forEach((button) => button.addEventListener("click", () => setNetworkMode(button.dataset.network)));
  $$(".view-tab").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $("#sidebarToggleBtn").addEventListener("click", toggleSidebarMode);
  $("#openSettingsDrawerBtn").addEventListener("click", openSettingsDrawer);
  $("#closeSettingsDrawerBtn").addEventListener("click", closeSettingsDrawer);
  $("#settingsScrim").addEventListener("click", closeSettingsDrawer);
  $("#openShortcutHelpBtn").addEventListener("click", openShortcutHelp);
  $("#closeShortcutHelpBtn").addEventListener("click", closeShortcutHelp);
  $("#shortcutHelpScrim").addEventListener("click", closeShortcutHelp);

  $("#pickFilesBtn").addEventListener("click", () => {
    if (!appState?.job?.running) $("#fileInput").click();
  });
  $("#pickFolderBtn").addEventListener("click", () => {
    if (!appState?.job?.running) $("#folderPicker").click();
  });
  $("#fileInput").addEventListener("change", (event) => uploadFiles(event.target.files));
  $("#folderPicker").addEventListener("change", (event) => uploadFiles(event.target.files));

  $("#pickNativeFolderBtn").addEventListener("click", async () => {
    if (appState?.job?.running) return;
    try {
      const result = await postJson("/api/pick-folders", {});
      const picked = uniqueFolderList(result.folders || [result.folder]);
      if (!picked.length) return;
      addFolderEntries(picked, { previewDelay: 80 });
    } catch (_error) {
      // User cancellation should stay quiet.
    }
  });

  const dropzone = $("#dropzone");
  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("is-dragging");
    });
  });
  dropzone.addEventListener("drop", (event) => {
    if (!appState?.job?.running && Date.now() > desktopDropHandledUntil) {
      void filesFromDataTransfer(event.dataTransfer).then((files) => uploadFiles(files));
    }
  });
  window.addEventListener("culvia-desktop-drop", (event) => {
    handleDesktopDroppedPaths(event.detail?.paths || []);
  });

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
  $("#clearFilterScopeBtn").addEventListener("click", clearFilterScope);
  $("#saveFilterPresetBtn").addEventListener("click", saveCurrentFilterPreset);
  $("#filterPresetNameInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      saveCurrentFilterPreset();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelRenameFilterPreset();
    }
  });
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
  [
    ["#minScore", "#minScoreText"],
    ["#minModelQuality", "#minModelQualityText"],
    ["#minAestheticReference", "#minAestheticReferenceText"],
    ["#minTechnical", "#minTechnicalText"],
    ["#minLlmReview", "#minLlmReviewText"],
  ].forEach(([inputSelector, textSelector]) => {
    $(inputSelector).addEventListener("input", () => {
      setText(textSelector, Number($(inputSelector).value).toFixed(1));
      scheduleFilterUpdate();
    });
  });
  const handleFolderSourceChange = () => {
    if (appState?.job?.running) return;
    if (sourceMode !== "folders") setSourceMode("folders");
    markSourceInputsDirty();
    updatePathSummaries();
    scheduleSourcePreview();
  };
  $("#folderList").addEventListener("input", (event) => {
    if (!event.target?.matches?.("[data-folder-path]")) return;
    event.target.dataset.uiTooltip = event.target.value;
    handleFolderSourceChange();
  });
  $("#folderList").addEventListener("change", (event) => {
    if (!event.target?.matches?.("[data-folder-path]")) return;
    setFolderList(foldersFromInput(), { previewDelay: 120 });
  });
  $("#folderList").addEventListener("click", (event) => {
    const removeButton = event.target?.closest?.("[data-remove-source-folder]");
    if (removeButton) {
      const index = Number(removeButton.dataset.removeSourceFolder);
      setFolderList(foldersFromInput().filter((_folder, folderIndex) => folderIndex !== index), { previewDelay: 80 });
      return;
    }
    const copyButton = event.target?.closest?.("[data-copy-source-folder]");
    if (copyButton) {
      void copyFileFolderPath(copyButton.dataset.copySourceFolder || "");
    }
  });
  $("#folderAddBtn").addEventListener("click", () => addFolderEntries(folderValuesFromText($("#folderAddInput").value)));
  $("#folderAddInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addFolderEntries(folderValuesFromText(event.target.value));
    }
  });
  $("#folderAddInput").addEventListener("paste", (event) => {
    const text = event.clipboardData?.getData("text") || "";
    if (!text.includes("\n")) return;
    event.preventDefault();
    addFolderEntries(folderValuesFromText(text));
  });
  $("#clearFoldersBtn").addEventListener("click", () => setFolderList([], { previewDelay: 0 }));
  $("#cacheInput").addEventListener("change", () => {
    if (appState?.job?.running) return;
    markSourceInputsDirty();
    scheduleSourcePreview(120);
  });
  [
    ["#aestheticWeight", "#aestheticWeightText"],
    ["#technicalWeight", "#technicalWeightText"],
    ["#compositionLightWeight", "#compositionLightWeightText"],
  ].forEach(([inputSelector, textSelector]) => {
    $(inputSelector).addEventListener("input", () => {
      $("#weightPreset").value = "custom";
      $(textSelector).textContent = percentValue($(inputSelector).value);
      $("#customWeights").classList.remove("is-hidden");
      scheduleFilterUpdate();
    });
  });
  $("#limitInput").addEventListener("input", scheduleFilterUpdate);
  $("#limitInput").addEventListener("change", scheduleFilterUpdate);

  $("#prevBtn").addEventListener("click", () => {
    moveSelection(-1);
  });
  $("#nextBtn").addEventListener("click", () => {
    moveSelection(1);
  });
  $("#manualPickBtn").addEventListener("click", () => updateManualMark({ status: "pick", source: "manual", acceptedScore: null }, { advance: markAdvanceEnabled }));
  $("#manualHoldBtn").addEventListener("click", () => updateManualMark({ status: "hold", source: "manual", acceptedScore: null }, { advance: markAdvanceEnabled }));
  $("#manualRejectBtn").addEventListener("click", () => updateManualMark({ status: "reject", source: "manual", acceptedScore: null }, { advance: markAdvanceEnabled }));
  $("#markAdvanceToggle").addEventListener("click", toggleMarkAdvanceMode);
  $("#acceptModelBtn").addEventListener("click", () => acceptPhotoResult("model"));
  $("#acceptLlmBtn").addEventListener("click", () => acceptPhotoResult("llm"));
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
  $("#previewLink").addEventListener("click", (event) => {
    if (appState?.capabilities?.nativeFilePreview !== true) return;
    event.preventDefault();
    void openPhotoPreview(selectedPhoto());
  });
  $("#revealBtn").addEventListener("click", () => revealPhoto(selectedPhoto()));
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
