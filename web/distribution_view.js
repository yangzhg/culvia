window.CulviaDistributionView = (() => {
  const distributionModel = window.CulviaDistributionModel;
  const {
    clamp,
    escapeHtml,
    iconMarkup,
    textHintAttributes,
  } = window.CulviaUiHelpers;
  const averageNumbers = distributionModel.averageNumbers;
  const bucketWave = distributionModel.bucketWave;
  const densityOverlayStyle = distributionModel.densityOverlayStyle;
  const dimensionPalette = distributionModel.dimensionPalette;
  const distributionLensOptions = distributionModel.lensOptions;
  const distributionStats = distributionModel.stats;
  const distributionTier = distributionModel.tier;
  const numericValue = distributionModel.numericValue;
  const scoreBuckets = distributionModel.scoreBuckets;
  const scoreMapDomain = distributionModel.scoreMapDomain;
  const scoreMapGuidePercent = distributionModel.scoreMapGuidePercent;
  const scoreMapPercent = distributionModel.scoreMapPercent;
  const smoothPath = distributionModel.smoothPath;
  const svgNumber = distributionModel.svgNumber;

  function t(key, params = {}) {
    const api = window.CulviaI18n;
    return api?.t ? api.t(key, params) : key;
  }

  function tr(key, params = {}, fallback = "") {
    const value = t(key, params);
    return value === key && fallback ? fallback : value;
  }

  function pathName(path) {
    const normalized = String(path || "").replaceAll("\\", "/").replace(/\/+$/, "");
    return normalized.split("/").filter(Boolean).pop() || normalized || t("common.unknown");
  }

  function scoreValue(value) {
    return value == null ? t("common.noData") : Number(value).toFixed(1);
  }

  function photoCountText(count) {
    const value = Number(count || 0);
    return tr("common.photoCount", { count: value }, `${value} 张`);
  }

  function distributionTierMeta(key, lens = "overview") {
    const meta = (lensKey, tierKey, label, range, icon, copy) => ({
      copy: tr(`distribution.tier.${lensKey}.${tierKey}.copy`, {}, copy),
      icon,
      label: tr(`distribution.tier.${lensKey}.${tierKey}.label`, {}, label),
      range: tr(`distribution.tier.${lensKey}.${tierKey}.range`, {}, range),
    });
    const maps = {
      overview: {
        elite: meta("overview", "elite", "精修候选", "8.0-10", "sparkle", "优先进入精修池"),
        strong: meta("overview", "strong", "稳妥保留", "7.0-7.9", "check", "适合二次挑选"),
        watch: meta("overview", "watch", "观察区", "6.0-6.9", "image", "看题材和情绪取舍"),
        quiet: meta("overview", "quiet", "低优先级", "0-5.9", "archive", "除非有特殊意义"),
      },
      technical: {
        elite: meta("technical", "elite", "技术优秀", "8.0-10", "check", "清晰、曝光和画面洁净度都更稳"),
        strong: meta("technical", "strong", "稳定可用", "7.0-7.9", "gauge", "技术上通常不用大幅补救"),
        watch: meta("technical", "watch", "需要复核", "6.0-6.9", "image", "建议放大检查清晰和曝光"),
        quiet: meta("technical", "quiet", "技术风险", "0-5.9", "archive", "优先确认失焦、过曝或噪点"),
      },
      llm: {
        elite: meta("llm", "elite", "强烈认可", "8.0-10", "brain", "大模型认为审美和完成度都突出"),
        strong: meta("llm", "strong", "建议保留", "7.0-7.9", "check", "适合进入人工二次判断"),
        watch: meta("llm", "watch", "可讨论", "6.0-6.9", "image", "可能需要依赖题材或情绪取舍"),
        quiet: meta("llm", "quiet", "低认可", "0-5.9", "archive", "大模型判断吸引力或技术完成度偏弱"),
      },
      aesthetic: {
        elite: meta("aesthetic", "elite", "审美突出", "8.0-10", "sparkle", "构图、光线、色彩整体更完整"),
        strong: meta("aesthetic", "strong", "审美稳定", "7.0-7.9", "check", "适合按题材和情绪继续挑"),
        watch: meta("aesthetic", "watch", "审美观察", "6.0-6.9", "image", "看是否有局部亮点值得保留"),
        quiet: meta("aesthetic", "quiet", "吸引力弱", "0-5.9", "archive", "可能缺少明确主体或画面张力"),
      },
      disagreement: {
        elite: meta("disagreement", "elite", "强分歧", "高", "brain", "大模型和本地评审差异明显，建议人工复核"),
        strong: meta("disagreement", "strong", "中分歧", "中", "gauge", "模型意见不完全一致，可抽查"),
        watch: meta("disagreement", "watch", "轻微分歧", "低", "image", "差异存在，但通常不影响排序"),
        quiet: meta("disagreement", "quiet", "意见接近", "稳", "check", "多路评审大体一致"),
      },
    };
    return maps[lens]?.[key] || maps.overview[key] || { label: t("common.noData"), range: "", icon: "image", copy: "" };
  }

  function distributionLensConfig(lens) {
    return distributionModel.lensConfig(lens, (key) => t(key));
  }

  function distributionLensMeta(lens, entries) {
    if (!entries.length) return t("distribution.lensMeta.empty");
    const config = distributionLensConfig(lens);
    const count = entries.filter((entry) => config.primary(entry) != null).length;
    if (!count) return t("distribution.lensMeta.noData");
    return t("distribution.lensMeta.count", { count });
  }

  function distributionEntries(photos = []) {
    return distributionModel.entries(photos || []);
  }

  function photoNodeTitle(entry, label = "分数") {
    return `${pathName(entry.photo.path)} · ${label} ${scoreValue(entry.score)}`;
  }

  const scoreMapPlotInset = {
    top: 14,
    right: 6,
    bottom: 15,
    left: 9,
  };

  function scoreMapPlotX(percent) {
    const plotWidth = 100 - scoreMapPlotInset.left - scoreMapPlotInset.right;
    return scoreMapPlotInset.left + (clamp(percent, 0, 100) / 100) * plotWidth;
  }

  function scoreMapPlotY(percent) {
    const plotHeight = 100 - scoreMapPlotInset.top - scoreMapPlotInset.bottom;
    return scoreMapPlotInset.top + ((100 - clamp(percent, 0, 100)) / 100) * plotHeight;
  }

  function renderScoreTerrain(entries, lens, config, buckets, wave) {
    const bucketTicks = buckets
      .map((bucket, index) => {
        const height = Math.max(5, (bucket.count / wave.maxCount) * 42);
        const tier = distributionTier((bucket.min + bucket.max) / 2, lens);
        const bucketTitle = t("distribution.bucketTitle", { min: bucket.min.toFixed(1), max: bucket.max.toFixed(1), count: bucket.count });
        return `
          <i
            class="score-volume-bar tone-${tier} ${bucket.count ? "has-data" : ""}"
            style="height:${height.toFixed(1)}%"
            data-ui-tooltip="${escapeHtml(bucketTitle)}"
          ></i>
        `;
      })
      .join("");
    const callouts = [...buckets]
      .filter((bucket) => bucket.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, 3)
      .sort((a, b) => a.min - b.min)
      .map((bucket) => {
        const left = ((bucket.min + bucket.max) / 2) * 10;
        const bucketTitle = t("distribution.bucketTitle", { min: bucket.min.toFixed(1), max: bucket.max.toFixed(1), count: bucket.count });
        return `
          <span
            class="terrain-callout"
            style="left:${left.toFixed(1)}%"
            data-ui-tooltip="${escapeHtml(bucketTitle)}"
          >
            <strong>${bucket.count}</strong>
            <small>${bucket.min.toFixed(1)}-${bucket.max.toFixed(1)}</small>
          </span>
        `;
      })
      .join("");
    return `
      <section class="spectrum-panel distribution-lab-panel score-terrain" aria-label="${escapeHtml(t("distribution.scoreDensityAria"))}">
        <div class="distribution-section-head">
          <span>${escapeHtml(config.densityLabel)}</span>
          <strong>${escapeHtml(config.passLabel)} · ${config.passThreshold.toFixed(1)}+</strong>
        </div>
        <div class="score-terrain-stage" style="--pass-left:${(config.passThreshold * 10).toFixed(1)}%; --top-left:${(config.topThreshold * 10).toFixed(1)}%">
          <div class="score-volume">${bucketTicks}</div>
          <svg viewBox="0 0 100 38" preserveAspectRatio="none" aria-hidden="true">
            <path class="terrain-area" d="${wave.area}"></path>
            <path class="terrain-line" d="${wave.path}"></path>
          </svg>
          <div class="terrain-callouts">${callouts}</div>
          <div class="terrain-threshold pass"><span>${escapeHtml(config.passLabel)}</span></div>
          <div class="terrain-threshold top"><span>${escapeHtml(t("distribution.priorityShort"))}</span></div>
        </div>
        <div class="spectrum-axis">
          <span>0</span>
          <span>2.5</span>
          <span>5</span>
          <span>7.5</span>
          <span>10</span>
        </div>
      </section>
    `;
  }

  function renderScoreMap(entries, lens, config) {
    const plotted = entries.filter((entry) => entry.x != null && entry.y != null);
    if (!plotted.length) {
      return `
        <section class="distribution-card score-map-card" aria-label="${escapeHtml(config.compassTitle)}">
          <div class="distribution-section-head">
            <span>${escapeHtml(t("distribution.mapKicker"))}</span>
            <strong>${escapeHtml(config.compassTitle)}</strong>
          </div>
          <div class="score-map-empty">${escapeHtml(t("distribution.mapEmpty"))}</div>
        </section>
      `;
    }
    const featured = new Set(
      [...plotted]
        .sort((a, b) => b.score - a.score)
        .slice(0, Math.min(6, plotted.length))
        .map((entry) => entry.index),
    );
    const xDomain = scoreMapDomain(plotted.map((entry) => entry.x));
    const yDomain = scoreMapDomain(plotted.map((entry) => entry.y));
    const xGuide = scoreMapGuidePercent(config.passThreshold, xDomain);
    const yGuide = scoreMapGuidePercent(config.passThreshold, yDomain);
    const heatColumns = 7;
    const heatRows = 7;
    const heatCells = Array.from({ length: heatColumns * heatRows }, () => ({ count: 0, scoreTotal: 0, xTotal: 0, yTotal: 0 }));
    plotted.forEach((entry) => {
      const xPercent = scoreMapPercent(entry.x, xDomain);
      const yPercent = scoreMapPercent(entry.y, yDomain);
      const column = Math.min(Math.floor(clamp(xPercent ?? 0, 0, 99.999) / 100 * heatColumns), heatColumns - 1);
      const row = Math.min(Math.floor(clamp(yPercent ?? 0, 0, 99.999) / 100 * heatRows), heatRows - 1);
      const cell = heatCells[row * heatColumns + column];
      cell.count += 1;
      cell.scoreTotal += entry.score;
      cell.xTotal += xPercent ?? 0;
      cell.yTotal += yPercent ?? 0;
    });
    const maxHeatCount = Math.max(1, ...heatCells.map((cell) => cell.count));
    const heatLayer = heatCells
      .map((cell) => {
        if (!cell.count) return "";
        const averageScore = cell.scoreTotal / cell.count;
        const left = scoreMapPlotX(cell.xTotal / cell.count);
        const top = scoreMapPlotY(cell.yTotal / cell.count);
        const heat = cell.count / maxHeatCount;
        const size = 118 + heat * 142;
        const opacity = 0.18 + heat * 0.46;
        return `
          <span
            class="score-map-heat-spot tone-${distributionTier(averageScore, lens)}"
            style="left:${left.toFixed(2)}%; top:${top.toFixed(2)}%; --heat-size:${size.toFixed(1)}px; --heat-opacity:${opacity.toFixed(2)}"
            data-ui-tooltip="${escapeHtml(t("distribution.heatTitle", { count: cell.count, average: scoreValue(averageScore) }))}"
          ></span>
        `;
      })
      .join("");
    const sampled = plotted.length > 180 ? plotted.filter((entry, index) => featured.has(entry.index) || index % Math.ceil(plotted.length / 180) === 0) : plotted;
    const points = sampled
      .map((entry) => {
        const tier = distributionTier(entry.score, lens);
        const left = scoreMapPlotX(scoreMapPercent(entry.x, xDomain) ?? 0);
        const top = scoreMapPlotY(scoreMapPercent(entry.y, yDomain) ?? 0);
        const size = 5 + clamp(entry.score / 10, 0, 1) * 10;
        const isFeatured = featured.has(entry.index);
        const pointTitle = `${pathName(entry.photo.path)} · ${config.xLabel} ${scoreValue(entry.x)} · ${config.yLabel} ${scoreValue(entry.y)}`;
        return `
          <button
            class="score-map-point tone-${tier} ${isFeatured ? "is-featured" : ""}"
            type="button"
            data-photo-index="${entry.index}"
            aria-label="${escapeHtml(pointTitle)}"
            data-ui-tooltip="${escapeHtml(pointTitle)}"
            style="left:${left.toFixed(2)}%; top:${top.toFixed(2)}%; --point-size:${size.toFixed(1)}px; --point-alpha:${(0.22 + clamp(entry.score / 10, 0, 1) * 0.42).toFixed(2)}"
          >
            ${isFeatured ? `<img src="${entry.photo.thumb}" alt="${escapeHtml(t("distribution.thumbAlt"))}" loading="lazy" />` : ""}
            <span>${scoreValue(entry.score)}</span>
          </button>
        `;
      })
      .join("");
    return `
      <section class="distribution-card score-map-card" aria-label="${escapeHtml(config.compassTitle)}">
        <div class="distribution-section-head">
          <span>${escapeHtml(t("distribution.mapKicker"))}</span>
          <strong>${escapeHtml(config.compassTitle)}</strong>
        </div>
        <div
          class="score-map ${xDomain.zoomed ? "is-x-zoomed" : ""} ${yDomain.zoomed ? "is-y-zoomed" : ""}"
          style="--x-min-label:'${xDomain.min.toFixed(1)}'; --x-max-label:'${xDomain.max.toFixed(1)}'; --y-min-label:'${yDomain.min.toFixed(1)}'; --y-max-label:'${yDomain.max.toFixed(1)}'"
        >
          <div class="score-map-heat" aria-hidden="true">${heatLayer}</div>
          <div class="score-map-axis x-axis" aria-hidden="true"></div>
          <div class="score-map-axis y-axis" aria-hidden="true"></div>
          ${yGuide == null ? "" : `<div class="score-map-guide horizontal" style="top:${scoreMapPlotY(yGuide).toFixed(2)}%"></div>`}
          ${xGuide == null ? "" : `<div class="score-map-guide vertical" style="left:${scoreMapPlotX(xGuide).toFixed(2)}%"></div>`}
          <span class="score-map-label top">${escapeHtml(config.yLabel)}</span>
          <span class="score-map-label right">${escapeHtml(config.xLabel)}</span>
          ${points}
          <div class="score-map-legend" aria-hidden="true">
            <span>${escapeHtml(t("distribution.scoreMapping"))}</span>
            <i></i>
            <small>${escapeHtml(t("distribution.low"))}</small>
            <small>${escapeHtml(t("distribution.high"))}</small>
          </div>
        </div>
      </section>
    `;
  }

  function distributionText(key, fallback, params = {}) {
    return tr(`distribution.${key}`, params, fallback);
  }

  function distributionMetricLabel(key) {
    return distributionText(`metric.${key}.label`, key);
  }

  function distributionMetricAxis(key) {
    return distributionText(`metric.${key}.axis`, distributionMetricLabel(key));
  }

  function radarMetricDefinitions() {
    return [
      { key: "recommendation", getter: (_photo, entry) => entry.recommendation },
      { key: "aestheticOverall", getter: (_photo, entry) => entry.aesthetic },
      { key: "technicalQc", getter: (_photo, entry) => entry.technical },
      { key: "modelQuality", getter: (_photo, entry) => entry.modelQuality },
      { key: "composition", getter: (photo) => photo.llmReviewScores?.llm_composition ?? photo.scores?.composition },
      { key: "light", getter: (photo) => photo.llmReviewScores?.llm_lighting ?? photo.scores?.lighting },
      { key: "color", getter: (photo) => photo.scores?.color },
      { key: "llmOverall", getter: (_photo, entry) => entry.llm },
      { key: "llmAesthetic", getter: (photo) => photo.llmReviewScores?.llm_aesthetic_overall },
      { key: "llmTechnical", getter: (photo) => photo.llmReviewScores?.llm_technical_overall },
      { key: "consistency", getter: (_photo, entry) => (entry.disagreement == null ? null : 10 - entry.disagreement) },
    ];
  }

  function radarPoint(index, total, value, radius = 36, center = 50) {
    const angle = -Math.PI / 2 + (index / Math.max(total, 1)) * Math.PI * 2;
    const normalized = clamp((numericValue(value) ?? 0) / 10, 0, 1);
    return {
      x: center + Math.cos(angle) * radius * normalized,
      y: center + Math.sin(angle) * radius * normalized,
    };
  }

  function radarAxisPoint(index, total, radius = 42, center = 50) {
    const angle = -Math.PI / 2 + (index / Math.max(total, 1)) * Math.PI * 2;
    return {
      x: center + Math.cos(angle) * radius,
      y: center + Math.sin(angle) * radius,
    };
  }

  function radarPolygon(points) {
    return points.map((point) => `${svgNumber(point.x)},${svgNumber(point.y)}`).join(" ");
  }

  function metricAverage(entries, getter) {
    return averageNumbers(entries.map((entry) => getter(entry.photo, entry)));
  }

  function radarPriorityScore(entry) {
    return (
      numericValue(entry.recommendation) ??
      numericValue(entry.localReview) ??
      averageNumbers([entry.aesthetic, entry.technical, entry.llm])
    );
  }

  function renderMetricRadar(entries) {
    const scoredEntries = entries
      .map((entry) => ({ ...entry, radarPriority: radarPriorityScore(entry) }))
      .filter((entry) => entry.radarPriority != null);
    const priorityEntries = scoredEntries.filter((entry) => entry.radarPriority >= 8);
    const fallbackCount = Math.max(3, Math.ceil(entries.length * 0.18));
    const priorityPool =
      priorityEntries.length >= 3
        ? priorityEntries
        : [...scoredEntries].sort((a, b) => (b.radarPriority ?? 0) - (a.radarPriority ?? 0)).slice(0, fallbackCount);
    const metrics = radarMetricDefinitions()
      .map((definition) => {
        const average = metricAverage(entries, definition.getter);
        if (average == null) return null;
        return {
          ...definition,
          label: distributionMetricLabel(definition.key),
          axis: distributionMetricAxis(definition.key),
          average,
          priorityAverage: metricAverage(priorityPool, definition.getter) ?? average,
          count: entries.filter((entry) => numericValue(definition.getter(entry.photo, entry)) != null).length,
        };
      })
      .filter(Boolean);

    if (metrics.length < 3) {
      return `
        <section class="distribution-card radar-card is-global is-empty" aria-label="${escapeHtml(t("distribution.radarAria"))}">
          <div class="distribution-section-head">
            <span>${escapeHtml(t("distribution.radarKicker"))}</span>
            <strong>${escapeHtml(t("distribution.radarInsufficient"))}</strong>
          </div>
          <div class="radar-empty">${escapeHtml(t("distribution.radarEmpty"))}</div>
        </section>
      `;
    }

    const total = metrics.length;
    const rings = [2, 4, 6, 8, 10]
      .map((value) => {
        const points = metrics.map((_, index) => radarPoint(index, total, value, 36));
        return `<polygon class="radar-ring" points="${radarPolygon(points)}"></polygon>`;
      })
      .join("");
    const axes = metrics
      .map((metric, index) => {
        const end = radarAxisPoint(index, total, 37);
        const label = radarAxisPoint(index, total, 44);
        return `
          <line class="radar-axis" x1="50" y1="50" x2="${svgNumber(end.x)}" y2="${svgNumber(end.y)}"></line>
          <text class="radar-axis-label" x="${svgNumber(label.x)}" y="${svgNumber(label.y)}">${escapeHtml(metric.axis)}</text>
        `;
      })
      .join("");
    const averagePoints = metrics.map((metric, index) => radarPoint(index, total, metric.average, 36));
    const priorityPoints = metrics.map((metric, index) => radarPoint(index, total, metric.priorityAverage, 36));
    const dots = metrics
      .map((metric, index) => {
        const point = averagePoints[index];
        return `<circle class="radar-dot" cx="${svgNumber(point.x)}" cy="${svgNumber(point.y)}" r="1.35"><title>${escapeHtml(`${metric.label} ${scoreValue(metric.average)}`)}</title></circle>`;
      })
      .join("");
    const metricRows = metrics
      .map(
        (metric) => `
          <div class="radar-metric-row">
            <span${textHintAttributes(metric.label)}>${escapeHtml(metric.label)}</span>
            <strong>${scoreValue(metric.average)}</strong>
            <i style="width:${clamp(metric.average * 10, 0, 100).toFixed(1)}%"></i>
            <small${textHintAttributes(t("distribution.radarPriorityMeta", { score: scoreValue(metric.priorityAverage), count: metric.count }))}>${escapeHtml(t("distribution.radarPriorityMeta", { score: scoreValue(metric.priorityAverage), count: metric.count }))}</small>
          </div>
        `,
      )
      .join("");

    return `
      <section class="distribution-card radar-card is-global" aria-label="${escapeHtml(t("distribution.radarAria"))}">
        <div class="distribution-section-head">
          <span>${escapeHtml(t("distribution.radarKicker"))}</span>
          <strong>${escapeHtml(t("distribution.radarCurrent", { count: metrics.length }))}</strong>
        </div>
        <div class="radar-layout">
          <div class="radar-stage">
            <svg viewBox="0 0 100 100" aria-hidden="true">
              ${rings}
              ${axes}
              <polygon class="radar-priority-shape" points="${radarPolygon(priorityPoints)}"></polygon>
              <polygon class="radar-average-shape" points="${radarPolygon(averagePoints)}"></polygon>
              <polyline class="radar-average-line" points="${radarPolygon(averagePoints)} ${svgNumber(averagePoints[0].x)},${svgNumber(averagePoints[0].y)}"></polyline>
              ${dots}
            </svg>
          </div>
          <div class="radar-side">
            <div class="radar-legend">
              <span><i class="average"></i>${escapeHtml(t("distribution.radarCurrentDisplay"))}</span>
              <span><i class="priority"></i>${escapeHtml(t("distribution.priorityZone"))}</span>
            </div>
            <div class="radar-metrics">${metricRows}</div>
          </div>
        </div>
      </section>
    `;
  }

  function dimensionCard(label, value, meta = "", display = "") {
    const numeric = numericValue(value);
    const width = numeric == null ? 0 : clamp(numeric / 10, 0, 1) * 100;
    return `
      <article class="dimension-card">
        <span${textHintAttributes(label)}>${escapeHtml(label)}</span>
        <strong>${escapeHtml(display || scoreValue(numeric))}</strong>
        <div class="dimension-meter"><i style="width:${width.toFixed(1)}%"></i></div>
        <small${textHintAttributes(meta || t("distribution.currentAverage"))}>${escapeHtml(meta || t("distribution.currentAverage"))}</small>
      </article>
    `;
  }

  function dimensionRidgeCard(label, values, meta = t("distribution.currentDistribution"), display = "") {
    const numericValues = values.map(numericValue).filter((value) => value != null);
    const stats = distributionStats(numericValues);
    const buckets = scoreBuckets(numericValues, 18);
    const wave = bucketWave(buckets, 32);
    const average = stats?.average ?? null;
    const markerLeft = average == null ? 0 : clamp(average * 10, 0, 100);
    return `
      <article class="dimension-card dimension-ridge ${stats ? "" : "is-empty"}">
        <div class="dimension-ridge-head">
          <span${textHintAttributes(label)}>${escapeHtml(label)}</span>
          <strong>${escapeHtml(display || scoreValue(average))}</strong>
        </div>
        <div class="dimension-ridge-wave" style="--marker-left:${markerLeft.toFixed(1)}%">
          <svg viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
            <path d="${wave.area}"></path>
            <path d="${wave.path}"></path>
          </svg>
          <i></i>
        </div>
        <small${textHintAttributes(stats ? t("distribution.dimensionMeta", { meta, count: numericValues.length }) : t("distribution.noData"))}>${escapeHtml(stats ? t("distribution.dimensionMeta", { meta, count: numericValues.length }) : t("distribution.noData"))}</small>
      </article>
    `;
  }

  function dimensionStackSeries(lens, entries) {
    const seriesMaps = {
      overview: [
        ["recommendation", (_photo, entry) => entry.recommendation],
        ["technicalQc", (_photo, entry) => entry.technical],
        ["aestheticReference", (photo) => photo.aestheticReferenceScores?.clip_aesthetic],
        ["llmOverall", (_photo, entry) => entry.llm],
      ],
      technical: [
        ["sharpness", (photo) => photo.technicalScores?.sharpness],
        ["exposure", (photo) => photo.technicalScores?.exposure],
        ["tonalRange", (photo) => photo.technicalScores?.contrast],
        ["cleanliness", (photo) => photo.technicalScores?.cleanliness],
        ["modelQuality", (photo) => photo.modelQualityScores?.clip_iqa_overall],
      ],
      llm: [
        ["aestheticOverall", (photo) => photo.llmReviewScores?.llm_aesthetic_overall],
        ["llmTechnical", (photo) => photo.llmReviewScores?.llm_technical_overall],
        ["composition", (photo) => photo.llmReviewScores?.llm_composition],
        ["light", (photo) => photo.llmReviewScores?.llm_lighting],
        ["content", (photo) => photo.llmReviewScores?.llm_content],
      ],
      aesthetic: [
        ["quality", (photo) => photo.scores?.quality],
        ["composition", (photo) => photo.scores?.composition],
        ["light", (photo) => photo.scores?.lighting],
        ["color", (photo) => photo.scores?.color],
        ["depth", (photo) => photo.scores?.depth_of_field],
        ["content", (photo) => photo.scores?.content],
      ],
      disagreement: [
        ["localOverall", (_photo, entry) => entry.localReview],
        ["llmOverall", (_photo, entry) => entry.llm],
        ["disagreement", (_photo, entry) => entry.disagreement],
      ],
    };
    return (seriesMaps[lens] || seriesMaps.overview)
      .map(([key, getter]) => {
        const values = entries.map((entry) => numericValue(getter(entry.photo, entry))).filter((value) => value != null);
        return { label: distributionMetricLabel(key), getter, values, average: averageNumbers(values) };
      })
      .filter((series) => series.values.length);
  }

  function dimensionStackAreaPath(topPoints, bottomPoints) {
    if (!topPoints.length || !bottomPoints.length) return "";
    const bottom = [...bottomPoints].reverse();
    const bottomLine = bottom.map((point) => `L ${svgNumber(point.x)} ${svgNumber(point.y)}`).join(" ");
    return `${smoothPath(topPoints)} ${bottomLine} Z`;
  }

  function renderDimensionStack(lens, entries, config) {
    const series = dimensionStackSeries(lens, entries);
    if (!series.length) return "";
    const bucketCount = Math.min(28, Math.max(12, Math.ceil(entries.length / 5)));
    const buckets = Array.from({ length: bucketCount }, (_, index) => ({
      min: (index / bucketCount) * 10,
      max: ((index + 1) / bucketCount) * 10,
      entries: [],
    }));
    entries.forEach((entry) => {
      const score = numericValue(entry.score);
      if (score == null) return;
      const bucketIndex = Math.min(Math.floor(clamp(score, 0, 9.999) / (10 / bucketCount)), bucketCount - 1);
      buckets[bucketIndex].entries.push(entry);
    });
    const stackRows = buckets.map((bucket) =>
      series.map((item) => averageNumbers(bucket.entries.map((entry) => item.getter(entry.photo, entry))) ?? 0),
    );
    const maxTotal = Math.max(1, ...stackRows.map((row) => row.reduce((sum, value) => sum + value, 0)));
    const palette = dimensionPalette;
    const baseY = 92;
    const chartHeight = 78;
    const maxDensityCount = Math.max(1, ...buckets.map((bucket) => bucket.entries.length));
    const densityPoints = buckets.map((bucket, index) => ({
      x: (index / Math.max(buckets.length - 1, 1)) * 100,
      y: baseY - (bucket.entries.length / maxDensityCount) * (chartHeight * 0.88),
    }));
    const densityPath = smoothPath(densityPoints);
    const densityArea = `${densityPath} L 100 ${baseY} L 0 ${baseY} Z`;
    const densityStyle = densityOverlayStyle(lens);
    const densityCss = `--density-color:${densityStyle.color}; --density-fill:${densityStyle.fill}; --density-glow:${densityStyle.glow}`;
    const layers = series.map((item, seriesIndex) => {
      const topPoints = stackRows.map((row, rowIndex) => {
        const lower = row.slice(0, seriesIndex).reduce((sum, value) => sum + value, 0);
        const upper = lower + row[seriesIndex];
        return {
          x: (rowIndex / Math.max(stackRows.length - 1, 1)) * 100,
          y: baseY - (upper / maxTotal) * chartHeight,
        };
      });
      const bottomPoints = stackRows.map((row, rowIndex) => {
        const lower = row.slice(0, seriesIndex).reduce((sum, value) => sum + value, 0);
        return {
          x: (rowIndex / Math.max(stackRows.length - 1, 1)) * 100,
          y: baseY - (lower / maxTotal) * chartHeight,
        };
      });
      return {
        ...item,
        color: palette[seriesIndex % palette.length],
        path: dimensionStackAreaPath(topPoints, bottomPoints),
      };
    });
    const topLinePoints = stackRows.map((row, rowIndex) => ({
      x: (rowIndex / Math.max(stackRows.length - 1, 1)) * 100,
      y: baseY - (row.reduce((sum, value) => sum + value, 0) / maxTotal) * chartHeight,
    }));
    const gradientId = (index) => `dimensionStackGradient-${lens}-${index}`;
    const defs = layers
      .map(
        (layer, index) => `
          <linearGradient id="${gradientId(index)}" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="${layer.color}" stop-opacity="0.9"></stop>
            <stop offset="100%" stop-color="${layer.color}" stop-opacity="0.46"></stop>
          </linearGradient>
        `,
      )
      .join("");
    const paths = layers
      .map(
        (layer, index) => `
          <path
            class="dimension-stack-area"
            d="${layer.path}"
            fill="url(#${gradientId(index)})"
            style="--layer-color:${layer.color}"
          ></path>
        `,
      )
      .join("");
    const densityOverlay = `
      <path class="score-density-area" d="${densityArea}" style="${densityCss}"></path>
      <path class="score-density-line" d="${densityPath}" style="${densityCss}"></path>
    `;
    const legend = layers
      .map(
        (layer) => `
          <span class="dimension-stack-legend-item" style="--legend-color:${layer.color}">
            <i></i>
            <strong${textHintAttributes(layer.label)}>${escapeHtml(layer.label)}</strong>
            <small>${scoreValue(layer.average)}</small>
          </span>
        `,
      )
      .join("");
    const densityLegend = `
      <span class="dimension-stack-legend-item is-density" style="--legend-color:${densityStyle.color}; ${densityCss}">
        <i></i>
        <strong${textHintAttributes(config.densityLabel)}>${escapeHtml(config.densityLabel)}</strong>
        <small>${escapeHtml(photoCountText(entries.length))}</small>
      </span>
    `;
    return `
      <section class="distribution-card dimension-stack-card has-density-overlay" aria-label="${escapeHtml(t("distribution.stackAria"))}">
        <div class="distribution-section-head">
          <span>${escapeHtml(t("distribution.stackKicker"))}</span>
          <strong>${escapeHtml(t("distribution.stackTitle", { density: config.densityLabel }))}</strong>
        </div>
        <div class="dimension-stack-chart">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <defs>${defs}</defs>
            ${paths}
            <path class="dimension-stack-ridge" d="${smoothPath(topLinePoints)}"></path>
            ${densityOverlay}
          </svg>
          <div class="dimension-stack-axis">
            <span>${escapeHtml(t("distribution.lowScoreBand"))}</span>
            <span>${escapeHtml(t("distribution.highScoreBand"))}</span>
          </div>
        </div>
        <div class="dimension-stack-legend">${legend}${densityLegend}</div>
      </section>
    `;
  }

  function renderDimensionCards(lens, entries, totalVisible) {
    const fieldValues = (getter) => entries.map((entry) => getter(entry.photo, entry)).filter((value) => numericValue(value) != null);
    const llmCount = entries.filter((entry) => entry.llm != null).length;
    const fieldSets = {
      overview: [
        [distributionMetricLabel("recommendation"), fieldValues((_photo, entry) => entry.recommendation)],
        [distributionMetricLabel("technicalAverage"), fieldValues((_photo, entry) => entry.technical)],
        [distributionMetricLabel("aestheticReference"), fieldValues((photo) => photo.aestheticReferenceScores?.clip_aesthetic)],
        [
          distributionMetricLabel("llmCoverage"),
          entries.map((entry) => (entry.llm != null ? 10 : 0)),
          t("distribution.llmCoveragePercent", { percent: Math.round((llmCount / Math.max(totalVisible, 1)) * 100) }),
          `${llmCount}/${totalVisible}`,
        ],
      ],
      technical: [
        [distributionMetricLabel("sharpness"), fieldValues((photo) => photo.technicalScores?.sharpness)],
        [distributionMetricLabel("exposure"), fieldValues((photo) => photo.technicalScores?.exposure)],
        [distributionMetricLabel("tonalRange"), fieldValues((photo) => photo.technicalScores?.contrast)],
        [distributionMetricLabel("cleanliness"), fieldValues((photo) => photo.technicalScores?.cleanliness)],
        [distributionMetricLabel("modelQuality"), fieldValues((photo) => photo.modelQualityScores?.clip_iqa_overall)],
      ],
      llm: [
        [distributionMetricLabel("overall"), fieldValues((photo) => photo.llmReviewScores?.llm_review_overall)],
        [distributionMetricLabel("aestheticOverall"), fieldValues((photo) => photo.llmReviewScores?.llm_aesthetic_overall)],
        [distributionMetricLabel("llmTechnical"), fieldValues((photo) => photo.llmReviewScores?.llm_technical_overall)],
        [distributionMetricLabel("composition"), fieldValues((photo) => photo.llmReviewScores?.llm_composition)],
        [distributionMetricLabel("light"), fieldValues((photo) => photo.llmReviewScores?.llm_lighting)],
        [distributionMetricLabel("content"), fieldValues((photo) => photo.llmReviewScores?.llm_content)],
      ],
      aesthetic: [
        [distributionMetricLabel("quality"), fieldValues((photo) => photo.scores?.quality)],
        [distributionMetricLabel("composition"), fieldValues((photo) => photo.scores?.composition)],
        [distributionMetricLabel("light"), fieldValues((photo) => photo.scores?.lighting)],
        [distributionMetricLabel("color"), fieldValues((photo) => photo.scores?.color)],
        [distributionMetricLabel("depth"), fieldValues((photo) => photo.scores?.depth_of_field)],
        [distributionMetricLabel("content"), fieldValues((photo) => photo.scores?.content)],
      ],
      disagreement: [
        [distributionMetricLabel("localOverall"), fieldValues((_photo, entry) => entry.localReview)],
        [distributionMetricLabel("llmOverall"), fieldValues((_photo, entry) => entry.llm)],
        [distributionMetricLabel("disagreement"), fieldValues((_photo, entry) => entry.disagreement), t("distribution.disagreementHigherRisk")],
        [
          distributionMetricLabel("strongDisagreement"),
          entries.map((entry) => (entry.disagreement != null && entry.disagreement >= 7 ? 10 : 0)),
          t("distribution.currentLensRatio"),
          photoCountText(entries.filter((entry) => entry.disagreement != null && entry.disagreement >= 7).length),
        ],
      ],
    };
    return (fieldSets[lens] || fieldSets.overview).map((item) => dimensionRidgeCard(...item)).join("");
  }

  function distributionDecision(lens, entries, allEntries, config, stats, passCount, topCount, peakLabel) {
    const total = entries.length;
    const llmCoverage = allEntries.filter((entry) => entry.llm != null).length;
    const passRatio = Math.round((passCount / Math.max(total, 1)) * 100);
    const topRatio = Math.round((topCount / Math.max(total, 1)) * 100);
    const riskCount = entries.filter((entry) => entry.score < config.passThreshold).length;
    const spreadText = stats.spread >= 2.8 ? t("distribution.clearSpread") : t("distribution.stableSpread");
    const copyByLens = {
      overview: {
        title: t("distribution.decision.overview.title"),
        body: t("distribution.decision.overview.body", { risk: riskCount, top: topCount }),
        actions: [
          ["gallery", "layoutGrid", t("distribution.goGallery")],
          ["export", "check", t("distribution.viewPicks")],
        ],
      },
      technical: {
        title: t("distribution.decision.technical.title"),
        body: t("distribution.decision.technical.body", { risk: riskCount }),
        actions: [
          ["gallery", "layoutGrid", t("distribution.goGallery")],
          ["overview", "barChart", t("distribution.viewRecommendation")],
        ],
      },
      llm: {
        title: llmCoverage < allEntries.length ? t("distribution.decision.llm.titleCoverage") : t("distribution.decision.llm.titleReady"),
        body: t("distribution.decision.llm.body", { covered: llmCoverage, total: allEntries.length }),
        actions: [
          ["gallery", "layoutGrid", t("distribution.goGallery")],
          ["disagreement", "gitCompare", t("distribution.viewDisagreement")],
        ],
      },
      aesthetic: {
        title: t("distribution.decision.aesthetic.title"),
        body: t("distribution.decision.aesthetic.body", { top: topCount }),
        actions: [
          ["gallery", "layoutGrid", t("distribution.goGallery")],
          ["technical", "gauge", t("distribution.viewTechnical")],
        ],
      },
      disagreement: {
        title: t("distribution.decision.disagreement.title"),
        body: t("distribution.decision.disagreement.body", { top: topCount }),
        actions: [
          ["gallery", "layoutGrid", t("distribution.goGallery")],
          ["llm", "brain", t("distribution.viewLlm")],
        ],
      },
    };
    const decision = copyByLens[lens] || copyByLens.overview;
    const priorityLabel = lens === "disagreement" ? t("distribution.strongDisagreement") : t("distribution.priorityZone");
    const metricCards = [
      [priorityLabel, `${topCount}`, `${topRatio}%`],
      [config.passLabel, `${passCount}`, `${passRatio}%`],
      [config.summaryLabel, scoreValue(stats.average), t("distribution.peak", { peak: peakLabel })],
      [t("distribution.coverage"), `${entries.length}/${allEntries.length}`, llmCoverage ? t("distribution.llmCoverage", { count: llmCoverage }) : spreadText],
    ]
      .map(
        ([label, value, meta]) => `
          <article class="decision-metric">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
            <small>${escapeHtml(meta)}</small>
          </article>
        `,
      )
      .join("");
    const actions = decision.actions
      .map(
        ([action, icon, label]) => `
          <button class="decision-action" type="button" data-distribution-action="${escapeHtml(action)}"${textHintAttributes(label)}>
            ${iconMarkup(icon)}
            <span>${escapeHtml(label)}</span>
          </button>
        `,
      )
      .join("");
    return `
      <section class="distribution-decision-panel" aria-label="${escapeHtml(t("distribution.decisionAria"))}">
        <div class="decision-copy">
          <span>${escapeHtml(t("distribution.nextStep"))}</span>
          <strong>${escapeHtml(decision.title)}</strong>
          <p>${escapeHtml(decision.body)}</p>
          <div class="decision-actions">${actions}</div>
        </div>
        <div class="decision-metrics">${metricCards}</div>
      </section>
    `;
  }

  return {
    distributionDecision,
    distributionEntries,
    distributionLensConfig,
    distributionLensMeta,
    distributionMetricAxis,
    distributionMetricLabel,
    distributionTierMeta,
    renderDimensionCards,
    renderDimensionStack,
    renderMetricRadar,
    renderScoreMap,
    renderScoreTerrain,
  };
})();
