[English version](../../en/technical/technical.md)

# Smart Boiler for Versatile Thermostat — dokumentacja techniczna

Status: aktualny.

> **W trakcie budowy, bez wydania.** Integracja nie pracowała jeszcze z prawdziwym kotłem.

Ten dokument opisuje budowę integracji: jej części, jeden krok sterowania, cykl życia, to, co
zapisuje, i sposób testowania. Co integracja robi dla użytkownika, opisuje
[przewodnik użytkownika](../user-guide/user-guide.md); wszystkie zasady i decyzje są w
[`docs/pl/specification/scope.md`](../specification/scope.md). Skróty: Home Assistant (HA), Versatile Thermostat
(VT), OpenTherm Gateway (OTGW), Message Queuing Telemetry Transport (MQTT).

## Spis treści

1. [Przegląd](#1-przegląd)
2. [Struktura repozytorium](#2-struktura-repozytorium)
3. [Zadania komponentów](#3-zadania-komponentów)
4. [Jeden krok sterowania](#4-jeden-krok-sterowania)
5. [Cykl życia](#5-cykl-życia)
6. [Stan trwały](#6-stan-trwały)
7. [Testowanie](#7-testowanie)

## 1. Przegląd

Integracja (domena `vtherm_smart_boiler`) jest wtyczką VT. Zastępuje kocioł centralny VT
działający w trybie wł./wył.: czyta strefy VT, decyduje, kiedy kocioł grzeje i jak ciepła jest
jego woda, zapisuje to do kotła i oddaje kocioł przy każdym wyjściu.

- **Czysta logika w `core/`.** Każde prawo sterowania i uczenia, analiza monitora i werdykt to
  czysty Python bez importów HA — test parsuje importy `core/`, żeby to wymusić. Ten sam rdzeń
  działa w testach jednostkowych, w symulatorze i w HA.
- **Strona HA** wokół niego zbiera dane wejściowe z encji wybranych przez użytkownika, uruchamia
  rdzeń na timerach i przy zmianach stanu, wykonuje jego zapisy i publikuje czujniki, czujniki
  binarne, przełączniki, przyciski i zgłoszenia w Naprawach.
- **`vtherm_link.py` to jedyne wejście do danych stref.** Czyta każdą strefę wyłącznie przez
  `vtherm_api` (zasada użytkownika, 2026-11-24/25; I12.7). Strefa to termostat przekazany przez
  VT modułowi funkcji wtyczki, którego zadeklarowane `entity_id` się zgadza. Z termostatu:
  temperatura pokoju i czas jej pomiaru przez VT, nastawa, tryb, czy strefa grzeje i czy jej
  urządzenie pracuje oraz powód, dla którego VT trzyma ją wyłączoną (tylko okno). Z jego
  `entry_infos`: typ, cykl i urządzenia, czy liczy go centralny kocioł VT, termometr i czujnik
  okna pokoju oraz ustawienia centralnego kotła VT. Z wywołań VT na module funkcji: strefa liczy
  się jako uruchomiona od pierwszego `refresh_state` od VT, a jej wypełnienie i otwarcie zaworu to
  to, co ostatnio podał hak mocy VT jako zastosowane. Strefa, której termostatu VT nie przekazał,
  jest nieznana; nic z encji klimatu VT jej nie zastępuje. Historia pokoi to to, co odczytał,
  przechowywane przez samą wtyczkę (zobacz [Stan trwały](#6-stan-trwały)); nic z encji klimatu VT
  do niej nie trafia. Z encji klimatu VT czyta na razie jeszcze: wybór stref, nazwy stref,
  zgłoszenie o przeładowaniu i tryb centralny VT (aż pokoje będą pochodzić z VT, krok I12.11).
  Wykrywa, co jest zainstalowane (VT i jego wersję, `vtherm_api`), zamiast to zakładać;
  nie czyta niczego ze SmartPI. Żaden inny moduł nie odczytuje stanu strefy po nazwie encji.
- **Moduł funkcji (feature manager) zarejestrowany w VT** (`feature_manager.py`, przez
  `register_feature_manager` z `vtherm_api`) to kanał, którym VT przekazuje każdy termostat.
  Zachowuje to, co mówi mu VT — jego `refresh_state` i hak mocy `async_on_underlying_power` — i
  nie publikuje niczego na termostatach VT: dane o wodzie, które pokazywał do I12.9, usunięto, bo
  nikt ich nie czytał (decyzja użytkownika z 2026-11-25). Jest rejestrowany dopiero po wczytaniu
  VT; termostat, który już działa, trafia do niego dopiero po następnym przeładowaniu VT, którego
  wtyczka nigdy sama nie wywołuje — takie strefy wymienia zgłoszenie w Naprawach, a do tego czasu
  są nieznane.
- **„Nie daje ciepła”** (`binary_sensor`, klucz `no_heat`; `core/boiler_call.py`): jeden sygnał
  dla całego domu, włączony, gdy kocioł nie daje teraz pokojom ciepła, z powodem — kocioł
  centralny VT nie wzywa ciepła, trwa jego opóźnienie włączenia, ciepła woda, usterka kotła albo
  wtyczka nie może ręczyć za ciepło. Wyliczany z decyzji sterowania w każdym kroku; niedostępny,
  gdy sterowanie jest wyłączone. Użytkownik wybiera go w ustawieniu „heating unavailable” w
  SmartPI 1.0 albo używa w automatyzacji: wtyczka sama nie wstrzymuje nauki żadnej strefy
  (I12.9).

Szczegóły: [`docs/pl/specification/scope.md`, §2](../specification/scope.md#2-dlaczego-wtyczka) i
[§5](../specification/scope.md#5-sprzęt-obiegi-i-algorytmy-stref).

## 2. Struktura repozytorium

```text
custom_components/vtherm_smart_boiler/   integracja (strona HA)
├── core/                                 czysta logika, bez importów HA
├── transport/                            odczyt encji kotła i moduły zapisu
├── translations/                         en.json (źródło) i inne języki
└── frontend/                             zbudowana strona „Kocioł” i karty, licencje, teksty
frontend/                                 źródło strony „Kocioł” (TypeScript, Lit, Vite)
tests/                                    testy: core/, integration/, sim/, tools/ i reszta
sim/                                      symulator fizyki i jego komponenty HA tylko do testów
tools/                                    import historii z recordera do analizy offline
devenv/                                   testowy HA (Docker compose) do scenariuszy odbiorczych
scripts/                                  env.sh (uruchamia każde polecenie w projekcie), deploy
docs/                                     dokumentacja, osobny katalog na każdy język
├── en/                                   angielski, wersja podstawowa
│   ├── specification/                    co wtyczka robi (zakres) i jej interfejsy
│   ├── user-guide/                       jak jej używać
│   ├── technical/                        jak jest zbudowana
│   ├── development/                      plan rozwoju; plany i przeglądy (historia)
│   └── testing/                          środowisko testowe i raporty z testów
├── pl/                                   polski: każdy aktualny dokument, ten sam układ
└── images/                               obrazy wspólne dla wszystkich języków
```

- `sim/custom_components/` zawiera `boiler_sim` (symulowany kocioł, pomieszczenia i pogodę) oraz
  zastępczy `opentherm_gw`, oba tylko do testów.
- `tools/import_history.py` zamienia kopię bazy recordera HA na historię rdzenia, żeby analizę
  monitora można było sprawdzić na zapisanych danych: sygnały kotła, pogodę i pomocnika
  przełączanego przez kocioł centralny VT — nigdy encje klimatu VT.
- Strona „Kocioł” ([`plan-0.2-i10.md`](../../en/development/plans/plan-0.2-i10.md)):
  `frontend/` to jej źródło; `npm run build` w tym katalogu zapisuje moduł, który wtyczka
  udostępnia, do `custom_components/vtherm_smart_boiler/frontend/`, razem z licencjami pakietów w
  nim zawartych. Te pliki są w repozytorium, więc HACS je instaluje; CI buduje je ponownie i
  zgłasza błąd, gdy się różnią. Są tam też teksty strony (`frontend/translations/`, angielski to
  źródło): czyta je strona, a `panel.py` bierze z nich nazwę w menu bocznym. To, co mówią już
  encje wtyczki — nazwy alarmów i sygnałów, powody werdyktu, skąd pochodzi wartość budynku —
  strona bierze z własnych tłumaczeń wtyczki (`translations/`), które Home Assistant podaje jej
  w języku użytkownika (`hass.loadBackendTranslation("entity", …)`), więc każde jest zapisane
  raz. `panel.py`
  udostępnia pliki i dodaje stronę do menu bocznego przez `panel_custom` Home Assistanta;
  przełącznik „Strona w menu bocznym” ją zabiera i przywraca. Strona zostaje na czas
  przeładowania — zabrana, wyrzuciłaby oglądającego ją użytkownika z błędem; start rejestruje ją
  ponownie w jednym kroku — i znika z wyłączonym albo usuniętym wpisem albo z wyłączonym tym
  przełącznikiem (F17 z J4). Póki wpis działa, `panel.py` każe
  też Home Assistantowi wczytywać ten sam moduł na każdej stronie (`frontend.add_extra_js_url`,
  zabierane przy wyładowaniu, starszy adres zastępowany po aktualizacji), więc części przeglądu
  są w wyborze kart jako cztery karty — stan i kafelki, schemat i pokoje, krzywa, ostatnie 24 h —
  każda to własna część strony (`frontend/src/cards.ts`), bez ustawień: każda sama znajduje
  działający wpis przez `vtherm_smart_boiler/installation`. Gdy frontend Home Assistanta nie
  działa, nic nie jest rejestrowane. Node.js instaluje `scripts/bootstrap_node.sh` do
  `.tools/node/`. `websocket_api.py` to to, co strona czyta: pięć poleceń WebSocket tylko do
  odczytu, dla każdego zalogowanego użytkownika, każde odpowiada z działającego wpisu (inaczej
  błąd `not_running`): `vtherm_smart_boiler/installation` — kocioł, obiegi z ich strefami i
  grzejnikami, encja wybrana dla każdego sygnału, encje wtyczki według klucza i ustawienia
  krzywej; `vtherm_smart_boiler/curve` — punkty krzywej dla ustawień w użyciu albo dla wartości
  roboczych, bez zapisu, z `core/curve_view.py` (krzywa przy temperaturze pokojowej w użyciu,
  potem limity, tak jak decyduje sterowanie przed korektą komfortu, potrzebą obiegu i rampą), ze
  sprawdzeniami z ustawień według ich kluczy tłumaczeń; `vtherm_smart_boiler/days` — podsumowania
  dni w zapisanej postaci, razem z gazem na stopniodzień z ostatnich 12 tygodni liczonym przez
  `core/weekly.py` (tydzień bez gazu w którymś dniu nie ma wyniku, zasada monitora), sygnaturą
  energetyczną dopasowaną przez `core/signature.py` — gaz na grzanie każdego dnia na 24 h wobec
  jego średniej temperatury zewnętrznej, osobno dni tylko obserwowane i dni pod sterowaniem, linia
  każdej grupy przez jej dni grzania (zimniejsze niż próg grzania w użyciu, z gazem na grzanie)
  według zasad dopasowania budynku (`core/building.py`: liczba dni, rozrzut temperatur, więcej
  gazu w zimniejsze dni, R²) albo powód jej braku, i obie porównane w środku temperatur, które
  obie obejmują — oraz z jednostką licznika gazu (bez licznika żadną: gaz jest wtedy szacowany w
  jednostce danych gazu kotła); każdy dzień zapisany od I10.7 trzyma swoje starty grzania
  godzina po godzinie od swojego początku (`hourly_starts`, 23 albo 25 godzin przy zmianie
  czasu), które strona umieszcza na ich godzinach zegarowych; dni zapisane wcześniej ich nie mają
  i nadal są czytane;
  `vtherm_smart_boiler/burns` — palenia z ostatniej analizy monitora tak,
  jak je sklasyfikował (ogrzewanie, ciepła woda, nieznane), więc strona rysuje palenia samego
  monitora; `vtherm_smart_boiler/journal` — dziennik (zob. [Stan trwały](#6-stan-trwały)), od
  podanej chwili, jeśli ją podano; oraz jeden zapis, tylko dla administratora:
  `vtherm_smart_boiler/curve/save` zapisuje punkt krzywej przy największym mrozie i, na poziomie
  zaawansowanym, jej przesunięcie **przez własne ustawienia wtyczki** — ich formularz „Krzywa
  grzewcza” wypełniony zapisanymi wartościami i zmianami, potem „Zapisz i zakończ” — więc każde
  sprawdzenie i sam zapis z przeładowaniem są tych ustawień; odmowa wraca z polem i kluczem
  tłumaczenia, a zapisu, przy którym ustawienia by się zatrzymały (potwierdzenie, inna sekcja),
  się nie robi. Ich schematy używają `probatio`, jak własne polecenia Home Assistanta od 2026.10.
  Zakładka „Stan i alarmy” zapomina zmierzoną wartość budynku własnymi przyciskami wtyczki
  (`button.press`), dostępnymi tylko dla administratora, po potwierdzeniu.

## 3. Zadania komponentów

**Konfiguracja wpisu (`__init__.py`).** Czyta opcje wpisu do `EntryConfig`, buduje koordynator
i jednostkę sterowania, dołącza koordynator do modułu funkcji, a przy wyładowaniu najpierw
zatrzymuje jednostkę sterowania (oddaje ona kocioł), a koordynator na końcu. HA jest
importowany tylko wewnątrz funkcji.

**Koordynator (`coordinator.py`, `SmartBoilerCoordinator`).** Śledzi wskazane encje, trzyma
historię kroczącą i wylicza to, co publikują encje. Szybka ścieżka działa przy zmianach stanu i
co 30 sekund (odczyty, sprawdzenie sygnałów, ciepła woda, bieżące alarmy); analiza
(`core/analysis.py`) działa co kilka minut na kopii historii, poza pętlą zdarzeń. Koordynator
zarządza też magazynami (zobacz [Stan trwały](#6-stan-trwały)).

Historia (`core/history.py`, `History`) ma trzy źródła. Sygnały kotła, pogoda, stan sterowania
wtyczki i pomocnik przełączany przez kocioł centralny VT przychodzą na żywo z ich stanów, a po
starcie z rejestratora: ostatnie 8 dni (`HISTORY_DAYS`) i starsze dni, do roku wstecz, tylko do
budowy podsumowań dni. Pokoje pochodzą z własnych odczytów wtyczki przez `vtherm_api`, przy każdym
odświeżeniu (30 s) i każdym kroku sterowania (10 s), tylko zmiany (`ZoneSeries.record`), a po
starcie z magazynu pokoi — nigdy z zapisów encji klimatu VT w rejestratorze (I12.7b). „Czy kocioł
był wezwany do grzania” (`History.zone_demand`, `zone_calling`) to stan pomocnika wszędzie, gdzie
jest znany — własna decyzja VT, z jego progami — a pokoje tylko tam, gdzie nie jest, albo gdy
pomocnik nie jest ustawiony (samo monitorowanie). Odróżnia palenia na grzanie od ciepłej wody
(każde podsumowanie dnia, werdykt, dopasowanie budynku), przerwy, które może ocenić dryf
histerezy, krótkie palenia liczone przez niestabilny zapłon i palenia brane przez dowody
najniższej temperatury wody. Własne szczegóły pokoi — średnia nastawa w raporcie, otwarcia
zaworów w tych dowodach — pochodzą tylko z magazynu pokoi, więc zaczynają się od instalacji.

**Monitor i analiza (`core/monitor.py`, `core/analysis.py`, `core/verdict.py`).** Od historii do
cykli pracy palnika, metryk, ostrzeżeń o trendach, raportu i werdyktu sterowania, zawsze z
powodami. `core/alarms.py` zawiera alarmy monitora, z histerezą, żeby nie migotały.

**Jednostka sterowania (`control.py`, `ControlUnit`).** Strona HA sterowania: krok sterowania co
kilka sekund, jego zapisy przez moduł zapisu, oddanie kotła przy każdym wyjściu i stan
pokazywany przez encje — w tym „Nie daje ciepła”. Zamienia zdarzenia zabezpieczeń i awarie
na alarmy. Moduł zapisu istnieje tylko wtedy, gdy sterowanie jest włączone. Błąd wewnętrzny
oddaje kocioł i blokuje sterowanie zatrzaskiem.

**Krok sterowania (`core/loop.py`, `loop_step`).** Jeden krok: od decyzji sterownika, przez
zabezpieczenia zapisu, do tego, co zostaje zapisane teraz. Ten sam krok napędza symulator i HA.
Przekaźnik ma własny krok (`core/relay.py`).

**Sterownik (`core/controller.py`, `decide`).** Maszyna stanów, która zamienia to, co wtyczka
wie, na polecenie dla kotła, w stałej kolejności pierwszeństwa: sterowanie wyłączone; zatrzask
albo alarm ustawiony na oddanie kotła; brakujący warunek wstępny (blokada); utracona albo
nieświeża łączność z kotłem; usterka samego kotła; w pozostałych przypadkach włączenie lub
wyłączenie grzania z ochrony przed mrozem i zapotrzebowania stref, a temperatura wody z krzywej
(`core/curve.py`), limitów i rampy.

**Zapotrzebowanie (`core/demand.py`, `boiler_demand`).** To, o czym decydował kocioł centralny
VT, teraz zadanie wtyczki: wołające urządzenia albo strefy (domyślnie urządzenia VT, tak jak
liczy je jego kocioł centralny), łączna moc albo otwarcie zaworów, przy czym każda strefa liczy
się tylko wtedy, gdy VT podaje jej stan jednoznacznie; gdy VT nie podaje stanu urządzenia,
zasada VT — zawór choć trochę otwarty, inaczej cykl pracy powyżej 0.

**Obiegi sterowane przez inną automatykę (`core/circuit_requests.py`, `circuits_asking`).**
Obieg, którego mieszaczem albo pompą steruje coś innego, prosi o ciepło przez własną encję albo
przez swoje strefy; encja, której nie da się odczytać, o nic nie prosi i jest wskazana. Gdy obieg
prosi, jego potrzeba — najpierw odczyt encji, inaczej wpisana wartość — jest dolną granicą wody,
bez żadnego dodatku (`core/limits.py`, `limit_flow`). Stały zawór żadnej granicy nie wyznacza:
kocioł idzie po krzywej, a zawór stoi otwarty, gdy woda jest na poziomie nastawy lub niżej.

**Pilnowanie stref (`core/zone_watch.py`, `follow_zones`).** Okres rozpoznania po starcie
(najwyżej 10 minut), okres przejściowy każdej strefy i przypadek, gdy wszystkie strefy są
nieznane.

**Zabezpieczenia (`core/guards.py`, `plan_write`, `classify`).** Co naprawdę może zostać
zapisane, o cokolwiek prosi sterownik: nic do trwałej pamięci kotła, ogranicznik częstości
zapisów, powtórzenia tam, gdzie wartość wygasa. Oceniają odczyt zwrotny i przypisują zmianę,
której wtyczka nie zrobiła, do utraconego polecenia, wartości ignorowanej od początku, wartości
przyciętej albo innego sterownika.

**Przekaźnik (`core/relay.py`).** Kocioł wł./wył. przełączany przekaźnikiem: co jest do niego
zapisywane, co znaczy zgłaszany przez niego stan i czy kocioł pokazuje, że grzeje.

**Oddanie sterowania (`core/hand_back.py`).** Dowody oddania sterowania: co świadczy o
zwolnieniu, kiedy stała trzecia wartość oznacza, że cel trzyma inny sterownik, i kiedy zmiana
celu dwuwartościowego jest utraconym poleceniem. Jednostka sterowania zapisuje trzy części i
ponawia, aż zostaną potwierdzone.

**Moduły zapisu (`transport/writers.py`).** Jedyny kod, który zmienia kocioł: encja do zapisu,
OTGW przez `opentherm_gw` z HA, firmware OTGW przez MQTT albo przekaźnik. Każdy moduł zapisu zna
usługi, które może wywołać (test sprawdza listę); nieudany zapis zgłasza `WriteError` i nigdy
nie jest uznawany za wykonany. Odczyt kotła jest w `transport/entities.py`, który niczego nie
zapisuje.

**Konfiguracja (`config_flow.py`, `config.py`, `control_config.py`).** Formularze konfiguracji
i opcji oraz opcje sterowania jako obiekty rdzenia, z blokadami, które nie pozwalają ruszyć
sterowaniu. Oba przepływy to jedno menu sekcji; sterowanie to pięć jego pozycji, każda jako jeden
formularz — urządzenie sterujące, krzywa grzewcza, zachowanie sterowania, ochrona przed mrozem,
reakcje na alarmy (`CONTROL_ITEMS`) —, każda pokazana tam, gdzie ma zastosowanie, i otwierana
po sprawdzeniu ścieżki zapisu (`_control_path`). Formularz pokazuje się ponownie z polami, które
odsłoniła odpowiedź (`entity_form_fields`, `relay_form_fields`); wartość ukrytego pola zostaje. Sterowanie czyta swoją sekcję z dołożonymi tematami MQTT połączenia i odczytami
zwrotnymi z sygnałów (`with_boiler_inputs`): każda wartość jest zapisana raz. Strefy należą do
obiegów: każdy obieg wymienia zasilane strefy VT, a z nich te z podłogówką i z konwektorami,
a ze strefy zasilanej tylko w części — jej urządzenia (`devices`, według strefy; formularz
przypisuje każde urządzenie do strefy przez `vtherm_link.zone_devices`); tylko tak strefa może
być w dwóch obiegach. Własna sekcja stref trzyma tylko to, czy zawory strefy zamykają się, gdy
jest wyłączona (`config._circuit_zones`). `repairs.py` zawiera przepływy napraw (na przykład potwierdzenie oddania kotła
zrobionego ręcznie).

## 4. Jeden krok sterowania

Timer uruchamia krok jednostki sterowania (`ControlUnit._async_step` w `control.py`). Czystą
częścią jest `loop_step` w `core/loop.py`, który wywołuje `decide` w `core/controller.py`, a
potem zabezpieczenia w `core/guards.py`.

```mermaid
flowchart TD
    A["Timer: krok sterowania"] --> B{"Magazyny odczytane i strefy śledzone?"}
    B -->|"nie"| Z["Brak decyzji w tym kroku"]
    B -->|"tak"| C["Odczyt: migawka i świeżość kotła, strefy przez vtherm_link, ciepła woda"]
    C --> D["Blokady i zatrzaski"]
    D --> E["Zapotrzebowanie stref, prośby obiegów i ochrona przed mrozem: boiler_demand, circuits_asking, follow_zones"]
    E --> F{"Sterownik decyduje: decide"}
    F -->|"oddanie kotła"| H["Oddanie: najniższa woda, grzanie, gdzie ktoś przejmuje, zwolnienie"]
    F -->|"grzanie, spoczynek, mróz"| G["Zabezpieczenia oceniają odczyt: plan_write, classify"]
    G -->|"inny sterownik"| S["Ustąpienie: oddanie kotła i zatrzask"]
    S --> H
    G -->|"dozwolone"| W["Moduł zapisu zapisuje nastawę i włączenie lub wyłączenie grzania"]
    G -->|"nic do zrobienia"| K["Wstrzymanie: nic nie jest zapisywane"]
    W --> F2["Dalej: zaległe oddanie, przekaźnik, magazyn, stan i „nie daje ciepła”"]
    K --> F2
    H --> F2
```

- **Świeżość:** nic nie jest zapisywane bez świeżych danych kotła — przy przekaźniku bez
  świeżego stanu samego przekaźnika; limity wieku ustawione przez użytkownika należą do
  wskazanych sygnałów i odchodzą razem z nimi. Łączność jest oceniana w oknie (utracona, gdy
  nieświeże kroki pokryją 5 minut w ciągu 10; wraca po 60 sekundach świeżych danych).
- **Blokady i zatrzaski** idą przed zapotrzebowaniem: zatrzask albo alarm ustawiony na oddanie
  kotła oddaje kocioł, o cokolwiek proszą strefy.
- **Decyzja:** włączenie lub wyłączenie grzania jest ustalane w każdym kroku — zapotrzebowanie
  stref albo prośba obiegu sterowanego przez inną automatykę; temperatura wody co odstęp decyzji
  (domyślnie 5 minut) i od razu po końcu blokady albo usterki lub gdy zmienia się potrzeba
  obiegu: krzywa, nigdy poniżej potrzeby proszącego obiegu,
  ograniczona przez obiegi zasilane prosto z kotła i maksimum kotła. Przy kilku obiegach
  temperatura pokojowa krzywej i korekta komfortu biorą pod uwagę strefy obiegu zasilanego
  prosto z kotła.
- **Zabezpieczenia** widzą odczyt zwrotny każdego zapisu; oddania kotła żadne zabezpieczenie
  nigdy nie wstrzymuje.
- **Dalsze kroki:** zaległe oddanie kotła jest ponawiane co minutę, aż zostanie potwierdzone;
  stan sterowania jest zapisywany od razu, gdy się zmieni (zobacz
  [Stan trwały](#6-stan-trwały)).

Szczegóły: [`docs/pl/specification/scope.md`, §7](../specification/scope.md#7-funkcje-według-etapów).

## 5. Cykl życia

**Konfiguracja wpisu.** `async_setup_entry` czyta opcje; część sterowania, której nie da się
użyć, wyłącza tylko sterowanie, a nie cały wpis, więc monitor dalej działa, a zaległe oddanie
kotła i tak zostaje wysłane. Koordynator czyta swoje magazyny; jednostka sterowania ostrożnie
czyta stan sterowania (zobacz niżej) i, zanim cokolwiek innego może zawieść, raz próbuje oddać
kocioł, jeśli poprzednie uruchomienie zostawiło to jako zaległe (niepowodzenie zostaje zaległe i
jest ponawiane przez zegar). Potem startują koordynator i jednostka sterowania, jednostka
sterowania rejestruje swoje zadanie zamknięcia, a koordynator zostaje dołączony do modułu
funkcji.

**Okres rozpoznania.** Po starcie HA albo przeładowaniu VT strefy zgłaszają się jedna po
drugiej. Sterownik nie podejmuje nowych decyzji, dopóki każda strefa się nie zgłosi, najwyżej
przez 10 minut. Polecenie trzymane przed ponownym uruchomieniem jest zachowywane albo od razu
przywracane, jeśli nic tego nie zabrania; w przeciwnym razie najpierw kocioł jest oddawany. VT
może pokazywać termostat, którego nie uruchomił, jako „wyłączony”; nigdy nie jest to czytane
jako „brak zapotrzebowania”.

**Przeładowanie.** Zapisanie opcji przeładowuje integrację: jeśli sterowanie trzyma kocioł, jest
on oddawany i przejmowany ponownie (przekaźnik przechodzi w stan spoczynkowy i z powrotem).

**Zatrzymanie HA.** Oddanie kotła działa w zadaniu zamknięcia (`hass.async_add_shutdown_job`),
które HA uruchamia przed swoim zdarzeniem zatrzymania. Wszystkie zadania zamknięcia mają wspólny
limit 20 sekund, po którym HA anuluje te, które wciąż trwają; oddanie kotła jest zbudowane tak,
żeby się w nim zmieścić. Oddanie niepotwierdzone do tego czasu zostaje zaległe w magazynie
sterowania i jest ponawiane przy następnym starcie.

**Wyładowanie.** `async_unload_entry` najpierw zatrzymuje jednostkę sterowania (oddaje ona
kocioł), odłącza moduł funkcji, wyładowuje platformy, a na końcu zatrzymuje koordynator.

**Usunięcie.** Jeśli przy usuwaniu wpisu oddanie kotła wciąż jest zaległe, nie da się go już
ponowić: zgłoszenie w Naprawach, które przetrwa wpis, mówi użytkownikowi, żeby oddał kocioł
ręcznie.

## 6. Stan trwały

Sterowanie ma własny magazyn (`ControlStore` w `coordinator.py`), oddzielny od głównego magazynu
wpisu, który trzyma drobne dane monitora i podsumowania dni.

- **Co trzyma:** czy sterowanie jest włączone, ostatnie polecenie i to, czy wtyczka steruje,
  zatrzaski i ich przyczyny, zaległe oddanie kotła i dowody zwolnienia, wartości bazowe, z którymi porównują zabezpieczenia, obserwacje przekaźnika i aktywne alarmy
  sterowania.
- **Zapisywane od razu:** każda zmiana, której awaria nie może zgubić — znacznik sterowania,
  zatrzask, zaległe oddanie kotła — jest zapisywana natychmiast i atomowo. Wynik każdego zapisu
  jest odnotowywany; nieudany zapis tworzy zgłoszenie w Naprawach (pełny dysk albo pamięć tylko
  do odczytu).
- **Czytane ostrożnie** (`async_read_control_state`): gdy magazynu nie da się odczytać (brak go,
  jest uszkodzony albo ma inny kształt), a opcje zawierają część sterowania, oddanie kotła liczy
  się jako zaległe, a kocioł jako trzymany, więc wtyczka dla bezpieczeństwa oddaje kocioł.

**Dziennik** (`journal.py`, jego zasady w `core/journal.py`) też ma własny magazyn,
`<domain>.<entry_id>.journal`, więc główny magazyn wpisu i jego wersja zostają bez zmian. Trzyma
to, co wtyczka zdecydowała i dlaczego, dla strony „Kocioł”: starty i zatrzymania wtyczki,
przejęcie kotła przez sterowanie i jego oddanie, włączenie i wyłączenie wezwania ciepła,
zapisaną nastawę wody — jej pierwszą wartość, potem każdą zmianę o co najmniej 1 K od wartości
ostatnio zapisanej w dzienniku — potrzebę obiegu, która trzyma wodę, alarm podniesiony (albo z
podniesionym poziomem) i ustąpiony oraz każdy zapis ustawień, ze strony (z tym, co zmienił) albo
z ustawień (z sekcjami, które się zmieniły); każde z powodami, które podało sterowanie. Tylko
obserwuje — słucha stanu sterowania i odświeżeń monitora i niczego nie zmienia; jego błąd jest
logowany raz. Pierwsze spojrzenie po starcie zapisuje ponowne przejęcie kotła przez sterowanie
— po restarcie albo przeładowaniu, z wezwaniem ciepła, wodą i potrzebą obiegu — a zatrzymanie
zapisuje oddanie kotła, które sterowanie zrobiło tuż przed nim, chyba że oddanie jest jeszcze
należne (F18 z J4); alarmy już podniesione są punktem wyjścia startu; alarm, którego nie da się
teraz ocenić, zostaje taki, jaki był. Trzyma 14
dni i najwyżej 2000 wpisów, najstarsze wypadają pierwsze (tymczasowo, K4); zapisywany minutę po
zmianie, od razu przy wyładowaniu wpisu i przez Home Assistanta przy jego zatrzymaniu; magazyn,
którego nie da się odczytać, zaczyna pusty dziennik. Znika razem z innymi magazynami wpisu, gdy
wpis jest usuwany.

**Historia pokoi** (`rooms_store` w `coordinator.py`, jej format w `core/history.py`) też ma
własny magazyn, `<domain>.<entry_id>.rooms`: temperatura, nastawa, tryb, wezwanie, wypełnienie i
otwarcie zaworu każdego pokoju, tak jak wtyczka odczytała je przez `vtherm_api` w ostatnich 8
dniach. Każda seria to jeden wiersz tekstu — chwile w pełnych sekundach, każda po pierwszej jako
sekundy od poprzedniej; wartości do trzech miejsc po przecinku — bo Home Assistant zapisuje swoje
magazyny z wcięciami. Trzyma najwyżej 10 000 najnowszych próbek serii, więc migocząca wartość nie
powiększa pliku bez końca. Zapisywany pół godziny po zmianie (najwyżej około 48 zapisów na dobę)
i przy czystym zatrzymaniu; odczytywany przy starcie, dla pokoi skonfigurowanych teraz, nieznany
od ostatniego zapisu do następnego odczytu pokoi — awaria gubi to, co przyszło od zapisu. Serii,
której nie da się odczytać, nie bierze; magazyn bez chwili zapisu pomija. Nic do niego nie jest
zapisywane, zanim go odczytano. Znika razem z innymi magazynami wpisu, gdy wpis jest usuwany.

## 7. Testowanie

Trzy warstwy ([`docs/pl/development/plan.md`, „Test environment”](../development/plan.md#środowisko-testowe)):

1. **Testy rdzenia** (`tests/core/`) — zwykły pytest, bez HA, bez sieci.
2. **Testy integracyjne** — `pytest-homeassistant-custom-component`: HA działa wewnątrz procesu
   testów; bez instancji, bez sieci. Ciągła integracja (CI) pobiera też VT 10.6.5 z jego tagu,
   więc testy z prawdziwym VT działają przy każdej zmianie. Pobiera też SmartPI 0.4.0, tylko do
   wdrożenia na testowy HA: wtyczka nie czyta niczego ze SmartPI.
3. **Testowy HA** — osobny kontener (`devenv/`) z wtyczką, VT, SmartPI i symulatorem, w którym
   scenariusze odbiorcze są uruchamiane, zanim cokolwiek trafi do prawdziwego kotła.

**Symulator** (`sim/simulator.py`, z `sim/custom_components/boiler_sim`) modeluje kocioł,
pomieszczenia i pogodę. Scenariusz ustala instalację, pogodę, pobory ciepłej wody i zawory
stref, a w każdym okresie sterowania może wywołać sterownik; polecenia docierają do
symulowanego kotła tak jak przez bramkę. Sterowanie jest testowane tylko na symulatorze.

**Uruchamianie sprawdzeń**, tak jak opisuje [`CONTRIBUTING.md`](../../../CONTRIBUTING.md), każde
przez `scripts/env.sh`:

```sh
scripts/env.sh python -m pytest -q -p no:homeassistant --disable-socket --allow-unix-socket \
    tests/core
scripts/env.sh python -m pytest -q --ignore=tests/core
scripts/env.sh ruff check .
scripts/env.sh ruff format --check .
scripts/env.sh mypy
```

Strona „Kocioł”, w `frontend/`: `../scripts/env.sh npm test` i `../scripts/env.sh npm run build`
(najpierw sprawdzenie typów); zbudowane pliki trafiają do repozytorium.
`../scripts/env.sh npm run screenshots` rysuje zbudowaną stronę na przykładowych danych
(`frontend/preview/index.html`) w Chromium bez okna — jasny i ciemny motyw, komputer i telefon,
administrator i zwykły użytkownik — do `.tmp/screenshots/` i zgłasza błąd przy każdym błędzie na
stronie; `scripts/bootstrap_browser.sh` umieszcza to Chromium i potrzebne mu biblioteki systemowe
w `.tools/`.

