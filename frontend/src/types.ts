// The parts of Home Assistant's frontend objects the page reads, and what the plugin's WebSocket
// commands answer (custom_components/vtherm_smart_boiler/websocket_api.py). Home Assistant passes
// a sidebar page `hass`, `narrow`, `route` and `panel`.

export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
  last_changed: string;
  last_updated: string;
}

export interface HomeAssistant {
  language: string;
  locale?: { language: string };
  user?: { is_admin: boolean; name?: string };
  themes?: { darkMode?: boolean };
  states: Record<string, HassEntity>;
  callWS<T>(message: Record<string, unknown>): Promise<T>;
  callService(domain: string, service: string, data?: Record<string, unknown>): Promise<unknown>;
  formatEntityState?(entity: HassEntity, state?: string): string;
}

export interface PanelInfo {
  config?: { entry_id?: string };
}

export interface ZoneInfo {
  entity_id: string;
  emitter: "radiator" | "underfloor" | "convector";
}

export interface CircuitInfo {
  id: string;
  name: string;
  control: "unmixed_shared" | "through_boiler" | "separate" | "passive_fixed";
  fixed_temperature: number | null;
  max_flow: number | null;
  needed: number | null;
  zones: ZoneInfo[];
}

export interface CurveSettings {
  entered: boolean;
  design_outdoor: number;
  design_flow: number;
  room: number;
  exponent: number;
  offset: number;
  hard_min: number;
  hard_max: number;
  circuit_max: number | null;
  boiler_max: number | null;
  room_auto: boolean;
  comfort_correction: boolean;
  correction_max_k: number;
  /** The settings' advanced level: the offset can be saved. */
  advanced: boolean;
}

export interface Installation {
  entry_id: string;
  title: string;
  boiler: { type: string | null; dhw: string; condensing: boolean };
  circuits: CircuitInfo[];
  signals: Record<string, string>;
  weather: string | null;
  entities: Record<string, string>;
  curve: CurveSettings | null;
}
