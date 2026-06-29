window.CulviaFilterPanel = (() => {
  function create({
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
    render,
    getAppState,
    setAppState,
    getCommandNotice,
    resetSelectedIndex,
  }) {
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

    let filterTimer = null;
    let filterUpdateInFlight = null;
    let filterRestoreAttempted = false;
    let filterPresets = savedFilterPresets();
    let renamingFilterPresetId = "";

    function appState() {
      return getAppState();
    }

    function commandLoading() {
      return Boolean(getCommandNotice()?.loading);
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

    function filterPresetContext() {
      return {
        options: {
          manualStatusOptions: appState()?.manualStatusOptions || [],
          colorLabelOptions: appState()?.colorLabelOptions || [],
          modelAgreementOptions: appState()?.modelAgreementOptions || [],
          sortOptions: appState()?.sortOptions || [],
          weightPresets: appState()?.weightPresets || [],
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

    function activeFilterChips(filters = appState()?.filters || {}) {
      return filterPresetView.activeFilterChips(filters, filterPresetContext());
    }

    function renderScope() {
      const bar = $("#filterScopeBar");
      const container = $("#filterScopeChips");
      const clearButton = $("#clearFilterScopeBtn");
      if (!bar || !container || !clearButton) return;

      const chips = activeFilterChips(appState()?.filters || {});
      bar.classList.toggle("is-hidden", !chips.length);
      container.innerHTML = chips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("");
      clearButton.disabled = Boolean(appState()?.job?.running) || commandLoading();
    }

    function filterPresetSuggestedName(filters = appState()?.filters || {}) {
      return filterPresetView.suggestedName(filters, filterPresetContext());
    }

    function filterPresetSummary(filters = {}) {
      return filterPresetView.summary(filters, filterPresetContext());
    }

    function filterPresetMetaText(preset) {
      return filterPresetView.metaText(preset, filterPresetContext());
    }

    function renderPresets() {
      const list = $("#filterPresetList");
      const input = $("#filterPresetNameInput");
      const saveButton = $("#saveFilterPresetBtn");
      const hint = $("#filterPresetHint");
      if (!list || !input || !saveButton) return;

      filterPresets = savedFilterPresets();
      if (renamingFilterPresetId && !filterPresets.some((preset) => preset.id === renamingFilterPresetId)) {
        renamingFilterPresetId = "";
      }
      const currentFilters = normalizeFilterPayload(appState()?.filters || {});
      input.placeholder = renamingFilterPresetId ? t("filters.renamePlaceholder") : filterPresetSuggestedName(currentFilters);
      const saveIcon = renamingFilterPresetId ? "pencil" : "bookmark";
      const saveLabel = renamingFilterPresetId ? t("filters.confirmRename") : t("filters.saveView");
      saveButton.innerHTML = iconMarkup(saveIcon);
      saveButton.removeAttribute("title");
      saveButton.dataset.uiTooltip = saveLabel;
      saveButton.setAttribute("aria-label", saveLabel);
      saveButton.disabled = Boolean(appState()?.job?.running) || commandLoading();
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
        button.addEventListener("click", () => applyPreset(button.dataset.filterPreset));
      });
      list.querySelectorAll("[data-update-filter-preset]").forEach((button) => {
        button.addEventListener("click", () => refreshPreset(button.dataset.updateFilterPreset));
      });
      list.querySelectorAll("[data-rename-filter-preset]").forEach((button) => {
        button.addEventListener("click", () => beginRenamePreset(button.dataset.renameFilterPreset));
      });
      list.querySelectorAll("[data-delete-filter-preset]").forEach((button) => {
        button.addEventListener("click", () => removePreset(button.dataset.deleteFilterPreset));
      });
    }

    function renderControls() {
      const state = appState();
      if (!state) return;
      const selectedSort = state.filters.sortField || "recommendation_0_10";
      $("#sortField").value = selectedSort;
      $("#sortOptions").innerHTML = (state.sortOptions || [])
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
          scheduleUpdate();
        });
      });
      const selectedPreset = state.filters.weightPreset || "balanced";
      $("#weightPreset").value = selectedPreset;
      $("#weightPresetOptions").innerHTML = (state.weightPresets || [])
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
          scheduleUpdate();
        });
      });
      const customWeights = state.filters.customWeights || {};
      $("#aestheticWeight").value = customWeights.aesthetic ?? 0.6;
      $("#technicalWeight").value = customWeights.technical ?? 0.25;
      $("#compositionLightWeight").value = customWeights.compositionLight ?? 0.15;
      setText("#aestheticWeightText", percentValue($("#aestheticWeight").value));
      setText("#technicalWeightText", percentValue($("#technicalWeight").value));
      setText("#compositionLightWeightText", percentValue($("#compositionLightWeight").value));
      $("#customWeights").classList.toggle("is-hidden", selectedPreset !== "custom");
      $("#minScore").value = state.filters.minScore ?? 0;
      setText("#minScoreText", Number(state.filters.minScore ?? 0).toFixed(1));
      $("#minModelQuality").value = state.filters.minModelQuality ?? 0;
      setText("#minModelQualityText", Number(state.filters.minModelQuality ?? 0).toFixed(1));
      $("#minAestheticReference").value = state.filters.minAestheticReference ?? 0;
      setText("#minAestheticReferenceText", Number(state.filters.minAestheticReference ?? 0).toFixed(1));
      $("#minTechnical").value = state.filters.minTechnical ?? 0;
      setText("#minTechnicalText", Number(state.filters.minTechnical ?? 0).toFixed(1));
      $("#minLlmReview").value = state.filters.minLlmReview ?? 0;
      setText("#minLlmReviewText", Number(state.filters.minLlmReview ?? 0).toFixed(1));
      const selectedAgreement = state.filters.modelAgreement || "all";
      $("#modelAgreement").value = selectedAgreement;
      $("#modelAgreementOptions").innerHTML = (state.modelAgreementOptions || [])
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
          scheduleUpdate();
        });
      });
      const selectedManualStatus = state.filters.manualStatus || "all";
      $("#manualStatusFilter").value = selectedManualStatus;
      $("#manualStatusOptions").innerHTML = (state.manualStatusOptions || [])
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
          scheduleUpdate();
        });
      });
      const selectedColorLabel = state.filters.colorLabel || "all";
      $("#colorLabelFilter").value = selectedColorLabel;
      $("#colorLabelOptions").innerHTML = (state.colorLabelOptions || [])
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
          scheduleUpdate();
        });
      });
      $("#limitInput").value = state.filters.limit ?? 80;
      renderPresets();
    }

    function payloadFromInputs() {
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

    function applyPayloadToInputs(filters = {}) {
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

    async function applyUpdate() {
      window.clearTimeout(filterTimer);
      filterTimer = null;
      filterUpdateInFlight = (async () => {
        setAppState(await postJson("/api/filter", payloadFromInputs()));
        persistFilterPayload(appState().filters);
        resetSelectedIndex();
        render();
        return appState();
      })();
      try {
        return await filterUpdateInFlight;
      } finally {
        filterUpdateInFlight = null;
      }
    }

    async function clearScope() {
      applyPayloadToInputs();
      try {
        await applyUpdate();
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

    async function saveCurrentPreset() {
      if (!appState()) return;
      const input = $("#filterPresetNameInput");
      if (renamingFilterPresetId) {
        const preset = savedFilterPresets().find((item) => item.id === renamingFilterPresetId);
        const presetName = input.value.trim();
        if (!preset || !presetName) {
          renamingFilterPresetId = "";
          input.value = "";
          renderPresets();
          return;
        }
        filterPresets = renameFilterPreset(renamingFilterPresetId, presetName);
        renamingFilterPresetId = "";
        input.value = "";
        renderPresets();
        showCommandNotice({
          tone: "ready",
          state: t("filters.renameState"),
          title: t("filters.renameTitle", { name: presetName }),
          detail: filterPresetSummary(preset.filters),
        }, 2400);
        return;
      }
      try {
        await flushUpdate();
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
      const presetName = input.value.trim() || filterPresetSuggestedName(appState().filters);
      filterPresets = saveFilterPreset(presetName, appState().filters);
      input.value = "";
      renderPresets();
      showCommandNotice({
        tone: "ready",
        state: t("filters.saveState"),
        title: t("filters.saveTitle", { name: presetName }),
        detail: filterPresetSummary(appState().filters),
      }, 2600);
    }

    function beginRenamePreset(presetId) {
      const preset = savedFilterPresets().find((item) => item.id === presetId);
      if (!preset) return;
      renamingFilterPresetId = preset.id;
      const input = $("#filterPresetNameInput");
      input.value = preset.name;
      renderPresets();
      window.setTimeout(() => {
        input.focus();
        input.select();
      }, 0);
    }

    function cancelRenamePreset() {
      if (!renamingFilterPresetId) return;
      renamingFilterPresetId = "";
      $("#filterPresetNameInput").value = "";
      renderPresets();
    }

    async function refreshPreset(presetId) {
      const preset = savedFilterPresets().find((item) => item.id === presetId);
      if (!preset) return;
      cancelRenamePreset();
      try {
        await flushUpdate();
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
      filterPresets = updateFilterPreset(presetId, appState().filters);
      renderPresets();
      showCommandNotice({
        tone: "ready",
        state: t("filters.updateState"),
        title: t("filters.updateTitle", { name: preset.name }),
        detail: filterPresetSummary(appState().filters),
      }, 2600);
    }

    async function applyPreset(presetId) {
      const preset = savedFilterPresets().find((item) => item.id === presetId);
      if (!preset) return;
      cancelRenamePreset();
      applyPayloadToInputs(preset.filters);
      try {
        await applyUpdate();
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

    function removePreset(presetId) {
      const preset = savedFilterPresets().find((item) => item.id === presetId);
      if (renamingFilterPresetId === presetId) renamingFilterPresetId = "";
      filterPresets = deleteFilterPreset(presetId);
      renderPresets();
      if (preset) {
        showCommandNotice({
          tone: "partial",
          state: t("filters.deleteState"),
          title: t("filters.deleteTitle", { name: preset.name }),
          detail: t("filters.remainingViews", { count: filterPresets.length }),
        }, 2200);
      }
    }

    function scheduleUpdate() {
      window.clearTimeout(filterTimer);
      filterTimer = window.setTimeout(() => {
        applyUpdate().catch((error) => {
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

    async function flushUpdate() {
      if (filterTimer) return applyUpdate();
      if (filterUpdateInFlight) return filterUpdateInFlight;
      return appState();
    }

    async function restoreSavedFiltersIfNeeded() {
      const state = appState();
      if (!state || filterRestoreAttempted || state.job?.running) return;
      filterRestoreAttempted = true;
      const savedFilters = savedFilterPayload();
      if (savedFilters && !filtersAreDefault(savedFilters) && filtersAreDefault(state.filters)) {
        try {
          setAppState(await postJson("/api/filter", savedFilters));
        } catch (_error) {
          localStorage.removeItem(FILTER_STORAGE_KEY);
        }
      }
    }

    function persistCurrentFilters() {
      persistFilterPayload(appState()?.filters || {});
    }

    function setManualStatus(status) {
      $("#manualStatusFilter").value = status;
    }

    function bindEvents() {
      $("#clearFilterScopeBtn").addEventListener("click", clearScope);
      $("#saveFilterPresetBtn").addEventListener("click", saveCurrentPreset);
      $("#filterPresetNameInput").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          saveCurrentPreset();
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancelRenamePreset();
        }
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
          scheduleUpdate();
        });
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
          scheduleUpdate();
        });
      });
      $("#limitInput").addEventListener("input", scheduleUpdate);
      $("#limitInput").addEventListener("change", scheduleUpdate);
    }

    return {
      applyUpdate,
      bindEvents,
      cancelRenamePreset,
      clearScope,
      flushUpdate,
      persistCurrentFilters,
      renderControls,
      renderPresets,
      renderScope,
      restoreSavedFiltersIfNeeded,
      saveCurrentPreset,
      scheduleUpdate,
      setManualStatus,
    };
  }

  return { create };
})();
