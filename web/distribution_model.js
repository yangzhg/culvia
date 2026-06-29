(() => {
  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function numericValue(value) {
    if (value == null || value === "") return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function averageNumbers(values) {
    const numbers = values.map(numericValue).filter((value) => value != null);
    if (!numbers.length) return null;
    return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
  }

  function tier(score, lens = "overview") {
    if (lens === "disagreement") {
      if (score >= 7) return "elite";
      if (score >= 5) return "strong";
      if (score >= 2) return "watch";
      return "quiet";
    }
    if (score >= 8) return "elite";
    if (score >= 7) return "strong";
    if (score >= 6) return "watch";
    return "quiet";
  }

  function photoTechnicalScore(photo) {
    return (
      numericValue(photo.technicalScores?.technical_overall) ??
      numericValue(photo.modelQualityScores?.clip_iqa_overall) ??
      numericValue(photo.scores?.quality)
    );
  }

  function photoAestheticScore(photo) {
    return (
      numericValue(photo.scores?.overall) ??
      averageNumbers([
        photo.scores?.quality,
        photo.scores?.composition,
        photo.scores?.lighting,
        photo.scores?.color,
        photo.scores?.depth_of_field,
        photo.scores?.content,
      ]) ??
      numericValue(photo.aestheticReferenceScores?.clip_aesthetic)
    );
  }

  function photoLlmScore(photo) {
    return (
      numericValue(photo.llmReviewScores?.llm_review_overall) ??
      averageNumbers([photo.llmReviewScores?.llm_aesthetic_overall, photo.llmReviewScores?.llm_technical_overall])
    );
  }

  function photoLocalReviewScore(photo) {
    return averageNumbers([photoAestheticScore(photo), photoTechnicalScore(photo)]);
  }

  function photoDisagreementIndex(photo) {
    const llmScore = photoLlmScore(photo);
    const localScore = photoLocalReviewScore(photo);
    if (llmScore == null || localScore == null) return null;
    return clamp((Math.abs(llmScore - localScore) / 2.4) * 10, 0, 10);
  }

  const lensOptions = [
    { value: "overview", labelKey: "distribution.lens.overview", label: "推荐", icon: "barChart" },
    { value: "technical", labelKey: "distribution.lens.technical", label: "技术", icon: "gauge" },
    { value: "llm", labelKey: "distribution.lens.llm", label: "大模型", icon: "brain" },
    { value: "aesthetic", labelKey: "distribution.lens.aesthetic", label: "审美细节", icon: "sparkle" },
    { value: "disagreement", labelKey: "distribution.lens.disagreement", label: "分歧", icon: "gitCompare" },
  ];

  function lensConfig(lens, translate) {
    const text = (lensKey, key) => translate(`distribution.config.${lensKey}.${key}`);
    const configs = {
      overview: {
        kicker: text("overview", "kicker"),
        title: text("overview", "title"),
        summaryLabel: text("overview", "summary"),
        densityLabel: text("overview", "density"),
        passLabel: text("overview", "pass"),
        passThreshold: 7,
        topThreshold: 8,
        xLabel: text("overview", "x"),
        yLabel: text("overview", "y"),
        compassTitle: text("overview", "compass"),
        primary: (entry) => entry.recommendation,
        x: (entry) => entry.technical,
        y: (entry) => entry.recommendation,
        empty: text("overview", "empty"),
      },
      technical: {
        kicker: text("technical", "kicker"),
        title: text("technical", "title"),
        summaryLabel: text("technical", "summary"),
        densityLabel: text("technical", "density"),
        passLabel: text("technical", "pass"),
        passThreshold: 7,
        topThreshold: 8,
        xLabel: text("technical", "x"),
        yLabel: text("technical", "y"),
        compassTitle: text("technical", "compass"),
        primary: (entry) => entry.technical,
        x: (entry) => entry.modelQuality ?? entry.technical,
        y: (entry) => entry.technical,
        empty: text("technical", "empty"),
      },
      llm: {
        kicker: text("llm", "kicker"),
        title: text("llm", "title"),
        summaryLabel: text("llm", "summary"),
        densityLabel: text("llm", "density"),
        passLabel: text("llm", "pass"),
        passThreshold: 7,
        topThreshold: 8,
        xLabel: text("llm", "x"),
        yLabel: text("llm", "y"),
        compassTitle: text("llm", "compass"),
        primary: (entry) => entry.llm,
        x: (entry) => entry.technical ?? entry.localReview,
        y: (entry) => entry.llm,
        empty: text("llm", "empty"),
      },
      aesthetic: {
        kicker: text("aesthetic", "kicker"),
        title: text("aesthetic", "title"),
        summaryLabel: text("aesthetic", "summary"),
        densityLabel: text("aesthetic", "density"),
        passLabel: text("aesthetic", "pass"),
        passThreshold: 7,
        topThreshold: 8,
        xLabel: text("aesthetic", "x"),
        yLabel: text("aesthetic", "y"),
        compassTitle: text("aesthetic", "compass"),
        primary: (entry) => entry.aesthetic,
        x: (entry) => numericValue(entry.photo.scores?.composition) ?? entry.aesthetic,
        y: (entry) => numericValue(entry.photo.scores?.lighting) ?? entry.aesthetic,
        empty: text("aesthetic", "empty"),
      },
      disagreement: {
        kicker: text("disagreement", "kicker"),
        title: text("disagreement", "title"),
        summaryLabel: text("disagreement", "summary"),
        densityLabel: text("disagreement", "density"),
        passLabel: text("disagreement", "pass"),
        passThreshold: 5,
        topThreshold: 7,
        xLabel: text("disagreement", "x"),
        yLabel: text("disagreement", "y"),
        compassTitle: text("disagreement", "compass"),
        primary: (entry) => entry.disagreement,
        x: (entry) => entry.localReview,
        y: (entry) => entry.llm,
        empty: text("disagreement", "empty"),
      },
    };
    return configs[lens] || lensConfig("overview", translate);
  }

  function entries(photos) {
    return (photos || []).map((photo, index) => {
      const recommendation = numericValue(photo.recommendation ?? photo.overall);
      const technical = photoTechnicalScore(photo);
      const aesthetic = photoAestheticScore(photo);
      const modelQuality = numericValue(photo.modelQualityScores?.clip_iqa_overall);
      const llm = photoLlmScore(photo);
      const localReview = photoLocalReviewScore(photo);
      const disagreement = photoDisagreementIndex(photo);
      return { photo, index, recommendation, technical, aesthetic, modelQuality, llm, localReview, disagreement };
    });
  }

  function stats(values) {
    const sorted = values.filter((value) => value != null).sort((a, b) => a - b);
    if (!sorted.length) return null;
    const total = sorted.length;
    return {
      total,
      average: sorted.reduce((sum, value) => sum + value, 0) / total,
      median: total % 2 ? sorted[Math.floor(total / 2)] : (sorted[Math.floor(total / 2) - 1] + sorted[Math.floor(total / 2)]) / 2,
      best: Math.max(...sorted),
      spread: Math.max(...sorted) - Math.min(...sorted),
    };
  }

  function svgNumber(value) {
    return Number(value).toFixed(2);
  }

  function smoothPath(points) {
    if (!points.length) return "";
    let path = `M ${svgNumber(points[0].x)} ${svgNumber(points[0].y)}`;
    for (let index = 0; index < points.length - 1; index += 1) {
      const p0 = points[index - 1] || points[index];
      const p1 = points[index];
      const p2 = points[index + 1];
      const p3 = points[index + 2] || p2;
      const cp1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 };
      const cp2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 };
      path += ` C ${svgNumber(cp1.x)} ${svgNumber(cp1.y)} ${svgNumber(cp2.x)} ${svgNumber(cp2.y)} ${svgNumber(p2.x)} ${svgNumber(p2.y)}`;
    }
    return path;
  }

  function scoreBuckets(values, bucketCount = 24) {
    const buckets = Array.from({ length: bucketCount }, (_, index) => ({
      min: (index / bucketCount) * 10,
      max: ((index + 1) / bucketCount) * 10,
      count: 0,
    }));
    values
      .map(numericValue)
      .filter((value) => value != null)
      .forEach((value) => {
        const bucketIndex = Math.min(Math.floor(clamp(value, 0, 9.999) / (10 / bucketCount)), bucketCount - 1);
        buckets[bucketIndex].count += 1;
      });
    return buckets;
  }

  function bucketWave(buckets, height = 38) {
    const maxCount = Math.max(1, ...buckets.map((bucket) => bucket.count));
    const points = buckets.map((bucket, index) => ({
      x: (index / Math.max(buckets.length - 1, 1)) * 100,
      y: height - 3 - (bucket.count / maxCount) * (height - 10),
    }));
    const path = smoothPath(points);
    const area = `${path} L 100 ${height - 2} L 0 ${height - 2} Z`;
    const peak = buckets.reduce((bestBucket, bucket) => (bucket.count > bestBucket.count ? bucket : bestBucket), buckets[0]);
    return { maxCount, points, path, area, peak };
  }

  function scoreMapDomain(values) {
    const sorted = values.map(numericValue).filter((value) => value != null).sort((a, b) => a - b);
    if (!sorted.length) return { min: 0, max: 10, zoomed: false };
    const rawMin = sorted[0];
    const rawMax = sorted[sorted.length - 1];
    const rawSpan = rawMax - rawMin;
    if (rawSpan >= 8.4) return { min: 0, max: 10, zoomed: false };
    const center = (rawMin + rawMax) / 2;
    const span = Math.max(rawSpan || 0.8, 1.4);
    const paddedSpan = Math.min(10, span * 1.28);
    let min = center - paddedSpan / 2;
    let max = center + paddedSpan / 2;
    if (min < 0) {
      max = Math.min(10, max - min);
      min = 0;
    }
    if (max > 10) {
      min = Math.max(0, min - (max - 10));
      max = 10;
    }
    if (max - min < 0.8) {
      min = Math.max(0, center - 0.4);
      max = Math.min(10, center + 0.4);
    }
    return { min, max, zoomed: min > 0.05 || max < 9.95 };
  }

  function scoreMapPercent(value, domain) {
    const numeric = numericValue(value);
    if (numeric == null) return null;
    return clamp(((numeric - domain.min) / Math.max(domain.max - domain.min, 0.01)) * 100, 0, 100);
  }

  function scoreMapGuidePercent(value, domain) {
    if (value < domain.min || value > domain.max) return null;
    return scoreMapPercent(value, domain);
  }

  function densityOverlayStyle(lens) {
    const styles = {
      overview: { color: "var(--gold)", fill: "rgba(var(--warning-rgb), 0.24)", glow: "rgba(var(--warning-rgb), 0.56)" },
      technical: { color: "var(--info)", fill: "rgba(var(--info-rgb), 0.22)", glow: "rgba(var(--info-rgb), 0.5)" },
      llm: { color: "var(--violet)", fill: "rgba(123, 97, 178, 0.22)", glow: "rgba(123, 97, 178, 0.5)" },
      aesthetic: { color: "var(--gold)", fill: "rgba(var(--gold-rgb), 0.22)", glow: "rgba(var(--gold-rgb), 0.52)" },
      disagreement: { color: "var(--reject)", fill: "rgba(var(--reject-rgb), 0.22)", glow: "rgba(var(--reject-rgb), 0.5)" },
    };
    return styles[lens] || styles.overview;
  }

  const dimensionPalette = ["var(--pick)", "var(--info)", "var(--hold)", "var(--reject)", "var(--violet)", "var(--selection)"];

  window.CulviaDistributionModel = {
    averageNumbers,
    bucketWave,
    clamp,
    densityOverlayStyle,
    dimensionPalette,
    entries,
    lensConfig,
    lensOptions,
    numericValue,
    scoreBuckets,
    scoreMapDomain,
    scoreMapGuidePercent,
    scoreMapPercent,
    smoothPath,
    stats,
    svgNumber,
    tier,
  };
})();
