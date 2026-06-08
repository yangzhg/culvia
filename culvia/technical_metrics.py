from __future__ import annotations

from pathlib import Path

from culvia.image_io import open_image_rgb


def clamp_score(value: float) -> float:
    return max(0.0, min(float(value), 10.0))


def technical_analysis_array(path: str | Path) -> tuple[object, object]:
    import numpy as np

    image = open_image_rgb(path)
    image.thumbnail((1024, 1024))
    rgb = np.asarray(image, dtype="float32") / 255.0
    luminance = rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
    return rgb, luminance


def sharpness_score(luminance: object) -> float:
    import numpy as np

    y = np.asarray(luminance, dtype="float32")
    if y.shape[0] < 3 or y.shape[1] < 3:
        return 0.0
    laplacian = -4.0 * y[1:-1, 1:-1] + y[:-2, 1:-1] + y[2:, 1:-1] + y[1:-1, :-2] + y[1:-1, 2:]
    variance = float(np.var(laplacian))
    normalized = (np.log10(variance + 1e-6) + 4.0) / 2.15
    return clamp_score(normalized * 10.0)


def exposure_score(luminance: object) -> float:
    import numpy as np

    y = np.asarray(luminance, dtype="float32")
    mean = float(np.mean(y))
    clipped_shadows = float(np.mean(y < 0.025))
    clipped_highlights = float(np.mean(y > 0.975))
    mid_penalty = min(abs(mean - 0.46) / 0.42, 1.0)
    clip_penalty = min((clipped_shadows + clipped_highlights) * 3.0, 1.0)
    return clamp_score((1.0 - (0.58 * mid_penalty + 0.42 * clip_penalty)) * 10.0)


def contrast_score(luminance: object) -> float:
    import numpy as np

    y = np.asarray(luminance, dtype="float32")
    std = float(np.std(y))
    low_curve = min(max((std - 0.055) / 0.16, 0.0), 1.0)
    high_penalty = min(max((std - 0.42) / 0.18, 0.0), 1.0)
    return clamp_score(low_curve * (1.0 - high_penalty) * 10.0)


def cleanliness_score(luminance: object) -> float:
    import numpy as np

    y = np.asarray(luminance, dtype="float32")
    if y.shape[0] < 5 or y.shape[1] < 5:
        return 5.0

    center = y[1:-1, 1:-1]
    local_mean = (center + y[:-2, 1:-1] + y[2:, 1:-1] + y[1:-1, :-2] + y[1:-1, 2:]) / 5.0
    residual = center - local_mean
    gradient = (np.abs(y[1:-1, 2:] - y[1:-1, :-2]) + np.abs(y[2:, 1:-1] - y[:-2, 1:-1])) / 2.0
    flat_mask = gradient < 0.035
    if int(np.sum(flat_mask)) > 500:
        noise = float(np.std(residual[flat_mask]))
    else:
        noise = float(np.std(residual)) * 0.65
    normalized_noise = min(max((noise - 0.006) / 0.04, 0.0), 1.0)
    return clamp_score((1.0 - normalized_noise) * 10.0)


def analyze_technical_quality(path: str | Path) -> dict[str, float]:
    _rgb, luminance = technical_analysis_array(path)
    sharpness = sharpness_score(luminance)
    exposure = exposure_score(luminance)
    contrast = contrast_score(luminance)
    cleanliness = cleanliness_score(luminance)
    technical_overall = sharpness * 0.4 + exposure * 0.25 + contrast * 0.2 + cleanliness * 0.15
    return {
        "technical_overall": round(clamp_score(technical_overall), 4),
        "sharpness": round(sharpness, 4),
        "exposure": round(exposure, 4),
        "contrast": round(contrast, 4),
        "cleanliness": round(cleanliness, 4),
    }
