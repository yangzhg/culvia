(function () {
  const FILTER_STORAGE_KEY = "culvia.filters.v1";
  const FILTER_PRESETS_STORAGE_KEY = "culvia.filterPresets.v1";
  const MAX_FILTER_PRESETS = 12;

  function defaultFilterPayload() {
    return {
      sortField: "recommendation_0_10",
      minScore: 0,
      minModelQuality: 0,
      minAestheticReference: 0,
      minTechnical: 0,
      minLlmReview: 0,
      modelAgreement: "all",
      manualStatus: "all",
      colorLabel: "all",
      limit: 80,
      weightPreset: "balanced",
      customWeights: {
        aesthetic: 0.6,
        technical: 0.25,
        compositionLight: 0.15,
      },
    };
  }

  function normalizeFilterPayload(filters = {}) {
    const defaults = defaultFilterPayload();
    const customWeights = filters.customWeights || {};
    return {
      sortField: filters.sortField || defaults.sortField,
      minScore: Number(filters.minScore ?? defaults.minScore),
      minModelQuality: Number(filters.minModelQuality ?? defaults.minModelQuality),
      minAestheticReference: Number(filters.minAestheticReference ?? defaults.minAestheticReference),
      minTechnical: Number(filters.minTechnical ?? defaults.minTechnical),
      minLlmReview: Number(filters.minLlmReview ?? defaults.minLlmReview),
      modelAgreement: filters.modelAgreement || defaults.modelAgreement,
      manualStatus: filters.manualStatus || defaults.manualStatus,
      colorLabel: filters.colorLabel || defaults.colorLabel,
      limit: Number(filters.limit ?? defaults.limit),
      weightPreset: filters.weightPreset || defaults.weightPreset,
      customWeights: {
        aesthetic: Number(customWeights.aesthetic ?? defaults.customWeights.aesthetic),
        technical: Number(customWeights.technical ?? defaults.customWeights.technical),
        compositionLight: Number(customWeights.compositionLight ?? defaults.customWeights.compositionLight),
      },
    };
  }

  function filterPayloadEquals(left, right) {
    return JSON.stringify(normalizeFilterPayload(left)) === JSON.stringify(normalizeFilterPayload(right));
  }

  function filtersAreDefault(filters = {}) {
    return filterPayloadEquals(filters, defaultFilterPayload());
  }

  function savedFilterPayload() {
    try {
      const raw = localStorage.getItem(FILTER_STORAGE_KEY);
      return raw ? normalizeFilterPayload(JSON.parse(raw)) : null;
    } catch (_error) {
      localStorage.removeItem(FILTER_STORAGE_KEY);
      return null;
    }
  }

  function persistFilterPayload(filters = {}) {
    try {
      const payload = normalizeFilterPayload(filters);
      if (filtersAreDefault(payload)) {
        localStorage.removeItem(FILTER_STORAGE_KEY);
        return;
      }
      localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(payload));
    } catch (_error) {
      // A blocked localStorage write should not interrupt the culling workflow.
    }
  }

  function cleanPresetName(name) {
    return String(name || "").trim().replace(/\s+/g, " ").slice(0, 32);
  }

  function normalizeFilterPreset(preset = {}) {
    const name = cleanPresetName(preset.name);
    if (!name) return null;
    return {
      id: String(preset.id || `preset-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`),
      name,
      filters: normalizeFilterPayload(preset.filters || {}),
      updatedAt: Number(preset.updatedAt || Date.now()),
    };
  }

  function savedFilterPresets() {
    try {
      const raw = localStorage.getItem(FILTER_PRESETS_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map(normalizeFilterPreset)
        .filter(Boolean)
        .sort((left, right) => right.updatedAt - left.updatedAt)
        .slice(0, MAX_FILTER_PRESETS);
    } catch (_error) {
      localStorage.removeItem(FILTER_PRESETS_STORAGE_KEY);
      return [];
    }
  }

  function persistFilterPresets(presets = []) {
    const normalized = presets
      .map(normalizeFilterPreset)
      .filter(Boolean)
      .sort((left, right) => right.updatedAt - left.updatedAt)
      .slice(0, MAX_FILTER_PRESETS);
    try {
      if (!normalized.length) {
        localStorage.removeItem(FILTER_PRESETS_STORAGE_KEY);
        return [];
      }
      localStorage.setItem(FILTER_PRESETS_STORAGE_KEY, JSON.stringify(normalized));
    } catch (_error) {
      // Presets are convenience state; blocked storage should not stop culling.
    }
    return normalized;
  }

  function saveFilterPreset(name, filters = {}) {
    const cleanName = cleanPresetName(name);
    if (!cleanName) return savedFilterPresets();
    const preset = normalizeFilterPreset({
      id: `preset-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
      name: cleanName,
      filters,
      updatedAt: Date.now(),
    });
    const nextPresets = [preset, ...savedFilterPresets().filter((item) => item.name !== cleanName && item.id !== preset.id)];
    return persistFilterPresets(nextPresets);
  }

  function deleteFilterPreset(id) {
    return persistFilterPresets(savedFilterPresets().filter((item) => item.id !== id));
  }

  function renameFilterPreset(id, name) {
    const cleanName = cleanPresetName(name);
    const presets = savedFilterPresets();
    const target = presets.find((item) => item.id === id);
    if (!target || !cleanName) return presets;
    const renamed = { ...target, name: cleanName, updatedAt: Date.now() };
    return persistFilterPresets([renamed, ...presets.filter((item) => item.id !== id && item.name !== cleanName)]);
  }

  function updateFilterPreset(id, filters = {}) {
    const presets = savedFilterPresets();
    const target = presets.find((item) => item.id === id);
    if (!target) return presets;
    const updated = { ...target, filters: normalizeFilterPayload(filters), updatedAt: Date.now() };
    return persistFilterPresets([updated, ...presets.filter((item) => item.id !== id)]);
  }

  window.CulviaFilterState = {
    FILTER_STORAGE_KEY,
    FILTER_PRESETS_STORAGE_KEY,
    defaultFilterPayload,
    normalizeFilterPayload,
    filterPayloadEquals,
    filtersAreDefault,
    savedFilterPayload,
    persistFilterPayload,
    savedFilterPresets,
    persistFilterPresets,
    saveFilterPreset,
    deleteFilterPreset,
    renameFilterPreset,
    updateFilterPreset,
  };
})();
