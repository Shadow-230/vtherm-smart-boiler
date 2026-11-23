# Device templates — one parameter file per boiler device

Status: history — kept as it was written, in English only; only the ✅ of a finished step is still added. The current documents: [the documentation map](../../README.md).

Goal: what differs between boiler connections moves out of the code's tables into one YAML file
per device, so that a new variant of a known kind needs a file, not a code change. What control
does, and every safety rule around it, stays as it is. After the first release, before 0.3.

## The user's decisions (2026-11-22)

1. **A template of parameters**, not a plugin that works a device out by itself: each device has
   its file, and the fields describe how it behaves.
2. **In English**, with the field names chosen before anything is written:
   [`device-connections.md`](../../specification/device-connections.md).
3. **Three layers:** `protocol`, `behaviour`, and `access`, a list of routes, as one device runs
   over different protocols and integrations, Wi-Fi and makers' clouds included.
4. **The limits:** a template chooses among mechanisms in the code and never describes their
   steps; it cannot get round a safety rule, and a file that fails its check leaves the connection
   at monitoring.
5. **YAML**, shipped with a release after review. **No user files** in the first version.
6. **No control through a cloud** (#208), before the first release.
7. **After the beta, before 0.3:** moving the tables touches the code that writes to a boiler.

## Steps

Each step is its own pull request. In each, a test shows every connection gets exactly the options
it gets today; if one differs, work stops and the user is asked. Entries need no migration: an
`access` `id` is the connection text they store.

| Step | What | Tests |
|---|---|---|
| T1 | Format and check: the loader, the check, and the files for today's eight connections, not yet used | the files' values equal today's tables |
| T2 | What a connection can do: modes, topologies and write path read from the file | every connection as before |
| T3 | Forms: defaults and required confirmations from the file | the options flow as before |
| T4 | Setpoint and heating off: parameters from the file; the safety rules stay in the code and can refuse a file | a file that breaks a rule is refused |
| T5 | Writing: service names and commands from the file, the mechanisms unchanged | the writers' calls as before; J4 after this step |
| T6 | Readings: MQTT topics, report rhythm, values that mean unknown, how the gateway's entities are told | freshness and alarms as before |
| T7 | Tests: the simulator runs each template by parameter; a test keeps the document's cards equal to the files | |
| T8 | The proof: DIYLess on ESPHome added as a file only, with no code change | |
| T9 🔒 | The whole J4, and the user's decision before a release | |
