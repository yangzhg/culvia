window.CulviaExportActions = (() => {
  const resultActions = Object.freeze({
    copyDestination: "copyDestination",
    revealDestination: "revealDestination",
    none: "",
  });

  function t(key, params = {}, fallback = "") {
    const api = window.CulviaI18n;
    const value = api?.t ? api.t(key, params) : key;
    return value === key && fallback ? fallback : value;
  }

  function copiedCount(result) {
    return Number(result?.copied || 0);
  }

  function skippedCount(result) {
    return Number(result?.skipped || 0);
  }

  function exportStatusText(result) {
    const copied = copiedCount(result);
    const skipped = skippedCount(result);
    return skipped
      ? t("export.statusPartial", { copied, skipped }, `已导出 ${copied} 张 · ${skipped} 张未复制`)
      : t("export.statusDone", { copied }, `已导出 ${copied} 张`);
  }

  function primaryActionView(options = {}) {
    const selected = Number(options.selectedCount || 0);
    const destination = String(options.destination || "");
    const preflight = options.preflight || null;
    const loading = Boolean(options.preflightLoading);
    const error = String(options.preflightError || "");
    const statusText = String(options.statusText || "");
    const ready = preflight ? Number(preflight.ready || 0) : selected;
    const missing = Number(preflight?.missing || 0);
    const renamed = Number(preflight?.renamed || 0);
    const destinationIssue = String(preflight?.destinationIssue || "");
    const baseLabel = selected ? t("export.exportCount", { count: selected }, `导出 ${selected} 张`) : t("export.selected", {}, "导出入选");

    if (!selected) {
      return {
        disabled: true,
        hint: t("export.noPicksHint", {}, "当前没有入选照片。"),
        icon: "archive",
        label: t("export.selected", {}, "导出入选"),
      };
    }
    if (!destination) {
      return {
        disabled: true,
        hint: t("export.waitDestinationHint", { count: selected }, `已入选 ${selected} 张，等待选择导出位置。`),
        icon: "archive",
        label: baseLabel,
      };
    }
    if (loading) {
      return {
        disabled: true,
        hint: t("export.checkingHint", {}, "正在检查导出位置。"),
        icon: "loader",
        label: t("export.checking", {}, "检查中"),
      };
    }
    if (error) {
      return {
        disabled: true,
        hint: error,
        icon: "circleHelp",
        label: baseLabel,
      };
    }
    if (preflight?.destinationWritable === false || options.blocked) {
      return {
        disabled: true,
        hint: destinationIssue || t("export.destinationUnavailable", {}, "导出位置不可用。"),
        icon: "circleHelp",
        label: baseLabel,
      };
    }
    if (statusText) {
      return {
        disabled: false,
        hint: statusText,
        icon: "archive",
        label: t("export.again", { count: selected }, `再次导出 ${selected} 张`),
      };
    }
    if (missing) {
      return {
        disabled: false,
        hint: t("export.readyWithMissingHint", { missing, ready }, `${ready} 张可复制，${missing} 张缺失。`),
        icon: "archive",
        label: ready ? t("export.exportCount", { count: ready }, `导出 ${ready} 张`) : baseLabel,
      };
    }
    if (renamed) {
      return {
        disabled: false,
        hint: t("export.readyWithRenamedHint", { renamed, selected }, `${selected} 张可复制，${renamed} 张会自动改名。`),
        icon: "archive",
        label: baseLabel,
      };
    }
    return {
      disabled: false,
      hint: t("export.readyHint", { count: selected }, `${selected} 张可复制。`),
      icon: "archive",
      label: baseLabel,
    };
  }

  function successNotice(result, helpers) {
    const copied = copiedCount(result);
    const destination = String(result?.destination || "");
    const destinationName = destination ? helpers.pathName(destination) : t("export.destinationName", {}, "导出目录");
    return {
      tone: skippedCount(result) ? "partial" : "ready",
      state: t("export.noticeDone", {}, "已导出"),
      title: skippedCount(result) ? t("export.noticePartial", {}, "入选照片部分导出") : t("export.noticeSuccess", {}, "入选照片已导出"),
      detail: `${t("common.photoCount", { count: copied }, `${copied} 张照片`)} · ${destinationName}`,
    };
  }

  function failureState(message) {
    const detail = String(message || t("export.noticeFailureState", {}, "导出失败"));
    return {
      statusText: detail,
      notice: {
        tone: "danger",
        state: t("export.noticeFailureState", {}, "导出失败"),
        title: t("export.noticeFailureTitle", {}, "没有导出入选照片"),
        detail,
      },
      duration: 4200,
    };
  }

  function destinationFromResult(result, fallback) {
    return String(result?.destination || fallback || "");
  }

  function revealDestinationPayload(destination) {
    return {
      path: String(destination || ""),
      purpose: "export",
    };
  }

  function revealFailureNotice(message) {
    const fallback = t("export.revealFailureDetail", {}, "当前环境无法直接打开文件管理器，请使用导出位置手动打开。");
    return {
      tone: "danger",
      state: t("export.revealFailureState", {}, "无法打开"),
      title: t("export.revealFailureTitle", {}, "没有打开导出目录"),
      detail: String(message || fallback),
    };
  }

  function copyDestinationSuccessNotice(destination, helpers) {
    const destinationName = helpers?.pathName ? helpers.pathName(destination) : t("export.destinationName", {}, "导出目录");
    return {
      tone: "ready",
      state: t("export.copySuccessState", {}, "已复制"),
      title: t("export.copySuccessTitle", {}, "导出路径已复制"),
      detail: destinationName,
    };
  }

  function copyDestinationFailureNotice(message) {
    return {
      tone: "danger",
      state: t("export.copyFailureState", {}, "复制失败"),
      title: t("export.copyFailureTitle", {}, "没有复制导出路径"),
      detail: String(message || t("export.copyFailureDetail", {}, "当前浏览器不允许写入剪贴板，请手动复制导出位置。")),
    };
  }

  function resultActionFromEvent(event) {
    const target = event?.target;
    if (target?.closest?.("[data-export-copy-destination]")) return resultActions.copyDestination;
    if (target?.closest?.("[data-export-reveal-destination]")) return resultActions.revealDestination;
    return resultActions.none;
  }

  return {
    copyDestinationFailureNotice,
    copyDestinationSuccessNotice,
    destinationFromResult,
    exportStatusText,
    failureState,
    primaryActionView,
    revealDestinationPayload,
    revealFailureNotice,
    resultActionFromEvent,
    resultActions,
    successNotice,
  };
})();
