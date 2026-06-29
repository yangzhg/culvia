window.CulviaDistributionPanel = (() => {
  function create({
    $,
    t,
    tr,
    escapeHtml,
    iconMarkup,
    scoreValue,
    pathName,
    photos,
    switchView,
    openViewerAt,
    distributionLensOptions,
    distributionStats,
    distributionTier,
    scoreBuckets,
    bucketWave,
    distributionDecision,
    distributionEntries,
    distributionLensConfig,
    distributionLensMeta,
    distributionTierMeta,
    renderDimensionStack,
    renderMetricRadar,
  }) {
    let distributionLens = "overview";

    function renderDistribution() {
      const container = $("#distributionChart");
      if (!container) return;
      const lens = distributionLensOptions.some((option) => option.value === distributionLens) ? distributionLens : "overview";
      const config = distributionLensConfig(lens);
      const allEntries = distributionEntries(photos());
      const entries = allEntries
        .map((entry) => ({ ...entry, score: config.primary(entry), x: config.x(entry), y: config.y(entry) }))
        .filter((entry) => entry.score != null);
      container.className = `distribution-studio lens-${lens}`;

      const lensControls = `
        <div class="distribution-lenses" role="tablist" aria-label="${escapeHtml(t("distribution.lensAria"))}">
          ${distributionLensOptions
            .map((option) => {
              const label = tr(option.labelKey, {}, option.label);
              const meta = distributionLensMeta(option.value, allEntries);
              return `
                <button
                  class="distribution-lens ${option.value === lens ? "is-active" : ""}"
                  type="button"
                  role="tab"
                  aria-selected="${option.value === lens ? "true" : "false"}"
                  data-distribution-lens="${option.value}"
                  data-ui-tooltip="${escapeHtml(`${label} · ${meta}`)}"
                >
                  <span class="distribution-lens-icon">${iconMarkup(option.icon)}</span>
                  <span class="distribution-lens-copy">
                    <strong>${escapeHtml(label)}</strong>
                    <small>${escapeHtml(meta)}</small>
                  </span>
                </button>
              `;
            })
            .join("")}
        </div>
      `;

      if (!entries.length) {
        container.innerHTML = `
          ${renderMetricRadar(allEntries)}
          <div class="distribution-view-layout" aria-label="${escapeHtml(t("distribution.layoutAria"))}">
            ${lensControls}
            <section class="distribution-view-content" aria-label="${escapeHtml(t("distribution.contentAria"))}">
              <div class="distribution-empty is-compact">
                <div class="empty-symbol">${iconMarkup("barChart", "empty-icon")}</div>
                <h2>${escapeHtml(config.empty)}</h2>
                <p>${escapeHtml(t("distribution.switchHint"))}</p>
              </div>
            </section>
          </div>
        `;
        bindDistributionControls(container);
        return;
      }

      const values = entries.map((entry) => entry.score);
      const stats = distributionStats(values);
      const total = entries.length;
      const passCount = entries.filter((entry) => entry.score >= config.passThreshold).length;
      const topCount = entries.filter((entry) => entry.score >= config.topThreshold).length;
      const buckets = scoreBuckets(values, 24);
      const wave = bucketWave(buckets, 38);
      const peakBucket = wave.peak;
      const peakLabel = `${peakBucket.min.toFixed(1)}-${peakBucket.max.toFixed(1)}`;
      const topRatio = Math.round((topCount / total) * 100);

      const tierKeys = ["elite", "strong", "watch", "quiet"];
      const tiers = tierKeys
        .map((key) => {
          const meta = distributionTierMeta(key, lens);
          const items = entries.filter((entry) => distributionTier(entry.score, lens) === key).sort((a, b) => b.score - a.score);
          const ratio = Math.round((items.length / total) * 100);
          const previews = items.length
            ? items
                .slice(0, 4)
                .map(
                  (entry) => `
                    <button class="tier-thumb" type="button" data-photo-index="${entry.index}" aria-label="${escapeHtml(pathName(entry.photo.path))}" data-ui-tooltip="${escapeHtml(pathName(entry.photo.path))}">
                      <img src="${entry.photo.thumb}" alt="${escapeHtml(t("distribution.thumbAlt"))}" loading="lazy" />
                      <span>${scoreValue(entry.score)}</span>
                    </button>
                  `,
                )
                .join("")
            : `<div class="tier-empty">${escapeHtml(t("distribution.empty"))}</div>`;
          return `
            <article class="distribution-tier tone-${key}">
              <div class="tier-head">
                <span>${iconMarkup(meta.icon)}</span>
                <div>
                  <strong>${meta.label}</strong>
                  <small>${meta.range}</small>
                </div>
              </div>
              <div class="tier-count">
                <strong>${items.length}</strong>
                <span>${ratio}%</span>
              </div>
              <div class="tier-thumbs">${previews}</div>
              <p>${meta.copy}</p>
            </article>
          `;
        })
        .join("");

      container.innerHTML = `
        ${renderMetricRadar(allEntries)}

        <div class="distribution-view-layout" aria-label="${escapeHtml(t("distribution.layoutAria"))}">
          ${lensControls}
          <section class="distribution-view-content" aria-label="${escapeHtml(t("distribution.contentAria"))}">
            <div class="distribution-head is-compact">
              <div>
                <div class="section-kicker">${escapeHtml(config.kicker)}</div>
                <h2>${escapeHtml(config.title)}</h2>
                <p>${escapeHtml(t("distribution.viewSummary", { peak: peakLabel, ratio: topRatio, total }))}</p>
              </div>
              <div class="distribution-score">
                <span>${escapeHtml(config.summaryLabel)}</span>
                <strong>${scoreValue(stats.average)}</strong>
                <small>${escapeHtml(t("distribution.medianBest", { best: scoreValue(stats.best), median: scoreValue(stats.median) }))}</small>
              </div>
            </div>

            ${distributionDecision(lens, entries, allEntries, config, stats, passCount, topCount, peakLabel)}
            ${renderDimensionStack(lens, entries, config)}

            <section class="tier-board" aria-label="${escapeHtml(t("distribution.tierAria"))}">
              ${tiers}
            </section>
          </section>
        </div>
      `;

      bindDistributionControls(container);
    }

    function bindDistributionControls(container) {
      container.querySelectorAll("[data-distribution-lens]").forEach((button) => {
        button.addEventListener("click", () => {
          distributionLens = button.dataset.distributionLens || "overview";
          renderDistribution();
        });
      });
      container.querySelectorAll("[data-distribution-action]").forEach((button) => {
        button.addEventListener("click", () => {
          const action = button.dataset.distributionAction || "";
          if (["gallery", "export", "viewer"].includes(action)) {
            switchView(action);
            return;
          }
          if (distributionLensOptions.some((option) => option.value === action)) {
            distributionLens = action;
            renderDistribution();
          }
        });
      });
      container.querySelectorAll("[data-photo-index]").forEach((node) => {
        node.addEventListener("click", () => {
          openViewerAt(Number(node.dataset.photoIndex));
        });
      });
    }

    return { render: renderDistribution };
  }

  return { create };
})();
