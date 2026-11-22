# Smart Boiler for Versatile Thermostat — test report

Status: history — kept as it was written, in English only. The current documents: [the documentation map](../../README.md).

**Tests in a real Home Assistant, 18 to 21 November 2026: the `qas` branch (commit b96016c) and
the Boiler page on `dev` (commit 98d135e)**

This is the plain-language report. The detailed technical report, with every test and its
evidence, is [`unreleased.md`](unreleased.md): sections 4.7 and 4.8, the starts criterion in
section 5, the findings F15–F20 and L12–L14 in section 7.

## In short

- We tested the plugin's checked version (`qas`) on the newest Home Assistant (2026.11.2),
  Versatile Thermostat (10.6.5) and SmartPI (0.6.7), on eight copies of Home Assistant over three
  days. Then we tested the new Boiler page from `dev`.
- **Almost everything works.** 79 test runs: 70 passed straight away, and one more passed when
  repeated. The failures that remain are explained below; most of them come from our own test
  tools, not from the plugin.
- **The plugin does not make the boiler start more often than the boiler's own controls**, as long
  as Versatile Thermostat's cycle is 15 minutes, the cycle the plugin advises. The rooms stay just
  as warm. With VT's default 5-minute cycle the boiler starts more often, as expected, and the
  plugin now warns about that cycle.
- **Four faults in the plugin**, none of which loses control of the boiler or leaves it unsafe:
  1. When the heating curve is too low and the boiler runs steadily at its minimum, the plugin
     does not say "the water is too cool".
  2. Saving the heating curve from the new Boiler page quietly resets one of its settings (the
     radiators' exponent), so the water ends up warmer than the user asked.
  3. After saving from the page, the user is thrown back to the main dashboard.
  4. The page's journal does not mention the moments when the plugin hands the boiler back during
     a restart and takes it again.
- **One decision for you:** any Home Assistant user, not only an administrator, can switch the
  plugin's control on, by using the switch outside the page.

## What we tested

- **The whole set of automatic tests in a real Home Assistant (J4)**, on `qas` b96016c. This
  covers:
  - the OpenTherm gateway with a wall thermostat;
  - an on/off relay;
  - a boiler driven through its own entities;
  - a gateway with nothing on the thermostat terminals.

  On each path we checked handing the boiler back safely, restarts, lost signals, other
  controllers, faults, hot water, frost, US units and the wall thermostat's own program.
- **The starts criterion.** For a full day, the plugin's control and the boiler's own controls ran
  side by side, at +8 °C and at −5 °C outside, first with a 15-minute and then with a 5-minute VT
  cycle.
- **The new Boiler page (step I10.10).** We tested the page and its four cards in the browser:
  - as an administrator and as an ordinary user;
  - in Polish and English;
  - in the light and the dark theme;
  - on a wide screen and on a phone-sized one;
  - on a gateway with two days of history, on a fresh installation, and on a relay.

## Results by area

| Area | Result |
|---|---|
| Handing the boiler back safely (switching off, reloads, restarts, a killed Home Assistant) | works |
| Lost signals, a lost gateway, other controllers, the boiler's faults | works |
| Hot water, frost protection, floor heating limits, US units | works |
| The wall thermostat's own program at 6:00 | works |
| The relay (timers, restarts, lost Wi-Fi, start delay) | works; two tests failed only because of our test tool |
| The boiler's own entities, a stand-alone gateway | works |
| The starts criterion, 15-minute VT cycle | **passed** at +8 °C (as many starts as the boiler alone) and at −5 °C (about 2 starts an hour, burns of about 12 minutes) |
| The starts criterion, VT's default 5-minute cycle | not passed (expected); the plugin warns about short cycles |
| The comfort correction (raising the water when rooms stay cold) | works; it stops 0.47 K short of its 3 K limit in what reaches the boiler (by design, a question for later) |
| "The water is too cool" advice | **fault 1**: missing when the boiler runs at its minimum and the water is above a too-low setting |
| The Boiler page: sidebar, tabs, replay of the last day, cards, relay | works |
| The Boiler page: switching control from the page | works, with a confirmation; ordinary users are blocked on the page |
| The Boiler page: saving the heating curve | **faults 2 and 3** |
| The Boiler page: journal | works, **except fault 4** |

## The faults, in simple words

1. **No "water too cool" advice when the boiler runs at its minimum.** With a curve set too low,
   the boiler burnt for more than four hours at its minimum, and two rooms stayed cold. The water
   came out a little warmer than the plugin asked, because the boiler could not go lower. The
   plugin only gives the advice when the water matches its setting closely, so it stayed silent.
   The fix is small.
2. **Saving the curve from the page resets the radiators' exponent.** We moved the curve's point
   by 1 °C, and the saved exponent (1.0) quietly went back to the default (1.3). The water then
   rose by about 2.3 °C instead of 1, and the confirmation window did not mention it.
3. **After saving from the page, the page closes.** The save works, but while the plugin reloads,
   the page is removed for a moment and the browser jumps to the main dashboard, so the user does
   not see the result. The same happens whenever the plugin reloads with the page open.
4. **The journal misses the hand-back during a restart.** When the plugin reloads or Home
   Assistant restarts while the plugin controls the boiler, the boiler is safely handed back and
   taken again, but the journal only says "stopped" and "started".

There are also small display issues:
- one line of the status can appear in the server's language instead of the user's;
- times follow the browser's time zone, not the user's Home Assistant setting;
- the "Use" tab shows empty values without saying why;
- the installation drawing is cut off in a narrow card.

## What our test tools got wrong

Several failures came from the test scenarios, not from the plugin:
- One test waited for the boiler to burn long enough, and it never did.
- Two relay tests restarted the relay before it was switched on.
- One test assumed SmartPI had finished learning, on an installation one minute old.
- One test is shorter than the 3 hours the warning it checks needs.
- The 12-hour test at −2 °C expects warmer rooms than the default curve gives.

The development session will fix the tools.

## Decisions needed

- Should only administrators be able to switch the plugin's control on, also outside the page?
- Should the comfort correction's limit reach the boiler exactly (3 K instead of 2.53 K)?

## Not tested, and why

- The "Forget" buttons for measured building values: the simulator never runs for the three weeks
  a measurement needs.
- Saving the curve's offset at the simple settings level: all test installations use the advanced
  level.
- The newest change on `dev` (#178), which came after these tests.
