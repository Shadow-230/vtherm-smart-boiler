[English version](../../en/specification/water-interface.md)

# Dane Smart Boiler o wodzie dla algorytmów stref — specyfikacja integracji

Status: uzgodniony z właścicielem 2026-10-12; wymagania są zamknięte. Strona Smart Boiler jest
zbudowana (krok I9 w `docs/en/development/plans/plan-0.2.md`, `docs/en/development/plans/plan-0.2-i9.md`, 2026-10-12); test kontraktowy
(`tests/test_water_interface.py`) pilnuje każdej nazwy i wartości podanej poniżej. Rozszerzony
2026-10-14, na prośbę SmartPI i za zgodą właściciela, o to, czy kocioł jest wezwany do grzania
(§4, §4.3) — dodatek w ramach §8.

Część obowiązująca (sekcje 1–10) mówi, co Smart Boiler udostępnia, pod jakimi nazwami, z jakimi
wartościami, co czyta z algorytmu strefy i jaką usługę wywołuje. To, co odbiorca robi z danymi,
jest sprawą jego własnej specyfikacji; uzgodnienia z właścicielem dotyczące użycia przez SmartPI
są w Załączniku A, dla kontekstu.

## 1. Cel

Model pokoju w algorytmie strefy zakłada, że jednostka polecenia zawsze daje tyle samo ciepła.
Przy kotle ze sterowaniem pogodowym, mieszaczu, pracy palnika w cyklach albo c.w.u. z priorytetem
to nieprawda. Smart Boiler zna wodę, którą dostaje obieg każdej strefy; udostępnia ją, żeby
algorytm strefy mógł ją uwzględnić. Pierwszym odbiorcą jest SmartPI.

Strefa może też wołać, gdy kocioł wcale nie jest rozpalony: kryteria zapotrzebowania nie są
spełnione (woła za mało urządzeń lub stref, za mała moc), trwa opóźnienie włączenia VT albo
kocioł zgłasza własną usterkę. Decyduje o tym Smart Boiler, więc sam to podaje (`boiler_called`,
§4.3) — poza przerwami palnika, które śledzi `heat_available`.

## 2. Zasady

- **Opcjonalne.** Smart Boiler działa bez żadnego odbiorcy, a odbiorca bez Smart Boiler. Każda
  brakująca wartość znaczy „brak danych”, a odbiorca zachowuje się wtedy tak, jakby interfejsu nie
  było.
- **Jeden kierunek.** Smart Boiler udostępnia, jaka jest teraz woda. Odbiorca nigdy nie ustawia
  temperatury wody i o nią nie prosi: wody zwykle nie da się ustawić dla pojedynczej strefy, a jej
  wybór zostaje po stronie Smart Boiler (jego krzywa, obiegi i strefa krytyczna).
- **Jedno źródło.** Każdy czujnik po stronie kotła jest przypisany w Smart Boiler, który przekazuje
  dane dalej w każdym trybie sterowania, także w trybie tylko monitorowanie.
- **Jedno źródło ciepła na termostat VT.** VT prowadzi jedno sterowanie na strefę: ogrzewanie
  podłogowe i grzejniki to osobne termostaty VT, ewentualnie ze strefą nadrzędną nad obiema.
- **Bez numeru wersji.** Odbiorca sprawdza, co istnieje (właściwość, klucz, funkcję); zmiany tylko
  dodają; zmiana znaczenia dostaje nową nazwę, a stara zostaje na czas przejścia. Test kontraktowy
  w Smart Boiler pilnuje każdej nazwy, typu i dozwolonej wartości tej specyfikacji, więc nic się
  nie zmieni bez nieudanego sprawdzenia.

## 3. Gdzie są dane

### 3.1 Menedżer funkcji

Smart Boiler rejestruje w każdym termostacie VT menedżera funkcji VT o nazwie
`vtherm_smart_boiler`. Ma on pola z sekcji 4 jako właściwości tylko do odczytu. Odbiorca sięga do
niego przez `thermostat.get_feature_manager("vtherm_smart_boiler")` tam, gdzie VT ma tę metodę (VT
10.5.0.beta1 i nowsze). VT daje termostatowi jego menedżerów w chwili, gdy termostat startuje,
więc termostat, który wystartował, zanim Smart Boiler się zarejestrował, nie ma go aż do
następnego przeładowania VT.

### 3.2 Publiczne API

Gdy Smart Boiler działa, `hass.data["vtherm_smart_boiler_api"]` zawiera obiekt z nazwanymi
funkcjami; po zatrzymaniu Smart Boiler jest usuwany. Dziś ma jedną:

- `zone_water(entity_id: str) -> Mapping[str, Any] | None` — dla identyfikatora encji klimatu VT:
  mapa tylko do odczytu z polami z sekcji 4; `None`, gdy termostat nie jest strefą Smart Boiler
  albo jego danych nie da się odczytać.

Działa z każdą wersją VT, którą Smart Boiler obsługuje (10.2.0 i nowsze; przetestowana 10.5.1)
oraz przed przeładowaniem VT. Odbiorca niczego nie importuje ze Smart Boiler; sprawdza tylko, czy
istnieją klucz i funkcja. Późniejszy dodatek to nowa funkcja na tym samym obiekcie. Pozostałe
klucze Smart Boiler w `hass.data` są wewnętrzne i nie należą do tego interfejsu.

### 3.3 Atrybut w termostacie VT

Atrybut `smart_boiler` w każdej encji climate VT, którą obsługuje Smart Boiler, jest mapą:

| Klucz | Typ | Wartość | Publikowany |
|---|---|---|---|
| `heat_available` | `bool \| None` | jak w sekcji 4 | przy każdej zmianie |
| `supply_temperature` | `int \| None`, °C | wartość z sekcji 4 zaokrąglona do 1 °C | przy zmianie o co najmniej 1 K lub przy przejściu do `None` albo z `None` |

Tylko do wyświetlania: VT zapisuje atrybuty swoich termostatów, więc atrybut zmienia się rzadko.
Odbiorca czyta wartości na żywo (3.1, 3.2).

### 3.4 Co Smart Boiler czyta od odbiorcy

Smart Boiler czyta, dla każdego termostatu VT, klucz, który odbiorca zapisuje w `specific_states`
termostatu (VT nie zapisuje tej części swoich atrybutów). Jego obecność znaczy „algorytm tego
termostatu używa danych o wodzie”. Nazwę klucza określa specyfikacja odbiorcy; dla SmartPI
propozycja to `water_factor`. Smart Boiler czyta go tak, jak czyta inne dane strefy z VT.

### 3.5 Jaką usługę wywołuje Smart Boiler

Smart Boiler wstrzymuje i wznawia naukę SmartPI przez `vtherm_smartpi.set_smartpi_learning`
(`entity_id`, `learning_enabled`), w warunkach, które sam określa:

| Warunek | Wstrzymane |
|---|---|
| Działa c.w.u. z priorytetem (zasobnik ładowany przez zawór trójdrogowy, kocioł dwufunkcyjny) | strefy wołające o ciepło (zawór otwarty); strefa, która nie woła, uczy się dalej, jak stygnie |
| Usterka samego kotła, przy której sterowanie wyłącza grzanie | strefy wołające o ciepło |
| Duże wahanie temperatury wody, które powoduje wtyczka | tylko termostaty bez klucza z 3.4: u termostatu z kluczem dane o wodzie tłumaczą to wahanie |

Przy wznawianiu odczyt zwrotny flagi nauki i limit jednej godziny działają jak dotychczas
(`docs/pl/specification/scope.md` §5).

## 4. Pola

Dla każdego termostatu VT, który jest strefą Smart Boiler.

| Pole | Typ, jednostka | Wartości | `None`, gdy | Cel |
|---|---|---|---|---|
| `supply_temperature` | `float`, °C | woda docierająca do obiegu tego termostatu, tak jak zmierzona: bez zaokrąglania i bez uśredniania; od −20 do 110 °C (odczyt spoza tego zakresu jest nieznany) | nieznana; powód podaje `supply_reason` | jak ciepła jest woda w odbiornikach ciepła strefy |
| `supply_reason` | `str` | jedna z 4.1 | `supply_temperature` jest znana | dlaczego woda nie jest znana i czy trwale |
| `supply_measured_at` | `datetime`, UTC | kiedy wykonano odczyt, na którym opiera się wartość | `supply_temperature` to `None` | tylko informacja: źródło, które zgłasza tylko przy zmianie, zachowuje stary czas, choć jego wartość jest prawidłowa (sekcja 6) |
| `heat_available` | `bool` | `True`: płomień pali się (tam, gdzie przypisano sygnał płomienia), a temperatura zasilania jest o więcej niż 2 K wyższa od powrotu — o więcej niż 3 K wyższa od temperatury pokoju, gdy powrót nie jest znany; po ustawieniu `True` zostaje tak, dopóki różnica nie spadnie do 1 K i 2 K (histereza). `False`: płomień nie pali się, c.w.u. z priorytetem zabiera ciepło albo zasilanie nie jest wyższe od powrotu lub pokoju o tyle | nie da się tego ustalić | czy ciepło dociera teraz do strefy — podąża za palnikiem, więc zmienia się przy każdym cyklu palnika |
| `heat_reason` | `str` | jedna z 4.2 | `heat_available` to `True` | dlaczego ciepło nie dociera do strefy albo dlaczego nie da się tego ustalić |
| `boiler_called` | `bool` | `True`: Smart Boiler prosi teraz kocioł o centralne ogrzewanie (c.o.), wraz z ochroną przed mrozem. `False`: nie prosi, gdy steruje kotłem | Smart Boiler teraz nie steruje kotłem albo jeszcze nie może tego ustalić | czy kocioł jest proszony o ciepło, niezależnie od włączeń i wyłączeń samego palnika |
| `call_reason` | `str` | jedna z 4.3 | `boiler_called` to `True` | dlaczego kocioł nie jest wezwany albo dlaczego nie da się tego ustalić |
| `demand_count` | `int` | urządzenia — albo strefy, zależnie od `count_by` — które teraz wołają | żadna strefa nie jest znana | diagnostyka: zapotrzebowanie wobec progu |
| `count_threshold` | `int` | liczba, która uruchamia kocioł | kryterium liczby jest wyłączone (0) | diagnostyka |
| `count_by` | `str` | `devices` (głowice, zawory i przełączniki VT, tak jak liczy je centralny kocioł VT) albo `zones` | kryterium liczby jest wyłączone | diagnostyka |
| `demand_power_kw` | `float`, kW | moc średnia stref z ich cykli, zsumowana, tak jak pokazuje ją centralny kocioł VT; liczy się do progu tylko wtedy, gdy zawór wołającej strefy jest otwarty albo jej urządzenie włączone | żadna strefa nie podaje mocy | diagnostyka |
| `power_threshold_kw` | `float`, kW | moc, która uruchamia kocioł | kryterium mocy nie jest ustawione | diagnostyka |
| `demand_opening` | `float`, od 0 do 1 | największe otwarcie wśród wołających stref — otwarcie zaworu, a w przeciwnym razie cykl pracy strefy | żadna wołająca strefa go nie podaje | diagnostyka |
| `opening_threshold` | `float`, od 0 do 1 | otwarcie, które uruchamia kocioł | kryterium otwarcia nie jest ustawione | diagnostyka |

`boiler_called`, `call_reason` i pola zapotrzebowania dotyczą całej instalacji: są takie same dla
każdej jej strefy. `True` znaczy, że Smart Boiler poleca grzać, a nie dowód, że kocioł słucha
(zignorowany zapis lub niepotwierdzony przekaźnik ma własny alarm); przerwa palnika lub c.w.u.
z priorytetem zostają w `heat_available` / `heat_reason`.

Która woda jest „wodą docierającą do obiegu tego termostatu”:

- własny czujnik zasilania obiegu, jeśli jest przypisany, a jego odczyt jest świeży;
- w przeciwnym razie, dla obiegu zasilanego prosto z kotła, temperatura zasilania kotła;
- dla obiegu biernego za stałym zaworem: niższa z wartości — temperatura zasilania kotła i
  zadeklarowana temperatura zaworu;
- dla obiegu mieszanego (własny mieszacz, inna automatyka albo przez kocioł) bez własnego
  czujnika: nieznana (`circuit_not_measured`).

### 4.1 `supply_reason`

| Wartość | Znaczenie | Trwały? |
|---|---|---|
| `not_mapped` | nie przypisano czujnika wody dla tego obiegu: ani temperatury zasilania kotła, ani czujnika obiegu | trwały — do zmiany konfiguracji |
| `circuit_not_measured` | obieg mieszany bez własnego czujnika: temperatura zasilania kotła nic o nim nie mówi | trwały |
| `several_circuits` | urządzenia termostatu są w więcej niż jednym obiegu, a ich wody się różnią albo jedna jest nieznana (rozwiązanie zastępcze: sekcja 2 oczekuje jednego źródła na termostat); obiegi o tej samej wodzie podają ją | trwały |
| `flow_unknown` | czujnik jest przypisany, ale teraz nie daje nic użytecznego: jest niedostępny, nieznany, nie jest liczbą albo wychodzi poza zakres od −20 do 110 °C | chwilowy |
| `flow_stale` | ostatni odczyt czujnika jest starszy niż jego limit wieku (sekcja 6) | chwilowy |

### 4.2 `heat_reason`

| Wartość | Znaczenie |
|---|---|
| `dhw_active` | c.w.u. z priorytetem zabiera ciepło kotła; nigdy w kotle bez c.w.u. ani bez priorytetu |
| `flame_off` | płomień nie pali się |
| `flame_unknown` | przypisany sygnał płomienia jest nieznany lub nieświeży |
| `flow_near_return` | temperatura zasilania nie jest wyraźnie wyższa od powrotu |
| `flow_near_room` | brak znanego powrotu: temperatura zasilania nie jest wyraźnie wyższa od temperatury pokoju |
| `flow_unknown`, `flow_stale`, `circuit_not_measured` | woda nie jest teraz znana — jak w 4.1 |
| `not_mapped` | brak czujnika wody dla tego obiegu — jak w 4.1 |
| `room_unknown` | nie jest znany ani powrót, ani temperatura pokoju, z którymi można by porównać |

### 4.3 `call_reason`

| Wartość | Znaczenie | `boiler_called` |
|---|---|---|
| `below_threshold` | strefy wołają, ale kryteria zapotrzebowania (liczba, moc, otwarcie) nie są spełnione | `False` |
| `no_demand` | nic nie woła — ani żadna strefa, ani obieg sterowany przez inną automatykę | `False` |
| `activation_delay` | kryteria są spełnione; start czeka na opóźnienie włączenia VT | `False` |
| `boiler_fault` | kocioł zgłasza własną usterkę; sterowanie utrzymuje grzanie wyłączone | `False` |
| `not_controlling` | Smart Boiler teraz nie steruje kotłem: sterowanie wyłączone, niedozwolone, oddane, tylko monitorowanie | `None` |
| `waiting_data` | Smart Boiler steruje, ale jeszcze nie może tego ustalić: dane kotła nieświeże, odczyt zwrotny nieznany, okres rozpoznania po starcie trzyma „wyłączone”, wszystkie strefy nieznane | `None` |

Gdy pasuje kilka: najpierw `boiler_fault`, potem `activation_delay`, potem `below_threshold`,
potem `no_demand`. Grzanie, ochrona przed mrozem i nastawa awaryjna (grzanie bez temperatury
zewnętrznej) liczą się jako wezwanie do grzania, tak samo jak polecenie grzania, które trzyma okres
rozpoznania. Ścieżka włącz/wyłącz (przekaźnik) ma te same stany.

## 5. Gdy brakuje wartości

### 5.1 Według tego, co jest przypisane (obowiązujące)

W każdym wierszu `heat_available` jest `False` z `dhw_active`, gdy działa c.w.u. z priorytetem, oraz
z `flame_off`, gdy przypisany sygnał płomienia mówi, że płomień nie pali się (sekcja 4); tabela
pokazuje resztę.

| Sytuacja | `supply_temperature` | `heat_available` |
|---|---|---|
| Brak czujnika wody dla obiegu (brak temperatury zasilania kotła i brak czujnika obiegu) | `None`, `not_mapped` | `None`, `not_mapped` |
| Czujnik przypisany, teraz niedostępny albo z nierealnym odczytem | `None`, `flow_unknown` | `None`, `flow_unknown` |
| Czujnik przypisany, odczyt starszy niż limit wieku | `None`, `flow_stale` | `None`, `flow_stale` |
| Obieg mieszany bez własnego czujnika | `None`, `circuit_not_measured` | `None`, `circuit_not_measured` |
| Nie przypisano sygnału płomienia | jak wyżej | oceniane tylko po wodzie (bez powodów `flame_*`) |
| Sygnał płomienia przypisany, ale nieznany lub nieświeży | jak wyżej | `None`, `flame_unknown` |
| Nie przypisano powrotu (albo obieg mieszany, którego woda nie wraca do kotła) | jak wyżej | oceniane względem pokoju |
| Brak powrotu i temperatura pokoju nieznana | jak wyżej | `None`, `room_unknown` |
| Sygnał c.w.u. nieprzypisany albo nieznany | jak wyżej | niezablokowane: tylko znany pobór daje `dhw_active` |
| Kocioł bez c.w.u. albo c.w.u. bez priorytetu | jak wyżej | nigdy `dhw_active` |
| Termostat nie jest strefą Smart Boiler (w żadnym obiegu) | brak danych: `zone_water` daje `None`, właściwości menedżera `None` | brak danych |
| Smart Boiler nie działa, startuje albo się przeładowuje | brak danych: brak klucza API albo `None` | brak danych |

Wezwanie (§4.3) nie zależy od tego, co jest przypisane: podąża za sterowaniem. Bez sterowania
(tylko monitorowanie) albo gdy sterowanie się zatrzymuje, `boiler_called` to `None` z
`not_controlling`, a pola zapotrzebowania to `None`.

### 5.2 Według instalacji (przykłady, nie obowiązujące)

To, co dostaje odbiorca, wynika z tego, co jest przypisane (5.1), a nie z rodzaju połączenia.
Zwykle:

| Instalacja | Co zwykle daje |
|---|---|
| OpenTherm Gateway, ESPHome OpenTherm, EMS-ESP | temperaturę zasilania kotła, powrót, płomień, aktywne c.w.u.: każde pole |
| Kocioł on/off na przekaźniku | nic, chyba że czujnik na rurze jest przypisany jako zasilanie; sygnał płomienia lub c.w.u. tylko tam, gdzie kocioł go udostępnia. Stan samego przekaźnika to nie płomień |
| Moduł Wi-Fi kotła, integracja producenta | to, co ta integracja pokazuje, często odpytywane co jedną do kilku minut i zaokrąglone; automatyczne limity wieku podążają za jej rytmem |
| Inna integracja tylko do odczytu | to, co pokazuje |
| Tylko monitorowanie (każde połączenie) | to samo co ze sterowaniem: dane nie zależą od sterowania |
| Obieg z własnym mieszaczem i czujnikiem za nim | woda z tego czujnika |

## 6. Świeżość i odświeżanie

- Smart Boiler ocenia świeżość każdego sygnału własnym limitem wieku (domyślnie automatycznym:
  żadnego, dopóki źródło dwa razy nie powtórzy niezmienionej wartości, potem pięciokrotność jego
  rytmu, od 10 do 30 min; do ustawienia dla każdego sygnału). Po jego przekroczeniu: `flow_stale`.
- Odbiorca ufa `None` i jego powodowi. Sam nie stosuje żadnego limitu wieku do
  `supply_measured_at`: źródła MQTT i ESPHome zgłaszają tylko przy zmianie i zachowują stary czas,
  choć ich wartość jest prawidłowa.
- Wartości są przeliczane przy każdej aktualizacji Smart Boiler — przy każdej zmianie czytanego
  sygnału i co najmniej co 30 s — i czytane na żywo; bez ograniczania częstości. Wezwanie i
  zapotrzebowanie (§4.3) podążają za krokiem sterowania, co 10 s, i są czytane na żywo.

## 7. Jednostki i formaty

- Temperatury w °C, niezależnie od jednostki czujnika (Smart Boiler przelicza; czujnik bez
  jednostki jest traktowany jako °C), także w Home Assistant ustawionym na °F.
- Czasy jako `datetime` UTC ze strefą czasową.
- Moc w kW; otwarcia jako ułamki od 0 do 1.
- Powody jako ciągi znaków z 4.1, 4.2 i 4.3.

## 8. Zmiany

- Tylko dodatki: nowe pole, nowa wartość powodu, nowa funkcja API.
- Odbiorca musi traktować nieznaną wartość powodu jako „brak danych” na tę chwilę.
- Zmiana znaczenia dostaje nową nazwę; stara nazwa zostaje, dopóki odbiorcy się nie przeniosą.
- Test kontraktowy (sekcja 2) zawodzi przy każdej zmianie nazwy, typu lub dozwolonej wartości; to
  niepowodzenie przypomina, żeby zaktualizować tę specyfikację i powiadomić odbiorców.

## 9. Czego nie ma w interfejsie

Odbiorca nie publikuje żadnej temperatury wody, której by potrzebował, a Smart Boiler żadnej nie
przyjmuje: wymagałoby to dużej przebudowy, a wody zwykle nie da się ustawić dla pojedynczej
strefy. Smart Boiler czyta od odbiorcy tylko klucz z 3.4.

## 10. Zbudowane

Strona Smart Boiler: krok I9 (2026-10-12) — pola (z powodami `not_mapped` i `several_circuits`),
właściwości menedżera (3.1), API (3.2), atrybut (3.3), odczyt klucza odbiorcy (3.4), warunki
wstrzymania (3.5) i test kontraktowy (sekcja 2). 2026-10-14: wezwanie kotła i zapotrzebowanie
wobec progów (§4, §4.3), na prośbę SmartPI (SmartPI:
`specs/2026-10-14-smart-boiler-boiler-call.md`), z powodem `below_threshold` i poprawionym
przyporządkowaniem uzgodnionym wtedy; bez dodania wstrzymania nauki z tego powodu (3.5 bez zmian).
Strona odbiorcy należy do odbiorcy: dla SmartPI — Załącznik A.

## Załącznik A — użycie przez SmartPI (uzgodnione 2026-10-12; należy do własnej specyfikacji SmartPI)

Zostaje tu, dopóki nie przejmie tego specyfikacja SmartPI; informacyjnie dla Smart Boiler.

1. **Typ ogrzewania.** Każdy termostat SmartPI ma typ ogrzewania: grzejnik wodny, podłoga wodna,
   mata elektryczna, elektryczne szybkie. Typ wodny daje wykładnik odbiornika ciepła `n` i wodę
   odniesienia `T_ref`; wartości tymczasowe: grzejnik 1.3 i 60 °C, podłoga 1.1 i 45 °C. Typy
   elektryczne pomijają dane o wodzie.
2. **Współczynnik mocy odbiornika ciepła.** `φ = (max(T_supply − T_room, 0) / (T_ref − 20)) ** n`,
   przy temperaturze zasilania uśrednionej z około 15 minut, ponieważ praca palnika w cyklach
   sprawia, że wartość surowa skacze.
3. **Użycie.** Zapotrzebowanie jako moc przy wodzie odniesienia; polecenie dla odbiornika ciepła to
   ta moc podzielona przez `φ`, przed krzywą zaworu; nauka używa polecenia × `φ`; model strefy i
   jego hamulec używają tego samego współczynnika.
4. **Nauka stygnięcia trwa zawsze.** Żadnej własnej blokady nauki w SmartPI: wejście polecenie ×
   `φ` równe 0 (palnik wyłączony, c.w.u., zawór zamknięty) uczy strat. Wstrzymania pochodzą tylko
   ze Smart Boiler (3.5).
5. **C.w.u. z priorytetem.** Gdy `heat_reason` to `dhw_active`, `φ = 0` dla obiegu termostatu:
   temperatura zasilania kotła pokazuje wtedy wodę grzejącą zasobnik. Całka nie rośnie, a polecenie
   jest trzymane.
6. **Brak ciepła z innych powodów.** Przy `φ` bliskim 0 całka nie rośnie (anti-windup).
7. **Brakujące dane.** Powód chwilowy (4.1): długoterminowa średnia współczynnika, żeby nauczony
   model zachował swoje jednostki. Powód trwały albo brak danych od startu: `φ = 1`, jak bez
   interfejsu.
8. **Dane pojawiające się lub znikające na stałe** (pojawia się lub znika powód trwały): jednostki
   nauczonego modelu się zmieniają; SmartPI przeskalowuje nauczoną moc średnim współczynnikiem albo
   proponuje reset swojego modelu.
9. **Klucz z 3.4.** SmartPI zapisuje `water_factor` (współczynnik, który stosuje, albo `None`) w
   `specific_states` dla każdego termostatu typu wodnego, który używa tych danych.
10. **Wezwanie kotła** (prośba z 2026-10-14). Gdy `boiler_called` to `False`, a polecenie strefy
    jest większe niż 0, oraz przez czas ustalania po każdej zmianie, SmartPI wstrzymuje naukę
    modelu strefy i czasów martwych i zamraża korektę sprzężenia w przód; jego regulacja się nie
    zmienia. `None`: nieznane ze Smart Boiler — SmartPI czyta wtedy centralny kocioł VT, tam gdzie
    VT liczy dla niego termostat, a w przeciwnym razie zachowuje się jak dotąd. Smart Boiler nie
    dodaje wstrzymania dla tego przypadku.
