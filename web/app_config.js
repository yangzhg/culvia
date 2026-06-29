(function () {
  const scoreFields = ["quality", "composition", "lighting", "color", "depth_of_field", "content"];
  const technicalFields = ["sharpness", "exposure", "contrast", "cleanliness"];
  const modelQualityFields = ["clip_iqa_sharpness", "clip_iqa_exposure", "clip_iqa_cleanliness"];
  const aestheticReferenceFields = ["clip_aesthetic"];
  const llmSummaryFields = ["llm_review_overall"];
  const llmAestheticFields = [
    "llm_aesthetic_overall",
    "llm_quality",
    "llm_composition",
    "llm_lighting",
    "llm_color",
    "llm_depth_of_field",
    "llm_content",
  ];
  const llmTechnicalFields = ["llm_technical_overall", "llm_sharpness", "llm_exposure", "llm_contrast", "llm_cleanliness"];
  const llmReviewFields = [...llmSummaryFields, ...llmAestheticFields, ...llmTechnicalFields];
  const manualColorLabels = [
    { value: "", label: "无色标", labelKey: "color.empty", shortcut: "c" },
    { value: "red", label: "红色", labelKey: "color.red", shortcut: "r" },
    { value: "yellow", label: "黄色", labelKey: "color.yellow", shortcut: "y" },
    { value: "green", label: "绿色", labelKey: "color.green", shortcut: "g" },
    { value: "blue", label: "蓝色", labelKey: "color.blue", shortcut: "b" },
    { value: "purple", label: "紫色", labelKey: "color.purple", shortcut: "v" },
  ];
  const supportedTypes = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"];
  const scoreLevelKeys = {
    "封面候选": "scoreLevel.coverCandidate",
    "值得精修": "scoreLevel.worthRetouching",
    "保留观察": "scoreLevel.keepForReview",
    "谨慎保留": "scoreLevel.lowPriority",
    "未评分": "scoreLevel.unrated",
  };
  const technicalTagKeys = {
    "清晰稳定": "technicalTag.sharpStable",
    "清晰度风险": "technicalTag.sharpRisk",
    "清晰度一般": "technicalTag.sharpModerate",
    "曝光需检查": "technicalTag.exposureCheck",
    "曝光稳定": "technicalTag.exposureStable",
    "噪点风险": "technicalTag.noiseRisk",
    "层次清楚": "technicalTag.tonalClear",
  };
  const manualSourceKeys = {
    manual: "manual.source.manual",
    model: "manual.source.model",
    llm: "manual.source.llm",
    model_batch: "manual.source.modelBatch",
    llm_batch: "manual.source.llmBatch",
    "人工": "manual.source.manual",
    "综合模型": "manual.source.model",
    "大模型": "manual.source.llm",
    "批量综合": "manual.source.modelBatch",
    "批量大模型": "manual.source.llmBatch",
  };
  const metricLabelKeys = {
    clip_aesthetic: "sort.clip_aesthetic_0_10",
    clip_iqa_cleanliness: "sort.cleanliness_0_10",
    clip_iqa_exposure: "sort.exposure_0_10",
    clip_iqa_overall: "sort.clip_iqa_overall_0_10",
    clip_iqa_sharpness: "sort.sharpness_0_10",
    cleanliness: "sort.cleanliness_0_10",
    color: "sort.color_0_10",
    composition: "sort.composition_0_10",
    content: "sort.content_0_10",
    contrast: "sort.contrast_0_10",
    depth_of_field: "sort.depth_of_field_0_10",
    exposure: "sort.exposure_0_10",
    lighting: "sort.lighting_0_10",
    llm_aesthetic_overall: "sort.llm_aesthetic_overall_0_10",
    llm_cleanliness: "sort.cleanliness_0_10",
    llm_color: "sort.color_0_10",
    llm_composition: "sort.composition_0_10",
    llm_content: "sort.content_0_10",
    llm_contrast: "sort.contrast_0_10",
    llm_depth_of_field: "sort.depth_of_field_0_10",
    llm_exposure: "sort.exposure_0_10",
    llm_lighting: "sort.lighting_0_10",
    llm_quality: "sort.quality_0_10",
    llm_review_overall: "sort.llm_review_overall_0_10",
    llm_sharpness: "sort.sharpness_0_10",
    llm_technical_overall: "sort.llm_technical_overall_0_10",
    overall: "sort.overall_0_10",
    quality: "sort.quality_0_10",
    sharpness: "sort.sharpness_0_10",
    technical_overall: "sort.technical_overall_0_10",
  };

  window.CulviaAppConfig = {
    scoreFields,
    technicalFields,
    modelQualityFields,
    aestheticReferenceFields,
    llmSummaryFields,
    llmAestheticFields,
    llmTechnicalFields,
    llmReviewFields,
    manualColorLabels,
    manualSourceKeys,
    metricLabelKeys,
    scoreLevelKeys,
    supportedTypes,
    technicalTagKeys,
  };
})();
