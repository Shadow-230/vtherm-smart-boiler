// What the overview shows now, from Home Assistant's entity states: the status with its reasons,
// the Control switch, and the tiles. A pure function: the component draws what it returns. A value
// whose entity is not picked in the settings is not shown; nothing is filled in.
import { formatNumber, formatTemperature, numberOf } from "./format";
import type { HassEntity, Installation } from "./types";

export type Translate = (key: string, values?: Record<string, string>) => string;

export interface Tile {
  key: string;
  label: string;
  value: string;
  detail: string;
}

export interface StatusView {
  title: string;
  detail: string;
  /** "burning": the burner is lit (heating or hot water); "called": the boiler is called for
   * heat, the burner not lit right now (between burns); "off": neither. */
  heat: HeatState;
  /** The control state's own code ("heating", "idle", …), or "monitoring" without control. */
  code: string;
}

export type HeatState = "burning" | "called" | "off";

export interface ControlView {
  entityId: string;
  on: boolean;
  available: boolean;
}

export interface LiveView {
  status: StatusView;
  control: ControlView | null;
  tiles: Tile[];
}

export interface LiveInputs {
  installation: Installation;
  states: Record<string, HassEntity>;
  language: string;
  t: Translate;
  /** Home Assistant's own text for an entity's state, in its language. */
  stateText: (entity: HassEntity) => string;
}

const CONDENSING_BELOW = 55; // °C, the usual return for condensing (the user guide's metric)

function state(inputs: LiveInputs, entityId: string | null | undefined): HassEntity | undefined {
  return entityId ? inputs.states[entityId] : undefined;
}

function signal(inputs: LiveInputs, name: string): HassEntity | undefined {
  return state(inputs, inputs.installation.signals[name]);
}

function plugin(inputs: LiveInputs, key: string): HassEntity | undefined {
  return state(inputs, inputs.installation.entities[key]);
}

/** Every zone of the installation, once — a zone in two circuits counts once. */
export function zoneIds(installation: Installation): string[] {
  return [...new Set(installation.circuits.flatMap((c) => c.zones.map((z) => z.entity_id)))];
}

/** The zones calling for heat, as the plugin counts them ("Calling for heat"). */
export function callingZones(inputs: LiveInputs): string[] {
  const calling = plugin(inputs, "demand_count")?.attributes.calling_zones;
  return Array.isArray(calling) ? calling.filter((z): z is string => typeof z === "string") : [];
}

function flameOn(inputs: LiveInputs): boolean {
  return signal(inputs, "flame")?.state === "on";
}

// The control states that call the boiler for heat (``core.boiler_call``), where the plugin's
// "Heat call" sensor is not there to say it.
const CALLING_MODES = new Set(["heating", "frost", "fallback"]);

/** Whether the boiler is lit, called for heat between burns, or neither: the plugin's "Heat
 * call" says whether it is called, else the control state does. */
function heatState(inputs: LiveInputs, flame: boolean): HeatState {
  if (flame) return "burning";
  const called = plugin(inputs, "boiler_called");
  if (called && called.state !== "unavailable" && called.state !== "unknown") {
    return called.state === "on" ? "called" : "off";
  }
  const control = plugin(inputs, "control_state");
  return control && CALLING_MODES.has(control.state) ? "called" : "off";
}

function statusView(inputs: LiveInputs): StatusView {
  const { t } = inputs;
  const flame = flameOn(inputs);
  const heat = heatState(inputs, flame);
  const control = plugin(inputs, "control_state");
  if (control && control.state !== "unavailable") {
    const reasons = control.attributes.reasons_text;
    return {
      title: inputs.stateText(control),
      detail: typeof reasons === "string" ? reasons : "",
      heat,
      code: control.state,
    };
  }
  const flameEntity = signal(inputs, "flame");
  const detail = !flameEntity
    ? t("status.monitoring_detail")
    : flame
      ? t("status.burner_on")
      : t("status.burner_off");
  return { title: t("status.monitoring"), detail, heat, code: "monitoring" };
}

function controlView(inputs: LiveInputs): ControlView | null {
  const entityId = inputs.installation.entities.control;
  const entity = state(inputs, entityId);
  if (!entityId || !entity) return null;
  return { entityId, on: entity.state === "on", available: entity.state !== "unavailable" };
}

function tiles(inputs: LiveInputs): Tile[] {
  const { t, language, installation } = inputs;
  const out: Tile[] = [];

  const setpoint = plugin(inputs, "control_setpoint");
  if (setpoint) {
    const requested = numberOf(String(setpoint.attributes.requested ?? ""));
    const readBack = numberOf(String(setpoint.attributes.read_back ?? ""));
    const confirmed = requested != null && readBack != null && Math.abs(requested - readBack) < 0.5;
    out.push({
      key: "water",
      label: t("tiles.water"),
      value: formatTemperature(requested, language),
      detail:
        requested == null
          ? t("tiles.water_none")
          : confirmed
            ? t("tiles.water_confirmed")
            : t("tiles.water_waiting"),
    });
  }

  const flow = signal(inputs, "flow");
  if (flow) {
    out.push({
      key: "flow",
      label: t("tiles.flow"),
      value: formatTemperature(numberOf(flow.state), language),
      detail: t("tiles.flow_detail"),
    });
  }

  const ret = signal(inputs, "return");
  if (ret) {
    const value = numberOf(ret.state);
    const condenses = installation.boiler.condensing && value != null && value < CONDENSING_BELOW;
    out.push({
      key: "return",
      label: t("tiles.return"),
      value: formatTemperature(value, language),
      detail: condenses ? t("tiles.return_condensing") : t("tiles.return_detail"),
    });
  }

  const outdoor = signal(inputs, "outdoor");
  const weather = state(inputs, installation.weather);
  const weatherTemperature = weather ? numberOf(String(weather.attributes.temperature ?? "")) : null;
  if (outdoor || weatherTemperature != null) {
    const sensor = outdoor ? numberOf(outdoor.state) : null;
    out.push({
      key: "outdoor",
      label: t("tiles.outdoor"),
      value: formatTemperature(sensor ?? weatherTemperature, language),
      detail: sensor != null ? t("tiles.outdoor_sensor") : t("tiles.outdoor_weather"),
    });
  }

  const flame = signal(inputs, "flame");
  if (flame) {
    const lit = flame.state === "on";
    const modulation = numberOf(signal(inputs, "modulation")?.state);
    const hotWater = signal(inputs, "dhw_active")?.state === "on";
    out.push({
      key: "flame",
      label: t("tiles.flame"),
      value: lit ? t("tiles.flame_on") : t("tiles.flame_off"),
      detail:
        lit && hotWater
          ? t("tiles.flame_hot_water")
          : lit && modulation != null
            ? t("tiles.flame_modulation", { value: formatNumber(modulation, language, 0) })
            : "",
    });
  }

  const zones = zoneIds(installation);
  if (zones.length && plugin(inputs, "demand_count")) {
    out.push({
      key: "rooms",
      label: t("tiles.rooms"),
      value: t("tiles.rooms_value", {
        calling: String(callingZones(inputs).filter((z) => zones.includes(z)).length),
        total: String(zones.length),
      }),
      detail: t("tiles.rooms_detail"),
    });
  }
  return out;
}

/** The overview's live part: what the boiler and control do now. */
export function liveView(inputs: LiveInputs): LiveView {
  return { status: statusView(inputs), control: controlView(inputs), tiles: tiles(inputs) };
}
