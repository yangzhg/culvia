// Application entry point. Each module registers itself on `window.Culvia*`;
// the import order below is the only place load order is declared.

// Locale resources and i18n runtime.
import "./locales/zh-CN.js?v=20260922-export-progress";
import "./locales/en.js?v=20260922-export-progress";
import "./i18n_messages.js";
import "./i18n.js";

// Pure state and interaction helpers.
import "./filter_state.js";
import "./filter_presets.js?v=20260908-responsive-readability";
import "./culling_flow.js";
import "./shortcuts.js";
import "./gallery_keyboard.js";
import "./viewer_keyboard.js";
import "./manual_status.js";

// View factories.
import "./llm_config_view.js?v=20260812-responsive-nav";
import "./command_view.js?v=20260904-full-filter-scope";
import "./export_preflight.js";
import "./export_preflight_state.js";
import "./export_result_data.js";
import "./export_result.js";
import "./export_actions.js?v=20260922-export-progress";
import "./export_list.js?v=20260904-score-provenance";
import "./batch_actions.js?v=20260904-batch-confirm";
import "./clipboard.js";
import "./api_client.js";
import "./update_panel.js?v=20260922-update-packages";
import "./distribution_model.js";
import "./app_config.js";
import "./icons.js";
import "./ui_helpers.js";
import "./gallery_view.js?v=20260904-score-provenance";
import "./distribution_view.js";
import "./distribution_panel.js";
import "./export_panel.js?v=20260922-export-progress";
import "./llm_config_panel.js";
import "./gallery_panel.js?v=20260908-view-lifecycle";
import "./viewer_panel.js?v=20260904-score-provenance";
import "./source_panel.js?v=20260908-responsive-readability";
import "./filter_panel.js?v=20260908-responsive-readability";
import "./viewer_inspector.js";

// Orchestrator: wires state, rendering, and events together.
import "./app.js?v=20260908-view-lifecycle";
