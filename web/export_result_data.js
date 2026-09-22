window.CulviaExportResultData = (() => {
  const RECEIPT_STATUSES = new Set(["running", "completed", "failed", "interrupted"]);
  const PREVIEW_LIMIT = 20;

  function count(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0, Math.trunc(number)) : 0;
  }

  function normalize(result) {
    if (!result) return null;
    const copiedFiles = normalizeCopiedFiles(result);
    const skippedDetails = normalizeSkippedDetails(result);
    const skippedReasonSummary = normalizeSkippedReasonSummary(result, skippedDetails);
    const operationId = String(result.operationId || "");
    const previewEntries = normalizePreviewEntries(result);
    return {
      operationId,
      sequence: count(result.sequence),
      revision: count(result.revision),
      status: operationId ? (RECEIPT_STATUSES.has(result.status) ? result.status : "unknown") : "completed",
      total: count(result.total),
      processed: count(result.processed),
      unconfirmed: count(result.unconfirmed),
      notAttempted: count(result.notAttempted),
      previewEntries,
      previewCount: previewEntries.length,
      totalEntryCount: Math.max(count(result.totalEntryCount), previewEntries.length),
      errorText: result.errorText || null,
      copied: count(result.copied),
      copiedFiles,
      destination: String(result.destination || ""),
      skipped: count(result.skipped),
      skippedDetails,
      skippedReasonSummary,
    };
  }

  function normalizePreviewEntries(result) {
    if (!Array.isArray(result?.previewEntries)) return [];
    return result.previewEntries.slice(0, PREVIEW_LIMIT).map((entry) => ({
      index: count(entry?.index),
      source: String(entry?.source || ""),
      target: String(entry?.target || ""),
      status: String(entry?.status || "unknown"),
      reason: String(entry?.reason || ""),
      message: String(entry?.message || ""),
      messageText: entry?.messageText || null,
    }));
  }

  function shouldReplaceReceipt(current, incoming) {
    if (!incoming?.operationId) return false;
    if (!current?.operationId) return true;
    if (incoming.operationId !== current.operationId) return count(incoming.sequence) > count(current.sequence);
    if (count(incoming.revision) <= count(current.revision)) return false;
    return !(["completed", "failed", "interrupted"].includes(current.status) && incoming.status === "running");
  }

  function normalizeCopiedFiles(result) {
    if (Array.isArray(result?.copiedFiles)) return result.copiedFiles;
    return [];
  }

  function normalizeSkippedDetails(result) {
    if (Array.isArray(result?.skippedDetails)) {
      return result.skippedDetails.map((item) => ({
        label: item?.label || "未复制",
        message: item?.message || "",
        messageText: item?.messageText || null,
        path: item?.path || "",
        reason: item?.reason || "unknown",
      }));
    }
    return [];
  }

  function normalizeSkippedReasonSummary(result, skippedDetails = normalizeSkippedDetails(result)) {
    if (Array.isArray(result?.skippedReasonSummary) && result.skippedReasonSummary.length) {
      return result.skippedReasonSummary.map((item) => ({
        count: Number(item?.count || 0),
        label: item?.label || "未复制",
        reason: item?.reason || "unknown",
      }));
    }
    const grouped = skippedDetails.reduce((summary, item) => {
      const reason = item?.reason || "unknown";
      const label = item?.label || "未复制";
      const current = summary.get(reason) || { count: 0, label, reason };
      current.count += 1;
      summary.set(reason, current);
      return summary;
    }, new Map());
    return [...grouped.values()];
  }

  return {
    normalize,
    normalizeCopiedFiles,
    normalizePreviewEntries,
    normalizeSkippedDetails,
    normalizeSkippedReasonSummary,
    shouldReplaceReceipt,
  };
})();
