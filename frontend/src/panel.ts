// The Boiler page in Home Assistant's sidebar (docs/en/development/plans/plan-0.2-i10.md). It reads
// the installation from the plugin once, then follows Home Assistant's states; the overview draws
// what they say. The schematic, the curve and the last 24 h come in the next steps.
import { LitElement, css, html, nothing } from "lit";
import { localize } from "./localize";
import "./overview";
import type { HomeAssistant, Installation, PanelInfo } from "./types";

export const PANEL_TAG = "vtherm-smart-boiler-panel";

type Load =
  | { kind: "loading" }
  | { kind: "ready"; installation: Installation }
  | { kind: "not_running" }
  | { kind: "error"; message: string };

export class SmartBoilerPanel extends LitElement {
  static properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    panel: { attribute: false },
    load: { state: true },
  };

  declare hass?: HomeAssistant;
  declare narrow: boolean;
  declare panel?: PanelInfo;
  declare load: Load;
  private requested = false;

  constructor() {
    super();
    this.narrow = false;
    this.load = { kind: "loading" };
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  protected willUpdate(): void {
    if (this.hass && !this.requested) {
      this.requested = true;
      void this.fetchInstallation();
    }
  }

  private async fetchInstallation(showLoading = true): Promise<void> {
    if (!this.hass) return;
    if (showLoading) this.load = { kind: "loading" };
    try {
      const installation = await this.hass.callWS<Installation>({
        type: "vtherm_smart_boiler/installation",
      });
      this.load = { kind: "ready", installation };
    } catch (err) {
      const code = (err as { code?: unknown })?.code;
      const message = (err as { message?: unknown })?.message;
      this.load =
        code === "not_running"
          ? { kind: "not_running" }
          : { kind: "error", message: typeof message === "string" ? message : String(err) };
    }
  }

  /** After a save from the page the plugin reloads its settings: read the installation again
   * once it has (a few seconds), keeping the page as it is meanwhile. */
  private refetchSoon(): void {
    window.setTimeout(() => void this.fetchInstallation(false), 3000);
  }

  private body() {
    switch (this.load.kind) {
      case "loading":
        return html`<p class="note">${this.t("panel.loading")}</p>`;
      case "not_running":
        return html`<p class="note">${this.t("panel.not_running")}</p>`;
      case "error":
        return html`<p class="note error" role="alert">
          ${this.t("panel.error", { message: this.load.message })}
        </p>`;
      case "ready":
        return html`<vtherm-smart-boiler-overview
          .hass=${this.hass}
          .installation=${this.load.installation}
          @installation-changed=${() => this.refetchSoon()}
        ></vtherm-smart-boiler-overview>`;
    }
  }

  render() {
    return html`
      <header class="toolbar">
        ${this.narrow
          ? html`<ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>`
          : nothing}
        <h1>${this.t("panel.title")}</h1>
      </header>
      <main>${this.body()}</main>
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
    .note {
      color: var(--secondary-text-color);
    }
    .error {
      color: var(--error-color, #db4437);
    }
  `;
}

if (!customElements.get(PANEL_TAG)) {
  customElements.define(PANEL_TAG, SmartBoilerPanel);
}
