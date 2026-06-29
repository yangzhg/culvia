window.CulviaGalleryPanel = (() => {
  function create({
    $,
    $$,
    t,
    setText,
    escapeHtml,
    pathName,
    i18n,
    galleryView,
    galleryKeyboard,
    cullingFlow,
    manualStars,
    localizedManualSource,
    localizedMetricText,
    localizedScoreLevel,
    localizedTechnicalTag,
    manualStatusLabel,
    galleryColorBadgeMarkup,
    galleryQuickActionLabel,
    gallerySelectLabel,
    isSourcePreviewActive,
    matchingSourcePreview,
    updatePhotoMark,
    statusToggleChanges,
    openBatchStatusConfirm,
    switchView,
    renderViewer,
    getAppState,
    getActiveView,
    getSourceMode,
    setSelectedIndex,
  }) {
    let selectedGalleryIds = new Set();
    let gallerySelectionAnchorId = "";
    let galleryMarqueeState = null;
    let gallerySuppressNextCardClick = false;
    let galleryRatingTooltipHideTimer = null;
    let galleryRatingTooltipBridgeTarget = null;

    function visibleGallerySelection(photos = getAppState()?.photos || []) {
      const selectedIds = CulviaBatchActions.visibleSelectedIds(photos, [...selectedGalleryIds]);
      if (selectedIds.length !== selectedGalleryIds.size) {
        selectedGalleryIds = new Set(selectedIds);
      }
      if (gallerySelectionAnchorId && !selectedIds.includes(gallerySelectionAnchorId)) {
        const visibleIds = new Set((photos || []).map((photo) => photo.fileId).filter(Boolean));
        if (visibleIds.has(gallerySelectionAnchorId)) return selectedIds;
        gallerySelectionAnchorId = selectedIds[selectedIds.length - 1] || "";
      }
      return selectedIds;
    }

    function galleryBatchTarget(photos = getAppState()?.photos || []) {
      return CulviaBatchActions.targetFromSelection(photos, visibleGallerySelection(photos));
    }

    function renderBatchScopePill(rootSelector, labelSelector, target) {
      const root = $(rootSelector);
      if (!root) return;
      setText(labelSelector, CulviaBatchActions.scopeSummary(target));
      root.classList.toggle("is-selected", target.scope === "selected");
      root.classList.toggle("is-filtered", target.scope !== "selected");
      const title = CulviaBatchActions.scopeTitle(target);
      root.dataset.uiTooltip = title;
      root.setAttribute("aria-label", title);
      root.removeAttribute("title");
    }

    function renderGallerySelectionSummary(photos, selectedIds) {
      const root = $("#gallerySelectionSummary");
      if (!root) return;
      const selectedSet = new Set(selectedIds || []);
      const selectedEntries = (photos || []).map((photo, index) => ({ index, photo })).filter((entry) => selectedSet.has(entry.photo.fileId));
      if (!selectedEntries.length) {
        root.classList.add("is-hidden");
        root.innerHTML = "";
        return;
      }
      const previewLimit = 7;
      const previews = selectedEntries
        .slice(0, previewLimit)
        .map(
          (entry) => {
            const title = pathName(entry.photo.path || entry.photo.filename || t("gallery.photoFallback"));
            return `
              <button class="gallery-selection-thumb" type="button" data-gallery-summary-index="${entry.index}" aria-label="${escapeHtml(t("gallery.viewPhoto", { name: title }))}" data-ui-tooltip="${escapeHtml(title)}">
                <img src="${escapeHtml(entry.photo.thumb)}" alt="" loading="lazy" />
              </button>
            `;
          },
        )
        .join("");
      const overflow = selectedEntries.length > previewLimit ? `<span class="gallery-selection-overflow">+${selectedEntries.length - previewLimit}</span>` : "";
      root.classList.remove("is-hidden");
      root.innerHTML = `
        <div class="gallery-selection-summary-copy">
          <span>${escapeHtml(t("gallery.selectedPhotos"))}</span>
          <strong>${escapeHtml(t("common.photoCount", { count: selectedEntries.length }))}</strong>
        </div>
        <div class="gallery-selection-strip">${previews}${overflow}</div>
      `;
      root.querySelectorAll("[data-gallery-summary-index]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const index = Number(button.dataset.gallerySummaryIndex);
          if (!Number.isInteger(index) || index < 0 || index >= (getAppState()?.photos || []).length) return;
          setSelectedIndex(index);
          switchView("viewer");
          renderViewer();
        });
      });
    }

    function renderGalleryBulkToolbar(photos) {
      const target = galleryBatchTarget(photos);
      const selectedIds = visibleGallerySelection(photos);
      const selectedCount = selectedIds.length;
      const allVisibleSelected = Boolean(photos.length) && selectedCount >= photos.length;
      const disabled = !target.count || Boolean(getAppState()?.job?.running);
      setText("#galleryBulkCount", t("common.photoCount", { count: photos.length }));
      setText("#gallerySelectedCount", t("common.photoCount", { count: selectedCount }));
      renderBatchScopePill("#galleryBatchScopeText", "#galleryBatchScopeLabel", target);
      renderGallerySourceStatus();
      renderGalleryThumbnailProgress();
      renderGallerySelectionSummary(photos, selectedIds);
      const selectVisibleButton = $("#gallerySelectVisibleBtn");
      if (selectVisibleButton) selectVisibleButton.disabled = !photos.length || allVisibleSelected || Boolean(getAppState()?.job?.running);
      const clearButton = $("#galleryClearSelectionBtn");
      if (clearButton) clearButton.disabled = !selectedGalleryIds.size || Boolean(getAppState()?.job?.running);
      ["#galleryBatchPickBtn", "#galleryBatchHoldBtn", "#galleryBatchRejectBtn"].forEach((selector) => {
        const button = $(selector);
        if (button) button.disabled = disabled;
      });
    }

    function renderGallerySourceStatus() {
      const root = $("#gallerySourceStatus");
      if (!root) return;
      if (getSourceMode() !== "folders") {
        root.className = "gallery-source-status is-hidden";
        root.textContent = "";
        return;
      }
      if (isSourcePreviewActive()) {
        root.className = "gallery-source-status is-scanning";
        root.textContent = t("gallery.sourceScanning");
        return;
      }
      const preview = matchingSourcePreview();
      if (!preview) {
        root.className = "gallery-source-status is-hidden";
        root.textContent = "";
        return;
      }
      const total = Number(preview.total || 0);
      root.className = `gallery-source-status ${total > 0 ? "is-ready" : "is-empty"}`;
      root.textContent = total > 0 ? t("gallery.sourceCount", { count: total }) : t("gallery.sourceEmpty");
    }

    function galleryThumbnailStats() {
      const images = $$("#galleryGrid [data-gallery-thumb]");
      let loaded = 0;
      let failed = 0;
      images.forEach((image) => {
        const card = image.closest(".photo-card");
        if (card?.classList.contains("is-thumb-error")) {
          failed += 1;
          return;
        }
        if (card?.classList.contains("is-thumb-loaded") || (image.complete && image.naturalWidth > 0)) {
          loaded += 1;
        }
      });
      return {
        failed,
        loaded,
        pending: Math.max(images.length - loaded - failed, 0),
        total: images.length,
      };
    }

    function renderGalleryThumbnailProgress() {
      const root = $("#galleryThumbProgress");
      if (!root) return;
      const stats = galleryThumbnailStats();
      if (!stats.total || (!stats.pending && !stats.failed)) {
        root.classList.add("is-hidden");
        return;
      }
      const done = Math.min(stats.total, stats.loaded + stats.failed);
      const percent = stats.total ? Math.max(3, Math.min(100, (done / stats.total) * 100)) : 0;
      root.classList.remove("is-hidden");
      setText("#galleryThumbProgressLabel", stats.failed ? t("gallery.thumbProgressFailed", { count: stats.failed }) : t("gallery.thumbProgressLabel"));
      setText("#galleryThumbProgressCount", t("gallery.thumbProgressCount", { done, total: stats.total }));
      const bar = $("#galleryThumbProgressBar");
      if (bar) bar.style.width = `${percent}%`;
    }

    function syncGalleryThumbnailStates() {
      $$("#galleryGrid [data-gallery-thumb]").forEach((image) => {
        if (!image.complete) return;
        updateGalleryThumbState(image, !(image.naturalWidth > 0));
      });
      renderGalleryThumbnailProgress();
    }

    function scheduleGalleryThumbnailSync() {
      window.requestAnimationFrame(syncGalleryThumbnailStates);
    }

    function selectGalleryRange(fileId) {
      const rangeIds = cullingFlow.rangeFileIds(getAppState()?.photos || [], gallerySelectionAnchorId, fileId);
      if (!rangeIds.length) return false;
      rangeIds.forEach((rangeFileId) => selectedGalleryIds.add(rangeFileId));
      gallerySelectionAnchorId = fileId;
      renderGallerySelectionState();
      return true;
    }

    function toggleGallerySelection(fileId, options = {}) {
      if (!fileId) return;
      if (options.range && gallerySelectionAnchorId && selectGalleryRange(fileId)) return;
      if (selectedGalleryIds.has(fileId)) {
        selectedGalleryIds.delete(fileId);
      } else {
        selectedGalleryIds.add(fileId);
      }
      gallerySelectionAnchorId = fileId;
      renderGallerySelectionState();
    }

    function clearGallerySelection() {
      if (!selectedGalleryIds.size) return;
      selectedGalleryIds.clear();
      gallerySelectionAnchorId = "";
      renderGallerySelectionState();
    }

    function selectVisibleGalleryPhotos() {
      const photos = getAppState()?.photos || [];
      if (!photos.length) return;
      photos.forEach((photo) => {
        if (photo.fileId) selectedGalleryIds.add(photo.fileId);
      });
      gallerySelectionAnchorId = photos[photos.length - 1]?.fileId || gallerySelectionAnchorId;
      renderGallerySelectionState();
    }

    function galleryMarqueeRect(state) {
      const left = Math.min(state.startX, state.currentX);
      const top = Math.min(state.startY, state.currentY);
      const right = Math.max(state.startX, state.currentX);
      const bottom = Math.max(state.startY, state.currentY);
      return {
        bottom,
        height: bottom - top,
        left,
        right,
        top,
        width: right - left,
      };
    }

    function rectsIntersect(a, b) {
      return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    }

    function cacheGalleryMarqueeTargets() {
      if (!galleryMarqueeState) return;
      const cardByFileId = new Map();
      const cardRects = $$("#galleryGrid .photo-card")
        .map((card) => {
          const index = Number(card.dataset.index);
          const fileId = getAppState()?.photos?.[index]?.fileId || "";
          if (!fileId) return null;
          const rect = card.getBoundingClientRect();
          cardByFileId.set(fileId, card);
          return { fileId, rect };
        })
        .filter(Boolean);
      galleryMarqueeState.cardByFileId = cardByFileId;
      galleryMarqueeState.cardRects = cardRects;
    }

    function galleryMarqueeTargetIds(rect) {
      const cachedRects = galleryMarqueeState?.cardRects;
      if (cachedRects?.length) {
        return cachedRects
          .filter((entry) => rectsIntersect(rect, entry.rect))
          .map((entry) => entry.fileId);
      }
      return $$("#galleryGrid .photo-card")
        .filter((card) => {
          const cardRect = card.getBoundingClientRect();
          return rectsIntersect(rect, cardRect);
        })
        .map((card) => {
          const index = Number(card.dataset.index);
          return getAppState()?.photos?.[index]?.fileId || "";
        })
        .filter(Boolean);
    }

    function clearGalleryMarqueePreview() {
      const previewIds = galleryMarqueeState?.previewIds;
      const cardByFileId = galleryMarqueeState?.cardByFileId;
      if (previewIds?.size && cardByFileId?.size) {
        previewIds.forEach((fileId) => cardByFileId.get(fileId)?.classList.remove("is-marquee-target"));
        galleryMarqueeState.previewIds = new Set();
        return;
      }
      $$("#galleryGrid .photo-card.is-marquee-target").forEach((card) => card.classList.remove("is-marquee-target"));
    }

    function applyGalleryMarqueePreview(targetIds) {
      const targetSet = new Set(targetIds);
      const previousSet = galleryMarqueeState?.previewIds || new Set();
      const cardByFileId = galleryMarqueeState?.cardByFileId;
      if (cardByFileId?.size) {
        previousSet.forEach((fileId) => {
          if (!targetSet.has(fileId)) cardByFileId.get(fileId)?.classList.remove("is-marquee-target");
        });
        targetSet.forEach((fileId) => {
          if (!previousSet.has(fileId)) cardByFileId.get(fileId)?.classList.add("is-marquee-target");
        });
        galleryMarqueeState.previewIds = targetSet;
        return;
      }
      $$("#galleryGrid .photo-card").forEach((card) => {
        const index = Number(card.dataset.index);
        const fileId = getAppState()?.photos?.[index]?.fileId || "";
        card.classList.toggle("is-marquee-target", targetSet.has(fileId));
      });
    }

    function updateGalleryMarqueeBox(rect) {
      const marquee = $("#gallerySelectionMarquee");
      if (!marquee) return;
      marquee.classList.toggle("is-hidden", rect.width < 1 || rect.height < 1);
      marquee.style.left = `${rect.left}px`;
      marquee.style.top = `${rect.top}px`;
      marquee.style.width = `${rect.width}px`;
      marquee.style.height = `${rect.height}px`;
    }

    function resetGalleryMarquee() {
      if (galleryMarqueeState?.raf) window.cancelAnimationFrame(galleryMarqueeState.raf);
      document.body.classList.remove("is-gallery-marquee-selecting");
      clearGalleryMarqueePreview();
      galleryMarqueeState = null;
      const marquee = $("#gallerySelectionMarquee");
      if (marquee) {
        marquee.classList.add("is-hidden");
        marquee.removeAttribute("style");
      }
    }

    function isGalleryMarqueeStartArea(event) {
      if (getActiveView() !== "gallery") return false;
      const workspace = event.currentTarget?.closest?.(".workspace") || $(".workspace");
      const grid = $("#galleryGrid");
      const workspaceRect = workspace?.getBoundingClientRect();
      const gridRect = grid?.getBoundingClientRect();
      if (!workspaceRect || !gridRect || gridRect.width < 1 || gridRect.height < 1) return false;
      const top = gridRect.top - 36;
      return event.clientX >= workspaceRect.left
        && event.clientX <= workspaceRect.right
        && event.clientY >= top
        && event.clientY <= gridRect.bottom;
    }

    function beginGalleryMarquee(event) {
      if (event.button !== 0 || event.pointerType === "touch" || !getAppState()?.photos?.length || getAppState()?.job?.running) return;
      if (event.target?.closest?.("button, a, input, textarea, select, summary")) return;
      if (event.target?.closest?.(".topbar, .command-center, .stats-grid, .view-tabs, .filter-scope-bar, .gallery-bulk-toolbar, .gallery-selection-summary")) return;
      if (!isGalleryMarqueeStartArea(event)) return;
      galleryMarqueeState = {
        additive: Boolean(event.shiftKey || event.metaKey || event.ctrlKey),
        baseSelectedIds: new Set(selectedGalleryIds),
        cardByFileId: new Map(),
        cardRects: [],
        currentIds: [],
        currentX: event.clientX,
        currentY: event.clientY,
        dragging: false,
        pointerId: event.pointerId,
        previewIds: new Set(),
        raf: 0,
        startX: event.clientX,
        startY: event.clientY,
      };
      window.addEventListener("pointermove", updateGalleryMarquee, { passive: false });
      window.addEventListener("pointerup", finishGalleryMarquee, { once: true });
      window.addEventListener("pointercancel", cancelGalleryMarquee, { once: true });
    }

    function flushGalleryMarqueeUpdate() {
      if (!galleryMarqueeState) return;
      galleryMarqueeState.raf = 0;
      const rect = galleryMarqueeRect(galleryMarqueeState);
      galleryMarqueeState.currentIds = galleryMarqueeTargetIds(rect);
      updateGalleryMarqueeBox(rect);
      applyGalleryMarqueePreview(galleryMarqueeState.currentIds);
    }

    function updateGalleryMarquee(event) {
      if (!galleryMarqueeState || event.pointerId !== galleryMarqueeState.pointerId) return;
      galleryMarqueeState.currentX = event.clientX;
      galleryMarqueeState.currentY = event.clientY;
      const distance = Math.hypot(galleryMarqueeState.currentX - galleryMarqueeState.startX, galleryMarqueeState.currentY - galleryMarqueeState.startY);
      if (!galleryMarqueeState.dragging && distance < 6) return;
      if (!galleryMarqueeState.dragging) {
        galleryMarqueeState.dragging = true;
        document.body.classList.add("is-gallery-marquee-selecting");
        cacheGalleryMarqueeTargets();
      }
      event.preventDefault();
      if (!galleryMarqueeState.raf) {
        galleryMarqueeState.raf = window.requestAnimationFrame(flushGalleryMarqueeUpdate);
      }
    }

    function finishGalleryMarquee(event) {
      window.removeEventListener("pointermove", updateGalleryMarquee);
      window.removeEventListener("pointercancel", cancelGalleryMarquee);
      if (!galleryMarqueeState || event.pointerId !== galleryMarqueeState.pointerId) {
        resetGalleryMarquee();
        return;
      }
      if (!galleryMarqueeState.dragging) {
        resetGalleryMarquee();
        return;
      }
      event.preventDefault();
      if (galleryMarqueeState.raf) {
        window.cancelAnimationFrame(galleryMarqueeState.raf);
        flushGalleryMarqueeUpdate();
      }
      const nextSelected = galleryMarqueeState.additive ? new Set(galleryMarqueeState.baseSelectedIds) : new Set();
      galleryMarqueeState.currentIds.forEach((fileId) => nextSelected.add(fileId));
      selectedGalleryIds = nextSelected;
      gallerySelectionAnchorId = galleryMarqueeState.currentIds[galleryMarqueeState.currentIds.length - 1] || gallerySelectionAnchorId;
      gallerySuppressNextCardClick = true;
      window.setTimeout(() => {
        gallerySuppressNextCardClick = false;
      }, 160);
      resetGalleryMarquee();
      renderGallerySelectionState();
    }

    function cancelGalleryMarquee() {
      window.removeEventListener("pointermove", updateGalleryMarquee);
      window.removeEventListener("pointerup", finishGalleryMarquee);
      resetGalleryMarquee();
    }

    function galleryCardSignature(photo) {
      return galleryView.cardSignature(photo, i18n?.language?.() || "");
    }

    function galleryTooltipMarkup(photo) {
      return galleryView.tooltipMarkup(photo, {
        localizedManualSource,
        localizedMetricText,
        localizedScoreLevel,
        localizedTechnicalTag,
        manualStars,
        manualStatusLabel,
        t,
      });
    }

    function galleryCardMarkup(photo, index, selected, signature) {
      return galleryView.cardMarkup(photo, index, selected, signature, {
        disabled: Boolean(getAppState()?.job?.running),
        galleryColorBadgeMarkup,
        galleryQuickActionLabel,
        gallerySelectLabel,
        localizedScoreLevel,
        t,
      });
    }

    function createGalleryCard(markup) {
      const template = document.createElement("template");
      template.innerHTML = markup.trim();
      return template.content.firstElementChild;
    }

    function updateGalleryCardSelectionState(card, photo, index, selected) {
      galleryView.updateSelectionState(card, photo, index, selected, {
        disabled: Boolean(getAppState()?.job?.running),
        gallerySelectLabel,
      });
    }

    function renderGallerySelectionState(photos = getAppState()?.photos || []) {
      const grid = $("#galleryGrid");
      renderGalleryBulkToolbar(photos);
      if (!grid) return;
      const photosById = new Map((photos || []).map((photo, index) => [photo.fileId, { index, photo }]));
      grid.querySelectorAll(".photo-card[data-file-id]").forEach((card) => {
        const entry = photosById.get(card.dataset.fileId || "");
        if (!entry) return;
        updateGalleryCardSelectionState(card, entry.photo, entry.index, selectedGalleryIds.has(entry.photo.fileId));
      });
    }

    function renderGallery() {
      const photos = getAppState()?.photos || [];
      const grid = $("#galleryGrid");
      renderGalleryBulkToolbar(photos);
      if (isSourcePreviewActive()) {
        grid.replaceChildren(createGalleryCard(galleryView.loadingStateMarkup({
          state: t("source.previewScanningState"),
          text: t("source.previewScanningDetail"),
          title: t("source.previewScanningTitle"),
        })));
        renderGalleryThumbnailProgress();
        return;
      }
      if (!photos.length) {
        grid.replaceChildren(createGalleryCard(galleryView.emptyStateMarkup({
          text: t("gallery.emptyText"),
          title: t("gallery.emptyTitle"),
        })));
        renderGalleryThumbnailProgress();
        return;
      }
      const orderedCards = Array.from(grid.querySelectorAll(".photo-card[data-file-id]"));
      const orderMatches = orderedCards.length === photos.length && orderedCards.every((card, index) => card.dataset.fileId === photos[index]?.fileId);
      if (orderMatches) {
        photos.forEach((photo, index) => {
          const selected = selectedGalleryIds.has(photo.fileId);
          const signature = galleryCardSignature(photo);
          const card = orderedCards[index];
          if (card.dataset.gallerySignature !== signature) {
            card.replaceWith(createGalleryCard(galleryCardMarkup(photo, index, selected, signature)));
            return;
          }
          updateGalleryCardSelectionState(card, photo, index, selected);
        });
        scheduleGalleryThumbnailSync();
        return;
      }
      const existingCards = new Map(
        Array.from(grid.querySelectorAll(".photo-card[data-file-id]")).map((card) => [card.dataset.fileId, card]),
      );
      const fragment = document.createDocumentFragment();
      photos.forEach((photo, index) => {
        const selected = selectedGalleryIds.has(photo.fileId);
        const signature = galleryCardSignature(photo);
        let card = existingCards.get(photo.fileId);
        if (!card || card.dataset.gallerySignature !== signature) {
          card = createGalleryCard(galleryCardMarkup(photo, index, selected, signature));
        } else {
          updateGalleryCardSelectionState(card, photo, index, selected);
        }
        fragment.appendChild(card);
      });
      grid.replaceChildren(fragment);
      scheduleGalleryThumbnailSync();
    }

    function updateGalleryThumbState(image, failed) {
      const card = image?.closest?.(".photo-card");
      if (!card) return;
      card.classList.toggle("is-thumb-error", failed);
      card.classList.toggle("is-thumb-loaded", !failed);
    }

    function handleGalleryImageLoad(event) {
      const image = event.target?.closest?.("[data-gallery-thumb]");
      if (!image) return;
      delete image.dataset.galleryRetry;
      updateGalleryThumbState(image, false);
      renderGalleryThumbnailProgress();
    }

    function handleGalleryImageError(event) {
      const image = event.target?.closest?.("[data-gallery-thumb]");
      if (!image) return;
      if (!image.dataset.galleryRetry) {
        image.dataset.galleryRetry = "1";
        window.setTimeout(() => {
          if (!image.isConnected) return;
          const retryUrl = new URL(image.currentSrc || image.src, window.location.href);
          retryUrl.searchParams.set("retry", String(Date.now()));
          image.src = retryUrl.pathname + retryUrl.search;
        }, 700);
        return;
      }
      updateGalleryThumbState(image, true);
      renderGalleryThumbnailProgress();
    }

    function handleGalleryGridClick(event) {
      const statusButton = event.target?.closest?.("[data-gallery-status]");
      if (statusButton) {
        if (getAppState()?.job?.running) return;
        event.stopPropagation();
        const fileId = statusButton.dataset.fileId || "";
        const photo = (getAppState()?.photos || []).find((item) => item?.fileId === fileId);
        updatePhotoMark(
          fileId,
          statusToggleChanges(
            { status: statusButton.dataset.galleryStatus || "", source: "manual", acceptedScore: null },
            photo?.manual?.status || "",
          ),
        );
        return;
      }
      const selectButton = event.target?.closest?.("[data-gallery-select]");
      if (selectButton) {
        if (getAppState()?.job?.running) return;
        event.stopPropagation();
        toggleGallerySelection(selectButton.dataset.gallerySelect || "", { range: event.shiftKey });
        return;
      }
      const card = event.target?.closest?.("#galleryGrid .photo-card");
      if (!card) return;
      if (gallerySuppressNextCardClick) {
        gallerySuppressNextCardClick = false;
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      setSelectedIndex(Number(card.dataset.index));
      switchView("viewer");
      renderViewer();
    }

    function visibleElement(selector) {
      return Array.from(document.querySelectorAll(selector)).find((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }) || null;
    }

    function rectanglesIntersect(first, second) {
      return !!(first && second && !(
        first.right <= second.left ||
        first.left >= second.right ||
        first.bottom <= second.top ||
        first.top >= second.bottom
      ));
    }

    function ensureGalleryRatingTooltip(rating) {
      const card = rating?.closest?.("#galleryGrid .photo-card");
      if (!card) return null;
      card.classList.add("is-tooltip-open");
      let tooltip = rating.querySelector(".rating-tooltip");
      if (tooltip) return tooltip;
      const index = Number(card.dataset.index);
      const photo = getAppState()?.photos?.[index];
      if (!photo) return null;
      const tooltipNode = createGalleryCard(galleryTooltipMarkup(photo));
      rating.appendChild(tooltipNode);
      return tooltipNode;
    }

    function hideGalleryRatingTooltip(rating) {
      if (!rating) return;
      rating.classList.remove("is-tooltip-bridging");
      rating.closest(".photo-card")?.classList.remove("is-tooltip-open");
      rating.querySelector(".rating-tooltip")?.remove();
      if (galleryRatingTooltipBridgeTarget === rating) {
        galleryRatingTooltipBridgeTarget = null;
      }
    }

    function placeGalleryRatingTooltip(rating) {
      const tooltip = ensureGalleryRatingTooltip(rating);
      if (!tooltip) return;
      tooltip.classList.remove("is-placement-below");
      const toolbar = visibleElement(".gallery-bulk-toolbar");
      if (!toolbar) return;
      const tooltipRect = tooltip.getBoundingClientRect();
      const toolbarRect = toolbar.getBoundingClientRect();
      const hitsToolbar = rectanglesIntersect(tooltipRect, toolbarRect);
      if (hitsToolbar || tooltipRect.top < toolbarRect.bottom + 8) {
        tooltip.classList.add("is-placement-below");
      }
    }

    function handleGalleryTooltipIntent(event) {
      const rating = event.target?.closest?.("#galleryGrid .gallery-rating");
      if (!rating) return;
      if (galleryRatingTooltipHideTimer) {
        window.clearTimeout(galleryRatingTooltipHideTimer);
        galleryRatingTooltipHideTimer = null;
      }
      if (galleryRatingTooltipBridgeTarget && galleryRatingTooltipBridgeTarget !== rating) {
        hideGalleryRatingTooltip(galleryRatingTooltipBridgeTarget);
      }
      rating.classList.remove("is-tooltip-bridging");
      galleryRatingTooltipBridgeTarget = null;
      placeGalleryRatingTooltip(rating);
    }

    function clearGalleryTooltipPlacement(event) {
      const rating = event.target?.closest?.("#galleryGrid .gallery-rating");
      if (!rating) return;
      const nextTarget = event.relatedTarget;
      if (nextTarget && rating.contains(nextTarget)) return;
      if (galleryRatingTooltipHideTimer) {
        window.clearTimeout(galleryRatingTooltipHideTimer);
      }
      if (event.type !== "pointerout") {
        hideGalleryRatingTooltip(rating);
        return;
      }
      rating.classList.add("is-tooltip-bridging");
      galleryRatingTooltipBridgeTarget = rating;
      galleryRatingTooltipHideTimer = window.setTimeout(() => {
        hideGalleryRatingTooltip(rating);
        galleryRatingTooltipHideTimer = null;
      }, 320);
    }

    function handleGalleryShortcut(event) {
      const selectedCount = visibleGallerySelection(getAppState()?.photos || []).length;
      const shortcut = galleryKeyboard.shortcutActionFromEvent(event, { activeView: getActiveView(), selectedCount });
      if (shortcut.action === galleryKeyboard.actions.none) return false;
      if (shortcut.action === galleryKeyboard.actions.selectVisible) {
        event.preventDefault();
        selectVisibleGalleryPhotos();
        return true;
      }
      if (shortcut.action === galleryKeyboard.actions.clearSelection) {
        event.preventDefault();
        clearGallerySelection();
        return true;
      }
      if (shortcut.action === galleryKeyboard.actions.batchStatus) {
        event.preventDefault();
        void openBatchStatusConfirm(shortcut.status);
        return true;
      }
      return false;
    }

    return {
      visibleGallerySelection,
      galleryBatchTarget,
      renderBatchScopePill,
      clearGallerySelection,
      selectVisibleGalleryPhotos,
      beginGalleryMarquee,
      renderGallerySelectionState,
      renderGallery,
      handleGalleryImageLoad,
      handleGalleryImageError,
      handleGalleryGridClick,
      handleGalleryTooltipIntent,
      clearGalleryTooltipPlacement,
      handleGalleryShortcut,
      selectedGalleryIds: () => selectedGalleryIds,
      setGallerySelectionAnchorId: (value) => {
        gallerySelectionAnchorId = value;
      },
    };
  }

  return { create };
})();
