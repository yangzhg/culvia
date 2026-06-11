window.CulviaSourcePanel = (() => {
  function create({
    $,
    $$,
    t,
    tr,
    escapeHtml,
    iconMarkup,
    pathName,
    parentPath,
    setText,
    apiClient,
    postJson,
    errorMessage,
    showCommandNotice,
    supportedTypes,
    copyFileFolderPath,
    refreshSourceDependentControls,
    render,
    loadState,
    syncPollTimer,
    resetSelectedIndex,
    getAppState,
    setAppState,
  }) {
    let sourceMode = "folders";
    let sourceInputsDirty = false;
    let sourcePreviewTimer = null;
    let sourcePreviewRequestId = 0;
    let sourcePreviewLoading = false;
    let sourcePreviewPending = false;
    let desktopDropHandledUntil = 0;

    function appState() {
      return getAppState();
    }

    function uniqueFolderList(items) {
      const source = Array.isArray(items) ? items : items == null ? [] : [items];
      const seen = new Set();
      return source
        .map((item) => String(item || "").trim())
        .filter((item) => {
          if (!item || seen.has(item)) return false;
          seen.add(item);
          return true;
        });
    }

    function syncFolderInputFromList(folders) {
      const input = $("#folderInput");
      if (input) input.value = uniqueFolderList(folders).join("\n");
    }

    function folderEditorHasFocus() {
      return Boolean(document.activeElement?.closest?.(".manual-path-edit"));
    }

    function foldersFromInput() {
      const list = $("#folderList");
      if (list) {
        const values = Array.from(list.querySelectorAll("[data-folder-path]")).map((input) => input.value);
        return uniqueFolderList(values);
      }
      const input = $("#folderInput");
      return input ? uniqueFolderList(input.value.split("\n")) : [];
    }

    function folderListsEqual(left = [], right = []) {
      const a = uniqueFolderList(left);
      const b = uniqueFolderList(right);
      return a.length === b.length && a.every((value, index) => value === b[index]);
    }

    function matchingPreview(folders = foldersFromInput()) {
      const preview = appState()?.sourcePreview;
      if (!preview || preview.mode !== "folders" || preview.ready !== true) return null;
      return folderListsEqual(preview.folders || [], folders) && Number.isFinite(Number(preview.total)) ? preview : null;
    }

    function isSourcePreviewJob(job = appState()?.job) {
      return Boolean(job?.running) && job.kind === "source_preview";
    }

    function isPreviewActive() {
      return sourcePreviewLoading || isSourcePreviewJob();
    }

    function cachePath() {
      return $("#cacheInput")?.value.trim() || "";
    }

    function inputSnapshot() {
      return {
        mode: sourceMode || appState()?.source?.mode || "folders",
        folders: foldersFromInput(),
        cachePath: cachePath() || appState()?.source?.cachePath || "",
      };
    }

    function applyInputSnapshot(snapshot) {
      const state = appState();
      if (!snapshot || !state) return;
      sourceMode = snapshot.mode || "folders";
      state.source = {
        ...(state.source || {}),
        mode: sourceMode,
        folders: uniqueFolderList(snapshot.folders || []),
        cachePath: snapshot.cachePath || "",
      };
      syncFolderInputFromList(state.source.folders || []);
    }

    function markInputsDirty() {
      sourceInputsDirty = true;
      syncFolderInputFromList(foldersFromInput());
      applyInputSnapshot(inputSnapshot());
      refreshSourceDependentControls();
    }

    function markClean() {
      sourceInputsDirty = false;
    }

    function folderValuesFromText(text) {
      return uniqueFolderList(String(text || "").split(/\r?\n/));
    }

    function renderSourceFolderList(folders = foldersFromInput(), busy = Boolean(appState()?.job?.running)) {
      const list = $("#folderList");
      if (!list) return;
      const normalized = uniqueFolderList(folders);
      if (!normalized.length) {
        list.innerHTML = `<div class="source-folder-empty">${escapeHtml(t("source.noFolders"))}</div>`;
        return;
      }
      list.innerHTML = normalized
        .map(
          (folder, index) => `
            <div class="source-folder-row" data-folder-row>
              <input
                class="text-input source-folder-input"
                type="text"
                value="${escapeHtml(folder)}"
                data-folder-path
                data-folder-index="${index}"
                aria-label="${escapeHtml(t("source.folderPath"))}"
                data-ui-tooltip="${escapeHtml(folder)}"
                ${busy ? "disabled" : ""}
              />
              <button class="icon-button" type="button" data-copy-source-folder="${escapeHtml(folder)}" data-ui-tooltip="${escapeHtml(t("source.copyFolder"))}" aria-label="${escapeHtml(t("source.copyFolder"))}" ${busy ? "disabled" : ""}>
                ${iconMarkup("copy")}
              </button>
              <button class="icon-button" type="button" data-remove-source-folder="${index}" data-ui-tooltip="${escapeHtml(t("source.removeFolder"))}" aria-label="${escapeHtml(t("source.removeFolder"))}" ${busy ? "disabled" : ""}>
                ${iconMarkup("trash")}
              </button>
            </div>
          `,
        )
        .join("");
    }

    function updatePathSummaries() {
      $("#folderSummary")?.removeAttribute("data-i18n");
      const folders = foldersFromInput();
      const preview = matchingPreview(folders);
      const previewText = isPreviewActive()
        ? ` · ${t("source.previewScanningState")}`
        : preview
          ? ` · ${t("source.previewCount", { count: Number(preview.total) })}`
          : "";
      if (!folders.length) {
        setText("#folderSummary", t("source.empty"));
      } else if (folders.length === 1) {
        setText("#folderSummary", `${pathName(folders[0])} · ${parentPath(folders[0])}${previewText}`);
      } else {
        setText(
          "#folderSummary",
          `${tr("source.folderCount", { count: folders.length }, `${folders.length} 个目录`)} · ${folders.slice(0, 2).map(pathName).join("、")}${previewText}`,
        );
      }
    }

    function setSourceMode(mode, { dirty = false } = {}) {
      if (dirty && appState()?.job?.running) return;
      sourceMode = mode;
      $$("[data-source]").forEach((button) => button.classList.toggle("is-active", button.dataset.source === mode));
      $$("[data-source-view]").forEach((view) => {
        view.classList.toggle("is-active", view.dataset.sourceView === mode);
      });
      if (dirty) {
        markInputsDirty();
        schedulePreview();
      }
    }

    function setFolderList(folders, { dirty = true, previewDelay = 240 } = {}) {
      const nextFolders = uniqueFolderList(folders);
      syncFolderInputFromList(nextFolders);
      renderSourceFolderList(nextFolders, Boolean(appState()?.job?.running));
      if (sourceMode !== "folders") setSourceMode("folders");
      if (dirty) {
        markInputsDirty();
        updatePathSummaries();
        schedulePreview(previewDelay);
      }
    }

    function addFolderEntries(values, { previewDelay = 120 } = {}) {
      const additions = uniqueFolderList(values);
      if (!additions.length || appState()?.job?.running) return;
      setFolderList([...foldersFromInput(), ...additions], { previewDelay });
      const addInput = $("#folderAddInput");
      if (addInput) addInput.value = "";
    }

    function hasSelectedSource() {
      return Boolean(foldersFromInput().length || appState()?.source?.uploadedPaths?.length);
    }

    function sourcePreviewPayload() {
      return {
        mode: sourceMode,
        folders: foldersFromInput(),
        cachePath: cachePath(),
        uploadedPaths: appState()?.source?.uploadedPaths || [],
      };
    }

    function stopPreview() {
      sourcePreviewRequestId += 1;
      sourcePreviewLoading = false;
      window.clearTimeout(sourcePreviewTimer);
    }

    function schedulePreview(delay = 240) {
      window.clearTimeout(sourcePreviewTimer);
      const requestId = ++sourcePreviewRequestId;
      if (!appState()) {
        sourcePreviewPending = true;
        sourcePreviewLoading = false;
        return;
      }
      if (appState().job?.running || sourceMode !== "folders") {
        sourcePreviewLoading = false;
        return;
      }
      sourcePreviewPending = false;
      const payload = sourcePreviewPayload();
      const hasFolders = Boolean((payload.folders || []).length);
      sourcePreviewTimer = window.setTimeout(() => {
        void loadSourcePreview(payload, requestId, { showLoading: hasFolders });
      }, hasFolders ? delay : 0);
    }

    async function loadSourcePreview(payload = sourcePreviewPayload(), requestId = ++sourcePreviewRequestId, options = {}) {
      const mode = payload.mode || "folders";
      if (!appState() || appState().job?.running || !["folders", "uploads"].includes(mode)) return;
      const hasSource = mode === "uploads" ? Boolean((payload.uploadedPaths || []).length) : Boolean((payload.folders || []).length);
      const sourceSnapshot = mode === "folders" ? inputSnapshot() : null;
      const showLoading = options.showLoading !== false && hasSource;
      sourcePreviewLoading = showLoading;
      if (showLoading) {
        render();
      }
      try {
        const response = await postJson("/api/source/preview", payload);
        if (requestId !== sourcePreviewRequestId) return;
        setAppState(response);
        if (sourceSnapshot) applyInputSnapshot(sourceSnapshot);
        resetSelectedIndex();
        sourcePreviewLoading = false;
        syncPollTimer();
      } catch (error) {
        if (requestId !== sourcePreviewRequestId) return;
        showCommandNotice(
          {
            tone: "danger",
            state: t("source.previewFailedState"),
            title: t("source.previewFailedTitle"),
            detail: errorMessage(error),
          },
          4200,
        );
      } finally {
        if (requestId === sourcePreviewRequestId) {
          sourcePreviewLoading = false;
          render();
          syncPollTimer();
        }
      }
    }

    async function loadUploadedSourcePreview(savedPaths) {
      const uploadedPaths = uniqueFolderList(savedPaths || []);
      if (!uploadedPaths.length || appState()?.job?.running) return;
      sourcePreviewRequestId += 1;
      sourcePreviewLoading = true;
      sourcePreviewPending = false;
      sourceMode = "uploads";
      const state = appState();
      if (state?.source) {
        state.source = {
          ...(state.source || {}),
          mode: "uploads",
          uploadedPaths,
        };
      }
      render();
      try {
        setAppState(await postJson("/api/source/preview", {
          mode: "uploads",
          folders: foldersFromInput(),
          cachePath: cachePath(),
          uploadedPaths,
        }));
        sourceInputsDirty = false;
        resetSelectedIndex();
        syncPollTimer();
        await loadState();
      } catch (error) {
        showCommandNotice(
          {
            tone: "danger",
            state: t("source.previewFailedState"),
            title: t("source.previewFailedTitle"),
            detail: errorMessage(error),
          },
          4200,
        );
      } finally {
        sourcePreviewLoading = false;
        render();
        syncPollTimer();
      }
    }

    function uploadFileName(file) {
      return file?.webkitRelativePath || file?.relativePath || file?.name || "upload";
    }

    function hasRelativeUploadPath(file) {
      return Boolean(file?.webkitRelativePath || file?.relativePath);
    }

    function annotateDroppedFile(file, relativePath) {
      if (!relativePath || file.webkitRelativePath) return file;
      try {
        Object.defineProperty(file, "relativePath", { value: relativePath, configurable: true });
      } catch (_error) {
        // A plain file name is still safe if the browser does not allow annotation.
      }
      return file;
    }

    function readEntryFile(entry, relativePath = "") {
      return new Promise((resolve) => {
        entry.file(
          (file) => resolve([annotateDroppedFile(file, relativePath || entry.fullPath?.replace(/^\/+/, "") || file.name)]),
          () => resolve([]),
        );
      });
    }

    async function readDirectoryEntry(entry, prefix = "") {
      const reader = entry.createReader();
      const files = [];
      const readBatch = () =>
        new Promise((resolve) => {
          reader.readEntries(resolve, () => resolve([]));
        });
      while (true) {
        const entries = await readBatch();
        if (!entries.length) break;
        for (const child of entries) {
          const childPath = `${prefix}${entry.name}/${child.name}`;
          if (child.isFile) {
            files.push(...(await readEntryFile(child, childPath)));
          } else if (child.isDirectory) {
            files.push(...(await readDirectoryEntry(child, `${prefix}${entry.name}/`)));
          }
        }
      }
      return files;
    }

    async function filesFromDataTransfer(dataTransfer) {
      const items = Array.from(dataTransfer?.items || []);
      if (!items.length) return Array.from(dataTransfer?.files || []);
      const files = [];
      for (const item of items) {
        const entry = item.webkitGetAsEntry?.();
        if (entry?.isFile) {
          files.push(...(await readEntryFile(entry)));
        } else if (entry?.isDirectory) {
          files.push(...(await readDirectoryEntry(entry)));
        } else {
          const file = item.getAsFile?.();
          if (file) files.push(file);
        }
      }
      return files.length ? files : Array.from(dataTransfer?.files || []);
    }

    async function uploadFiles(fileList) {
      if (appState()?.job?.running) return;
      const files = Array.from(fileList || []);
      if (!files.length) return;
      const containsDirectoryUpload = files.some(hasRelativeUploadPath);
      const form = new FormData();
      files.forEach((file) => form.append("files", file, uploadFileName(file)));
      $("#uploadHint").textContent = containsDirectoryUpload ? t("source.uploadingFolder") : t("source.uploading");
      const result = await apiClient.uploadForm("/api/upload", form);
      $("#uploadHint").textContent = t("source.uploadedCount", { count: Number(result.count || 0) });
      if ((result.saved || []).length) {
        await loadUploadedSourcePreview(result.saved || []);
      } else {
        await loadState();
      }
    }

    function handleDesktopDroppedPaths(paths) {
      const droppedPaths = uniqueFolderList(paths || []);
      if (!droppedPaths.length || appState()?.job?.running) return;
      desktopDropHandledUntil = Date.now() + 1500;
      addFolderEntries(droppedPaths, { previewDelay: 80 });
      showCommandNotice(
        {
          tone: "ready",
          state: t("source.desktopDropState"),
          title: t("source.desktopDropTitle"),
          detail: t("source.desktopDropDetail", { count: droppedPaths.length }),
        },
        2600,
      );
    }

    function buildScoringPayload(selectedModels = []) {
      return {
        mode: sourceMode,
        folders: foldersFromInput(),
        cachePath: cachePath(),
        uploadedPaths: appState()?.source?.uploadedPaths || [],
        selectedModels,
      };
    }

    function renderControls() {
      const state = appState();
      if (!state) return;
      const capabilities = state.capabilities || {};
      const busy = Boolean(state.job?.running);
      const nativeFolderButton = $("#pickNativeFolderBtn");
      const nativeFolderSupported = capabilities.nativeFolderPicker !== false;
      const nativeFolderLabel = nativeFolderSupported ? t("source.pickFolder") : t("source.pathOnly");
      nativeFolderButton.disabled = !nativeFolderSupported || busy;
      nativeFolderButton.dataset.uiTooltip = nativeFolderLabel;
      nativeFolderButton.removeAttribute("title");
      nativeFolderButton.setAttribute("aria-label", nativeFolderLabel);
      nativeFolderButton.classList.toggle("is-unavailable", !nativeFolderSupported);
      const folderInput = $("#folderInput");
      if (folderInput) folderInput.disabled = busy;
      const folderAddInput = $("#folderAddInput");
      if (folderAddInput) folderAddInput.disabled = busy;
      $("#folderAddBtn").disabled = busy;
      $("#clearFoldersBtn").disabled = busy || !foldersFromInput().length;
      const cacheInput = $("#cacheInput");
      if (cacheInput) cacheInput.disabled = busy;
      ["#pickFilesBtn", "#pickFolderBtn", "#fileInput", "#folderPicker"].forEach((selector) => {
        const control = $(selector);
        if (control) control.disabled = busy;
      });
      $$("[data-source]").forEach((button) => {
        button.disabled = busy;
      });
      if (!sourceInputsDirty && !folderEditorHasFocus()) {
        syncFolderInputFromList(state.source.folders || []);
        renderSourceFolderList(state.source.folders || [], busy);
      } else {
        renderSourceFolderList(foldersFromInput(), busy);
      }
      if (!sourceInputsDirty && document.activeElement !== $("#cacheInput")) {
        $("#cacheInput").value = state.source.cachePath || "";
      }
      updatePathSummaries();
      setSourceMode(sourceInputsDirty ? sourceMode : state.source.mode || sourceMode);
    }

    function resumePendingPreviewIfReady() {
      if (sourcePreviewPending && sourceMode === "folders" && !appState()?.job?.running) {
        schedulePreview(80);
      }
    }

    function bindEvents() {
      $("#fileInput").setAttribute("accept", supportedTypes.join(","));
      $("#folderPicker").setAttribute("accept", supportedTypes.join(","));

      $$("[data-source]").forEach((button) =>
        button.addEventListener("click", () => setSourceMode(button.dataset.source, { dirty: true })),
      );
      $("#pickFilesBtn").addEventListener("click", () => {
        if (!appState()?.job?.running) $("#fileInput").click();
      });
      $("#pickFolderBtn").addEventListener("click", () => {
        if (!appState()?.job?.running) $("#folderPicker").click();
      });
      $("#fileInput").addEventListener("change", (event) => uploadFiles(event.target.files));
      $("#folderPicker").addEventListener("change", (event) => uploadFiles(event.target.files));

      $("#pickNativeFolderBtn").addEventListener("click", async () => {
        if (appState()?.job?.running) return;
        try {
          const result = await postJson("/api/pick-folders", {});
          const picked = uniqueFolderList(result.folders || [result.folder]);
          if (!picked.length) return;
          addFolderEntries(picked, { previewDelay: 80 });
        } catch (_error) {
          // User cancellation should stay quiet.
        }
      });

      const dropzone = $("#dropzone");
      ["dragenter", "dragover"].forEach((eventName) => {
        dropzone.addEventListener(eventName, (event) => {
          event.preventDefault();
          dropzone.classList.add("is-dragging");
        });
      });
      ["dragleave", "drop"].forEach((eventName) => {
        dropzone.addEventListener(eventName, (event) => {
          event.preventDefault();
          dropzone.classList.remove("is-dragging");
        });
      });
      dropzone.addEventListener("drop", (event) => {
        if (!appState()?.job?.running && Date.now() > desktopDropHandledUntil) {
          void filesFromDataTransfer(event.dataTransfer).then((files) => uploadFiles(files));
        }
      });
      window.addEventListener("culvia-desktop-drop", (event) => {
        handleDesktopDroppedPaths(event.detail?.paths || []);
      });

      const handleFolderSourceChange = () => {
        if (appState()?.job?.running) return;
        if (sourceMode !== "folders") setSourceMode("folders");
        markInputsDirty();
        updatePathSummaries();
        schedulePreview();
      };
      $("#folderList").addEventListener("input", (event) => {
        if (!event.target?.matches?.("[data-folder-path]")) return;
        event.target.dataset.uiTooltip = event.target.value;
        handleFolderSourceChange();
      });
      $("#folderList").addEventListener("change", (event) => {
        if (!event.target?.matches?.("[data-folder-path]")) return;
        setFolderList(foldersFromInput(), { previewDelay: 120 });
      });
      $("#folderList").addEventListener("click", (event) => {
        const removeButton = event.target?.closest?.("[data-remove-source-folder]");
        if (removeButton) {
          const index = Number(removeButton.dataset.removeSourceFolder);
          setFolderList(foldersFromInput().filter((_folder, folderIndex) => folderIndex !== index), { previewDelay: 80 });
          return;
        }
        const copyButton = event.target?.closest?.("[data-copy-source-folder]");
        if (copyButton) {
          void copyFileFolderPath(copyButton.dataset.copySourceFolder || "");
        }
      });
      $("#folderAddBtn").addEventListener("click", () => addFolderEntries(folderValuesFromText($("#folderAddInput").value)));
      $("#folderAddInput").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          addFolderEntries(folderValuesFromText(event.target.value));
        }
      });
      $("#folderAddInput").addEventListener("paste", (event) => {
        const text = event.clipboardData?.getData("text") || "";
        if (!text.includes("\n")) return;
        event.preventDefault();
        addFolderEntries(folderValuesFromText(text));
      });
      $("#clearFoldersBtn").addEventListener("click", () => setFolderList([], { previewDelay: 0 }));
      $("#cacheInput").addEventListener("change", () => {
        if (appState()?.job?.running) return;
        markInputsDirty();
        schedulePreview(120);
      });
    }

    return {
      applyInputSnapshot,
      bindEvents,
      buildScoringPayload,
      cachePath,
      dirty: () => sourceInputsDirty,
      foldersFromInput,
      hasSelectedSource,
      inputSnapshot,
      isPreviewActive,
      markClean,
      markInputsDirty,
      matchingPreview,
      mode: () => sourceMode,
      renderControls,
      resumePendingPreviewIfReady,
      schedulePreview,
      setSourceMode,
      stopPreview,
      uniqueFolderList,
      updatePathSummaries,
    };
  }

  return { create };
})();
