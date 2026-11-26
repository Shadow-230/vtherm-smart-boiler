// The Status and alarms tab (docs/en/development/plans/plan-0.2-i10.md, I10.5): the verdict
// with its reasons, the alarms, the signals' health, the building values and the lowest water
// temperature suggested — all from the plugin's own entities, in its own words (its
// translations, loaded through Home Assistant). An administrator can forget a measured building
// value with the plugin's own buttons, after confirming; nothing else changes here.
import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import { formatNumber, numberOf } from "./format";
import { localize } from "./localize";
import {
  REASON_UNITS,
  alarmList,
  buildingValue,
  entityText,
  signalList,
  verdictReasons,
  verdictSizing,
  type AlarmInfo,
  type Localize,
  type ReasonInfo,
  type Severity,
  type SignalStatus,
} from "./status";
import { profileZone } from "./time";
import type { HassEntity, HomeAssistant, Installation } from "./types";

export const STATUS_TAG = "vtherm-smart-boiler-status";

/** The building values: the sensor, its reset button, the digits shown. */
const BUILDING: [sensor: string, button: string, digits: number][] = [
  ["loss_coefficient", "reset_loss_coefficient", 3],
  ["heating_threshold", "reset_heating_threshold", 1],
];

const ICONS: Record<Severity | SignalStatus | ReasonInfo["kind"], string> = {
  alarm: "!",
  warning: "!",
  unknown: "?",
  clear: "✓",
  ok: "✓",
  stale: "!",
  unavailable: "!",
  not_mapped: "–",
  problem: "!",
  missing: "?",
  data: "…",
  fine: "✓",
};

export class SmartBoilerStatus extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
    texts: { attribute: false },
    confirming: { state: true },
    error: { state: true },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;
  /** The plugin's own texts, once Home Assistant has loaded them (the panel asks). */
  declare texts: Localize | null;
  /** The building value whose reset waits for confirmation. */
  declare confirming: string;
  declare error: string;

  constructor() {
    super();
    this.texts = null;
    this.confirming = "";
    this.error = "";
  }

  protected willUpdate(): void {
    // Home Assistant's dark theme: the status colours have their own steps there.
    this.toggleAttribute("dark", this.hass?.themes?.darkMode === true);
  }

  updated(): void {
    const dialog = this.renderRoot.querySelector("dialog");
    if (!dialog) return;
    if (this.confirming && !dialog.open) dialog.showModal();
    if (!this.confirming && dialog.open) dialog.close();
  }

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private get language(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private get isAdmin(): boolean {
    return this.hass?.user?.is_admin === true;
  }

  private entity(key: string): HassEntity | undefined {
    const id = this.installation?.entities[key];
    return id ? this.hass?.states[id] : undefined;
  }

  /** An entity's name in the plugin's words, else its friendly name, else its key. */
  private nameOf(platform: "sensor" | "binary_sensor" | "button", key: string): string {
    const friendly = this.entity(key)?.attributes.friendly_name;
    return entityText(this.texts, platform, key, "name", typeof friendly === "string" ? friendly : key);
  }

  private moreInfo(entityId: string | undefined): void {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  private number(value: number | null, digits: number): string {
    return formatNumber(value, this.language, digits);
  }

  // ------------------------------------------------------------------------------- the verdict

  private reasonValue(reason: ReasonInfo): string {
    const unit = REASON_UNITS[reason.code];
    if (!unit || reason.value == null) return "";
    const shown = (v: number) =>
      unit === "share"
        ? `${this.number(v * 100, 0)} %`
        : unit === "per_hour"
          ? `${this.number(v, 1)} /h`
          : unit === "days"
            ? this.t("checks.days", { value: this.number(v, 1) })
            : this.number(v, 0);
    const value = shown(reason.value);
    const against = reason.limit == null ? value : this.t("checks.against", { value, limit: shown(reason.limit) });
    // I13.5: beside the short burns' share, the share under 3 minutes.
    return reason.very_short_share == null
      ? against
      : `${against} · ${this.t("checks.under_3_min", { value: `${this.number(reason.very_short_share * 100, 0)} %` })}`;
  }

  private reasonNote(reason: ReasonInfo): string {
    if (reason.detail) return entityText(this.texts, "sensor", "verdict", `state_attributes.detail.state.${reason.detail}`, "");
    if (reason.changed_by_control == null) return "";
    const state = reason.changed_by_control ? "true" : "false";
    return entityText(this.texts, "sensor", "verdict", `state_attributes.changed_by_control.state.${state}`, "");
  }

  private verdictCard(): TemplateResult | typeof nothing {
    const sensor = this.entity("verdict");
    if (!sensor) return nothing;
    const state = sensor.state;
    const known = ["worth_it", "not_worth_it", "not_enough_data"].includes(state);
    const stateText = known
      ? entityText(this.texts, "sensor", "verdict", `state.${state}`, this.hass?.formatEntityState?.(sensor) ?? state)
      : this.t("checks.not_known");
    const reasons = verdictReasons(sensor);
    const since = sensor.attributes.monitoring_since;
    const leftOut = sensor.attributes.days_left_out;
    const date = typeof since === "string" ? new Date(since) : null;
    return html`<section class="card">
      <div class="head">
        <h3>${this.nameOf("sensor", "verdict")}</h3>
        <button class="link" @click=${() => this.moreInfo(sensor.entity_id)}>${this.t("checks.history")}</button>
      </div>
      <div class="verdict ${known ? state : "none"}">${stateText}</div>
      <p class="muted small">
        ${date && !Number.isNaN(date.getTime())
          ? this.t("checks.since", { date: date.toLocaleDateString(this.language, { day: "numeric", month: "long", year: "numeric", timeZone: profileZone(this.hass) }) })
          : nothing}
        ${typeof leftOut === "number" && leftOut > 0 ? html` · ${this.t("checks.left_out", { count: String(leftOut) })}` : nothing}
      </p>
      <p class="muted small">${this.t("checks.verdict_hint")}</p>
      ${reasons.length
        ? html`<ul class="rows">
            ${reasons.map((reason) => {
              const value = this.reasonValue(reason);
              const note = this.reasonNote(reason);
              return html`<li class="row">
                <span class="mark ${reason.kind}" aria-hidden="true">${ICONS[reason.kind]}</span>
                <span class="what">
                  <span>${entityText(this.texts, "sensor", "verdict", `state_attributes.reasons.state.${reason.code}`, reason.code)}</span>
                  ${value ? html`<span class="muted small value">${value}</span>` : nothing}
                  ${note ? html`<span class="muted small">${note}</span>` : nothing}
                </span>
                <span class="sr">${this.t(`checks.kind_${reason.kind}`)}</span>
              </li>`;
            })}
          </ul>`
        : nothing}
      ${this.sizingLine(sensor)}
    </section>`;
  }

  /** I13.4: the boiler's outputs against the house's design load, each where known. */
  private sizingLine(sensor: HassEntity): TemplateResult | typeof nothing {
    const sizing = verdictSizing(sensor);
    if (!sizing) return nothing;
    const parts: string[] = [];
    if (sizing.minPower != null) parts.push(this.t("checks.sizing_min", { value: this.number(sizing.minPower, 1) }));
    if (sizing.maxPower != null) parts.push(this.t("checks.sizing_max", { value: this.number(sizing.maxPower, 1) }));
    if (sizing.designLoad != null && sizing.designOutdoor != null)
      parts.push(
        this.t("checks.sizing_load", {
          value: this.number(sizing.designLoad, 1),
          outdoor: this.number(sizing.designOutdoor, 0),
        }),
      );
    return html`<p class="muted small"><b>${this.t("checks.sizing")}:</b> ${parts.join(" · ")}</p>`;
  }

  // -------------------------------------------------------------------------------- the alarms

  private alarmReason(alarm: AlarmInfo): string {
    if (!alarm.reason) return "";
    const path =
      alarm.key === "outdoor_sensor_problem"
        ? `state_attributes.status.state.${alarm.reason}`
        : `state_attributes.reason.state.${alarm.reason}`;
    return entityText(this.texts, "binary_sensor", alarm.key, path, "");
  }

  private alarmRow(alarm: AlarmInfo): TemplateResult {
    const reason = alarm.severity === "clear" ? "" : this.alarmReason(alarm);
    const limitName = entityText(this.texts, "binary_sensor", alarm.key, "state_attributes.limit.name", "");
    const limit =
      alarm.limit != null && alarm.severity !== "clear" && limitName
        ? `${limitName}: ${this.number(alarm.limit, alarm.limit % 1 === 0 ? 0 : 1)}`
        : "";
    const detail = [reason, limit].filter(Boolean).join(" · ");
    return html`<li>
      <button class="row action" @click=${() => this.moreInfo(alarm.entityId)}>
        <span class="mark ${alarm.severity}" aria-hidden="true">${ICONS[alarm.severity]}</span>
        <span class="what">
          <span>${this.nameOf("binary_sensor", alarm.key)}</span>
          ${detail ? html`<span class="muted small">${detail}</span>` : nothing}
        </span>
        <span class="chip ${alarm.severity}">${this.t(`checks.severity_${alarm.severity}`)}</span>
      </button>
    </li>`;
  }

  private alarmsCard(): TemplateResult {
    const alarms = alarmList(this.installation?.entities ?? {}, this.hass?.states ?? {});
    const shown = alarms.filter((a) => a.severity !== "clear");
    const clear = alarms.filter((a) => a.severity === "clear");
    const active = shown.filter((a) => a.severity === "alarm" || a.severity === "warning").length;
    return html`<section class="card">
      <div class="head">
        <h3>${this.t("checks.alarms")}</h3>
        <span class="muted small">${this.t("checks.alarms_count", { active: String(active), all: String(alarms.length) })}</span>
      </div>
      ${active === 0
        ? html`<p class="calm"><span class="mark clear" aria-hidden="true">✓</span>${this.t("checks.no_alarm")}</p>`
        : nothing}
      ${shown.length ? html`<ul class="rows">${shown.map((a) => this.alarmRow(a))}</ul>` : nothing}
      ${clear.length
        ? html`<details>
            <summary>${this.t("checks.clear", { count: String(clear.length) })}</summary>
            <ul class="rows">${clear.map((a) => this.alarmRow(a))}</ul>
          </details>`
        : nothing}
      <p class="muted small">${this.t("checks.alarms_hint")}</p>
    </section>`;
  }

  // ------------------------------------------------------------------------------- the signals

  private signalsCard(): TemplateResult | typeof nothing {
    const sensor = this.entity("signal_problems");
    if (!sensor) return nothing;
    const signals = signalList(sensor);
    const mapped = signals.filter((s) => s.status !== "not_mapped");
    const unmapped = signals.filter((s) => s.status === "not_mapped");
    const name = (signal: string) =>
      entityText(this.texts, "binary_sensor", "connection", `state_attributes.problems.state.${signal}`, signal);
    const link = this.entity("connection");
    return html`<section class="card">
      <div class="head">
        <h3>${this.t("checks.signals")}</h3>
        ${link
          ? html`<span class="chip ${link.state === "on" ? "ok" : link.state === "off" ? "unavailable" : "unknown"}">
              ${this.t(link.state === "on" ? "checks.link_on" : link.state === "off" ? "checks.link_off" : "checks.not_known")}
            </span>`
          : nothing}
      </div>
      ${mapped.length
        ? html`<ul class="rows">
            ${mapped.map(
              (s) => html`<li>
                <button class="row action" @click=${() => this.moreInfo(this.installation?.signals[s.signal])}>
                  <span class="mark ${s.status}" aria-hidden="true">${ICONS[s.status]}</span>
                  <span class="what"><span>${name(s.signal)}</span></span>
                  <span class="chip ${s.status}">${this.t(`checks.signal_${s.status}`)}</span>
                </button>
              </li>`,
            )}
          </ul>`
        : html`<p class="muted">${this.t("checks.no_signal")}</p>`}
      ${unmapped.length
        ? html`<p class="muted small">${this.t("checks.not_mapped", { names: unmapped.map((s) => name(s.signal)).join(", ") })}</p>`
        : nothing}
    </section>`;
  }

  // ----------------------------------------------------------------------- the building values

  private buildingRow([key, button, digits]: (typeof BUILDING)[number]): TemplateResult | typeof nothing {
    const sensor = this.entity(key);
    const value = buildingValue(sensor);
    if (!sensor || !value) return nothing;
    const unit = value.unit ? ` ${value.unit}` : "";
    const source = value.source
      ? entityText(this.texts, "sensor", key, `state_attributes.source.state.${value.source}`, value.source)
      : "";
    const parts: string[] = [];
    if (value.entered != null) parts.push(this.t("checks.entered", { value: `${this.number(value.entered, digits)}${unit}` }));
    if (value.measured != null) {
      const confidence = value.measuredConfidence == null ? "" : this.number(value.measuredConfidence * 100, 0);
      parts.push(
        value.measuredRange
          ? this.t("checks.measured_range", {
              value: `${this.number(value.measured, digits)}${unit}`,
              from: this.number(value.measuredRange[0], digits),
              to: this.number(value.measuredRange[1], digits),
              confidence,
            })
          : this.t("checks.measured", { value: `${this.number(value.measured, digits)}${unit}`, confidence }),
      );
    } else {
      parts.push(this.t("checks.not_measured"));
    }
    const resetId = this.installation?.entities[button];
    const canReset = this.isAdmin && resetId != null && value.measured != null;
    return html`<div class="building">
      <div class="head">
        <span class="label">${this.nameOf("sensor", key)}</span>
        ${source ? html`<span class="chip source">${source}</span>` : nothing}
      </div>
      <div class="big">${value.value == null ? "—" : `${this.number(value.value, digits)}${unit}`}</div>
      <p class="muted small">${parts.join(" · ")}</p>
      ${value.mismatch
        ? html`<p class="small warn-text">
            <span class="mark warning" aria-hidden="true">!</span>${entityText(this.texts, "sensor", key, "state_attributes.mismatch.name", this.t("checks.mismatch"))}
          </p>`
        : nothing}
      ${resetId
        ? html`<button class="outline" ?disabled=${!canReset} @click=${() => this.ask(button)}>
            ${this.nameOf("button", button)}
          </button>`
        : nothing}
    </div>`;
  }

  private buildingCard(): TemplateResult {
    return html`<section class="card">
      <div class="head"><h3>${this.t("checks.building")}</h3></div>
      <p class="muted small">${this.t("checks.building_hint")}</p>
      <div class="buildings">${BUILDING.map((row) => this.buildingRow(row))}</div>
      ${this.isAdmin ? nothing : html`<p class="muted small">${this.t("checks.admin_only")}</p>`}
      ${this.error ? html`<p class="error" role="alert">${this.error}</p>` : nothing}
    </section>`;
  }

  private ask(button: string): void {
    this.error = "";
    this.confirming = button;
  }

  private async decide(go: boolean): Promise<void> {
    const button = this.confirming;
    this.confirming = "";
    const entityId = this.installation?.entities[button];
    if (!go || !entityId || !this.hass || !this.isAdmin) return;
    try {
      await this.hass.callService("button", "press", { entity_id: entityId });
    } catch (err) {
      const message = (err as { message?: unknown })?.message;
      this.error = this.t("checks.reset_failed", { message: typeof message === "string" ? message : String(err) });
    }
  }

  // -------------------------------------------------------------------- the lowest water temp

  private lowestWaterCard(): TemplateResult | typeof nothing {
    const key = "lowest_water_suggestion";
    const sensor = this.entity(key);
    if (!sensor) return nothing;
    const a = sensor.attributes;
    const value = numberOf(sensor.state);
    const attr = (name: string, state: unknown) =>
      typeof state === "string" ? entityText(this.texts, "sensor", key, `state_attributes.${name}.state.${state}`, state) : "";
    const label = (name: string) => entityText(this.texts, "sensor", key, `state_attributes.${name}.name`, name);
    const facts: string[] = [];
    const add = (name: string, shown: string | null) => shown && facts.push(`${label(name)}: ${shown}`);
    add("counted_burns", typeof a.counted_burns === "number" ? this.number(a.counted_burns, 0) : null);
    add("short_share", typeof a.short_share === "number" ? `${this.number(a.short_share, 0)} %` : null);
    add("reference", typeof a.reference === "number" ? `${this.number(a.reference, 1)} °C` : null);
    add("window_days", typeof a.window_days === "number" ? this.number(a.window_days, 0) : null);
    if (typeof a.source === "string") add("source", attr("source", a.source));
    const estimate = typeof a.estimate_from_power === "number" ? `${this.number(a.estimate_from_power, 0)} °C` : null;
    const missing = Array.isArray(a.missing) ? a.missing.filter((m): m is string => typeof m === "string") : [];
    return html`<section class="card">
      <div class="head"><h3>${this.nameOf("sensor", key)}</h3></div>
      <div class="big">${value == null ? "—" : `${this.number(value, 0)} °C`}</div>
      ${typeof a.state === "string" ? html`<p>${attr("state", a.state)}</p>` : nothing}
      ${facts.length ? html`<p class="muted small">${facts.join(" · ")}</p>` : nothing}
      ${estimate
        ? html`<p class="muted small">${label("estimate_from_power")}: ${estimate}</p>`
        : typeof a.estimate_gap === "string"
          ? html`<p class="muted small">${label("estimate_gap")} ${attr("estimate_gap", a.estimate_gap)}</p>`
          : nothing}
      ${missing.length
        ? html`<p class="muted small">${label("missing")}: ${missing.map((m) => attr("missing", m)).join(", ")}</p>`
        : nothing}
      <p class="muted small">${this.t("checks.lowest_water_hint")}</p>
    </section>`;
  }

  render() {
    if (!this.hass || !this.installation) return nothing;
    const confirming = this.confirming;
    return html`
      <div class="grid">
        ${this.verdictCard()} ${this.alarmsCard()} ${this.signalsCard()} ${this.buildingCard()}
        ${this.lowestWaterCard()}
      </div>
      ${confirming
        ? html`<dialog aria-labelledby="reset-title" @cancel=${() => (this.confirming = "")}>
            <h2 id="reset-title">${this.nameOf("button", confirming)}</h2>
            <p>${this.t("checks.reset_body")}</p>
            <div class="actions">
              <button class="text" @click=${() => void this.decide(false)}>${this.t("checks.cancel")}</button>
              <button class="primary" @click=${() => void this.decide(true)}>${this.t("checks.reset")}</button>
            </div>
          </dialog>`
        : nothing}
    `;
  }

  static styles = css`
    :host {
      display: block;
      --sb-good: #2e7d32;
      --sb-warn: #a35f00;
      --sb-bad: #c62828;
      --sb-on-mark: #fff;
    }
    :host([dark]) {
      --sb-good: #66bb6a;
      --sb-warn: #f0a030;
      --sb-bad: #ef6a5e;
      --sb-on-mark: #111;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr));
      gap: 16px;
      align-items: start;
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
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 6px 12px;
      margin-bottom: 8px;
    }
    h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
    p {
      margin: 6px 0;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .error {
      color: var(--sb-bad);
    }
    .verdict {
      font-size: 22px;
      font-weight: 600;
      margin: 4px 0;
    }
    .verdict.worth_it {
      color: var(--primary-color);
    }
    .big {
      font-size: 26px;
      font-weight: 600;
      line-height: 1.2;
      font-variant-numeric: tabular-nums;
    }
    .rows {
      list-style: none;
      margin: 8px 0 0;
      padding: 0;
      display: flex;
      flex-direction: column;
    }
    .rows li {
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    .row {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 8px 0;
      width: 100%;
      box-sizing: border-box;
    }
    .rows li.row {
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    button.action {
      appearance: none;
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: start;
      cursor: pointer;
      border-radius: 6px;
      padding: 8px 4px;
    }
    button.action:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    button.action:focus-visible,
    button.link:focus-visible,
    button.outline:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 2px;
    }
    .what {
      display: flex;
      flex-direction: column;
      gap: 2px;
      flex: 1;
      min-width: 0;
    }
    .value {
      font-variant-numeric: tabular-nums;
    }
    .mark {
      flex: none;
      display: inline-grid;
      place-items: center;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      font-size: 12px;
      font-weight: 700;
      color: var(--sb-on-mark);
      background: var(--disabled-color, #9c9a93);
      margin-top: 1px;
    }
    .mark.alarm,
    .mark.unavailable {
      background: var(--sb-bad);
    }
    .mark.warning,
    .mark.stale,
    .mark.problem {
      background: var(--sb-warn);
    }
    .mark.clear,
    .mark.ok,
    .mark.fine {
      background: var(--sb-good);
    }
    .chip {
      flex: none;
      font-size: 12px;
      font-weight: 500;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid currentColor;
      color: var(--secondary-text-color);
      white-space: nowrap;
    }
    .chip.alarm,
    .chip.unavailable {
      color: var(--sb-bad);
    }
    .chip.warning,
    .chip.stale {
      color: var(--sb-warn);
    }
    .chip.ok,
    .chip.clear {
      color: var(--sb-good);
    }
    .chip.source {
      color: var(--primary-color);
    }
    .calm {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .warn-text {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--sb-warn);
    }
    details {
      margin-top: 8px;
    }
    summary {
      cursor: pointer;
      color: var(--secondary-text-color);
      font-size: 13px;
      padding: 4px 0;
    }
    .buildings {
      display: grid;
      gap: 16px;
      margin-top: 8px;
    }
    .building + .building {
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding-top: 12px;
    }
    .label {
      font-size: 13px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    button.link {
      appearance: none;
      border: 0;
      background: transparent;
      color: var(--primary-color);
      font: inherit;
      font-size: 13px;
      cursor: pointer;
      padding: 4px;
    }
    button.outline {
      appearance: none;
      border: 1px solid var(--primary-color);
      background: transparent;
      color: var(--primary-color);
      border-radius: 10px;
      min-height: 36px;
      padding: 0 14px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      margin-top: 4px;
    }
    button.outline:disabled {
      border-color: var(--disabled-color, #bdbdbd);
      color: var(--disabled-color, #bdbdbd);
      cursor: default;
    }
    .sr {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
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
      margin: 0 0 8px;
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

if (!customElements.get(STATUS_TAG)) {
  customElements.define(STATUS_TAG, SmartBoilerStatus);
}
