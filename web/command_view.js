window.CulviaCommandView = (() => {
  function t(key, params = {}) {
    const api = window.CulviaI18n;
    return api?.t ? api.t(key, params) : key;
  }

  function clamp(value, min = 0, max = 1) {
    const number = Number(value);
    if (!Number.isFinite(number)) return min;
    return Math.min(max, Math.max(min, number));
  }

  function isPaused(job = {}) {
    return Boolean(job?.paused) || job?.phase === "paused" || job?.phase === "pausing";
  }

  function currentPhotoView(job = {}, { running = false, paused = false, modelProgress = null } = {}) {
    if (!running || modelProgress || !job?.currentFile) {
      return {
        completed: [],
        emptyText: t("command.waitingEvaluation"),
        file: "",
        stage: "",
        thumb: "",
        visible: false,
      };
    }
    const activeStage = job.activeEvaluation || t("command.processingButton");
    return {
      completed: Array.isArray(job.completedEvaluations) ? job.completedEvaluations : [],
      emptyText: t("command.waitingEvaluation"),
      file: job.currentFile,
      stage: paused ? t("command.pausedStage") : t("command.currentStage", { stage: activeStage }),
      thumb: job.currentThumb || "",
      visible: true,
    };
  }

  function progressView(progress) {
    if (!progress) return null;
    const value = clamp(progress.value);
    return {
      detail: progress.detail || "",
      label: progress.label || t("command.processing"),
      value,
      width: `${value * 100}%`,
    };
  }

  function commandViewState({
    commandNotice = null,
    hasResults = false,
    job = {},
    model = {},
    networkText = "",
    sourceReady = false,
    summary = {},
  } = {}) {
    const running = Boolean(job?.running);
    const sourcePreviewRunning = running && job?.kind === "source_preview";
    const modelProgress = job?.modelProgress;
    const paused = isPaused(job);
    const loadingModel = !sourcePreviewRunning && job?.phase === "loading_model";
    const resolvedNetworkText = networkText || t("network.directConnection");
    let dotTone = model?.tone || "";
    let state = model?.label || t("command.state");
    let title = sourceReady ? (model?.downloaded ? t("command.readyToScore") : t("command.firstRunPrepares")) : t("command.chooseSourceFirst");
    let detail = sourceReady
      ? model?.downloaded
        ? t("command.startAutoDetail")
        : t("command.prepareWithNetwork", { network: resolvedNetworkText })
      : t("command.chooseSourceDetail");
    let progress = null;

    if (running) {
      dotTone = "partial";
      state = sourcePreviewRunning
        ? t("command.scanningSource")
        : paused
          ? t("command.pausedState")
          : modelProgress
            ? t("command.preparingModel")
            : loadingModel
              ? t("command.loadingModel")
              : t("command.scoring");
      title = sourcePreviewRunning
        ? job.title || t("command.scanningSourceTitle")
        : paused
          ? t("command.pausedTitle")
          : modelProgress
            ? t("command.preparingTitle")
            : loadingModel
              ? t("command.loadingTitle")
              : t("command.scoringTitle");
      detail = sourcePreviewRunning
        ? job.detail || t("command.scanningSourceDetail")
        : modelProgress
        ? t("command.modelThenScore")
        : loadingModel
          ? job.detail || t("command.modelReadyLocal")
          : paused
            ? job.detail || t("command.resumeDetail")
            : job.detail || t("command.waitPlease");
      progress = {
        detail: modelProgress?.detail || job.detail || "",
        label: modelProgress?.label || job.title || t("command.processing"),
        value: modelProgress?.progress ?? (loadingModel ? 0.96 : job.progress ?? 0),
      };
    } else if (job?.phase === "error") {
      dotTone = "danger";
      state = t("command.needsAction");
      title = t("command.incomplete");
      detail = job.error || job.detail || t("command.retryDetail");
    } else if ((summary?.scored || 0) > 0) {
      dotTone = "ready";
      state = t("command.resultsReady");
      title = t("command.continueOrCull");
      detail = t("command.scoredSummary", { scored: summary.scored, showing: summary.showing });
    }

    if (!running && commandNotice) {
      dotTone = commandNotice.tone || "ready";
      state = commandNotice.state;
      title = commandNotice.title;
      detail = commandNotice.detail;
      progress = commandNotice.progress || null;
    }

    const noticeLoading = Boolean(commandNotice?.loading);
    const noticeAction = !running && !noticeLoading ? commandNotice?.action : null;
    return {
      compact: !running && Boolean(hasResults),
      currentPhoto: currentPhotoView(job, { running, paused, modelProgress }),
      detail,
      dotTone,
      mainScore: {
        disabled: running || noticeLoading || !sourceReady,
        icon: running || noticeLoading ? "loader" : "play",
        label: running ? t("command.processingButton") : model?.downloaded ? t("command.start") : t("command.prepareAndScore"),
      },
      noticeAction: {
        disabled: !noticeAction,
        icon: noticeAction?.icon || "undo",
        label: noticeAction?.label || t("command.undo"),
        visible: Boolean(noticeAction),
      },
      pause: {
        disabled: noticeLoading,
        icon: paused ? "play" : "pause",
        label: paused ? t("command.continue") : t("command.pause"),
        visible: running && !sourcePreviewRunning,
      },
      progress: progressView(progress),
      running,
      state,
      title,
    };
  }

  function commandDomPlan(viewState) {
    return {
      buttons: {
        mainScore: {
          disabled: viewState.mainScore.disabled,
          icon: viewState.mainScore.icon,
          label: viewState.mainScore.label,
          selector: "#mainScoreBtn",
        },
        noticeAction: {
          disabled: viewState.noticeAction.disabled,
          hidden: !viewState.noticeAction.visible,
          icon: viewState.noticeAction.icon,
          label: viewState.noticeAction.label,
          selector: "#commandNoticeActionBtn",
        },
        pause: {
          disabled: viewState.pause.disabled,
          hidden: !viewState.pause.visible,
          icon: viewState.pause.icon,
          label: viewState.pause.label,
          selector: "#pauseJobBtn",
        },
      },
      center: {
        compact: viewState.compact,
        running: viewState.running,
        selector: ".command-center",
      },
      currentPhoto: {
        completed: viewState.currentPhoto.completed,
        completedSelector: "#commandCompletedEvaluations",
        emptyText: viewState.currentPhoto.emptyText,
        file: viewState.currentPhoto.file,
        fileSelector: "#commandCurrentFile",
        hidden: !viewState.currentPhoto.visible,
        selector: "#commandCurrentPhoto",
        stage: viewState.currentPhoto.stage,
        stageSelector: "#commandCurrentStage",
        thumb: viewState.currentPhoto.thumb,
        thumbSelector: "#commandCurrentThumb",
      },
      dot: {
        className: `dot ${viewState.dotTone}`.trim(),
        selector: "#commandDot",
      },
      progress: {
        barSelector: "#commandProgressBar",
        detail: viewState.progress?.detail || "",
        detailSelector: "#commandProgressDetail",
        hidden: !viewState.progress,
        label: viewState.progress?.label || "",
        labelSelector: "#commandProgressLabel",
        selector: "#commandProgress",
        width: viewState.progress?.width || "0%",
      },
      texts: [
        { selector: "#commandState", text: viewState.state },
        { selector: "#commandTitle", text: viewState.title },
        { selector: "#commandDetail", text: viewState.detail },
      ],
    };
  }

  return {
    commandDomPlan,
    commandViewState,
    currentPhotoView,
    isPaused,
    progressView,
  };
})();
