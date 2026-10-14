[English version](../../../en/testing/reports/README.md)

# Raporty z testów

Status: aktualny.

Każde wydanie ma raport z testów, które przeszła jego wersja: `docs/en/testing/reports/<version>.md`
(decyzja użytkownika z 2026-10-08). Dopóki wersja nie ma nazwy (`docs/en/development/plans/plan-0.2.md`, K4 i K5),
raport w trakcie pisania to `unreleased.md`; przy wydaniu dostaje nazwę wersji i idzie razem
z pull requestem z `dev` do `qas`.

Każdy przebieg testów dostaje też obok raport prostym językiem, `<date>-test-report.md`: co
przetestowano, wyniki według obszarów, znalezione problemy i decyzje, których wymagają, prostymi
słowami dla czytelnika, który nie zna kodu (prośba użytkownika z 2026-10-11).

## Co zawiera raport

1. **Wersja i kod** — wersja, przetestowany commit, daty.
2. **Środowisko** — Home Assistant (wersja, na której zbudowano wtyczkę, i najstarsza obsługiwana),
   Versatile Thermostat, SmartPI, `vtherm_api`, które zainstalował Home Assistant, Python.
3. **Testy automatyczne** — liczby testów rdzenia (bez Home Assistant) i pozostałych, oczekiwane
   niepowodzenia i dlaczego, lint i typy, przebiegi CI.
4. **J4 w testowym Home Assistant** — każdy scenariusz z identyfikatorem, co sprawdza, wynik, data
   i dowody (co zapisano do kotła, jakie stany i alarmy widziano); przebiegi przejrzane ręcznie,
   z uzasadnieniem.
5. **Kryterium startów** — starty na godzinę i temperatury w pokojach z jego czterech przebiegów,
   stosunek do kryterium i wyniki z testu w procesie.
6. **Czego nie uruchomiono i dlaczego** — scenariusze, do których prawdziwy Home Assistant nie
   sięga, albo odłożone na później.
7. **Ustalenia i znane ograniczenia** — co znalazły przebiegi, wraz z tym, co dalej.

## Jak powstaje część J4

Testowy Home Assistant to dedykowany testowy LXC (`docs/pl/testing/test-environment.md`). Jego
instancje są wdrażane poleceniem `scripts/deploy_test.sh --instance N [--config NAME]` i
konfigurowane tak, jak mówi sekcja 4 pliku `docs/pl/testing/test-environment.md`. Scenariusze
uruchamia program w `devenv/j4/`:

```
HA_INSTANCE=1 scripts/env.sh python devenv/j4/run.py B1 C2 ...      # scenariusze według identyfikatora
HA_INSTANCE=1 scripts/env.sh python devenv/j4/restart.py B3 B6     # restarty
HA_INSTANCE=6 scripts/env.sh python devenv/j4/paths.py R1 ...      # przekaźnik (6), encja (7), samodzielny (8)
HA_INSTANCE=1 scripts/env.sh python devenv/j4/corrections.py Q1 ... # poprawki z 2026-10-10
```

`corrections.py` testuje poprawki z 2026-10-10 (G11, `docs/en/development/plans/plan-0.2-g11.md`): limit i ostrzeżenie
korekty komfortu, pasmo nauki SmartPI, temperaturę pokojową krzywej w trybie Auto i regułę długiego
palenia. Długi przebieg (`run.py L1`, liczbę godzin ustawia
`J4_HOURS`) trwa dłużej niż dwie godziny polecenia w tle i działa odłączony.

Każdy scenariusz zaczyna się i kończy w czystym stanie — sterowanie wyłączone i oddane, usterki
symulatora wyczyszczone, strefy grzeją do swoich wartości zadanych — i sprawdza to, co sprawdza
test akceptacyjny w procesie dla tego samego scenariusza (`tests/integration/test_acceptance.py`):
stany wtyczki, alarmy i zgłoszenia naprawy oraz każde polecenie wysłane do bramki, przechwycone na
żywo przez WebSocket w Home Assistant. Jego wyniki wraz z dowodami trafiają do
`research/<date>-j4-results.md` (poza gitem); raport bierze je stamtąd. Program uruchamiający
czyta, gdzie się połączyć, tylko z `devenv/local.env`.
