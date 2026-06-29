window.CulviaExportResultData = (() => {
  function normalize(result) {
    if (!result) return null;
    const copiedFiles = normalizeCopiedFiles(result);
    const skippedDetails = normalizeSkippedDetails(result);
    const skippedReasonSummary = normalizeSkippedReasonSummary(result, skippedDetails);
    return {
      copied: Number(result.copied || 0),
      copiedFiles,
      destination: String(result.destination || ""),
      skipped: Number(result.skipped || 0),
      skippedDetails,
      skippedReasonSummary,
    };
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
    normalizeSkippedDetails,
    normalizeSkippedReasonSummary,
  };
})();
