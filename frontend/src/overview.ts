// The overview (docs/en/development/plans/plan-0.2-i10.md, I10.3): the status with its reasons
// and the Control switch, the tiles, the schematic with the rooms beside the curve, and the last
// 24 h, whose scrubber shows any moment of the day in every part above. Only an administrator can
// switch control, only now and only after confirming; the switch's own checks still apply — a
// refusal is shown as given.
import { LitElement, css, html, nothing } from "lit";
import { liveView, type LiveView } from "./live";
import { localize } from "./localize";
import "./curve-card";
import "./schematic-card";
import "./timeline-card";
import {
  WINDOW_MS,
  clock,
  parseHistory,
  statesAt,
  watchedEntities,
  type History,
  type RecordedState,
} from "./timeline";
import type { HomeAssistant, Installation } from "./types";

export const OVERVIEW_TAG = "vtherm-smart-boiler-overview";

/** The overview's parts; a card shows one of them (I10.8). */
export const PARTS = ["status", "schematic", "curve", "timeline"] as const;
export type Part = (typeof PARTS)[number];

const FLAME_PATH =
  "M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.3 1.6 1 2.6 2 3.1C11 9 11.3 6 12 3z";

export class SmartBoilerOverview extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
    parts: { attribute: false },
    confirming: { state: true },
    error: { state: true },
    history: { state: true },
    historyStatus: { state: true },
    at: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  /** The parts shown: all of them on the page, one on a card. */
  declare parts: readonly Part[];
  declare confirming: boolean;
  declare error: string;
  declare history: History | null;
  declare historyStatus: string;
  /** The moment shown: `null` for now. */
  declare at: number | null;
  private window: [number, number] = [0, 0];
  private historyAsked = false;

  constructor() {
    super();
    this.parts = PARTS;
    this.confirming = false;
    this.error = "";
    this.history = null;
    this.historyStatus = "loading";
    this.at = null;
  }

  protected willUpdate(): void {
    // The last 24 h are read only where they are shown: a card of another part does not ask.
    if (this.hass && this.installation && !this.historyAsked && this.parts.includes("timeline")) {
      this.historyAsked = true;
      void this.askHistory();
    }
  }

  /** The last 24 h of every entity the overview reads, from Home Assistant's recorder. */
  private async askHistory(): Promise<void> {
    const hass = this.hass as HomeAssistant;
    const end = Date.now();
    const start = end - WINDOW_MS;
    this.window = [start, end];
    try {
      const answer = await hass.callWS<Record<string, RecordedState[]>>({
        type: "history/history_during_period",
        start_time: new Date(start).toISOString(),
        end_time: new Date(end).toISOString(),
        entity_ids: watchedEntities(this.installation as Installation),
        include_start_time_state: true,
        significant_changes_only: false,
        minimal_response: false,
        no_attributes: false,
      });
      this.history = parseHistory(answer);
      this.historyStatus = "ready";
    } catch (err) {
      const message = (err as { message?: unknown })?.message;
      this.historyStatus = typeof message === "string" ? message : String(err);
    }
  }

  /** Home Assistant as the overview shows it: now, or at the moment picked on the last 24 h. */
  private shown(): HomeAssistant | undefined {
    const hass = this.hass;
    if (!hass || this.at == null || !this.history) return hass;
    return { ...hass, states: statesAt(this.history, this.at, hass.states) };
  }

  private moveTo(at: number | null): void {
    this.at = at;
    if (at == null && Date.now() - this.window[1] > 5 * 60000) void this.askHistory();
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private view(): LiveView | null {
    const hass = this.shown();
    if (!hass || !this.installation) return null;
    return liveView({
      installation: this.installation,
      states: hass.states,
      language: hass.locale?.language ?? hass.language,
      t: (key, values) => this.t(key, values),
      stateText: (entity) => hass.formatEntityState?.(entity) ?? entity.state,
    });
  }

  private get isAdmin(): boolean {
    return this.hass?.user?.is_admin === true;
  }

  private ask(): void {
    this.error = "";
    this.confirming = true;
  }

  private async decide(go: boolean, view: LiveView): Promise<void> {
    this.confirming = false;
    const control = view.control;
    if (!go || !control || !this.hass) return;
    try {
      await this.hass.callService("switch", control.on ? "turn_off" : "turn_on", {
        entity_id: control.entityId,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String((err as { message?: unknown })?.message ?? err);
      this.error = this.t("control.failed", { message });
    }
  }

  updated(): void {
    const dialog = this.renderRoot.querySelector("dialog");
    if (!dialog) return;
    if (this.confirming && !dialog.open) dialog.showModal();
    if (!this.confirming && dialog.open) dialog.close();
  }

  render() {
    const view = this.view();
    if (!view) return nothing;
    const { status, control, tiles } = view;
    const replay = this.at != null;
    const canSwitch = control !== null && control.available && this.isAdmin && !replay;
    const shown = this.shown();
    const hint = !control
      ? ""
      : replay
        ? this.t("control.replay_hint")
        : !control.available
        ? this.t("control.unavailable")
        : !this.isAdmin
          ? this.t("control.admin_only")
          : control.on
            ? this.t("control.hint_on")
            : this.t("control.hint_off");
    const part = (name: Part) => this.parts.includes(name);
    const schematic = part("schematic");
    const curve = part("curve");
    return html`
      ${part("status") ? this.statusPart(status, control, tiles, replay, canSwitch, hint) : nothing}
      ${schematic || curve
        ? html`<div class="row ${schematic && curve ? "" : "single"}">
            ${schematic
              ? html`<vtherm-smart-boiler-schematic
                  class="wide"
                  .hass=${shown}
                  .installation=${this.installation}
                ></vtherm-smart-boiler-schematic>`
              : nothing}
            ${curve
              ? html`<vtherm-smart-boiler-curve
                  class="side"
                  .hass=${shown}
                  .installation=${this.installation}
                ></vtherm-smart-boiler-curve>`
              : nothing}
          </div>`
        : nothing}
      ${part("timeline")
        ? html`<vtherm-smart-boiler-timeline
            .hass=${this.hass}
            .installation=${this.installation}
            .history=${this.history}
            .from=${this.window[0]}
            .to=${this.window[1]}
            .at=${this.at}
            .status=${this.historyStatus}
            .alone=${this.parts.length === 1}
            @at-change=${(e: CustomEvent<number | null>) => this.moveTo(e.detail)}
          ></vtherm-smart-boiler-timeline>`
        : nothing}
      ${control && part("status")
        ? html`<dialog aria-labelledby="confirm-title" @cancel=${() => (this.confirming = false)}>
            <h2 id="confirm-title">
              ${control.on ? this.t("control.confirm_off_title") : this.t("control.confirm_on_title")}
            </h2>
            <p>${control.on ? this.t("control.confirm_off_body") : this.t("control.confirm_on_body")}</p>
            <div class="actions">
              <button class="text" @click=${() => this.decide(false, view)}>${this.t("control.cancel")}</button>
              <button class="primary" @click=${() => this.decide(true, view)}>
                ${control.on ? this.t("control.confirm_off") : this.t("control.confirm_on")}
              </button>
            </div>
          </dialog>`
        : nothing}
    `;
  }

  private statusPart(
    status: LiveView["status"],
    control: LiveView["control"],
    tiles: LiveView["tiles"],
    replay: boolean,
    canSwitch: boolean,
    hint: string,
  ) {
    return html`
      <section class="card hero">
        <div class="status">
          <div class="flame ${status.flame ? "lit" : ""}" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d=${FLAME_PATH}></path></svg>
          </div>
          <div class="words">
            <div class="title-row">
              <h2>${status.title}</h2>
              ${replay ? html`<span class="chip">${this.t("control.replay", { time: clock(this.at as number, this.hass?.locale?.language ?? this.hass?.language ?? "en") })}</span>` : nothing}
            </div>
            ${status.detail ? html`<p>${status.detail}</p>` : nothing}
          </div>
        </div>
        ${control
          ? html`<div class="control">
              <div class="label">
                <div>${this.t("control.label")} <span class="muted">${this.t("control.experimental")}</span></div>
                <div class="muted small">${hint}</div>
              </div>
              <button
                class="switch ${control.on ? "on" : ""}"
                role="switch"
                aria-checked=${control.on ? "true" : "false"}
                aria-label=${this.t("control.label")}
                ?disabled=${!canSwitch}
                @click=${() => this.ask()}
              >
                <span class="knob"></span>
              </button>
            </div>`
          : nothing}
        ${this.error ? html`<p class="error" role="alert">${this.error}</p>` : nothing}
      </section>

      ${tiles.length
        ? html`<section class="tiles" aria-label=${this.t("panel.title")}>
            ${tiles.map(
              (tile) => html`<div class="card tile">
                <div class="tile-label">${tile.label}</div>
                <div class="tile-value">${tile.value}</div>
                <div class="muted small">${tile.detail}</div>
              </div>`,
            )}
          </section>`
        : nothing}
    `;
  }

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 16px;
      box-sizing: border-box;
      min-width: 0;
    }
    .hero {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 16px 24px;
    }
    .status {
      display: flex;
      align-items: center;
      gap: 16px;
      flex: 999 1 420px;
      min-width: 0;
    }
    .flame {
      width: 54px;
      height: 54px;
      border-radius: 50%;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
      display: flex;
      align-items: center;
      justify-content: center;
      flex: none;
      color: var(--disabled-text-color, #9e9e9e);
    }
    .flame.lit {
      color: var(--state-climate-heat-color, #ff8100);
    }
    .flame svg {
      width: 30px;
      height: 30px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    h2 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
    .title-row {
      display: flex;
      align-items: baseline;
      gap: 10px;
      flex-wrap: wrap;
    }
    .chip {
      font-size: 12px;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 999px;
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    .words p {
      margin: 4px 0 0;
      color: var(--secondary-text-color);
    }
    .control {
      display: flex;
      align-items: center;
      gap: 14px;
      flex: 1 1 340px;
      justify-content: flex-end;
      text-align: right;
    }
    .label > div:first-child {
      white-space: nowrap;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .switch {
      appearance: none;
      border: 0;
      padding: 0;
      width: 52px;
      height: 32px;
      border-radius: 16px;
      background: var(--disabled-color, #bdbdbd);
      position: relative;
      cursor: pointer;
      flex: none;
    }
    .switch.on {
      background: var(--primary-color);
    }
    .switch:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }
    .switch:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 3px;
    }
    .knob {
      position: absolute;
      top: 4px;
      left: 4px;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
      transition: left 0.15s;
    }
    .switch.on .knob {
      left: 24px;
    }
    .error {
      flex-basis: 100%;
      margin: 0;
      color: var(--error-color, #db4437);
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      align-items: flex-start;
    }
    .wide {
      flex: 999 1 640px;
      min-width: 0;
    }
    .row.single > * {
      flex: 1 1 100%;
    }
    .side {
      flex: 1 1 360px;
      min-width: 0;
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
    }
    .tile {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .tile-label {
      font-size: 13px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .tile-value {
      font-size: 26px;
      font-weight: 600;
      line-height: 1.1;
      font-variant-numeric: tabular-nums;
    }
    dialog {
      border: 0;
      border-radius: var(--ha-dialog-border-radius, 16px);
      padding: 24px;
      max-width: 440px;
      width: calc(100% - 32px);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
    }
    dialog::backdrop {
      background: rgba(0, 0, 0, 0.45);
    }
    dialog h2 {
      font-size: 20px;
      margin-bottom: 8px;
    }
    dialog p {
      margin: 0;
      color: var(--secondary-text-color);
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 20px;
    }
    .actions button {
      appearance: none;
      border: 0;
      border-radius: 10px;
      min-height: 40px;
      padding: 0 16px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }
    .actions .text {
      background: transparent;
      color: var(--primary-color);
    }
    .actions .primary {
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
  `;
}

if (!customElements.get(OVERVIEW_TAG)) {
  customElements.define(OVERVIEW_TAG, SmartBoilerOverview);
}
