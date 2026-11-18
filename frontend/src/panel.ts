// The Boiler page in Home Assistant's sidebar (docs/en/development/plans/plan-0.2-i10.md). For
// now its frame: the toolbar in Home Assistant's theme and language; the overview, the schematic
// and the curve come in the next steps.
import { LitElement, css, html, nothing } from "lit";
import { localize } from "./localize";
import type { HomeAssistant, PanelInfo } from "./types";

export const PANEL_TAG = "vtherm-smart-boiler-panel";

export class SmartBoilerPanel extends LitElement {
  static properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    panel: { attribute: false },
  };

  declare hass?: HomeAssistant;
  declare narrow: boolean;
  declare panel?: PanelInfo;

  constructor() {
    super();
    this.narrow = false;
  }

  private t(key: string): string {
    return localize(this.hass?.language, key);
  }

  render() {
    return html`
      <header class="toolbar">
        ${this.narrow
          ? html`<ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>`
          : nothing}
        <h1>${this.t("panel.title")}</h1>
      </header>
      <main>
        <p>${this.t("panel.building")}</p>
      </main>
    `;
  }

  static styles = css`
    :host {
      display: block;
      min-height: 100%;
      background: var(--primary-background-color);
      color: var(--primary-text-color);
      font-family: var(--ha-font-family-body, Roboto, sans-serif);
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: var(--header-height, 56px);
      padding: 0 16px;
      box-sizing: border-box;
      background: var(--app-header-background-color, var(--primary-color));
      color: var(--app-header-text-color, var(--text-primary-color));
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 400;
    }
    main {
      max-width: 1240px;
      margin: 0 auto;
      padding: 16px;
    }
    p {
      color: var(--secondary-text-color);
    }
  `;
}

if (!customElements.get(PANEL_TAG)) {
  customElements.define(PANEL_TAG, SmartBoilerPanel);
}
