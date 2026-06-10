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
    localizedScoreLevel,
    manualBadgeMarkup,
    colorLabelMeta,
    manualColorLabels,
    numericValue,
    clipboard,
    postJson,
    errorMessage,
    showCommandNotice,
    revealPhoto,
    applyBatchColor,
    galleryBatchTarget,
    renderBatchScopePill,
    getAppState,
    getActiveView,
  }) {
    let exportDestination = "";
    let exportStatusText = "";
    let exportResult = null;
    let exportPreflight = null;
    let exportPreflightLoading = false;
    let exportPreflightError = "";
    let exportPreflightKey = "";

    function setMeterWidth(selector, value, total) {
      const node = $(selector);
      if (!node) return;
      const percent = total > 0 ? clamp(value / total, 0, 1) * 100 : 0;
      node.style.width = `${percent}%`;
    }

    function renderDeliveryOverview(all = {}, visible = {}) {
      const allTotal = Number(getAppState()?.summary?.scored || 0);
      const visibleTotal = Number(getAppState()?.summary?.showing || (getAppState()?.photos || []).length || 0);
      const selected = Number(all.selected || 0);
      const rejected = Number(all.rejected || 0);
      const pending = Math.max(allTotal - selected - rejected, 0);
      const visiblePending = Math.max(visibleTotal - Number(visible.selected || 0) - Number(visible.rejected || 0), 0);
      const decided = selected + rejected;
      setText("#deliveryReadyCount", t("common.photoCount", { count: selected }));
      setText("#deliveryPickCount", selected);
      setText("#deliveryPendingCount", pending);
      setText("#deliveryRejectCount", rejected);
      setText("#deliveryVisiblePendingCount", visiblePending);
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
      return CulviaExportPreflight.currentKey(exportDestination, getAppState()?.selectedPhotos || []);
    }

    function applyExportPreflightState(next) {
      if (!next) return;
      if (Object.prototype.hasOwnProperty.call(next, "preflight")) exportPreflight = next.preflight;
      if (Object.prototype.hasOwnProperty.call(next, "loading")) exportPreflightLoading = next.loading;
      if (Object.prototype.hasOwnProperty.call(next, "error")) exportPreflightError = next.error;
      if (Object.prototype.hasOwnProperty.call(next, "key")) exportPreflightKey = next.key;
    }

    function exportResultMarkup() {
      return CulviaExportResult.renderMarkup(exportResult, {
        canRevealDestination: getAppState()?.capabilities?.revealInFileManager !== false,
        escapeHtml,
        iconMarkup,
        parentPath,
        pathName,
      });
    }

    function bindBatchColorChoices(container) {
      container.querySelectorAll("[data-batch-color]").forEach((button) => {
        button.addEventListener("click", () => applyBatchColor(button.dataset.batchColor || "", galleryBatchTarget(getAppState()?.photos || [])));
      });
    }

    function renderExportBatchColorChoices(batchActions) {
      const container = $("#batchColorLabels");
      if (!container) return;
      const localizedColorLabels = manualColorLabels.map((item) => colorLabelMeta(item.value));
      container.innerHTML = CulviaBatchActions.colorChoiceViews(localizedColorLabels, {
        disabled: !batchActions.hasPhotos,
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
      const busy = Boolean(getAppState()?.job?.running);
      const exportAction = CulviaExportActions.primaryActionView({
        blocked: isExportDestinationBlocked(),
        destination: exportDestination,
        preflight: exportPreflight,
        preflightError: exportPreflightError,
        preflightLoading: exportPreflightLoading,
        selectedCount: all.selected,
        statusText: exportStatusText,
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
      const photos = getAppState()?.selectedPhotos || [];
      const visiblePhotos = getAppState()?.photos || [];
      const batchTarget = galleryBatchTarget(visiblePhotos);
      const list = $("#exportList");
      const all = getAppState()?.curation?.all || {};
      const visible = getAppState()?.curation?.visible || {};
      const preflightKey = currentExportPreflightKey();
      if (
        CulviaExportPreflightState.shouldRefresh({
          activeView: getActiveView(),
          currentKey: preflightKey,
          destination: exportDestination,
          loading: exportPreflightLoading,
          storedKey: exportPreflightKey,
        })
      ) {
        applyExportPreflightState({ key: preflightKey });
        void refreshExportPreflight({ key: preflightKey });
      }
      renderDeliveryOverview(all, visible);
      setText(
        "#curationSummaryText",
        t("export.curationSummary", {
          rated: all.rated || 0,
          selected: all.selected || 0,
          visibleSelected: visible.selected || 0,
        }),
      );
      const destinationText = exportDestination ? `${pathName(exportDestination)} · ${parentPath(exportDestination)}` : t("export.destinationEmpty");
      setTextWithHint("#exportDestinationText", destinationText);
      const preflightNode = $("#exportPreflight");
      if (preflightNode) preflightNode.innerHTML = exportPreflightMarkup();
      const exportResultNode = $("#exportResult");
      if (exportResultNode) exportResultNode.innerHTML = exportResultMarkup();
      renderBatchScopePill("#exportBatchScopeText", "#exportBatchScopeLabel", batchTarget);
      const batchActions = CulviaBatchActions.acceptControls(batchTarget, visiblePhotos, {
        hasLlmReview: (photo) => numericValue(photo.llmReviewScores?.llm_review_overall) != null,
      });
      updateExportActionControls(all, batchActions);
      renderExportBatchColorChoices(batchActions);
      renderExportSelectedList(list, photos);
    }

    async function pickExportFolder() {
      if (getAppState()?.job?.running) return;
      try {
        const result = await postJson("/api/pick-export-folder", {});
        if (result.folder) {
          exportDestination = result.folder;
          exportStatusText = "";
          exportResult = null;
          applyExportPreflightState({ error: "", preflight: null });
          await refreshExportPreflight();
        }
      } catch (_error) {
        // Folder picker cancellation should stay quiet.
      }
    }

    async function refreshExportPreflight(options = {}) {
      if (getAppState()?.job?.running) return;
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
      if (getAppState()?.job?.running) return;
      if (!exportDestination) return;
      try {
        $("#exportSelectedBtn").disabled = true;
        exportResult = null;
        renderExportList();
        const result = await postJson("/api/export/selected-files", { destination: exportDestination });
        exportResult = result;
        exportStatusText = CulviaExportActions.exportStatusText(result);
        showCommandNotice(CulviaExportActions.successNotice(result, { pathName }));
        renderExportList();
        await refreshExportPreflight();
      } catch (error) {
        exportResult = null;
        const failure = CulviaExportActions.failureState(errorMessage(error));
        exportStatusText = failure.statusText;
        showCommandNotice(failure.notice, failure.duration);
        renderExportList();
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
      renderExportList,
      pickExportFolder,
      refreshExportPreflight,
      exportSelectedPhotos,
      revealExportDestination,
      copyExportDestination,
      handleExportResultClick,
      handleExportPreflightClick,
    };
  }

  return { create };
})();
