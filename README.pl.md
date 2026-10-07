[English version](README.md)

[![Status][status-shield]](#stan)
[![Release][release-shield]][releases]
[![Commit activity on dev][commits-shield]][commits]
[![License][license-shield]][license]
[![HACS][hacs-shield]](#instalacja)

# Versatile Thermostat Smart Boiler

<p align="center"><b>
Prowadzi kocioł gazowy według potrzeb pomieszczeń z Versatile Thermostat i zawsze bezpiecznie go
oddaje.
</b></p>

> **Jeszcze bez wydania — nie instaluj w ogrzewaniu, na którym polegasz.**
> Integracja jest w budowie i nie pracowała jeszcze z prawdziwym kotłem. Nie ma wydania ani
> wpisu w Home Assistant Community Store (HACS); pierwsze wydanie wstępne pojawi się po testach
> na testowym Home Assistant i po przeglądzie.
> Gdzie jesteśmy: [Stan](#stan) · co dalej: [Plan rozwoju](#plan-rozwoju).

**Versatile Thermostat Smart Boiler** to wtyczka do [Versatile Thermostat][vt] (VT), która
prowadzi kocioł gazowy według tego, czego pomieszczenia naprawdę potrzebują: mniej i dłuższych
cykli pracy palnika, więcej kondensacji, mniej gazu na stopniodzień — przy tym samym komforcie w
pomieszczeniach i bez zaburzania własnych modeli pomieszczeń w algorytmach stref. Zastępuje
kocioł centralny VT działający w trybie wł./wył. sterowaniem temperaturą wody w kotle i zawsze
wie, jak oddać kocioł jego własnemu sterowaniu.

To **nie** jest regulator pomieszczeń (pomieszczenia zostają przy VT i jego algorytmach), nie
steruje zaworami ani pompami ciepła i nie wysyła żadnych danych poza twój Home Assistant.

# Co robi

- **Najpierw monitorowanie.** Zanim zacznie sterować, obserwuje kocioł przez okres
  monitorowania (domyślnie 7 dni): cykle pracy palnika i ich długość, kondensację, pobory
  ciepłej wody, gaz na stopniodzień, problemy z sygnałami oraz werdykt, czy sterowanie się
  opłaca.
- **Temperatura wody zależna od pogody** według krzywej, którą wpisujesz, ograniczona najniższą
  i najwyższą temperaturą wody, pułapem pogodowym i maksimum każdego obiegu.
- **Włączanie i wyłączanie grzania idzie za strefami VT** — według liczby stref potrzebujących
  ciepła, łącznej mocy albo otwarcia zaworów, tak jak w kotle centralnym VT — a tryby centralne
  VT działają przez strefy.
- **Zapisuje przez to, co masz:** wybraną encję, OpenTherm Gateway (`opentherm_gw` z Home
  Assistant albo jego firmware przez MQTT) albo przekaźnik dla kotła wł./wył.
- **Najpierw bezpieczeństwo:** ochrona przed mrozem, ochrona przed częstym taktowaniem, odczyt
  zwrotny każdego zapisu, nigdy walka z innym sterownikiem, nic zapisywanego do trwałej pamięci
  kotła i bezpieczne oddanie kotła jego własnemu sterowaniu przy każdym wyjściu — ponawiane aż
  do potwierdzenia.
- Każda opcja ma ostrożną wartość domyślną i opis, który mówi, co robi i czym ryzykuje.

# Współpraca z Versatile Thermostat

1. Ustaw termostaty VT dla pomieszczeń ogrzewanych przez kocioł. Jeśli w VT jest skonfigurowany
   kocioł centralny, odznacz go w centralnej konfiguracji VT i uruchom ponownie Home Assistant:
   jego miejsce zajmuje wtyczka.
2. Dodaj jeden wpis **Versatile Thermostat Smart Boiler** i wybierz strefy VT, które ogrzewa ten
   kocioł.
3. Wybierz encję, która dostarcza każdy sygnał kotła — do sterowania co najmniej płomień i
   temperaturę zasilania.
4. Pozwól jej monitorować przez okres monitorowania (domyślnie 7 dni) i przeczytaj werdykt.
5. Potem, jeśli chcesz, ustaw sterowanie w opcjach i włącz **Sterowanie (eksperymentalne)**.

Krok po kroku: [przewodnik użytkownika][guide-pl].

# Stan

| Etap | Stan |
|---|---|
| 0.1 Monitor (tylko odczyt) | zbudowany, wydany razem z 0.2 |
| 0.2 Podstawa sterowania | zbudowana; poprawiona po trzech pełnych przeglądach (0.2.1, 0.2.2, 0.2.3) |
| Testy na testowym Home Assistant | następne |
| Przegląd przed prawdziwym kotłem | po tych testach |
| Pierwsze wydanie wstępne (tymczasowo 0.2.3b1) | po przeglądzie |

# Plan rozwoju

| Wydanie | Zawartość |
|---|---|
| 0.2 Podstawa sterowania | monitor plus sterowanie temperaturą wody, bezpieczne oddanie kotła, ochrona przed mrozem |
| 0.3 Ochrona przed taktowaniem i wartości pomieszczeń | praca cykliczna i lato/zima z prognozy, limit modulacji, tryb wartości pomieszczeń, podłogówka za zaworem mieszającym |
| 0.4 Uczenie i strojenie | uczenie po stronie wody, propozycje, sezonowe dostrojenie |
| 0.5 Prognoza | wyprzedzanie dla wolnych grzejników na podstawie zapisanych prognoz |
| Później | ładowanie ciepłej wody, domyślna lista HACS, więcej urządzeń |

Cele są zamierzeniami, nie zobowiązaniami; każde wydanie zbiera dane dla następnego. Szczegóły:
[`PLAN.md`][plan] (po angielsku).

# Dokumentacja

| Dokument | Co zawiera |
|---|---|
| [`SCOPE.md`][scope] | specyfikacja: co wtyczka robi, jej zasady i wszystkie decyzje (po angielsku) |
| [`PLAN.md`][plan] | plan rozwoju, wydania i środowisko testowe (po angielsku) |
| [`docs/`][docs] | plan każdego wydania i przeglądy kodu (po angielsku) |
| 🇬🇧 [User guide][guide] · 🇵🇱 [Przewodnik użytkownika][guide-pl] | wymagania, instalacja, szybki start, jak to działa, podłączenie kotła, bezpieczeństwo, alarmy |
| 🇬🇧 [Technical documentation][technical] · 🇵🇱 [Dokumentacja techniczna][technical-pl] | części integracji, jeden krok sterowania, cykl życia, stan trwały, testy |
| [`CONTRIBUTING.md`][contributing] | jak współtworzyć: gałęzie, testy, zasady (po angielsku) |
| [`LICENSE`][license] | Apache License 2.0 |

Gałąź `main` zawiera te dokumenty; rozwijany kod jest na gałęzi [`dev`][dev] i trafi do `main`
z pierwszym wydaniem.

# Instalacja

Jeszcze nie: nie ma wydania. Gdy się pojawi, będzie się instalować przez HACS jako niestandardowe
repozytorium.

# Współtworzenie

Wkład jest mile widziany — otwieraj pull requesty do `dev`. Najpierw przeczytaj
[`CONTRIBUTING.md`][contributing]: ta integracja steruje ogrzewaniem domu, więc każda zmiana jest
mała, przetestowana i przejrzana. Jakie automatyczne sprawdzenia działają i kiedy, opisuje jego
część [Checks](CONTRIBUTING.md#checks).

# Autorzy

[@Shadow-230](https://github.com/Shadow-230)

# Licencja

[Apache License 2.0][license].

[vt]: https://github.com/jmcollin78/versatile_thermostat
[dev]: https://github.com/Shadow-230/vtherm-smart-boiler/tree/dev
[scope]: SCOPE.md
[plan]: PLAN.md
[docs]: docs/
[guide]: documentation/en/user-guide.md
[guide-pl]: documentation/pl/user-guide.md
[technical]: documentation/en/technical.md
[technical-pl]: documentation/pl/technical.md
[contributing]: CONTRIBUTING.md
[license]: LICENSE
[releases]: https://github.com/Shadow-230/vtherm-smart-boiler/releases
[commits]: https://github.com/Shadow-230/vtherm-smart-boiler/commits/dev
[status-shield]: https://img.shields.io/badge/status-in%20development-orange.svg?style=for-the-badge
[release-shield]: https://img.shields.io/badge/release-none%20yet-lightgrey.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/m/Shadow-230/vtherm-smart-boiler/dev.svg?style=for-the-badge
[license-shield]: https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=for-the-badge
[hacs-shield]: https://img.shields.io/badge/HACS-not%20yet-lightgrey.svg?style=for-the-badge
