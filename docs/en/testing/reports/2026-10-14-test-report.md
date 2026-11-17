# Smart Boiler for Versatile Thermostat — test report

Status: history — kept as it was written, in English only. The current documents: [the documentation map](../../README.md).

**Tests in a real Home Assistant, 14 October 2026, on the `qas` branch (commit c488e90)**

This is the plain-language report. The detailed technical report, with every test and its
evidence, is [`unreleased.md`](unreleased.md), section 4.6. The report of the first round of tests
(8 to 11 October) is [`2026-10-11-test-report.md`](2026-10-11-test-report.md).

## In short

- We tested the version of the plugin that is ready for checking (`qas`), with the newest
  Versatile Thermostat, 10.5.1. Six copies of Home Assistant ran the tests side by side for about
  an hour.
- **Every test passed.** Four of them first failed because of our own test tools; we looked at
  each one closely and found that the plugin had done the right thing.
- **One small new fault:** when the water has to rise slowly to what a floor-heating circuit needs,
  it stops half a degree short (54.5 °C instead of 55 °C). The circuit still gets more than it
  needs.
- **Before the tests we found one fault in the plugin by reading its code.** One settings screen
  could not be saved on older installations. It was fixed before the tests, and the tests confirm
  the fix.
- **Updating the plugin while it controls the boiler works.** The plugin hands the boiler back
  safely when Home Assistant stops, and takes control again right after it starts.
- No real boiler was used. Nothing was connected to a real home.

## What changed since the first round

Since 11 October the plugin got new setup screens (a menu instead of a long chain of forms), new
data about the water that it shows in each room's thermostat, a number of small fixes found by
checking the tests themselves, and support for the newest Versatile Thermostat (10.5.1). Before
running anything we went through all 81 changes and listed what the tests would check and what
they could not.

## How we tested

- **Test computers.** The same separate, isolated test machine as before, with its firewall. We
  checked again that the test machine cannot reach the home network.
- **Simulated boiler and house**, with the real Versatile Thermostat 10.5.1 and SmartPI 0.4.0.
- **Each copy had its own job:**

| Copy | What it tested |
|---|---|
| 1 | The main setup (a gateway with a wall thermostat): updating while in control, hot water, the "Control mode" screen |
| 2 | The water data shown in each room, and settings the plugin must refuse |
| 3 | All rooms disappearing, reloading the plugin, a boiler that ignores commands |
| 4 | Versatile Thermostat's start delay |
| 6 | A simple on/off boiler switched by a relay |
| 7 | A boiler driven through a device that keeps the value it is given |

## Results

| Area | What we checked | Result |
|---|---|---|
| Updating | The plugin updated while controlling the boiler, as an update through HACS does. Its saved settings were converted to the new format without errors, and control came back at once. | Passed |
| Hot water | While hot water runs, the plugin pauses SmartPI's learning and resumes it after. It never touches the hot-water setting. | Passed |
| Water data in each room | Each room's thermostat shows the water temperature and whether heat reaches the room. It shows "no heat" while hot water runs, and "unknown" when the water sensor fails. | Passed (after review) |
| Settings it must refuse | Control is refused without the reading it needs, with an on/off contact on the thermostat terminals, or when the wiring is unknown. | Passed |
| "Monitoring only" | The new "Control mode" screen saves "monitoring only", and the plugin then writes nothing to the boiler. | Passed (the fault fixed before the tests) |
| Rooms disappearing | When all rooms disappear from Versatile Thermostat, the plugin waits, warns, and hands the boiler back to the wall thermostat. It takes control again when they return. | Passed |
| Reloading | Reloading the plugin hands the boiler back and resumes control. | Passed |
| Ignored commands | When the gateway ignores the plugin's commands, the plugin warns after a few tries and does not fight or keep repeating. | Passed |
| Start delay | With Versatile Thermostat's start delay of 2 minutes, the boiler waits 2 minutes before it starts. | Passed (after review) |
| Relay boilers | The relay follows the rooms. It is switched off and on again around a reload. When all rooms disappear, it does what the owner chose: hands the boiler back, or switches heating off. | Passed (one test repeated) |
| A circuit run by another automation | A floor-heating circuit with its own mixer asks for heat through a switch. The boiler heats for it even with no room asking, keeps the water above what it needs, and stops when it no longer asks. | Passed (after review), with the small fault below |
| Device-driven boilers | A device that restarts gets its value again. A device that restarts while control is being handed back still gets the hand-back once it returns. | Passed |

## Problems found

### The fault in the plugin (fixed before the tests)

On an installation set up before the plugin asked how the boiler is connected, the "Control mode"
screen could not be saved. Nothing was changed and the boiler was not affected, but the owner
could not switch to "monitoring only" from that screen. It was fixed (#127), and the test on
copy 1 confirms it.

### A small fault found in this round

When control is already on and a floor-heating circuit starts to ask for 50 °C, the plugin raises
the water slowly, 1 degree a minute, as it always does, towards 55 °C (the need plus a margin of
5 degrees). It stopped at 54.5 °C and stayed there. Switched on while the circuit was already
asking, it went to 55 °C at once. The circuit still got 4.5 degrees more than it needs, so the
house is not affected; the development session will look at why the last half degree is not sent.

### Problems in our own test tools

Four tests first failed because of the test tools, not the plugin. In each case the evidence
showed the plugin doing the right thing:

1. **Start delay.** The test measured the first wait from the wrong moment: the rooms had already
   asked for heat a little earlier, when the plugin was switched on. A second check, with the rooms
   quiet before they asked, measured 2 minutes and 7 seconds.
2. **Water data.** The test compared the room's "heat available" value with the burner at the
   moment it read it. But Versatile Thermostat updates that value only when it updates the room,
   which can be minutes later. At every update the value was right.
3. **Relay.** The test waited 2 minutes for the relay, but Versatile Thermostat had not opened the
   valves by then. Repeated, the test passed.
4. **Floor-heating circuit.** The test expected the water at 55 °C within a minute, but the plugin
   raises it slowly by design. A longer check showed the rise (and the half degree above).

These need small changes to the test tools; the development session makes them.

### What the test setup cannot show

- **Rooms with thermostatic radiator valves.** Versatile Thermostat 10.5.1 changed when such a
  room counts as "heating", and the plugin uses that to decide when to heat. Our simulated rooms
  use simple switches, so these tests cannot show it. A separate automated test with the real
  Versatile Thermostat was added for it (#130).
- **Some small fixes** to how the plugin judges the boiler's replies during hot water, and to the
  comfort correction, cannot be triggered by the simulator. They are covered by automated tests.

### Questions for the owner

The three questions from the first round are still open: the comfort correction's extra boiler
starts, the boiler starting more often in frost, and when the "long burn" warning should
trigger. These tests did not change them.

## Not tested

- The tests from the first round that these changes do not affect.
- How often the boiler starts (the comparison of 8 to 11 October). The test copies used for it
  were set up for this round instead; they need setting up again for that comparison.
- The newest `vtherm_api` (0.6.0). The test copies kept 0.5.0, which Versatile Thermostat 10.5.1
  accepts; 0.6.0 is checked only by the automated tests.

## Automated tests

On this version (`qas` c488e90): 2036 core tests and 3116 tests with Home Assistant passed, plus
the 4 known failures that wait for the decisions above. Style and type checks are clean. The early
warnings with the newest Versatile Thermostat, SmartPI and `vtherm_api` passed.
