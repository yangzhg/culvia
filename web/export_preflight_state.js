window.CulviaExportPreflightState = (() => {
  function shouldRefresh(options = {}) {
    return Boolean(options.destination)
      && options.activeView === "export"
      && !options.loading
      && options.storedKey !== options.currentKey;
  }

  function emptyState() {
    return {
      error: "",
      key: "",
      loading: false,
      preflight: null,
    };
  }

  function beginRequest(requestKey) {
    return {
      error: "",
      key: String(requestKey || ""),
      loading: true,
    };
  }

  function isCurrent(storedKey, requestKey) {
    return String(storedKey || "") === String(requestKey || "");
  }

  function successState(payload) {
    return {
      error: "",
      preflight: payload || null,
    };
  }

  function failureState(message) {
    return {
      error: String(message || "导出预检不可用"),
      preflight: null,
    };
  }

  function finishRequest() {
    return {
      loading: false,
    };
  }

  function exportBlocked(state = {}) {
    return Boolean(state.loading || state.error || state.preflight?.destinationWritable === false);
  }

  return {
    beginRequest,
    emptyState,
    exportBlocked,
    failureState,
    finishRequest,
    isCurrent,
    shouldRefresh,
    successState,
  };
})();
