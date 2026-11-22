// The overview (docs/en/development/plans/plan-0.2-i10.md, I10.3): the status with its reasons
// and whether control is on, the tiles, the schematic with the rooms beside the curve, and the
// last 24 h, whose scrubber shows any moment of the day in every part above. Control is switched
// in the plugin's settings, by an administrator (plan-0.2-i11.md, the user's decisions of
// 2026-11-22): the page shows its state and leads an administrator there.
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

/** The plugin's page in Home Assistant's settings: its "Configure" opens the options. */
export const SETTINGS_PATH = "/config/integrations/integration/vtherm_smart_boiler";

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
    history: { state: true },
    historyStatus: { state: true },
    at: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  /** The parts shown: all of them on the page, one on a card. */
  declare parts: readonly Part[];
  declare history: History | null;
  declare historyStatus: string;
  /** The moment shown: `null` for now. */
  declare at: number | null;
  private window: [number, number] = [0, 0];
  private historyAsked = false;

  constructor() {
    super();
    this.parts = PARTS;
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

  /** The plugin's own page in Home Assistant's settings, where "Configure" opens its options:
   * control is switched there ("Control mode", "Control on"). */
  private openSettings(): void {
    window.history.pushState(null, "", SETTINGS_PATH);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  render() {
    const view = this.view();
    if (!view) return nothing;
    const { status, control, tiles } = view;
    const replay = this.at != null;
    const canChange = control !== null && this.isAdmin && !replay;
    const shown = this.shown();
    const hint = !control
      ? ""
      : replay
        ? this.t("control.replay_hint")
        : !control.available
          ? this.t("control.unavailable")
          : this.isAdmin
            ? this.t("control.hint_settings")
            : this.t("control.admin_only");
    const part = (name: Part) => this.parts.includes(name);
    const schematic = part("schematic");
    const curve = part("curve");
    return html`
      ${part("status") ? this.statusPart(status, control, tiles, replay, canChange, hint) : nothing}
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
    `;
  }

  private statusPart(
    status: LiveView["status"],
    control: LiveView["control"],
    tiles: LiveView["tiles"],
    replay: boolean,
    canChange: boolean,
    hint: string,
  ) {
    return html`
      <section class="card hero">
        <div class="status">
          <div
            class="flame ${status.heat}"
            role="img"
            aria-label=${this.t(`status.heat_${status.heat}`)}
            title=${this.t(`status.heat_${status.heat}`)}
          >
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
              <span class="pill ${control.on ? "on" : ""}" role="status">
                ${control.on ? this.t("control.on") : this.t("control.off")}
              </span>
              ${canChange
                ? html`<button class="text" @click=${() => this.openSettings()}>
                    ${this.t("control.settings")}
                  </button>`
                : nothing}
            </div>`
          : nothing}
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
    /* Called for heat between burns: the flame in the heating colour, outlined; lit: filled, on
       a warm ground. */
    .flame.called,
    .flame.burning {
      color: var(--state-climate-heat-color, #ff8100);
      background: color-mix(in srgb, var(--state-climate-heat-color, #ff8100) 14%, transparent);
    }
    .flame.burning {
      background: color-mix(in srgb, var(--state-climate-heat-color, #ff8100) 24%, transparent);
    }
    .flame.burning svg {
      fill: currentColor;
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
    .pill {
      flex: none;
      border-radius: 14px;
      padding: 4px 12px;
      font-weight: 600;
      background: var(--disabled-color, #bdbdbd);
      color: var(--text-primary-color, #fff);
    }
    .pill.on {
      background: var(--primary-color);
    }
    button.text {
      appearance: none;
      border: 0;
      border-radius: 10px;
      min-height: 36px;
      padding: 0 12px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      background: transparent;
      color: var(--primary-color);
      flex: none;
    }
    button.text:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 2px;
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
  `;
}

if (!customElements.get(OVERVIEW_TAG)) {
  customElements.define(OVERVIEW_TAG, SmartBoilerOverview);
}
