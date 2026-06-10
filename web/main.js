// Application entry point. Each module registers itself on `window.Culvia*`;
// the import order below is the only place load order is declared.

// Locale resources and i18n runtime.
import "./locales/zh-CN.js";
import "./locales/en.js";
import "./i18n_messages.js";
import "./i18n.js";

// Pure state and interaction helpers.
import "./filter_state.js";
import "./filter_presets.js";
import "./culling_flow.js";
import "./shortcuts.js";
import "./gallery_keyboard.js";
import "./viewer_keyboard.js";
import "./manual_status.js";

// View factories.
import "./llm_config_view.js";
import "./command_view.js";
import "./export_preflight.js";
import "./export_preflight_state.js";
import "./export_result_data.js";
import "./export_result.js";
import "./export_actions.js";
import "./export_list.js";
import "./batch_actions.js";
import "./clipboard.js";
import "./api_client.js";
import "./distribution_model.js";
import "./app_config.js";
import "./icons.js";
import "./ui_helpers.js";
import "./gallery_view.js";
import "./distribution_view.js";
import "./distribution_panel.js";
import "./export_panel.js";
import "./llm_config_panel.js";
import "./gallery_panel.js";
import "./viewer_inspector.js";

// Orchestrator: wires state, rendering, and events together.
import "./app.js";
