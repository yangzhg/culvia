window.CulviaManualStatus = (() => {
  const normalizedStatuses = Object.freeze({
    hold: "hold",
    pending: "hold",
    pick: "pick",
    reject: "reject",
  });

  function normalizeStatus(value) {
    return normalizedStatuses[String(value || "").toLowerCase()] || "";
  }

  function toggledStatus(currentStatus, requestedStatus) {
    const current = normalizeStatus(currentStatus);
    const requested = normalizeStatus(requestedStatus);
    if (!requested) return "";
    return current === requested ? "" : requested;
  }

  function statusClass(value) {
    const normalized = normalizeStatus(value);
    if (normalized === "pick") return "is-picked";
    if (normalized === "reject") return "is-rejected";
    if (normalized === "hold") return "is-pending";
    return "is-unreviewed";
  }

  function statusIcon(value) {
    const normalized = normalizeStatus(value);
    if (normalized === "pick") return "check";
    if (normalized === "reject") return "x";
    if (normalized === "hold") return "clock";
    return "";
  }

  function stars(rating) {
    const numeric = Math.round(Number(rating || 0));
    const value = Math.min(Math.max(numeric, 0), 5);
    return `${"★".repeat(value)}${"☆".repeat(5 - value)}`;
  }

  return {
    normalizeStatus,
    stars,
    statusClass,
    statusIcon,
    toggledStatus,
  };
})();
