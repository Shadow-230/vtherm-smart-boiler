// The installation (docs/en/development/plans/plan-0.2-i10.md, I10.3b): the schematic from
// schematic.ts, with the circuits taking water now. No rooms list: the rooms are VT's, on its own
// page (plan-0.2-i12.md, decision 6). It shows; it changes nothing.
import { LitElement, css, html, nothing, svg } from "lit";
import type { LiveInputs } from "./live";
import { localize } from "./localize";
import { VIEW_BOX, schematicView } from "./schematic";
import type { HomeAssistant, Installation } from "./types";

export const SCHEMATIC_TAG = "vtherm-smart-boiler-schematic";

const FLAME_PATH =
  "M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.3 1.6 1 2.6 2 3.1C11 9 11.3 6 12 3z";

/** A point of the drawing as a share of the box, for the labels laid over it. */
function percent(value: number, from: number, size: number): string {
  return `${(((value - from) / size) * 100).toFixed(2)}%`;
}

export class SmartBoilerSchematic extends LitElement {
  static properties = {
    hass: { attribute: false },
    installation: { attribute: false },
  };

  declare hass?: HomeAssistant;
  declare installation?: Installation;

  private t(key: string, values?: Record<string, string>): string {
    return localize(this.hass?.language, key, values);
  }

  private inputs(): LiveInputs | null {
    const hass = this.hass;
    if (!hass || !this.installation) return null;
    return {
      installation: this.installation,
      states: hass.states,
      language: hass.locale?.language ?? hass.language,
      t: (key, values) => this.t(key, values),
      stateText: (entity) => hass.formatEntityState?.(entity) ?? entity.state,
    };
  }

  render() {
    const inputs = this.inputs();
    if (!inputs) return nothing;
    const view = schematicView(inputs);
    const { paths } = view;
    const taking = view.circuits.filter((c) => c.active).map((c) => c.name);
    const status = view.labels[1]?.text ?? "";
    const box = `${VIEW_BOX.x} ${VIEW_BOX.y} ${VIEW_BOX.width} ${VIEW_BOX.height}`;
    return html`
      <section class="card">
        <h3>${this.t("schematic.title")}</h3>
        <div
          class="drawing"
          role="img"
          aria-label=${this.t("schematic.aria", {
            status,
            circuits: taking.length ? taking.join(", ") : this.t("schematic.nobody"),
          })}
        >
          <svg viewBox=${box} aria-hidden="true">
            <defs>
              <linearGradient id="sb-body" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="#fbfbfa"></stop>
                <stop offset="1" stop-color="#b9b8b2"></stop>
              </linearGradient>
              <linearGradient id="sb-hot" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="#e34948"></stop>
                <stop offset="1" stop-color="#2a78d6"></stop>
              </linearGradient>
              <linearGradient id="sb-still" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="#c9c8c2"></stop>
                <stop offset="1" stop-color="#8f8e88"></stop>
              </linearGradient>
            </defs>
            ${svg`
              <path class="body" d=${paths.body}></path>
              <path class="pipe gray" d=${paths.gray}></path>
              <path class="pipe blue" d=${paths.blue}></path>
              <path class="pipe red" d=${paths.red}></path>
              <path class="pipe mix" d=${paths.mix}></path>
              <path class="coil off" d=${paths.coilOff}></path>
              <path class="coil on" d=${paths.coilOn}></path>
              <path class="floor off" d=${paths.floorOff}></path>
              <path class="floor on" d=${paths.floorOn}></path>
              <path class="rad off" d=${paths.radOff}></path>
              <path class="rad on" d=${paths.radOn}></path>
              <path class="flow" d=${paths.flow}></path>
              <path class="arrow red" d=${paths.arrRed}></path>
              <path class="arrow blue" d=${paths.arrBlue}></path>
              <path class="valve off" d=${paths.valveOff}></path>
              <path class="valve on" d=${paths.valveOn}></path>
              <path class="pump" d=${paths.pumps}></path>
              <path class="pump-mark off" d=${paths.pumpOff}></path>
              <path class="pump-mark on" d=${paths.pumpOn}></path>
            `}
          </svg>
          <svg
            class="flame ${view.flame ? "lit" : ""}"
            viewBox="0 0 24 24"
            aria-hidden="true"
            style="left: ${percent(135, VIEW_BOX.x, VIEW_BOX.width)}; top: ${percent(185, VIEW_BOX.y, VIEW_BOX.height)}"
          >
            <path d=${FLAME_PATH}></path>
          </svg>
          ${view.labels.map((label) => {
            const style = `left: ${percent(label.x, VIEW_BOX.x, VIEW_BOX.width)}; top: ${percent(label.y, VIEW_BOX.y, VIEW_BOX.height)}`;
            return label.caption
              ? html`<span class="captioned" style=${style}
                  ><span class="text">${label.caption}</span><span class="${label.kind}">${label.text}</span></span
                >`
              : html`<span
                  class="${label.kind}${label.minor ? " minor" : ""}${label.end ? " end" : ""}${label.wrap ? " wrap" : ""}"
                  style=${style}
                  >${label.text}</span
                >`;
          })}
        </div>
        ${view.circuits.length
          ? html`<ul class="circuits">
              ${view.circuits.map(
                (circuit) => html`<li class=${circuit.active ? "on" : ""}>
                  <span class="strong">${circuit.name}</span>
                  <span class=${circuit.active ? "takes" : "muted"}
                    >${circuit.active ? this.t("schematic.takes_heat") : this.t("schematic.no_heat")}</span
                  >
                </li>`,
              )}
            </ul>`
          : nothing}
        <div class="legend">
          <span><i class="hot"></i>${this.t("schematic.legend_hot")}</span>
          <span><i class="mixed"></i>${this.t("schematic.legend_mixed")}</span>
          <span><i class="cold"></i>${this.t("schematic.legend_return")}</span>
          <span><i class="still"></i>${this.t("schematic.legend_idle")}</span>
          <span>${this.t("schematic.legend_moving")}</span>
        </div>
      </section>
    `;
  }

  static styles = css`
    :host {
      display: block;
      container-type: inline-size;
      --sb-hot: #e34948;
      --sb-cold: #2a78d6;
      --sb-mix: #eb6834;
      --sb-still: #a9a8a2;
      --sb-line: #6b6964;
      --sb-pump: #1f9d3a;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 14px;
      box-sizing: border-box;
      min-width: 0;
    }
    h3 {
      margin: 0 0 6px;
      font-size: 16px;
      font-weight: 600;
    }
    .drawing {
      position: relative;
      width: 100%;
      aspect-ratio: 1000 / 500;
    }
    .drawing > svg:first-child {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
    }
    .body {
      fill: url(#sb-body);
      stroke: var(--sb-line);
      stroke-width: 1.5;
    }
    .pipe {
      fill: none;
      stroke-width: 7;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .pipe.red {
      stroke: var(--sb-hot);
    }
    .pipe.blue {
      stroke: var(--sb-cold);
    }
    .pipe.mix {
      stroke: var(--sb-mix);
    }
    .pipe.gray {
      stroke: var(--sb-still);
    }
    .flow {
      fill: none;
      stroke: rgba(255, 255, 255, 0.9);
      stroke-width: 2.5;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-dasharray: 3 13;
      animation: flow 0.8s linear infinite;
    }
    @keyframes flow {
      to {
        stroke-dashoffset: -32;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .flow {
        animation: none;
      }
    }
    .coil,
    .floor {
      fill: none;
      stroke-linejoin: round;
      stroke-linecap: round;
    }
    .coil {
      stroke-width: 4;
    }
    .floor {
      stroke-width: 6;
    }
    .coil.on {
      stroke: var(--sb-hot);
    }
    .floor.on {
      stroke: url(#sb-hot);
    }
    .coil.off,
    .floor.off {
      stroke: var(--sb-still);
    }
    .rad {
      stroke: var(--sb-line);
      stroke-width: 1;
    }
    .rad.on {
      fill: url(#sb-hot);
    }
    .rad.off {
      fill: url(#sb-still);
    }
    .arrow.red {
      fill: var(--sb-hot);
    }
    .arrow.blue {
      fill: var(--sb-cold);
    }
    .valve {
      stroke: var(--sb-line);
      stroke-width: 1;
    }
    .valve.on {
      fill: var(--sb-pump);
    }
    .valve.off {
      fill: #d6d5cf;
    }
    .pump {
      fill: #f4f4f2;
      stroke: var(--sb-line);
      stroke-width: 1.5;
    }
    .pump-mark.on {
      fill: var(--sb-pump);
    }
    .pump-mark.off {
      fill: var(--sb-still);
    }
    .flame {
      position: absolute;
      width: 4%;
      height: auto;
      aspect-ratio: 1;
      transform: translate(-50%, -50%);
      fill: none;
      stroke: var(--sb-still);
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
      pointer-events: none;
    }
    .flame.lit {
      stroke: var(--state-climate-heat-color, #ff8100);
    }
    .text,
    .value,
    .captioned {
      position: absolute;
      transform: translate(-50%, -50%);
      white-space: nowrap;
      pointer-events: none;
    }
    .text,
    .inside {
      position: absolute;
      transform: translate(-50%, -50%);
      white-space: nowrap;
      pointer-events: none;
      font-size: clamp(8px, 1.55cqw, 12px);
    }
    .text.end {
      transform: translate(-100%, -50%);
    }
    /* The boiler's state wraps inside its body (150 of the drawing's 1000 wide) at any width. */
    .inside.wrap {
      font-size: clamp(7.5px, 1.55cqw, 12px); /* a long word still fits the boiler's body */
      white-space: normal;
      width: 13%;
      text-align: center;
      line-height: 1.15;
    }
    /* A value with its name above it, as one block. */
    .captioned {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
    }
    .captioned > span {
      position: static;
      transform: none;
    }
    .text {
      color: var(--secondary-text-color);
    }
    .inside {
      color: #3d3c38; /* the boiler's body is light in every theme */
    }
    .value {
      background: #1d1d1c;
      color: #fff;
      font-weight: 600;
      font-size: clamp(9px, 1.7cqw, 13px);
      padding: 0.22em 0.6em;
      border-radius: 6px;
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.18);
      font-variant-numeric: tabular-nums;
    }
    /* The circuits by name, in a narrow card only: there the drawing leaves its labels out, so
       they would overlap. */
    .circuits {
      display: none;
      list-style: none;
      margin: 6px 0 0;
      padding: 0;
      flex-direction: column;
      gap: 4px;
      font-size: 13px;
    }
    .circuits li {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 8px;
      padding: 4px 8px;
      border-radius: 8px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }
    .circuits li.on {
      border-color: var(--sb-mix);
    }
    @container (max-width: 480px) {
      .minor {
        display: none;
      }
      .circuits {
        display: flex;
      }
    }
    .takes {
      color: var(--sb-mix);
    }
    .strong {
      font-weight: 600;
    }
    .muted {
      color: var(--secondary-text-color);
      font-weight: 500;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 16px;
      font-size: 12px;
      color: var(--secondary-text-color);
      padding: 12px 2px 0;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .legend i {
      display: inline-block;
      width: 16px;
      height: 5px;
      border-radius: 3px;
    }
    .legend .hot {
      background: var(--sb-hot);
    }
    .legend .mixed {
      background: var(--sb-mix);
    }
    .legend .cold {
      background: var(--sb-cold);
    }
    .legend .still {
      background: var(--sb-still);
    }
  `;
}

if (!customElements.get(SCHEMATIC_TAG)) {
  customElements.define(SCHEMATIC_TAG, SmartBoilerSchematic);
}
