# Product Direction and Design Principles

Simplified Chinese: [../../zh-CN/developer/product-direction.md](../../zh-CN/developer/product-direction.md)

This file records long-term product judgment for Culvia. It is not external overview copy; it is the decision basis for future iterations.

## Research Inputs

- [Aftershoot Select](https://aftershoot.com/selects/): automatic first-pass culling helps photographers review, override, and export ratings, color labels, and flags to Lightroom Classic or Capture One.
- [Adobe Lightroom Classic ratings, flags, and color labels](https://helpx.adobe.com/ca/lightroom-classic/help/flag-label-rate-photos.html): mature culling tools treat ratings, flags, and color labels as the base language for browsing, comparing, and filtering.
- [Capture One rating and color tags](https://support.captureone.com/hc/en-us/article_attachments/360007177777): professional workflows rely on ratings and color labels to organize photos; tools should reduce decision friction instead of interrupting review with complex panels.
- [Narrative Select](https://narrative.so/): high-frequency culling depends on fast loading, quick decisions, and explainable signals such as focus and closed-eye checks.

## Positioning

Culvia is a photo curation and review application for photographers. It should respect the photographer's final decision like a professional photo tool, while organizing machine scoring, LLM critique, and technical QC as reviewable second opinions.

## Design Principles

- Image first: the current photo is always the primary object. Scores and advice support review; they do not compete with the image.
- Model assistance, photographer authority: automatic scoring helps sort, warn, and batch triage. Manual pick/review/reject decisions always have the highest priority.
- Explanations must be scannable: LLM text should be structured into overall critique, aesthetic rationale, technical issues, retouching advice, and shooting advice instead of long unbroken paragraphs.
- Professional but not cold: the visual language should be calm, premium, and low-distraction. Color should express state and hierarchy, not decoration.
- Shared local and Web core: Web, local app, and pip distribution share the same API and scoring logic. Native abilities are surfaced through capabilities and graceful fallback.
- Privacy by default: local models do not upload photos. LLM review must be explicitly configured. API keys must not enter SQLite or Git.

## Workflow Skeleton

1. Import: choose a local folder, drag a folder, or upload temporary images.
2. Score: prepare models automatically, show the current image, completed evaluations, and pause/resume status.
3. Triage: narrow candidates by combined recommendation, model disagreement, technical issues, and LLM opinions.
4. Review: finish final decisions in the viewer using the large photo, thumbnail strip, star rating, and pick/review/reject controls.
5. Mark: use ratings, flag status, and color labels as professional culling language that can travel across tools.
6. Export: export selected photos and CSV details, with future support for Lightroom/Capture One-friendly rating and label mappings.

## History and Undo Principles

- Undo belongs in the main workflow: after a mistake, the first recovery path should be toast undo or `Cmd/Ctrl+Z`, not opening a settings drawer.
- History is for audit and understanding: the recent-actions panel should explain what happened, whether it was restored, and whether it is still restorable. It should not become the high-frequency command surface.
- Do not overwrite later decisions: if a user manually changed related photos after a batch operation, undo should fail protectively instead of silently rolling back.
- Native text input behavior wins: when focus is inside path, filter name, LLM configuration, or prompt editors, `Cmd/Ctrl+Z` must remain text undo.
- Inline undo should stay restrained: if the history panel gains undo buttons later, show the affected scope and conflict risk first.
- Language should sound like a culling tool: use user-facing workflow terms and avoid exposing payload IDs, history IDs, or database details.

## Roadmap

- Architecture: continue keeping `culvia_app.py` thin by moving behavior into app factory, state store, scoring service, file service, and export service boundaries.
- Frontend: reshape import, models, and filters into task drawers and workbench toolbars, reducing sidebar configuration noise.
- Visual design: maintain unified design tokens and chart palettes instead of inventing colors module by module.
- Local app: continue the desktop route using the `culvia-supervisor` supervisor and Starlette API. The current shell implementation uses Tauri; pywebview remains only a lightweight fallback candidate, and Electron is not the default route.
- Culling: improve shortcuts, batch acceptance, color labels, duplicate/similar group comparison, and export mapping.
- LLM: keep the OpenAI-compatible interface, support model-list retrieval, prompt presets, result versioning, and failure retry.
