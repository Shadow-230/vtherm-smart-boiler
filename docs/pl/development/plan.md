[English version](../../en/development/plan.md)

# Plan rozwoju

Status: aktualny.

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
| D. Integracja z HA | własny szkielet (`vtherm_hysteresis` jako wzór), config flow z poziomami prosty/zaawansowany, encje, tłumaczenia, rejestracja w `vtherm_api`, transport przez encje (odczyt; zapis od 0.2), wbudowana obsługa OTGW | środowisko testowe |
| E. Wydanie | dokumentacja, licencja, HACS (od Home Assistanta 2026.11 Marketplace), zgłoszenie na listę wtyczek VT | — |

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
| 0.2 Podstawa sterowania — pierwsze wydanie (jego wersję postanowi się w K4 i K5; tymczasowo 0.2.3b1) | monitor z 0.1 plus sterowanie: na życzenie użytkownika, oznaczone jako eksperymentalne, dostępne od pierwszego dnia — żaden okres monitorowania go nie wstrzymuje (decyzja użytkownika z 2026-10-08), werdykt po 7 dniach danych; każda opcja z ostrożną wartością domyślną i opisem ryzyka; grzanie włącza się i wyłącza tak, jak decyduje kocioł centralny VT, przez pomocnika, za którym wtyczka idzie od razu, i nic liczonego ani odmierzanego nie wstrzymuje grzania wbrew VT (I12); stała krzywa (wpisana; jedna dla zapisywanego obiegu, osobna dla każdego obiegu z CH2); najniższa i najwyższa temperatura wody; okresy rozpoznania i karencji (wymienione wyjątki zasady 12); ochrona przed mrozem zostawiona VT (I12); korekta komfortu w twardych granicach (domyślnie włączona przy pełnym sterowaniu od G11); zapisy każdą drogą: encja wskazana przez użytkownika, wbudowany OTGW przez `opentherm_gw` albo jego firmware przez MQTT, albo przekaźnik dla kotła włącz/wyłącz (klasa 3, 0.2.2); sterowanie tylko ze znanym oddaniem sterowania; nastawa powtarzana co 30 s tam, gdzie nadpisanie wygasa (wbudowany OTGW, wskazana encja zadeklarowana jako wygasająca); wartość, którą urządzenie trzyma (zadeklarowana jako trzymana), wysyłana przy zmianie, po powrocie urządzenia i co 5 min; nic nie jest zapisywane do pamięci trwałej kotła (cel zadeklarowany jako zapisywany na stałe albo o nieznanym typie zapisu zostawia sterowanie wyłączone); żadnych zapisów bez świeżych danych; odczyt zwrotny każdego zapisu; bezpieczne oddanie sterowania przy każdym wyjściu, ponawiane do potwierdzenia; czyste przeładowanie; bezpieczna nastawa awaryjna przy awarii czujnika zewnętrznego; bit włączenia c.w.u. zostawiony taki, jaki był; strażnicy zapisu (strażnik tempa zapisu przed pętlą wymykającą się spod kontroli; zmiany widoczne w odczycie zwrotnym oceniane przez cztery klasy — zgubione polecenie, ignorowane od początku, obcięte, inny sterownik; oddanie sterowania nigdy niewstrzymywane); reakcje alarmów jak w decyzji 7; reguła braku danych; w trybie nastawy zasilania sterowanie tylko ze źródłem potwierdzonej nastawy; jeden obieg zasilany prosto z kotła, z obiegami za stałym zaworem albo sterowanymi przez inną automatykę obok niego (CH2 później); ostrzeżenie o niskim przepływie; lato i zima z VT; rampa temperatury wody; czujnik „nie daje ciepła” dla algorytmów stref (I12); topologia bramki (tryb i to, co jest podłączone do zacisków termostatu) decyduje, czy sterowanie jest dozwolone i do czego prowadzi oddanie sterowania; pole wyboru „własny sterownik pokojowy”; sterowanie w trybie nastawy zasilania (tryb podobny do termostatu w 0.3); menedżer funkcji VT jako kanał, którym VT przekazuje swoje termostaty (I12); korekta komfortu domyślnie włączona przy pełnym sterowaniu, w granicach limitu użytkownika, z ostrzeżeniem, gdy krzywa jest za niska dla pokoju; temperatura pokojowa krzywej Auto (nastawa najcieplejszej strefy) albo Ręczna; długie palenie bez ocieplenia zgłaszane użytkownikowi (krok G11, `docs/en/development/plans/plan-0.2-g11.md`); obiegi tak, jak widzi je kocioł — każdy ze swoimi strefami, swoją najwyższą temperaturą wody oraz własną krzywą i korektą, obieg sterowany przez inną automatykę prosi o ciepło i ustawia dolną granicę temperatury wody, woda kotła obsługuje najbardziej wymagający obieg, który prosi o ciepło; opcje jako pojedyncze formularze bez podmenu, każde pole widoczne tylko tam, gdzie może działać, teksty krótkie i proste (krok I8, `docs/en/development/plans/plan-0.2-i8.md`, który usuwa też to, co należy do pokoi i stref: pokój odniesienia, obsługę okien, obce ciepło, encje dla stref); strona „Kocioł” w menu bocznym i te same części jako karty — stan, kafelki, schemat hydrauliczny z obiegami, które biorą wodę, krzywa z podglądem i zapisem przez administratora, ostatnie 24 h, palnik, zużycie, analizy, dziennik decyzji, stan i alarmy (krok I10, `docs/en/development/plans/plan-0.2-i10.md`; decyzje użytkownika z 2026-11-18); pliki wydania (`LICENSE`, README, `hacs.json`, akcja HACS, Hassfest); **środowisko testowe**: testowy HA w swoim LXC, własny symulator fizyki, scenariusze akceptacyjne (najpierw w jednym procesie, potem w testowym HA) | każdy scenariusz akceptacyjny przechodzi w testowym HA; instalacja autora monitoruje przez 7 dni, potem pracuje ze sterowaniem bez błędów; użytkownik przejrzał 0.1 i 0.2; opublikowane | druga połowa listopada |
| 0.3 Przeciwdziałanie częstym startom i tryb podobny do termostatu | sterowanie cyklem pracy — do rozstrzygnięcia w świetle zasady 12 (`docs/en/development/plans/plan-0.2.2.md` decyzja 13), razem z przerwą przed ponownym startem i histerezą wezwania do grzania (K4, 2026-11-17); korekta komfortu proporcjonalna do niedogrzania, z co najmniej dwóch pokoi przy pełnym zapotrzebowaniu, najwyżej 1–2 K; ograniczenie modulacji, przedstawione jako sposób na dłuższe palenia; wolniejsze opadanie wody przy jej minimum, sprawdzone w symulatorze; planowanie z prognozą (FC2) odłożone — nie znaleziono dowodów; tryb podobny do termostatu — kocioł dostaje temperaturę i nastawę, albo różnicę, strefy proszącej o ciepło, której brakuje najwięcej, i sam ustala swoją wodę (ID 24 / 16 albo wskazane encje; `docs/en/development/plans/plan-0.2-i8.md` G) — domyślnie wyłączony, tylko dla kotła, o którym wiadomo, że reaguje na ID 16/24; termostat ścienny jako rezerwa na awarię Home Assistanta — jedna droga, od VT do termostatu, domyślnie wyłączona (najwcześniej; `docs/en/development/plans/plan-0.2-i8.md` I1); tryb „zastosuj” dla najniższej temperatury wody; grzejniki i podłogówka za zaworem mieszającym (jeden zapisywany obieg plus bierne obiegi stałe) | mniej startów, ten sam komfort | grudzień–styczeń |
| 0.4 Nauka i strojenie | nauka po stronie wody — najpierw przesunięcie krzywej, jej nachylenie dopiero przy różnych temperaturach zewnętrznych; podpowiedzi doradcy, domyślnie „proponuj”, z pokazanym zmierzonym skutkiem każdej zmiany; pasmo strojenia (Wysokie tylko z wyraźnego wyboru); sezonowe dostrojenie zatrzymane na granicy taktowania, z czasem nagrzewania po obniżeniu jako miarą komfortu; próg grzania z regresji — każde dla obiegu, także woda, której potrzebuje obieg sterowany przez inną automatykę, gdy nie podano wartości | niższy powrót, mniej gazu na stopniodzień | styczeń–luty |
| 0.5 Prognoza | wyprzedzanie dla wolnych odbiorników ciepła (FC3) w prostej formie: ograniczona temperatura zewnętrzna „z wyprzedzeniem” tylko dla wolnych obiegów, słońce tylko obniża wodę; czas wyprzedzenia z odpowiedzi obiegu, a zapisane prognozy mówią, na ile można im ufać; stała czasowa budynku z okresów bez grzania (K4, 2026-11-17) | lepszy komfort przy zmianach pogody bez dodatkowego gazu | późna zima albo następny sezon |
| Później | ładowanie c.w.u.; domyślna lista Marketplace (`hacs/default`) i zgłoszenie na listę wtyczek VT; wbudowana obsługa kolejnych urządzeń; gaz szacowany z mocy kotła tam, gdzie nie podano zużycia gazu; polecenia przekaźnika poza włącznikiem i encją termostatu kotła (swobodne akcje VT), jeśli ktoś o to poprosi | — | od wiosny 2027 |

Terminy są celami, nie zobowiązaniami. Symulator pozostaje minimalny: wystarczy, by przyjąć 0.2, zanim trafi
do prawdziwego kotła.
Żadne wydanie nie trafia do prawdziwego kotła, zanim przejdzie w środowisku testowym. Testy automatyczne działają
w jednym procesie; Claude łączy się tylko z testowym HA.

## Przed 0.2

Kontrole przed kodem sterowania: `docs/en/development/plans/plan-0.2.md`, faza F (zrobiona 2026-09-24; odpowiedzi w `docs/pl/specification/scope.md` §11).

## Przed pierwszym wydaniem — do przeglądu (K4)

Dodane 2026-11-16, po sprawdzeniu najnowszego Home Assistanta i VT oraz po przeglądzie
opublikowanych badań (notatki `research/2026-11-16-*`, poza repozytorium). Każdy punkt czeka na
decyzję użytkownika w K4.

**Jak wtyczka jest publikowana.** Od Home Assistanta 2026.11 HACS jest częścią Home Assistanta
i nazywa się Marketplace. Repozytorium spoza jego listy nadal można dodać z linku.

- Kod trafia na `main` (z `qas`) przed wydaniem: dziś na `main` są tylko dokumenty, a Marketplace
  może instalować właśnie z niego.
- Pierwsze wydanie to albo „pre-release” na GitHubie, albo zwykłe wydanie, które w opisie nazywa
  się betą. „Pre-release” jest ukryty, dopóki użytkownik nie włączy wersji przedpremierowych dla
  tego repozytorium, a dopóki nie ma zwykłego wydania, Marketplace instaluje zamiast niego gałąź
  domyślną.
- Po instalacji trzeba zrestartować Home Assistanta albo przeładować VT: VT znajduje wtyczkę
  dopiero, gdy uruchamia swoje termostaty.
- Gdy rodzaj wydania będzie wybrany, instrukcja (§2) i README opiszą obie drogi instalacji: HACS do
  Home Assistanta 2026.10, Marketplace od 2026.11.
- Domyślna lista Marketplace (`hacs/default`) wymaga wydania, przechodzących kontroli i licencji
  open source (Apache-2.0 przechodzi); kolejka trwa miesiące. Lista wtyczek VT to formularz na
  stronie VT.

**Wersje.** Testy przechodzą na najnowsze wersje — Home Assistant 2026.11, VT 10.6.5, SmartPI
0.6.5, `vtherm_api` 0.9.0 — w osobnej sesji testowej; kod wtyczki musi z nimi działać (decyzja
użytkownika, 2026-11-16). Najstarszy obsługiwany Home Assistant idzie za najnowszym VT: 2026.10.4,
jak wymaga VT 10.6.5 (użytkownik, 2026-11-17; `hacs.json`, dwie wersje środowiska testowego w CI).

**Home Assistant 2027.11** usuwa pięć starych interfejsów. Wtyczka używała jednego — starego
sposobu zmiany ID encji — i jest gotowa na nowy (#147, 2026-11-16). VT 10.6.5 nadal używa starych
właściwości temperatury termostatów, które w 2027.11 przestają działać; strefy wtyczki zależą od
tego, czy VT je zmieni. Sprawdzane przy każdym przebiegu wczesnego ostrzegania; bez zgłaszania do
VT (decyzja użytkownika, 2026-11-16).

**Z badań.** Propozycje; każda zmienia ustawienie domyślne albo regułę. **Postanowione przez
użytkownika 2026-11-17** (`research/2026-11-17-k4-literature-proposals.md`): od 1 do 6 i tekst
werdyktu zbudowane — 1 w #149, 2 w #150 (ostrzeżenie o cyklu w VT; kryterium J4: najwyżej ×1,10
startów własnej regulacji kotła albo najwyżej 6 na godzinę przy medianie palenia 10 min), 3 w #151,
4 w #152, 5 i 6 z tekstem o przewymiarowaniu w #153 (gaz na stopniodzień był już z 7 dni); od 7 do
10 w ich wydaniach (niżej, „Wydania” i „Przed 0.3”); przerwę przed ponownym startem z 7 postanawia
się przed 0.3. Zostaje to, co zbudowane, tam, gdzie badania się zgadzają, oraz tymczasowe wartości,
o których badania nic nie mówią (progi zapłonu i spalin, mróz, rampa, czasy).

1. Korekta komfortu domyślnie wyłączona, przynajmniej gdy strefy działają na TPI z VT, a zamiast
   tego proponowana przez doradcę. W badaniach to przesunięcie krzywej na podstawie jednego pokoju
   wzorcowego bez zaworu termostatycznego, proporcjonalne do niedogrzania pokoju — a nie korekta,
   która rośnie do swojego limitu na pokojach dławionych przez VT. Zgadzają się z tym starty z J4,
   od ×1,30 do ×4,42 (F8). To odwraca decyzję z 2026-10-10 (G11).
2. Zalecić cykl TPI co najmniej 10 minut dla stref, które wołają kocioł (domyślnie w VT 5). Dodatkowe
   starty przy −5 °C (F9) biorą się z przerw między impulsami VT, przy obciążeniu, przy którym kocioł
   z modulacją rzadko by gasł. Praktyka brytyjska dla kotłów gazowych to 6 cykli na godzinę.
3. Częste starty w dwóch stopniach: informacja powyżej około 6 na godzinę przez kilka godzin, alarm
   powyżej 12 (dziś tylko 12).
4. Straty ciepła budynku uznawane za znane dopiero po około 3 tygodniach grzania i pokazywane
   z zakresem.
5. Gaz na stopniodzień z 7 dni; zmiana względem poprzedniego dnia z pasmem na szum.
6. Tekst werdyktu wskazuje przewymiarowany kocioł jako główną przyczynę krótkich paleń.
7. Do 0.3: krótka przerwa przed ponownym startem palnika (3 do 5 minut), skracana przy dużym
   niedogrzaniu, ochronie przed mrozem albo ciepłej wodzie i nigdy nieopóźniająca wyłączenia. Jest
   sprzeczna z zasadą 12 (grzanie od razu za VT), więc decyduje użytkownik. Razem z nią korekta
   proporcjonalna do niedogrzania: tylko z pokoi przy pełnym zapotrzebowaniu przez całe cykle, poza
   strefą martwą, z co najmniej dwóch pokoi, najwyżej 1 do 2 K.
8. Do 0.4: najpierw uczyć się przesunięcia krzywej, a jej nachylenia dopiero przy różnych
   temperaturach zewnętrznych; domyślnie „proponuj”; przestać obniżać wodę, gdy starty rosną albo
   palenia się skracają; pokazywać zmierzony skutek każdej zmiany.
9. Do 0.5: wyprzedzanie w prostej formie — ograniczona temperatura zewnętrzna „z wyprzedzeniem”
   tylko dla wolnych obiegów; słońce tylko obniża wodę i tylko trochę. Badania pokazują mały zysk
   z prognoz tam, gdzie pokoje mają już własne sterowanie.
10. Później: średnia temperatura powrotu albo udział poniżej około 45 °C obok udziału poniżej
    55 °C.

Badania zgadzają się z tym, co jest zbudowane: kształt krzywej, najwyższa temperatura wody obiegu,
woda ustawiana przez najbardziej wymagający obieg, krótkie palenia liczone poniżej 10 minut, ciepła
woda rozpoznawana z sygnałów samego kotła. Nie mówią nic o: zapobieganiu taktowaniu na podstawie
prognozy (FC2), progach zapłonu i spalin, paśmie strojenia 3 / 8 / 15 % ani o tym, czy prawdziwe
kotły używają identyfikatorów OpenTherm 16 i 24 (tryb „jak termostat”).

## Przed 0.3

- Punkt decyzyjny po 2–4 tygodniach danych grzewczych z 0.2: pełny zakres, odchudzony zakres albo
  zatrzymanie po 0.2.
- W tym punkcie (K4, 2026-11-17): przerwa 3–5 min przed ponownym startem po zatrzymaniu grzania —
  skracana przy dużym niedogrzaniu, ochronie przed mrozem albo ciepłej wodzie, nigdy nieopóźniająca
  wyłączenia (Siemens LMS14, czas przeciw taktowaniu w kotłach Vaillant; około 0,04 K przy −5 °C) —
  oraz histereza wezwania do grzania (ASHRAE Guideline 36). Obie są sprzeczne z zasadą 12 (grzanie
  od razu za VT): decyduje użytkownik.
- **Szablony urządzeń** (decyzje użytkownika z 2026-11-22): to, czym różnią się połączenia kotła,
  przechodzi do jednego pliku YAML na urządzenie, w trzech warstwach: protokół, zachowanie i drogi
  do urządzenia. Po pierwszym wydaniu, przed pracami nad 0.3:
  [`plan-device-templates.md`](../../en/development/plans/plan-device-templates.md); pola i obecne
  karty są w [`device-connections.md`](../specification/device-connections.md).
- **Pomysły z `vtherm_api`** (przeczytane 2026-11-22), żaden nie jest potrzebny do bety:
  - *Impulsy stref znane z wyprzedzeniem.* VT mówi menedżerowi funkcji, kiedy zaczyna się cykl każdej
    strefy i jak długo grzeje (`async_on_underlying_power`, od `vtherm_api` 0.9.0). Wtyczka mogłaby
    odróżnić krótką przerwę między strefami od prawdziwego końca zapotrzebowania, czyli przerwę,
    która gasi palnik przy 5-minutowym cyklu VT. To jest sprzeczne z zasadą 12, więc decyduje
    użytkownik, a zysk trzeba najpierw zmierzyć w symulatorze.
  - *Ostrzeżenie przed trybem bezpiecznym VT.* Zegary świeżości VT (`vtherm_api` 0.12.0, jeszcze
    niewydane) pozwoliłyby powiedzieć, że czujnik milczy przez większą część opóźnienia
    bezpieczeństwa VT.
  - *Jeden sygnał dla każdego algorytmu strefy: „ta strefa dostaje teraz ciepło”.* Autor SmartPI
    zaproponował interfejs na tym poziomie 2026-11-22. Byłaby to mała, opcjonalna umowa w
    `vtherm_api`, najpierw omówiona z autorami VT i SmartPI, z działającą wtyczką jako dowodem i bez
    pull requesta przed ich zgodą.

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
- 0.2, krok I10 — `docs/en/development/plans/plan-0.2-i10.md`: strona „Kocioł” w menu bocznym i te
  same części jako karty, zmiana krzywej ze strony z tymi samymi sprawdzeniami co w ustawieniach
  (decyzje użytkownika z 2026-11-18)
- 0.2, krok I11 — `docs/en/development/plans/plan-0.2-i11.md`: sterowanie włącza i wyłącza tylko
  administrator w ustawieniach wtyczki, oraz automatyzacje; przełącznik „Sterowanie” staje się
  samym pokazaniem stanu (decyzje użytkownika z 2026-11-22, po F19 z J4)
- 0.2, krok I12 — `docs/en/development/plans/plan-0.2-i12.md`: integracja z VT tylko przez
  `vtherm_api`; o grzaniu decyduje centralny kocioł VT przez pomocnika, za którym idzie wtyczka;
  bez pauz nauki, interfejsu wody i własnej ochrony przed mrozem; pokoje z VT; VT 10.6.5 jako
  najstarsza obsługiwana wersja (decyzje użytkownika z 2026-11-24 i 2026-11-25)
- Szablony urządzeń — `docs/en/development/plans/plan-device-templates.md`: jeden plik parametrów na
  urządzenie kotła, po pierwszym wydaniu (decyzje użytkownika z 2026-11-22)
