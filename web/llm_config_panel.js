window.CulviaLlmConfigPanel = (() => {
  function create({
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
    requestDangerConfirm,
    render,
    getAppState,
    setAppState,
  }) {
    let llmModelOptions = [];
    let llmModelsLoading = false;
    let llmModelListMessage = "";
    let llmSelectedModel = "";
    let llmModelMenuOpen = false;
    let llmModelSearchQuery = "";
    let llmConfigEditing = false;

    function selectedLlmModel() {
      return llmSelectedModel || getAppState()?.llm?.model || "";
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
        fallbackModel: getAppState()?.llm?.model || "gpt-4o-mini",
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
        if (hasInputKey || getAppState()?.llm?.configured) {
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
      renderLlmModelPicker(getAppState()?.llm || {});
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
      const llm = getAppState()?.llm || {};
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
        refreshButton.disabled = Boolean(getAppState()?.job?.running) || llmModelsLoading;
      }
      const saveButton = $(domPlan.saveButton.selector);
      if (saveButton) {
        saveButton.disabled = Boolean(getAppState()?.job?.running) || llmModelsLoading;
      }
    }

    async function loadLlmModels({ payloadOverrides = {}, openMenu = false, announce = true } = {}) {
      if (!getAppState() || getAppState().job?.running || llmModelsLoading) return;
      llmModelsLoading = true;
      llmModelListMessage = "";
      renderLlmConfig();
      try {
        const result = await postJson("/api/llm-models", llmConnectionPayload(payloadOverrides));
        llmModelOptions = result.models || [];
        llmModelListMessage = llmConfigView.modelListResultMessage(llmModelOptions);
        if (!llmSelectedModel) {
          llmSelectedModel = result.currentModel || llmModelOptions[0]?.value || getAppState()?.llm?.model || "";
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
      if (getAppState()?.job?.running) return;
      llmConfigEditing = true;
      llmSelectedModel = getAppState()?.llm?.model || llmSelectedModel;
      renderLlmConfig();
    }

    function cancelLlmConfigEdit() {
      if (getAppState()?.job?.running) return;
      llmConfigEditing = false;
      llmModelMenuOpen = false;
      llmModelSearchQuery = "";
      llmSelectedModel = getAppState()?.llm?.model || "";
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
      if (!getAppState() || getAppState().job?.running) return;
      const payload = llmConfigFormPayload();
      try {
        setAppState(await postJson("/api/llm-config", payload));
        llmModelMenuOpen = false;
        llmModelSearchQuery = "";
        llmSelectedModel = getAppState()?.llm?.model || payload.model;
        llmConfigEditing = false;
        showCommandNotice({
          tone: getAppState().llm?.configured ? "ready" : "partial",
          state: getAppState().llm?.configured ? t("llm.saveState") : t("llm.needsConfigState"),
          title: getAppState().llm?.configured ? t("llm.connectedTitle") : t("llm.paramsSavedTitle"),
          detail: getAppState().llm?.configured
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
      if (getAppState()?.job?.running || !getAppState()?.llm?.configured) return;
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
        setAppState(await postJson("/api/llm-config", payload));
        llmConfigEditing = false;
        llmModelMenuOpen = false;
        llmSelectedModel = getAppState()?.llm?.model || "";
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

    return {
      selectedLlmModel,
      renderLlmConfig,
      loadLlmModels,
      toggleLlmModelMenu,
      handleLlmModelSearchInput,
      handleLlmModelSearchKeydown,
      handleLlmModelDocumentClick,
      openLlmConfigEditor,
      cancelLlmConfigEdit,
      resetLlmModelCatalogForConnectionChange,
      saveLlmConfig,
      clearLlmKey,
      llmModelsLoading: () => llmModelsLoading,
      setLlmModelMenuOpen: (value) => {
        llmModelMenuOpen = value;
      },
      setLlmModelOptions: (value) => {
        llmModelOptions = value;
      },
      setLlmModelListMessage: (value) => {
        llmModelListMessage = value;
      },
      setLlmSelectedModel: (value) => {
        llmSelectedModel = value;
      },
      setLlmConfigEditing: (value) => {
        llmConfigEditing = value;
      },
    };
  }

  return { create };
})();
