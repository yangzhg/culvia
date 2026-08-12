window.CulviaUpdatePanel = (() => {
  const RELEASE_PATH_PREFIX = "/yangzhg/culvia/releases/tag/";

  function versionText(value, t) {
    const version = String(value || "").trim().replace(/^[vV]/, "");
    return version ? `v${version}` : t("about.versionUnknown");
  }

  function runtimeText(app, t) {
    if (app?.distribution !== "desktop") return t("about.runtime.web");
    if (app?.runtimeProfile === "full") return t("about.runtime.desktopFull");
    if (app?.runtimeProfile === "lite") return t("about.runtime.desktopLite");
    return t("about.runtime.desktop");
  }

  function trustedReleaseUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (
        url.protocol !== "https:"
        || url.hostname !== "github.com"
        || url.port
        || url.username
        || url.password
        || url.search
        || url.hash
      ) return "";
      const tag = url.pathname.slice(RELEASE_PATH_PREFIX.length);
      return url.pathname.startsWith(RELEASE_PATH_PREFIX) && tag && !tag.includes("/") ? url.toString() : "";
    } catch (_error) {
      return "";
    }
  }

  function statusView({ checking = false, error = "", result = null } = {}, t) {
    if (checking) return { text: t("update.checking"), tone: "", labelKey: "update.checking" };
    if (error) {
      return {
        text: t("update.failed", { reason: error }),
        tone: "error",
        labelKey: "update.recheck",
      };
    }
    if (result?.status === "updateAvailable") {
      return {
        text: t("update.available", { version: result.latestVersion }),
        tone: "available",
        labelKey: "update.recheck",
      };
    }
    if (result?.status === "ahead") {
      return {
        text: t("update.ahead", { version: result.latestVersion }),
        tone: "ready",
        labelKey: "update.recheck",
      };
    }
    if (result?.status === "current") {
      return {
        text: t("update.current", { version: result.currentVersion }),
        tone: "ready",
        labelKey: "update.recheck",
      };
    }
    return { text: t("update.idle"), tone: "", labelKey: "update.check" };
  }

  function viewState(app = {}, updateState = {}, t = (key) => key) {
    const status = statusView(updateState, t);
    const desktop = app.distribution === "desktop";
    const mismatch = Boolean(desktop && app.versionMismatch);
    const releaseUrl = updateState.result?.status === "updateAvailable"
      ? trustedReleaseUrl(updateState.result.releaseUrl)
      : "";
    return {
      currentVersion: versionText(app.version || app.serviceVersion, t),
      runtime: runtimeText(app, t),
      platform: t("about.platformValue", {
        platform: app.platform || t("about.versionUnknown"),
        architecture: app.architecture || t("about.versionUnknown"),
      }),
      serviceVersion: versionText(app.serviceVersion, t),
      serviceVersionVisible: desktop,
      mismatchText: mismatch
        ? t("about.versionMismatch", {
            shellVersion: String(app.shellVersion || app.version || "").replace(/^[vV]/, ""),
            serviceVersion: String(app.serviceVersion || "").replace(/^[vV]/, ""),
          })
        : "",
      statusText: status.text,
      statusClass: `update-check-status${status.tone ? ` is-${status.tone}` : ""}`,
      checkLabelKey: status.labelKey,
      checking: Boolean(updateState.checking),
      releaseUrl,
    };
  }

  function create({ $, t, postJson, errorMessage, getAppState }) {
    let checking = false;
    let result = null;
    let lastError = null;

    function setText(selector, value) {
      const node = $(selector);
      if (node) node.textContent = value;
    }

    function render() {
      const error = lastError ? errorMessage(lastError) : "";
      const plan = viewState(getAppState()?.app || {}, { checking, result, error }, t);
      setText("#appVersionValue", plan.currentVersion);
      setText("#appRuntimeValue", plan.runtime);
      setText("#appPlatformValue", plan.platform);
      setText("#serviceVersionValue", plan.serviceVersion);
      $("#serviceVersionFact")?.classList.toggle("is-hidden", !plan.serviceVersionVisible);

      const mismatchNotice = $("#versionMismatchNotice");
      if (mismatchNotice) {
        mismatchNotice.textContent = plan.mismatchText;
        mismatchNotice.classList.toggle("is-hidden", !plan.mismatchText);
      }

      const status = $("#updateCheckStatus");
      if (status) {
        status.className = plan.statusClass;
        status.textContent = plan.statusText;
      }

      const button = $("#checkUpdateBtn");
      if (button) {
        button.disabled = plan.checking;
        button.setAttribute("aria-busy", plan.checking ? "true" : "false");
        button.querySelector(".icon")?.classList.toggle("is-spinning", plan.checking);
      }
      const buttonLabel = $("#checkUpdateLabel");
      if (buttonLabel) {
        buttonLabel.dataset.i18n = plan.checkLabelKey;
        buttonLabel.textContent = t(plan.checkLabelKey);
      }

      const releaseLink = $("#openReleaseLink");
      if (releaseLink) {
        releaseLink.classList.toggle("is-hidden", !plan.releaseUrl);
        if (plan.releaseUrl) releaseLink.href = plan.releaseUrl;
        else releaseLink.removeAttribute("href");
      }
    }

    async function checkForUpdates() {
      if (checking) return;
      checking = true;
      lastError = null;
      render();
      try {
        const payload = await postJson("/api/update/check", {});
        if (!payload?.status || !payload?.latestVersion) {
          throw new Error(JSON.stringify({ errorCode: "updateCheckInvalidResponse" }));
        }
        result = payload;
      } catch (requestError) {
        result = null;
        lastError = requestError;
      } finally {
        checking = false;
        render();
      }
    }

    function bindEvents() {
      $("#checkUpdateBtn")?.addEventListener("click", checkForUpdates);
    }

    return {
      bindEvents,
      checkForUpdates,
      render,
    };
  }

  return {
    create,
    trustedReleaseUrl,
    viewState,
  };
})();
