window.CulviaViewerInspector = (() => {
  const {
    aestheticReferenceFields,
    llmAestheticFields,
    llmReviewFields,
    llmSummaryFields,
    llmTechnicalFields,
    metricLabelKeys,
    modelQualityFields,
    scoreFields,
    technicalFields,
    technicalTagKeys,
  } = window.CulviaAppConfig;
  const { escapeHtml, iconMarkup, textHintAttributes } = window.CulviaUiHelpers;
  const manualStatus = window.CulviaManualStatus;

  function t(key, params = {}) {
    const api = window.CulviaI18n;
    return api?.t ? api.t(key, params) : key;
  }

  function tr(key, params = {}, fallback = "") {
    const value = t(key, params);
    return value === key && fallback ? fallback : value;
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

  function scoreValue(value) {
    return value == null ? t("common.noData") : Number(value).toFixed(1);
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

  function metricText(value, missing = t("common.noData")) {
    return localizedMetricText(value, missing);
  }

  function hasMetric(value) {
    return Boolean(value && value !== "暂无");
  }

  function hasAnyMetric(texts, fields) {
    return fields.some((field) => hasMetric(texts?.[field]));
  }

  function localizedMetricLabel(field, labels = {}) {
    return tr(metricLabelKeys[field] || `sort.${field}_0_10`, {}, labels[field] || field);
  }

  function localizedTechnicalTag(tag) {
    const value = String(tag || "").trim();
    return value ? tr(technicalTagKeys[value] || "", {}, value) : "";
  }

  function manualStatusLabel(status) {
    const normalized = manualStatus.normalizeStatus(status);
    if (normalized === "pick") return t("manual.status.pick");
    if (normalized === "hold") return t("manual.status.hold");
    if (normalized === "reject") return t("manual.status.reject");
    return t("manual.status.unreviewed");
  }

  function insightMetaText(insight) {
    const parts = [];
    if (insight?.model) parts.push(insight.model);
    if (insight?.confidence != null) parts.push(t("insight.confidence", { percent: Math.round(Number(insight.confidence) * 100) }));
    return parts.join(" · ");
  }

  function renderSuggestionList(title, items, icon = "sparkle") {
    if (!items?.length) return "";
    return `
      <section class="insight-action-group">
        <div class="insight-action-title">
          ${iconMarkup(icon)}
          <span>${escapeHtml(title)}</span>
        </div>
        <ol class="insight-action-list">
          ${items
            .map(
              (item, index) => `
                <li>
                  <span>${String(index + 1).padStart(2, "0")}</span>
                  <p>${escapeHtml(item)}</p>
                </li>
              `,
            )
            .join("")}
        </ol>
      </section>
    `;
  }

  function renderLlmInsight(insight) {
    if (!insight) {
      return `
        <div class="insight-empty">
          ${escapeHtml(t("insight.empty"))}
        </div>
      `;
    }
    const photography = insight.photographySuggestions?.length
      ? insight.photographySuggestions
      : (insight.suggestions || [])
          .filter((item) => item.startsWith("拍摄："))
          .map((item) => item.replace(/^拍摄：/, ""));
    const retouching = insight.retouchingSuggestions?.length
      ? insight.retouchingSuggestions
      : (insight.suggestions || [])
          .filter((item) => item.startsWith("修图："))
          .map((item) => item.replace(/^修图：/, ""));
    const meta = insightMetaText(insight);
    return `
      <div class="insight-card">
        <div class="insight-cover">
          <div class="insight-mark">${iconMarkup("brain")}</div>
          <div class="insight-title-block">
            <span>${escapeHtml(t("insight.title"))}</span>
            <strong>${escapeHtml(insight.title || t("insight.fallbackTitle"))}</strong>
          </div>
          ${
            insight.score != null
              ? `<div class="insight-score"><strong>${scoreValue(insight.score)}</strong><span>${escapeHtml(t("insight.total"))}</span></div>`
              : ""
          }
        </div>
        ${insight.summary ? `<p class="insight-summary">${escapeHtml(insight.summary)}</p>` : ""}
        ${
          insight.explanation
            ? `
              <section class="insight-evidence">
                <span>${escapeHtml(t("insight.evidence"))}</span>
                <p>${escapeHtml(insight.explanation)}</p>
              </section>
            `
            : ""
        }
        <div class="insight-action-grid">
          ${renderSuggestionList(t("insight.photography"), photography, "aperture")}
          ${renderSuggestionList(t("insight.retouching"), retouching, "pencil")}
        </div>
        ${meta ? `<div class="insight-foot">${escapeHtml(meta)}</div>` : ""}
      </div>
    `;
  }

  function scoreRowsMarkup(photo, options = {}) {
    const appState = options.appState || {};
    const showMissingScoreDetails = Boolean(options.showMissingScoreDetails);
    const scoreLabels = appState.scoreLabels || {};
    const technicalLabels = appState.technicalLabels || {};
    const modelQualityLabels = appState.modelQualityLabels || {};
    const aestheticReferenceLabels = appState.aestheticReferenceLabels || {};
    const llmReviewLabels = appState.llmReviewLabels || {};
    const hasCoreScores = hasAnyMetric(photo.scoreTexts, scoreFields);
    const hasLlmScores = hasAnyMetric(photo.llmReviewTexts, llmReviewFields);
    const countMissing = (fields, texts) => fields.filter((field) => !hasMetric(texts?.[field])).length;
    const missingCount =
      countMissing(["overall", ...scoreFields], photo.scoreTexts) +
      countMissing(aestheticReferenceFields, photo.aestheticReferenceTexts) +
      countMissing(modelQualityFields, photo.modelQualityTexts) +
      countMissing(llmReviewFields, photo.llmReviewTexts) +
      countMissing(technicalFields, photo.technicalTexts);
    const sourceTitle = (label, source, value, missing = t("score.notCalculated"), titleOptions = {}) => {
      const hasValue = hasMetric(value);
      const valueMarkup = hasValue || !titleOptions.hideMissingValue
        ? `<strong class="${hasValue ? "" : "is-missing"}">${escapeHtml(metricText(value, missing))}</strong>`
        : "";
      return `
        <div class="score-group-title">
          <div>
            <span${textHintAttributes(label)}>${escapeHtml(label)}</span>
            <small${textHintAttributes(source)}>${escapeHtml(source)}</small>
          </div>
          ${valueMarkup}
        </div>
      `;
    };
    const missingNote = (message) => `<div class="score-missing-note">${escapeHtml(message)}</div>`;
    const scoreRow = (label, stars, text, missing = t("score.notCalculated")) => {
      const displayText = metricText(text, missing);
      return `
        <div class="score-row">
          <span class="score-name"${textHintAttributes(label)}>${escapeHtml(label)}</span>
          <span class="score-stars">${stars || "☆☆☆☆☆"}</span>
          <span class="score-num ${hasMetric(text) ? "" : "is-missing"}"${textHintAttributes(displayText)}>${escapeHtml(displayText)}</span>
        </div>
      `;
    };
    const metricRows = (fields, labels, stars, texts, missing = t("score.notCalculated")) =>
      fields
        .filter((field) => showMissingScoreDetails || hasMetric(texts?.[field]))
        .map((field) => scoreRow(localizedMetricLabel(field, labels), stars?.[field], texts?.[field], missing))
        .join("");
    const coreDetailFields = hasMetric(photo.overallText) ? scoreFields : ["overall", ...scoreFields];
    const scoreRows = coreDetailFields
      .filter((field) => showMissingScoreDetails || hasMetric(photo.scoreTexts?.[field]))
      .map((field) => scoreRow(localizedMetricLabel(field, scoreLabels), photo.scoreStars?.[field], photo.scoreTexts?.[field]))
      .join("");
    const modelQualityRows = metricRows(
      modelQualityFields,
      modelQualityLabels,
      photo.modelQualityStars,
      photo.modelQualityTexts,
      t("score.notCalculated"),
    );
    const aestheticReferenceRows = metricRows(
      aestheticReferenceFields,
      aestheticReferenceLabels,
      photo.aestheticReferenceStars,
      photo.aestheticReferenceTexts,
      t("score.notCalculated"),
    );
    const technicalRows = metricRows(technicalFields, technicalLabels, photo.technicalStars, photo.technicalTexts);
    const renderLlmRows = (fields) =>
      fields
        .filter((field) => showMissingScoreDetails || hasMetric(photo.llmReviewTexts?.[field]))
        .map((field) => scoreRow(localizedMetricLabel(field, llmReviewLabels), photo.llmReviewStars?.[field], photo.llmReviewTexts?.[field], t("score.notReviewed")))
        .join("");
    const llmSummaryRows = renderLlmRows(llmSummaryFields);
    const llmAestheticRows = renderLlmRows(llmAestheticFields);
    const llmTechnicalRows = renderLlmRows(llmTechnicalFields);
    const tags = (photo.technicalTags || [])
      .map((tag) => {
        const label = localizedTechnicalTag(tag);
        return `<span class="score-tag"${textHintAttributes(label)}>${escapeHtml(label)}</span>`;
      })
      .join("");
    const coreGroup = scoreRows || showMissingScoreDetails
      ? `
        <div class="score-group">
          ${sourceTitle(t("score.core.title"), t("score.core.source"), photo.overallText, t("score.notCalculated"), { hideMissingValue: true })}
          ${!hasCoreScores && showMissingScoreDetails ? missingNote(t("score.core.missingNote")) : ""}
          ${scoreRows}
        </div>
      `
      : "";
    const aestheticReferenceGroup = aestheticReferenceRows || showMissingScoreDetails
      ? `
        <div class="score-group">
          ${sourceTitle(t("score.aestheticReference.title"), t("score.aestheticReference.source"), photo.aestheticReferenceTexts?.clip_aesthetic)}
          ${aestheticReferenceRows}
          ${!aestheticReferenceRows && showMissingScoreDetails ? missingNote(t("score.aestheticReference.missingNote")) : ""}
        </div>
      `
      : "";
    const modelQualityGroup = modelQualityRows || showMissingScoreDetails
      ? `
        <div class="score-group">
          ${sourceTitle(t("score.modelQuality.title"), t("score.modelQuality.source"), photo.modelQualityTexts?.clip_iqa_overall)}
          ${modelQualityRows}
          ${!modelQualityRows && showMissingScoreDetails ? missingNote(t("score.modelQuality.missingNote")) : ""}
        </div>
      `
      : "";
    const llmGroup = hasLlmScores || photo.llmInsight || showMissingScoreDetails
      ? `
        <div class="score-group">
          ${sourceTitle(t("score.llm.title"), appState.llm?.model || t("score.llm.source"), photo.llmReviewTexts?.llm_review_overall, t("score.notReviewed"))}
          ${hasLlmScores ? llmSummaryRows : showMissingScoreDetails ? missingNote(t("score.llm.missingNote")) : ""}
          ${llmAestheticRows ? `<div class="score-subtitle">${escapeHtml(t("score.llm.aestheticSubtitle"))}</div>${llmAestheticRows}` : ""}
          ${llmTechnicalRows ? `<div class="score-subtitle">${escapeHtml(t("score.llm.technicalSubtitle"))}</div>${llmTechnicalRows}` : ""}
          ${photo.llmInsight || showMissingScoreDetails ? renderLlmInsight(photo.llmInsight) : ""}
        </div>
      `
      : "";
    const technicalGroup = technicalRows || tags || showMissingScoreDetails
      ? `
        <div class="score-group">
          ${sourceTitle(t("score.technical.title"), t("score.technical.source"), photo.technicalTexts?.technical_overall)}
          ${technicalRows}
          ${tags ? `<div class="score-tag-row">${tags}</div>` : ""}
        </div>
      `
      : "";
    const photoFolder = parentPath(photo.path);
    const fileRows = [
      { key: "name", label: t("score.file.name"), value: pathName(photo.path) },
      { key: "folder", label: t("score.file.folder"), value: photoFolder, action: "copyFolder" },
      { key: "photoSource", label: t("score.file.photoSource"), value: appState?.source?.mode === "uploads" ? t("score.file.uploads") : t("score.file.folders") },
      { key: "manualStatus", label: t("score.file.manualStatus"), value: manualStatusLabel(photo.manual?.status || "") },
    ]
      .map(({ key, label, value, action }) => {
        const displayValue = value || t("score.noData");
        const copyLabel = t("score.file.copyFolder");
        return `
          <div class="file-meta-row ${action ? "has-action" : ""}" data-file-meta="${escapeHtml(key)}">
            <span>${escapeHtml(label)}</span>
            <strong${textHintAttributes(displayValue)}>${escapeHtml(displayValue)}</strong>
            ${action === "copyFolder" && value ? `
              <button
                class="file-meta-copy"
                type="button"
                data-copy-file-folder="${escapeHtml(value)}"
                aria-label="${escapeHtml(copyLabel)}"
                data-ui-tooltip="${escapeHtml(copyLabel)}"
              >
                ${iconMarkup("copy")}
              </button>
            ` : ""}
          </div>
        `;
      })
      .join("");
    const fileGroup = `
      <div class="score-group">
        ${sourceTitle(t("score.file.title"), t("score.file.source"), pathName(photo.path), t("score.unnamed"))}
        <div class="file-meta-list">${fileRows}</div>
      </div>
    `;
    const detailViews = [
      {
        key: "overview",
        label: t("score.tab.overview"),
        content: [coreGroup, aestheticReferenceGroup].filter(Boolean).join(""),
        empty: t("score.empty.overview"),
      },
      {
        key: "llm",
        label: t("score.tab.llm"),
        content: llmGroup,
        empty: t("score.empty.llm"),
      },
      {
        key: "technical",
        label: t("score.tab.technical"),
        content: [modelQualityGroup, technicalGroup].filter(Boolean).join(""),
        empty: t("score.empty.technical"),
      },
      {
        key: "file",
        label: t("score.tab.file"),
        content: fileGroup,
        empty: t("score.empty.file"),
      },
    ];
    const requestedTab = String(options.activeTab || "overview");
    const activeTab = detailViews.some((view) => view.key === requestedTab) ? requestedTab : "overview";
    const activeDetailView = detailViews.find((view) => view.key === activeTab) || detailViews[0];
    const detailTabs = detailViews
      .map(
        (view) => `
          <button
            class="score-detail-tab ${view.key === activeDetailView.key ? "is-active" : ""}"
            type="button"
            role="tab"
            aria-selected="${view.key === activeDetailView.key ? "true" : "false"}"
            data-score-detail-tab="${view.key}"
          >
            ${escapeHtml(view.label)}
          </button>
        `,
      )
      .join("");
    const html = `
      <div class="score-detail-toolbar">
        <span>${escapeHtml(t("score.detailTitle"))}</span>
        <button
          id="toggleMissingScoreDetails"
          class="score-missing-toggle ${showMissingScoreDetails ? "is-active" : ""}"
          type="button"
          aria-label="${escapeHtml(missingCount ? t("score.missingTooltip", { count: missingCount }) : t("score.noMissingTooltip"))}"
          data-ui-tooltip="${escapeHtml(missingCount ? t("score.missingTooltip", { count: missingCount }) : t("score.noMissingTooltip"))}"
        >
          ${iconMarkup("eye")}
          ${escapeHtml(showMissingScoreDetails ? t("score.hideMissing") : t("score.showMissing"))}
        </button>
      </div>
      <div class="score-detail-tabs" role="tablist" aria-label="${escapeHtml(t("score.detailAria"))}">
        ${detailTabs}
      </div>
      ${
        activeDetailView.content
          ? `<div class="score-detail-panel" role="tabpanel">${activeDetailView.content}</div>`
          : `<div class="score-empty-note">${escapeHtml(activeDetailView.empty)}</div>`
      }
    `;
    return { activeTab, html, missingCount };
  }

  function signalChipsMarkup(photo, options = {}) {
    const chips = [
      {
        key: "overall",
        label: t("score.signal.overall"),
        source: t("score.signal.overallSource"),
        value: photo.recommendationText || photo.overallText,
        missing: t("score.signal.notCalculated"),
      },
      {
        key: "aesthetic-reference",
        label: t("score.signal.aestheticReference"),
        source: "CLIP",
        value: photo.aestheticReferenceTexts?.clip_aesthetic,
        missing: t("score.signal.notCalculated"),
      },
      {
        key: "llm",
        label: t("score.signal.llm"),
        source: options.llmModel || t("score.signal.llmSource"),
        value: photo.llmReviewTexts?.llm_review_overall,
        missing: t("score.signal.notReviewed"),
      },
      {
        key: "technical",
        label: t("score.signal.technical"),
        source: t("score.signal.technicalSource"),
        value: photo.technicalTexts?.technical_overall,
        missing: t("score.signal.notCalculated"),
      },
    ];
    return chips
      .map(
        (chip) => {
          const hasValue = hasMetric(chip.value);
          const valueText = metricText(chip.value, chip.missing);
          const hint = `${chip.label} · ${valueText} · ${chip.source}`;
          return `
            <div
              class="signal-chip ${hasValue ? "is-ready" : "is-missing"}"
              role="listitem"
              data-signal-chip="${escapeHtml(chip.key)}"
              data-signal-state="${hasValue ? "ready" : "missing"}"
              aria-label="${escapeHtml(hint)}"
              data-ui-tooltip="${escapeHtml(hint)}"
            >
              <span>${escapeHtml(chip.label)}</span>
              <strong>${escapeHtml(valueText)}</strong>
              <small>${escapeHtml(chip.source)}</small>
            </div>
          `;
        },
      )
      .join("");
  }

  return {
    scoreRowsMarkup,
    signalChipsMarkup,
  };
})();
