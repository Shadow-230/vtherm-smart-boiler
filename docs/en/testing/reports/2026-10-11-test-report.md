# Smart Boiler for Versatile Thermostat — test report

Status: history — kept as it was written, in English only. The current documents: [the documentation map](../../README.md).

**Tests in a real Home Assistant, 8 to 11 October 2026**

This is the plain-language report. The detailed technical report, with every test and its
evidence, is [`unreleased.md`](unreleased.md).

## In short

- We tested the plugin for four days in real Home Assistant installations, with a simulated
  boiler and house. In all, there were about 120 test runs.
- **The plugin did what it is designed to do in almost every case.** It kept the boiler under
  control, followed the rooms, and always gave control back safely when it should.
- **We found one real fault in the plugin.** It has been fixed, and the fix has been confirmed.
- **Three things need a decision by the owner** before the first release:
  1. The new "comfort correction" setting, now switched on by default, makes the boiler start
     much more often in cold weather, for almost no extra warmth.
  2. In frost, the plugin makes the boiler start more often than the boiler would on its own.
  3. The new "long burn" warning can miss a boiler that keeps switching on and off.
- No real boiler was used. Nothing was connected to a real home.

## What the plugin does

The plugin controls a home's gas boiler for Versatile Thermostat (VT). VT decides which rooms need
heat. The plugin decides how hot the water in the radiators should be, and when the boiler should
heat. When the plugin stops, it must always **hand back** the boiler, meaning it gives control
back to the boiler's own controls or to the wall thermostat, so the house never goes cold.

## How we tested

- **Test computers.** A separate, isolated test machine ran up to eight copies of Home Assistant
  at the same time. A firewall stopped them from reaching the home network.
- **Simulated boiler and house.** A simulator played the part of the boiler, the house, the
  weather and the radiator valves. It can also fake problems: a broken sensor, a lost
  connection, a boiler fault, a device that restarts.
- **Real VT.** The rooms were controlled by the real Versatile Thermostat (version 10.4.0) and
  SmartPI (version 0.4.0), as in a real home.
- **Each copy had its own job:**

| Copy | What it tested |
|---|---|
| 1 | The main setup: a boiler behind an OpenTherm gateway, with a wall thermostat |
| 2 to 5 | How often the boiler starts: the plugin against the boiler on its own |
| 6 | A simple on/off boiler, switched by a relay |
| 7 | A boiler driven through a device such as an ESPHome board |
| 8 | A gateway with no wall thermostat |

- **Plugin versions.** We tested three versions of the code as it was being built: the version
  from 8 October, the version with the new setup screens (9–10 October), and the version with the
  changes decided on 10 October.

## Results

| Area | What we checked | Result |
|---|---|---|
| Everyday control | The boiler heats when a room asks for heat and stops when no room does. It reacts within seconds. | Passed |
| Handing back | Switching the plugin off always gives the boiler back safely, in the right order. | Passed |
| Restarts | Home Assistant restarted normally, crashed, or reloaded the plugin several times in a row. Control came back as the user left it, and no second control loop was left running. | Passed |
| Lost data | The boiler's data stopped arriving, the outdoor sensor failed, the outdoor reading disappeared for 3 hours, the gateway lost its connection or restarted. The plugin waited, then handed back or used a safe fallback, and never left the house without heat. | Passed |
| Another controller | Something else kept changing the boiler's setting. The plugin corrected it once, then stepped aside instead of fighting. | Passed |
| Ignored commands | The boiler or gateway ignored the plugin's commands. The plugin noticed, warned the user, and did not keep repeating. | Passed |
| Boiler faults | Low water pressure and a boiler lockout. The plugin switched heating off safely, told the user, and resumed when the fault cleared. | Passed |
| Wrong settings | Settings that would be unsafe are refused, with a clear message. | Passed |
| Temperature limits | The water never went above the set maximum, and never above 40 °C for underfloor heating. | Passed |
| Relay boilers | Relay restarts, power cuts, Wi-Fi loss, relays with their own switch-off timers, a relay that switches itself off every 2 minutes, and a boiler that waits 20 minutes before it restarts. | Passed |
| Device-driven boilers | Handing back through a value, a switch or a timeout. A device that restarts in the middle of handing back. | Passed, after the fix described below |
| Gateway without a thermostat | Handing back stops the heating, as the plugin says it will. | Passed |
| Wall thermostat | After handing back, the wall thermostat took over at once and followed its own day and night program. | Passed |
| Fahrenheit | Home Assistant set to °F. The boiler still received the right temperatures in °C. | Passed |
| Long runs | 12 hours in cold weather and 12 hours in mild weather. No alarms, no errors, the water kept within its limits. | Passed |
| Upgrade | Settings saved by an older version of the plugin were updated automatically, with no errors. | Passed |
| New features (10 October) | The comfort correction stays within its limit and warns when it reaches it. It takes SmartPI's learning into account. The curve can follow the warmest room automatically. It detects an open window without a window sensor. | Passed |
| New "long burn" warning | Should warn when the boiler burns for hours without warming the rooms. | Did not trigger in our test (see question 3) |

## How often the boiler starts

Each time a boiler starts, it wears a little and wastes some gas. We wanted the plugin to start the
boiler **no more than 10% more often** than the boiler would on its own, with the rooms just as
warm. We ran the plugin and the boiler on its own side by side, at +8 °C and at −5 °C outside.

| | +8 °C outside | −5 °C outside |
|---|---|---|
| Plugin, comfort correction off, over a full day | about the same as the boiler on its own | **1.7 times as many starts** |
| Plugin, comfort correction off, at night only | about the same | about the same |
| Plugin, comfort correction on, at night only | **1.3 times as many starts** | **4.4 times as many starts** |
| Warmth of the rooms | the same in every case (within 0.1 °C) | the same in every case (within 0.1 °C) |

In plain words: **without the comfort correction, the plugin is fine in mild weather and at night,
but starts the boiler more often during cold days. With the comfort correction on, it starts the
boiler much more often, and the rooms are not warmer.** Even the highest rate we saw, about 11
starts an hour (at +8 °C with the comfort correction on), stays below the plugin's own warning level
of 12 an hour, but it is not the goal.

## Problems found

### The fault in the plugin (fixed)

With a device such as an ESPHome board, if the device restarted exactly while the plugin was
handing back the boiler, the plugin forgot to send the final setting. It also cleared the warning
that should have told the user. As a result, the boiler could have stayed on the plugin's last
water temperature instead of returning to its own control. This was fixed, and the test now passes:
the plugin sends the full hand-back as soon as the device is back.

### Questions for the owner

1. **Comfort correction on by default?** It raises the water temperature when a room stays cold.
   In our tests it reached its limit, made the boiler start up to 4.4 times as often in cold
   weather, and did not make the rooms warmer. The rooms stayed about 1 °C below their target
   because of how VT's own room control works, which hotter water cannot fix.
2. **Boiler starts in frost.** The plugin switches heating on and off exactly when the rooms ask.
   On cold days, the rooms stop asking for a few moments quite often, and each pause stops the
   burner. The boiler on its own rides through more of these pauses.
3. **The "long burn" warning.** It only reacts after 3 hours of the flame burning without a break.
   A boiler that keeps switching on and off at its lowest power, while the rooms stay cold, never
   reaches that point, so nothing tells the user. It might be better to look at how much of the
   time the boiler is burning.

### What the test setup cannot show

- The simulated outdoor sensor kept exactly the same value for more than 12 hours. The plugin
  rightly decided it was stuck and used the weather forecast instead. In a real home this is the
  correct reaction.
- VT's room control kept the simulated rooms about 1 °C below their targets in every test, with or
  without the plugin.
- A relay timer set to exactly twice the plugin's 5-minute check could hide its switch-offs, so the
  tests used 11 minutes instead of 10.

## Problems in our own test tools

Many first failures were mistakes in our test scripts, not in the plugin: waiting too short a time,
checking too early, or starting from the wrong conditions. Each one was found, explained and
fixed, and the test was run again.

One mistake is worth naming. A test left one copy of Home Assistant with a wrong setting, and the
next tests ran with it. For a while this looked like a new fault in the plugin, and we reported it
as one. It was not. The test tools now check that every copy is in its normal state before each
test, stop loudly when a setting cannot be put back, and attach the plugin's own messages to every
failure, so that mistakes like this are caught at once.

## Not tested

- Rooms whose VT thermostat is in "auto" mode or of the "over climate" type. The simulated rooms
  only offer "heat" and "off". This is covered by the plugin's own automated tests.
- Connecting through the gateway's own MQTT messages, and the specific device types from the new
  setup screens (ESPHome, EMS-ESP, the boiler's Wi-Fi module). The simulator offers only the
  general connection types.
- The newest plugin code, written after 10 October. It will be tested on the release branch.

## Next steps

1. The owner decides the three questions above.
2. The fixes go into the release branch (`qas`).
3. The tests are run again on that branch. Not every test needs to run: the core checks of each
   connection type, plus everything the fixes touch.
4. If the comfort correction stays on by default, or its behaviour changes, the boiler-starts
   comparison is run again over full days.

## Automated tests

Besides these tests in a real Home Assistant, the plugin has about 4,400 automated tests that run
on every change. All of them pass, apart from four that are expected to fail until the
boiler-starts decision above is made.
