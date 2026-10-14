[English version](../../../en/testing/reports/unreleased.md)

# Raport z testów — wersja niewydana (tymczasowo 0.2.3b1)

Status: aktualny.

Wersja tego raportu prostym językiem: [`2026-10-11-test-report.md`](../../../en/testing/reports/2026-10-11-test-report.md).

**Stan: J4 na `dev` zakończył się 2026-10-11 rano.** Następny przebieg będzie na `qas`, po
poprawkach wynikających z przeglądu tego raportu (reguła użytkownika: od teraz J4 testuje to, co
jest na `qas`). W dniach od 2026-10-08 do 2026-10-11 osiem testowych Home Assistantów wykonało
około 120 przebiegów scenariuszy na trzech stanach kodu (sekcja 1). Znaleziono jeden błąd wtyczki:
F7, naprawiony w #51 i potwierdzony. Do rozstrzygnięcia w przeglądzie: kryterium startów przy
−5 °C (F9), koszt startów korekty komfortu (F8) oraz wyzwalanie reguły długiego palenia (F10).
Jak powstają raporty: `docs/pl/testing/reports/README.md`.

## 1. Wersja i kod

| | |
|---|---|
| Wersja | 0.2.3b1 w manifeście (tymczasowa; o wersji decydują K4 i K5) |
| Przetestowany kod wtyczki | (a) `dev` przy 9df2f06 — pierwszy przebieg instancji 1, 2026-10-08/09; (b) `dev` do I6 włącznie (737b2db … b832a0e) — instancje od 6 do 8 i drugi przebieg instancji 1, 2026-10-09/10; (c) `dev` do G11 włącznie (4378e02, z poprawką F7 z #51) — instancje 1, 2–5, 7 i 8 od 2026-10-10 16:45 UTC; instancja 6 działa na `dev` do I7 włącznie (663983d), żeby użytkownik mógł ją oglądać na żywo; nie była testowana. `dev` poszedł od tego czasu dalej (I8, do 1d6d724): nie jest tu testowany |
| Narzędzia testowe | gałąź `claude/j4-results`: runner (`devenv/j4/run.py`, `paths.py`, `restart.py`, `corrections.py`), usługi symulatora dla przekaźnika, typów zapisu, kotła i jego blokady awaryjnej, oraz konfiguracje w `devenv/config/`. 2026-10-12, po tym przebiegu, runner został przeniesiony na `dev` (#93), a jego zapisywanie opcji dostosowano do menu z I8 (`devenv/j4/walk.py`, `options.py`): każda zmiana idzie teraz przez pozycję, która o nią pyta — odczyty zwrotne wśród sygnałów kotła, pytania bramki w interfejsie kotła, twarde maksimum jako maksimum obiegu (E1), tylko monitorowanie jako tryb sterowania (G2), strefy podłogowe w obiegu (U1, U2). Sprawdzone testem w procesie na prawdziwym przepływie opcji przez jego REST API (`tests/integration/test_j4_walk.py`); jeszcze nie uruchomione w testowym Home Assistancie |
| Start J4 | 2026-10-08, przez użytkownika |

## 2. Środowisko

| | |
|---|---|
| Home Assistant | 2026.9.3 (testowe Home Assistanty i CI); 2026.9.0 w CI, najstarszy obsługiwany |
| Versatile Thermostat | 10.4.0 |
| SmartPI | 0.4.0 |
| `vtherm_api` | 0.5.0, tak jak zainstalował go Home Assistant w testowym Home Assistancie |
| Python | 3.14 |
| Testowy Home Assistant | osobny testowy LXC (Debian 13, Docker, zapora sieciowa na hoście Proxmox blokuje sieć domową: T-25 zaliczony), osiem instancji: 1 bramka z termostatem ściennym OpenTherm; 2–5 kryterium startów; 6 przekaźnik; 7 ścieżka przez encje (urządzenie trzymane); 8 samodzielna bramka |

## 3. Testy automatyczne

| Zestaw | Wynik |
|---|---|
| Rdzeń, bez Home Assistanta (`tests/core`) | 1473 passed (`dev` do G11 włącznie) |
| Pozostałe, z Home Assistantem | 2956 passed, 4 expected failures (`dev` do G11 włącznie) |
| `ruff check`, `ruff format --check`, `mypy` (tryb ścisły) | czysto |
| CI (obie wersje Home Assistanta, hassfest, HACS) | zielone przy każdym pull requeście scalonym do `dev` |

Cztery oczekiwane niepowodzenia to testy typu „strict”, które czekają na decyzje w K4: kryterium
startów z J4 przy dobowych wahaniach temperatury zewnętrznej (×1.20 przy +8 °C i ×2.16 przy −5 °C
wobec własnej regulacji kotła, pokoje równie ciepłe; `tests/sim/test_control_loop.py`) oraz jego
test pasma.

## 4. J4 w testowych Home Assistantach

„Bezpieczne oddanie sterowania” to: bramka dostaje najniższą temperaturę wody (20 °C), c.o.
włączone, a potem zwolnioną nastawę (0), w tej kolejności. „Reviewed” (sprawdzone ręcznie) oznacza
przebieg, którego pierwszy wynik pochodził od runnera; wyjaśnienie jest pod każdą tabelą. Dowody
każdego scenariusza są w `research/<date>-j4-*-results.md` (ignorowane przez git).

### 4.1 Instancja 1, pierwszy przebieg (kod a)

Kocioł kondensacyjny `condensing_small`, termostat ścienny OpenTherm na zaciskach bramki (21 °C od
06:00 do 22:00 UTC, poza tym 17 °C), bramka z termostatem, nastawa wygasająca, trzy strefy
grzejnikowe pod VT (TPI; SmartPI w sypialni), na zewnątrz 3 °C.

| ID | Scenariusz | Wynik | Dowody |
|---|---|---|---|
| A1 | grzanie podąża za strefami VT w obie strony | pass | c.o. wyłączone 6 s i 0 s po zamknięciu ostatniego zaworu; włączone 6 s po otwarciu zaworu (krok sterowania 10 s) |
| A2 | tryb centralny VT „Stopped” | pass | strefy wyłączone, brak zapotrzebowania, c.o. wyłączone, nastawa nadal trzymana — bez oddania sterowania; „Auto” znów grzeje |
| A3 | sterowanie wyłączone | pass | bezpieczne oddanie sterowania; bramka wraca do 42 °C z termostatu ściennego; nic więcej |
| B1 | wtyczka przeładowana | pass | bezpieczne oddanie sterowania, potem sterowanie wznowione |
| B2 | wpis wtyczki wyłączony, potem włączony | pass | bezpieczne oddanie sterowania, żadna pętla nie została przez 2 min; po włączeniu: sterowanie wraca tak, jak było |
| B3 | czysty restart Home Assistanta | pass | bezpieczne oddanie sterowania przy zatrzymaniu; po starcie przełącznik tak, jak był, a sterowanie znów trzyma kocioł |
| B4 | termostat znów grzeje po oddaniu sterowania, które nastąpiło po „off” | pass | CH=0 ze sterowania, potem bezpieczne oddanie sterowania z CH=1; wezwanie od termostatu ściennego dotarło do kotła |
| B5 | trzy przeładowania pod rząd | pass | 20 poleceń do bramki na 5 min przed i po: jedna pętla sterowania |
| B6 | Home Assistant zabity (`docker kill`, decyzja 15) | pass (reviewed) | wrócił w kilka sekund; przełącznik tak, jak zostawił go użytkownik (włączony), sterowanie od razu znów trzyma kocioł — „oddanie sterowania czeka, aż sterowanie zostanie wznowione”; drugą gałąź (życzenie wyłączone) sprawdza K1 |
| C1 | nieświeże dane (sygnał zasilania) | pass | przez 4 min nic nie zapisane; potem bezpieczne oddanie sterowania, „oddane”, alarm „dane kotła utracone” |
| C2 | czujnik temperatury zewnętrznej przestał działać | pass | zamiast niego pogoda (`outdoor_weather`), nastawa trzymana |
| C3 | utrata całej łączności z bramką | pass | „oddane”, powód `boiler_link_stale`; oddanie sterowania wysyłane raz po raz; alarm „oddanie sterowania nie powiodło się” |
| C4 | oddanie sterowania, gdy bramka jest niedostępna | pass | alarm od razu, nadal włączony po 3 min; przyjęte w ciągu 70 s od powrotu bramki; alarm wygaszony; nic więcej |
| C5 | reset bramki | pass | polecenie wysłane ponownie 14 s po resecie (przed 30-sekundowym podtrzymaniem); bez oddania sterowania, bez alarmu |
| C6 | brak jakiegokolwiek odczytu temperatury zewnętrznej przez 3 h | pass | najpierw `outdoor_held`; po 3 h `outdoor_unknown` i nastawa awaryjna (51.1 °C, z rampą), c.o. włączone — nigdy zero ciepła |
| D1 | polecenia gubione na bramce od początku | pass | alarm „kocioł nie przyjmuje polecenia” po trzech policzonych wysyłkach (po 2 min każda); nigdy nie uznano za inny sterownik; bez oddania sterowania; nie wysyłane ponownie |
| D2 | kocioł ignoruje to, co wysyła bramka | pass | bez alarmu (bramka odsyła to, co sama wysyła — to ograniczenie prawdziwej ścieżki); bez oddania sterowania; kocioł na własnej krzywej (42 °C) |
| D3 | inny sterownik (nastawa wymuszona na 62 °C) | pass | przepisana raz; potem bezpieczne oddanie sterowania, zatrzaśnięte `outside_change`; bez walki |
| D5 | zgubione nadpisania | pass | pierwsze dwa wysłane ponownie w ciągu 12 s; trzecie w ciągu godziny: bezpieczne oddanie sterowania, zatrzaśnięte `outside_change`; bez walki przez 10 min |
| D6 | stała nastawa przycinana na bramce | pass | uznane za inny sterownik: bezpieczne oddanie sterowania, zatrzaśnięte `outside_change` |
| D7 | ID 1 odrzucone przez kocioł | pass (reviewed) | wysyłki uznane za zignorowane (alarm), nigdy za inny sterownik, bez oddania sterowania, nie wysyłane ponownie; potwierdzenie bramki trwa krócej niż jeden krok symulatora i nigdy nie pojawia się w stanie odczytu zwrotnego |
| D8 | pobór c.w.u. podczas sterowania | pass | strefa SmartPI (zawór otwarty) wstrzymana na czas poboru i wznowiona po nim; bez zmiany z zewnątrz, bez zatrzasku; bit włączenia c.w.u. nigdy nie zapisany |
| E1 | twarde maksimum przy silnym mrozie (−25 °C, maksimum 48 °C) | pass | najwyższa nastawa 48.0 °C; powód `limit_hard_max` |
| E2 | strefa poza trybem centralnym przy „Stopped” | pass | salon wciąż wołał; wtyczka grzała dla niego; bez oddania sterowania |
| E3 | opóźnienie włączenia VT 120 s | pass | przy długim wezwaniu grzanie włączone 125 i 130 s po otwarciu pierwszego zaworu; wyłączenia nieopóźnione |
| E5 | „Stopped” i pokój o temperaturze 4 °C za zaworem, który VT trzyma zamknięty | pass | brak grzania wbrew zamkniętym zaworom („bezczynność”, c.o. wyłączone), bez oddania sterowania; zgłoszenie naprawy `frost_zone_closed` |
| F1 | usterka kotła: niskie ciśnienie | pass | przez 4 min nic; potem CH=0, bez oddania sterowania, bez zatrzasku, stan `boiler_fault`, zgłoszenie naprawy; c.o. wraca po ustąpieniu usterki |
| F2 | blokada awaryjna kotła | pass | jak w F1 |
| G1 | brak źródła potwierdzonej nastawy | pass | odrzucone przez formularz opcji (`confirmed_entity_missing`) |
| G2 | tryb tylko monitorowania | pass | odrzucone przez formularz opcji (`topology_no_control`) |
| G3 | styk włącz/wyłącz albo „nie wiem” na zaciskach termostatu | pass | formularz ostrzega „Ta zmiana zatrzymuje sterowanie” i zapisuje dopiero po „Zapisz mimo to”; potem odmowa włączenia przełącznika (`blocked_thermostat_on_off`; przy „nie wiem” sterowanie czeka), nic nie zapisane, termostat grzeje |
| H1 | wszystkie strefy VT niedostępne | pass | polecenie trzymane 10 min (`zones_recognition`); potem alarm „brak znanych stref”, zgłoszenie naprawy, bezpieczne oddanie sterowania termostatowi; sterowanie wróciło, gdy strefy wróciły |
| M1 | własny monitor wtyczki zawodzi (wstrzykiwacz błędów) | pass | sterowanie działało dalej 4 min; potem bezpieczne oddanie sterowania, blokada (`monitor_failed`), nie zatrzask; zgłoszenie naprawy; w czasie awarii nic nie zapisane; wróciło samo minutę po tym, jak monitor znów zadziałał |
| K1 | magazyny z przebiegu zakończonego awarią, życzenie wyłączone (wstrzykiwacz błędów) | pass | najpierw bezpieczne oddanie sterowania; przełącznik wyłączony; nic więcej |
| K2 | magazyn wpisu w innej wersji, brak magazynu sterowania | pass | najpierw bezpieczne oddanie sterowania; przełącznik wyłączony |
| K3 | zapisany zatrzask i zaległe oddanie sterowania | pass | najpierw bezpieczne oddanie sterowania; po włączeniu: nic nie zapisane, zatrzaśnięte `outside_change`; wyłączenie i włączenie go skasowało |
| K4 | magazyn sterowania zniknął, a magazyn wpisu mówi, że został zachowany | pass | najpierw bezpieczne oddanie sterowania; przełącznik wyłączony |
| K5 | wpis bramki bez odpowiedzi o zaciskach (jak przed 0.2.2) | pass | przez 10 min nic nie zapisane; blokada `thermostat_kind_unknown`; zgłoszenie naprawy, znika po udzieleniu odpowiedzi; termostat grzeje |
| D4 | inny sterownik, z opcją „powrót samoczynny” | pass | ustąpienie i zatrzaśnięcie; bez powrotu, dopóki cisza trwa krócej niż godzinę; powrót po godzinie ciszy (pierwszy przebieg trafił na zmianę programu termostatu ściennego o 06:00, która słusznie zaczęła godzinę od nowa) |
| E4 | korekta komfortu | partial | woda wzrosła o 2.5 K ponad krzywą (1 K na 30 min, gdy ciepło płynęło) i nigdy powyżej 3 K; powiadomienie o granicy wymaga 3 h na granicy, dłużej niż trwał przebieg — ostrzeżenie na granicy pokazują Q1 i Q5 (sekcja 4.5) |

Przebiegi sprawdzone ręcznie i przebiegi, w których runner się pomylił (żaden nie był winą wtyczki):

- B4, G1, G2, G3 najpierw zawiodły przez runnera: warunek wstępny nigdy niespełniony, puste pole
  wysłane jako null, odmowa formularza wzięta za zapis, krok „Zapisz mimo to” nieobsłużony.
- D1 i E3 zawiodły na czasach mierzonych przez runnera: alarm w D1 przyszedł wcześniej niż w teście
  w procesie, bo wpis w teście w procesie startuje razem z testem (jego 5-minutowy ślad startowy);
  runner w E3 mierzył najpierw od ostatniej zmiany zaworu, potem od impulsów TPI krótszych niż
  opóźnienie, które nigdy nie uruchamiają kotła — to reguła VT, o której ostrzega opis opcji; przy
  długim wezwaniu scenariusz przeszedł.
- D7 i D8 raz zostały uruchomione, gdy salon miał jeszcze 4 °C po E5 (ochrona przed mrozem,
  słusznie), a D8 jeszcze raz przy zamkniętym zaworze strefy SmartPI (nie było czego wstrzymać,
  słusznie); runner teraz przywraca pokoje i sprawia, że strefa woła.
- D4 najpierw działał bez swojej opcji: formularz potwierdza „powrót samoczynny” na osobnym kroku
  („oba będą sterować kotłem na zmianę”), a runner go nie zaznaczył.
- Strefy w trybie bezpieczeństwa VT: VT uważa czujnik, którego stan nie był zapisany przez 60 min,
  za martwy, a stałe temperatury pokoi i temperatura zewnętrzna w symulatorze trzymają jedną
  wartość dłużej; strefy były w trybie bezpieczeństwa w godzinach od 18:34 do 19:43 i od 20:42 do
  22:31 dnia 2026-10-08. Scenariusze uruchomione wtedy, które zależą od stref (E2, E3, D1, D7, D8,
  B5), powtórzono po podniesieniu opóźnienia bezpieczeństwa każdej strefy do 1440 min
  (`docs/pl/testing/test-environment.md`, sekcja 4). Wtyczka pokazała strefę w trybie
  bezpieczeństwa VT jako strefę o nieznanym stanie, z jej alarmem.

### 4.2 Instancja 1, drugi przebieg (kody b i c)

Wpis utworzony przez kod (a) zaktualizował się na miejscu: jego opcje przeszły z wersji podrzędnej
5 na 6 przy pierwszym starcie, bez ostrzeżenia i błędu, a każdy scenariusz sterowania z pierwszego
przebiegu uruchomiono ponownie.

| ID | Wynik | Uwagi |
|---|---|---|
| G1, G2, G3 | pass | pierwsze kroki konfiguracji i opcji w kształcie zmienionym przez I6 |
| F1, F2 | pass (reviewed) | pierwsza próba miała pokoje na zadanych temperaturach, więc grzanie nie było włączone, gdy przyszła usterka; z pokojami wołającymi: przez 4 min nic, potem CH=0, `boiler_fault`, zgłoszenie, powrót po ustąpieniu usterki |
| D8 | pass | wstrzymanie i wznowienie SmartPI podczas poboru |
| C1, C2, C3, C4 | pass | jak w pierwszym przebiegu |
| C5 | pass (reviewed) | reset bramki obsłużony (wysłane ponownie 0.7 s po nim); jego sprawdzenie „bez alarmu” trafiło na L4 |
| K1, K2, K3, K4, K5 | pass | jak w pierwszym przebiegu |
| E6 | pass | kocioł pracujący krótkimi cyklami przy +10 °C: 11 startów w ciągu godziny; grzanie nigdy nie wyłączone przy otwartym zaworze (sprawdzono 119 przełączeń) |
| B1, B2, B3, B4, B5 | pass | jak w pierwszym przebiegu |
| B6 | pass (reviewed) | przełącznik wrócił tak, jak był, sterowanie wznowione; runner najpierw oczekiwał „off” (poprawione, docs/en/specification/scope.md §7) |
| D1, D2, D3, D5, D6, D7 | pass | jak w pierwszym przebiegu |
| D4 | pass | ustąpienie po 150 s; bez powrotu, dopóki cisza trwa krócej niż godzinę; nowa sesja znów sterowała |
| E1, E2, E3, E5 | pass | jak w pierwszym przebiegu |
| H1, M1 | pass | jak w pierwszym przebiegu |
| W1 | pass | własny program termostatu ściennego w czasie rzeczywistym: pokazany na przełączniku (17 °C w nocy); sterowanie oddane, termostat nie woła w nocy, gdy jego pokój ma 19 °C; o 06:00 jego program ustawił dla pokoju 21 °C i termostat od razu zawołał, kocioł grzał; wtyczka nic nie zapisała po oddaniu sterowania |
| C6 | pass | ostatnia wartość temperatury zewnętrznej trzymana, po 3 h nastawa awaryjna (51.1 °C), c.o. włączone |
| E4 | partial | jak w pierwszym przebiegu (2.4 K w 3 h) |

### 4.3 Instancja 6 — ścieżka przez przekaźnik (kod b)

Kocioł włącz/wyłącz, którego zaciski termostatu zamyka przekaźnik symulatora; przekaźnik
zadeklarowany jako zgłaszający swój stan, „off” po zaniku zasilania, bez timera, stan spoczynku
„off”. Własne ustawienia przekaźnika zmienia na miejscu `relay_setup` symulatora dla R9 do R16.

| ID | Scenariusz | Wynik | Dowody |
|---|---|---|---|
| R1 | przekaźnik podąża za strefami VT w obie strony | pass | włączony, gdy pokoje wołają, wyłączony po zaspokojeniu, znów włączony |
| R2 | przekaźnik się restartuje, widać go jako niedostępny | pass (reviewed) | znów „on” po 20 s; bez alarmu |
| R3 | przekaźnik restartuje się niezauważony | pass (reviewed) | znów „on” po 10 s |
| R4 | automatyka przełącza przekaźnik, gdy jest dostępny | pass (reviewed) | zapisane z powrotem raz; za drugim razem wtyczka ustąpiła po 20 s, stan spoczynku zapisany raz, potem przekaźnik zostawiony w spokoju |
| R5 | przekaźnik traci Wi-Fi na 8 min | pass | w tym czasie nic nie zapisane; alarm i zgłoszenie po 5 min; po powrocie polecenie wysłane ponownie |
| R6 | start po otwarciu pierwszego zaworu | pass | przekaźnik włączony 125 s po otwarciu pierwszego zaworu |
| R7 | Home Assistant zatrzymany i uruchomiony | pass | wyłączony przy zatrzymaniu, potem znów włączony |
| R8 | bez zaznaczenia osobnego styku | pass | „ta zmiana zatrzymuje sterowanie”, potem odmowa włączenia przełącznika; nic do przekaźnika |
| R9 | zadeklarowany 10-minutowy timer, który „on” uruchamia od nowa | pass (reviewed) | odnowiony 6 razy w 30 min, nigdy nie wygasł, bez alarmu, nie było o co pytać |
| R10 | zadeklarowany 11-minutowy timer, który liczy się od pierwszego „on” | pass (reviewed) | każde wygaśnięcie obsłużone od razu, nie liczone, bez alarmu |
| R11 | timer „nie wiem”, własny timer przekaźnika uruchamiany od nowa przez „on” | pass | utrzymany włączony powtórzeniami (co najwyżej co 5 min); „off” raz, bez powtórzeń |
| R12 | stan po zaniku zasilania (4 przypadki) | pass | wyłączony, choć polecono włączyć: znów „on”; włączony, choć polecono wyłączyć: znów „off”; „last”: nic |
| R13 | encja przekaźnika w trybie optymistycznym | pass (reviewed) | „sterowany bez potwierdzenia”, sprawdzenie przekaźnika „niezweryfikowane”; niezauważony restart cofnięty przez ślepe powtórzenie (230 s); „off” też powtarzane |
| R14 | 20-minutowa blokada ponownego startu wobec 30-minutowego dowodu grzania | pass | palnik zapalił się 19 min po przekaźniku; bez „kocioł nie odpowiada” |
| R15 | przekaźnik „inching” wyłączony 2 min po każdym „on” | pass (reviewed) | trzy wyłączenia obsłużone, przy czwartym wtyczka ustąpiła po 8.8 min od początku sterowania; zgłoszenie o zatrzasku podaje „około 2 min”; potem zostawiony w spokoju |
| R16 | niezadeklarowany 11-minutowy timer | pass | rozpoznany przy drugim wygaśnięciu: ostrzeżenie prosi o zadeklarowanie go (11 min); grzanie trwa dalej |
| R17 | wszystkie strefy nieznane, zaznaczenie „własny sterownik pokoju” | pass | spoczynek „on”: oddane, przekaźnik włączony, `no_zone_known_handed_back`; spoczynek „off”: bezczynność, przekaźnik wyłączony, `no_zone_known_off` |
| R18 | opóźnienie włączenia VT 120 s na ścieżce przekaźnika | pass (reviewed) | każdy start czekał 125 i 130 s |

Sprawdzone ręcznie: runner najpierw wysyłał zdarzenia w obrębie 120-sekundowego okna potwierdzenia
reguły przekaźnika (R2–R4; testy w procesie czekają 130 s); mierzył od cyklu VT, który zaczął się
przed wezwaniem (R9, R13); użył 10-minutowego timera, który wygasa razem z 5-minutowym odnowieniem
i dlatego jest ukryty przed Home Assistantem (R10, PB-25); czekał, aż przekaźnik „inching”
pozostanie włączony (R15); i mierzył start od otwarcia zaworu, podczas gdy trwało jeszcze czekanie
od wcześniejszego impulsu (R18). Każdy z nich przeszedł po poprawieniu.

### 4.4 Instancja 7 — ścieżka przez encje, urządzenie trzymane (kody b i c)

`number.boiler_sim_flow_setpoint` i `switch.boiler_sim_ch_enable`, oba trzymane; odczyt zwrotny to
własna nastawa sterowania kotła; wartość oddania sterowania 0 „własne sterowanie”.

| ID | Scenariusz | Wynik | Dowody |
|---|---|---|---|
| N1 | sterowanie i bezpieczne oddanie sterowania | pass | |
| N2 | urządzenie restartuje się podczas oddawania sterowania | kod b: FAIL (F7); kod c: pass | kod b: po powrocie zapisany raz tylko włącznik grzania — nastawa uznana za „trzymaną przez inny sterownik”, zanim wtyczka w ogóle ją zapisała (dwa razy); kod c: po powrocie zapisane raz [20, c.o. włączone, 0], alarm wygaszony po sprawdzeniach ponowienia (`taken_by_other`) |
| N3 | nastawa, którą kocioł zapisuje na stałe, albo mógłby zapisać | pass | odrzucone tam, gdzie jest wpisywana (`write_type_not_supported`) |
| N4 | bez włącznika grzania | pass | „ta zmiana zatrzymuje sterowanie”, potem odmowa włączenia przełącznika |
| N5 | wszystkie strefy nieznane, z zaznaczeniem własnego sterownika pokoju i bez niego | pass | z: oddane własnemu sterownikowi kotła; bez: bezczynność, bez oddania sterowania |
| N6 | sama encja nastawy niedostępna podczas oddawania sterowania | pass | w tym czasie nic nie zapisane; po powrocie [20, 0] zapisane raz; alarm wygaszony po sprawdzeniach ponowienia (`taken_by_other`: pytanie K4 o wartość własnego sterowania odczytaną z kotła) |
| N7 | przełącznik włączający sterowanie zewnętrzne jako oddanie sterowania | pass | włączony ze sterowaniem, wyłączony przy oddaniu sterowania, znów włączony |
| N8 | oddanie sterowania przez limit czasu na wygasającej nastawie | pass | najniższa wartość raz, potem limit czasu urządzenia ją zwalnia; urządzenie, które zachowuje wartość: alarm 245 s po oddaniu sterowania (jego limit czasu + 3 min), nic więcej nie zapisane |
| U1 | ogrzewanie podłogowe, maksimum obiegu 40 °C, −5 °C | pass | każda nastawa ≤ 40.0, pokazane `limit_circuit_max`; temperatura zasilania ≤ 40.0; alarm zbyt gorącej wody (45 °C) nieaktywny, oceniony |
| U2 | ogrzewanie podłogowe i grzejnik na jednym obiegu, +5 °C | pass | nastawy ≤ 38.0, nic nie ograniczono; alarm nieaktywny |
| L1 | 12 h przy +12 °C | pass (reviewed) | pokoje w granicach 1.5 K; bez alarmu i zatrzasku; grzanie podąża za VT (poprawiono próbkowanie runnera) |

NEW-N2: przebieg po #51 sprawdził alarm 50 s po powrocie urządzenia, przed dwoma sprawdzeniami
ponowienia w odstępie minuty, które oceniają odczyt zwrotny własnego sterowania trzymanego
urządzenia; runner teraz na nie czeka, a N2 przeszedł 2026-10-11 o 07:26 UTC. Przebiegi N2 i N6 z
2026-10-10 o 16:46 były na złej konfiguracji i są nieważne: N8 zostawił instancję na oddaniu
sterowania przez limit czasu (jego przywrócenie zostało odrzucone, gdy oddanie sterowania było
zaległe, czego runner nie zauważył) — to nie regresja #51, jak najpierw zgłoszono; runner teraz
odmawia uruchomienia scenariusza na instancji, która nie jest w stanie bazowym, a odrzucone
przywrócenie zatrzymuje go z wyraźnym komunikatem.

### 4.5 Instancja 8 — samodzielna bramka (kody b i c) i poprawki z 2026-10-10

| ID | Scenariusz | Wynik | Dowody |
|---|---|---|---|
| S1 | oddanie sterowania przez samodzielną bramkę | pass | przełącznik mówi „grzanie się zatrzymuje”; grzanie zatrzymuje się od razu |
| S2 | wszystkie strefy nieznane, samodzielna | pass | bezczynność, c.o. wyłączone, bez oddania sterowania |
| L1 | 12 h przy −2 °C | pass (reviewed) | nastawa podtrzymywana (najdłuższa przerwa 30 s), 94 przełączenia podążające za VT, bez alarmu i zatrzasku, c.w.u. nietknięta; pokoje 1.1–1.7 K poniżej swoich nastaw — F11 |
| T1 | Home Assistant w jednostkach amerykańskich (US customary) | pass | sygnały w °F (zasilanie 98.4 °F), kocioł dostał °C (43.7–44.2 °C), bez alarmu, bezpieczne oddanie sterowania; limity VT ustawione w °F na czas testu, wszystko potem przywrócone |
| Q2 | za niska krzywa, korekta wyłączona (G11 E) | FAIL (scenario) | płomień nigdy nie palił się 3 h bez przerwy (najwyżej 2.2 h): reguła długiego palenia słusznie się nie uruchomiła — F10 |
| Q5 | jeden pokój niedogrzany, gdy pozostałe trzymają nastawy (G11 B) | pass | korekta rosła dla niego (61 min); na granicy 3 K ostrzeżenie `room_short_at_limit` z nazwą `climate.zone_living` |

Na instancji 1 (kod c): Q1 pass — za niska krzywa przy włączonej korekcie i SmartPI sypialni
zresetowanym do fazy nauki, pokoje 0.2 K poniżej nastaw: korekta ruszyła (55 min), a na granicy
ostrzeżenie `curve_too_low` wskazało trzy strefy; Q3 pass — temperatura pokojowa krzywej w trybie
Auto podążała za najcieplejszym pokojem (22 → 23 °C), z górnym ograniczeniem 23 °C, nieruszana
przez chłodniejszy pokój, wykluczona łazienka pominięta (21 °C); Q4 pass — spadek o 1.5 K w jednym
pokoju: „okno prawdopodobnie otwarte” 10 s później, bez korekty przez 30 min.

## 5. Kryterium startów

Cztery przebiegi obok siebie (instancje od 2 do 5, `devenv/config/starts.yaml`): sterowanie
wtyczki wobec własnej regulacji kotła, przy +8 °C i przy −5 °C z dobowym wahaniem ±3 K, każda
strefa na TPI, krzywa wtyczki ustawiona jak własna krzywa kotła. Kryterium: sterowanie uruchamia
palnik co najwyżej 1.10 razy częściej, a pokoje są co najwyżej o 0.3 K chłodniejsze.

Pierwszy przebieg — kod (a), korekta wyłączona, cała doba (2026-10-09 16:27 → 2026-10-10 16:27 UTC):

| | +8 °C sterowanie | +8 °C własna | −5 °C sterowanie | −5 °C własna |
|---|---|---|---|---|
| starty palnika | 149 | 145 | 55 | 32 |
| starty na godzinę | 6.2 | 6.0 | 2.3 | 1.3 |
| przełączenia grzania | 368 | 356 | 110 | 66 |
| średnia nastawa | 37.6 | 37.0 | 50.6 | 50.0 |
| pokoje (salon / sypialnia / łazienka) | 19.41 / 18.59 / 20.61 | 19.37 / 18.55 / 20.58 | 19.44 / 18.53 / 20.77 | 19.43 / 18.53 / 20.78 |

×1.03 przy +8 °C — pass; ×1.72 przy −5 °C — FAIL; pokoje równie ciepłe w obu przypadkach. W teście
w procesie: ×1.20 i ×2.16. Sterowanie trzymało kocioł przez cały czas. Woda taka sama w granicach
0.6 K: sterowanie częściej włącza i wyłącza grzanie (grzanie od razu podąża za strefami VT), a przy
−5 °C cykle TPI w VT zostawiają krótkie chwile, w których żadna strefa nie woła. Same godziny nocne
(23:00–07:00) z tego samego przebiegu dają ×0.96 i ×0.93.

Drugi przebieg — kod (c), korekta komfortu włączona, tylko noc (2026-10-10 23:00 → 2026-10-11 07:00
UTC, skrócony na prośbę użytkownika; 6 h na ustabilizowanie):

| noc | +8 °C sterowanie | +8 °C własna | −5 °C sterowanie | −5 °C własna |
|---|---|---|---|---|
| starty palnika | 86 | 66 | 53 | 12 |
| średnia nastawa / zasilanie | 41.2 / 37.7 | 39.2 / 37.2 | 55.5 / 51.7 | 52.2 / 51.4 |
| płomień pali się | 44 % | 53 % | 67 % | 92 % |
| pokoje (salon / sypialnia / łazienka) | 19.40 / 18.54 / 20.67 | 19.40 / 18.53 / 20.66 | 19.49 / 18.59 / 20.86 | 19.45 / 18.55 / 20.79 |

×1.30 przy +8 °C i ×4.42 przy −5 °C — FAIL; zysk w komforcie 0.00–0.07 K. Przy −5 °C korekta stała
na granicy 3 K z podniesionym `curve_too_low` — F8.

## 6. Nieuruchomione i dlaczego

- H2, strefa w trybie „auto” lub typu over_climate: strefy over_switch w VT mają tylko grzanie i
  wyłączenie; objęte testami w procesie.
- Ścieżka MQTT przez firmware: działa droga przez zaślepkę `opentherm_gw`; MQTT potrzebuje brokera
  w LXC.
- Typy połączeń z I6 poza ścieżkami ogólnymi (ESPHome, EMS-ESP, moduł Wi-Fi kotła): symulator
  oferuje tylko ogólną ścieżkę przez encje.
- Ogrzewanie podłogowe przez sześć godzin: po 100 min (U1, U2), wystarcza dla ograniczenia i alarmu.
- Home Assistant w °F na ścieżce przez encje: tylko na ścieżce przez bramkę (T1).
- Klasy reguły długiego palenia (G11 E): nie osiągnięte (Q2, F10).
- `dev` po G11 (I7, I8): nietestowany; następny przebieg jest na `qas`.

## 7. Ustalenia i znane ograniczenia

Stan z rana 2026-10-11: N2 znów przeszedł (kod c); N8 działa ponownie na instancji 7, żeby
sprawdzić jego przywrócenie po zaległym oddaniu sterowania.

| # | Ustalenie | Waga | Co dalej |
|---|---|---|---|
| F1 | symulator nie miał `services.yaml`: Home Assistant zapisał błąd w logu przy starcie (jego usługi działały) | niska, tylko test | naprawione (#32) |
| F2 | na świeżej instalacji wtyczka zapisała w logu ostrzeżenie „No stored control state could be read; control is not configured, so nothing is owed” — normalny stan na poziomie ostrzeżenia | niska | naprawione (#34): poziom informacji |
| F3 | polskie tłumaczenie VT 10.4.0 nie przechodzi kontroli symboli zastępczych Home Assistanta (dwa teksty) | niska, sprawa samego VT | nic tutaj |
| F4 | `select.central_mode` w notatkach to nazwa opcji; identyfikator encji wynika z nazwy wpisu centralnego | brak | brak |
| F5 | konfiguracja centralna VT utworzona po starcie Home Assistanta — bez kotła centralnego — trzyma sterowanie w oczekiwaniu do restartu (zgodnie z założeniem) | niska | mówi o tym przewodnik użytkownika (#35) |
| F6 | VT przełącza strefę w tryb bezpieczeństwa, gdy stan jej czujnika nie jest zapisywany przez 60 min; stała temperatura pokoju lub zewnętrzna może mieć jedną wartość tak długo — w symulatorze, a więc i w prawdziwym domu z czujnikiem, który zgłasza tylko zmiany | średnia, konfiguracja | podniesiono opóźnienie bezpieczeństwa stref testowych; warto dodać linijkę w przewodniku użytkownika (opóźnienie bezpieczeństwa VT a stałe czujniki) — do decyzji |
| L1 | opóźnienie włączenia VT sprawdza zapotrzebowanie ponownie na końcu: impuls TPI krótszy niż opóźnienie nigdy nie uruchamia kotła | zgodnie z założeniem | napisane w opisie opcji |
| L2 | „powrót samoczynny” liczy swoją godzinę ciszy od ostatniego zapisu innego sterownika, wraz ze zmianami własnego programu termostatu ściennego | zgodnie z założeniem | napisane w potwierdzeniu opcji |
| L3 | za bramką OpenTherm Gateway kocioł, który ignoruje nastawę, nie jest widoczny: bramka odsyła to, co wysyła | ograniczenie prawdziwej ścieżki | znane (PB-91) |
| F7 | trzymane urządzenie restartujące się podczas oddawania sterowania nigdy nie dostało wartości oddania sterowania dla nastawy: trzecia wartość na odczycie zwrotnym po przerwie została uznana za wartość innego sterownika, zanim wtyczka ją zapisała, a alarm „oddanie sterowania nie powiodło się” wygasł | wysoka, ścieżka przez encje | naprawione (#51, #58); J4 N2 przechodzi: po powrocie zapisane raz [20, c.o. włączone, 0] |
| F8 | przy włączonej korekcie komfortu: w nocy ×1.30 (+8 °C) i ×4.42 (−5 °C) własnych startów kotła, za 0.00–0.07 K komfortu — pokoje nadal mają o około 1 K za mało z powodu odchylenia TPI w VT, którego korekta nie usunie, a woda na granicy sprawia, że każdy cykl TPI zatrzymuje palnik | średnia | G11 włączył ją domyślnie w pełnym sterowaniu: do decyzji w K4 (symulacja w testach mówi ×1.39 i ×6.28) |
| F9 | kryterium startów nie jest spełnione przy −5 °C w ciągu całej doby przy wyłączonej korekcie (×1.72; ×0.93 w nocy) | średnia | K4: grzanie od razu podąża za VT zgodnie z regułą użytkownika |
| F10 | reguła długiego palenia działa dopiero po 3 h płomienia bez przerwy; kocioł pracujący cyklami na swoim minimum, gdy pokoje są niedogrzane, nigdy jej nie wyzwala, więc przy wyłączonej korekcie nic nie informuje użytkownika (Q2) | średnia | do decyzji: liczyć udział czasu pracy palnika, a nie jedno nieprzerwane palenie |
| F11 | 12 h przy −2 °C z domyślną krzywą i wyłączoną korektą zostawiło pokoje o 1.1–1.7 K za zimne, płomień na 100 % i temperaturę zasilania na nastawie — kocioł miał zapas, woda była zbyt chłodna (przypadek stojący za G11) | obecnie brak | zajmują się tym G11 B, D i E |
| L4 | czujnik zewnętrzny symulatora, ustawiony ręcznie, nie zmienia się przez ponad 12 h, podczas gdy jego pogoda się zmienia: wtyczka słusznie uznaje go za zawieszony i używa pogody | stanowisko testowe | brak |
| L5 | strefy TPI w VT (współczynniki 0.6 / 0.01) trzymają symulowane pokoje o około 1–1.5 K poniżej ich nastaw w każdych warunkach, z wtyczką i bez niej | stanowisko testowe, VT | nic tutaj; na to natrafia F8 |
| L6 | timer przekaźnika będący całkowitą wielokrotnością 5-minutowego odnowienia wtyczki wygasa razem z odnowieniem, niewidoczny dla Home Assistanta (PB-25) | zgodnie z założeniem | runner używa 11 min |

Błędy samego runnera znalezione i naprawione podczas J4, żaden nie dotyczył wtyczki: czasy w
obrębie okna potwierdzenia reguły przekaźnika; niespełnione warunki wstępne (pokoje na zadanej
temperaturze przed usterką, cykl VT, który zaczął się przed wezwaniem); 10-sekundowe próbki
spóźnione względem zmian wtyczki (L1); odrzucone przywrócenie, gdy oddanie sterowania było
zaległe, niezauważone (N8 → nieważne przebiegi N2/N6); opcje zapisane bez pól, których runner nie
ustawił (nowe wartości domyślne G11). Od 2026-10-10 runner odmawia uruchomienia scenariusza na
instancji, która nie jest w stanie bazowym, zatrzymuje się przy odrzuconym przywróceniu i dołącza
do każdego niepowodzenia ostrzeżenia wtyczki, stan sterowania, alarmy i zgłoszenia.
