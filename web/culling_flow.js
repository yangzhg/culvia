(function () {
  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function safeIndex(photos = [], index = 0) {
    const length = Array.isArray(photos) ? photos.length : 0;
    if (!length) return 0;
    return clamp(Number(index) || 0, 0, length - 1);
  }

  function nextIndexByDelta(photos = [], currentIndex = 0, delta = 0) {
    const length = Array.isArray(photos) ? photos.length : 0;
    if (!length) return 0;
    return clamp(safeIndex(photos, currentIndex) + Number(delta || 0), 0, length - 1);
  }

  function nextIndexAfterMark(photos = [], previousIndex = 0, previousFileId = "", advance = false) {
    const length = Array.isArray(photos) ? photos.length : 0;
    if (!length) return 0;
    const fallbackIndex = safeIndex(photos, previousIndex);
    const retainedIndex = photos.findIndex((photo) => photo?.fileId === previousFileId);
    if (retainedIndex < 0) return fallbackIndex;
    return advance ? nextIndexByDelta(photos, retainedIndex, 1) : retainedIndex;
  }

  function rangeFileIds(photos = [], anchorFileId = "", targetFileId = "") {
    if (!Array.isArray(photos) || !anchorFileId || !targetFileId) return [];
    const anchorIndex = photos.findIndex((photo) => photo?.fileId === anchorFileId);
    const targetIndex = photos.findIndex((photo) => photo?.fileId === targetFileId);
    if (anchorIndex < 0 || targetIndex < 0) return [];
    const start = Math.min(anchorIndex, targetIndex);
    const end = Math.max(anchorIndex, targetIndex);
    return photos.slice(start, end + 1).map((photo) => photo?.fileId).filter(Boolean);
  }

  window.CulviaCullingFlow = {
    nextIndexByDelta,
    nextIndexAfterMark,
    rangeFileIds,
  };
})();
