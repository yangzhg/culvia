window.CulviaExportPanel = (() => {
  function create({
    $,
    t,
    clamp,
    escapeHtml,
    iconMarkup,
    parentPath,
    pathName,
    setText,
    setTextWithHint,
    setButtonLabel,
    localizedMetricText,
    localizedScoreLevel,
    manualBadgeMarkup,
    colorLabelMeta,
    manualColorLabels,
    numericValue,
    clipboard,
    postJson,
    errorMessage,
    showCommandNotice,
    flushFilterUpdate,
    downloadFile,
    revealPhoto,
    applyBatchColor,
    galleryBatchTarget,
    renderBatchScopePill,
    getAppState,
    getActiveView,
    onActivityChange,
    refreshState,
  }) {
    let exportDestination = "";
    let exportStatusText = "";
    let exportResult = null;
    let exporting = false;
    let destinationChosen = false;
    let pendingPreviousOperationId = "";
    let receiptReadError = null;
    let receiptTransportError = null;
    let requestFailure = null;
    let failedPreviousOperationId = "";
    let renderedResultMarkup = null;
    let renderedOperationId = "";
    const clearedOperationIds = new Set();
    let exportPreflight = null;
    let exportPreflightLoading = false;
    let exportPreflightError = "";
    let exportPreflightKey = "";

    function receiptToken() {
      return exportResult?.operationId
        ? `${exportResult.operationId}:${exportResult.sequence}:${exportResult.revision}`
        : "";
    }

    function isExporting() {
      return exporting || exportResult?.status === "running";
    }

    function acceptReceipt(receipt) {
      if (!receipt?.operationId || clearedOperationIds.has(receipt.operationId)) return;
      if (!CulviaExportResultData.shouldReplaceReceipt(exportResult, receipt)) return;
      const wasRunning = exportResult?.status === "running";
      exportResult = receipt;
      if (!destinationChosen) exportDestination = String(receipt.destination || "");
      if (wasRunning && receipt.status !== "running") {
        applyExportPreflightState(CulviaExportPreflightState.emptyState());
      }
      if (receipt.operationId !== failedPreviousOperationId) {
        requestFailure = null;
        exportStatusText = "";
      }
    }

    function clearReceipt() {
      if (exportResult?.operationId) clearedOperationIds.add(exportResult.operationId);
      exportResult = null;
      exportStatusText = "";
      receiptReadError = null;
      receiptTransportError = null;
      requestFailure = null;
      if (!destinationChosen) exportDestination = "";
      applyExportPreflightState(CulviaExportPreflightState.emptyState());
    }

    function syncReceiptFromState(options = {}) {
      const app = getAppState();
      if (options.stateLoaded) receiptTransportError = null;
      if (app?.exportReceiptError) {
        receiptReadError = app.exportReceiptError;
        return;
      }
      if (!app || !Object.prototype.hasOwnProperty.call(app, "exportReceipt")) return;
      receiptReadError = null;
      if (app.exportReceipt === null) {
        // A state request started before the current result must not erase it.
        if (!exporting && options.expectedReceiptToken === receiptToken()) clearReceipt();
        return;
      }
      acceptReceipt(app.exportReceipt);
      if (options.stateLoaded && app.exportReceipt?.operationId !== failedPreviousOperationId) {
        requestFailure = null;
        exportStatusText = "";
      }
    }

    function receiptErrorText() {
      const error = receiptReadError || receiptTransportError || requestFailure;
      if (!error) return "";
      if (error.errorCode) return errorMessage(new Error(JSON.stringify(error)));
      return t("export.resultRequestUnconfirmed", { reason: errorMessage(error) });
    }

    function visibleExportResult() {
      return exporting && exportResult?.operationId === pendingPreviousOperationId ? null : exportResult;
    }

    function stateReadFailed(error) {
      receiptTransportError = error;
      if (getActiveView() === "export") renderExportList();
    }

    async function refreshExportReceipt() {
      if (!refreshState) return;
      try {
        await refreshState();
        syncReceiptFromState({ stateLoaded: true });
      } catch (error) {
        receiptTransportError = error;
      }
      renderExportList();
      onActivityChange?.();
    }

    function setMeterWidth(selector, value, total) {
      const node = $(selector);
      if (!node) return;
      const percent = total > 0 ? clamp(value / total, 0, 1) * 100 : 0;
      node.style.width = `${percent}%`;
    }

    function renderDeliveryOverview(all = {}, filtered = {}) {
      const allTotal = Number(getAppState()?.summary?.scored || 0);
      const filteredTotal = Number(getAppState()?.summary?.matched || (getAppState()?.photos || []).length || 0);
      const selected = Number(all.selected || 0);
      const rejected = Number(all.rejected || 0);
      const pending = Math.max(allTotal - selected - rejected, 0);
      const filteredPending = Math.max(
        filteredTotal - Number(filtered.selected || 0) - Number(filtered.rejected || 0),
        0,
      );
      const decided = selected + rejected;
      setText("#deliveryReadyCount", t("common.photoCount", { count: selected }));
      setText("#deliveryPickCount", selected);
      setText("#deliveryPendingCount", pending);
      setText("#deliveryRejectCount", rejected);
      setText("#deliveryVisiblePendingCount", filteredPending);
      const guidance = !allTotal
        ? t("export.guidanceEmpty")
        : selected
          ? t("export.guidanceReady", { pending, selected })
          : t("export.guidancePending", { pending });
      setText("#deliveryGuidance", guidance);
      setMeterWidth("#deliveryMeterPick", selected, allTotal);
      setMeterWidth("#deliveryMeterPending", pending, allTotal);
      setMeterWidth("#deliveryMeterReject", rejected, allTotal);
      $(".delivery-overview")?.classList.toggle("is-empty", !allTotal);
      $(".delivery-overview")?.classList.toggle("is-ready", selected > 0);
      $(".delivery-overview")?.classList.toggle("is-decided", allTotal > 0 && decided >= allTotal);
    }

    function exportPreflightMarkup() {
      return CulviaExportPreflight.renderMarkup(
        {
          destination: exportDestination,
          error: exportPreflightError,
          loading: exportPreflightLoading,
          preflight: exportPreflight,
        },
        {
          escapeHtml,
          iconMarkup,
          parentPath,
          pathName,
        },
      );
    }

    function currentExportPreflightKey() {
      const app = getAppState();
      const selectionKey = app?.curation?.exportSelectionKey;
      if (typeof selectionKey === "string") return `${exportDestination}::selection:${selectionKey}`;
      return CulviaExportPreflight.currentKey(exportDestination, app?.selectedPhotos || []);
    }

    function applyExportPreflightState(next) {
      if (!next) return;
      if (Object.prototype.hasOwnProperty.call(next, "preflight")) exportPreflight = next.preflight;
      if (Object.prototype.hasOwnProperty.call(next, "loading")) exportPreflightLoading = next.loading;
      if (Object.prototype.hasOwnProperty.call(next, "error")) exportPreflightError = next.error;
      if (Object.prototype.hasOwnProperty.call(next, "key")) exportPreflightKey = next.key;
    }

    function exportResultMarkup() {
      return CulviaExportResult.renderMarkup(visibleExportResult(), {
        canRevealDestination: getAppState()?.capabilities?.revealInFileManager !== false,
        escapeHtml,
        iconMarkup,
        parentPath,
        pathName,
      }, { error: receiptErrorText() });
    }

    function renderExportResult() {
      const node = $("#exportResult");
      if (!node) return;
      const markup = exportResultMarkup();
      if (markup === renderedResultMarkup) return;
      const operationId = visibleExportResult()?.operationId || "";
      const sameOperation = operationId === renderedOperationId;
      const expanded = sameOperation && Boolean(node.querySelector?.("details")?.open);
      const focused = sameOperation ? node.querySelector?.(":focus") : null;
      const focusSelector = [
        "[data-export-download-receipt]", "[data-export-copy-destination]",
        "[data-export-reveal-destination]", "[data-export-refresh-receipt]", "summary",
      ].find((selector) => focused?.matches?.(selector));
      node.innerHTML = markup;
      if (expanded && node.querySelector?.("details")) node.querySelector("details").open = true;
      if (focusSelector) node.querySelector?.(focusSelector)?.focus?.({ preventScroll: true });
      renderedResultMarkup = markup;
      renderedOperationId = operationId;
    }

    function bindBatchColorChoices(container) {
      container.querySelectorAll("[data-batch-color]").forEach((button) => {
        button.addEventListener("click", () => {
          if (isExporting() || getAppState()?.job?.running) return;
          const colorLabel = button.dataset.batchColor || "";
          applyBatchColor(
            colorLabel,
            galleryBatchTarget(getAppState()?.photos || []),
            () => Array.from(container.querySelectorAll("[data-batch-color]"))
              .find((candidate) => (candidate.dataset.batchColor || "") === colorLabel),
          );
        });
      });
    }

    function renderExportBatchColorChoices(batchActions) {
      const container = $("#batchColorLabels");
      if (!container) return;
      const localizedColorLabels = manualColorLabels.map((item) => colorLabelMeta(item.value));
      container.innerHTML = CulviaBatchActions.colorChoiceViews(localizedColorLabels, {
        disabled: isExporting() || Boolean(getAppState()?.job?.running) || !batchActions.hasPhotos,
      })
        .map(
          (item) => `
            <button
              class="${escapeHtml(item.className)}"
              type="button"
              data-batch-color="${escapeHtml(item.value)}"
              aria-label="${escapeHtml(item.title)}"
              data-ui-tooltip="${escapeHtml(item.title)}"
              ${item.disabled ? "disabled" : ""}
            >${escapeHtml(item.text)}</button>
          `,
        )
        .join("");
      bindBatchColorChoices(container);
    }

    function bindExportListRevealActions(list, photos) {
      list.querySelectorAll(".reveal-list").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.getAttribute("aria-disabled") === "true") return;
          revealPhoto(CulviaExportList.photoForReveal(photos, button.dataset.exportListIndex));
        });
      });
    }

    function renderExportSelectedList(list, photos) {
      list.innerHTML = CulviaExportList.renderMarkup(photos, {
        canRevealFile: getAppState()?.capabilities?.revealInFileManager !== false,
        escapeHtml,
        iconMarkup,
        localizedMetricText,
        localizedScoreLevel,
        manualBadgeMarkup,
        pathName,
      });
      bindExportListRevealActions(list, photos);
    }

    function isExportDestinationBlocked() {
      return CulviaExportPreflightState.exportBlocked({
        error: exportPreflightError,
        loading: exportPreflightLoading,
        preflight: exportPreflight,
      });
    }

    function updateExportActionControls(all, batchActions) {
      const busy = isExporting() || Boolean(getAppState()?.job?.running);
      const result = visibleExportResult();
      const resultStatus = !result?.operationId && result?.destination === exportDestination
        ? CulviaExportActions.exportStatusText(result)
        : "";
      const exportAction = CulviaExportActions.primaryActionView({
        blocked: isExportDestinationBlocked(),
        destination: exportDestination,
        exporting: isExporting(),
        preflight: exportPreflight,
        preflightError: exportPreflightError,
        preflightLoading: exportPreflightLoading,
        selectedCount: all.selected,
        statusText: exportStatusText || resultStatus,
      });
      setButtonLabel($("#exportSelectedBtn"), exportAction.icon, exportAction.label);
      $("#exportSelectedBtn").disabled = busy || exportAction.disabled;
      setText("#exportSelectedHint", exportAction.hint);
      setButtonLabel($("#acceptFilteredModelBtn"), batchActions.model.icon, batchActions.model.label);
      setButtonLabel($("#acceptFilteredLlmBtn"), batchActions.llm.icon, batchActions.llm.label);
      $("#acceptFilteredModelBtn").disabled = busy || batchActions.model.disabled;
      $("#acceptFilteredLlmBtn").disabled = busy || batchActions.llm.disabled;
      const destinationButton = $("#pickExportFolderBtn");
      if (destinationButton) destinationButton.disabled = busy;
    }

    function renderExportList() {
      syncReceiptFromState();
      const photos = getAppState()?.selectedPhotos || [];
      const visiblePhotos = getAppState()?.photos || [];
      const batchTarget = galleryBatchTarget(visiblePhotos);
      const list = $("#exportList");
      const all = getAppState()?.curation?.all || {};
      const filtered = getAppState()?.curation?.filtered || getAppState()?.curation?.visible || {};
      const preflightKey = currentExportPreflightKey();
      if (
        !isExporting()
        && !getAppState()?.job?.running
        && CulviaExportPreflightState.shouldRefresh({
          activeView: getActiveView(),
          currentKey: preflightKey,
          destination: exportDestination,
          loading: exportPreflightLoading,
          storedKey: exportPreflightKey,
        })
      ) {
        void refreshExportPreflight({ key: preflightKey });
      }
      renderDeliveryOverview(all, filtered);
      setText(
        "#curationSummaryText",
        t("export.curationSummary", {
          rated: all.rated || 0,
          selected: all.selected || 0,
          filteredSelected: filtered.selected || 0,
        }),
      );
      const destinationText = exportDestination ? `${pathName(exportDestination)} · ${parentPath(exportDestination)}` : t("export.destinationEmpty");
      setTextWithHint("#exportDestinationText", destinationText);
      const preflightNode = $("#exportPreflight");
      if (preflightNode) preflightNode.innerHTML = exportPreflightMarkup();
      renderExportResult();
      renderBatchScopePill("#exportBatchScopeText", "#exportBatchScopeLabel", batchTarget);
      const batchActions = CulviaBatchActions.acceptControls(batchTarget, visiblePhotos, {
        filteredLlmReviewCount: getAppState()?.curation?.filteredLlmReviewedCount,
        hasLlmReview: (photo) => numericValue(photo.llmReviewScores?.llm_review_overall) != null,
      });
      updateExportActionControls(all, batchActions);
      renderExportBatchColorChoices(batchActions);
      renderExportSelectedList(list, photos);
    }

    async function pickExportFolder() {
      if (isExporting() || getAppState()?.job?.running) return;
      try {
        const result = await postJson("/api/pick-export-folder", {});
        if (result.folder && !isExporting() && !getAppState()?.job?.running) {
          exportDestination = result.folder;
          destinationChosen = true;
          exportStatusText = "";
          applyExportPreflightState({ error: "", preflight: null });
          await refreshExportPreflight();
        }
      } catch (_error) {
        // Folder picker cancellation should stay quiet.
      }
    }

    async function refreshExportPreflight(options = {}) {
      if (isExporting() || getAppState()?.job?.running) return;
      if (!exportDestination) {
        applyExportPreflightState(CulviaExportPreflightState.emptyState());
        renderExportList();
        return;
      }
      const requestKey = options.key || currentExportPreflightKey();
      applyExportPreflightState(CulviaExportPreflightState.beginRequest(requestKey));
      renderExportList();
      try {
        const payload = await postJson("/api/export/preflight", { destination: exportDestination });
        if (!CulviaExportPreflightState.isCurrent(exportPreflightKey, requestKey)) return;
        applyExportPreflightState(CulviaExportPreflightState.successState(payload));
      } catch (error) {
        if (!CulviaExportPreflightState.isCurrent(exportPreflightKey, requestKey)) return;
        applyExportPreflightState(CulviaExportPreflightState.failureState(errorMessage(error)));
      } finally {
        if (!CulviaExportPreflightState.isCurrent(exportPreflightKey, requestKey)) return;
        applyExportPreflightState(CulviaExportPreflightState.finishRequest());
        renderExportList();
      }
    }

    async function exportSelectedPhotos() {
      if (isExporting() || getAppState()?.job?.running) return;
      if (!exportDestination || isExportDestinationBlocked()) return;
      exporting = true;
      exportStatusText = "";
      pendingPreviousOperationId = exportResult?.operationId || "";
      requestFailure = null;
      receiptReadError = null;
      receiptTransportError = null;
      if (!exportResult?.operationId) exportResult = null;
      try {
        onActivityChange?.();
        renderExportList();
        const result = await postJson("/api/export/selected-files", { destination: exportDestination });
        if (result.operationId) acceptReceipt(result);
        else exportResult = result;
        if (!result.operationId || result.status === "completed") {
          showCommandNotice(CulviaExportActions.successNotice(result, { pathName }));
        }
      } catch (error) {
        requestFailure = error;
        failedPreviousOperationId = pendingPreviousOperationId;
        const failure = CulviaExportActions.failureState(errorMessage(error));
        exportStatusText = failure.statusText;
        showCommandNotice(failure.notice, failure.duration);
      } finally {
        if (refreshState) {
          try {
            await refreshState();
            syncReceiptFromState({ stateLoaded: true });
          } catch (error) {
            receiptTransportError = error;
          }
        }
        exporting = false;
        pendingPreviousOperationId = "";
        applyExportPreflightState(CulviaExportPreflightState.emptyState());
        renderExportList();
        onActivityChange?.();
      }
    }

    async function downloadFilteredCsv(event) {
      event?.preventDefault();
      if (getAppState()?.job?.running) return;
      try {
        await CulviaBatchActions.withCommittedFilter(
          "filtered",
          flushFilterUpdate,
          () => downloadFile("/api/export", "culvia_scores_filtered.csv"),
        );
      } catch (error) {
        showCommandNotice(
          {
            tone: "danger",
            state: t("export.filteredCsvFailureState"),
            title: t("export.filteredCsvFailureTitle"),
            detail: errorMessage(error),
          },
          4200,
        );
      }
    }

    async function revealExportDestination() {
      const destination = CulviaExportActions.destinationFromResult(exportResult, exportDestination);
      if (!destination) return;
      try {
        await postJson("/api/reveal", CulviaExportActions.revealDestinationPayload(destination));
      } catch (error) {
        showCommandNotice(CulviaExportActions.revealFailureNotice(errorMessage(error)), 4200);
      }
    }

    async function copyExportDestination() {
      const destination = CulviaExportActions.destinationFromResult(exportResult, exportDestination);
      if (!destination) return;
      try {
        const copied = await clipboard.writeText(destination);
        if (!copied) throw new Error("clipboard_unavailable");
        showCommandNotice(CulviaExportActions.copyDestinationSuccessNotice(destination, { pathName }), 2600);
      } catch (error) {
        showCommandNotice(CulviaExportActions.copyDestinationFailureNotice(errorMessage(error)), 4200);
      }
    }

    function handleExportResultClick(event) {
      const resultActions = CulviaExportActions.resultActions;
      const action = CulviaExportActions.resultActionFromEvent(event);
      if (action === resultActions.downloadReceipt) {
        const operationId = event.target.closest("[data-export-download-receipt]").dataset.exportDownloadReceipt;
        const download = CulviaExportActions.receiptDownload(operationId);
        if (download) downloadFile(download.url, download.filename);
        return;
      }
      if (action === resultActions.refreshReceipt) {
        void refreshExportReceipt();
        return;
      }
      if (action === resultActions.copyDestination) {
        void copyExportDestination();
        return;
      }
      if (action === resultActions.revealDestination) {
        void revealExportDestination();
      }
    }

    function handleExportPreflightClick(event) {
      const action = CulviaExportPreflight.actionFromEvent(event);
      if (action === CulviaExportPreflight.actions.pickFolder) {
        void pickExportFolder();
      }
    }

    return {
      clearReceipt,
      isExporting,
      receiptToken,
      syncReceiptFromState,
      stateReadFailed,
      refreshExportReceipt,
      renderExportList,
      pickExportFolder,
      refreshExportPreflight,
      exportSelectedPhotos,
      downloadFilteredCsv,
      revealExportDestination,
      copyExportDestination,
      handleExportResultClick,
      handleExportPreflightClick,
    };
  }

  return { create };
})();
