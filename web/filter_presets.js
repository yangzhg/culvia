(function () {
  const THRESHOLD_LABELS = [
    ["minScore", "推荐"],
    ["minModelQuality", "画质"],
    ["minAestheticReference", "审美参考"],
    ["minTechnical", "技术"],
    ["minLlmReview", "大模型"],
  ];

  function optionLabel(options, value, fallback = value) {
    return (options || []).find((item) => item.value === value)?.label || fallback;
  }

  function t(context, key, params = {}, fallback = "") {
    if (typeof context.t !== "function") return fallback || key;
    const value = context.t(key, params);
    return value === key && fallback ? fallback : value;
  }

  function contextualOptionLabel(context, group, options, value, fallback = value) {
    const option = (options || []).find((item) => item.value === value);
    if (typeof context.optionLabel === "function") {
      return context.optionLabel(group, option || { value, label: fallback });
    }
    return optionLabel(options, value, fallback);
  }

  function manualStatusText(value, context = {}) {
    if (typeof context.manualStatusLabel === "function") {
      return context.manualStatusLabel(value);
    }
    return value;
  }

  function colorLabelText(value, context = {}) {
    if (typeof context.colorLabelMeta === "function") {
      return context.colorLabelMeta(value)?.label || value;
    }
    return value;
  }

  function activeFilterChips(filters = {}, context = {}) {
    const chips = [];
    const options = context.options || {};
    const sortField = filters.sortField || "recommendation_0_10";
    const manualStatus = filters.manualStatus || "all";
    const colorLabel = filters.colorLabel || "all";
    const agreement = filters.modelAgreement || "all";
    const limit = Number(filters.limit || 80);
    const weightPreset = filters.weightPreset || "balanced";

    if (manualStatus !== "all") {
      chips.push(`${t(context, "filters.chip.manual", {}, "人工")}：${contextualOptionLabel(context, "manual", options.manualStatusOptions, manualStatus, manualStatusText(manualStatus, context))}`);
    }
    if (colorLabel !== "all") {
      chips.push(`${t(context, "filters.chip.color", {}, "色标")}：${contextualOptionLabel(context, "color", options.colorLabelOptions, colorLabel, colorLabelText(colorLabel, context))}`);
    }
    if (agreement !== "all") {
      chips.push(`${t(context, "filters.chip.review", {}, "评审")}：${contextualOptionLabel(context, "agreement", options.modelAgreementOptions, agreement, agreement)}`);
    }
    THRESHOLD_LABELS.forEach(([key, label]) => {
      const value = Number(filters[key] || 0);
      const localizedLabel = t(context, {
        minScore: "filters.recommendation",
        minModelQuality: "filters.modelQuality",
        minAestheticReference: "filters.aestheticReference",
        minTechnical: "filters.technicalReview",
        minLlmReview: "filters.llm",
      }[key], {}, label);
      if (value > 0) chips.push(`${localizedLabel} ≥ ${value.toFixed(1)}`);
    });
    if (sortField !== "recommendation_0_10") {
      chips.push(`${t(context, "filters.chip.sort", {}, "排序")}：${contextualOptionLabel(context, "sort", options.sortOptions, sortField, t(context, "common.custom", {}, "自定义"))}`);
    }
    if (limit !== 80) chips.push(`${t(context, "filters.chip.limit", {}, "最多")} ${t(context, "common.photoCount", { count: limit }, `${limit} 张`)}`);
    if (weightPreset !== "balanced") {
      chips.push(`${t(context, "filters.chip.weight", {}, "权重")}：${contextualOptionLabel(context, "weight", options.weightPresets, weightPreset, t(context, "common.custom", {}, "自定义"))}`);
    }
    return chips;
  }

  function suggestedName(filters = {}, context = {}) {
    const chips = activeFilterChips(filters, context);
    return chips.length ? chips.slice(0, 2).join(" · ") : t(context, "common.allPhotos", {}, "全量照片");
  }

  function summary(filters = {}, context = {}) {
    const chips = activeFilterChips(filters, context);
    return chips.length ? chips.slice(0, 3).join(" · ") : t(context, "common.defaultRange", {}, "默认范围");
  }

  function updatedText(updatedAt, now = Date.now(), context = {}) {
    const timestamp = Number(updatedAt || 0);
    if (!timestamp) return t(context, "common.localView", {}, "本地视图");
    const age = now - timestamp;
    if (age < 60 * 1000) return t(context, "common.justSaved", {}, "刚刚保存");
    if (age < 60 * 60 * 1000) {
      const count = Math.max(1, Math.round(age / 60000));
      return t(context, "common.minutesAgo", { count }, `${count} 分钟前`);
    }
    const date = new Date(timestamp);
    const locale = typeof context.language === "function" ? context.language() : "zh-CN";
    return date.toLocaleDateString(locale === "en" ? "en-US" : "zh-CN", { month: "numeric", day: "numeric" });
  }

  function metaText(preset = {}, context = {}) {
    const filterSummary = summary(preset.filters, context);
    const updated = updatedText(preset.updatedAt, Date.now(), context);
    return filterSummary === preset.name ? updated : `${filterSummary} · ${updated}`;
  }

  window.CulviaFilterPresets = {
    activeFilterChips,
    suggestedName,
    summary,
    updatedText,
    metaText,
  };
})();
