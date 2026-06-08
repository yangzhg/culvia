window.CulviaLlmConfigView = (() => {
  const htmlEscapes = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  const knownSourceLabels = new Set(["default", "env", "environment", "keychain", "persisted", "session", "sqlite"]);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => htmlEscapes[char]);
  }

  function t(key, params = {}) {
    const api = window.CulviaI18n;
    return api?.t ? api.t(key, params) : key;
  }

  function zh(key) {
    const api = window.CulviaI18n;
    return api?.t ? api.t(key, {}, "zh-CN") : key;
  }

  function sourceLabel(source) {
    const value = String(source || "").trim();
    if (!value || value === "unconfigured" || value === zh("llmConfirm.unconfigured")) return t("llmConfirm.unconfigured");
    return knownSourceLabels.has(value) ? t(`llm.source.${value}`) : value;
  }

  function promptPresetLabel(llm) {
    const selected = llm?.promptPreset || "balanced";
    const preset = (llm?.promptPresets || []).find((option) => option.value === selected);
    return preset?.label || selected || t("llm.promptDefault");
  }

  function customPromptSummary(value, limit = 24) {
    const text = String(value || "").trim();
    if (!text) return "";
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
  }

  function normalizedModelOptions({ currentModel, fallbackModel = "gpt-4o-mini", providerOptions = [] } = {}) {
    const seen = new Set();
    const options = [];
    const addOption = (value, source = "provider") => {
      const model = String(value || "").trim();
      if (!model || seen.has(model)) return;
      seen.add(model);
      options.push({ value: model, label: model, source });
    };
    addOption(currentModel, "current");
    (Array.isArray(providerOptions) ? providerOptions : []).forEach((option) => {
      addOption(option?.value || option?.id || option?.label, option?.source || "provider");
    });
    if (!options.length) addOption(fallbackModel, "current");
    return options;
  }

  function modelButtonMeta(selectedOption, hasProviderOptions) {
    if (selectedOption?.source === "current") return t("llm.currentConfig");
    return hasProviderOptions ? t("llm.modelsFetched") : t("llm.pickFromList");
  }

  function modelPickerState({ currentModel, fallbackModel, providerOptions, selectedModel, searchQuery = "" } = {}) {
    const options = normalizedModelOptions({ currentModel, fallbackModel, providerOptions });
    const selected = String(selectedModel || currentModel || options[0]?.value || "");
    const selectedOption = options.find((option) => option.value === selected) || options[0];
    const query = String(searchQuery || "").trim().toLowerCase();
    const visibleOptions = query
      ? options.filter((option) => option.value.toLowerCase().includes(query))
      : options;
    return {
      buttonMeta: modelButtonMeta(selectedOption, Boolean(providerOptions?.length)),
      buttonText: selectedOption?.label || t("llm.chooseModel"),
      options,
      query,
      selected,
      selectedOption,
      visibleOptions: visibleOptions.map((option) => ({
        ...option,
        active: option.value === selected,
        ariaSelected: option.value === selected ? "true" : "false",
        className: `llm-model-option ${option.value === selected ? "is-selected" : ""}`.trim(),
        meta: option.source === "current" ? t("llm.modelCurrent") : t("llm.modelAvailable"),
      })),
    };
  }

  function promptOptionViews(llm) {
    const selectedPrompt = llm?.promptPreset || "balanced";
    return (llm?.promptPresets || []).map((option) => {
      const active = option.value === selectedPrompt;
      return {
        ariaChecked: active ? "true" : "false",
        className: `llm-prompt-option ${active ? "is-active" : ""}`.trim(),
        description: option.description || "",
        label: option.label,
        value: option.value,
      };
    });
  }

  function modelOptionMarkup(option, { checkIcon = "" } = {}) {
    return `
      <button
        class="${escapeHtml(option.className)}"
        type="button"
        role="option"
        aria-selected="${escapeHtml(option.ariaSelected)}"
        aria-label="${escapeHtml(option.label)}"
        data-ui-tooltip="${escapeHtml(option.label)}"
        data-model-value="${escapeHtml(option.value)}"
      >
        <span class="llm-model-option-main" aria-label="${escapeHtml(option.label)}" data-ui-tooltip="${escapeHtml(option.label)}">${escapeHtml(option.label)}</span>
        <span class="llm-model-option-meta">${escapeHtml(option.meta)}</span>
        <span class="llm-model-option-check">${option.active ? String(checkIcon || "") : ""}</span>
      </button>
    `;
  }

  function modelOptionsMarkup(options, { checkIcon = "", emptyText = t("llm.noMatchingModels") } = {}) {
    const visibleOptions = Array.isArray(options) ? options : [];
    if (!visibleOptions.length) return `<div class="llm-model-empty">${escapeHtml(emptyText)}</div>`;
    return visibleOptions.map((option) => modelOptionMarkup(option, { checkIcon })).join("");
  }

  function modelListResultMessage(models = []) {
    const count = Array.isArray(models) ? models.length : Number(models) || 0;
    return count > 0 ? t("llm.modelsCount", { count }) : t("llm.noAvailableModels");
  }

  function modelPickerDomPlan(pickerState, { checkIcon = "", menuOpen = false, searchQuery = "" } = {}) {
    return {
      button: {
        ariaExpanded: menuOpen ? "true" : "false",
        metaSelector: "#llmModelButtonMeta",
        metaText: pickerState.buttonMeta,
        selector: "#llmModelButton",
        textSelector: "#llmModelButtonText",
        text: pickerState.buttonText,
      },
      list: {
        html: modelOptionsMarkup(pickerState.visibleOptions, { checkIcon }),
        selector: "#llmModelList",
      },
      menu: {
        hidden: !menuOpen,
        selector: "#llmModelMenu",
      },
      picker: {
        open: Boolean(menuOpen),
        selector: "#llmModelPicker",
      },
      searchInput: {
        selector: "#llmModelSearchInput",
        value: searchQuery,
      },
    };
  }

  function promptOptionMarkup(option) {
    return `
      <button
        class="${escapeHtml(option.className)}"
        type="button"
        role="radio"
        aria-checked="${escapeHtml(option.ariaChecked)}"
        data-llm-prompt="${escapeHtml(option.value)}"
      >
        <span>${escapeHtml(option.label)}</span>
        <small>${escapeHtml(option.description || "")}</small>
      </button>
    `;
  }

  function promptOptionsMarkup(options) {
    return (Array.isArray(options) ? options : []).map((option) => promptOptionMarkup(option)).join("");
  }

  function promptSelectionDomPlan(selectedPrompt = "balanced") {
    const value = String(selectedPrompt || "balanced");
    return {
      input: {
        selector: "#llmPromptPreset",
        value,
      },
      options: {
        activeClass: "is-active",
        ariaAttribute: "aria-checked",
        datasetKey: "llmPrompt",
        selectedValue: value,
        selector: "[data-llm-prompt]",
      },
    };
  }

  function connectionPayload(values = {}) {
    return {
      apiKey: String(values.apiKey || "").trim(),
      baseUrl: String(values.baseUrl || "").trim(),
      model: String(values.model || "").trim(),
      cachePath: String(values.cachePath || "").trim(),
    };
  }

  function configFormPayload(values = {}) {
    const promptPreset = String(values.promptPreset || "balanced").trim() || "balanced";
    const payload = {
      ...connectionPayload(values),
      promptPreset,
      customPrompt: String(values.customPrompt || "").trim(),
      persist: Boolean(values.persist),
    };
    if (values.clearKey) payload.clearKey = true;
    return payload;
  }

  function configViewState(llm = {}, { editing = false, modelsLoading = false, modelListMessage = "" } = {}) {
    const configured = Boolean(llm?.configured);
    const promptLabel = promptPresetLabel(llm);
    const customSummary = customPromptSummary(llm?.customPrompt);
    const model = llm?.model || t("llm.defaultModel");
    const keyLabel = llm?.keyLabel || t("llm.keyConfigured");
    const source = configured ? sourceLabel(llm?.source) : t("llmConfirm.unconfigured");
    return {
      configured,
      statusText: configured ? t("llm.keyConfigured") : t("llmConfirm.unconfigured"),
      statusReady: configured,
      modelPreview: model,
      readonlyHidden: Boolean(editing),
      editorHidden: !editing,
      editHidden: Boolean(editing),
      cancelHidden: !editing,
      readonly: {
        key: configured ? keyLabel : t("llmConfirm.unconfigured"),
        source,
        baseUrl: llm?.baseUrl || llm?.endpoint || t("llmConfirm.defaultEndpoint"),
        model,
        prompt: customSummary ? `${promptLabel} · ${customSummary}` : promptLabel,
      },
      inputs: {
        apiKeyValue: "",
        apiKeyPlaceholder: configured ? t("llm.replaceKeyPlaceholder", { key: keyLabel }) : "API Key",
        baseUrlValue: llm?.baseUrl || "",
        baseUrlPlaceholder: llm?.endpoint || t("llm.baseUrlPlaceholder"),
        customPromptValue: llm?.customPrompt || "",
        promptPreset: llm?.promptPreset || "balanced",
      },
      hint: configured
        ? t("llm.configuredHint", { key: keyLabel, model, source })
        : t("llm.unconfiguredHint"),
      modelListHint: modelsLoading
        ? t("llm.loadingModels")
        : modelListMessage || (configured ? t("llm.fetchModelsReady") : t("llm.modelHint")),
      refreshIcon: modelsLoading ? "loader" : "refreshCw",
    };
  }

  function configDomUpdatePlan(viewState) {
    return {
      inputs: [
        {
          placeholder: viewState.inputs.baseUrlPlaceholder,
          selector: "#llmBaseUrlInput",
          value: viewState.inputs.baseUrlValue,
        },
        {
          placeholder: viewState.inputs.apiKeyPlaceholder,
          selector: "#llmApiKeyInput",
          value: viewState.inputs.apiKeyValue,
        },
        {
          selector: "#llmCustomPromptInput",
          value: viewState.inputs.customPromptValue,
        },
      ],
      refreshButton: {
        icon: viewState.refreshIcon,
        selector: "#refreshLlmModelsBtn",
      },
      status: {
        ready: viewState.statusReady,
        selector: "#llmStatusPill",
        text: viewState.statusText,
      },
      texts: [
        { selector: "#llmModelPreview", text: viewState.modelPreview },
        { selector: "#llmReadonlyKey", text: viewState.readonly.key },
        { selector: "#llmReadonlySource", text: viewState.readonly.source },
        { selector: "#llmReadonlyBaseUrl", text: viewState.readonly.baseUrl },
        { selector: "#llmReadonlyModel", text: viewState.readonly.model },
        { selector: "#llmReadonlyPrompt", text: viewState.readonly.prompt },
        { selector: "#llmConfigHint", text: viewState.hint },
        { selector: "#llmModelListHint", text: viewState.modelListHint },
      ],
      visibility: [
        { hidden: viewState.readonlyHidden, selector: "#llmConfigReadonly" },
        { hidden: viewState.editorHidden, selector: "#llmConfigEditor" },
        { hidden: viewState.editHidden, selector: "#editLlmConfigBtn" },
        { hidden: viewState.cancelHidden, selector: "#cancelLlmConfigBtn" },
      ],
    };
  }

  return {
    configDomUpdatePlan,
    configFormPayload,
    configViewState,
    connectionPayload,
    customPromptSummary,
    escapeHtml,
    modelButtonMeta,
    modelListResultMessage,
    modelOptionMarkup,
    modelOptionsMarkup,
    modelPickerDomPlan,
    modelPickerState,
    normalizedModelOptions,
    promptOptionMarkup,
    promptSelectionDomPlan,
    promptOptionViews,
    promptOptionsMarkup,
    promptPresetLabel,
    sourceLabel,
  };
})();
