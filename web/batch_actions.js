window.CulviaBatchActions = (() => {
  function t(key, params = {}, fallback = "") {
    const api = window.CulviaI18n;
    const value = api?.t ? api.t(key, params) : key;
    return value === key && fallback ? fallback : value;
  }

  function photoFileId(photo) {
    return String(photo?.fileId || "");
  }

  function visibleSelectedIds(photos = [], selectedIds = []) {
    const visibleIds = new Set((photos || []).map(photoFileId).filter(Boolean));
    return (selectedIds || []).map((fileId) => String(fileId || "")).filter((fileId) => fileId && visibleIds.has(fileId));
  }

  function emptyTarget() {
    return { scope: "filtered", fileIds: [], count: 0, label: t("batch.scopeFiltered", {}, "当前筛选") };
  }

  function targetFromSelection(photos = [], selectedIds = []) {
    const selected = visibleSelectedIds(photos, selectedIds);
    if (selected.length) {
      return { scope: "selected", fileIds: selected, count: selected.length, label: t("batch.scopeSelected", {}, "已选照片") };
    }
    return { scope: "filtered", fileIds: [], count: (photos || []).length, label: t("batch.scopeFiltered", {}, "当前筛选") };
  }

  function targetPhotos(photos = [], target = emptyTarget()) {
    const source = photos || [];
    if (target.scope !== "selected") return source;
    const selectedIds = new Set((target.fileIds || []).map((fileId) => String(fileId || "")).filter(Boolean));
    return source.filter((photo) => selectedIds.has(photoFileId(photo)));
  }

  function scopeSummary(target = emptyTarget()) {
    return t("batch.scopeSummary", { scope: target.label || t("batch.scopeFiltered", {}, "当前筛选"), count: Number(target.count || 0) }, `${target.label || "当前筛选"} ${Number(target.count || 0)} 张`);
  }

  function scopeTitle(target = emptyTarget()) {
    return target.scope === "selected"
      ? t("batch.scopeTitleSelected", {}, "批量操作只作用于已选照片")
      : t("batch.scopeTitleFiltered", {}, "批量操作作用于当前筛选结果");
  }

  function statusMeta(status) {
    if (status === "pick") {
      return { label: t("manual.status.pick", {}, "入选"), icon: "check", tone: "pick", detail: t("batch.pickDetail", {}, "这些照片会被标为入选，并进入后续导出候选。") };
    }
    if (status === "reject") {
      return { label: t("manual.status.reject", {}, "淘汰"), icon: "x", tone: "reject", detail: t("batch.rejectDetail", {}, "这些照片会被标为淘汰，通常不会进入交付集合。") };
    }
    return { label: t("manual.status.hold", {}, "待复核"), icon: "clock", tone: "pending", detail: t("batch.holdDetail", {}, "这些照片会进入待复核状态，可稍后重新判断。") };
  }

  function statusTriggerSelector(status) {
    if (status === "reject") return "#galleryBatchRejectBtn";
    if (status === "pick") return "#galleryBatchPickBtn";
    return "#galleryBatchHoldBtn";
  }

  function confirmView(status, target = emptyTarget()) {
    const meta = statusMeta(status);
    return {
      actionLabel: meta.label,
      buttonLabel: t("batch.confirmStatus", { status: meta.label }, `确认${meta.label}`),
      countText: t("batch.confirmCount", { count: Number(target.count || 0), scope: target.label || t("batch.scopeFiltered", {}, "当前筛选") }, `${Number(target.count || 0)} 张 · ${target.label || "当前筛选"}`),
      detail: meta.detail,
      icon: meta.icon,
      scopeText: target.label || t("batch.scopeFiltered", {}, "当前筛选"),
      title: t("batch.titleStatus", { status: meta.label }, `批量设为${meta.label}？`),
      tone: meta.tone,
    };
  }

  function acceptControls(target = emptyTarget(), photos = [], options = {}) {
    const scopedPhotos = targetPhotos(photos, target);
    const selectedScope = target.scope === "selected";
    const hasLlmReview = scopedPhotos.some((photo) => {
      if (typeof options.hasLlmReview === "function") return Boolean(options.hasLlmReview(photo));
      return photo?.llmReviewScores?.llm_review_overall != null;
    });
    return {
      photos: scopedPhotos,
      count: scopedPhotos.length,
      hasPhotos: scopedPhotos.length > 0,
      model: {
        icon: "sparkle",
        label: selectedScope ? t("batch.acceptSelected", {}, "采纳已选") : t("batch.acceptFiltered", {}, "采纳当前筛选"),
        disabled: !scopedPhotos.length,
      },
      llm: {
        icon: "brain",
        label: selectedScope ? t("batch.acceptSelectedLlm", {}, "采纳已选大模型") : t("batch.acceptLlm", {}, "采纳大模型"),
        disabled: !hasLlmReview,
      },
    };
  }

  function acceptNotice(options = {}) {
    const action = options.action || {};
    const basis = options.basis === "llm" ? "llm" : "model";
    const scope = options.scope || "current";
    const accepted = Number(action.accepted || 0);
    const skipped = Number(action.skipped || 0);
    const sourceLabel = basis === "llm" ? t("filters.llm", {}, "大模型") : t("manual.acceptModel", {}, "综合模型");
    const scopeLabel = scope === "selected"
      ? t("batch.scopeSelected", {}, "已选照片")
      : scope === "filtered"
        ? t("batch.scopeFiltered", {}, "当前筛选")
        : t("batch.scopeCurrent", {}, "当前照片");
    return {
      duration: accepted ? 6200 : 2400,
      notice: {
        tone: accepted ? "ready" : "partial",
        state: accepted ? t("batch.noticeAccepted", {}, "已采纳") : t("batch.noticeNothingAccepted", {}, "无可采纳"),
        title: t("batch.noticeAppliedTitle", { source: sourceLabel }, `${sourceLabel}结果已应用`),
        detail: skipped
          ? t("batch.noticeAppliedDetailSkipped", { accepted, scope: scopeLabel, skipped }, `${scopeLabel} · ${accepted} 张已更新，${skipped} 张缺少分数`)
          : t("batch.noticeAppliedDetail", { accepted, scope: scopeLabel }, `${scopeLabel} · ${accepted} 张已更新`),
      },
    };
  }

  function colorChoiceViews(items = [], options = {}) {
    const disabled = Boolean(options.disabled);
    return (items || []).map((item) => {
      const value = String(item?.value || "");
      const label = String(item?.label || t("filters.color", {}, "色标"));
      const shortcut = String(item?.shortcut || "");
      return {
        className: `manual-color-choice batch-color-choice ${value ? `is-${value}` : "is-clear"}`,
        disabled,
        text: value ? "" : "×",
        title: `${label}${shortcut ? ` · ${shortcut.toUpperCase()}` : ""}`,
        value,
      };
    });
  }

  function colorNotice(options = {}) {
    const colorLabel = String(options.colorLabel || "");
    const colorName = String(options.colorName || t("filters.color", {}, "色标"));
    const count = Number(options.count || 0);
    const target = options.target || emptyTarget();
    return {
      tone: "success",
      state: t("batch.colorMarked", {}, "已标记"),
      title: colorLabel ? t("batch.colorSetTitle", { color: colorName }, `已设为${colorName}`) : t("batch.colorClearedTitle", {}, "已清除色标"),
      detail: scopeSummary({ ...target, count }),
    };
  }

  return {
    acceptControls,
    acceptNotice,
    colorChoiceViews,
    colorNotice,
    confirmView,
    emptyTarget,
    scopeSummary,
    scopeTitle,
    statusMeta,
    statusTriggerSelector,
    targetFromSelection,
    targetPhotos,
    visibleSelectedIds,
  };
})();
