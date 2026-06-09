window.CulviaGalleryView = (() => {
  const manualStatus = window.CulviaManualStatus;
  const { escapeHtml, iconMarkup, textHintAttributes } = window.CulviaUiHelpers;

  function cardSignature(photo, language = "") {
    const manual = photo?.manual || {};
    return JSON.stringify({
      fileId: photo?.fileId || "",
      aestheticReferenceTexts: photo?.aestheticReferenceTexts || {},
      language,
      level: photo?.level || "",
      llmInsightSummary: photo?.llmInsight?.summary || "",
      llmReviewTexts: photo?.llmReviewTexts || {},
      manual: {
        acceptedScore: manual.acceptedScore ?? null,
        colorLabel: manual.colorLabel || "",
        rating: manual.rating || 0,
        sourceLabel: manual.sourceLabel || "",
        status: manual.status || "",
      },
      modelQualityTexts: photo?.modelQualityTexts || {},
      overallText: photo?.overallText || "",
      recommendationStars: photo?.recommendationStars || photo?.stars || "",
      recommendationText: photo?.recommendationText || "",
      scoreTexts: photo?.scoreTexts || {},
      technicalTags: photo?.technicalTags || [],
      technicalTexts: photo?.technicalTexts || {},
      thumb: photo?.thumb || "",
    });
  }

  function emptyStateMarkup(options = {}) {
    return `
      <div class="empty-state">
        <div class="empty-symbol">${iconMarkup("image", "empty-icon")}</div>
        <h2>${escapeHtml(options.title || "")}</h2>
        <p>${escapeHtml(options.text || "")}</p>
      </div>
    `;
  }

  function loadingStateMarkup(options = {}) {
    const title = escapeHtml(options.title || "");
    const text = escapeHtml(options.text || "");
    const state = escapeHtml(options.state || "");
    const skeletons = Array.from({ length: 8 })
      .map(
        () => `
          <div class="gallery-scan-skeleton">
            <span></span>
            <strong></strong>
          </div>
        `,
      )
      .join("");
    return `
      <div class="gallery-scan-state" role="status" aria-live="polite">
        <div class="gallery-scan-orbit" aria-hidden="true">
          <span></span>
          <span></span>
        </div>
        <div class="gallery-scan-copy">
          <span>${state}</span>
          <h2>${title}</h2>
          <p>${text}</p>
        </div>
        <div class="gallery-scan-grid" aria-hidden="true">${skeletons}</div>
      </div>
    `;
  }

  function tooltipMarkup(photo, options = {}) {
    const manual = photo.manual || {};
    const manualStatusText = options.manualStatusLabel?.(manual.status || "") || "";
    const photoLevel = options.localizedScoreLevel?.(photo.level) || "";
    const detailRows = [
      [options.t?.("gallery.detail.manualDecision") || "", manualStatusText],
      [options.t?.("gallery.detail.manualRating") || "", manual.rating ? options.manualStars?.(manual.rating) : options.t?.("gallery.unscored")],
      [
        options.t?.("gallery.detail.acceptSource") || "",
        manual.sourceLabel ? options.localizedManualSource?.(manual) : options.t?.("gallery.manualUnconfirmed"),
      ],
      [options.t?.("gallery.detail.aestheticProfile") || "", photo.overallText],
      [options.t?.("gallery.detail.aestheticReference") || "", photo.aestheticReferenceTexts?.clip_aesthetic],
      [options.t?.("gallery.detail.llmOverall") || "", photo.llmReviewTexts?.llm_review_overall],
      [options.t?.("gallery.detail.llmAesthetic") || "", photo.llmReviewTexts?.llm_aesthetic_overall],
      [options.t?.("gallery.detail.llmTechnical") || "", photo.llmReviewTexts?.llm_technical_overall],
      [options.t?.("gallery.detail.modelQuality") || "", photo.modelQualityTexts?.clip_iqa_overall],
      [options.t?.("gallery.detail.technicalQc") || "", photo.technicalTexts?.technical_overall],
      [options.t?.("gallery.detail.composition") || "", photo.scoreTexts?.composition],
      [options.t?.("gallery.detail.light") || "", photo.scoreTexts?.lighting],
      [options.t?.("gallery.detail.color") || "", photo.scoreTexts?.color],
      [options.t?.("gallery.detail.sharpness") || "", photo.technicalTexts?.sharpness],
      [options.t?.("gallery.detail.exposure") || "", photo.technicalTexts?.exposure],
    ];
    const tooltipRows = detailRows
      .map(([label, value]) => {
        const displayValue = options.localizedMetricText?.(value, options.t?.("common.noData")) || "";
        return `
          <div class="rating-tooltip-row">
            <span${textHintAttributes(label)}>${escapeHtml(label)}</span>
            <strong${textHintAttributes(displayValue)}>${escapeHtml(displayValue)}</strong>
          </div>
        `;
      })
      .join("");
    const tags = (photo.technicalTags || [])
      .map((tag) => {
        const label = options.localizedTechnicalTag?.(tag) || "";
        return `<span${textHintAttributes(label)}>${escapeHtml(label)}</span>`;
      })
      .join("");
    return `
      <div class="rating-tooltip" role="tooltip">
        <div class="rating-tooltip-head">
          <span${textHintAttributes(photoLevel)}>${escapeHtml(photoLevel)}</span>
          <strong${textHintAttributes(photo.recommendationText || photo.overallText)}>${escapeHtml(photo.recommendationText || photo.overallText)}</strong>
        </div>
        ${tooltipRows}
        ${photo.llmInsight?.summary ? `<p class="rating-tooltip-summary">${escapeHtml(photo.llmInsight.summary)}</p>` : ""}
        ${tags ? `<div class="rating-tooltip-tags">${tags}</div>` : ""}
      </div>
    `;
  }

  function cardMarkup(photo, index, selected, signature, options = {}) {
    const manual = photo.manual || {};
    const disabled = Boolean(options.disabled);
    const photoLevel = options.localizedScoreLevel?.(photo.level) || "";
    const selectLabel = options.gallerySelectLabel?.(photo, selected) || "";
    const pickLabel = options.galleryQuickActionLabel?.(photo, "pick") || "";
    const pendingLabel = options.galleryQuickActionLabel?.(photo, "hold") || "";
    const rejectLabel = options.galleryQuickActionLabel?.(photo, "reject") || "";
    const loadingMode = index < 12 ? "eager" : "lazy";
    const fetchPriority = index < 6 ? "high" : "auto";
    return `
      <article class="photo-card ${manualStatus.statusClass(manual.status)} ${selected ? "is-selected" : ""}" data-index="${index}" data-file-id="${escapeHtml(photo.fileId)}" data-gallery-signature="${escapeHtml(signature)}">
        <img src="${escapeHtml(photo.thumb)}" alt="${escapeHtml(options.t?.("gallery.thumbnailAlt") || "")}" loading="${loadingMode}" decoding="async" fetchpriority="${fetchPriority}" data-gallery-thumb />
        <div class="gallery-thumb-loading" aria-hidden="true">
          <span></span>
        </div>
        <div class="gallery-thumb-fallback" aria-hidden="true">
          ${iconMarkup("image", "gallery-thumb-fallback-icon")}
          <span>${escapeHtml(options.t?.("gallery.thumbnailUnavailable") || "")}</span>
        </div>
        <button
          class="gallery-select-toggle ${selected ? "is-selected" : ""}"
          type="button"
          data-gallery-select="${escapeHtml(photo.fileId)}"
          aria-pressed="${selected ? "true" : "false"}"
          aria-label="${escapeHtml(selectLabel)}"
          data-ui-tooltip="${escapeHtml(selectLabel)}"
          ${disabled ? "disabled" : ""}
        >${iconMarkup(selected ? "checkSquare" : "square", "gallery-select-icon")}</button>
        ${options.galleryColorBadgeMarkup?.(manual) || ""}
        <div class="gallery-quick-actions" aria-label="${escapeHtml(options.t?.("gallery.quickAria") || "")}">
          <button
            class="gallery-quick-action ${manual.status === "pick" ? "is-active is-picked" : ""}"
            type="button"
            data-gallery-status="pick"
            data-file-id="${escapeHtml(photo.fileId)}"
            aria-label="${escapeHtml(pickLabel)}"
            data-ui-tooltip="${escapeHtml(pickLabel)}"
            ${disabled ? "disabled" : ""}
          >${iconMarkup("check", "gallery-quick-icon")}</button>
          <button
            class="gallery-quick-action ${manual.status === "hold" ? "is-active is-pending" : ""}"
            type="button"
            data-gallery-status="hold"
            data-file-id="${escapeHtml(photo.fileId)}"
            aria-label="${escapeHtml(pendingLabel)}"
            data-ui-tooltip="${escapeHtml(pendingLabel)}"
            ${disabled ? "disabled" : ""}
          >${iconMarkup("clockCompact", "gallery-quick-icon")}</button>
          <button
            class="gallery-quick-action ${manual.status === "reject" ? "is-active is-rejected" : ""}"
            type="button"
            data-gallery-status="reject"
            data-file-id="${escapeHtml(photo.fileId)}"
            aria-label="${escapeHtml(rejectLabel)}"
            data-ui-tooltip="${escapeHtml(rejectLabel)}"
            ${disabled ? "disabled" : ""}
          >${iconMarkup("x", "gallery-quick-icon")}</button>
        </div>
        <footer class="photo-card-overlay">
          <div
            class="gallery-rating"
            tabindex="0"
            aria-label="${escapeHtml(options.t?.("gallery.viewRating") || "")}"
          >
            <span class="rating-label"${textHintAttributes(photoLevel)}>${escapeHtml(photoLevel)}</span>
            <strong>${escapeHtml(photo.recommendationText || photo.overallText)}</strong>
            <span>${escapeHtml(photo.recommendationStars || photo.stars)}</span>
          </div>
        </footer>
      </article>
    `;
  }

  function updateSelectionState(card, photo, index, selected, options = {}) {
    const disabled = Boolean(options.disabled);
    card.dataset.index = String(index);
    card.classList.toggle("is-selected", selected);
    const button = card.querySelector("[data-gallery-select]");
    if (!button) return;
    const previousSelected = button.classList.contains("is-selected");
    const selectLabel = options.gallerySelectLabel?.(photo, selected) || "";
    button.classList.toggle("is-selected", selected);
    button.disabled = disabled;
    button.dataset.gallerySelect = photo.fileId || "";
    button.setAttribute("aria-pressed", selected ? "true" : "false");
    button.setAttribute("aria-label", selectLabel);
    button.dataset.uiTooltip = selectLabel;
    if (previousSelected !== selected) {
      button.innerHTML = iconMarkup(selected ? "checkSquare" : "square", "gallery-select-icon");
    }
    card.querySelectorAll("[data-gallery-status]").forEach((statusButton) => {
      statusButton.disabled = disabled;
    });
  }

  return {
    cardMarkup,
    cardSignature,
    emptyStateMarkup,
    loadingStateMarkup,
    tooltipMarkup,
    updateSelectionState,
  };
})();
