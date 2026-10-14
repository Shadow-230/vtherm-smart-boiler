[English version](../../en/development/plan.md)

# Plan rozwoju

Zakres: `docs/pl/specification/scope.md`. Własna ocena autora dotycząca jego instalacji: `home-assessment.md`
(prywatna) — nigdy źródło wartości dla kodu, ustawień domyślnych, testów ani dokumentacji.

## Podejście — jedno jądro, trzy źródła danych

Czysta logika w `core/` pracuje na jednym formacie szeregów czasowych (płomień, zasilanie, powrót, modulacja, c.w.u.,
pogoda, migawki prognozy, obiegi, strefy). Ten sam kod dostaje dane z:

1. wyeksportowanej historii — odtwarzanie w testach,
2. symulatora — testowanie praw sterowania,
3. żywego HA — przez warstwę integracji.

Ocena, monitor i sterowanie to jedna baza kodu, a nie trzy projekty. Model obiegów
(kocioł → obiegi → strefy) jest częścią jądra od 0.1; w 0.2 jedna krzywa obsługuje jeden zapisywany
obieg, a krzywe dla poszczególnych obiegów przychodzą z CH2 (`docs/pl/specification/scope.md` §5).

## Ścieżki

| Ścieżka | Zawartość | Działa na |
|---|---|---|
| A. Jądro | wykrywanie cykli palenia, metryki (starty, palenia, kondensacja, gaz, stopniodni), wykrywanie c.w.u., model obiegów, model parametrów ze źródłem i pewnością, oszacowanie budynku, prawa sterowania i nauki | Python 3.14 |
| B. Dane | wspólny format, importer historii, magazyn migawek prognozy, werdykt oceny z danych na żywo i wyeksportowanych | Python 3.14 |
| C. Symulator | kocioł (minimalna moc, histereza, objętość wody), dom jako jedna masa, jedna niemieszana pętla (`sim/custom_components/boiler_sim/profiles.py`), strefy; ogólne profile dla klasy kotła; obiegi mieszane i sterowane osobno od 0.3 | Python 3.14 |
| D. Integracja z HA | własny szkielet (`vtherm_hysteresis` jako wzór), config flow z poziomami prosty/zaawansowany, encje, tłumaczenia, rejestracja w `vtherm_api`, transport przez encje (odczyt; zapis od 0.2), wbudowana obsługa OTGW, wstrzymania nauki | środowisko testowe |
| E. Wydanie | dokumentacja, licencja, HACS, zgłoszenie na listę wtyczek VT | — |

## Środowisko testowe

Trzy warstwy:

1. Testy `core/` — zwykły pytest, bez Home Assistanta.
2. Testy integracji — `pytest-homeassistant-custom-component`: Home Assistant działa wewnątrz procesu
   testowego; bez instancji, bez sieci.
3. Testowy HA — dedykowany LXC w Proxmox z oficjalnym kontenerem Home Assistanta w przypiętej wersji,
   przygotowany przez użytkownika (`devenv/`). Wtyczka, VT i SmartPI pochodzą z tego projektu;
   kocioł, pokoje i pogoda pochodzą z naszego własnego symulatora fizyki, komponentu tylko do testów
   (`sim/custom_components/boiler_sim`), z prawdziwymi termostatami VT sterującymi zaworami jego stref.
   Testowy LXC nie sięga do żadnego urządzenia w sieci domowej — w tym do produkcyjnego HA, jego brokera MQTT
   i prawdziwej bramki: blokuje to zapora sieciowa (firewall) na hoście Proxmox, niedostępna z wnętrza LXC
   (2026-10-08). Claude łączy się tylko z tą instancją (`CLAUDE.md`).

Sterowanie jest testowane tylko na symulatorze: scenariusze akceptacyjne działają najpierw w jednym procesie,
potem w testowym HA. Szczegóły: `docs/en/development/plans/plan-0.2.md`, faza J. CI pobiera VT 10.5.1 i SmartPI 0.4.0
z ich tagów na serwerach GitHub, więc testy z prawdziwym VT działają przy każdej zmianie; nic nie jest pobierane
lokalnie (`docs/en/development/plans/plan-0.2.2.md`, decyzja 14).

## Wydania

0.1 jest publikowane razem z 0.2 — to pierwsze wydanie, jego wersję postanowi się w K4 i K5 (tymczasowo
0.2.3b1, `docs/en/development/plans/plan-0.2.2.md` decyzja 16), ze sterowaniem, testowane jako całość; 0.2.1, 0.2.2 i
0.2.3 poprawiają 0.2 po jego przeglądach (`docs/en/development/plans/plan-0.2.1.md`, `docs/en/development/plans/plan-0.2.2.md`,
`docs/en/development/plans/plan-0.2.3.md`).
Potem wydawać wcześnie i małymi krokami: każde wydanie zbiera dane dla następnego.

| Wydanie | Zawartość | Gotowe, gdy | Termin |
|---|---|---|---|
| Krok 0 | Python 3.14 i narzędzia wewnątrz projektu (`.tools/`, `.venv/`, `.tmp/`, `scripts/env.sh`), układ repozytorium; lokalny git (od 2026-09-24) | — | teraz |
| 0.1 Monitor (tylko odczyt) — gotowe 2026-09-24, publikowane z 0.2 | jądro: wspólny format, model obiegów, model parametrów, oszacowanie obciążenia budynku, wykrywanie cykli palenia i c.w.u., metryki; config flow (prosty / zaawansowany) z polami encji — użytkownik wskazuje, która encja dostarcza każdy sygnał, jak w VT; tylko odczyt; możliwości wynikają z wypełnionych pól; dane stref przez VT; encje: metryki, łączność, dla każdej strefy dostępne c.w.u. i współczynnik mocy odbiornika ciepła, strefa krytyczna, pokój odniesienia (`docs/pl/specification/scope.md` §5), werdykt; kontrola sygnałów; obce ciepło (pokój odniesienia, encje dla stref i obce ciepło usunięte w I8); alarmy, wczesne ostrzeżenie, raport wyjaśniający zmiany; FC0; pobieranie diagnostyki HA; tłumaczenia EN + PL; minimalny symulator, importer historii, testy integracji | wszystkie testy i `ruff` przechodzą ✅ | wrzesień |
| 0.2 Podstawa sterowania — pierwsze wydanie (jego wersję postanowi się w K4 i K5; tymczasowo 0.2.3b1) | monitor z 0.1 plus sterowanie: na życzenie użytkownika, oznaczone jako eksperymentalne, dostępne od pierwszego dnia — żaden okres monitorowania go nie wstrzymuje (decyzja użytkownika z 2026-10-08), werdykt po 7 dniach danych; każda opcja z ostrożną wartością domyślną i opisem ryzyka; zastępuje centralny kocioł VT: grzanie włącza się i wyłącza od razu zgodnie ze strefami VT, centralne tryby VT przez zapotrzebowanie stref, nic liczonego ani odmierzanego nie wstrzymuje grzania wbrew VT; zapotrzebowanie kotła ze stref wołających, z mocy całkowitej albo z otwarcia zaworów; stała krzywa (wpisana; jedna dla zapisywanego obiegu, osobna dla każdego obiegu z CH2); najniższa i najwyższa temperatura wody, ochrona przed mrozem (jeden z wymienionych wyjątków zasady 12, z okresami rozpoznania i karencji oraz opóźnieniem włączenia VT); korekta komfortu w twardych granicach (domyślnie włączona przy pełnym sterowaniu od G11); zapisy każdą drogą: encja wskazana przez użytkownika, wbudowany OTGW przez `opentherm_gw` albo jego firmware przez MQTT, albo przekaźnik dla kotła włącz/wyłącz (klasa 3, 0.2.2); sterowanie tylko ze znanym oddaniem sterowania; nastawa powtarzana co 30 s tam, gdzie nadpisanie wygasa (wbudowany OTGW, wskazana encja zadeklarowana jako wygasająca); wartość, którą urządzenie trzyma (zadeklarowana jako trzymana), wysyłana przy zmianie, po powrocie urządzenia i co 5 min; nic nie jest zapisywane do pamięci trwałej kotła (cel zadeklarowany jako zapisywany na stałe albo o nieznanym typie zapisu zostawia sterowanie wyłączone); żadnych zapisów bez świeżych danych; odczyt zwrotny każdego zapisu; bezpieczne oddanie sterowania przy każdym wyjściu, ponawiane do potwierdzenia; czyste przeładowanie; bezpieczna nastawa awaryjna przy awarii czujnika zewnętrznego; bit włączenia c.w.u. zostawiony taki, jaki był; strażnicy zapisu (strażnik tempa zapisu przed pętlą wymykającą się spod kontroli; zmiany widoczne w odczycie zwrotnym oceniane przez cztery klasy — zgubione polecenie, ignorowane od początku, obcięte, inny sterownik; oddanie sterowania nigdy niewstrzymywane); reakcje alarmów jak w decyzji 7; reguła braku danych; w trybie nastawy zasilania sterowanie tylko ze źródłem potwierdzonej nastawy; jeden obieg zasilany prosto z kotła, z obiegami za stałym zaworem albo sterowanymi przez inną automatykę obok niego (CH2 później); ostrzeżenie o niskim przepływie; lato i zima z VT; rampa temperatury wody; wstrzymania nauki (`docs/pl/specification/scope.md` §5); topologia bramki (tryb i to, co jest podłączone do zacisków termostatu) decyduje, czy sterowanie jest dozwolone i do czego prowadzi oddanie sterowania; pole wyboru „własny sterownik pokojowy”; sterowanie w trybie nastawy zasilania (tryb podobny do termostatu w 0.3); menedżer funkcji VT pokazujący, czy ciepło jest dostępne (jedna wartość od I8); korekta komfortu domyślnie włączona przy pełnym sterowaniu, w granicach limitu użytkownika, z ostrzeżeniem, gdy krzywa jest za niska dla pokoju; temperatura pokojowa krzywej Auto (nastawa najcieplejszej strefy) albo Ręczna; długie palenie bez ocieplenia zgłaszane użytkownikowi (krok G11, `docs/en/development/plans/plan-0.2-g11.md`); obiegi tak, jak widzi je kocioł — każdy ze swoimi strefami, swoją najwyższą temperaturą wody oraz własną krzywą i korektą, obieg sterowany przez inną automatykę prosi o ciepło i ustawia dolną granicę temperatury wody, woda kotła obsługuje najbardziej wymagający obieg, który prosi o ciepło; opcje jako pojedyncze formularze bez podmenu, każde pole widoczne tylko tam, gdzie może działać, teksty krótkie i proste (krok I8, `docs/en/development/plans/plan-0.2-i8.md`, który usuwa też to, co należy do pokoi i stref: pokój odniesienia, obsługę okien, obce ciepło, encje dla stref); pliki wydania (`LICENSE`, README, `hacs.json`, akcja HACS, Hassfest); **środowisko testowe**: testowy HA w swoim LXC, własny symulator fizyki, scenariusze akceptacyjne (najpierw w jednym procesie, potem w testowym HA) | każdy scenariusz akceptacyjny przechodzi w testowym HA; instalacja autora monitoruje przez 7 dni, potem pracuje ze sterowaniem bez błędów; użytkownik przejrzał 0.1 i 0.2; opublikowane | druga połowa listopada |
| 0.3 Przeciwdziałanie częstym startom i tryb podobny do termostatu | sterowanie cyklem pracy — do rozstrzygnięcia w świetle zasady 12 (`docs/en/development/plans/plan-0.2.2.md` decyzja 13); ograniczenie modulacji, planowanie z prognozą (FC2); tryb podobny do termostatu — kocioł dostaje temperaturę i nastawę, albo różnicę, strefy proszącej o ciepło, której brakuje najwięcej, i sam ustala swoją wodę (ID 24 / 16 albo wskazane encje; `docs/en/development/plans/plan-0.2-i8.md` G); termostat ścienny jako rezerwa na awarię Home Assistanta — jedna droga, od VT do termostatu, domyślnie wyłączona (najwcześniej; `docs/en/development/plans/plan-0.2-i8.md` I1); tryb „zastosuj” dla najniższej temperatury wody; grzejniki i podłogówka za zaworem mieszającym (jeden zapisywany obieg plus bierne obiegi stałe) | mniej startów, ten sam komfort | grudzień–styczeń |
| 0.4 Nauka i strojenie | nauka po stronie wody, podpowiedzi doradcy, pasmo strojenia, sezonowe dostrojenie — każde dla obiegu, także woda, której potrzebuje obieg sterowany przez inną automatykę, gdy nie podano wartości | niższy powrót, mniej gazu na stopniodzień | styczeń–luty |
| 0.5 Prognoza | wyprzedzanie dla wolnych odbiorników ciepła (FC3), czas wyprzedzenia z zapisanych prognoz | lepszy komfort przy zmianach pogody bez dodatkowego gazu | późna zima albo następny sezon |
| Później | ładowanie c.w.u.; domyślna lista HACS i zgłoszenie na listę wtyczek VT; wbudowana obsługa kolejnych urządzeń; gaz szacowany z mocy kotła tam, gdzie nie podano zużycia gazu; polecenia przekaźnika poza włącznikiem i encją termostatu kotła (swobodne akcje VT), jeśli ktoś o to poprosi | — | od wiosny 2027 |

Terminy są celami, nie zobowiązaniami. Symulator pozostaje minimalny: wystarczy, by przyjąć 0.2, zanim trafi
do prawdziwego kotła.
Żadne wydanie nie trafia do prawdziwego kotła, zanim przejdzie w środowisku testowym. Testy automatyczne działają
w jednym procesie; Claude łączy się tylko z testowym HA.

## Przed 0.2

Kontrole przed kodem sterowania: `docs/en/development/plans/plan-0.2.md`, faza F (zrobiona 2026-09-24; odpowiedzi w `docs/pl/specification/scope.md` §11).

## Przed 0.3

- Punkt decyzyjny po 2–4 tygodniach danych grzewczych z 0.2: pełny zakres, odchudzony zakres albo
  zatrzymanie po 0.2.

## Plany wydań

- 0.1 — `docs/en/development/plans/plan-0.1.md`
- 0.2 — `docs/en/development/plans/plan-0.2.md`
- 0.2.1 — `docs/en/development/plans/plan-0.2.1.md`: poprawki po przeglądzie z 2026-09-24 i decyzje
  użytkownika z 2026-09-25, przed testowym HA
- 0.2.2 — `docs/en/development/plans/plan-0.2.2.md` (szczegóły: `docs/en/development/plans/plan-0.2.2-details.md`): poprawki
  po przeglądzie z 2026-09-26 i decyzje użytkownika z 2026-09-26/27; pierwsza wersja do
  opublikowania (tymczasowo)
- 0.2, krok I6 — `docs/en/development/plans/plan-0.2-i6.md`: konfiguracja zaczyna się od tego, jak jest podłączony kocioł,
  trybu sterowania, źródła ciepła i typu kotła (decyzje użytkownika z 2026-10-08 i
  2026-10-09)
- 0.2, krok G11 — `docs/en/development/plans/plan-0.2-g11.md`: korekta komfortu domyślnie włączona, temperatura pokojowa
  krzywej Auto albo Ręczna, reguła długiego palenia i strażnik okna (decyzje użytkownika
  z 2026-10-10)
- 0.2, krok I7 — `docs/en/development/plans/plan-0.2-i7.md`: konfiguracja i opcje przechodzą przez menu sekcji,
  zapisywane raz na końcu, jak w Versatile Thermostat (decyzje użytkownika z
  2026-10-10)
- 0.2, krok I8 — `docs/en/development/plans/plan-0.2-i8.md`: wtyczka kotła, jeden formularz na pozycję menu — to, co należy
  do pokoi i stref, odpada, obiegi i łańcuch sterowania stają się pozycjami menu, teksty krótkie i
  proste (decyzje użytkownika z 2026-10-10)
