window.CulviaViewerPanel = (() => {
  function create({
    $,
    t,
    clamp,
    escapeHtml,
    textHintAttributes,
    pathName,
    setText,
    setButtonLabel,
    cullingFlow,
    viewerKeyboard,
    viewerInspector,
    manualColorLabels,
    metricLabelKeys,
    numericValue,
    manualBadgeMarkup,
    colorLabelMeta,
    colorLabelTitle,
    manualStatusLabel,
    manualStatusClass,
    localizedManualSource,
    localizedMetricText,
    localizedScoreLevel,
    copyFileFolderPath,
    updateManualMark,
    acceptPhotoResult,
    revealPhoto,
    openPhotoPreview,
    getAppState,
    getActiveView,
  }) {
    const MARK_ADVANCE_STORAGE_KEY = "culvia.markAdvance.v1";
    let selectedIndex = 0;
    let showMissingScoreDetails = false;
    let inspectorDetailTab = "overview";
    let markAdvanceEnabled = localStorage.getItem(MARK_ADVANCE_STORAGE_KEY) === "true";

    function selectedPhoto() {
      const appState = getAppState();
      if (!appState?.photos?.length) return null;
      selectedIndex = clamp(selectedIndex, 0, appState.photos.length - 1);
      return appState.photos[selectedIndex];
    }

    function selectedIndexValue() {
      return selectedIndex;
    }

    function setSelectedIndex(index) {
      selectedIndex = Number(index) || 0;
    }

    function resetSelectedIndex() {
      selectedIndex = 0;
    }

    function ensureSelectedIndex() {
      const photos = getAppState()?.photos || [];
      if (selectedIndex >= photos.length) selectedIndex = 0;
    }

    function preserveSelectedPhoto(previousFileId, { advance = false, previousIndex = selectedIndex } = {}) {
      const photos = getAppState()?.photos || [];
      if (!previousFileId || !photos.length) {
        selectedIndex = 0;
        return;
      }
      selectedIndex = cullingFlow.nextIndexAfterMark(photos, previousIndex, previousFileId, Boolean(advance));
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

    function renderScoreRows(photo) {
      const plan = viewerInspector.scoreRowsMarkup(photo, {
        activeTab: inspectorDetailTab,
        appState: getAppState(),
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
        llmModel: getAppState()?.llm?.model || "",
      });
    }

    function filmstripWindow(photos, index, maxItems = 84) {
      if (photos.length <= maxItems) return { start: 0, end: photos.length };
      const safeIndex = clamp(index, 0, photos.length - 1);
      const radius = Math.floor(maxItems / 2);
      let start = safeIndex - radius;
      start = clamp(start, 0, Math.max(0, photos.length - maxItems));
      return { start, end: Math.min(photos.length, start + maxItems) };
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
          .map((item, offset) => {
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
          })
          .join("")}
        ${trailingCount ? `<div class="thumb-window-edge">${escapeHtml(t("viewer.afterCount", { count: trailingCount }))}</div>` : ""}
      `;
      filmstrip.querySelectorAll(".thumb").forEach((button) => {
        button.addEventListener("click", () => {
          selectedIndex = Number(button.dataset.index);
          render();
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

    function renderManualControls(photo) {
      const appState = getAppState();
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

    function render() {
      const photos = getAppState()?.photos || [];
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
      const mainScoreText = photo.recommendationText || photo.overallText;
      const mainScoreEmpty = !mainScoreText || mainScoreText === t("common.noData") || mainScoreText === t("score.noData");
      setText("#mainScore", mainScoreText);
      const mainScoreEl = $("#mainScore");
      if (mainScoreEl) {
        mainScoreEl.classList.toggle("is-empty", mainScoreEmpty);
        // applyI18n() would otherwise overwrite real values with the empty placeholder.
        if (mainScoreEmpty) mainScoreEl.setAttribute("data-i18n", "score.noData");
        else mainScoreEl.removeAttribute("data-i18n");
      }
      setText("#mainStars", photo.recommendationStars || photo.stars);
      setText("#mainLevel", `${currentLevel} · ${selectedIndex + 1} / ${photos.length}`);
      $("#mainLevel").dataset.uiTooltip = `${currentLevel} · ${selectedIndex + 1} / ${photos.length}`;
      $("#mainLevel").removeAttribute("title");
      setText("#viewerCounter", `${selectedIndex + 1} / ${photos.length}`);
      setText("#viewerLevel", currentLevel);
      $("#viewerLevel").dataset.uiTooltip = currentLevel;
      $("#viewerLevel").removeAttribute("title");
      const previewLink = $("#previewLink");
      const nativePreviewSupported = getAppState()?.capabilities?.nativeFilePreview === true;
      previewLink.href = photo.preview;
      previewLink.dataset.nativePreview = nativePreviewSupported ? "true" : "false";
      const previewTitle = nativePreviewSupported ? t("viewer.previewNativeSupported") : t("viewer.previewWebSupported");
      previewLink.setAttribute("aria-label", previewTitle);
      previewLink.dataset.uiTooltip = previewTitle;
      previewLink.removeAttribute("title");
      const revealSupported = getAppState()?.capabilities?.revealInFileManager !== false;
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
      const photos = getAppState()?.photos || [];
      if (!photos.length) return;
      const nextIndex = cullingFlow.nextIndexByDelta(photos, selectedIndex, delta);
      if (nextIndex === selectedIndex) return;
      selectedIndex = nextIndex;
      render();
    }

    function handleShortcut(event) {
      const shortcut = viewerKeyboard.shortcutActionFromEvent(event, {
        activeView: getActiveView(),
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

    function bindEvents() {
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
      $("#previewLink").addEventListener("click", (event) => {
        if (getAppState()?.capabilities?.nativeFilePreview !== true) return;
        event.preventDefault();
        void openPhotoPreview(selectedPhoto());
      });
      $("#revealBtn").addEventListener("click", () => revealPhoto(selectedPhoto()));
    }

    return {
      bindEvents,
      ensureSelectedIndex,
      handleShortcut,
      moveSelection,
      preserveSelectedPhoto,
      render,
      resetSelectedIndex,
      selectedIndex: selectedIndexValue,
      selectedPhoto,
      setSelectedIndex,
    };
  }

  return { create };
})();
