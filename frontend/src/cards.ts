// The overview's parts as cards for the user's own dashboards (docs/en/development/plans/
// plan-0.2-i10.md, I10.8): status and tiles, the schematic, the curve, the last 24 h. Each
// finds the plugin's one entry by itself (vtherm_smart_boiler/installation) and needs no settings;
// each is the page's own part, with the same rules — only an administrator switches control or
// saves the curve, after confirming. The plugin loads this module on every page of Home
// Assistant while it runs, so the cards are in the card picker.
import { LitElement, css, html, nothing } from "lit";
import { localize } from "./localize";
import "./overview";
import type { Part } from "./overview";
import type { HomeAssistant, Installation } from "./types";

export interface CardKind {
  part: Part;
  tag: string;
  /** Rows of 50 px in a masonry dashboard. */
  size: number;
  /** Columns of 12 in a sections dashboard. */
  columns: number;
}

export const CARDS: CardKind[] = [
  { part: "status", tag: "vtherm-smart-boiler-status-card", size: 4, columns: 12 },
  { part: "schematic", tag: "vtherm-smart-boiler-schematic-card", size: 8, columns: 12 },
  { part: "curve", tag: "vtherm-smart-boiler-curve-card", size: 8, columns: 6 },
  { part: "timeline", tag: "vtherm-smart-boiler-day-card", size: 6, columns: 12 },
];

type Load =
  | { kind: "loading" }
  | { kind: "ready"; installation: Installation }
  | { kind: "not_running" }
  | { kind: "error"; message: string };

export class SmartBoilerCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    load: { state: true },
  };

  declare hass?: HomeAssistant;
  declare load: Load;
  protected kind: CardKind = CARDS[0];
  private requested = false;

  constructor() {
    super();
    this.load = { kind: "loading" };
  }

  /** A card has no settings of its own: the plugin's entry says everything. */
  setConfig(_config: Record<string, unknown>): void {}

  getCardSize(): number {
    return this.kind.size;
  }

  getGridOptions(): Record<string, number | string> {
    return { columns: this.kind.columns, rows: "auto", min_columns: 6 };
  }

  protected willUpdate(): void {
    if (this.hass && !this.requested) {
      this.requested = true;
      void this.fetchInstallation();
    }
  }

  private async fetchInstallation(): Promise<void> {
    if (!this.hass) return;
    try {
      const installation = await this.hass.callWS<Installation>({ type: "vtherm_smart_boiler/installation" });
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

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  render() {
    switch (this.load.kind) {
      case "loading":
        return html`<div class="card note">${this.t("panel.loading")}</div>`;
      case "not_running":
        return html`<div class="card note">${this.t("panel.not_running")}</div>`;
      case "error":
        return html`<div class="card note error" role="alert">${this.t("panel.error", { message: this.load.message })}</div>`;
      case "ready":
        return html`<vtherm-smart-boiler-overview
          .parts=${[this.kind.part]}
          .hass=${this.hass}
          .installation=${this.load.installation}
          @installation-changed=${() => window.setTimeout(() => void this.fetchInstallation(), 3000)}
        ></vtherm-smart-boiler-overview>`;
    }
    return nothing;
  }

  static styles = css`
    :host {
      display: block;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 16px;
      box-sizing: border-box;
    }
    .note {
      color: var(--secondary-text-color);
    }
    .error {
      color: var(--error-color, #db4437);
    }
  `;
}

interface CardEntry {
  type: string;
  name: string;
  description: string;
  preview?: boolean;
}

/** Each card defined, and listed in the card picker in the page's language as it is when the
 * picker opens. */
export function defineCards(language: () => string | undefined): void {
  for (const kind of CARDS) {
    if (!customElements.get(kind.tag)) {
      customElements.define(
        kind.tag,
        class extends SmartBoilerCard {
          protected kind = kind;
          static getStubConfig(): Record<string, unknown> {
            return {};
          }
        },
      );
    }
  }
  const listed = window as unknown as { customCards?: CardEntry[] };
  listed.customCards = listed.customCards ?? [];
  for (const kind of CARDS) {
    if (listed.customCards.some((card) => card.type === kind.tag)) continue;
    const entry = { type: kind.tag, preview: true } as CardEntry;
    Object.defineProperties(entry, {
      name: { enumerable: true, get: () => localize(language(), `cards.${kind.part}`) },
      description: { enumerable: true, get: () => localize(language(), `cards.${kind.part}_detail`) },
    });
    listed.customCards.push(entry);
  }
}

defineCards(() => document.documentElement.lang || navigator.language);
