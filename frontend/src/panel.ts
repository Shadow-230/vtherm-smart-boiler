// The Boiler page in Home Assistant's sidebar (docs/en/development/plans/plan-0.2-i10.md). It reads
// the installation from the plugin once, then follows Home Assistant's states; the overview draws
// what they say. The schematic, the curve and the last 24 h come in the next steps.
import { LitElement, css, html, nothing } from "lit";
import { localize } from "./localize";
import "./burner-view";
import "./overview";
import type { HomeAssistant, Installation, PanelInfo } from "./types";

export const PANEL_TAG = "vtherm-smart-boiler-panel";

const TABS = ["overview", "burner"] as const;
type Tab = (typeof TABS)[number];

/** The tab a link names (#burner), else the overview. */
function tabOf(hash: string): Tab {
  const name = hash.replace(/^#/, "");
  return (TABS as readonly string[]).includes(name) ? (name as Tab) : "overview";
}

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
    tab: { state: true },
  };

  declare hass?: HomeAssistant;
  declare narrow: boolean;
  declare panel?: PanelInfo;
  declare load: Load;
  declare tab: Tab;
  private requested = false;

  constructor() {
    super();
    this.narrow = false;
    this.load = { kind: "loading" };
    this.tab = tabOf(location.hash);
  }

  private choose(tab: Tab): void {
    this.tab = tab;
    history.replaceState(history.state, "", tab === "overview" ? location.pathname : `#${tab}`);
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
        // Both views stay mounted, so each keeps what it read when the other is shown.
        return html`<vtherm-smart-boiler-overview
            ?hidden=${this.tab !== "overview"}
            .hass=${this.hass}
            .installation=${this.load.installation}
            @installation-changed=${() => this.refetchSoon()}
          ></vtherm-smart-boiler-overview>
          <vtherm-smart-boiler-burner
            ?hidden=${this.tab !== "burner"}
            .hass=${this.hass}
            .installation=${this.load.installation}
          ></vtherm-smart-boiler-burner>`;
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
      <nav class="tabs" aria-label=${this.t("tabs.label")}>
        ${TABS.map(
          (tab) => html`<button
            class="tab ${this.tab === tab ? "on" : ""}"
            aria-current=${this.tab === tab ? "page" : "false"}
            @click=${() => this.choose(tab)}
          >
            ${this.t(`tabs.${tab}`)}
          </button>`,
        )}
      </nav>
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
    .tabs {
      display: flex;
      gap: 2px;
      padding: 0 8px;
      overflow-x: auto;
      background: var(--app-header-background-color, var(--primary-color));
    }
    .tab {
      appearance: none;
      border: 0;
      background: none;
      font: inherit;
      font-weight: 500;
      padding: 0 16px;
      height: 44px;
      color: var(--app-header-text-color, var(--text-primary-color));
      opacity: 0.75;
      border-bottom: 2px solid transparent;
      cursor: pointer;
      white-space: nowrap;
    }
    .tab.on {
      opacity: 1;
      border-bottom-color: var(--app-header-text-color, var(--text-primary-color));
    }
    .tab:focus-visible {
      outline: 2px solid var(--app-header-text-color, #fff);
      outline-offset: -4px;
    }
    [hidden] {
      display: none !important;
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
