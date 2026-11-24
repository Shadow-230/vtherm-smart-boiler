# Smart Boiler for Versatile Thermostat — test report

Status: history — kept as it was written, in English only. The current documents: [the documentation map](../../README.md).

**Tests in a real Home Assistant, 22 to 24 November 2026, on the `qas` branch (commits 7b34657 and 76559e7)**

This is the plain-language report. The detailed technical report is [`unreleased.md`](unreleased.md):
- section 4.10 for these runs, and section 5 for the starts;
- the findings F21 and L17 to L19 in section 7.

The report of the tests before it is [`2026-11-22-i11-test-report.md`](2026-11-22-i11-test-report.md).

## In short

- **We tested only what had changed, as you asked.** There were two code versions:
  - 7b34657: a more typical simulated house, a light bedroom for SmartPI (the regulation that learns how a room heats, in Versatile Thermostat — VT — which runs the rooms), and the Boiler page's display fixes;
  - 76559e7: two safeguards. One recognises a gateway connected over MQTT. The other blocks control through an integration that says it works through a cloud.
- **Every scenario passed.** The only fault found is small, on the Boiler page's display (below).
- **The test that could never run before now passes (Q5).** In the new light bedroom, SmartPI finished learning in 7 h 41 min, with the plugin controlling the boiler. The warning then named only the room that could not reach its setpoint.
- **The boiler's starts stay within the rule** (VT's 15-min cycle, in the new house). The rule: no more than 1.1 times the starts of the boiler's own regulation, or no more than 6 starts an hour with burns of at least 10 minutes.
  - At +8 °C the starts were the same (×1.01).
  - At −5 °C there were more (×1.42), but about 2 starts an hour with burns of about 12 minutes, which is within the rule.
  - The rooms were as warm or slightly warmer.
  - You ended the measurement 12 hours early. The day it counts is still a whole day, after the first 12 hours of settling. At −5 °C the plugin started the boiler far more often in the warmer half of the day than in the colder half. That warmer half came right after the settling, so from one day we cannot tell whether the difference comes from the time of day or from the house still settling.
- **The Boiler page:** the status is in the user's language, and the times follow the profile's time zone. The days and the starts by hour stay in Home Assistant's time zone. A dash in Use now comes with its reason. One small thing is left: in a very narrow dashboard column the labels on the schematic overlap.
- **The two safeguards break nothing.** The new "cloud" block appears on no setup, the control settings save, and the boiler-fault test still passes.
- **What the bench cannot show:** the bench has no MQTT gateway and no cloud integration, so neither safeguard shows its own effect here. Only tests in the code cover them.

## What we tested

| Area | Result |
|---|---|
| The comfort correction (raising the water when rooms stay cold): rising, its limit written exactly, its warning (Q1, E4) | works |
| One room that cannot reach its setpoint while the others hold (Q5) | works, the first time |
| "Water too cool" when the curve is too low (Q2) | works |
| The heating curve's room temperature in Auto (Q3; the curve sets the water's temperature by the outdoor one) | works |
| A hot-water draw under control: SmartPI paused and resumed (D8) | works |
| 12 hours of control at −2 °C (L1) | works; the light bedroom not too warm; two rooms 1.3–1.9 °C short, told as "water too cool" (the default curve is too low in that frost — known) |
| The relay, the boiler's own entities, a stand-alone gateway (R9, N1, S1) | works, on both versions |
| The boiler's own fault (F1) | works on the new version |
| What the Boiler page reads from the plugin (P2) | works, on both versions |
| The page by hand: language, time zones, the reasons, a narrow column | works, but for the labels in a narrow column |
| The starts against the boiler's own regulation, VT's 15-min cycle | met: ×1.01 at +8 °C; ×1.42 at −5 °C but about 2 starts an hour, 12-minute burns; the rooms as warm |

## Not tested, and why

- **Scenarios whose code did not change**, and the new house changes only how fast the rooms warm or cool.
- **VT's 5-min cycle in the starts test.** You left it out. It is expected to fail as before, which is why the plugin advises 10–15 min.
- **The safeguards' own effect**, for the reason above.
- **The same things as before:**
  - "Forget" for the measured building values;
  - the curve's offset at the simple settings level;
  - an English title in the sidebar;
  - removing the plugin;
  - a whole week of gas data.
