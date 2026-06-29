window.CulviaViewerKeyboard = (() => {
  const actions = Object.freeze({
    color: "color",
    navigate: "navigate",
    none: "",
    rating: "rating",
    status: "status",
  });

  function shortcutKey(event) {
    return String(event?.key || "").toLowerCase();
  }

  function hasNoModifiers(event) {
    return !event?.metaKey && !event?.ctrlKey && !event?.shiftKey && !event?.altKey;
  }

  function isPlainManualShortcutEvent(event) {
    return !event?.repeat && hasNoModifiers(event);
  }

  function ratingShortcut(key) {
    const normalized = String(key || "");
    if (normalized === "0") return 0;
    return /^[1-5]$/.test(normalized) ? Number(normalized) : undefined;
  }

  function statusShortcut(key) {
    const statusByKey = { p: "pick", u: "hold", x: "reject" };
    const normalized = String(key || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(statusByKey, normalized) ? statusByKey[normalized] : undefined;
  }

  function colorShortcut(key) {
    const colorByKey = { b: "blue", c: "", g: "green", r: "red", v: "purple", y: "yellow" };
    const normalized = String(key || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(colorByKey, normalized) ? colorByKey[normalized] : undefined;
  }

  function navigationActionFromEvent(event) {
    if (!hasNoModifiers(event)) return { action: actions.none };
    if (event?.key === "ArrowLeft") return { action: actions.navigate, direction: -1 };
    if (event?.key === "ArrowRight") return { action: actions.navigate, direction: 1 };
    return { action: actions.none };
  }

  function shortcutActionFromEvent(event, context = {}) {
    if (context.activeView !== "viewer") return { action: actions.none };
    const navigation = navigationActionFromEvent(event);
    if (navigation.action !== actions.none) return navigation;
    if (!context.hasSelectedPhoto || !isPlainManualShortcutEvent(event)) return { action: actions.none };

    const rawKey = String(event?.key || "");
    const key = shortcutKey(event);
    const rating = ratingShortcut(rawKey);
    if (rating !== undefined) return { action: actions.rating, rating };

    const status = statusShortcut(key);
    if (status !== undefined) return { action: actions.status, status };

    const colorLabel = colorShortcut(key);
    if (colorLabel !== undefined) return { action: actions.color, colorLabel };
    return { action: actions.none };
  }

  return {
    actions,
    colorShortcut,
    hasNoModifiers,
    isPlainManualShortcutEvent,
    navigationActionFromEvent,
    ratingShortcut,
    shortcutActionFromEvent,
    shortcutKey,
    statusShortcut,
  };
})();
