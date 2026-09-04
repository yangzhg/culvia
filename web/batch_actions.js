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
    return { scope: "filtered", fileIds: [], count: 0, showing: 0, label: t("batch.scopeFiltered", {}, "全部筛选结果") };
  }

  function targetFromSelection(photos = [], selectedIds = [], matchedCount = null) {
    const selected = visibleSelectedIds(photos, selectedIds);
    if (selected.length) {
      return { scope: "selected", fileIds: selected, count: selected.length, label: t("batch.scopeSelected", {}, "已选照片") };
    }
    const showing = (photos || []).length;
    const parsedMatched = Number(matchedCount);
    const count = Number.isFinite(parsedMatched) ? Math.max(showing, Math.trunc(parsedMatched), 0) : showing;
    return { scope: "filtered", fileIds: [], count, showing, label: t("batch.scopeFiltered", {}, "全部筛选结果") };
  }

  function targetPhotos(photos = [], target = emptyTarget()) {
    const source = photos || [];
    if (target.scope !== "selected") return source;
    const selectedIds = new Set((target.fileIds || []).map((fileId) => String(fileId || "")).filter(Boolean));
    return source.filter((photo) => selectedIds.has(photoFileId(photo)));
  }

  function scopeSummary(target = emptyTarget()) {
    return t("batch.scopeSummary", { scope: target.label || t("batch.scopeFiltered", {}, "全部筛选结果"), count: Number(target.count || 0) }, `${target.label || "全部筛选结果"} ${Number(target.count || 0)} 张`);
  }

  function scopeTitle(target = emptyTarget()) {
    return target.scope === "selected"
      ? t("batch.scopeTitleSelected", {}, "批量操作只作用于已选照片")
      : t("batch.scopeTitleFiltered", {}, "批量操作作用于当前筛选结果");
  }

  function filterCountSummary(matchedCount, showingCount) {
    const parsedShowing = Number(showingCount);
    const showing = Number.isFinite(parsedShowing) ? Math.max(0, Math.trunc(parsedShowing)) : 0;
    const parsedMatched = Number(matchedCount);
    const matched = matchedCount == null || !Number.isFinite(parsedMatched)
      ? showing
      : Math.max(showing, Math.trunc(parsedMatched), 0);
    return t(
      "gallery.matchSummary",
      { matched, showing },
      `${matched} / ${showing}`,
    );
  }

  async function withCommittedFilter(scope, flushUpdate, operation) {
    if (scope === "filtered") await flushUpdate();
    return operation();
  }

  async function withCommittedTarget(target, flushUpdate, rebuildFilteredTarget, operation) {
    return withCommittedFilter(target?.scope, flushUpdate, () => {
      const committedTarget = target?.scope === "filtered" ? rebuildFilteredTarget() : target;
      return operation(committedTarget);
    });
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

  function filteredImpactDetail(detail, target = emptyTarget()) {
    const count = Number(target.count || 0);
    const showing = Number(target.showing ?? count);
    return target.scope === "filtered" && count > showing
      ? t(
        "batch.filteredLimitDetail",
        { count, detail, showing },
        `${detail}将更新全部 ${count} 张匹配照片；当前仅展示 ${showing} 张。`,
      )
      : detail;
  }

  function actionConfirmationMeta(action = {}) {
    if (action.kind === "color") {
      const colorLabel = String(action.colorLabel || "");
      const colorName = String(action.colorName || t("color.empty", {}, "无色标"));
      const clearing = !colorLabel;
      return {
        label: colorName,
        icon: "circle",
        tone: "pending",
        detail: t("batch.colorConfirmDetail", {}, "这会修改每张目标照片的色标。"),
        title: clearing
          ? t("batch.titleColorClear", {}, "清除这些照片的色标？")
          : t("batch.titleColor", { color: colorName }, `将色标设为${colorName}？`),
        buttonLabel: clearing
          ? t("batch.confirmColorClear", {}, "清除色标")
          : t("batch.confirmColor", { color: colorName }, `设为${colorName}`),
      };
    }
    if (action.kind === "accept") {
      const llm = action.basis === "llm";
      return {
        label: llm ? t("filters.llm", {}, "大模型") : t("manual.acceptModel", {}, "综合模型"),
        icon: llm ? "brain" : "sparkle",
        tone: "pending",
        detail: llm
          ? t("batch.acceptLlmConfirmDetail", {}, "有大模型评分的照片会更新人工星级和入选、待复核或淘汰判断。")
          : t("batch.acceptModelConfirmDetail", {}, "有综合模型评分的照片会更新人工星级和入选、待复核或淘汰判断。"),
        title: llm
          ? t("batch.titleAcceptLlm", {}, "采纳这些照片的\u200b大模型结果？")
          : t("batch.titleAcceptModel", {}, "采纳这些照片的\u200b综合模型结果？"),
        buttonLabel: llm
          ? t("batch.confirmAcceptLlm", {}, "采纳大模型")
          : t("batch.confirmAcceptModel", {}, "采纳综合模型"),
      };
    }
    const status = String(action.status || "");
    const meta = statusMeta(status);
    return {
      ...meta,
      title: t("batch.titleStatus", { status: meta.label }, `批量设为${meta.label}？`),
      buttonLabel: t("batch.confirmStatus", { status: meta.label }, `确认${meta.label}`),
    };
  }

  function statusTriggerSelector(status) {
    if (status === "reject") return "#galleryBatchRejectBtn";
    if (status === "pick") return "#galleryBatchPickBtn";
    return "#galleryBatchHoldBtn";
  }

  function confirmView(status, target = emptyTarget()) {
    return confirmActionView({ kind: "status", status }, target);
  }

  function confirmActionView(action, target = emptyTarget()) {
    const meta = actionConfirmationMeta(action);
    const count = Number(target.count || 0);
    return {
      actionLabel: meta.label,
      buttonLabel: meta.buttonLabel,
      countText: t("common.photoCount", { count }, `${count} 张`),
      detail: filteredImpactDetail(meta.detail, target),
      icon: meta.icon,
      scopeText: target.label || t("batch.scopeFiltered", {}, "全部筛选结果"),
      title: meta.title,
      tone: meta.tone,
    };
  }

  function acceptControls(target = emptyTarget(), photos = [], options = {}) {
    const scopedPhotos = targetPhotos(photos, target);
    const selectedScope = target.scope === "selected";
    const visibleHasLlmReview = scopedPhotos.some((photo) => {
      if (typeof options.hasLlmReview === "function") return Boolean(options.hasLlmReview(photo));
      return photo?.llmReviewScores?.llm_review_overall != null;
    });
    const filteredLlmReviewCount = Number(options.filteredLlmReviewCount);
    const hasLlmReview = !selectedScope && Number.isFinite(filteredLlmReviewCount)
      ? filteredLlmReviewCount > 0
      : visibleHasLlmReview;
    const hasPhotos = selectedScope ? scopedPhotos.length > 0 : Number(target.count || 0) > 0;
    return {
      photos: scopedPhotos,
      count: selectedScope ? scopedPhotos.length : Number(target.count || 0),
      hasPhotos,
      model: {
        icon: "sparkle",
        label: selectedScope ? t("batch.acceptSelected", {}, "采纳已选") : t("batch.acceptFiltered", {}, "采纳当前筛选"),
        disabled: !hasPhotos,
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
        ? t("batch.scopeFiltered", {}, "全部筛选结果")
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
    confirmActionView,
    confirmView,
    emptyTarget,
    filterCountSummary,
    scopeSummary,
    scopeTitle,
    statusMeta,
    statusTriggerSelector,
    targetFromSelection,
    targetPhotos,
    visibleSelectedIds,
    withCommittedFilter,
    withCommittedTarget,
  };
})();
