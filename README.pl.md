[English version](README.md)

[![Status][status-shield]](#stan)
[![Release][release-shield]][releases]
[![Commit activity on dev][commits-shield]][commits]
[![License][license-shield]][license]
[![HACS][hacs-shield]](#instalacja)
[![Buy me a coffee][bmc-shield]][bmc]

# Smart Boiler for Versatile Thermostat

<p align="center">
  <img src="docs/images/logo.png" alt="Smart Boiler for Versatile Thermostat logo" width="280" />
</p>

<p align="center"><b>
Prowadzi kocioł centralnego ogrzewania według potrzeb pomieszczeń z Versatile Thermostat i zawsze
bezpiecznie go oddaje.
</b></p>

> **Jeszcze bez wydania — nie instaluj w ogrzewaniu, na którym polegasz.**
> Integracja jest w budowie i nie pracowała jeszcze z prawdziwym kotłem. Nie ma wydania ani
> wpisu w Home Assistant Community Store (HACS); pierwsze wydanie wstępne pojawi się po testach
> na testowym Home Assistant i po przeglądzie.
> Gdzie jesteśmy: [Stan](#stan) · co dalej: [Plan rozwoju](#plan-rozwoju).

**Smart Boiler for Versatile Thermostat** to wtyczka do [Versatile Thermostat][vt] (VT) — nie jest
częścią VT ani dziełem jego autorów — która prowadzi kocioł centralnego ogrzewania — gazowy,
olejowy, elektryczny lub na inne paliwo, każdy, z którym Home Assistant się komunikuje, ale nie
pompę ciepła — według tego, czego pomieszczenia naprawdę potrzebują: mniej i dłuższych cykli pracy
palnika, więcej kondensacji tam, gdzie kocioł kondensuje, mniej paliwa na stopniodzień — przy tym
samym komforcie w pomieszczeniach i bez zaburzania własnych modeli pomieszczeń w algorytmach stref.
Zastępuje kocioł centralny VT działający w trybie wł./wył. sterowaniem temperaturą wody w kotle i
zawsze wie, jak oddać kocioł jego własnemu sterowaniu.

To **nie** jest regulator pomieszczeń (pomieszczenia zostają przy VT i jego algorytmach), nie
steruje zaworami ani pompami ciepła i nie wysyła żadnych danych poza twój Home Assistant.

# Co robi

- **Monitorowanie, a sterowanie, kiedy zechcesz.** Obserwuje kocioł — cykle pracy palnika i ich
  długość, kondensację, pobory ciepłej wody, gaz na stopniodzień, problemy z sygnałami — a po
  7 dniach danych daje werdykt, czy sterowanie się opłaca. Dopóki nie włączysz sterowania, kocioł
  pracuje jak dotąd; włączyć je możesz od pierwszego dnia.
- **Temperatura wody zależna od pogody** według krzywej, którą wpisujesz, ograniczona najniższą
  i najwyższą temperaturą wody oraz maksimum każdego obiegu.
- **Włączanie i wyłączanie grzania idzie za strefami VT** — według liczby wołających urządzeń
  (albo stref), łącznej mocy albo otwarcia zaworów, tak jak w kotle centralnym VT — a tryby
  centralne VT działają przez strefy.
- **Zapisuje przez to, co masz:** wybraną encję, OpenTherm Gateway (`opentherm_gw` z Home
  Assistant albo jego firmware przez MQTT) albo przekaźnik dla kotła wł./wył.
- **Najpierw bezpieczeństwo:** ochrona przed mrozem, ochrona przed częstym taktowaniem, odczyt
  zwrotny każdego zapisu, nigdy walka z innym sterownikiem, nic zapisywanego do trwałej pamięci
  kotła i bezpieczne oddanie kotła jego własnemu sterowaniu przy każdym wyjściu — ponawiane aż
  do potwierdzenia.
- Każda opcja ma ostrożną wartość domyślną i opis, który mówi, co robi i czym ryzykuje.

# Do czego się przydaje

- **Czy mój kocioł taktuje?** Wskaż sygnały kotła i zostaw sterowanie wyłączone: monitor liczy
  starty na godzinę, długość cykli pracy palnika, udział kondensacji i gaz na stopniodzień, a jego
  werdykt mówi, czy warto włączyć sterowanie. Nic nie trafia do kotła.
- **Kocioł OpenTherm i VT w każdym pomieszczeniu.** Wtyczka ustawia temperaturę wody według
  temperatury na zewnątrz i włącza oraz wyłącza grzanie według stref VT — przez OpenTherm Gateway,
  ESPHome OpenTherm albo EMS-ESP. Z termostatem ściennym na bramce kocioł wraca do niego przy
  każdym oddaniu sterowania.
- **Kocioł wł./wył.** Przekaźnik na zaciskach termostatu pokojowego idzie za strefami VT zamiast
  kotła centralnego VT; wtyczka sprawdza przekaźnik albo powtarza polecenie i oddaje sterowanie
  do stanu przekaźnika po oddaniu.
- **Podłogówka bez mieszacza.** Najwyższa temperatura wody obiegu ogranicza każdą nastawę, a alarm
  mówi, gdy zmierzone zasilanie długo jest wyższe.

# Wymagania

| Wymaganie | Wersja |
|---|---|
| Home Assistant | 2026.9 lub nowszy |
| Versatile Thermostat | 10.2.0 lub nowszy (od 10.2.0 ładuje zewnętrzne menedżery funkcji); testowana wersja to 10.5.1 — tymczasowo, do pierwszego wydania |
| `vtherm_api` | 0.5.0 lub nowsza, instalowana z wtyczką |
| SmartPI, Auto-TPI | opcjonalne; działa każdy algorytm stref VT |

Monitorować można każdy kocioł, którego sygnały Home Assistant pokazuje jako encje. Do
sterowania wtyczka zapisuje przez OpenTherm Gateway (integrację `opentherm_gw` z Home Assistant
albo jej firmware przez MQTT), ESPHome OpenTherm, EMS-ESP, przekaźnik dla kotła wł./wył. albo inną
wybraną encję do zapisu. Nie jest zapisywane nic, co kocioł zachowałby w trwałej pamięci. Do tej
pory testowane tylko z symulowanym kotłem. Co zapisuje każde połączenie i co robi po oddaniu
sterowania: [przewodnik, część 5][guide-connect].

# Instalacja

**Nie ma jeszcze wydania.** Gdy się pojawi, instaluje się przez HACS jako własne repozytorium
albo ręcznie: [przewodnik, część 2][guide-install]. Potem [szybki start][guide-start] prowadzi
przez ustawienia.

# Dokumentacja

Wszystko, czego potrzebuje użytkownik, jest w **przewodniku** — 🇵🇱 [Przewodnik
użytkownika][guide] · 🇬🇧 [User guide][guide-en]:

| Co chcesz wiedzieć | Gdzie w przewodniku |
|---|---|
| Co jest potrzebne, jak zainstalować, pierwsze ustawienia | [1–3][guide] |
| Jak to działa: werdykt, włączanie i wyłączanie grzania, temperatura wody, mróz, obiegi, algorytmy stref | [4][guide-how] |
| Jak podłączyć kocioł i co robi oddanie sterowania przy każdym połączeniu | [5][guide-connect] |
| Bezpieczeństwo: oddanie sterowania, inne sterowniki, utrata łączności, świeżość danych | [6][guide-safety] |
| Co znaczy każdy alarm i zgłoszenie w Naprawach | [7][guide-alarms] |
| Encje | [9][guide-entities] |
| Jak często odświeżają się dane i co zostaje lokalnie | [10, 11][guide-updates] |
| Opcje i czym każda ryzykuje | [12][guide-options] |
| Przykłady automatyzacji | [13][guide-automations] |
| Rozwiązywanie problemów | [14][guide-troubleshooting] |
| Znane ograniczenia | [15][guide-limitations] |
| Usuwanie | [16][guide-removal] |

Specyfikacja, dokumentacja techniczna, plany i raporty z testów są wymienione na
[mapie dokumentacji][docs-map].

Gałąź `main` zawiera te dokumenty; rozwijany kod jest na gałęzi [`dev`][dev] i trafi do `main`
z pierwszym wydaniem.

# Stan

| Etap | Stan |
|---|---|
| 0.1 Monitor (tylko odczyt) | zbudowany, wydany razem z 0.2 |
| 0.2 Podstawa sterowania | zbudowana; poprawiona po trzech pełnych przeglądach (0.2.1, 0.2.2, 0.2.3) |
| Testy na testowym Home Assistant | trwają |
| Przegląd przed prawdziwym kotłem | po tych testach |
| Pierwsze wydanie wstępne (tymczasowo 0.2.3b1) | po przeglądzie |

# Plan rozwoju

| Wydanie | Zawartość |
|---|---|
| 0.2 Podstawa sterowania | monitor plus sterowanie temperaturą wody, bezpieczne oddanie kotła, ochrona przed mrozem |
| 0.3 Ochrona przed taktowaniem i tryb jak termostat | praca cykliczna, limit modulacji, planowanie z prognozy, tryb jak termostat, podłogówka za zaworem mieszającym |
| 0.4 Uczenie i strojenie | uczenie po stronie wody, propozycje, sezonowe dostrojenie |
| 0.5 Prognoza | wyprzedzanie dla wolnych grzejników na podstawie zapisanych prognoz |
| Później | ładowanie ciepłej wody, domyślna lista HACS, więcej urządzeń |

Cele są zamierzeniami, nie zobowiązaniami; każde wydanie zbiera dane dla następnego. Szczegóły:
[plan rozwoju][plan].

# Współtworzenie

Wkład jest mile widziany — otwieraj pull requesty do `dev`. Najpierw przeczytaj
[`CONTRIBUTING.md`][contributing]: ta integracja steruje ogrzewaniem domu, więc każda zmiana jest
mała, przetestowana i przejrzana. Jakie automatyczne sprawdzenia działają i kiedy, opisuje jego
część [Checks](CONTRIBUTING.md#checks).

# ☕ Wsparcie

Jeśli Smart Boiler for Versatile Thermostat Ci się przydaje, możesz wesprzeć jego rozwój tutaj:

<a href="https://buymeacoffee.com/shadow23"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy me a coffee" height="50"></a>

# Autorzy

[@Shadow-230](https://github.com/Shadow-230)

# Licencja

[Apache License 2.0][license].

[vt]: https://github.com/jmcollin78/versatile_thermostat
[dev]: https://github.com/Shadow-230/vtherm-smart-boiler/tree/dev
[plan]: docs/pl/development/plan.md
[contributing]: CONTRIBUTING.md
[license]: LICENSE
[releases]: https://github.com/Shadow-230/vtherm-smart-boiler/releases
[commits]: https://github.com/Shadow-230/vtherm-smart-boiler/commits/dev
[bmc]: https://buymeacoffee.com/shadow23
[guide]: docs/pl/user-guide/user-guide.md
[guide-install]: docs/pl/user-guide/user-guide.md#2-instalacja
[guide-start]: docs/pl/user-guide/user-guide.md#3-szybki-start
[guide-how]: docs/pl/user-guide/user-guide.md#4-jak-to-działa
[guide-connect]: docs/pl/user-guide/user-guide.md#5-podłączenie-kotła
[guide-safety]: docs/pl/user-guide/user-guide.md#6-bezpieczeństwo-i-oddanie-sterowania
[guide-alarms]: docs/pl/user-guide/user-guide.md#7-alarmy-i-zgłoszenia-w-naprawach
[guide-entities]: docs/pl/user-guide/user-guide.md#9-encje
[guide-updates]: docs/pl/user-guide/user-guide.md#10-jak-często-odświeżają-się-dane
[guide-options]: docs/pl/user-guide/user-guide.md#12-opcje-i-ryzyko
[guide-automations]: docs/pl/user-guide/user-guide.md#13-przykłady-automatyzacji
[guide-troubleshooting]: docs/pl/user-guide/user-guide.md#14-rozwiązywanie-problemów
[guide-limitations]: docs/pl/user-guide/user-guide.md#15-znane-ograniczenia
[guide-removal]: docs/pl/user-guide/user-guide.md#16-usuwanie
[guide-en]: docs/en/user-guide/user-guide.md
[docs-map]: docs/pl/README.md
[status-shield]: https://img.shields.io/badge/status-in%20development-orange.svg?style=for-the-badge
[release-shield]: https://img.shields.io/badge/release-none%20yet-lightgrey.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/m/Shadow-230/vtherm-smart-boiler/dev.svg?style=for-the-badge
[license-shield]: https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=for-the-badge
[hacs-shield]: https://img.shields.io/badge/HACS-not%20yet-lightgrey.svg?style=for-the-badge
[bmc-shield]: https://img.shields.io/badge/buy%20me%20a%20coffee-shadow23-ffdd00.svg?style=for-the-badge&logo=buymeacoffee&logoColor=black
