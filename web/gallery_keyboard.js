window.CulviaGalleryKeyboard = (() => {
  const actions = Object.freeze({
    batchStatus: "batchStatus",
    clearSelection: "clearSelection",
    none: "",
    selectVisible: "selectVisible",
  });

  function shortcutKey(event) {
    return String(event?.key || "").toLowerCase();
  }

  function hasNoModifiers(event) {
    return !event?.metaKey && !event?.ctrlKey && !event?.shiftKey && !event?.altKey;
  }

  function isSelectAllShortcut(event) {
    return !event?.repeat && (event?.metaKey || event?.ctrlKey) && !event?.shiftKey && !event?.altKey && shortcutKey(event) === "a";
  }

  function galleryStatusShortcut(key) {
    const statusByKey = { p: "pick", u: "hold", x: "reject" };
    const normalized = String(key || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(statusByKey, normalized) ? statusByKey[normalized] : undefined;
  }

  function shortcutActionFromEvent(event, context = {}) {
    if (context.activeView !== "gallery") return { action: actions.none, status: undefined };
    const selectedCount = Number(context.selectedCount || 0);
    if (isSelectAllShortcut(event)) return { action: actions.selectVisible, status: undefined };
    if (!event?.repeat && event?.key === "Escape" && hasNoModifiers(event) && selectedCount) {
      return { action: actions.clearSelection, status: undefined };
    }
    const status = galleryStatusShortcut(shortcutKey(event));
    if (status !== undefined && !event?.repeat && hasNoModifiers(event) && selectedCount) {
      return { action: actions.batchStatus, status };
    }
    return { action: actions.none, status: undefined };
  }

  return {
    actions,
    galleryStatusShortcut,
    hasNoModifiers,
    isSelectAllShortcut,
    shortcutActionFromEvent,
    shortcutKey,
  };
})();
