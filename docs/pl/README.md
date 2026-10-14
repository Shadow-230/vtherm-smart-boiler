[English version](../en/README.md)

# Dokumentacja

Ten katalog zawiera całą dokumentację Smart Boiler for Versatile Thermostat. Każdy katalog ma
jeden temat. Głównym językiem jest angielski; każdy aktualny dokument ma też polską kopię w tym
samym miejscu pod `docs/pl/`.

## Co gdzie jest

| Katalog | Co zawiera | Dla kogo |
|---|---|---|
| [`user-guide/`](user-guide/user-guide.md) | jak zainstalować, ustawić i używać wtyczki | użytkownicy |
| [`technical/`](technical/technical.md) | jak wtyczka jest zbudowana: jej części, jeden krok sterowania, testy | programiści |
| [`specification/`](specification/scope.md) | co wtyczka robi i dlaczego: zakres, interfejs danych o wodzie, kody używane w kodzie | programiści, recenzenci |
| [`development/`](development/plan.md) | plan rozwoju; plany każdego wydania i przeglądy (tylko po angielsku) | programiści |
| [`testing/`](testing/test-environment.md) | testowy Home Assistant i raporty z testów | testerzy |
| `../images/` | obrazy wspólne dla wszystkich języków | — |

## Dokumenty

| Dokument | Status | Wersja angielska |
|---|---|---|
| [Przewodnik użytkownika](user-guide/user-guide.md) | aktualny | [tak](../en/user-guide/user-guide.md) |
| [Dokumentacja techniczna](technical/technical.md) | aktualny | [tak](../en/technical/technical.md) |
| [Zakres](specification/scope.md) | aktualny | [tak](../en/specification/scope.md) |
| [Dane o wodzie dla algorytmów stref](specification/water-interface.md) | aktualny | [tak](../en/specification/water-interface.md) |
| [Kody odniesień](specification/references.md) | aktualny | [tak](../en/specification/references.md) |
| [Plan rozwoju](development/plan.md) | aktualny | [tak](../en/development/plan.md) |
| [Środowisko testowe](testing/test-environment.md) | aktualny | [tak](../en/testing/test-environment.md) |
| [Raporty z testów: jak powstają](testing/reports/README.md) | aktualny | [tak](../en/testing/reports/README.md) |
| [Raport z testów w trakcie](testing/reports/unreleased.md) | aktualny | [tak](../en/testing/reports/unreleased.md) |
| [Plany wydań](../en/development/plans/) | historia | tylko po angielsku |
| [Przeglądy kodu](../en/development/reviews/) | historia | tylko po angielsku |
| [Raport z testów z 2026-10-11](../en/testing/reports/2026-10-11-test-report.md) | historia | tylko po angielsku |

Dokumenty **aktualne** zmieniają się razem z kodem, w obu językach w tym samym pull requeście.
**Historia** to zapis tego, jak powstawała wtyczka. Zostaje tylko po angielsku i nie jest
przepisywana. Jedyny wyjątek: krok planu wydania nadal dostaje ✅, gdy zostanie wykonany.

Pozostałe pliki na górze repozytorium: `README.pl.md` (od tego zacznij), `CHANGELOG.md` (co
zmienia każde wydanie), `CONTRIBUTING.md` (jak współtworzyć) i `LICENSE`.
