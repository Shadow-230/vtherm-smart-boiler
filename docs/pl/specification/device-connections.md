[English version](../../en/specification/device-connections.md)

# Połączenia kotła i szablon urządzenia

Status: aktualny. **Wtyczka jeszcze nie czyta tych plików.** Dziś te same fakty są w jej kodzie.
Ten dokument zapisuje je urządzenie po urządzeniu, w formacie, który wtyczka będzie czytać po
pierwszym wydaniu ([plan](../../en/development/plans/plan-device-templates.md)). Nazwy i wartości są
po angielsku w każdym języku.

## 1. Trzy warstwy

Do jednego urządzenia można dotrzeć kilkoma drogami i każda może działać inaczej. Dlatego szablon
ma trzy warstwy:

1. **`protocol`**: czym urządzenie rozmawia z kotłem (`opentherm`, `ems`, `ebus`, `bsb`, `on_off`,
   `proprietary`, `unknown`).
2. **`behaviour`**: co urządzenie robi, niezależnie od drogi dostępu: jak trzyma nastawę, jak
   wyłącza grzanie, jak oddaje kocioł i co robi z ciepłą wodą. Od tej warstwy zależy
   bezpieczeństwo.
3. **`access`**: lista dróg z Home Assistanta do urządzenia. Każda ma własne `id`, integrację,
   polecenia, odczyty i poziom sprawdzenia.

`id` drogi to nazwa połączenia, którą instalacja zapisuje już dziś (`opentherm_gw`, `otgw_mqtt` …),
więc przejście na szablony nie wymaga migracji.

Pliki są w YAML, po jednym na urządzenie, i po przeglądzie trafiają do wydania. W pierwszej wersji
użytkownicy nie mogą dodawać własnych, bo szablon decyduje o tym, co trafia do kotła.

## 2. Czego szablon nie może

Szablon **wybiera** spośród mechanizmów w kodzie. Nie opisuje ich kroków.

- **Zapis:** usługa, polecenie MQTT, encja, przekaźnik.
- **Wyłączenie grzania:** przełącznik, flaga bramki, wartość nastawy, przekaźnik.
- **Oddanie kotła:** wartość, limit czasu, przełącznik, zwolnienie bramki, stan spoczynkowy
  przekaźnika.

Urządzenie, które z nich korzysta, potrzebuje tylko pliku. Nowy mechanizm wymaga kodu i testów.

Te zasady zostają w kodzie i obowiązują bez względu na treść pliku:

- nic nie trafia do stałej pamięci kotła, a nieznany typ zapisu nie jest zapisywany;
- oddanie przez limit czasu wymaga nastawy, która wygasa;
- „wyłączenie” niską nastawą tylko tam, gdzie urządzenie samo wraca do swojego sterowania;
- limity temperatury wody i strażnicy zapisu nie są parametrami;
- **nic nie jest zapisywane przez usługę w chmurze** ([rozdział 6](#6-wi-fi-i-chmura));
- wtyczka nigdy nie zapisuje ciepłej wody (`dhw.write` to zawsze `none`).

Plik, który nie przejdzie sprawdzenia, zostawia to połączenie w samym monitoringu.

## 3. Pola

Najwyższy poziom: `schema_version`, `id`, `name`, `protocol`, `behaviour`, `access`. Jednostka jest
na końcu nazwy: `_s` to sekundy, `_c` to °C.

**`behaviour`**

| Pole | Wartości | Znaczenie |
|---|---|---|
| `topologies` | `gateway_standalone`, `gateway_with_thermostat`, `virtual` | jak urządzenie może stać między Home Assistantem a kotłem |
| `setpoint.write_type`, `ch.write_type` | `expiring`, `held`, `persistent`, `unknown` | jak urządzenie trzyma zapisaną wartość; `unknown`: deklaruje to użytkownik, a do tego czasu nic nie jest zapisywane |
| `setpoint.expires_after_s`, `repeat_every_s`, `min_c` | liczby | kiedy wartość wygasa, jak często jest powtarzana, najniższa wartość, którą urządzenie traktuje jako wygasającą |
| `ch.off_method` | `switch`, `gateway_flag`, `setpoint`, `relay` | jak wyłączane jest grzanie |
| `ch.off_setpoint_c` | liczba | wartość oznaczająca „wyłącz” przy `off_method: setpoint` |
| `hand_back.method` | `value`, `timeout`, `switch`, `gateway_release`, `relay_rest` | jak kocioł jest oddawany |
| `hand_back.value`, `timeout_s` | liczby | parametry tej metody |
| `hand_back.confirmed_by` | `read_back`, `none` | co pokazuje, że kocioł został oddany |
| `on_ha_stop.effect` | `setpoint_lapses`, `held_until_restart`, `stays`, `unknown` | co się dzieje, gdy Home Assistant stanie |
| `on_ha_stop.within_s` | liczba | jak szybko, domyślnie |
| `dhw.write` | `none` | wtyczka nigdy nie zapisuje ciepłej wody |
| `dhw.active_source` | `status_bit`, `entity`, `inferred`, `none` | skąd wiadomo o grzaniu ciepłej wody |
| `dhw.enable_kept_by` | `thermostat`, `device`, `not_kept`, `unknown` albo osobno dla topologii | kto pilnuje zezwolenia na ciepłą wodę |
| `dhw.flow_during_draw` | `dhw_water`, `ch_water`, `unknown` | co pokazuje temperatura zasilania podczas poboru; zależy to od kotła, więc szablon zostawia `unknown` |
| `dhw.signals` | `active`, `enable`, `setpoint`, `setpoint_bounds`, `temperature`, `flow_rate`, `burner_starts`, `burner_hours`, `pump_starts`, `pump_hours` | co urządzenie może zgłaszać |
| `fault_details.needs_indication` | `true`, `false` | szczegóły usterki liczą się tylko przy włączonym ogólnym wskaźniku usterki kotła |
| `safety.must_confirm` | nazwy ustawień | co użytkownik musi potwierdzić przed sterowaniem |
| `safety.known_limits` | nazwy | o czym trzeba powiedzieć użytkownikowi |

Typu kotła (dwufunkcyjny, z zasobnikiem) i priorytetu ciepłej wody tu nie ma: należą do instalacji,
a nie do sposobu podłączenia.

**Każda droga w `access`**

| Pole | Wartości | Znaczenie |
|---|---|---|
| `id` | nazwa połączenia | taka, jak zapisana w instalacji |
| `integration` | domena Home Assistanta | brak, gdy pasuje każda integracja |
| `link` | `local`, `cloud` | tylko tam, gdzie Home Assistant tego nie wie, na przykład za mostem MQTT |
| `verified` | zobacz rozdział 4 | na ile ta droga została sprawdzona |
| `boiler_class` | `flow_setpoint`, `on_off`, `read_only`, `by_mode` | co wtyczka może zrobić z kotłem |
| `control_modes` | `full`, `on_off`, `monitor` | co użytkownik może wybrać |
| `setup_fields` | nazwy pól | o co pyta konfiguracja |
| `transport.type` | `service`, `mqtt`, `entity`, `relay`, `none` | którędy idą polecenia |
| `transport.domain`, `command_topic`, `setpoint_command`, `ch_command` | tekst | polecenia |
| `gateway_source` | `platform`, `same_device`, `none` | jak rozpoznać encje samej bramki |
| `readings.report_mode` | `periodic`, `on_change`, `unknown` | jak urządzenie raportuje |
| `readings.report_every_s`, `heartbeat_s` | liczby | jego rytm |
| `readings.unknown_values` | sygnał: wartość | wartość oznaczająca „nieznane” |
| `readings.signal_topics` | sygnał: temat | tematy MQTT; `"*"`: jedna wiadomość zgłasza wszystkie sygnały |

## 4. Na ile droga została sprawdzona

| `verified` | Znaczenie |
|---|---|
| `real_device` | działała na prawdziwym kotle |
| `simulator` | przeszła J4 na testowym Home Assistancie z symulatorem |
| `documents` | odczytana ze źródeł lub dokumentów urządzenia i przetestowana w kodzie |
| `none` | niesprawdzona |

**Żadna droga nie działała jeszcze na prawdziwym kotle.** Pierwsza będzie na etapie K6.

## 5. Karty

### OpenTherm Gateway

```yaml
schema_version: 1
id: otgw
name: OpenTherm Gateway
protocol: opentherm
behaviour:
  topologies: [gateway_standalone, gateway_with_thermostat]
  setpoint: {write_type: expiring, expires_after_s: 60, repeat_every_s: 30, min_c: 8}
  ch: {write_type: held, off_method: gateway_flag}
  hand_back: {method: gateway_release, confirmed_by: read_back}
  on_ha_stop: {effect: setpoint_lapses, within_s: 60}
  dhw:
    write: none
    active_source: status_bit
    enable_kept_by: {gateway_with_thermostat: thermostat, gateway_standalone: not_kept}
    flow_during_draw: unknown
    signals: [active, enable, setpoint, setpoint_bounds, temperature]
  fault_details: {needs_indication: true}
  safety: {must_confirm: [], known_limits: [read_back_is_gateway_echo]}
access:
  - id: opentherm_gw
    integration: opentherm_gw
    verified: simulator
    boiler_class: flow_setpoint
    control_modes: [full, monitor]
    setup_fields: [gateway_id]
    transport:
      type: service
      domain: opentherm_gw
      setpoint_command: set_control_setpoint
      ch_command: set_central_heating_ovrd
    gateway_source: platform
    readings:
      report_mode: periodic
      unknown_values: {flow: 0, return: 0, pressure: 0, flue_gas: 0, outdoor: 0, room_temperature: 0}
  - id: otgw_mqtt
    integration: mqtt
    verified: documents
    boiler_class: flow_setpoint
    control_modes: [full, monitor]
    setup_fields: [mqtt_top, mqtt_node]
    transport:
      type: mqtt
      command_topic: "{mqtt_top}/set/{mqtt_node}/{command}"
      setpoint_command: ctrlsetpt
      ch_command: chenable
    gateway_source: same_device
    readings:
      report_mode: on_change
      heartbeat_s: 60
      unknown_values: {flow: 0, return: 0, pressure: 0, flue_gas: 0, outdoor: 0, room_temperature: 0}
      signal_topics:
        flame: flame
        flow: Tboiler
        return: Tret
        modulation: RelModLevel
        pressure: CHPressure
        dhw_active: domestichotwater
        ch_active: centralheating
        fault_indication: fault
        outdoor: Toutside
        flue_gas: Texhaust
        ch_setpoint: TSet
```

`CS` wygasa, jeśli nie jest powtarzane, a `CH=0` trwa do `CH=1` albo resetu bramki. Bez termostatu
bramka nie utrzymuje zezwolenia na ciepłą wodę. Na drodze MQTT encje napisane ręcznie w YAML nie mają
urządzenia w Home Assistancie: liczą się jako encje bramki, gdy jej nastawa też go nie ma.

### ESPHome OpenTherm

```yaml
schema_version: 1
id: esphome_opentherm
name: ESPHome OpenTherm
protocol: opentherm
behaviour:
  topologies: [virtual]
  setpoint: {write_type: held}
  ch: {write_type: held, off_method: switch}
  hand_back: {method: value, confirmed_by: read_back}
  on_ha_stop: {effect: held_until_restart, within_s: 900}
  dhw:
    write: none
    active_source: status_bit
    enable_kept_by: device
    flow_during_draw: unknown
    signals: [active, enable, setpoint, temperature]
  fault_details: {needs_indication: false}
  safety: {must_confirm: [esphome_safe_start], known_limits: [low_setpoint_leaves_ch_enabled]}
access:
  - id: esphome
    integration: esphome
    verified: documents
    boiler_class: flow_setpoint
    control_modes: [full, monitor]
    setup_fields: [setpoint_entity, ch_entity]
    transport: {type: entity}
    gateway_source: none
    readings: {report_mode: on_change}
```

ESP trzyma ostatnie wartości do restartu, domyślnie 15 minut po utracie API Home Assistanta, a potem
przyjmuje własne wartości startowe. Niska nastawa zostawia grzanie włączone, dlatego grzanie
wyłącza jego przełącznik.

### EMS-ESP

```yaml
schema_version: 1
id: ems_esp
name: EMS-ESP
protocol: ems
behaviour:
  topologies: [virtual]
  setpoint: {write_type: expiring, expires_after_s: 60, repeat_every_s: 30}
  ch: {write_type: unknown, off_method: setpoint, off_setpoint_c: 0}
  hand_back: {method: timeout, timeout_s: 60}
  on_ha_stop: {effect: setpoint_lapses, within_s: 60}
  dhw:
    write: none
    active_source: entity
    enable_kept_by: device
    flow_during_draw: unknown
    signals: [active, setpoint, temperature]
  fault_details: {needs_indication: false}
  safety: {must_confirm: [], known_limits: [setpoint_only_below_panel_setting]}
access:
  - id: ems_esp
    integration: mqtt
    verified: documents
    boiler_class: flow_setpoint
    control_modes: [full, monitor]
    setup_fields: [ems_esp_base, setpoint_entity]
    transport: {type: entity}
    gateway_source: none
    readings:
      report_mode: periodic
      report_every_s: 10
      signal_topics: {"*": [boiler_data, boiler_data_dhw]}
```

`selflowtemp` wygasa w ciągu około minuty, a powtarzane 0 trzyma grzanie wyłączone. Kocioł przyjmuje
nastawę z magistrali tylko poniżej ustawienia na własnym panelu.

### Przekaźnik przy kotle włącz/wyłącz

```yaml
schema_version: 1
id: relay
name: Relay on an on/off boiler
protocol: on_off
behaviour:
  ch: {off_method: relay}
  hand_back: {method: relay_rest}
  on_ha_stop: {effect: stays}
  dhw: {write: none, active_source: none, enable_kept_by: unknown, flow_during_draw: unknown}
  fault_details: {needs_indication: false}
access:
  - id: relay
    verified: simulator
    boiler_class: on_off
    control_modes: [on_off, monitor]
    setup_fields: [relay_entity]
    transport: {type: relay}
    gateway_source: none
    readings: {report_mode: unknown}
```

Timery i powtórzenia przekaźnika to jego własny mechanizm, ustawiany w formularzu przekaźnika.

### Moduł Wi-Fi kotła lub integracja producenta

```yaml
schema_version: 1
id: boiler_module
name: The boiler's Wi-Fi module or the maker's integration
protocol: proprietary
behaviour:
  topologies: [gateway_standalone, gateway_with_thermostat, virtual]
  setpoint: {write_type: unknown}
  ch: {write_type: unknown, off_method: switch}
  on_ha_stop: {effect: unknown}
  dhw: {write: none, active_source: entity, enable_kept_by: unknown, flow_during_draw: unknown}
  fault_details: {needs_indication: false}
access:
  - id: boiler_module
    verified: none
    boiler_class: by_mode
    control_modes: [full, monitor]   # through a cloud: monitoring only
    setup_fields: [setpoint_entity, ch_entity]
    transport: {type: entity}
    gateway_source: none
    readings: {report_mode: unknown}
```

Z góry nic nie wiadomo, więc nic nie jest zapisywane, dopóki użytkownik nie zadeklaruje, jak encja
trzyma wartość. Przez chmurę zostaje sam monitoring.

### Inna zapisywalna encja

```yaml
schema_version: 1
id: other_entity
name: Another writable entity
protocol: unknown
behaviour:
  topologies: [gateway_standalone, gateway_with_thermostat, virtual]
  setpoint: {write_type: unknown}
  ch: {write_type: unknown, off_method: switch}
  on_ha_stop: {effect: unknown}
  dhw: {write: none, active_source: entity, enable_kept_by: unknown, flow_during_draw: unknown}
  fault_details: {needs_indication: false}
access:
  - id: other_entity
    verified: simulator
    boiler_class: flow_setpoint
    control_modes: [full, monitor]   # through a cloud: monitoring only
    setup_fields: [setpoint_entity, ch_entity]
    transport: {type: entity}
    gateway_source: none
    readings: {report_mode: unknown}
```

Użytkownik uzupełnia to, co ta karta zostawia jako `unknown`.

### Inna integracja, tylko odczyt

```yaml
schema_version: 1
id: read_only
name: Another integration, read only
protocol: unknown
behaviour:
  dhw: {write: none, active_source: entity, enable_kept_by: unknown, flow_during_draw: unknown}
access:
  - id: read_only
    verified: none
    boiler_class: read_only
    control_modes: [monitor]
    setup_fields: []
    transport: {type: none}
    gateway_source: none
    readings: {report_mode: unknown}
```

## 6. Wi-Fi i chmura

Wi-Fi to sposób, w jaki urządzenie się łączy. Nie mówi, dokąd idą polecenia. Home Assistant to wie:
manifest każdej integracji ma pole `iot_class`.

| `iot_class` | Przykłady | Sterowanie |
|---|---|---|
| `local_push` | `opentherm_gw`, `mqtt`, `esphome` | dozwolone |
| `local_polling` | `incomfort`, `bsblan` | dozwolone |
| `cloud_polling`, `cloud_push` | `vicare`, `evohome` | **tylko monitoring** |

Chmura nie nadaje się do tego sterowania. Bez internetu wtyczka nie mogłaby oddać kotła, a usługi w
chmurze ograniczają liczbę wywołań. Na przykład w darmowym planie Viessmanna limit to 1450 wywołań na
dobę, a po jego przekroczeniu konto jest blokowane na 24 godziny; samo odpytywanie przez Home
Assistant zajmuje 1440.

Wtyczka nie widzi pomocnika ani mostu MQTT postawionego przed chmurą, a integrację, która nie podaje
`iot_class`, uznaje za lokalną. Szablon może podać `link: cloud` dla drogi, którą zna.

## 7. Drogi jeszcze nieopisane

Te drogi istnieją, ale nie mają własnej karty. Dziś działają tylko jako „inna zapisywalna encja”,
tam gdzie oferują zapisywalne encje:

- ESPHome przez MQTT zamiast natywnego API, z własnym `reboot_timeout`;
- interfejsy REST firmware OTGW, EMS-ESP i DIYLess;
- DIYLess, na własnym firmware albo na ESPHome;
- inne magistrale i mosty kotłów, na przykład eBUS albo BSB-LAN.
