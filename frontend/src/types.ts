// The parts of Home Assistant's frontend objects the page reads. Home Assistant passes them to a
// sidebar page as properties: `hass`, `narrow`, `route` and `panel`.

export interface HomeAssistant {
  language: string;
  user?: { is_admin: boolean };
  themes?: { darkMode?: boolean };
}

export interface PanelInfo {
  config?: { entry_id?: string };
}
