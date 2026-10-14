[English version](../../en/specification/scope.md)

# Smart Boiler for Versatile Thermostat — zakres

Ogólny zakres wtyczki, obowiązujący dla każdej instalacji. Zasady pracy i sprawdzone fakty:
`CLAUDE.md`. Plan rozwoju: `docs/pl/development/plan.md`. „Decyzja n” i „odpowiedź X” dotyczą
decyzji użytkownika z 2026-09-26/27 i odpowiedzi z 2026-09-27 w `docs/en/development/plans/plan-0.2.2.md`;
S-n i P-n dotyczą problemów z `docs/en/development/reviews/review-2026-09-26.md`. „(tymczasowe, K4)”
oznacza wartość lub regułę, którą użytkownik potwierdza albo zmienia na przeglądzie, zanim cokolwiek trafi do prawdziwego kotła (`docs/en/development/plans/plan-0.2.md` K4).

## 1. Czym jest

**Natywna wtyczka Versatile Thermostat (VT), która optymalizuje pracę kotła centralnego ogrzewania**
— na gaz, olej, prąd lub inne paliwo; dowolny kocioł, z którym może rozmawiać Home Assistant (§5 „Kotły”;
pompy ciepła wykluczone): mniej i dłuższe palenia, więcej kondensacji tam, gdzie kocioł kondensuje, mniej
paliwa na stopniodzień — przy tym samym komforcie w pokojach i bez psucia modeli pokojów w algorytmach stref.
To, co wtyczka potrafi, zależy od tego, co może zapisać łączność z kotłem (§5): temperaturę wody albo
tylko włączanie i wyłączanie; dane o kondensacji i gazie wymagają kondensacyjnego kotła gazowego
i sygnałów dla nich.

Jej przewaga nad samym kotłem: wie z VT, czego naprawdę potrzebują pokoje.

**Czym nie jest:** regulatorem pokojów (pokoje należą do VT i jego algorytmów stref), sterowaniem zaworami,
sterownikiem pompy ciepła (wykluczona) ani niczym, co wysyła dane na zewnątrz.

## 2. Dlaczego wtyczka

- Funkcja centralnego kotła w VT umie tylko włączać i wyłączać.
- Autor VT odmówił sterowania temperaturą wody w kotle (zgłoszenia #660, #451) i kieruje nowe funkcje
  do wtyczek (#2010).
- W ekosystemie VT nie ma wtyczki do kotła ani do OpenTherm (sprawdzone 2026-09-24).
  `vtherm_pellet_stove` (2026-09-22) steruje centralnym piecem na pelet — to wzór, jak wtyczka
  steruje źródłem ciepła.

## 3. Zasady

1. **Natywna** — instalacja z HACS i config flow; użytkownik nie potrzebuje automatyzacji, skryptów, blueprintów,
   pomocników ani YAML (testowy HA może ich używać).
2. **Uniwersalna** — kotły, obiegi, strefy i algorytmy stref opisują profile, odpowiedzi kreatora
   i wykryte możliwości, nigdy stałe wartości. Brak możliwości wyłącza funkcję z widocznym powodem.
   Encje, które pokazują dane wtyczki, tworzy wtyczka; encje, których potrzebuje — wejścia
   i cele zapisu — wskazuje użytkownik w config flow. Większość instalacji podaje tylko część wejść:
   każda funkcja działa z tym, co ma, a brak danych nigdy sam nie wyłącza grzania
   (reguła braku danych, §7).
3. **Centralna woda, lokalne zawory** — każdy obieg ma jedną temperaturę wody i własną krzywą; wtyczka ustala ją
   centralnie (tryb nastawy zasilania), zostawia ją własnej regulacji kotła (tryb podobny do termostatu, od 0.3)
   albo zasila obieg, który ma własny sterownik. Strefy dławią przepływ swoimi zaworami; informacja płynie od kotła
   do stref. Kocioł włączany i wyłączany przekaźnikiem (klasa 3) dostaje tylko włączanie i wyłączanie grzania:
   temperatura jego wody zostaje po stronie kotła.
4. **Nie psuć innych modeli** — wstrzymuj naukę algorytmów stref przez ich publiczne usługi
   (SmartPI; Auto-TPI dopiero wtedy, gdy jego usługa potrafi wstrzymać bez utraty tego, czego się nauczył, §11).
5. **Bezpieczna** — stałe zabezpieczenia z zasady 11 działają zawsze; limity ustawia użytkownik,
   z ostrożnymi wartościami domyślnymi.
6. **Lokalna** — nic nie jest wysyłane na zewnątrz.
7. **Angielski z tłumaczeniami HA** — nic widocznego dla użytkownika nie jest wpisane na sztywno.
8. **Domyślnie podpowiedzi** — automatyczne zmiany tylko w paśmie strojenia.
9. **Pogoda liczona raz** — krzywa grzewcza jest kanałem pogody; sygnały ze stref tylko ją korygują.
   Algorytm strefy z własnym składnikiem temperatury zewnętrznej (`tpi_coef_ext` w TPI, `u_ff1` w SmartPI)
   liczy pogodę drugi raz; dokumentacja mówi, jak go ustawić obok wtyczki. Składnik TPI jest ustawieniem;
   SmartPI 0.4.0 uczy się własnego składnika temperatury zewnętrznej (`u_ff1`), którego nie da się ustawić,
   i dokumentacja o tym mówi (S-50).
10. **Dwa rodzaje użytkowników** — zwykły użytkownik dostaje działające ustawienia domyślne, mało pytań i proste
    werdykty; zaawansowany dostaje każdy parametr, diagnostykę i możliwość nadpisania. Poziom zmienia to,
    co widać, nigdy to, jak wtyczka się zachowuje. Przy przejściu z zaawansowanego na prosty
    użytkownik wybiera, czy przywrócić ustawienia zaawansowane do wartości domyślnych, czy zostawić je ukryte;
    zostawione ustawienia nadal działają, a prosty widok pokazuje, że niektóre ustawienia zaawansowane
    różnią się od domyślnych.
11. **Użytkownik decyduje, mając informacje** — wybory dotyczące sterowania należą do użytkownika: droga zapisu,
    sposób oddania sterowania, tryb sterowania (nastawa zasilania, włącz/wyłącz, a od 0.3 tryb podobny do termostatu),
    limity, krzywa, progi zapotrzebowania, wstrzymania nauki, liczba dni danych, których potrzebuje werdykt.
    Każdy wybór ma ostrożną wartość domyślną i opis tego, co robi i czym grozi — w config flow i w dokumentacji.
    Stałe zabezpieczenia, nie opcje, przy każdym zapisie (nastawa zasilania, włączanie i wyłączanie c.o.,
    ograniczenie modulacji, wartości trybu podobnego do termostatu wysyłane do kotła, przekaźnik): żadnego zapisu bez
    świeżych danych wejściowych — sterowanie temperaturą wody wymaga znanych sygnałów płomienia i zasilania,
    a łącznością przekaźnika jest sam przekaźnik; wartości w twardych granicach, z wyjątkiem „wyłączone”
    i wartości oddania, które mają własne kontrole (§7) — wartość oddania nadal mieści się w maksimum obiegu
    i w najwyższej temperaturze wody (S-21); nic nie jest zapisywane do pamięci trwałej kotła — sterowanie zapisuje
    tylko do celów, których wartości wygasają albo które urządzenie trzyma (§7); strażnik tempa zapisu przed pętlą
    wymykającą się spod kontroli (powtórzony zapis czeka najwyżej jeden krok sterowania); odczyt zwrotny każdego
    zapisu albo wartość oznaczona jako niepotwierdzona, gdy nic niezależnego od wtyczki jej nie zgłasza — własny
    zgłaszany stan przekaźnika potwierdza przekaźnik, ale nie to, że kocioł grzeje; wartość zmienioną z zewnątrz
    oceniają cztery klasy — zgubione polecenie jest wysyłane ponownie, wartość ignorowana od początku nie jest już
    wysyłana, obcięcie jest akceptowane, a inny sterownik jest nadpisany raz, po czym wtyczka ustępuje z pełnym
    bezpiecznym oddaniem sterowania — nigdy walka (§7); oddanie sterowania przy każdym wyjściu w bezpiecznej kolejności,
    ze zdjętymi wszystkimi nadpisaniami, nigdy niewstrzymywane przez strażnika i ponawiane do potwierdzenia —
    z wyjątkiem celu, który inny sterownik przejmuje po oddaniu: ten liczy się jako oddany; sterowanie tylko ze znanym
    oddaniem i, przy sterowaniu nastawą, ze źródłem potwierdzonej nastawy; przy awarii czujnika zewnętrznego
    bezpieczna nastawa awaryjna, nigdy brak ciepła, albo w trybie podobnym do termostatu wyczyszczone jego wartości,
    żeby własne sterowanie kotła działało dalej; bit włączenia c.w.u. zostawiony taki, jaki był. Wartości limitów
    są opcjami; same zabezpieczenia nie są i żadne z nich nie decyduje, czy grzać (zasada 12). Przekaźnik,
    który nie zgłasza własnego stanu, jest sterowany ślepymi powtórzeniami i pokazany jako
    „sterowany bez potwierdzenia”; świeżość dotyczy wtedy wejść decyzji — stref i temperatury
    zewnętrznej.
12. **VT decyduje, czy grzać** — wtyczka zastępuje centralny kocioł VT: grzanie włącza się i wyłącza
    zgodnie z zapotrzebowaniem stref, od razu i w obu kierunkach; wtyczka decyduje tylko o tym, jak ciepła
    jest woda — krzywa, limity i rampa. Nic, co wtyczka liczy lub odmierza, nie wstrzymuje ani nie
    utrzymuje grzania wbrew VT: stary kocioł z wysoką minimalną mocą sam często się włącza i wyłącza,
    a jego blokowanie zostawiłoby dom zimny. Częste starty to informacja — alarm z progiem i werdykt.
    (Decyzja użytkownika z 2026-09-25.) Wymienione wyjątki, każdy ze swoim powodem (§7; decyzje
    użytkownika z 2026-09-26/27):
    1. Ochrona przed mrozem, siatka bezpieczeństwa — tylko dla stref, których odbiornik ciepła może przyjąć ciepło (decyzja 4).
    2. Okres rozpoznania, najwyżej 10 min po starcie Home Assistanta lub przeładowaniu VT: żadnej nowej
       decyzji, ostatnie polecenie zostaje. Powód: strefy zgłaszają się jedna po drugiej.
    3. Okres karencji: strefa, która staje się nieznana, zachowuje swoją ostatnią odpowiedź przez 10 min. Powód:
       przeładowanie jednej strefy nie powinno ani uruchamiać, ani zatrzymywać kotła.
    4. Brak grzania, gdy każda strefa jest nieznana albo nie da się ocenić żadnego skonfigurowanego kryterium
       zapotrzebowania, po okresie karencji, i nie ma działającego termostatu (§7). Powód: nic nie może poprosić
       o ciepło (decyzja 3).
    5. Opóźnienie włączenia VT, 0–600 s przed włączeniem, jak w VT 10.4.0. Powód: wolne zawory
       (decyzja 5).
    6. Zwykłe „wyłączone”, gdy kocioł zgłasza usterkę, która go zatrzymuje (znane „włączone” trzymane 5 min,
       tymczasowe, K4). Powód: wtyczka idzie za własną logiką kotła.
    7. Utrata łączności z kotłem: od pierwszego kroku żadnego zapisu bez świeżych danych, potem oddanie sterowania
       po 5 min — przy bramce samodzielnej grzanie się zatrzymuje — albo, dla przekaźnika, alarm i brak oddania (decyzja
       z 2026-09-25; §5 klasa 3). W międzyczasie `CS` bramki samodzielnej wygasa w ciągu około minuty, więc
       kocioł zatrzymuje się i startuje ponownie, gdy dane wrócą (dodatkowy start), a trzymane polecenie
       zostaje do 5 min, o cokolwiek prosi VT.

    Oddanie sterowania, którego wymagają reguły — inny sterownik, błąd wewnętrzny, własny monitor wtyczki
    niedziałający przez 5 min, kocioł ignorujący „wyłączenie grzania” od początku sesji,
    wyjście — nie jest decyzją o tym, czy grzać: oddaje kocioł jego własnemu sterowaniu albo termostatowi, a przy bramce
    samodzielnej zatrzymuje grzanie (§5). Przeciwdziałanie częstym startom w 0.3 ma być rozstrzygnięte
    w świetle tej zasady (decyzja 13).
13. **Ograniczona nauka** — każda wartość, którą wtyczka sama dostosowuje lub której się uczy, teraz i w późniejszych
    wydaniach, podlega stałym regułom, które nie są opcjami: (1) twarde pasmo wokół jej punktu wyjścia
    (wpis użytkownika albo wartość domyślna), którego nigdy nie opuszcza; (2) ograniczone tempo zmian, na godzinę
    i na dobę; (3) zmienia się tylko wtedy, gdy spełnione są wszystkie inne kryteria — komfort w każdej strefie,
    żadna strefa nie jest przegrzana, cykle kotła nie stają się częstsze, każdy limit jest dotrzymany — i cofa się,
    gdy któreś z nich się pogarsza; (4) celem jest pasmo „wystarczająco dobrze”, nie optimum: nauka w nim
    się zatrzymuje; (5) zamraża się w nietypowych warunkach — c.w.u., luki w danych, oddanie sterowania,
    skrajna pogoda (temperatura zewnętrzna poniżej projektowej temperatury zewnętrznej albo zmieniająca się
    szybciej niż 2 K na godzinę; tymczasowe, K4); (6) na brzegu pasma informuje zamiast naciskać dalej —
    punkt wyjścia jest prawdopodobnie zły; (7) każda wyuczona wartość jest widoczna i można ją zresetować;
    wartości sesji (korekta komfortu) są resetowane przy oddaniu sterowania i na końcu sesji; wyuczone
    właściwości kotła (najniższa temperatura wody, gdy tryb „zastosuj” nauczy się jej w 0.3) są zachowywane
    i resetowane, gdy użytkownik je zresetuje albo gdy zmieni się wejście, na którym się opierają; własny
    wpis użytkownika nigdy nie jest resetowany (decyzja 2, S-58). Doprowadzanie jednej wielkości do ideału może
    zepsuć inną: ogrzać jeden pokój, przegrzać resztę. (Decyzja użytkownika z 2026-09-25.) Wartości reguł —
    pasmo, tempa, warunki zamrożenia — są stałe; jedyne opcje to to, czy funkcja nauki działa (wyłączone /
    podpowiedzi / zastosuj) oraz pasmo strojenia z zasady 8 (Niskie / Średnie / Wysokie / Własne)
    (tymczasowe, K4). Każda wartość pokazuje swoje źródło — domyślna dla klasy kotła, wpis użytkownika,
    zmierzona, wyuczona; wpis użytkownika zawsze wygrywa ze zmierzonymi i wyuczonymi wartościami,
    a „zastosuj” (0.3) porusza się tylko w paśmie
    wokół niego (S-58).

## 4. Poziomy użytkowników

| Obszar | Zwykły użytkownik | Zaawansowany użytkownik |
|---|---|---|
| Kreator | najpierw sposób podłączenia kotła (z niego wynika klasa kotła), tryb sterowania (bez wartości domyślnej), źródło ciepła i typ kotła z kondensacją i priorytetem c.w.u. (I6, `docs/en/development/plans/plan-0.2-i6.md`); przy pełnym sterowaniu lub sterowaniu włącz/wyłącz także pozycje sterowania w konfiguracji — urządzenie sterujące, krzywa grzewcza, zachowanie sterowania, ochrona przed mrozem, reakcje alarmów, każda jako jeden formularz pokazywany tam, gdzie ma zastosowanie (I8 H) —, włącznik sterowania nadal wyłączony (decyzja 11 z I6); pozycja „Interfejs kotła” — tematy MQTT, bramka tam, gdzie skonfigurowano więcej niż jedną, topologia bramki i to, co jest podłączone do zacisków termostatu bramki (decyzja 1), wskaźnik restartu, tylko to, czego używa połączenie i tryb (I8 D2) —; odczyty zwrotne wśród sygnałów kotła (I8 D3); obiegi — każdy jako osobna pozycja menu, z nazwą, do czterech, usuwany zaznaczeniem pola, każdy z listą stref VT, które zasila, a spośród nich tych z ogrzewaniem podłogowym i konwektorami, a dla strefy, którą zasila tylko w części — urządzeniami tej strefy — strefa w dwóch obiegach należy do każdego przez swoje urządzenia (I8 F1, F2, F4; I8.8c) — i jedno pytanie o strefy: których zawory zamykają się po wyłączeniu (F5), temperatura zewnętrzna przy najsilniejszym mrozie (punkt krzywej, gdy jest krzywa; w innym razie z obciążeniem projektowym, I8 E3) i limity ciśnienia wody z instrukcji kotła; na drogach zapisu przez encję i przez przekaźnik pole wyboru „kocioł ma własny sterownik pokojowy” (odpowiedzi F, M); na drodze przez przekaźnik własne ustawienia przekaźnika i pole wyboru „to jest osobny styk przekaźnika, a nie ustawienie zapisane w pamięci kotła” (odpowiedź G); w ESPHome pole wyboru „bezpieczne wartości startowe i krótki `reboot_timeout` API” (decyzja 3 z I6) | każde pole profilu, wartości zmierzone, obciążenie budynku z własnych obliczeń |
| Ocena | werdykt: warto włączyć sterowanie albo nie, i dlaczego | wszystkie metryki, na zakres temperatury zewnętrznej, surowe dane cykli |
| Sterowanie | domyślnie wyłączone; po włączeniu sterowanie działa automatycznie w wybranym trybie; zmiany krzywej: podpowiedzi (domyślnie) albo automatycznie w ustawionym paśmie (Niskie / Średnie / Wysokie) | pasmo własne, nadpisania pojedynczych parametrów, ręczna edycja wyuczonych wartości, reset do profilu |
| Alarmy | rozsądne reakcje domyślne | progi dla każdego alarmu; reakcja tylko tam, gdzie pozwala na nią decyzja 7 (§7) |
| Diagnostyka | ukryta | parametry modelu, pewność, powody odrzucenia próbek |
| Nauka | korekta komfortu, dotąd jedyna nauka przy sterowaniu, jest domyślnie włączona przy pełnym sterowaniu i pokazana na obu poziomach (użytkownik, 2026-10-10, odwracając K4.1 — wpis po aktualizacji zachowuje to, z czym działał; `docs/en/development/plans/plan-0.2-g11.md`); jej limit ustawia użytkownik, na poziomie zaawansowanym; późniejsza nauka włączana w bezpiecznych granicach | wstrzymanie i wznowienie, korekta komfortu, pasmo strojenia (zasada 13), okna nauki, ustawienia ochrony algorytmów stref |

Przejście z zaawansowanego na proste oferuje „przywróć ustawienia zaawansowane do wartości domyślnych” (domyślnie
niezaznaczone). Nigdy nie rusza wyuczonych wartości; mają one własny przycisk „przywróć domyślne
wartości profilu”.

Profile kotłów — z „zresetuj do profilu” i „przywróć domyślne wartości profilu” — pojawią się później;
do tego czasu wartości domyślne daje klasa kotła.

## 5. Sprzęt, obiegi i algorytmy stref

### Kotły — każdy kocioł, który komunikuje się z HA

To, co wtyczka może zrobić, zależy od tego, co integracja potrafi zapisać:

| Klasa | Przykłady | Zakres | Od wydania |
|---|---|---|---|
| 1. Nastawa zasilania (+ limit modulacji) | OpenTherm (OTGW, DIYLess, ESPHome), EMS-ESP, część rozwiązań z ebusd | pełny | 0.2 |
| 2. Tylko parametry krzywej | BSB-LAN, ViCare | tylko podpowiedzi (S-56) | później |
| 3. Włącz/wyłącz | przekaźnik na zaciskach termostatu pokojowego kotła albo encja termostatu kotła przełączana między grzaniem a wyłączeniem | włączanie i wyłączanie grzania, jak w centralnym kotle VT, z zabezpieczeniami wtyczki | 0.2.2 |
| 4. Tylko odczyt | dowolny | monitor | 0.2 (zbudowany jako 0.1) |

- Odczyt działa z każdą integracją: użytkownik przypisuje każdy sygnał do encji w kreatorze
  konfiguracji; możliwości wynikają z wypełnionych pól.
- Tryb sterowania, jeden naraz, do wyboru przez użytkownika: **nastawa zasilania** (od 0.2) —
  wtyczka ustala temperaturę wody ze swojej krzywej i zapisuje nastawę; **włącz/wyłącz** (od 0.2.2,
  przekaźnik); **jak termostat** (od 0.3) — wtyczka włącza i wyłącza grzanie zgodnie z
  zapotrzebowaniem stref i wysyła do kotła temperaturę pokojową i nastawę, albo ich różnicę, dla
  strefy, która prosi o ciepło i której brakuje go najbardziej, a o temperaturze wody decyduje
  własna regulacja kotła; w tym trybie wtyczka nie zmienia ani krzywej, ani temperatury wody.
  Potrzebuje urządzenia, które przyjmuje te wartości (OpenTherm ID 24 / 16 przez wbudowaną obsługę
  albo encje wskazane przez użytkownika) oraz kotła, który z nich korzysta (§5, „Tryb jak
  termostat”).
- Zapis (od 0.2), w tej kolejności: (1) zapisywalna encja wskazana przez użytkownika — z dowolnej
  integracji, także encja stworzona przez użytkownika; (2) wbudowana obsługa urządzeń bez takiej
  encji — najpierw OTGW, przez `opentherm_gw` albo przez firmware bramki po MQTT; (3) od 0.2.2
  przekaźnik dla kotła włącz/wyłącz (klasa 3); (4) w przeciwnym razie tylko monitorowanie, z
  pokazaną przyczyną.
- **Połączenie** (I6, `docs/en/development/plans/plan-0.2-i6.md` decyzje 1–5; tymczasowe, K4):
  pierwszy panel konfiguracji pyta, jak kocioł jest podłączony, a odpowiedź ustala klasę kotła (co
  połączenie potrafi), oferowane ścieżki zapisu, oferowane typy zapisu i sposoby oddania
  sterowania, to, czy wymagany jest włącznik grzania, oraz podpowiadane encje; sekcja sterowania,
  która nie pasuje do połączenia, albo topologia inna niż „wirtualna” przy ESPHome lub EMS-ESP,
  jest zablokowana.

  | Połączenie | Ścieżka zapisu | Typy zapisu | Oddanie sterowania | Włącznik grzania | Klasa |
  |---|---|---|---|---|---|
  | OpenTherm Gateway (integracja) | `opentherm_gw` | stałe (`CS` wygasający, `CH=` trzymany) | bezpieczne oddanie sterowania | wbudowany | nastawa zasilania |
  | Firmware OTGW po MQTT | `otgw_mqtt` | jak wyżej | jak wyżej | wbudowany | nastawa zasilania |
  | ESPHome OpenTherm | encja, wirtualna | trzymany, trzymany (oferowane) | wartość (oferowane) | wymagany | nastawa zasilania |
  | EMS-ESP | encja, wirtualna | nastawa wygasająca (oferowane) | limit czasu urządzenia, 1 min (oferowane) | niepotrzebny: „wyłączone” to jego nastawa 0 | nastawa zasilania |
  | Przekaźnik | przekaźnik | — | jego stan spoczynku | — | włącz/wyłącz |
  | Moduł Wi-Fi kotła albo integracja producenta | encja | nieznane, nie jest zapisywana | — | wymagany | tylko odczyt (oferowane) |
  | Inna zapisywalna encja | encja | deklaruje użytkownik | wybiera użytkownik | wymagany | nastawa zasilania |
  | Inna integracja, tylko odczyt | brak | — | — | — | tylko odczyt |

  - ESPHome: ESP zachowuje ostatnią nastawę i włączenie CH do swojego restartu (jego API
    `reboot_timeout`, domyślnie 15 min), po czym wraca do skonfigurowanych wartości startowych;
    sterowanie wymaga zaznaczenia przez użytkownika, że te wartości są bezpieczne, a limit czasu
    krótki (bez tego jest blokada). Przewodnik użytkownika podaje przykładową konfigurację, z
    `force_update: true` na czujnikach; czujnik liczbowy, który w pierwszych sześciu godzinach
    działania nigdy nie powtarza niezmienionej wartości, jest wskazany w zgłoszeniu naprawy.
  - EMS-ESP: „wyłączone” to nastawa 0, czyli jego własne, opisane w dokumentacji „Force Heating
    Off”, zapisywane co 30 s jako wartość wygasająca — decyzja 11 z
    `docs/en/development/plans/plan-0.2.2.md` uchylona tylko dla EMS-ESP (użytkownik, 2026-10-08),
    i tylko przy nastawie zadeklarowanej jako wygasająca, tak aby zatrzymany Home Assistant
    zostawiał kocioł na jego własnym sterowaniu w ciągu około minuty. Wartość 0, którą kocioł od
    początku ignoruje, blokuje sterowanie i oddaje sterowanie, tak jak robi to odpowiedź O dla
    włącznika grzania. Nie wiadomo, co robi pompa przy 0; teksty o tym mówią.
  - Wpis utworzony przed I6 nie ma tych odpowiedzi i działa jak dawniej: bez nowej blokady; opcje
    pokazują panele, wstępnie wypełnione z zapisanej ścieżki zapisu tam, gdzie ta wskazuje
    połączenie.
- **Źródło ciepła i typ kotła** (I6, decyzje 7 i 8): gaz (ziemny lub LPG), olej, prąd albo inne —
  pellet i biomasa później — decydują o tym, które pola, sygnały i alarmy mają zastosowanie (kocioł
  elektryczny nie ma płomienia, spalin, kondensacji ani gazu: jego sygnał płomienia oznacza „grzanie
  włączone”; olej nie ma licznika gazu). Typ kotła ma standardowe nazwy — jednofunkcyjny z
  zasobnikiem c.w.u. lub bez, combi, combi z wbudowanym zasobnikiem — potem kondensacyjny (tylko
  gaz i olej) i, dla każdego kotła, który grzeje c.w.u., czy c.w.u. ma priorytet (domyślnie), czy
  nie; bez priorytetu c.w.u. ani nie wstrzymuje nauki, ani nie oznacza ciepła jako niedostępnego
  dla stref.
- Sterowanie włącza się tylko ze znanym sposobem oddania sterowania, wybranym przez użytkownika: dla
  wbudowanego OTGW jest to bezpieczne oddanie sterowania opisane niżej; dla wskazanej encji —
  wartość, zadeklarowana wraz ze skutkiem (własne sterowanie urządzenia wraca albo grzanie się
  zatrzymuje) i zakończona dopiero po odczycie zwrotnym, własny limit czasu urządzenia, albo
  przełącznik z zadeklarowanym typem zapisu (typ zapisywany na stałe nie jest używany, P-40); dla
  przekaźnika — jego stan spoczynku. Tryb tylko monitorowania nie jest sposobem oddania sterowania
  (S-59). Do czego prowadzi oddanie sterowania, zależy od topologii.
- **Bezpieczne oddanie sterowania** (decyzja użytkownika z 2026-09-26/27), w tej kolejności, jedna
  część po drugiej od razu, każda próbowana bez względu na to, co robią pozostałe, bez czekania na
  odczyt zwrotny i bez czekania, aż woda ostygnie (tymczasowe, K4): (1) woda na ustawioną najniższą
  temperaturę wody; (2) grzanie włączone tam, gdzie kocioł wraca do termostatu albo do własnego
  sterowania — na bramce zawsze `CH=1`, które zdejmuje tylko własne `CH=0` wtyczki (w pracy
  samodzielnej `CS=0` nadal zatrzymuje grzanie); włącznik grzania na ścieżce encji nie jest
  włączany tam, gdzie zadeklarowanym skutkiem jest „grzanie się zatrzymuje” (S-27); (3) zwolnienie
  — `CS=0` na bramce, wartość oddania sterowania, wyłączony przełącznik sterowania zewnętrznego albo
  limit czasu. Przekaźnik zamiast tego przechodzi do stanu spoczynku. Ta sama kolejność obowiązuje,
  gdy wtyczka ustępuje innemu sterownikowi (§7, odpowiedź H): oddawany jest każdy cel, nawet ten,
  który trzyma inny sterownik, a każda część jest zapisywana raz.
  - Tam, gdzie cel jest zadeklarowany jako trzymany (urządzenie zachowuje ostatnią otrzymaną
    wartość: ESPHome, DIYLess i podobne; nie `selflowtemp` w EMS-ESP, które wygasa w ciągu około
    minuty), a zwolnienie nie jest potwierdzone, kocioł zostaje na najniższej temperaturze wody:
    alarm włącza się od razu, a zwolnienie jest ponawiane co minutę, aż zostanie potwierdzone.
  - Cel, który po oddaniu sterowania przejmuje inny sterownik, liczy się jako oddany, bez
    ponawiania: nastawa — gdy stała, obca wartość utrzymuje się przez 2 ponowienia, liczone dopiero
    wtedy, gdy zapis oddania sterowania wykonany przez wtyczkę do tego celu dotarł w tej
    zaległości, i nie wtedy, gdy ślad awarii jego urządzenia albo restartu, widziany od tego zapisu,
    mówi, że urządzenie ją straciło (trzymany master, który restartuje się podczas oddania
    sterowania, wraca ze swoją własną wartością startową: F7 z J4); cel dwuwartościowy (włącznik
    grzania, przełącznik sterowania zewnętrznego, przekaźnik po oddaniu innym niż ustąpienie,
    tymczasowe, K4) — gdy jego stan z oddania sterowania został raz odczytany, a potem zmienił się
    bez śladu awarii. Wcześniej cel pozostaje zaległy i jest ponawiany. To zmienia „ponawiane co
    minutę, aż zostanie potwierdzone” tylko w tym przypadku.
  - Brakujący albo `unavailable` cel oznacza, że oddanie sterowania się nie udało: Home Assistant
    odrzuca takie wywołanie bez błędu. Cel `unknown` jest zapisywany i liczy się dopiero po
    odczycie zwrotnym (S-28). Encja z `assumed_state` albo bez raportu niezależnego od wtyczki jest
    „niepotwierdzona” i tak to pokazuje (S-09).
  - Oddanie sterowania przez limit czasu uznaje się za zwolnione, gdy odczyt zwrotny wróci w
    granice 0.5 K od poziomu wyjściowego sesji, albo gdy jest dalej niż 0.5 K zarówno od ostatniej
    wartości wtyczki, jak i od właśnie zapisanej najniższej temperatury wody (urządzenie, którego
    własna wartość się porusza). Formularz pyta o limit czasu urządzenia przy tej metodzie;
    sprawdzenie liczy od ostatniego zapisu, a `hand_back_failed` pojawia się 3 min po tym limicie
    czasu bez zwolnienia. Nie zapisuje ponowień, a do tego czasu cel pozostaje zaległy i jest
    pokazywany (S-20; decyzja 5 z `docs/en/development/plans/plan-0.2.3.md`; tymczasowe, K4).
  - Wartość oddania sterowania jest zwolniona tylko z najniższej temperatury wody: maksimum obiegu i
    najwyższa temperatura wody nadal obowiązują (S-21). „Wyłączone” jest odrzucane w granicach 0.5
    K od wartości oddania sterowania zadeklarowanej jako „własne sterowanie urządzenia wraca”
    (S-49). Po oddaniu sterowania jedynym maksimum jest własne maksimum kotła albo termostatu
    ściennego: niemieszana pętla ogrzewania podłogowego zostaje przy nim, jak mówią teksty o
    przekaźniku.
  - Zaległe oddanie sterowania można rozliczyć ręcznie: jego zgłoszenie naprawy jest oferowane,
    dopóki oddanie jest zaległe, a użytkownik potwierdza, że kocioł znów działa na własnym
    sterowaniu; wtyczka zapomina wtedy zaległość i przestaje ponawiać (S-45).
  - Usunięcie wpisu: Home Assistant nie daje prawa weta. Wtyczka robi ostatnią próbę, a jeśli się
    nie uda, wystawia trwałe zgłoszenie naprawy (S-54).
- Klasa 2: tylko podpowiedzi; wtyczka nie zapisuje parametrów krzywej, bo są trwałe (S-56).
- Klasa 3 — przekaźnik (od 0.2.2, tak jak działa centralny kocioł VT; decyzja 13): bez czasomierzy
  przeciw krótkim cyklom i bez limitu liczby startów, których centralny kocioł VT też nie ma.
  - Ścieżka zapisu „przekaźnik” to przełącznik albo encja termostatu kotła przełączana między
    grzaniem a wyłączeniem; `input_boolean` jest odrzucany, bo niczego nie potwierdza. Części
    dotyczące temperatury wody (krzywa, limity, rampa, korekta komfortu) nie mają zastosowania i są
    ukryte; opóźnienie włączenia jest pokazane (§7).
  - Wtyczka nie może odczytać własnych ustawień przekaźnika, więc formularz pyta o nie jako o
    deklarację użytkownika (wartości domyślne tymczasowe, K4): zaznaczenie „to jest osobny styk
    przekaźnika, a nie ustawienie zapisane w pamięci kotła”, bez którego sterowanie nie startuje, z
    blokadą podającą przyczynę (odpowiedź G); jego stan po zaniku zasilania (wyłączony / włączony /
    ostatni / nie wiem; domyślnie „nie wiem”, traktowane jako „może być włączony”); jego własny
    czasomierz wyłączenia (brak / jego długość, 10–120 min — krótszy jest odrzucany, a zapisany
    krótszy jest odczytywany jako „nie wiem”, z ostrzeżeniem w logu (decyzja użytkownika z
    2026-10-03) / nie wiem; domyślnie „nie wiem”, traktowane jako „może go mieć”); czy raportuje
    swój stan (tak / nie / nie wiem; domyślnie „nie wiem”, traktowane jako „nie” — encja z
    `assumed_state` zawsze liczy się jako „nie”); odstęp powtarzania, 10–300 s, domyślnie 300 s.
  - Płomień i zasilanie są opcjonalne dla całego wpisu; sterowanie temperaturą wody dostaje
    blokadę tam, gdzie brakuje któregoś z nich.
  - Łącznością jest przekaźnik: dostępny i, tam gdzie raportuje, w poleconym stanie. Przekaźnik poza
    zasięgiem wywołuje alarm „przekaźnik nieosiągalny” i po 5 min zgłoszenie naprawy, a po powrocie
    dostaje polecenie ponownie; w międzyczasie nie próbuje się oddania sterowania, bo nie mogłoby
    dotrzeć. Dla przekaźników to odstępstwo od zasady „utrata łączności oddaje sterowanie”
    (2026-09-25).
  - Jego własny zgłoszony stan potwierdza przekaźnik, a nie to, że kocioł grzeje — wyjątek od
    zasady „odczyt zwrotny z zapisywanej encji niczego nie potwierdza”. Encja z `assumed_state`
    niczego nie potwierdza. Stan jest sprawdzany co 5 min (tymczasowe, K4), a polecenie wysyłane
    ponownie tylko przy niezgodności; przekaźnik, który nie raportuje stanu albo może mieć
    czasomierz wyłączenia, dostaje ślepe powtórzenia co odstęp powtarzania i jest pokazany jako
    „sterowany bez potwierdzenia”. Przy zadeklarowanej długości czasomierza „włączony” jest
    odnawiany co min(czasomierz ÷ 2, odstęp powtarzania), a wyłączenie w ciągu 60 s od
    całkowitej wielokrotności czasomierza, najwyżej 3×, liczone od „włączony”, które rozpoczęło
    okres włączenia, albo od ostatniego odnowienia, jest upływem czasomierza: odpowiada się na nie
    „włączony” i nie liczy się go; każde inne wyłączenie to zmiana widziana na przekaźniku, według
    odpowiedzi C i N poniżej (decyzja 6 z `docs/en/development/plans/plan-0.2.3.md`).
    Przy „nie wiem” wyłączenie co najmniej jeden odstęp powtarzania po „włączony”, które rozpoczęło
    okres włączenia, też jest odpowiadane „włączony”, ale liczone jako restart, którego przekaźnik
    nie zgłosił (odpowiedź N): czwarty w ciągu 24 h sprawia, że wtyczka ustępuje (tymczasowe, K4;
    Z4-02). Wyłączenia powtarzające się w tym samym czasie od początku okresu włączenia, 9 min lub
    więcej (10 min, z dopuszczeniem pomiaru krótszego najwyżej o minutę) — w granicach 60 s albo
    całkowita wielokrotność do 3× — to własny czasomierz przekaźnika: odpowiada się na nie, nie
    liczy się ich już, a zgłoszenie z ostrzeżeniem prosi użytkownika o zadeklarowanie go; krótsze
    regularne wyłączenia nigdy nie są brane za niego, bo każde ponownie uruchamiałoby kocioł: liczą
    się do odpowiedzi N, czwarte w ciągu 24 h sprawia, że wtyczka ustępuje (raz stan spoczynku,
    zatrzaśnięte), a zgłoszenie naprawy zatrzasku na poziomie błędu mówi, że przekaźnik wyłączał się
    sam mniej więcej co N min, i każe ustawić jego czasomierz na co najmniej 30 min albo go wyłączyć
    (decyzja użytkownika z 2026-10-03); okres włączenia liczy się od „włączony”, który go
    rozpoczął — wtyczki albo późniejszego własnego przełączenia przekaźnika z wyłączonego na
    włączony, jak pokazał Home Assistant; powrót ze stanu „niedostępny” albo „nieznany” nie jest
    takim przełączeniem i go nie przesuwa (tymczasowe, K4; Z4R-02, Z4R2-01). Po rozpoznaniu własny
    czasomierz przekaźnika jest odnawiany jak zadeklarowany, „włączony” co min(jego długość ÷ 2,
    odstęp powtarzania); jego długość i porównane z nią wyłączenia z danego dnia są zapisywane razem
    z przekaźnikiem, więc ani restart, ani zapis opcji, ani utrata łączności nie powodują ich
    zapomnienia, a wyłączenie w takim wieku okresu włączenia, który wtyczka widziała od początku,
    nigdy nie liczy się do odpowiedzi N (wyłączenie po wyłączeniu i włączeniu zasilania,
    nieplanowanym restarcie albo przeładowaniu liczy się raz, Z4R3-04); są usuwane, gdy zmieni się
    odpowiedź o przekaźniku albo o jego czasomierzu. Ostrzeżenie mówi, że automatyka wyłączająca
    przekaźnik tak długo po „włączony” („maksymalny czas pracy”) wygląda tak samo (Z4R2-02,
    Z4R2-05).
  - Zmiany widziane na przekaźniku podlegają tabeli z §7 (wiersze R1–R9): przekaźnik znaleziony w
    innym stanie po utracie zasilania albo łączności, albo z powrotem w zadeklarowanym stanie po
    zaniku zasilania, dostaje polecenie ponownie (restart); 3 takie restarty w ciągu 24 h wywołują
    ostrzeżenie informacyjne, a czwarty w ciągu 24 h liczy się jako inny sterownik. Gdy stan po
    zaniku zasilania jest zadeklarowany jako „ostatni” albo „nie wiem”, zmiana przy zachowanej
    dostępności jest w ten sam sposób możliwym restartem, do 3 razy w ciągu 24 h. W przeciwnym
    razie zmiana na inny stan przy zachowanej dostępności — automatyka, człowiek, jego własny
    przycisk — liczy się jako inny sterownik: jest zapisywana raz ponownie, potem wtyczka ustępuje,
    nigdy nie walcząc (odpowiedzi C, D, N).
  - Przekaźnik, który raportuje stan i w tej sesji pokazał polecenie wtyczki, a potem nie pokazuje go
    przez 3 kolejne kontrole (około 15 min; tymczasowe, K4), przestał przyjmować polecenia:
    zgłoszenie naprawy na poziomie błędu; gdy poleceniem jest „wyłączony”, sterowanie jest też
    blokowane, a przekaźnik oddany, tak jak robi to odpowiedź O, a powiadomienie mówi, że kocioł
    może dalej grzać; gdy jest nim „włączony”, zgłoszenie mówi, że dom nie jest ogrzewany, a
    polecenie jest wysyłane ponownie przy każdej kontroli. Przekaźnik, który pokazuje polecenie, a
    potem wraca, to zmiana widziana na przekaźniku, jak wyżej (decyzja 6 z
    `docs/en/development/plans/plan-0.2.3.md`).
  - Przy oddaniu sterowania przekaźnik przechodzi do stanu spoczynku wybranego przez użytkownika:
    domyślnie „wyłączony”, „włączony” tylko wtedy, gdy użytkownik go wybrał, z tekstem o ryzyku;
    pojawia się powiadomienie, gdy „wyłączony” zostawia dom bez ogrzewania, podczas gdy jakaś strefa
    prosi o ciepło albo działa ochrona przed mrozem. Ustąpienie ustawia przekaźnik raz w stan
    spoczynku, a potem zostawia go w spokoju (odpowiedź L); dla przekaźników nie ma powrotu
    samoczynnego. Poza tym oddanie sterowania nigdy nie włącza przekaźnika.
  - Planowy restart Home Assistanta: stan spoczynku przy zatrzymaniu, potem od razu przywrócone
    ostatnie polecenie przy starcie, bez opóźnienia włączenia.
  - Opcjonalny dowód, że kocioł grzeje — temperatura rury zasilającej, moc elektryczna kotła, licznik
    gazu — jest tylko informacją, oceniany w ciągu 30 min po „włączony” (tymczasowe, K4); bez niego
    status mówi „sterowany bez potwierdzenia, że kocioł grzeje”.
  - Przejście z VT: przekaźnik (tam, gdzie polecenia VT wskazują przełącznik albo encję termostatu
    kotła; w przeciwnym razie wybiera go użytkownik), opóźnienie włączenia, odstęp powtarzania
    (tylko tam, gdzie podtrzymanie VT mieści się w 10–300 s) i próg mocy w takiej postaci, jak
    zaokrąglił go VT, są wstępnie wypełniane, zanim użytkownik odznaczy centralny kocioł VT,
    ponieważ VT wtedy je usuwa; próg liczby urządzeń z VT jest wstępnie wypełniany tylko tam, gdzie
    każda strefa ma jedno urządzenie grzewcze (tymczasowe, K4), a 0 — liczenie wyłączone, jak
    używał go VT — tam, gdzie liczba w VT wynosi 0 obok progu mocy (decyzja 7 z
    `docs/en/development/plans/plan-0.2.3.md`). Sterowanie czeka na restart Home Assistanta,
    którego potrzebuje VT — także wtedy, gdy centralny wpis VT zmienił się w tym uruchomieniu Home
    Assistanta, zanim wpis wtyczki zaczął obserwować VT, albo gdy czujnik centralnego kotła VT jest
    zastępczym czujnikiem zapisanym w tym uruchomieniu, podczas gdy wpis mówi, że jest wyłączony
    (decyzja 9 z `docs/en/development/plans/plan-0.2.3.md`).
  - Teksty konfiguracji podają fakty, bez porad dotyczących okablowania (I8 C4): jeśli Home
    Assistant się zatrzyma, przekaźnik zostaje taki, jaki był, i można go przełączyć ręcznie w jego
    własnej aplikacji albo na jego stronie; przekaźnik w zasilaniu kotła odcina też wybieg pompy i
    ochronę przed mrozem; zaciski termostatu pokojowego mogą mieć napięcie sieciowe; przekaźnik
    Zigbee może wyglądać na dostępny jeszcze długo po awarii; własny czasomierz wyłączenia
    przekaźnika, odnawiany każdym „włączony”, jest ustawiany dopiero po starcie sterowania — czy
    czasomierz Shelly uruchamia się od nowa przy powtórzonym „włączony”, nie jest udokumentowane.
- Drugi obieg sterowany przez kocioł (np. OpenTherm CH2) pojawi się później. Wersja 0.2 steruje
  najwyżej jednym obiegiem zasilanym prosto z kotła, a obok niego mogą być obiegi za stałym
  zaworem albo sterowane przez inną automatykę (w sumie do czterech; I8, decyzja F6): obieg, który
  miesza kocioł, albo drugi zasilany prosto z kotła, zostawia działający monitor, a blokada mówi,
  dlaczego. Jedna krzywa, w opcjach sterowania, obsługuje obieg zasilany prosto z kotła — a gdy go
  nie ma, pierwszy obieg; korekta komfortu i temperatura pokojowa krzywej (Auto) odczytują strefy
  tego obiegu, a wszystkie strefy tam, gdzie jest to jedyny obieg albo nie ma żadnego. Woda to
  krzywa, nigdy poniżej potrzeby obiegu sterowanego przez inną automatykę, dopóki ten prosi o ciepło
  — nic nie jest dodawane; stały zawór nie ustala dolnej granicy, stoi otwarty, dopóki woda jest
  równa jego nastawie lub niższa (decyzja użytkownika z 2026-10-14: mieszacz albo zawór nie musi
  mieszać cały czas); najwyższa temperatura wody obiegów zasilanych prosto z kotła (70 °C tam, gdzie
  pusta albo gdzie ich nie ma) i maksimum kotła ją ograniczają — obieg za mieszaczem albo stałym
  zaworem jest przez nie chroniony, a jego alarm „za gorąco” o tym informuje (odpowiedzi
  użytkownika z 2026-10-12). Krzywe dla każdego obiegu przyjdą razem z CH2.

### Topologia bramki

Sposób ustawienia bramki decyduje o tym, co wtyczka może robić i do czego prowadzi oddanie
sterowania. Inne bramki mają podobne warianty (DIYLess i ESPHome jako master albo przelotowo;
EMS-ESP z regulatorem albo bez). F3 ustaliło, że ani trybu OTGW, ani podłączonego termostatu nie da
się wiarygodnie odczytać przez Home Assistant (tryb jest odczytywany tylko wtedy, gdy bramka się
łączy; nie ma encji obecności).

| Tryb bramki | Termostat | Kto steruje kotłem | Co wtyczka może robić | Oddanie sterowania prowadzi do |
|---|---|---|---|---|
| monitor | fizyczny | termostat; bramka tylko słucha | tylko monitorowanie | — |
| gateway | termostat OpenTherm | termostat; bramka może nadpisać jego wartości | nastawa zasilania (nadpisanie `CS`) albo, od 0.3, tryb jak termostat (nadpisanie temperatury pokojowej i nastawy termostatu) | nadpisania zdjęte — termostat przejmuje, grzanie trwa |
| gateway | styk włącz/wyłącz albo „nie wiem” | styk, przez bramkę | tylko monitorowanie — sterowanie zablokowane (decyzja 1) | — |
| gateway | brak | bramka działa jako master | nastawa zasilania; od 0.3 tryb jak termostat (wstrzykiwany przez `AA`), jeśli kocioł grzeje na własnej regulacji bez `CS` | nadpisania zdjęte — grzanie się zatrzymuje |
| monitor | brak | nikt | nic | — |
| — | wirtualny — sterownik po stronie HA (np. DIYLess albo ESPHome jako master) | ten sterownik | przez jego encje: nastawa zasilania, jeśli ją udostępnia, od 0.3 wartości trybu jak termostat, jeśli ma własny regulator | sposób wybrany przez użytkownika dla jego encji |
| — | przekaźnik (klasa 3), opcjonalnie stary termostat równolegle | wtyczka, przez przekaźnik | tylko włączanie i wyłączanie grzania | zadeklarowany stan spoczynku: „wyłączony” — grzanie się zatrzymuje, chyba że grzeje stary termostat równolegle; „włączony” — kocioł grzeje według własnego pokrętła albo termostatu |

- Topologia jest częścią konfiguracji, deklarowaną przez użytkownika w pozycji „Interfejs kotła”
  (F3: nie da się jej odczytać przez Home Assistant; I8 D2), która oferuje tylko te topologie,
  przez które ścieżka zapisu połączenia może sterować — sterownik po stronie Home Assistanta
  (ESPHome, EMS-ESP) jest wirtualny bez pytania — i pokazuje się ponownie razem z pytaniem o
  zaciski termostatu tam, gdzie topologia bramki je ma.
- W każdej topologii po oddaniu sterowania albo gdy Home Assistant nie działa, woda podlega
  własnemu maksimum kotła lub termostatu ściennego, a nie maksimum obiegu wtyczki: niemieszana
  pętla ogrzewania podłogowego opiera się wtedy tylko na tym maksimum, więc jest ono ustawiane także
  tam (§5, bezpieczne oddanie sterowania).
- Obie topologie bramki — z termostatem i samodzielna — pytają, co jest podłączone do zacisków
  termostatu bramki: termostat OpenTherm, styk włącz/wyłącz, nic albo „nie wiem” (decyzja 1).
  Sterowanie jest zablokowane dla styku włącz/wyłącz i dla „nie wiem”: bramka utrzymuje `CH=0`
  mimo `CS=0` i wygaśnięcia nadpisania, więc po awarii w stanie „wyłączone” termostat włącz/wyłącz
  nie mógłby ogrzać domu. Monitor działa jak dotąd. Odpowiedź sprzeczna z topologią — termostat
  OpenTherm przy topologii samodzielnej, nic przy topologii z termostatem — jest odrzucana w
  formularzu z podpowiedzią, by wybrać drugą topologię. Wpis bramki utworzony przed 0.2.2, bez tej
  odpowiedzi, ma sterowanie zatrzymane, z powiadomieniem z prośbą o nią (odpowiedź K). „Wyłączone”
  jako niska `CS` z pozostawieniem `CH`, dla takich instalacji, czeka na użytkownika w K4
  (decyzja 11).
- Tryby sterowania, na które topologia nie pozwala, są niedostępne, z pokazaną przyczyną.
- Oddanie sterowania zatrzymuje zapotrzebowanie wtyczki na grzanie. Bez termostatu grzanie stoi,
  dopóki wtyczka albo użytkownik czegoś nie zrobi; kreator konfiguracji mówi o tym ryzyku, a po
  oddaniu sterowania w pracy samodzielnej przełącznik sterowania mówi, że ochrona przed mrozem
  opiera się teraz na własnej ochronie kotła, jeśli ją ma; alarm „oddane przy mrozie” włącza się,
  gdy obserwowana strefa pokazuje poniżej granicy mrozu, i gaśnie na poziomie zwolnienia albo
  powyżej (S-57; tymczasowe, K4). Utrata łączności z kotłem nie jest wyjątkiem: w każdej topologii
  bramki wywołuje alarm i sterowanie jest oddawane — w pracy samodzielnej grzanie się zatrzymuje
  (decyzja użytkownika z 2026-09-25). Wyjątkiem jest przekaźnik: alarm, bez oddania sterowania (§5,
  klasa 3).
- Wtyczka nigdy sama nie zmienia trybu bramki; bramka zapamiętuje swój tryb na stałe (F3).
  Oddanie sterowania OTGW to bezpieczne oddanie sterowania: `CS` na najniższą temperaturę wody,
  `CH=1`, potem `CS=0`.
- **Termostat ścienny na bramce** nie jest synchronizowany w 0.2.2. Teksty formularza mówią, że gdy
  wtyczka steruje, ustawienie grzania termostatu ściennego i jego przycisk wyłączenia nic nie robią
  (jego ustawienia c.w.u. nadal działają), a po oddaniu sterowania albo awarii Home Assistanta
  grzeje według własnego ustawienia i programu. Wtyczka pokazuje temperaturę, jaką termostat
  ścienny utrzymywałby po oddaniu sterowania, z opcjonalnego sygnału „nastawa termostatu
  przewodowego”, i ostrzega, gdy ta wartość jest nieznana albo niższa niż 15 °C (tymczasowe, K4).
  Strefa VT zbudowana na własnej encji termostatu bramki jest odrzucana: wołałaby o ciepło,
  ilekroć pali się płomień. Synchronizacja, z VT jako nadrzędnym i domyślnie wyłączona, pojawi się
  najwcześniej w 0.3.
- Bez termostatu awaria HA dłuższa niż około minuty zatrzymuje grzanie: `CS` wygasa (F3); kreator
  konfiguracji i przełącznik sterowania o tym mówią.
- Emulowany termostat OpenTherm wewnątrz wtyczki zostaje na później (§9).

### Topologia

Kocioł → obiegi → strefy. Jeden kocioł na instancję HA, w jednym wpisie; model danych od początku
obejmuje kilka obiegów.

### Obiegi i krzywe

Ogrzewanie podłogowe i grzejniki potrzebują różnych krzywych. Każdy obieg ma własną krzywą i limity
oraz przyjmuje typy odbiorników ciepła swoich stref (S-33); palnik jest wspólny.

| Sterowanie obiegiem | Przykład | Co robi wtyczka |
|---|---|---|
| Niemieszany, wspólny | grzejniki i ogrzewanie podłogowe na jednej pętli, bez zaworu mieszającego | jedna krzywa dla pętli, ograniczona przez najbardziej wrażliwy odbiornik ciepła (maksymalne zasilanie ogrzewania podłogowego) |
| Sterowany przez kocioł | OpenTherm CH2, EMS-ESP HC2, moduł mieszający kotła | własna krzywa i nastawa dla każdego obiegu; zasilanie kotła = największa potrzeba obiegu + zapas na mieszanie |
| Sterowany przez inną automatykę (mieszacz, pompa) | zewnętrzny sterownik mieszacza, mieszacz sterowany przez HA, osobny regulator pogodowy | grzeje, dopóki jego encja „obieg prosi o ciepło” jest włączona albo prosi któraś z jego stref — encja, której nie da się odczytać, o nic nie prosi, a stan sterowania mówi dlaczego; gdy prosi, utrzymuje wodę kotła na poziomie jego potrzeby lub wyżej (najpierw odczyt encji, w przeciwnym razie wpisana wartość), nic nie jest dodawane — potrzeba dotyczy odbiornika gorętszego niż krzywa, niezależnie od pogody (grzejnik nadmuchowy, nagrzewnica wentylacji, zasobnik), a nie podłogi za mieszaczem, przed czym formularz ostrzega raz (2026-10-14); nigdy nie steruje mieszaczem ani pompą (I8, decyzje F3, F6) |
| Bierny, stały | termostatyczny zawór mieszający | zadeklarowana stała temperatura, która mówi jego strefom, jaką wodę dostają; bez dolnej granicy zasilania kotła — obowiązuje krzywa, a zawór stoi otwarty przy swojej nastawie lub niżej (2026-10-14, zamiast nastawy + 5 K z S-42) |

- Każda strefa VT jest przypisana do obiegu w kreatorze; wybór strefy krytycznej odbywa się osobno
  dla każdego obiegu. Strefa zasilana przez dwa obiegi — grzejnik na jednym, pętla podłogowa na
  drugim — jest w każdym z nich przez własne urządzenia (I8.8b, I8.8c): obserwowana i liczona raz,
  jej ciepło dostępne przez któryś z nich; w obiegu sterowanym przez inną automatykę prosi o ciepło,
  dopóki VT pokazuje tam jako aktywne jedno z jej urządzeń, oraz w każdym z jej obiegów, w których
  VT nie mówi, które są aktywne (przyjmuje się stronę cieplejszą).
- Ochrona przed krótkimi cyklami, c.w.u. i limit modulacji działają na kocioł (wspólny palnik);
  strojenie krzywej, korekta komfortu i sezonowe dostrojenie działają dla każdego obiegu osobno.
- Kondensacja zależy od łącznego powrotu wszystkich obiegów.

### Algorytmy stref — dowolne

- Rdzeń używa tylko danych VT: `on_percent`, położenia zaworów, temperatura pokojowa względem celu,
  moc urządzeń.
- Wykrywane dodatki: SmartPI — wstrzymanie nauki i odczyt jego fazy nauki (G11 C); jego „lepszy
  sygnał” skreślony przez użytkownika 2026-10-12 (§9); Auto-TPI — wykrywany, nie wstrzymywany, ze
  zgłoszeniem naprawy (§11; S-29).
- Algorytm uczący się bez usługi wstrzymania dostaje wyraźne ostrzeżenie, które mówi, co kosztują
  jego rady.
- Dla każdej strefy wtyczka daje termostatowi VT, jako właściwości menedżera funkcji (menedżer
  funkcji od 0.2): **ciepło dostępne** (`heat_available`; przed 0.2.2 nazywane „ciepła woda
  dostępna”, P-61) — ciepło kotła dociera do strefy: tak, dopóki płomień się pali, a temperatura
  zasilania jest wyraźnie powyżej powrotu (powyżej pokoju, z szerszym marginesem, tylko tam, gdzie
  powrót nie jest znany: woda obiegu mieszanego wraca przez jego własne mieszanie, a instalacja może
  nie mieć przypisanego powrotu); nie, gdy płomień jest zgaszony albo c.w.u. jest aktywne na kotle,
  w którym c.w.u. ma priorytet; nieznane, gdy przypisany płomień, temperatura zasilania albo to, z
  czym się ją porównuje, jest nieznane lub nieświeże. Bez sygnału płomienia decyduje sama woda (I8,
  decyzja C1). Od I9 (decyzje użytkownika z 2026-10-12) wtyczka daje też **wodę docierającą do
  obiegu strefy**, z podaniem, dlaczego jej brakuje, kiedy ją zmierzono i dlaczego ciepło nie
  dociera do strefy — opcjonalny, jednokierunkowy interfejs dla algorytmów stref, dostępny także
  przez funkcję w `hass.data` i, zaokrąglony, w atrybucie `smart_boiler`
  (`docs/pl/specification/water-interface.md`). Algorytm strefy, który go używa, mówi o tym kluczem
  w `specific_states` VT i nie jest wtedy wstrzymywany z powodu wahnięcia wody; SmartPI 0.4.0 go
  nie używa. Żadna encja wtyczki nie należy do strefy, a strefa to nic więcej niż jej termostat,
  jej obieg, jej typ odbiornika ciepła i to, czy zamyka się po wyłączeniu: encje dla poszczególnych
  stref, moc i wykładnik odbiornika ciepła stref, „blisko temperatury pokojowej” z monitora (I8.1d)
  i współczynnik mocy odbiornika ciepła (I8.2) zostały usunięte
  (`docs/en/development/plans/plan-0.2-i8.md`).
- Ładowanie zasobnika c.w.u. wstrzymuje naukę tylko tam, gdzie c.w.u. ma priorytet (I6, decyzja 8),
  i tylko w strefach proszących o ciepło (zawór otwarty); strefy z zamkniętym zaworem uczą się dalej,
  jak pokój stygnie. Każdy pobór c.w.u. wstrzymuje ją, jakkolwiek krótki, także na kotle combi i
  także w ciągu 10 min od wznowienia, ponieważ strefy, które proszą o ciepło, w tym czasie go nie
  dostają (S-41); tak samo robi „wyłączone”, które sterowanie wysyła przy awarii kotła (§7). Nauka
  wznawia się, gdy temperatura zasilania wróci w granice tolerancji od swojej nastawy (3 K w obie
  strony), a najpóźniej 1 h po rozpoczęciu wstrzymania, nawet gdy jego przyczyna trwa (decyzja 14 z
  `docs/en/development/plans/plan-0.2.3.md`); wstrzymanie i wznowienie są odczytywane zwrotnie z
  flagi algorytmu — wstrzymanie, które się nie udało, nie jest wstrzymaniem wtyczki, wznowienie jest
  wysyłane ponownie co minutę, aż flaga pokaże „włączone” — a nauka, którą użytkownik wyłączył przed
  wstrzymaniem, nigdy nie jest wznawiana. Wyłączenia podczas własnego wstrzymania wtyczki nie da się
  odróżnić od tego wstrzymania: flaga pokazuje „wyłączone” w obu przypadkach.
- Domyślnie temperatura wody zmienia się stopniowo (rampa, §7): każdy krok nastawy jest na tyle mały,
  żeby kocioł jej nie przekroczył, a algorytmy stref za nią nadążają (S-47).

### Tryb jak termostat (0.3)

Postanowione przez użytkownika 2026-10-10 (`docs/en/development/plans/plan-0.2-i8.md` G; źródła:
`research/2026-10-10-room-values-mode-sources.md`). Ukryte w opcjach, dopóki nie działa: wpis, który
wcześniej wybrał „tylko temperaturę pokojową”, jest odczytywany jako tylko monitorowanie (I8.4a,
wersja podrzędna 14), co właśnie robił.

- Włączanie i wyłączanie grzania podąża za zapotrzebowaniem stref, jak w innych trybach; nigdy nie
  jest to porównanie temperatur.
- Liczą się tylko strefy, które teraz proszą o ciepło. Wygrywa ta, której brakuje najwięcej; jej cel
  to najwyższy ze znanych — nastawa VT, +0.5 K, gdy grzeje faza nauki SmartPI, nastawa opublikowana
  przez SmartPI. Strefa zmienia się tylko przy wyraźnej różnicy, a od razu, gdy przestaje prosić.
- Dopóki strefa prosi, kocioł widzi co najmniej minimalny niedobór — jego własna regulacja nigdy nie
  zatrzymuje grzania pokoju, który VT nadal grzeje (wartość tymczasowa, K4).
- Dwa rodzaje, do wyboru przez użytkownika według urządzenia: „temperatura i nastawa” (dwie encje
  albo OpenTherm ID 24 / 16 przez wbudowaną obsługę) albo „różnica” (jedna encja).
- Zaokrąglanie do 0.1 °C albo do kroku encji docelowej: niedobór w górę, temperatura w dół,
  nastawa ich suma — nigdy brak niedoboru, gdy strefa prosi.
- Zabezpieczenia: w realnych granicach temperatury pokojowej; wysyłane tylko przy zmianie i nie za
  często; czyszczone — nigdy zamrożone na ostatniej wartości — gdy brak ważnej strefy i przy oddaniu
  sterowania. Te wartości uwzględnia tylko kocioł z włączonym wpływem temperatury pokojowej, a
  wtedy zmienia razem z nimi swoją temperaturę zasilania — dlatego są strzeżone. To, co przyjmują
  ESPHome OpenTherm i EMS-ESP, jest sprawdzane przed planowaniem.

## 6. Dane i ich źródła

| Grupa | Przykłady |
|---|---|
| Specyfikacja kotła | połączenie, źródło ciepła, typ (jednofunkcyjny z zasobnikiem c.w.u. lub bez, combi, combi z zasobnikiem), priorytet c.w.u., moc min/maks, zakres modulacji, maksymalna nastawa c.o., kondensacja, granice ciśnienia wody, zużycie gazu min/maks |
| Ustawienia kotła (menu instalatora; później, §9 — S-60) | histereza c.o., czas ochrony przed krótkimi cyklami, wybieg pompy, próg letni, wbudowana krzywa |
| Instalacja | obiegi, typ obiegu (I8 F2: „sterowany przez inną automatykę” nazywał się wcześniej „mieszany przez osobny sterownik”), krzywa dla każdego obiegu, typy odbiorników ciepła, najwyższa temperatura wody każdego obiegu (dawne maksimum krzywej zostało w niej połączone), zawór mieszający, obejście |
| Budynek (cały dom, w kW; poziom zaawansowany, do statystyk — I8 E2) | projektowe obciążenie cieplne, próg grzania (do statystyk: nie włącza żadnego grzania) |

- Każdy parametr ma źródło i pewność, a jego źródło jest pokazane: domyślne dla klasy → wpisane
  przez użytkownika → zmierzone → nauczone. Wpis użytkownika zawsze wygrywa ze zmierzonymi i
  nauczonymi wartościami; nauka („zastosuj”, 0.3) zmienia wartość tylko w pasmie wokół niego
  (zasada 13, S-58). Niezgodność między wartościami zadeklarowanymi a zmierzonymi jest wynikiem
  diagnostycznym.
- Pole pokazuje się tylko tam, gdzie może działać, a już ustawiona wartość zostaje, gdy pole jest
  ukryte (I8 A3, E1, E4): maksymalna moc kotła i znaczenie modulacji — z sygnałem modulacji; jego
  zużycie gazu na godzinę przy minimalnej i maksymalnej mocy (m³/h, kg/h dla LPG, z danych
  technicznych w instrukcji) — z nim i bez licznika gazu; granice ciśnienia — z czujnikiem
  ciśnienia; obejście — z pompą albo sygnałem aktywnego grzania; najwyższa nastawa grzania — poza
  przekaźnikiem; powrót dla kondensacji — dla kotła kondensacyjnego z sygnałem powrotu; progi
  palenia i startów — z sygnałem płomienia. Zapisana wartość, której opcje nie przyjmują, jest
  pokazywana, żeby ją poprawić.
- Zwykli użytkownicy odpowiadają na to, czego potrzebuje ich instalacja; zaawansowani mogą wypełnić
  każde pole (§4). Wpis ręczny zawsze wygrywa; dane kotła odczytane z integracji tylko
  podpowiadają i czekają na potwierdzenie.
- Własny bilans cieplny użytkownika — obciążenie projektowe — daje straty ciepła budynku, jedyną
  wpisywaną ich wartość (wpisywany współczynnik strat stał się obciążeniem projektowym, które to
  daje; powierzchnia podłogi, izolacja i masa cieplna zniknęły, bo dawały tylko przybliżone reguły,
  których żadna funkcja nie potrzebowała — I8 B5); zapisane dni grzewcze je mierzą; szacunek z
  rachunków za gaz przyjdzie później.
- Model budynku to cały dom w kW — obciążenie kotła. Nie powiela modeli pokoju z algorytmów stref.
- Sygnały kotła wybiera się w jednym kroku (I8 D3–D7), w tym odczyty zwrotne sterowania: nastawa,
  którą otrzymał kocioł, to sygnał „nastawa c.o.”, wymagany do sterowania temperaturą wody, a
  włączanie i wyłączanie grzania w takiej postaci, w jakiej dostaje je kocioł, ma własne pole,
  o które pytamy tylko tam; krok sterowania już o nie nie pyta. Przekaźnik pyta najpierw „Czy
  odczytujesz kocioł także przez inną integrację?” — domyślnie Nie, Tak tam, gdzie taki sygnał jest
  już przypisany: Nie oferuje to, co odczytuje instalacja z przekaźnikiem — płomień, zasilanie,
  powrót, moc elektryczną kotła, licznik gazu, czujnik zewnętrzny i pogodę — a pozostałe sygnały
  kotła przypisane wcześniej są usuwane przy zapisie; Tak oferuje każdy sygnał. Temperatura
  zewnętrzna pochodzi z dowolnego czujnika zewnętrznego (własnego kotła, stacji pogodowej albo
  innego). Nastawa i temperatura pokojowa termostatu podłączonego do kotła albo do jego interfejsu
  są zapisywane na potrzeby oceny, dla każdego połączenia poza przekaźnikiem, przy którym kocioł
  nie jest odczytywany przez nic innego. Limit wieku należy tylko do przypisanego sygnału i znika
  razem z nim; przy przekaźniku limity oceniają tylko monitor — sterowanie przełącza przekaźnik
  według jego własnego stanu.

## 7. Funkcje według etapów

| Etap | Co daje | Steruje kotłem |
|---|---|---|
| **Monitor** | starty na godzinę, czas palenia, udział kondensacji, gaz na stopniodzień, stan łączności; alarmy — informacyjne, z reakcją w postaci oddania sterowania tylko tam, gdzie pozwala na nią decyzja 7 (§7); **wczesne ostrzeżenie** (spaliny, zapłony, ciśnienie, histereza); **długie palenie bez ocieplania** — płomień pali się 3 h, a temperatura w pokojach nie rośnie: woda za chłodna dla pokoi, którym brakuje ciepła, kocioł na granicy swojej mocy (ostrzeżenie), woda za gorąca (`docs/en/development/plans/plan-0.2-g11.md` E); **raport wyjaśniający zmiany** (pogoda / c.w.u. / ustawienia); kontrola czujnika zewnętrznego; wykrywanie c.w.u.; **zapis prognozy** (FC0); **kontrola sygnałów** — które opcjonalne sygnały są obecne i świeże | nie |
| **Doradca** | podpowiedzi dotyczące krzywej i ochrony przed częstymi startami, z uzasadnieniem i przyciskiem „zastosuj” | nie |
| **Krzywa (strategia A)** | zastępuje włącz/wyłącz VT i automatyzacje użytkownika; krzywa dla każdego obiegu; efektywna temperatura zewnętrzna; rampa; podtrzymanie; ochrona przed mrozem; wstrzymania nauki (c.w.u., awaria kotła, duże zmiany — tylko pod sterowaniem, S-61) | tak |
| **Ochrona przed częstymi startami** (do rozstrzygnięcia wobec zasady 12, decyzja 13) | praca cyklami przy małym obciążeniu, limit startów na godzinę, ograniczenie modulacji; **planowanie według prognozy** — przed nami łagodne godziny → długie cykle od początku (FC2) | tak |
| **Strojenie krzywej (strategia B)** | pasmo strojenia Niskie / Średnie / Wysokie / Własne (domyślnie 3 / 8 / 15 %); ręczne / półautomatyczne / automatyczne; **sezonowe dostrajanie** — każdego dnia trochę niżej, dopóki pokoje trzymają komfort; dla każdego obiegu | tak |
| **Prognoza** | **wyprzedzanie dla wolnych odbiorników ciepła** — podnieść wodę wcześniej przed mrozem, obniżyć ją wcześniej przed ciepłym lub słonecznym dniem (FC3); czas wyprzedzenia uczony dla każdego obiegu | tak |
| **C.w.u.** (opcjonalnie, tylko z zasobnikiem) | szybkie ładowanie, harmonogram dopasowany do okien nauki | tak |

**We wszystkich etapach**

- **Nauka po stronie wody:** z historii HA, gdy obejmuje sezon grzewczy, potem na żywo; zmiana
  ograniczona na dobę.
- **Obce ciepło** (kominek, piec, grzejnik elektryczny) obsługują VT i SmartPI: wtyczka go nie
  wykrywa i nie wstrzymuje dla niego nauki (I8.1c, decyzja użytkownika z 2026-10-10). Pokój, który
  ono ogrzewa, nie prosi o ciepło.
- **C.w.u.** jest wykrywane na każdym etapie; pod sterowaniem wstrzymuje naukę — w strefach
  wołających o ciepło (§5) — i przy każdym poborze trzyma korektę komfortu wtyczki w miejscu (S-61).

**Podstawa sterowania — od pierwszego wydania ze sterowaniem**

**Brakujące dane** (zasada użytkownika z 2026-09-26/27). Większość instalacji dostarcza tylko część
danych wejściowych; każda funkcja działa z tym, co ma.

- Funkcja, której brakuje danych wejściowych albo które są nieznane lub niedostępne, jest pokazana
  jako nieaktywna i w przetłumaczonym tekście podaje, czego jej brakuje.
- Brak danych sam nigdy nie wyłącza grzania i sam nigdy nie blokuje kotła — z wyjątkiem danych
  łączności z kotłem: gdy nie są świeże, nic się nie zapisuje (zasada 12, wyjątek 7).
- Ustawienie, którego formularz wymaga przed startem sterowania, może zostawić sterowanie
  niedostępne: zaciski termostatu (decyzja 1), nadający się do użycia włącznik grzania (decyzja 11),
  zaznaczenie przekaźnika „osobny styk” (odpowiedź G) oraz, dla wpisu bramki zrobionego przed 0.2.2,
  odpowiedź o jej zaciskach termostatu (odpowiedź K: sterowanie pozostaje zatrzymane, z komunikatem
  z prośbą o tę odpowiedź). Działa wtedy monitor, a kocioł zostaje przy własnym sterowaniu lub
  termostacie — to nie jest wyłączenie grzania z powodu braku danych.
- Gdy dana wejściowa znika, kiedy wtyczka steruje, funkcja, która jej używa, staje się nieaktywna,
  a sterowanie trwa z tym, co zostało; na przykład kryterium zapotrzebowania, któremu żadna strefa
  nie może dostarczać danych, liczy się jako brak danych.
- Jedna encja przypisana do dwóch sygnałów: zatrzymuje ją pierwszy sygnał, a późniejszy odpada
  (nieaktywny, z podaną nazwą); sterowanie dostaje blokadę, a formularz tego odmawia — nigdy błąd,
  który zatrzymuje wpis, dzięki czemu monitor i należne oddanie sterowania działają dalej.
- Dwa wymienione wyjątki od zasady 12 zatrzymują grzanie przy braku danych: utrata łączności
  z kotłem (oddanie sterowania po 5 min, które w układzie samodzielnym zatrzymuje grzanie;
  przekaźnik dostaje alarm i nie oddaje sterowania) oraz każda strefa VT wciąż nieznana po okresie
  karencji albo brak skonfigurowanego kryterium zapotrzebowania, które da się ocenić, gdy nie ma
  działającego termostatu (niżej).
- Instalacja, która nie daje żadnego potwierdzenia — ani sygnałów kotła, ani własnego zgłaszanego
  stanu przekaźnika — dostaje tylko monitor. Wyjątkiem jest przekaźnik, który nie zgłasza własnego
  stanu: jest sterowany ślepymi powtórzeniami i pokazany jako „sterowany bez potwierdzenia”.

Jak sterowanie podejmuje decyzje (zasada 12):

- Grzanie włącza się i wyłącza razem z zapotrzebowaniem stref przy każdym kroku sterowania (10 s),
  natychmiast i w obu kierunkach. Odstęp decyzji (opcja, domyślnie 5 min) dotyczy tylko temperatury
  wody.
- Zapotrzebowanie pochodzi ze stref wołających — stref VT porównywanych z progami: liczba
  wołających, łączna moc, otwarcie zaworu — każdy próg można stosować osobno lub razem z innymi, tak
  jak w VT, i jest sprawdzany względem skonfigurowanych stref. Liczba obejmuje urządzenia VT
  (głowice, zawory, przełączniki), tak jak robi to centralny kocioł VT, albo strefy — według wyboru
  użytkownika (decyzja użytkownika z 2026-10-14; dla nowej instalacji domyślnie urządzenia, wpis
  sprzed zmiany zostaje przy strefach): własna liczba VT jest wstępnie wypełniona tak, jak jest dla
  urządzeń, a dla stref tylko tam, gdzie każda strefa ma jedno urządzenie grzewcze (S-36), albo
  jako 0, gdzie VT nie używał liczby (§5, przejście z VT); liczba urządzeń nigdy nie żąda więcej,
  niż napędzają znane strefy. Jej źródło zależy od typu VT (otwarcie zaworu, stan urządzenia w VT,
  akcja grzania) i uwzględnia minimalny czas włączenia VT; tam, gdzie VT nie podaje stanu
  urządzenia, obowiązuje reguła samego VT: zawór otwarty choćby w niewielkim stopniu, a bez zaworu
  cykl pracy powyżej 0 — otwarcie zaworu i cykl pracy strefy oceniane każde osobno (2026-10-14,
  zamiast wspólnych 5 %). Strefy z przełącznikiem idą za stanem urządzenia w VT, więc kocioł może
  startować raz na cykl TPI (S-38). Kryterium mocy, dla każdej ścieżki zapisu, bierze średnią moc
  strefy w jej cyklu, tak jak liczy ją VT, ale tylko wtedy, gdy przynajmniej jedna wołająca strefa
  ma otwarty zawór lub aktywne urządzenie; moc urządzenia w VT równa 0 lub mniejsza to brak danych,
  a kryterium, któremu żadna strefa nie może dostarczać danych, formularz odrzuca. Próg otwarcia
  liczy tylko strefy wołające. Kryterium nie ma danych, gdy żadna strefa w trybie grzania nie może
  go zasilać, niezależnie od tego, czy strefa woła — strefa zasila kryterium mocy, dopóki VT
  publikuje moc jej urządzenia powyżej 0 albo jej średnią moc cyklu, a kryterium otwarcia, dopóki
  publikuje otwarcie; gdy żadna strefa nie jest w trybie grzania, nie ma zapotrzebowania. Gdy
  liczba wynosi 0, formularz odrzuca strefę, która nie może zasilać żadnego z pozostałych kryteriów,
  a wołająca strefa, która nie zasila żadnego z nich, jest wskazana alarmem „kryterium
  zapotrzebowania nie ma danych” (decyzja 3 z `docs/en/development/plans/plan-0.2.3.md`, PB-23).
  Sterowanie potrzebuje co najmniej jednej strefy VT (S-04).
- Strefa liczy się tylko wtedy, gdy jej stan jest znany: encja climate VT, która jest
  `unavailable` albo której tryb jest nieznany, jest nieznana — nigdy „bez zapotrzebowania”. Tak
  samo termostat, którego VT nie uruchomił, także po okresie rozpoznania: `is_ready` nie jest
  prawdą albo nie ma ani `is_ready`, ani `specific_states` z VT (VT 10.4.0 zapisuje je dopiero
  wtedy, gdy jedno z jego urządzeń się zgłosi). VT pokazuje taki termostat jako „off” (ten typu
  over_valve może pokazać „heat”) do czasu uruchomienia i utrzymuje go tak, gdy jedno z jego
  urządzeń jest niedostępne (decyzja 1 z `docs/en/development/plans/plan-0.2.3.md`). Uruchomiona
  strefa, której tryb to „off”, nie ma zapotrzebowania (S-34). Zrzut mocy zdejmuje zapotrzebowanie
  strefy. Strefa w trybie „auto” lub heat_cool grzeje według swojej akcji grzania i cyklu pracy.
- **Okres rozpoznania** (decyzja 3): po starcie Home Assistanta albo przeładowaniu VT, aż każda
  skonfigurowana strefa się zgłosi — VT pokazuje ją jako uruchomioną, a jej tryb i zapotrzebowanie
  są znane — najwyżej 10 min. W tym czasie nie zapada żadna nowa decyzja. Jeśli wtyczka sterowała
  kotłem przed restartem — także po czystym restarcie, który oddał sterowanie — jej ostatnie
  polecenie jest zachowane albo od razu przywrócone, razem z podtrzymaniami, gdy zapamiętane
  życzenie to „sterowanie włączone”, encja przełącznika sterowania nie jest wyłączona,
  nie trzyma się żaden zatrzask ani błąd wewnętrzny, opcje sterowania są takie same jak te, z którymi
  przejęto sterowanie, i nie trzyma się żadna inna blokada; dopóki cel zapisu i łączność z kotłem
  nie są dostępne, nic się nie zapisuje, a przywrócenie czeka, i łączność, która jeszcze się nie
  zgłosiła, nigdy nie zamienia przywrócenia w oddanie sterowania. Gdy któryś warunek zawodzi,
  najpierw następuje należne oddanie sterowania; tam, gdzie sterowanie nie trzymało kotła, wtyczka
  czeka. Utracony lub uszkodzony magazyn danych: wtyczka zakłada, że sterowała, i najpierw oddaje
  sterowanie (odpowiedź K). Przywrócone polecenie nie dostaje opóźnienia włączenia. Ochrona przed
  mrozem działa dla stref już znanych (tymczasowo, K4); start przeciwmrozowy wyłączonego kotła nadal
  czeka na opóźnienie włączenia VT, które liczy się od końca okresu rozpoznania.
- **Okres karencji:** strefa, która staje się nieznana, gdy VT działa, zachowuje swoją ostatnią
  odpowiedź przez 10 min; potem odpada i decydują strefy znane (to zmienia N3 z 2026-09-25). Strefa
  wciąż nieznana, gdy kończy się okres rozpoznania, nie ma ostatniej odpowiedzi i odpada od razu.
  Karencja obejmuje też blokadę „centralny kocioł VT nieznany” podczas przeładowania VT, gdy tuż
  przed nim centralny kocioł VT był znany jako wyłączony (P-105). Strefa nieznana dłużej niż limit
  podnosi alarm, bo ochrona przed mrozem jej nie widzi. Tak samo strefa, której czujnik pokojowy —
  wskazany we wpisie VT — zniknął, jest niedostępny lub nieznany tak długo, albo której `safety_state`
  w VT jest włączony (S-35): VT zachowuje ostatnią temperaturę, a jej zapotrzebowanie liczy się tak,
  jak pokazuje je VT — VT 10.4.0 w trybie bezpieczeństwa wyłącza strefę over_climate oraz strefę,
  której cykl pracy w trybie bezpieczeństwa wynosi 0 (brak zapotrzebowania), a pozostałe prowadzi
  z ich cyklem pracy w trybie bezpieczeństwa (`state_manager.py`). Nierealna temperatura pokojowa
  obserwowanej strefy jest nieznana, z tym samym alarmem po jej limicie; jedna reguła wiarygodności
  obsługuje każdy odczyt pokoju, od −30 do 45 °C (S-06; tymczasowo, K4).
- **Każda strefa nieznana** po tym czasie albo brak skonfigurowanego kryterium zapotrzebowania,
  które da się ocenić: nic nie prosi o ciepło (decyzja 3). Gdy jest **działający termostat**,
  kocioł jest mu oddany albo własnemu sterowaniu kotła. Działający termostat to: bramka
  z termostatem OpenTherm zadeklarowanym na jej zaciskach; ścieżka encji z zaznaczeniem „kocioł ma
  własny regulator pokojowy” (na przykład regulator pokojowy EMS na magistrali); albo ścieżka
  przekaźnika z tym zaznaczeniem i stanem spoczynku „on” (przekaźnik jest stykiem wezwania do
  grzania kotła). Nic innego się nie liczy: nie przekaźnik spoczywający w „on” bez zaznaczenia, nie
  zaznaczenie ze stanem spoczynku „off”, nie wartość oddania sterowania określona jako „wznawia się
  własne sterowanie urządzenia” bez zaznaczenia. Zaznaczenie nie jest oferowane przy bramce
  (odpowiedzi F, M). Bez działającego termostatu wtyczka nie grzeje — jej zwykłe „wyłączone”, dla
  przekaźnika przekaźnik wyłączony, nigdy jego stan spoczynku — bez oddania sterowania. Tak czy
  inaczej alarm „żadna strefa nie jest znana” i zgłoszenie naprawy pojawiają się od razu, także przy
  samym monitorze — błąd tam, gdzie grzanie się zatrzymuje, ostrzeżenie po oddaniu sterowania albo
  przy samym monitorze; tam, gdzie strefy są znane, ale żadnego kryterium nie da się ocenić,
  zgłoszenie podaje to kryterium (decyzja 3 z `docs/en/development/plans/plan-0.2.3.md`) — a sterowanie
  wznawia się samo, gdy strefa znów odpowie albo kryterium znów ma dane (po oddaniu sterowania:
  tymczasowo, K4). To zastępuje „grzej według krzywej, gdy żadna strefa nie jest znana”, bez względu
  na temperaturę zewnętrzną.
- Tryb centralny VT (Auto, Stopped, Heat only, Cool only, Frost protection) działa przez strefy: VT
  stosuje go tylko do termostatów, które za nim idą, wtyczka widzi skutek w zapotrzebowaniu każdej
  strefy, a strefy poza trybem centralnym nadal się liczą. „Stopped” to nie oddanie sterowania:
  sterowanie trwa, a gdy każda strefa jest zatrzymana, nie ma zapotrzebowania, więc grzanie
  pozostaje wyłączone, a ochrona przed mrozem nadal czuwa (decyzja użytkownika z 2026-09-25).
- Lato i zima pochodzą z VT: wtyczka nie ma własnego przełącznika lata. Gdy strefy VT są
  wyłączone, nie grzeje; gdy jakaś strefa woła, grzeje. Monitor trzyma próg grzewczy budynku, do
  liczenia stopniodni.
- **Ochrona przed mrozem** (decyzja 4) grzeje bez wezwania ze strony VT: gdy obserwowana strefa —
  każda strefa (domyślnie) albo jedna strefa wybrana przez użytkownika — spada poniżej limitu mrozu,
  grzanie idzie według krzywej, aż strefa wróci powyżej temperatury zakończenia, ale tylko dla
  zimnej strefy, której odbiornik ciepła może przyjąć ciepło: VT zgłasza otwarcie powyżej 0 albo
  aktywne urządzenie; sam tryb nie wystarcza. Strefa, której stanu zaworu nie da się odczytać, jest
  ogrzewana jak dotąd; opcja przy strefie „zamyka się, gdy VT ją wyłącza” (domyślnie wyłączona)
  sprawia, że strefa liczy się jako zamknięta, dopóki VT ma ją wyłączoną. Zimna strefa, którą VT
  trzyma zamkniętą, od razu podnosi zgłoszenie naprawy na poziomie błędu (gdy sterowanie jest
  skonfigurowane i włączone; tymczasowo, K4) i nie uruchamia kotła: podaje pokój i jego temperaturę,
  mówi, dlaczego wtyczka nie może go ogrzać i co zrobić, w słowach dobranych do powodu zamknięcia
  podanego przez VT (`hvac_off_reason`) — dla „off” zamiast tego preset ochrony przed mrozem VT; dla
  otwartego okna albo trybu centralnego VT „Stopped” — że pokój zostaje nieogrzewany, dopóki VT go
  nie otworzy; centralny tryb ochrony przed mrozem VT wymaga temperatury ochrony przed mrozem
  w każdym termostacie. Wtyczka nigdy nie zmienia trybu VT. Grzanie przeciwmrozowe, które trwa bez
  ocieplania się strefy, podnosi alarm; nie jest zatrzymywane. Grzanie przeciwmrozowe czeka na
  opóźnienie włączenia. To zmienia decyzję z 2026-09-25 („siatka bezpieczeństwa obejmuje cały dom”).
- **Opóźnienie włączenia VT** (decyzja 5), przeniesione tak jak w VT 10.4.0: 0–600 s co 10 s,
  domyślnie 0, także na ścieżce przekaźnika. Opóźnia tylko włączanie. Czekanie zaczyna się przy
  pierwszym prawdziwym wezwaniu do grzania, po okresie rozpoznania; wezwanie, które znika i wraca
  w czasie czekania, ani go nie anuluje, ani nie zaczyna od nowa, a na jego końcu kocioł rusza tylko
  wtedy, gdy zapotrzebowanie nadal jest. Wyłączenie pracującego kotła jest natychmiastowe; oddanie
  sterowania, wyłączenie sterowania albo blokada anulują oczekujący start. Bez opóźnienia, gdy
  wtyczka sterowała kotłem przed restartem. Jest wstępnie wypełnione zapisaną wartością z VT
  i pokazane do potwierdzenia. Jego tekst o ryzyku wymienia impulsy TPI krótsze niż opóźnienie oraz
  pompę, która może mimo to pracować bez włącznika grzania.
- Temperatura wody idzie za krzywą według efektywnej temperatury zewnętrznej, w granicach limitów,
  i zmienia się w tempie rampy, w K na minutę, przy każdym kroku. Rampa jest pomijana tylko dla
  limitów instalacji — najwyższej temperatury wody, obiegu, kotła — nie dla opadającej krzywej
  (S-23).
- **Najniższa temperatura wody** (decyzja 2; klucz `hard_min`) ogranicza krzywą od dołu, 10–50 °C,
  domyślnie 20 °C (tymczasowo, K4), ustawiana przez użytkownika jak ustawienie krzywej. Jej tekst
  wymienia oba ryzyka: za niska — kocioł w łagodną pogodę raz po raz sam się wyłącza, a w kotle
  niekondensacyjnym spaliny skraplają się w przewodzie spalinowym (wartość weź z jego instrukcji);
  za wysoka — woda cieplejsza, niż potrzebują pokoje. Wersja 0.2.2 tylko podpowiada: monitor
  pokazuje swoje dowody krótkiego palenia przy tej temperaturze oraz podpowiedzianą wartość —
  odniesienie + 2 K, zaokrąglone w górę do 0.5 °C i trzymane poniżej górnych limitów (tymczasowo,
  K4) — którą wpisuje użytkownik; szacunek „około” z minimalnej mocy kotła — temperatura zasilania
  z krzywej tam, gdzie odbiorniki ciepła oddają tę moc — jest pokazany obok niej tylko wtedy, gdy
  istnieją minimalna moc, wpisane lub z dużą pewnością zmierzone obciążenie projektowe i wpisana
  krzywa, nigdy dla kotła niekondensacyjnego (Q3.4; tymczasowo, K4). Nic nie zmienia się samo;
  „zastosuj” pojawi się w 0.3. Tam, gdzie temperaturę wody ustala własna krzywa kotła, wtyczka tylko
  podpowiada, w słowach dobranych do urządzenia, które ją ustala, nigdy jako równoległe przesunięcie
  tej krzywej; brak podpowiedzi, gdy sterowanie w samodzielnej instalacji jest oddane.
- **Maksimum obiegu** ogranicza nastawę; kocioł może ją przekroczyć, i mówi o tym tekst opcji.
  Alarm informacyjny pojawia się, gdy zmierzona temperatura zasilania przez pewien czas utrzymuje
  się powyżej temperatury alarmowej; obie wartości to ustawienia użytkownika na poziomie
  zaawansowanym, wstępnie wypełnione maksimum obiegu + 5 K i 10 min (decyzja 10). Potrzebuje
  odczytu temperatury zasilania oraz obiegu z maksimum; bez nich jest nieaktywny. W obiegu
  zasilanym prosto z kotła i mierzonym zasilaniem kotła nie liczy czasu, gdy pracuje c.w.u.
  z priorytetem: obieg nie dostaje wtedy nic z tej wody (decyzja użytkownika z 2026-10-12); gdy nie
  wiadomo, czy c.w.u. pracuje, czas jest liczony, więc prawdziwe przegrzanie nie zostanie pominięte.
- Temperatura zewnętrzna pochodzi z czujnika zewnętrznego, a gdy go nie ma — z encji pogody;
  czujnik, który utknął, jest zastępowany w ten sam sposób, z alarmem, a czujnik odbiegający od
  encji pogody ustępuje jej tylko wtedy, gdy encja pogody pokazuje zimniej — zimniejsza wartość
  prosi o więcej ciepła, które zawory ograniczają — oraz, bez odczytu pogody, tam, gdzie kontrola
  widziała, że czujnik pokazuje cieplej (decyzja 12). Gdy nie ma żadnego z nich, ostatnia
  efektywna temperatura zewnętrzna obowiązuje przez 3 h, potem zastępuje ją stała wartość awaryjna
  użytkownika albo projektowa temperatura zasilania (decyzja 9).
- **Korekta komfortu** (zasada 13; domyślnie włączona przy pełnym sterowaniu — decyzja użytkownika
  z 2026-10-10, odwracająca decyzję z 2026-10-03; wpis po aktualizacji zachowuje to, z czym działał,
  „wyłączona” tam, gdzie nigdy nie zapisał odpowiedzi; nie przy sterowaniu włącz/wyłącz;
  `docs/en/development/plans/plan-0.2-g11.md` B): gdy zawór strefy jest w pełni otwarty, a pokój
  wciąż nie dochodzi do nastawy, woda rośnie ponad krzywą — najwyżej o limit użytkownika (domyślnie
  3 K, do 10 K; jedyna granica ponad krzywą, odkąd zniknął „zakres korekty”, I8 B6), nigdy więcej
  niż 3 K na dobę, po 1 K co 30 min i tylko gdy płynie ciepło: oceniane po płomieniu, gdy jest
  znany, w przeciwnym razie po poleceniu (S-24); opada dwa razy szybciej, a strefa bez danych
  o otwarciu nie blokuje opadania; liczą się tylko strefy biorące ciepło, a korekta nie rośnie, gdy
  inna strefa biorąca ciepło jest więcej niż 1 K powyżej swojej nastawy (S-08); zatrzymuje się
  w miejscu, gdy limit trzyma nastawę, i nie rośnie po cofnięciu zegara (S-25); rośnie tylko
  wtedy, gdy liczba startów na godzinę nie rośnie w porównaniu z tymi samymi godzinami sprzed jej
  początku, a cofa się o krok, gdy rośnie (gdy starty są nieznane, nie rośnie), a jej wzrost jest
  wstrzymany — opadanie nadal jest dozwolone — w ekstremalnej pogodzie, gdy temperatura zewnętrzna
  jest nieznana i w pierwszej godzinie po starcie (reguły 3 i 5 zasady 13; decyzja 11 z
  `docs/en/development/plans/plan-0.2.3.md`); jest zerowana przy oddaniu sterowania i na końcu
  sesji; jeden pokój, w którym brakuje ciepła, liczy się jak każdy inny — krzywa musi utrzymać każdy
  pokój — w tych granicach, nigdy wyżej ze względu na jeden pokój (dodatki 2 i 3 z 2026-10-10); gdy
  osiąga swój limit na 3 h, a w którymś pokoju wciąż brakuje ciepła, zostaje na limicie, a alarm
  informacyjny i zgłoszenie naprawy na poziomie ostrzeżenia wskazują pokój i możliwe przyczyny — za
  niska krzywa grzewcza, za mały grzejnik w pokoju, pokój traci ciepło; najpierw krzywa, gdy
  w większości pokoi brakuje ciepła, a najpierw grzejnik i utrata ciepła, gdy brakuje go w jednym —
  znikają, gdy korekta spadnie poniżej limitu albo w żadnym pokoju nie brakuje ciepła. Jej wartość
  jest publikowana, a przycisk „Zresetuj korektę komfortu” ją zeruje (odpowiedź J). Własne
  integratory PI stref (SmartPI, TPI) działają z nią szeregowo; dokumentacja opisuje to
  współdziałanie i zalecane przy nim ustawienia VT. Strefa, której SmartPI jest w fazie nauki
  (włącz/wyłącz, wyłączenie dopiero przy jej nastawie + 0.5 K), liczy się jako taka, której brakuje
  ciepła, względem nastawy VT + 0.5 K — tu, w regule długotrwałej i w strefie krytycznej; w
  kalibracji albo gdy faza jest nieznana — względem nastawy VT
  (`docs/en/development/plans/plan-0.2-g11.md` C). Oknami zajmuje się VT (I8.1b): strefa, którą VT
  wyłącza lub obniża z powodu okna, już nie prosi o ciepło i nie wygląda na taką, której brakuje
  ciepła; wtyczka nie ma własnej obsługi okien.
- **Temperatura pokojowa krzywej: Auto albo Ręczna** (`docs/en/development/plans/plan-0.2-g11.md` D).
  Auto, domyślnie dla nowych wpisów: najwyższa nastawa VT wśród stref w trybie grzania, znanych
  i niepominiętych przez użytkownika, nie więcej niż 23 °C i w ramach własnych kontroli krzywej; idzie
  za presetami VT przez rampę, a gdy nie ma takiej strefy, obowiązuje ostatnia wartość. Ręczna:
  wpisana wartość, nastawa najcieplejszego pokoju. Wpis po aktualizacji działa w trybie Ręcznym
  z zapisaną wartością.
- **„Wyłączone”** idzie przez włącznik grzania (wbudowana obsługa OTGW: `CH=0`, trzymane, z `CS`
  co najmniej 8 °C; przekaźnik: przekaźnik wyłączony). Sterowanie bez działającego włącznika grzania
  jest zablokowane, a takie instalacje dostają monitor, tak jak w alternatywie decyzji 1 (niskie `CS`
  z `CH` zostawionym w spokoju). Badanie z 2026-09-27 nie znalazło kotła, w którym niska nastawa
  przy włączonym c.o. zatrzymuje pompę c.o. (Q3.2); blokadę zdejmuje tylko użytkownik, przy K4,
  cokolwiek wykaże badanie (decyzja 11, odpowiedź K). Kocioł, który od początku sesji ignoruje
  „grzanie wyłączone” albo „grzanie włączone” (decyzja 4 z
  `docs/en/development/plans/plan-0.2.3.md`), jest traktowany tak samo: sterowanie jest zablokowane,
  a kocioł oddany, z alarmem, a blokada podaje powód, dopóki użytkownik nie wyłączy i nie włączy
  sterowania po naprawieniu usterki (odpowiedź O).
- **Brak oznak, że kocioł grzeje** (ścieżki sterowania temperaturą wody; decyzja 2 z `docs/en/development/plans/plan-0.2.3.md`):
  blokada awaryjna, panel ustawiony na lato lub usterka gazu sprawiają, że każdy odczyt zwrotny
  potwierdza wartości wtyczki. Gdy grzanie jest zlecone, strefa woła i przez 30 min z rzędu
  (tymczasowo, K4) płomień jest znany jako wyłączony — albo, gdy płomień nie jest znany, temperatura
  zasilania nie wzrosła o 5 K — a temperatura zasilania, o ile jest znana, pozostaje poniżej nastawy
  wtyczki, pojawia się alarm informacyjny „brak oznak, że kocioł grzeje” i ostrzegawcze zgłoszenie
  naprawy. Nigdy nie następuje oddanie sterowania: sterowanie zapisuje wartości dalej. Oba zostają,
  dopóki nie pojawi się oznaka ciepła poza poborem c.w.u. — płomień włączony, temperatura zasilania
  wyższa o 5 K albo, gdy płomień nie jest znany, zasilanie na poziomie nastawy wtyczki — albo dopóki
  sterowanie nie zostanie wyłączone. Odliczanie zaczyna się od nowa, gdy tylko któryś warunek
  przestaje być spełniony, i po poborze c.w.u.; gdy nie jest znany ani płomień, ani temperatura
  zasilania, nic nie jest oceniane; grzanie tylko na mróz, gdy żadna strefa nie woła, zostaje
  alarmowi „ochrona przed mrozem nie grzeje”. Ścieżka z przekaźnikiem ma własny dowód ciepła (§5).
- **Ochrona kotła** opiera się na własnej logice kotła. Dwa opcjonalne sygnały przyjmują czujniki
  binarne, które wskazuje użytkownik: „własna usterka kotła: niskie ciśnienie wody” (poziom prosty)
  i „inna usterka, o której kocioł mówi, że go zatrzymuje” (poziom zaawansowany) — w `opentherm_gw`
  to czujnik kotła „Low water pressure” i jego inne czujniki usterek, w ESPHome jego czujniki
  binarne usterek, w EMS-ESP żaden standardowy (kody serwisowe zależne od modelu) (Q3.9). W OTGW taka
  flaga liczy się tylko wtedy, gdy włączone jest „Fault indication” kotła — trzeci opcjonalny sygnał,
  który wskazuje użytkownik, domyślnie żaden — bo bramka odczytuje szczegóły usterki raz przy każdej
  nowej usterce i nigdy więcej po jej ustąpieniu; bez tego sygnału flaga usterki z bramki niczego nie
  zatrzymuje, a funkcja podaje, czego jej brakuje (tymczasowo, K4). Gdy któryś z nich przez 5 min
  (tymczasowo, K4) pokazuje znane „włączone”, sterowanie wysyła swoje zwykłe „wyłączone” — także dla
  grzania na mróz — bez oddania sterowania i bez zatrzasku, a grzeje znowu samo w kroku, w którym
  każda wskazana usterka pokazuje „wyłączone”, „nieznane” lub „niedostępne” (nieznana usterka liczy
  się jako brak usterki). Bez wskazanej usterki niskie ciśnienie wywołuje tylko powiadomienie „dolej
  wody”, przy progu, który użytkownik bierze z instrukcji kotła — domyślnie żadnego. Zepsuty lub
  milczący czujnik ciśnienia nigdy nie zatrzymuje grzania. Ostrzeżenie i alarm wysokiego ciśnienia
  też nie mają wartości domyślnej: użytkownik wpisuje je poniżej ciśnienia, na jakie ustawiony jest
  zawór bezpieczeństwa, odczytanego na samym zaworze (w Europie często 3 bar, w Ameryce Północnej
  około 2.1 bar), tak jak mówi tekst przy polu (decyzja 13 z
  `docs/en/development/plans/plan-0.2.3.md`). Wysokie ciśnienie i gorące spaliny tylko informują,
  powiadomieniem, które mówi, co zrobić: odczytaj ciśnienie, na jakie ustawiony jest zawór
  bezpieczeństwa; wypuszczaj wodę tylko przy wyłączonym i wystudzonym ogrzewaniu. Gdy jest dość
  danych, ostrzeżenie przychodzi wcześniej — „ciśnienie ciągle spada — grozi nieszczelność” —
  oceniane z uwzględnieniem temperatury wody, bo ogrzewanie wody zmienia ciśnienie.

Stałe zabezpieczenia (zasada 11) przy każdym zapisie — nastawa zasilania, włączanie i wyłączanie
c.o., ograniczenie modulacji, wartości trybu działającego jak termostat (0.3) i przekaźnik:

- Żadnego zapisu bez świeżych danych wejściowych — danych, których używa decyzja: przy sterowaniu
  temperaturą wody musi być znany płomień i temperatura zasilania; przy przekaźniku sam przekaźnik
  (§5, klasa 3). Jedna reguła świeżości obsługuje monitor i sterowanie: sygnał jest świeży, dopóki
  jego encja jest dostępna i — jeśli ma limit wieku — dopóki jego ostatni raport mieści się w
  limicie; każdy sygnał ma własny limit, także płomień, a encja pogody ma limit własny. Stały odczyt
  nie jest odczytem nieświeżym — wiele źródeł melduje tylko zmiany — więc limit nigdy nie jest
  zakładany (I6, decyzja 9; tymczasowo, K4): jest to limit użytkownika (0: brak) albo, gdy pole
  zostanie puste, limit, na który źródło zasłuży, gdy co najmniej dwa razy w trakcie działania
  zobaczymy, że powtarza niezmienioną wartość (raport, w którym od poprzedniego nic się nie zmieniło,
  według jego własnego czasu zmiany) — pięciokrotność mediany jego odstępu między sygnałami życia,
  od 10 do 30 min dla sygnałów kotła, od 3 do 12 h dla pogody; źródło, które melduje tylko zmiany,
  nigdy takiego limitu nie zdobywa, więc źródło, które zawiesza się bez przejścia w stan
  „niedostępne”, nie zostanie wykryte, i opis opcji tak mówi. W firmware OTGW przez MQTT i w EMS-ESP
  wtyczka nasłuchuje własnych powtórzeń MQTT urządzenia (tylko odczyt) i uznaje je za raporty
  sygnałów, bo Home Assistant zapisuje encję MQTT tylko przy zmianie. Łączność z bramką jest częścią
  świeżości (jej encje stają się niedostępne); ciche zerwanie MQTT firmware OTGW jest widoczne przez
  jego temat dostępności w ciągu około 90 s, a zerwane połączenie między jego ESP a PIC nie jest w
  Home Assistant widoczne w ogóle — mówi o tym tekst opcji (Q3.6). Zero z wartości spoza regularnego
  odpytywania bramki liczy się jako nieznane, a granice wracają do bezpiecznych wartości domyślnych
  (0.2 nie czyta takich wartości).
- Utrata łączności z kotłem — płomień lub temperatura zasilania nieświeże przez 5 min w ciągu
  ostatnich 10 min, więc łączność świeża w jednym kroku z pięciu nadal jest utracona — zatrzymuje
  każdy zapis; alarm „utracona łączność z kotłem” pojawia się zawsze, gdy przełącznik sterowania jest
  włączony, a łączność utracona, niezależnie od tego, co pokazują blokady lub zatrzask, i następuje
  oddanie sterowania: przy termostacie przejmuje je termostat; przy pracy samodzielnej grzanie się
  zatrzymuje. Sterowanie wznawia się, gdy łączność jest świeża przez 60 s bez przerwy (tymczasowo,
  K4). Przekaźnik poza zasięgiem wywołuje zamiast tego własny alarm po 5 min, bez oddania sterowania
  (§5, klasa 3). Awaria czujnika temperatury zewnętrznej nie jest utratą łączności: prowadzi do
  nastawy awaryjnej, nigdy do zerowego grzania.
- Każda wartość mieści się w twardych limitach — najniższej i najwyższej temperaturze wody — z
  dwoma wyjątkami, które mają własne kontrole: „wyłączone” — tam, gdzie ścieżka może je zapisać jako
  niską nastawę (zablokowane przez decyzję 11 z `docs/en/development/plans/plan-0.2.2.md`, chyba że
  K4 zdejmie blokadę, z wyjątkiem własnej nastawy 0 w EMS-ESP, I6; gdzie indziej „wyłączone” to
  włącznik grzania albo przekaźnik) — niska nastawa co najmniej 1 K poniżej najniższej temperatury
  wody (P-43) i w zakresie celu zapisu; w OTGW `CS` nigdy nie jest zapisywane poniżej 8 °C jako
  nastawa, bo niższe wartości nie wygasają (`CS=0` przy oddaniu sterowania kasuje nadpisanie i nie
  jest nastawą, S-59) — oraz wartość oddania sterowania (§5, bezpieczne oddanie sterowania).
  „Wyłączone” jest odrzucane w granicach 0.5 K od wartości oddania sterowania zadeklarowanej jako
  „urządzenie wraca do własnego sterowania” (S-49). Wartości trybu działającego jak termostat (0.3)
  pozostają w rozsądnych granicach temperatury pokojowej.
- Nic nie jest zapisywane w pamięci trwałej kotła: sterowanie zapisuje tylko do celów zadeklarowanych
  jako wygasające (powtarzane co 30 s) lub trzymane (urządzenie zachowuje wartość; wtyczka wysyła ją
  przy zmianie, po powrocie urządzenia i co 5 min, bez wymagania echa — tymczasowo, K4 — co zastępuje
  „zapis tylko przy zmianie”). Cel nastawy zadeklarowany jako zapisywany na stałe albo o nieznanym
  typie zapisu utrzymuje sterowanie wyłączone, z pokazaną przyczyną; tak zadeklarowany włącznik
  grzania nie jest używany (decyzja użytkownika z 2026-09-25), a bez użytecznego włącznika grzania
  sterowanie jest zablokowane (decyzja 11). `CH=` w OTGW jest trzymane: PIC trzyma je do `CH=1` lub
  do resetu; wtyczka wysyła je znowu przy każdym podtrzymaniu `CS` (30 s; tymczasowo, K4), bo żyje
  ono w pamięci PIC, nie kotła, a niezauważony reset PIC w przeciwnym razie zgubiłby „wyłączone”
  nawet na 5 min tam, gdzie nie wskazano odczytu zwrotnego grzania. Ryzyka „trzymanego” (S-12):
  parametr, który kocioł zachowuje w swojej pamięci (na przykład `heatingtemp` w EMS-ESP), ale
  zadeklarowany jako trzymany, jest zapisywany przy każdej zmianie i co 5 min — około 288 zapisów na
  dobę; ostatnie trzymane polecenie, także „wyłączone”, zostaje, gdy Home Assistant nie działa.
- Temperatury są w °C, a różnice w K; formularz pokazuje jednostkę (S-44). Wartość trafia do encji w
  jej własnej jednostce (°C, °F lub K), zaokrąglona do kroku encji w granicach limitów i
  porównywana po zaokrągleniu; jej zakres jest sprawdzany w tej samej jednostce; encja w jakiejkolwiek
  innej jednostce albo encja nastawy z krokiem większym niż 1 K utrzymuje sterowanie wyłączone.
- Strażnik częstości zapisu chroniący przed zapętleniem: zapis powtórzony w tym samym kroku
  sterowania czeka na następny.
- Każdy zapis jest odczytywany zwrotnie; polecenie, które kocioł ignoruje, jest zgłaszane i nigdy nie
  uznaje się go za wykonane. Pokazywany stan to wartość potwierdzona przez kocioł albo nieznana —
  nigdy żądana. Włączenie i wyłączenie grzania jest potwierdzone tam, gdzie urządzenie je zgłasza, a
  tam, gdzie nie — oznaczone jako niepotwierdzone. Odczyt zwrotny wzięty z samej zapisywanej encji
  niczego nie potwierdza i jest oznaczony jako niepotwierdzony — z wyjątkiem własnego zgłaszanego
  stanu przekaźnika, który potwierdza przekaźnik (nie to, że kocioł grzeje). Encja z `assumed_state`
  albo bez raportu niezależnego od wtyczki jest „niepotwierdzona” i tak mówi (S-09). Cel w stanie
  `unknown` jest zapisywany i liczy się dopiero po odczycie zwrotnym (S-28). Odczyt zwrotny OTGW
  potwierdza bramka: `TSet` pokazuje to, co bramka wysyła, a nie to, co kocioł przyjął.
- **Zmiany widoczne w odczycie zwrotnym** (decyzja 6, odpowiedzi C, D, E, H, L, N, O) dzielą się na
  cztery klasy; wtyczka nigdy nie walczy z innym sterownikiem. Tabela poniżej mówi, która jest która.
- Każde wyjście — wyładowanie, przeładowanie, błąd, utrata danych, alarm ustawiony na oddanie
  sterowania, awaria własnego monitora wtyczki trwająca 5 min (odpowiedź I), ustąpienie — zatrzymuje
  każdą pętlę sterowania poza własnym ponawianiem oddania sterowania i wykonuje bezpieczne oddanie
  sterowania (§5), kasując każde nadpisanie. Kontrole, dzięki którym sterowanie może wrócić samo,
  działają dalej tam, gdzie wyjście na to pozwala: własny monitor wtyczki (odpowiedź I), utrata
  łączności z kotłem, samoczynny powrót po ustąpieniu.
- **Sesja** to jeden odcinek sterowania, od włączenia sterowania do jego wyłączenia; samoczynny
  powrót zaczyna nową. Restart lub przeładowanie też zaczyna nową sesję: to, co sesja trzyma (w tym
  korekta komfortu), zaczyna się od nowa, a stan sterowania — życzenie, zatrzaski, zaległe oddanie
  sterowania, ostatnie polecenie przywrócone w okresie rozpoznania — zostaje zachowany
  (`docs/en/development/plans/plan-0.2.2.md`, Terms).
- Zapis oddający sterowanie nie jest decyzją sterowania: nie wstrzymuje go żaden strażnik — ani
  świeżość, ani strażnik częstości zapisu — a jego wartość (np. `CS=0`) nie podlega twardym limitom
  poza tymi z §5. Oczekujące oddanie sterowania jest zapamiętane, pokazywane i ponawiane co minutę,
  aż zostanie potwierdzone (§5 dla celu, który przejmuje inny sterownik), i przetrwa restarty oraz
  zmiany opcji: zmiana, która by je usunęła, jest odrzucana albo jednostka, która tylko oddaje
  sterowanie, ponawia je dalej, ze zgłoszeniem naprawy. Nieudana konfiguracja najpierw wysyła
  zaległe oddanie sterowania, a jeśli jest ono jeszcze zaległe, gdy konfiguracja się poddaje,
  zgłasza to trwałym zgłoszeniem. Tam, gdzie oddanie sterowania zatrzymuje grzanie — według opcji,
  które da się odczytać, lub tych, z którymi sterowanie zostało przejęte — a zapamiętane życzenie to
  „sterowanie włączone”, nieudana konfiguracja od razu podnosi też trwałe zgłoszenie naprawy na
  poziomie błędu: wtyczka nie wystartowała, a dom nie jest ogrzewany (decyzja 12 z
  `docs/en/development/plans/plan-0.2.3.md`).
- **Stan sterowania** — znacznik „steruje”, zaległe oddanie sterowania i opcje, z którymi sterowanie
  zostało przejęte, zatrzaski, życzenie użytkownika (włączone lub wyłączone), ostatnie polecenie dane
  kotłu, strefa SmartPI wstrzymana przez wtyczkę — jest zapisywany natychmiast i niepodzielnie
  (atomowo), a odczytywany ostrożnie. Utrata, uszkodzenie lub nieczytelność zapisu stanu dla wpisu,
  który wcześniej działał, oznacza „sterował”: najpierw pełne oddanie sterowania (odpowiedź K). Po
  restarcie bez czystego zatrzymania oddanie sterowania czeka do wznowienia sterowania; po każdym
  restarcie przełącznik sterowania wraca w takim stanie, w jakim zostawił go użytkownik, a encja
  przełącznika sterowania wyłączona w Home Assistant oznacza sterowanie wyłączone (odpowiedź K).
- Przełącznik sterowania działa, cokolwiek innego jest zepsute: jego dostępność idzie za jednostką
  sterowania, nie za monitorem. Jeśli własny monitor wtyczki zawodzi przez 5 min, sterowanie zostaje
  oddane i wznawia się samo, gdy monitor znów działa, z informacyjną uwagą (odpowiedź I).
- Sterowanie tylko ze znanym oddaniem sterowania i, przy sterowaniu nastawą, ze źródłem potwierdzonej
  nastawy.
- W trybie działającym jak termostat (0.3) wartości trafiają do kotła tylko od strefy, która woła o
  grzanie i ma prawidłowe odczyty; bez takiej strefy są kasowane, a własne sterowanie kotła działa
  dalej.
- Bit zezwolenia na c.w.u. zostaje taki, jaki był, zanim wtyczka przejęła sterowanie.

Cztery klasy zmiany widocznej w odczycie zwrotnym:

- **Utracone polecenie** — odczyt zwrotny wrócił do stanu sprzed wtyczki (stan wyjściowy: pierwszy
  znany odczyt zwrotny, który nie jest wartością wtyczki; przy termostacie OpenTherm jego własne
  żądanie, gdy wskazano na nie pole opcjonalne) i w ciągu poprzednich 5 min jest ślad awarii: cel,
  jego odczyt zwrotny lub inna encja tego samego urządzenia była `unavailable`, `unknown` lub jej
  brakowało, albo bramka lub urządzenie zrestartowały się — w `opentherm_gw` i ESPHome restart widać
  po tym, że encje przechodzą w `unavailable`; w MQTT firmware OTGW i w EMS-ESP szybki restart może
  nie pokazać nic poza zrestartowanym czasem pracy (uptime), który wtyczka czyta tylko tam, gdzie
  użytkownik wskaże opcjonalny wskaźnik restartu (Q3.7; tymczasowo, K4). Reset PIC w czasie ruchu na
  magistrali i odpowiedź Data-Invalid na ID 1 nie zostawiają żadnego śladu. Pojedynczy taki powrót
  do stanu wyjściowego bez śladu to też utracone polecenie. Wtyczka wysyła polecenie od razu
  ponownie — oba cele jako jedna utrata — bez alarmu; 3 utraty w ciągu 24 h wywołują alarm
  informacyjny „utracone polecenia”, nigdy wstrzymania. Drugi powrót bez śladu w ciągu 60 min,
  którego żadne wysłanie nie tłumaczy, liczy się jako inny sterownik; wysłanie tłumaczy powrót, gdy
  powrót nastąpił, zanim ostatnie wysłanie wtyczki zostało odczytane zwrotnie jako jej wartość, albo
  w ciągu 120 s od wysłania nowej wartości (odpowiedź E) — nie tłumaczy go ten jeden ponowny zapis,
  nawet gdy niesie nową wartość: powrót po nim jest następną zmianą i wtyczka ustępuje (decyzja
  użytkownika z 2026-10-13).
- **Ignorowane od początku** — kocioł nigdy nie przyjmuje wartości: nigdy nie odczytano jej zwrotnie
  jako wartości wtyczki przez dłużej niż 120 s po każdym z pierwszych 3 wysłań w sesji (tymczasowo,
  K4). Wtyczka przestaje ją wysyłać do końca sesji i mówi „kocioł nie przyjmuje polecenia — sprawdź
  ustawienia”; drugi cel i grzanie na mróz działają dalej; bez blokady, bez zatrzasku; próba jest
  ponawiana w następnej sesji. Tam, gdzie oddanie sterowania zatrzymuje grzanie — przy pracy
  samodzielnej wartość zadeklarowana jako „grzanie się zatrzymuje” — dom nie jest wtedy ogrzewany i
  mówi o tym zgłoszenie naprawy na poziomie błędu; próba jest ponawiana w następnej sesji (Z4-11).
  Powrót do stanu wyjściowego bez śladu po każdym wysłaniu od początku sesji zostaje w tej klasie.
  Wyjątek (odpowiedź O): gdy „wyłączone” z włącznika grzania jest ignorowane od początku, sterowanie
  jest blokowane i od razu następuje oddanie sterowania kotłem, z alarmem, a blokada podaje
  przyczynę, dopóki użytkownik po naprawie nie wyłączy i nie włączy sterowania; przy przekaźniku
  powiadomienie mówi, że kocioł może dalej grzać. Jego „włączone” ignorowane od początku jest
  traktowane tak samo (decyzja 4 z `docs/en/development/plans/plan-0.2.3.md`): sterowanie
  zablokowane, sterowanie kotłem oddane i powiadomienie na poziomie błędu, że kocioł nie przyjmuje
  grzania; blokada zostaje, dopóki użytkownik nie wyłączy i nie włączy sterowania.
- **Przycięte** — jedna niższa wartość, w granicach 0.5 K, cokolwiek wtyczka wyśle (przy co najmniej
  2 wysłanych wartościach różniących się co najmniej o 1 K): przyjęta jako własny limit kotła, tylko
  informacja; wtyczka wysyła dalej swoją wartość i nigdy nie uczy się przycięcia jako limitu
  (tymczasowo, K4). Przycięcia nastawy, która się nie zmienia, nie da się odróżnić od innego
  sterownika (znane ograniczenie).
- **Inny sterownik** — wartość trzymana przez 2 kroki, która nie jest żadną z wartości wtyczki, jej
  poprzednią (dopóki jest wyłączona z oceny, patrz niżej), stanem wyjściowym, własnym żądaniem
  termostatu ani przycięciem: wtyczka zapisuje ponownie raz (zapamiętane na ten dzień, przez czysty
  restart i przez wyłączenie i włączenie sterowania); druga zmiana w ciągu 24 h albo ponowny zapis
  nieodczytany zwrotnie w ciągu 120 s sprawia, że wtyczka ustępuje — pełne bezpieczne oddanie
  sterowania każdego celu, przekaźnik ustawiony raz w stan spoczynku i potem zostawiony w spokoju
  (odpowiedzi H, L) — z powiadomieniem i zatrzaskiem, zapamiętanym mimo przeładowań i restartów,
  dopóki użytkownik nie wyłączy i nie włączy sterowania. Opcjonalny samoczynny powrót (domyślnie
  wyłączony, opisany, potwierdzany dwukrotnie; nie dla przekaźników) zaczyna nową sesję, gdy przez 60
  min nie widziano obcej wartości. Po oddaniu sterowania przez przełącznik sterowania zewnętrznego
  wymaga własnej opcji, domyślnie wyłączonej, której tekst mówi o ryzyku: przełącznik pokazuje
  „wyłączone” także wtedy, gdy człowiek celowo wyłączył sterowanie zewnętrzne albo gdy inny
  sterownik zapisuje nastawę, a powrót zabiera im kocioł (decyzja 10 z
  `docs/en/development/plans/plan-0.2.3.md`). Reakcja „informacja” dla innego sterownika już nie
  istnieje.

Poprzednia wartość wtyczki jest wyłączona z oceny — późne echo albo urządzenie, które ją trzyma —
dopóki nowa wartość wtyczki nie zostanie odczytana zwrotnie przez jej własne echo: raport co
najmniej tak nowy jak wysłanie, który nie może jeszcze być echem wcześniejszego wysłania tej samej
wartości (wartość wysłana pomiędzy nie została od tamtej pory odczytana zwrotnie, a tamto
wcześniejsze wysłanie było mniej niż 5 min temu); nieświeży raport nigdy się nie liczy (Z4R3-01).
Dla celu o dwóch wartościach (włącznik grzania, przełącznik sterowania zewnętrznego) tylko do tej
chwili albo do 5 min (300 s) po wysłaniu, zależnie od tego, co nastąpi wcześniej, łącznie z
wartością sprzed wtyczki (decyzja użytkownika z 2026-10-03). Te 5 minut zaczyna się od nowa przy
każdej wysłanej zmianie (nie przy podtrzymaniach, 30-sekundowym `CH=` w OTGW ani ponowieniach), więc
włącznik grzania ma też test zacięcia (KD-01, tymczasowo, K4): gdy jego odczyt zwrotny nie zmienił
się, a wtyczka wysłała drugi stan co najmniej dwa razy — każde wysłanie liczy się dopiero wtedy, gdy
przez trzy razy najdłuższe z ostatnich dziesięciu opóźnień echa plus 30 s (od ostatniego startu Home
Assistanta) nie zostało pokazane, przy czym to opóźnienie jest brane pod uwagę od momentu, gdy
widziano trzy echa (KDF-01) — a pierwsze z nich było 5 min temu lub dawniej, odczyt zwrotny jest
oceniany według tych klas bez względu na wyłączenie z oceny: zacięty przełącznik albo automatyka
przywracająca go tam, gdzie żaden krok tego nie widzi, jest oceniany w ciągu około 5–11 min od
pierwszego zignorowanego polecenia przy cyklach VT do 10 min (dłuższe: około cyklu plus minuta).
Odczyt zwrotny z odpytywania uczy się długiego opóźnienia, więc jego krótkie impulsy nigdy się nie
liczą; odpytywanie zsynchronizowane z cyklem VT (jego odstęp jest dzielnikiem lub wielokrotnością
cyklu) nadal może na stałe próbkować te same fazy i wyglądać na zacięte, impulsy krótsze niż około
minuta nigdy się nie liczą, a przełącznik zacięty, zanim widziano trzy echa, zostaje przy oknie 5
min (znane ograniczenia). Potem odczyt zwrotny w poprzednim stanie jest oceniany według tych klas:
powrót do stanu wyjściowego — według zasad powrotu (odpowiedź E); w przeciwnym razie inny
sterownik. Echo dwuwartościowe albo odczyt zwrotny z odpytywania wolniejszy niż 5 min też jest
oceniany — pole odczytu zwrotnego grzania prosi o taki, który zgłasza zmianę w ciągu około minuty:
wolniejszy opóźnia zauważenie zmiany, a wolniejszy niż 5 min może sprawić, że wtyczka ustąpi
niesłusznie (znane ograniczenie). Polecenie grzania utracone bez żadnego śladu awarii jest więc
wysyłane ponownie po najwyżej 5 min; utracone ze śladem — od razu. Nastawa zachowuje wyłączenie z
oceny — własny limit kotła jest oceniany jako przycięcie, na wolny odczyt zwrotny się czeka.
Nastawa, której nowa wartość nie została odczytana zwrotnie przez 5 min, gdy odczyt zwrotny jest
znany i pokazuje inną wartość, wywołuje „brak potwierdzenia” i zgłoszenie naprawy (ostrzeżenie;
błąd tam, gdzie oddanie sterowania zatrzymuje grzanie), które mówi, że kocioł nie pokazuje wartości
wtyczki i co sprawdzić; oba znikają, gdy wartość zostanie odczytana zwrotnie albo sterowanie
zostanie wyłączone, i nigdy same nie sprawiają, że wtyczka ustępuje (Z4-01, Z4R-01, Z4R2-03).

| Przypadek | Co pokazuje odczyt zwrotny | Klasa | Reakcja |
|---|---|---|---|
| Po awarii (urządzenie, bramka lub broker niedostępne; restart ESP, PIC lub EMS-ESP; przeładowanie `opentherm_gw`) | z powrotem w stanie wyjściowym, ze śladem | utracone polecenie | wysłane ponownie od razu; „utracone polecenia” przy 3 w ciągu 24 h |
| Trzymany cel po powrocie z niedostępności | jego przywrócona lub początkowa wartość albo nieznane | utracone polecenie | każda trzymana wartość wysłana ponownie od razu; wartość, z którą wrócił, nie jest oceniana |
| Odświeżanie trzymanych wartości | niewymagane | — | wysyłane co 5 min, bez wymagania echa; to nie jest ponowny zapis |
| Pojedynczy powrót bez śladu | z powrotem w stanie wyjściowym | utracone polecenie | jak po awarii |
| Drugi powrót bez śladu w ciągu 60 min, którego żadne wysłanie nie tłumaczy | z powrotem w stanie wyjściowym | inny sterownik | jedyny ponowny zapis dnia; następna zmiana w ciągu 24 h → ustąpienie |
| Odrzucane od początku | nigdy wartość wtyczki przez dłużej niż 120 s po każdym z pierwszych 3 wysłań | ignorowane od początku | nie wysyłane ponownie w tej sesji; informacja; „wyłączone” lub „włączone” z włącznika grzania: zablokowane i oddane (odpowiedź O; decyzja 4 z 0.2.3) |
| Ta sama niższa wartość, cokolwiek zostanie wysłane | przycięcie | przycięte | informacja; wtyczka zostaje przy własnej wartości |
| Obca wartość, także gdy wartość wtyczki ciągle się zmienia albo po nieznanym odczycie zwrotnym w chwili wysłania | inna stała wartość przez 2 kroki | inny sterownik | jeden ponowny zapis; druga zmiana w ciągu 24 h → ustąpienie |
| Różnica tylko w jednym kroku | — | — | nie jest oceniana, dopóki nie utrzyma się przez 2 kroki |
| Odczyt zwrotny nieznany lub niedostępny w czasie zapisu | nieznane | — | nic nie jest oceniane; „brak potwierdzenia” po 5 min; nigdy samo oddanie sterowania |
| Oddanie sterowania wbrew innemu sterownikowi | jego wartość trzymana przez 2 ponowienia albo cel dwuwartościowy zmieniony po odczytaniu zwrotnym stanu oddania | — | liczy się jako oddane; bez ponawiania |
| Niepotwierdzone zwolnienie trzymanej wartości | najniższa temperatura wody | — | alarm od razu; zwolnienie ponawiane co minutę |
| Przełącznik sterowania zewnętrznego wyłączony, gdy był dostępny | wyłączone, bez śladu | inny sterownik | ustąpienie od razu, bez ponownego zapisu |
| Przełącznik sterowania zewnętrznego wyłączony po restarcie urządzenia | wyłączone, po niedostępnym lub nieznanym | utracone polecenie | włączony ponownie |
| Przełącznik sterowania zewnętrznego, którego po włączeniu przez wtyczkę nigdy nie widziano jako włączonego | wyłączone | jak w dwóch wierszach wyżej | oceniany 5 min po włączeniu, jak w dwóch wierszach wyżej (Z4R2-03, K4.3) |
| Pobór c.w.u. | echo stanu kotła wyłącza się | — | nie jest oceniane w czasie poboru ani przez 2 min po nim |
| Własne wygaśnięcie wtyczki (cisza dłuższa niż 60 s), także wygasającego przełącznika sterowania zewnętrznego | inna wartość | — | wysłane ponownie; to nie jest zmiana z zewnątrz |
| Zmiany, których żaden odczyt zwrotny nie widzi (panel kotła, blokada awaryjna, aplikacja producenta) | nic | — | to nie jest zmiana z zewnątrz; widać je przez „brak oznak, że kocioł grzeje” (wyżej; decyzja 2 z 0.2.3) i „ochrona przed mrozem nie grzeje”; usterka zgłaszana przez kocioł zatrzymuje grzanie (ochrona kotła) |
| Okres rozpoznania | cokolwiek | — | ostatnie polecenie przywrócone według decyzji 3; odczyt zwrotny, który jeszcze go nie pokazuje, nie jest liczony |
| Skonfigurowany własny kocioł centralny VT | — | — | blokada, nigdy zmiana z zewnątrz |
| R1: przekaźnik poza zasięgiem | niedostępny, nieznany lub brak | — | nic nie jest zapisywane, gdy jest niedostępny lub go brak; „przekaźnik poza zasięgiem” po 5 min; bez oddania sterowania |
| R2: przekaźnik wraca w innym stanie po utracie zasilania lub łączności | inny stan, ze śladem | utracone polecenie | polecenie ponownie; „utracone polecenia” przy 3 w ciągu 24 h |
| R2a: przekaźnik znaleziony w zadeklarowanym stanie po odcięciu zasilania bez śladu (albo, gdy zadeklarowano „ostatni” lub „nie wiem”, zmieniony, gdy był dostępny) | ten stan | utracone polecenie do 3 razy w ciągu 24 h; czwarty raz: inny sterownik | polecenie ponownie; ostrzeżenie informacyjne przy 3; czwarty raz ustąpienie od razu |
| R3: przekaźnik przełączony, gdy cały czas był dostępny | inny stan, bez śladu | inny sterownik | jeden ponowny zapis; druga zmiana w ciągu 24 h → ustąpienie do stanu spoczynku, potem zostawiony w spokoju |
| R4: okresowa kontrola wykrywa niezgodność | nie ten stan, który zlecono | według śladu, jak R2, R2a lub R3 | jak R2, R2a lub R3 |
| R5: własny zegar wyłączenia przekaźnika | wyłączony po upływie jego czasu | — | znowu „włączone”, nie liczone, gdy jest to wygaśnięcie zadeklarowanego zegara — w granicach 60 s od całkowitej wielokrotności jego długości, najwyżej 3×, licząc od „włączone” danego okresu włączenia lub od ostatniego odnowienia; każde inne wyłączenie to R2a lub R3 (decyzja 6 z 0.2.3); przy zegarze „nie wiem” liczone jako restart do odpowiedzi N (Z4-02), chyba że powtarza się w tym samym wieku okresu włączenia, wynoszącym 9 min lub więcej (10 min, z tolerancją minuty), co jest własnym zegarem przekaźnika (Z4R-02); krótszy regularny nadal się liczy, a zgłoszenie o zatrzasku podaje jego długość (K4.2) |
| R6: przekaźnik, który nie zgłasza stanu | nic | — | ślepe powtórzenia; „sterowany bez potwierdzenia”; ręczna zmiana jest cofana przy następnym powtórzeniu |
| R7: przekaźnik nigdy nie przyjmuje polecenia | nigdy zlecony stan przez dłużej niż 120 s po każdym z pierwszych 3 wysłań | ignorowane od początku | nie zapisywane ponownie w tej sesji; zgłoszenie na poziomie alarmu; jego „wyłączone” lub „włączone” ignorowane: sterowanie zablokowane, a przekaźnik oddany (odpowiedź O; decyzja 4 z 0.2.3) |
| R7a: przekaźnik, który w trakcie sesji przestaje przyjmować polecenie | stan inny niż zlecony w 3 kolejnych kontrolach (około 15 min), a zleconego polecenia nie pokazał od chwili wysłania — polecenie, które już pokazuje, gdy od tamtej pory się nie przełączył, niczego nie kończy (przekaźnik zacięty przy krótkich impulsach VT; użytkownik, 2026-10-13) | przestał przyjmować polecenia | zgłoszenie na poziomie błędu; jego „wyłączone” nieprzyjęte: sterowanie zablokowane, a przekaźnik oddany (decyzja 6 z 0.2.3) |
| R8: oddanie sterowania przekaźnikiem | stan spoczynku | — | zrobione po odczycie zwrotnym; przy ustąpieniu zapisane raz i potem zostawione w spokoju |
| R9: planowany restart | — | — | stan spoczynku przy zatrzymaniu; ostatnie polecenie przywrócone od razu przy starcie |

Jak sterowanie wznawia się po zatrzymaniu:

| Przyczyna | Sterowanie wraca |
|---|---|
| Alarm ustawiony na oddanie sterowania (decyzja 7) | gdy użytkownik wyłączy i włączy sterowanie — zatrzask: przetrwa restart, pokazuje swoją przyczynę w jednym zgłoszeniu naprawy i sam nigdy nie wygasa |
| Inny sterownik (ustąpienie) | gdy użytkownik wyłączy i włączy sterowanie, albo samo po 60 min bez obcej wartości, gdy ta opcja jest włączona — nie dla przekaźników ani po oddaniu sterowania przez włącznik sterowania zewnętrznego bez jego własnej opcji |
| Przekaźnik znaleziony w zadeklarowanym stanie po zaniku zasilania (albo, przy „ostatni” lub „nie wiem”, zmieniony, gdy był dostępny) | ponowne wysłanie polecenia (odpowiedź D); czwarty taki przypadek w ciągu 24 h to inny sterownik: zatrzask ustąpienia do wyłączenia i włączenia (odpowiedź N) |
| Błąd wewnętrzny | przy każdej zmianie włącznika sterowania; zatrzask przetrwa restart |
| „Wyłączone” lub „włączone” dla włącznika grzania zignorowane od początku, albo przekaźnik, który przestaje przyjmować „wyłączone” | blokada, dopóki użytkownik nie wyłączy i nie włączy sterowania (odpowiedź O; decyzje 4 i 6 z 0.2.3) |
| Każde inne polecenie zignorowane od początku | przy następnej sesji |
| Utrata łączności z kotłem | samo, gdy dane są świeże przez 60 s |
| Przekaźnik poza zasięgiem | ponowne wysłanie polecenia, gdy wróci |
| Własna usterka kotła | samo, w kroku, w którym każda zmapowana usterka pokazuje wyłączone, nieznane lub niedostępne |
| Wszystkie strefy nieznane | samo, gdy któraś strefa znów odpowie |
| Awaria własnego monitora wtyczki | samo, gdy znów działa, z notatką informacyjną (odpowiedź I) |
| Alarm z reakcją oddania sterowania, już aktywny w chwili włączenia sterowania | blokuje sterowanie od razu; mówi o tym tekst włącznika |
| Blokada — brakujące ustawienie, skonfigurowany centralny kocioł VT, uruchamianie się Home Assistanta | samo, gdy blokada zniknie; „Centralny kocioł VT aktywny” dopiero po restarcie Home Assistanta, o który prosi jej tekst |

W trybie na wzór termostatu (0.3) kocioł działa według własnej regulacji: opcje krzywej, rampy,
ochrony przed krótkimi cyklami i limitu zasilania nie obowiązują; stałe zabezpieczenia obowiązują.

Które alarmy mogą oddać sterowanie (decyzja 7):

- Zawsze: błąd wewnętrzny; utrata łączności z kotłem po 5 min (przekaźnik: alarm, bez oddania
  sterowania); inny sterownik (ustąpienie); awaria własnego monitora wtyczki przez 5 min, a
  sterowanie wraca samo, gdy monitor znów działa (odpowiedź I); „wyłączone” lub „włączone” dla
  włącznika grzania zignorowane od początku sesji, albo przekaźnik, który w niej przestaje
  przyjmować „wyłączone”, z blokadą, dopóki użytkownik nie wyłączy i nie włączy sterowania
  (odpowiedź O; decyzje 4 i 6 z
  `docs/en/development/plans/plan-0.2.3.md`).
- Opcjonalnie, domyślnie informacja: kocioł ignorujący jakikolwiek inny zapis — oferowane tylko
  tam, gdzie przejmuje sterowanie termostat lub własne sterowanie kotła, nigdy na ścieżce
  przekaźnika.
- Każdy inny alarm informuje. Zatrzymanie grzania przy usterce kotła podlega własnej logice kotła
  (ochrona kotła, wyżej); wysokie ciśnienie i gorące spaliny dają powiadomienie z informacją, co
  zrobić.
- Liczy się tylko znany odczyt na poziomie alarmu, utrzymany przez 5 min; wartości nieznane nigdy.
  Alarm, którego wejście jest nieznane lub nie da się go ocenić, trzyma swój stan przez 60 min,
  potem pokazuje „nieznane”. Powiadomienie zamyka się po 60 min z powrotem w normalnym zakresie
  (tymczasowe, K4).
- Alarm z reakcją oddania sterowania, który jest już aktywny w chwili włączenia sterowania,
  blokuje sterowanie od razu, a tekst włącznika o tym mówi.
- Dozwolone reakcje to lista dozwolonych w kodzie: nowy alarm domyślnie informuje, a zapisana
  reakcja, która nie jest już dozwolona, jest unieszkodliwiana. Każde oddanie sterowania
  spowodowane przez alarm tworzy zgłoszenie naprawy, a każdy zatrzask, z jakiejkolwiek przyczyny,
  jedno zgłoszenie zatrzasku wpisu, z nazwaną przyczyną — na poziomie alarmu, gdy skutkiem oddania
  sterowania jest „ogrzewanie staje”, w innym razie na poziomie ostrzeżenia.
- **Powiadomienie** to zgłoszenie naprawy Home Assistanta, które wtyczka sama tworzy (bez
  wywołania usługi), z przetłumaczonym tekstem, który mówi, co się stało i co zrobić; zamyka się
  samo, gdy jego warunek ustąpi. **Alarm** to encja alarmu wtyczki, na poziomach ostrzeżenie i
  alarm; „informacja” to alarm, który nigdy nie zmienia sterowania.

Opcje, każda z ostrożną wartością domyślną i opisem ryzyka (temperatury w °C, różnice w K):

- Zapotrzebowanie kotła z liczby wołających stref, z mocy łącznej lub z otwarcia zaworów, każde
  kryterium osobno albo razem z innymi; dla każdej strefy „zamyka się, gdy VT ją wyłączy”
  (domyślnie wyłączone, decyzja 4).
- Rampa: jak szybko może zmieniać się temperatura wody, w K na minutę, aby kocioł nie
  przekroczył nastawy po jej skoku, a algorytmy stref nadążały.
- Opóźnienie włączenia VT, 0–600 s (decyzja 5), pokazywane na poziomie prostym i na ścieżce
  przekaźnika.
- Odstęp decyzji dla temperatury wody.
- Stała nastawa awaryjna, zastępująca nastawę z krzywej przy awarii czujnika zewnętrznego.
- Najniższa temperatura wody (decyzja 2), najwyższa temperatura wody, maksimum obiegu oraz jego
  temperatura i czas alarmu (decyzja 10) i, od 0.3, granice trybu na wzór termostatu. Limity
  wtyczki obowiązują tylko wtedy, gdy ona steruje; po oddaniu sterowania lub po awarii Home
  Assistanta obowiązuje własne maksimum kotła lub termostatu ściennego (§5, bezpieczne oddanie
  sterowania). Strażnik częstości zapisu i ponawianie oddania sterowania są stałe, nie są
  opcjami.
- Typ zapisu każdego wybranego celu zapisu — encja nastawy, włącznik grzania i włącznik sterowania
  zewnętrznego deklarują go każdy osobno: **wygasający** — nadpisanie powtarzane co 30 s, aby nie
  wygasło (ryzyko, jeśli encja jest w rzeczywistości zapisywana w pamięci kotła: każde
  powtórzenie ją zużywa, około 2900 zapisów dziennie); **trzymany** — urządzenie zachowuje
  wartość; wysyłany przy zmianie, po powrocie urządzenia i co 5 min (ryzyka: patrz „Nic nie jest
  zapisywane w trwałej pamięci kotła” wyżej); **zapisywany na stałe** albo **nieznany**
  (domyślnie) — nie jest zapisywany: dla celu nastawy sterowanie zostaje wyłączone, a włącznik
  grzania jest nieużywany, co blokuje sterowanie (decyzja 11). Wbudowany OTGW powtarza `CS` co
  30 s; jego `CH=` jest trzymany i wysyłany z każdym podtrzymaniem `CS`.
- Odczyt zwrotny włączenia i wyłączenia grzania: domyślnie brak — włączenie i wyłączenie grzania
  jest wtedy pokazywane jako niepotwierdzone (ryzyko: przełączenie go przez inny sterownik
  przejdzie niezauważone). Przy „bramka z termostatem” opcjonalne pole „żądana nastawa sterowania
  termostatu OpenTherm” pozwala odróżnić zgubione polecenie od innego sterownika; nie można go
  użyć jako odczytu zwrotnego nastawy.
- Limit wieku dla każdego zmapowanego sygnału (świeżość; idzie razem z sygnałem), także dla encji
  pogody: domyślnie pusty —
  automatyczny, ustalany po zaobserwowaniu, że źródło powtarza niezmienioną wartość; 0 oznacza
  brak (ryzyko: bez limitu zamrożone źródło nie zostanie wykryte; z limitem krótszym niż odstęp
  raportowania źródła sterowanie zatrzymuje się przy niezmiennej pogodzie).
- Ochrona przed mrozem: jej temperatura graniczna i temperatura zwolnienia oraz to, czy
  obserwuje każdą strefę (domyślnie), czy jedną strefę.
- Korekta komfortu włączona (domyślnie w pełnym sterowaniu) lub wyłączona; jej limit (domyślnie
  3 K, do 10 K); wzrost najwyżej 3 K dziennie, stały (zasada 13).
- Temperatura pokojowa krzywej: Auto (domyślnie) lub Ręcznie, oraz strefy, które Auto pomija.
- Wstrzymania nauki włączone (domyślnie) lub wyłączone.
- Reakcje, na które pozwala decyzja 7.
- Dwa sygnały usterki kotła, „Fault indication” bramki, próg „dolej wody” oraz ostrzeżenie i alarm
  wysokiego ciśnienia (domyślnie brak).
- Samoczynny powrót po innym sterowniku (domyślnie wyłączony, potwierdzony dwukrotnie; nie na
  ścieżce przekaźnika; po oddaniu sterowania przez włącznik sterowania zewnętrznego osobna opcja,
  domyślnie wyłączona).
- Co jest podłączone do zacisków termostatu bramki (decyzja 1).
- „Kocioł ma własny regulator pokojowy” (domyślnie wyłączone), tylko na ścieżkach encji i
  przekaźnika; na ścieżce przekaźnika liczy się tylko ze stanem spoczynku „włączony”
  (odpowiedzi F, M).
- Ustawienia przekaźnika (§5 klasa 3): zaznaczenie „osobny styk”, jego stan po zaniku zasilania,
  jego zegar wyłączenia, czy zgłasza swój stan, odstęp powtarzania, stan spoczynku i opcjonalny
  dowód, że kocioł grzeje.
- Ostrzeżenie o małym przepływie, gdy wszystkie zawory są zamknięte od 15 minut, a pompa pracuje
  (pompa pracuje jeszcze po wyłączeniu palnika) — wymaga sygnału pracy pompy lub aktywnego c.o.;
  wyłączone podczas c.w.u. i gdy zadeklarowano obejście lub sprzęgło hydrauliczne.

Wartości domyślne opcji bezpieczeństwa i dlaczego (użytkownik przegląda je w K4):

| Opcja | Domyślnie | Dlaczego |
|---|---|---|
| Sterowanie | wyłączone; można włączyć od pierwszego dnia; werdykt po 7 dniach danych | sterowanie jest eksperymentalne i dobrowolne; nie rusza niczego poza twardymi granicami, więc czekanie niczego nie chroni — dopóki nie jest włączone, kocioł działa jak dotąd (decyzja użytkownika z 2026-10-08) |
| Krzywa grzewcza | brak — wpisuje się projektową temperaturę zasilania | zła krzywa niedogrzewa lub marnuje gaz; żadnej cichej wartości domyślnej |
| Typ odbiornika ciepła | grzejnik — chyba że obieg wymienia strefę jako podłogową lub z konwektorami (I8 F2) | podłogówka potrzebuje własnej najwyższej temperatury wody; strefa, której nie ma na liście, jest traktowana jak grzejnik |
| Najniższa / najwyższa temperatura wody | 20 °C (tymczasowe, K4) / 70 °C tam, gdzie obieg żadnej nie podaje (jego najwyższa temperatura wody, z włączonym dawnym maksimum krzywej — I8 F2) | najniższa ogranicza krzywą od dołu — gdy jest za niska, kocioł co chwilę sam się zatrzymuje w łagodną pogodę, a kocioł niekondensacyjny ma skropliny w kominie (wartość weź z jego instrukcji); gdy jest za wysoka, woda jest cieplejsza, niż potrzebują pokoje (decyzja 2); 70 °C obejmuje typowe punkty projektowe grzejników i mieści się poniżej maksimum kotłów |
| Rampa | 1 K na minutę | skok nastawy na tyle mały, że kocioł go nie przekracza; algorytmy stref nadążają, a większe wahania wstrzymują naukę SmartPI (S-47) |
| Odstęp decyzji | 5 min | domyślny cykl VT |
| Opóźnienie włączenia | 0 s | jak w VT 10.4.0; opóźnienie jest dla powolnych zaworów (decyzja 5) |
| Typ zapisu wybranego celu | nieznany — sterowanie zostaje wyłączone, dopóki użytkownik nie zadeklaruje typu wygasający lub trzymany | wtyczka sama nie rozpozna typu, a zły domysł zużywa pamięć kotła |
| Nastawa „wyłączone” | 10 °C — używana tylko bez włącznika grzania, co decyzja 11 blokuje; z włącznikiem „wyłączone” to wyłączony włącznik, a nastawa zostaje przy wartości z krzywej (OTGW: `CH=0`, `CS` z krzywej, nigdy poniżej 8 °C) (Z4-07) | daleko poniżej każdej wartości grzania; sama niska nastawa to nie „wyłączone” (decyzja 11) |
| Wartość oddania sterowania (encja) | brak — wpisywana razem ze swoim skutkiem | 0 może oznaczać „brak ciepła” w jednym urządzeniu, a „własne sterowanie” w innym |
| Limit czasu urządzenia przy oddaniu sterowania przez limit czasu | 1 min (1–60), własny limit urządzenia wpisuje użytkownik | zwolnienie jest oceniane dopiero po jego wykonaniu, a „oddanie sterowania nie powiodło się” po 3 min od niego; dłuższy rzeczywisty limit czasu daje fałszywy alarm, który znika, gdy zwolnienie się pokaże (decyzja 5 z `docs/en/development/plans/plan-0.2.3.md`; tymczasowe, K4) |
| Nastawa awaryjna | ostatnia efektywna temperatura zewnętrzna przez 3 h, potem projektowa temperatura zasilania, albo stała wartość użytkownika (decyzja 9) | nigdy zero ciepła; zawory chronią pokoje przed przegrzaniem |
| Próg mrozu / zwolnienia | 5 / 7 °C | powyżej zera z zapasem, poniżej każdej nastawy komfortu |
| Ochrona przed mrozem | każda strefa, ogrzewana tylko tam, gdzie jej odbiornik ciepła może przyjąć ciepło | ciepło dla strefy, którą VT trzyma zamkniętą, nie dotrze; zgłoszenie naprawy mówi, co zrobić zamiast tego (decyzja 4) |
| Próg zapotrzebowania | jedna wołająca strefa | każda wołająca strefa grzeje, jak w centralnym kotle VT |
| Co liczy licznik | urządzenia VT, jak centralny kocioł VT (decyzja użytkownika z 2026-10-14; wpis sprzed tej daty zostaje przy strefach) | to samo co strefa przy domyślnej liczbie 1; użytkownik przechodzący z VT zachowuje liczbę z VT |
| Korekta komfortu | włączona w pełnym sterowaniu (decyzja użytkownika z 2026-10-10, odwracająca tę z 2026-10-03; wpis po aktualizacji zostaje przy tym, z czym działał); do swojego limitu, domyślnie 3 K (najwyżej 10 K), rośnie najwyżej 3 K dziennie; porównanie startów z nią włączoną (około 2026-10-12) może zmienić wartość domyślną | przy strefach TPI z VT może utrzymać wodę na jej krawędzi +3 K, podczas gdy strefa przy pełnym cyklu pracy nie dochodzi do celu o własne przesunięcie TPI, i wtedy cykl każdej strefy zatrzymuje palnik: od 1.75 do 5 razy więcej startów w symulacji, do 6.3 przy dobowym wahaniu temperatury zewnętrznej; włączona, pomaga pokojowi, którego odbiornik ciepła nie może ogrzać na krzywej, z ograniczeniem, aby inne się nie przegrzały |
| Wstrzymania nauki | włączone | chronią model SmartPI przed wahaniami, które wywołuje wtyczka |
| Reakcja alarmu | informacja; oddania sterowania z decyzji 7 zawsze | inny sterownik zapisuje wartości — nigdy z nim nie walczymy; wtyczka zatrzymuje grzanie tylko tam, gdzie sam kocioł się zatrzymuje |
| Alarm maksimum obiegu | maksimum obiegu + 5 K, przez 10 min (informacja); na obiegu zasilanym prosto z kotła c.w.u. z priorytetem nie jest liczona | kocioł może przekroczyć maksimum; użytkownik to widzi (decyzja 10); c.w.u. nie dociera do tego obiegu (2026-10-12) |
| Próg „dolej wody” | brak | wartość pochodzi z instrukcji kotła; zła wartość domyślna niczego nie zatrzyma, ale wprowadzi w błąd |
| Ostrzeżenie / alarm wysokiego ciśnienia | brak — wpisywane poniżej wartości znamionowej zaworu bezpieczeństwa, odczytanej z zaworu | wartości się różnią (często 3 bar w Europie, około 2.1 bar w Ameryce Północnej): domyślne 2.8 bar nigdy nie zadziałałoby poniżej zaworu 2.1 bar (decyzja 13 z `docs/en/development/plans/plan-0.2.3.md`) |
| Ostrzeżenie / alarm spalin | 85 / 100 °C przy kotle kondensacyjnym; brak przy niekondensacyjnym | cieplejsze spaliny znaczą, że kocioł nie kondensuje; zbyt wysoka wartość ostrzega za późno dla plastikowych rur spalinowych; kocioł niekondensacyjny ma znacznie gorętsze spaliny (powód do potwierdzenia w K4) |
| Częste starty | więcej niż 12 startów na godzinę | jeden start na 5-minutowy cykl, domyślny w VT; zbyt wysoka wartość ukrywa krótkie cykle (powód do potwierdzenia w K4) |
| Niestabilny zapłon | więcej niż 10 paleń krótszych niż minuta w ciągu doby | kilka może pochodzić z krótkich poborów c.w.u.; zbyt wiele ukryje problem z zapłonem (powód do potwierdzenia w K4) |
| Sygnały usterki kotła | brak | użytkownik mapuje własną usterkę kotła tam, gdzie pokazuje ją integracja |
| Zaciski termostatu (bramka) | brak — wymagane; „nie wiem” blokuje sterowanie | styk włącz/wyłącz nie mógłby ogrzać domu po awarii, gdy jest w stanie „wyłączone” (decyzja 1) |
| „Kocioł ma własny regulator pokojowy” | nie zaznaczone | bez tego brak odpowiedzi od VT oznacza brak grzania i alarm, nigdy domysł (odpowiedzi F, M) |
| Stan spoczynku przekaźnika | wyłączony | przekaźnik pozostawiony „włączony” grzeje bez regulacji pokojowej; powiadomienie mówi, kiedy „wyłączony” zostawia dom bez ogrzewania |
| Ustawienia przekaźnika | „nie wiem” — jego raport stanu jest traktowany jak „nie” | ostrożny odczyt każdej niewiadomej: ślepe powtórzenia, „może włączony” po zaniku zasilania, „może mieć zegar” |
| Odstęp powtarzania przekaźnika | 300 s (10–300 s) | odnawia przekaźnik, który może sam się wyłączyć, bez zalewania go poleceniami |
| Zaznaczenie „osobny styk” przekaźnika | nie zaznaczone — sterowanie nie startuje bez niego | ustawienie zapisane w pamięci kotła zużywałoby się przy każdym przełączeniu (odpowiedź G) |
| Samoczynny powrót po innym sterowniku | wyłączony | inny sterownik może nadal działać; użytkownik najpierw sprawdza |
| Samoczynny powrót po oddaniu sterowania przez włącznik sterowania zewnętrznego | wyłączony — własna opcja | włącznik pokazuje „wyłączony” także wtedy, gdy człowiek celowo wyłączył sterowanie zewnętrzne (decyzja 10 z `docs/en/development/plans/plan-0.2.3.md`) |
| Limit wieku świeżości | automatyczny: brak, dopóki źródło dwa razy nie powtórzy niezmienionej wartości, potem 5 × jego rytm, 10–30 min (pogoda 3–12 h) (tymczasowe, K4) | wiele źródeł raportuje tylko przy zmianie; założony limit na takim źródle zatrzymałby sterowanie przy niezmiennej pogodzie |
| Krótkie palenie (monitor, 1–60 min) | poniżej 10 min (tymczasowe, K4) | liczba krótkich paleń w monitorze i jego sugestie z niej korzystają; zbyt krótki limit ukrywa krótkie cykle, zbyt długi liczy normalne palenia jako krótkie |

Stałe wartości (S-37) — nie są opcjami. Każdy wiersz jest albo postanowiony (podana jest jego
decyzja lub data), albo tymczasowy, K4; wiersz, który nie podaje żadnej decyzji — „istniejące”,
„powód do potwierdzenia” lub sam powód — jest tymczasowy, K4. „Powód do potwierdzenia” oznacza
wartość, której powód nie jest jeszcze zapisany; użytkownik przegląda każdą tymczasową wartość w K4.

| Wartość | Gdzie | Dlaczego |
|---|---|---|
| Krok sterowania 10 s | `const.py` | grzanie od razu podąża za strefami |
| Podtrzymanie 30 s | `control_config.py` | OTGW potrzebuje `CS` co najmniej raz na minutę |
| Najniższe `CS` OTGW 8 °C | `transport/writers.py` | poniżej 8 °C nadpisanie nigdy nie wygasa |
| Limit czasu potwierdzenia 120 s; tolerancja 0.5 K — także strefa nieczułości dla małych zmian krzywej, co ogranicza liczbę startów (symulacja: x1.20 przy +8 °C z nią, x1.36 bez niej); granica, przy której woda jest trzymana (najniższa lub najwyższa temperatura wody, maksimum lub potrzeba obiegu, maksimum kotła), jest zapisywana dokładnie, gdy rampa ją osiągnie, powyżej 0.05 K (F14, J4 z 2026-10-14) | `core/guards.py`, `core/loop.py` | tymczasowe, K4 (powód do potwierdzenia) |
| Odstęp zapisu co najmniej 5 s | `core/guards.py` | jeden zapis na krok |
| Własne wygaśnięcie wtyczki po 60 s ciszy | `core/guards.py` | nadpisanie OTGW wygasa po około minucie |
| Okno ponownego zapisu 24 h | `core/guards.py` | postanowione 2026-09-25 |
| Ponowienie oddania sterowania co 60 s | `control.py` | istniejące |
| Utrata łączności: 5 min nieświeże w ciągu 10 min; powrót po 60 s świeżych | `core/controller.py` | 5 min postanowione 2026-09-25; okno i powrót tymczasowe, K4 |
| Alarm „strefa nieznana” po 30 min | `control.py` | tymczasowe, K4 (powód do potwierdzenia) |
| Utrzymanie temperatury zewnętrznej 3 h; stała czasowa temperatury zewnętrznej 3 h | `core/curve.py` | utrzymanie: decyzja 9; stała czasowa: tymczasowe, K4 (powód do potwierdzenia; Open after 0.2.2, #27) |
| Zawieszony czujnik: jedna wartość trzymana 12 h, gdy pogoda zmienia się o 3 K lub więcej; odchylenie 6 K na przestrzeni co najmniej 2 h nakładających się danych | `core/signal_check.py` | tymczasowe, K4 (powód do potwierdzenia) |
| Korekta komfortu +3 K (domyślna wartość jej limitu, opcja od 0.5 do 10 K od G11), 30 min na K, 3 h na krawędzi, 1 K powyżej zatrzymuje wzrost; zaspokojona poniżej 70 %, brakuje 0.3 K | `core/controller.py` | postanowione 2026-09-25 |
| Ochrona przed mrozem nie ogrzewa: 2 h, 0.5 K | `core/controller.py` | tymczasowe, K4 (powód do potwierdzenia) |
| Strefa pobiera ciepło przy otwarciu powyżej 5 %, nasycona przy 95 % — dla nauki, alarmów i historii; to, czy strefa woła, wynika zamiast tego z reguły VT (powyżej 0, 2026-10-14) | `core/readings.py` | istniejące |
| Ciepło dostępne: zasilanie 2 K powyżej powrotu albo 3 K powyżej temperatury pokoju, gdy nie ma powrotu; histereza 1 K | `core/heat.py` | tymczasowe, K4 (I8, decyzja C1) |
| Wiarygodny odczyt pokoju od −30 do 45 °C, jedna reguła dla każdego odczytu pokoju | `core/limits.py` | węższy zakres ukryłby zimny pokój przed ochroną przed mrozem (S-06; tymczasowe, K4) |
| Wstrzymania nauki: wahanie 5 K w 30 min, wstrzymanie co najmniej 10 min (pobór lub „wyłączone” z powodu usterki kotła wstrzymuje nawet w ciągu 10 min od wznowienia), wznowienie w granicach 3 K, najdłuższe wstrzymanie 60 min od jego początku, odczyt zwrotny po 1 min | `core/learning.py` | istniejące; reguły poboru i usterki oraz początek limitu: decyzja 14 z `docs/en/development/plans/plan-0.2.3.md` |
| Ostrzeżenie o małym przepływie po 15 min | `core/alarms.py` | istniejące |
| Okres rozpoznania najwyżej 10 min; karencja 10 min | `core/zone_watch.py` | postanowione (decyzja 3) |
| Przekaźnik poza zasięgiem 5 min | sterowanie | postanowione |
| Okno cofnięcia bez śladu 60 min; wysłanie wyjaśnia cofnięcie w ciągu 120 s od nowej wartości, jedyny ponowny zapis nigdy | strażnik zapisu | postanowione (odpowiedź E; ponowny zapis, 2026-10-13) |
| Samoczynny powrót po 60 min bez obcej wartości | `control.py` | postanowione |
| Przekaźnik w zadeklarowanym stanie po zaniku zasilania: ostrzeżenie przy 3 w ciągu 24 h, czwarty powoduje ustąpienie | sterowanie | postanowione (odpowiedzi D, N) |
| Awaria własnego monitora wtyczki: oddanie sterowania po 5 min | sterowanie | postanowione (odpowiedź I) |
| Opóźnienie włączenia 0–600 s co 10 | opcje | postanowione (decyzja 5) |
| „Wyłączone” co najmniej 1 K poniżej najniższej temperatury wody; odrzucane w granicach 0.5 K od wartości oddania sterowania „własne sterowanie” | limity | postanowione (P-43, S-49) |
| Kontrola przekaźnika 5 min; ślepe powtórzenia co odstęp powtarzania; wygaśnięcie zadeklarowanego zegara w ciągu 60 s od jego pełnej wielokrotności, najwyżej 3×, odnowienie co min(zegar ÷ 2, odstęp powtarzania); przekaźnik, który przestaje przyjmować polecenia: 3 kontrole z rzędu (około 15 min) | `core/relay.py` (decyzja 6 z 0.2.3) | tymczasowe, K4 |
| Trzymane wartości wysyłane ponownie co 5 min; `CH=` OTGW z każdym podtrzymaniem `CS` (30 s) | sterowanie | tymczasowe, K4; `CH=` żyje w pamięci PIC, a reset PIC bez śladu inaczej zgubiłby „wyłączone” nawet na 5 min |
| „Polecenia zgubione” przy 3 w ciągu 24 h, czyszczone po 24 h bez zgubienia; okno śladu 5 min | strażnik zapisu | tymczasowe, K4 |
| Różnica oceniana po 2 krokach (20 s) | strażnik zapisu | tymczasowe, K4 |
| Zignorowane od początku: nigdy niepokazywane przez ponad 120 s po każdym z pierwszych 3 wysłań | strażnik zapisu | tymczasowe, K4 |
| Obcięte: jedna niższa wartość w granicach 0.5 K przy co najmniej 2 wysłanych wartościach oddalonych od siebie o co najmniej 1 K | strażnik zapisu | tymczasowe, K4 |
| „Brak potwierdzenia” po 5 min | strażnik zapisu | tymczasowe, K4 |
| Echo stanu kotła nieoceniane w ciągu 2 min od poboru | strażnik zapisu | tymczasowe, K4 |
| Oddanie sterowania przejęte przez inny sterownik po 2 ponowieniach | oddanie sterowania | tymczasowe, K4 |
| Poziom alarmu liczy się po utrzymaniu 5 min; powiadomienie zamyka się po 60 min w zakresie; nieznane wejście trzymane 60 min, potem nieznane | alarmy | tymczasowe, K4 |
| Usterka kotła zatrzymuje grzanie po 5 min trwania | sterowanie | tymczasowe, K4 |
| Ostrzeżenie o termostacie ściennym poniżej 15 °C | monitor | tymczasowe, K4 |
| Oddanie sterowania przez limit czasu zwolnione w granicach 0.5 K od wartości bazowej, albo oddalone o 0.5 K zarówno od ostatniej wartości wtyczki, jak i od najniższej; „oddanie sterowania nie powiodło się” 3 min po limicie czasu urządzenia (podawanym w formularzu) | oddanie sterowania | tymczasowe, K4 (S-20; decyzja 5 z `docs/en/development/plans/plan-0.2.3.md`) |
| Okno dowodu grzania przekaźnika 30 min po „włączony” | sterowanie | dłuższe niż częsta 20-minutowa blokada ponownego startu; tymczasowe, K4 |
| „Brak oznak, że kocioł grzeje” na ścieżkach temperatury wody: 30 min trwania poleconego grzania, gdy strefa woła, a płomień jest znany jako zgaszony (albo, gdy nieznany, bez wzrostu zasilania o 5 K) | sterowanie (decyzja 2 z 0.2.3) | dłuższe niż częsta 20-minutowa blokada ponownego startu, jak okno przekaźnika; tymczasowe, K4 |
| „Nie warto” tylko przy ocenie co najmniej 3 z 4 kryteriów (2 z 3 dla kotła niekondensacyjnego) | werdykt | tymczasowe, K4 (S-32) |
| „Oddane w mrozie” poniżej progu mrozu, kasowane przy zwolnieniu | alarmy | tymczasowe, K4 (S-57) |
| Sugestia najniższej temperatury wody: odniesienie + 2 K, zaokrąglone w górę do 0.5 °C, poniżej górnych limitów | monitor | tymczasowe, K4 |
| Kryterium startów J4: w ciągu 24 h przy +8 °C i przy −5 °C, każde z dobowym wahaniem temperatury zewnętrznej ±3 K, co najwyżej tyle startów na godzinę, ile daje własna regulacja kotła, × 1.10, przy czym średnia temperatura każdego pokoju jest co najwyżej o 0.3 K niższa od jego średniej przy tej regulacji (równy komfort); test z wahaniem to ścisły xfail do K4 | akceptacja | tymczasowe, K4: dopuszczalny stosunek jest tam postanowiony (S-15; decyzja 8 z `docs/en/development/plans/plan-0.2.3.md`) |
| Czekanie na spóźniony raport: 60 s przy starcie; przy zatrzymaniu całe oddanie sterowania w 15 s, każdy zapis ograniczony do 3 s, czekanie na odczyt zwrotny min(5 s, pozostały czas) | oddanie sterowania | Home Assistant daje wszystkim zadaniom zamknięcia razem 20 s (Q3.3); urządzenie ESPHome raportuje w około 60 s od startu, do około 74 s bez mDNS — 90 s to alternatywa (Q3.5); tymczasowe, K4 |
| Ostatnie polecenie zapisane od razu przy zmianie o 1.0 K | stan sterowania (V3) | tymczasowe, K4 (powód do potwierdzenia) |
| Okno zwolnienia OTGW 60 s | oddanie sterowania (V4) | tymczasowe, K4 (powód do potwierdzenia) |
| Alarm zwolnienia trzymanego po 10 s; przejęcie przez inny sterownik po 2 sprawdzeniach w odstępie 60 s (3 w ciągu 120 s, gdy nieznana jest c.w.u., żadnego w ciągu 120 s od poboru) | oddanie sterowania (V5) | tymczasowe, K4 (powód do potwierdzenia) |
| Awaria monitora: 300 s w ciągu 600 s; sterowanie wraca po 60 s bez nieudanego odświeżenia | sterowanie (V6) | 300 s postanowione (odpowiedź I); reszta tymczasowa, K4 |
| Zgłoszenie „blokada zatrzymała grzanie” po 60 s | sterowanie (V7) | tymczasowe, K4 (powód do potwierdzenia) |
| Wspólne cofnięcie obu celów w ciągu 20 s liczone jako jedno zgubienie; próba ze śladem nie jest liczona do „zignorowane od początku” | strażnik zapisu (X1) | tymczasowe, K4 (powód do potwierdzenia) |
| Karencja P-105 600 s | `control.py` (X3) | tymczasowe, K4 (powód do potwierdzenia) |
| Histereza alarmu obiegu 1 K; jego czas 1–120 min; korekta komfortu najwyżej 3 K dziennie; limit wstrzymania nauki 1 h od jego początku (decyzja 14 z `docs/en/development/plans/plan-0.2.3.md`) | sterowanie (X4) | tymczasowe, K4 (powód do potwierdzenia) |
| Skrajna pogoda (reguła 5 zasady 13): temperatura zewnętrzna poniżej projektowej temperatury zewnętrznej albo zmieniająca się szybciej niż 2 K na godzinę | korekta komfortu (decyzja 11 z `docs/en/development/plans/plan-0.2.3.md`) | tymczasowe, K4: dobowe wahanie ±3 K zmienia temperaturę najwyżej o około 0.8 K na godzinę; przechodzący front zmienia ją szybciej |
| Projektowa temperatura zasilania co najmniej temperatura pokoju + 5 K; projektowa temperatura zewnętrzna co najwyżej temperatura pokoju − 10 K | formularz (X5) | tymczasowe, K4 (powód do potwierdzenia) |
| Dowody dla sugestii: 7 dni, 20 paleń, udział 0.5, pasma 1 K, otwarcie 50 %, +2 K, 2 K poniżej górnych limitów; zgłoszenie dotyczące termostatu ściennego po 30 min; dolny próg migracji 25 °C | monitor (X6) | tymczasowe, K4 (powód do potwierdzenia) |
| Zgłoszenie błędu konfiguracji VT po 10 min | `control.py` (X7) | tymczasowe, K4 (powód do potwierdzenia) |
| Tolerancja zegara przekaźnika 60 s; wzrost zasilania o 5 K jako dowód grzania; 20 zapamiętanych kontekstów | sterowanie (X8) | tymczasowe, K4 (powód do potwierdzenia) |
| Utrzymanie alarmów 5 min; nieznane wejście trzymane 1 h; 50 % znanego płomienia; limit − 2; 2 K; rozpiętość nachylenia 10 K; 0.05 bar/K; 40 °C; 0.1 bar; próbka ciśnienia co 10 min, pobierana po 10 min bez płomienia | `core/alarms.py` (Y1) | tymczasowe, K4 (powód do potwierdzenia) |
| Wnioskowanie o c.w.u. 0.35–0.65; 12 h; 6 h; 10 min; 1 h | monitor (Y2) | tymczasowe, K4 (powód do potwierdzenia) |
| Model budynku: 8 K; 12 K; 2 K; 3 z 4; 2 z 3; odczyty temperatury zewnętrznej w granicach −30…+30 °C | monitor (Y3) | tymczasowe, K4 (powód do potwierdzenia) |
| Limit czasu wywołania prognozy 30 s | prognozy (Y4) | tymczasowe, K4 (powód do potwierdzenia) |
| Alarmy startów i zapłonu nieznane, gdy ostatnia analiza jest starsza niż 15 min; zapis ostatniego przebiegu co 10 min | monitor (Y2) | tymczasowe, K4 (powód do potwierdzenia) |
| Zgłoszenie „zamknięta strefa” z ochrony przed mrozem aktualizowane przy zmianie o 1 K; czekanie 60 s na odtworzenie stanu włącznika sterowania | sterowanie (X4, V3) | tymczasowe, K4 (powód do potwierdzenia) |
| Limit czasu zapisu 10 s; krok sterowania liczy najwyżej 60 s | sterowanie | tymczasowe, K4 (powód do potwierdzenia) |
| Próg „dolej wody” przyjmowany w granicach 0.1–2.0 bar | opcje (Y1) | tymczasowe, K4 (powód do potwierdzenia) |
| Wywołania nauki SmartPI przekraczają limit czasu po 5 s, w ramach 15-sekundowego budżetu zatrzymania | `control.py` | tymczasowe, K4 (powód do potwierdzenia) |
| Minimalna wersja VT 10.2.0 (zewnętrzne menedżery funkcji ładują się od niej; 10.5.1 jest testowana) | `vtherm_link.py` | tymczasowe, K4 (Q3.1) |
| Uruchomiony termostat, który nie pokazuje wartości strefy w ciągu 15 min: zgłoszenie naprawy „przeładuj VT” | `feature_manager.py` | tymczasowe, K4 (powód do potwierdzenia) |
| Dzień się liczy, gdy 90 % jest znane; jego stopniodni wymagają 80 % | monitor (Y2) | tymczasowe, K4 (powód do potwierdzenia) |
| Sugestia najniższej temperatury wody nigdy powyżej 50 °C | monitor (X6) | tymczasowe, K4 (powód do potwierdzenia) |
| Sterowanie czeka na odczyt zwrotny bramki: zgłoszenie naprawy po 5 min, na poziomie błędu tam, gdzie oddanie sterowania zatrzymuje grzanie | sterowanie (Z4-10) | tymczasowe, K4 |
| Polecenie zignorowane od początku tam, gdzie oddanie sterowania zatrzymuje grzanie: zgłoszenie naprawy na poziomie błędu | sterowanie (Z4-11) | decyzja 6 zachowana (bez oddania sterowania, bez blokady) |
| Niezadeklarowany zegar przekaźnika: wyłączenia w ciągu 60 s od tego samego czasu trwania włączenia albo od jego całkowitej wielokrotności do 3×, przy zegarze 9 min lub dłuższym (10 min minus tolerancja 60 s); po rozpoznaniu odnawiany co min(długość ÷ 2, odstęp powtarzania), jego długość i wyłączenia zapisane | sterowanie (Z4R-02, Z4R2-01, Z4R2-05) | dolna granica 10 min — decyzja użytkownika z 2026-10-03, jej tolerancja 60 s — KD-02; reszta tymczasowa, K4 |
| Najkrótszy zegar przekaźnika: 10 min zadeklarowane, rozpoznawane od 9 min (dozwolony pomiar krótszy o minutę, KD-02) — krótszy zadeklarowany jest odrzucany przez formularz, a gdy jest zapisany, czytany jako „nie wiem”; krótsze regularne wyłączenia są liczone, czwarte w ciągu 24 h to ustąpienie ze zgłoszeniem nazywającym ich długość | przekaźnik, opcje, sterowanie (K4.2) | decyzja użytkownika z 2026-10-03 |
| Nastawa niepokazana: „brak potwierdzenia” i zgłoszenie naprawy po 5 min znanego odczytu zwrotnego pokazującego inną wartość; na poziomie błędu tam, gdzie oddanie sterowania zatrzymuje grzanie | strażnik zapisu, sterowanie (Z4R2-03) | tymczasowe, K4 |
| Poprzedni stan celu dwustanowego — włączenie i wyłączenie grzania, włącznik sterowania zewnętrznego niewidziany jako włączony — zwolniony z oceny najwyżej 300 s po wysłaniu, łącznie z wartością sprzed wtyczki; nowa wartość potwierdzana odczytem zwrotnym tylko przez własne echo (raport co najmniej tak nowy jak wysłanie, który nie może być echem wcześniejszego wysłania) | strażnik zapisu, sterowanie (Z4R2-03, Z4R3-01) | decyzja użytkownika z 2026-10-03 |
| Włączenie i wyłączenie grzania zacięte: oceniane, gdy jego odczyt zwrotny nie zmienił się, podczas gdy drugi stan wysłano co najmniej dwa razy, każdy niepokazany przez 3 × najdłuższe z ostatnich 10 opóźnień echa (uznawane od 3 ech) + 30 s, pierwszy 5 min temu lub wcześniej | strażnik zapisu (KD-01, KDF-01) | tymczasowe, K4 |

Kroki z `docs/en/development/plans/plan-0.2.2.md`, które budują te wartości, zapisują ich powody;
wartość, której krok potrzebuje poza tą tabelą, jest dodawana z „powód do potwierdzenia w K4”, jako diff do zgody.
### Plan prac nad prognozą

| Krok | Użycie prognozy | Etap | Wydanie |
|---|---|---|---|
| FC0 | zapisywanie migawek prognozy od pierwszego dnia | Monitor | 0.1 |
| FC1 | ~~przełączanie lato/zima na podstawie prognozy na kilka dni~~ — skreślone przez użytkownika 2026-10-10: lato i zima zostają po stronie VT | — | — |
| FC2 | planowanie przeciwdziałania cyklowaniu na łagodne godziny z wyprzedzeniem (do rozstrzygnięcia wobec zasady 12, decyzja 13) | Przeciwdziałanie cyklowaniu | 0.3 |
| FC3 | wyprzedzanie dla wolnych grzejników (podłogówka) | Prognoza | 0.5 |
| FC4 | korekta krzywej o wiatr i słońce | później | później |

FC0 jest pierwszy, bo rejestrator nie przechowuje prognoz: HA udostępnia je tylko przez usługę
`weather.get_forecasts`, a nie jako atrybuty encji (sprawdzone 2026-09-24). Wtyczka sama zapisuje
migawki, żeby mierzyć błąd prognozy dla każdego horyzontu i uczyć się czasu wyprzedzenia — FC3 bez
nich nie ma z czego się uczyć. Prognozy są czytane z encji pogody HA; sama wtyczka nigdy nie łączy
się z internetem.

Źródło: dowolna encja pogody HA, którą wybierze użytkownik. Prognoza godzinowa włącza FC2 i FC3;
źródło z samą prognozą dzienną wyłącza je i pokazuje widoczny powód.

## 8. Istniejące rozwiązania — co z nich bierzemy

### SAT (Smart Autotune Thermostat)

Tylko pomysły — napisane od nowa. Żaden kod SAT nie jest kopiowany, więc licencja GPL-3.0 SAT nie
dotyczy tej wtyczki.

| Pomysł | Moduł SAT | Gdzie tutaj |
|---|---|---|
| Cykl pracy wyliczany z przeregulowania: `(requested − reference) / (actual flow − reference)` | `pwm.py` | Przeciwdziałanie cyklowaniu |
| Budżet startów na godzinę zamiast stałej przerwy | `pwm.py` | Przeciwdziałanie cyklowaniu (do rozstrzygnięcia wobec zasady 12, decyzja 13) |
| Filtrowanie próbek do nauki (stabilna modulacja, zasilanie blisko nastawy, brak pracy w cyklach) | `minimum_setpoint.py` | Nauka po stronie wody |
| Temperatura powrotu jako korekta minimalnej nastawy | `minimum_setpoint.py` | Dostrajanie krzywej (kondensacja) |
| Ograniczone poprawki parametrów ze średnią z ostatnich optimów | `heating_curve.py` | Dostrajanie krzywej |
| Świeży odczyt zasilania zaraz po zapisie nastawy | `mqtt/opentherm.py` | Później (§9, S-60) |
| Procedura kalibracji przeregulowania | `overshoot_protection.py` | Później (§9, S-60) |
| Szacunek zużycia gazu na podstawie modulacji | — | Monitor |

**Nie bierzemy:** jego regulatora pokojowego, jego stałych (np. minimalnego czasu palenia około
trzech minut), plików producentów (S-59).

**Gdzie robimy to lepiej:** sterowanie oddane przy wyładowaniu wtyczki, sprawdzenie łączności przed
zapisem, jawne podtrzymanie — SAT wysyła nastawę tylko wtedy, gdy działa jego pętla.

### Google Nest

| Funkcja Nest | Tutaj | Etap |
|---|---|---|
| Długie palenie przy niskiej temperaturze wody (OpenTherm + True Radiant) | główna strategia: nisko, długo, rzadko | Krzywa, Przeciwdziałanie cyklowaniu |
| Seasonal Savings | sezonowe dostrojenie **krzywej** (nie nastaw pokojowych) | Dostrajanie krzywej |
| Home Report / Energy History | raport wyjaśniający zmiany (pogoda / c.w.u. / ustawienia) | Monitor |
| Furnace Heads-Up | wczesne ostrzeżenie: spaliny, zapłony, ciśnienie, histereza | Monitor |
| Leaf | wskaźnik kondensacji | Później (§9, S-60) |
| Aktualna pogoda i prognoza na najbliższe godziny | efektywna temperatura zewnętrzna, potem plan prac nad prognozą | Krzywa, Prognoza |
| Wczesne wyłączenie True Radiant dla wolnych układów | wcześniejsze obniżenie temperatury wody dla podłogówki | Prognoza |
| Sterowanie c.w.u. przez OpenTherm | szybkie ładowanie, harmonogram | C.w.u. |

**Nie bierzemy:** Auto-Schedule, Home/Away, Early-On, Sunblock, czasu do osiągnięcia temperatury
(warstwa pokoju i obecności — zadanie VT); Rush Hour Rewards (nie dotyczy gazu).

## 9. Później / wyłączone

**Później (poza obecnym zakresem):** nastawa zależna od obciążenia (strategia C); korekta krzywej o
wiatr i słońce (FC4); tryby zużycia gazu (eko / zrównoważony / komfort); emulowany termostat
OpenTherm; wbudowana obsługa kolejnych urządzeń bez zapisywalnych encji (EMS-ESP, ebusd, BSB-LAN, w
miarę potrzeb); gaz szacowany z mocy kotła tam, gdzie nie podano stawek za gaz.

Na razie bez wydania, chyba że użytkownik wskaże je przy K4 (S-60): świeży odczyt zasilania po
zapisie; kalibracja przeregulowania; MemberID kotła i obsługiwane komunikaty; wskaźnik kondensacji;
ustawienia instalatora kotła;
komendy przekaźnika poza włącznikiem i encją termostatu kotła (dowolne akcje VT), jeśli ktoś o to
poprosi; osobna encja echa dla przekaźnika; dla zaawansowanego użytkownika (§4) surowe dane cykli,
odrzucone próbki dopasowania budynku i ręczne zmiany nauczonych wartości; dane kotła odczytane z
integracji jako podpowiadane wartości parametrów (§6).
Sterowanie obiegiem „sterowany osobno” (`docs/en/development/plans/plan-0.2.3.md`, sekcja „Open
after 0.2.3”, pozycja 52) powstaje w 0.2 jako obieg „sterowany przez inną automatykę” (§5; I8.8).
Z przypisanym wydaniem: tryb „zastosuj” najniższej temperatury wody (0.3, gdy symulator pokaże, że
pomaga); termostat ścienny jako rezerwa na wypadek awarii Home Assistanta — w jedną stronę, od VT do
termostatu: użytkownik wybiera encję nastawy termostatu i strefę VT, domyślnie wyłączone;
zaokrąglone do kroku termostatu, nigdy niezapisywane w stałej pamięci termostatu ani bramki, nic nie
wysyłane w okresie rozpoznania (najwcześniej 0.3; `docs/en/development/plans/plan-0.2-i8.md` I1);
grzejniki i podłogówka za zaworem mieszającym jako jeden zapisywany obieg plus bierne obiegi stałe
(0.3). Zapisywana encja i zdarzenie „grzanie zlecone” dla użytkowników, którzy rezygnują z
centralnego kotła VT, planowane na 0.3, powstają już w 0.2 (decyzja użytkownika z 2026-10-14:
wtyczka pokazuje co najmniej to, co pokazuje centralny kocioł VT): **Wezwanie do grzania**
(włączone, wyłączone wraz z powodem, nieznane, gdy wtyczka nie steruje — `core/boiler_call.py`),
wołające urządzenia lub strefy i ich moc zsumowana obok progów oraz zdarzenie
`vtherm_smart_boiler_boiler_call`, gdy wezwanie się zmienia albo start zaczyna czekać na
opóźnienie włączenia VT. Auto-TPI VT nadal czyta tylko centralny kocioł VT, żeby pominąć naukę,
gdy kocioł jest wyłączony: to nie jest do zmiany przez wtyczkę (propozycja dla autorów VT).

**Skreślone przez użytkownika 2026-10-12:** „lepszy sygnał” SmartPI — czytanie wyjścia jego
regulatora (`u_pi`, `u_ff`) zamiast cyklu pracy stref (S-29); jego faza nauki jest czytana od
G11 C, więc z części SmartPI w S-29 nic nie zostaje.

**Skreślone przez użytkownika 2026-10-10** (`docs/en/development/plans/plan-0.2-i8.md` B):
przełączanie lato/zima w jakiejkolwiek formie (FC1), ostrzeżenie o strefach, których kocioł nie
zasila, propozycja dla autorów SmartPI i adaptacyjnego TPI, pole okablowania dla przekaźnika.

**Wyłączone:** pompy ciepła, regulacja pokojowa, sterowanie zaworami, wysyłanie danych na zewnątrz.

## 10. Ocena obok sterowania

Etap Monitor pozwala każdemu użytkownikowi ocenić swoją instalację, przed sterowaniem lub obok
niego: cyklowanie przy małym obciążeniu, czasy palenia, udział kondensacji oraz obciążenie budynku
w porównaniu z minimalną mocą kotła. Zwykli użytkownicy dostają werdykt z powodem; zaawansowani
dostają dane, na których się opiera. Sterowanie można włączyć od pierwszego dnia (decyzja
użytkownika z 2026-10-08). Dopóki użytkownik go nie włączy, kocioł pracuje jak dotąd — pod
centralnym kotłem VT, termostatem ściennym albo własną regulacją — a wtyczka tylko patrzy. Po
włączeniu nic nie rusza samo poza twardymi granicami: woda idzie za krzywą użytkownika, w granicach
najniższej i najwyższej temperatury wody, a jedyna nauka przy sterowaniu, korekta komfortu, jest w
pełnym sterowaniu domyślnie włączona i dodaje najwyżej swój limit (domyślnie 3 K), rosnąc najwyżej o
3 K na dobę (zasady 8 i 13; pasmo dostrajania przyjdzie później). Dlatego tydzień czekania niczego
nie chroni. Werdykt potrzebuje określonej liczby dni danych: domyślnie 7, co najmniej 7, najwyżej
60, liczonych w dniach kalendarzowych od utworzenia wpisu, więc utrata magazynu danych nie zaczyna
ich liczenia od nowa (odpowiedź K). Do tego czasu, a poza sezonem także wtedy, gdy dni mijają bez
dość danych, przełącznik sterowania pokazuje „za mało danych” i mówi, że sterowanie zacznie się bez
werdyktu (S-43). Werdykt jest radą; decyduje użytkownik.

Werdykt opiera się na tym, co zmierzono, i na tym, co zmienia wydane sterowanie:
- „Warto włączyć” pochodzi tylko z problemów, które zmienia sterowanie z 0.2.2; pozostałe są
  pokazane jako „jeszcze nie zmieniane” (S-22, odpowiedź K). Kryterium obciążenia liczy się tylko
  przy wpisanym albo pewnie zmierzonym modelu budynku (pewność co najmniej 0.5); oszacowanie z
  domyślnych wartości orientacyjnych jest tak oznaczone i niczego nie rozstrzyga (S-17). Wpisane
  obciążenie projektowe zawsze wygrywa ze zmierzonym, i teksty o tym mówią.
- „Nie warto” tylko przy co najmniej 3 z 4 ocenionych kryteriów — 2 z 3 dla kotła
  niekondensacyjnego (tymczasowe, K4); w innym razie „za mało danych” (S-32).
- Gaz zmierzony przy wyłączonym palniku — inni odbiorcy na tym samym liczniku — jest podawany osobno
  i nie liczy się jako gaz na ogrzewanie (S-31; tymczasowe, K4).
- Model budynku zasila tylko monitor; jest widoczny i można go zresetować. Ograniczona nauka
  (zasada 13) obejmuje to, czego używa sterowanie.

Werdykt obejmuje okno, które użytkownik może ustawić — domyślnie każdy dzień z danymi. Powstaje z
dziennych podsumowań, które wtyczka trzyma do roku, uzupełnianych przy starcie z rejestratora tak
daleko wstecz, jak sięga rejestrator, więc nie zależy od ustawień rejestratora. Stopniodni to
godzinowa całka z tego, o ile temperatura zewnętrzna jest niższa od progu ogrzewania budynku; gaz na
stopniodzień nie liczy gazu na c.w.u. tam, gdzie znane jest grzanie c.w.u. Starty na godzinę są
liczone po godzinach, w których było ogrzewanie.

## 11. Otwarte decyzje

- Wstrzymanie nauki podczas długich przerw przeciwdziałania cyklowaniu (woda blisko temperatury
  pokojowej, gdy strefa woła o ciepło) — rozstrzygnąć na danych z pierwszych instalacji (przed 0.3).
- Tryb na wzór termostatu z OTGW (0.3): z fizycznym termostatem (nadpisanie) i bez niego
  (wstrzykiwanie `AA` — czy kocioł grzeje według własnej regulacji bez `CS`); wersja firmware, która
  dodała `RT` i `BS`; co przyjmują ESPHome OpenTherm i EMS-ESP (przed 0.3).
- Zdjęcie blokady ze sterowania bez włącznika grzania („wyłączone” jako niska nastawa) oraz z
  niskiego `CS` z decyzji 1 przy pozostawionym `CH`: tylko użytkownik, przy K4, na podstawie badania,
  czy niska nastawa zatrzymuje i kocioł, i jego pompę — nawet jeśli badanie wypadnie dobrze
  (decyzja 11, odpowiedź K; L4 z `docs/en/development/plans/plan-0.2.1.md` zamyka decyzja 11). Już
  zdjęta dla samego EMS-ESP, którego własna nastawa 0 utrzymuje wyłączone grzanie (użytkownik,
  2026-10-08; I6, decyzja 4).
- Z I6 (`docs/en/development/plans/plan-0.2-i6.md`, „Open after I6”): wartości tabeli połączeń (K4);
  scalenie trzech pól najwyższej temperatury wody — kotła, obiegu i sterowania — które krzywa na
  razie podaje osobno (K4; pola obiegu i sterowania scalone w I8, decyzja F2); pelet i biomasa jako
  źródła ciepła; sterowanie dwoma obiegami naraz (0.3; zapisane odpowiedzi zostawiają miejsce na
  drugą konfigurację sterowania — obiegi za stałym zaworem albo sterowane przez inną automatykę obok
  obiegu zasilanego prosto z kotła są sterowane od I8.8); sam tryb temperatury pokojowej (0.3);
  wskazówka, że kocioł często zgłaszający jednocześnie grzanie i c.w.u. może nie mieć priorytetu
  c.w.u.
- Pierwsza opublikowana wersja i zawartość repozytorium (decyzja 16): wersja po niezależnym
  sprawdzeniu 0.2.2 i przy K4 — tymczasowo wersja wstępna 0.2.2b1, potem 0.2.2; zawartość przy K5.
- Tymczasowe decyzje poniżej, oznaczone (K4), użytkownik potwierdza lub zmienia na przeglądzie
  przed tym, zanim cokolwiek trafi do prawdziwego kotła (`docs/en/development/plans/plan-0.2.md`,
  K4).

**Postanowione**

- Licencja: **Apache-2.0** (2026-09-24). Cała logika i kod są pisane od zera; żaden kod nie jest
  kopiowany z żadnego projektu, inne projekty są tylko źródłem pomysłów. Plik `NOTICE` zawiera
  uznanie autorstwa, które muszą zachować kopie i prace pochodne.
- Pasmo dostrajania: Niskie / Średnie / Wysokie = 3 / 8 / 15 % różnicy między zasilaniem a pokojem
  przy bieżącej temperaturze zewnętrznej, nigdy poniżej 1 K; Własne dla zaawansowanych
  użytkowników. Poza pasmem: tylko sugestie (tymczasowe, K4).
- Zegary: krok sterowania co 10 s, który sprawdza świeżość i włącza oraz wyłącza grzanie zgodnie z
  zapotrzebowaniem stref; temperatura wody jest ustalana co odstęp decyzji (opcja, domyślnie 5 min,
  domyślny cykl VT — wtyczka nie czyta cykli stref); podtrzymanie co 30 s tam, gdzie ścieżka zapisu
  go potrzebuje — OTGW wymaga `CS` co najmniej raz na minutę, 30 s zostawia zapas.
- Baza sprzętu OTGW: nie dołączamy jej. Wtyczka używa MemberID kotła i obsługiwanych komunikatów,
  gdy integracja je udostępnia; profile kotłów są własne.
- 0.2 steruje tylko w trybie nastawy zasilania; tryb wartości pokojowych przychodzi w 0.3
  (2026-09-24); zmieniono mu nazwę na tryb na wzór termostatu, a użytkownik określił go na nowo
  2026-10-10 (§5).
- 0.2 obsługuje każdą ścieżkę zapisu, dla każdej instalacji: zapisywalną encję wybraną przez
  użytkownika oraz wbudowany OTGW przez `opentherm_gw` albo jego firmware przez MQTT (2026-09-24).
- GitHub i każda publikacja przychodzą po 0.2.2 — 0.2.1 i 0.2.2 poprawiają 0.2 po jego przeglądach;
  pierwsza wersja wstępna to 0.2.2b1 (tymczasowo, decyzja 16) i najpierw tylko monitoruje, bo
  sterowanie jest domyślnie wyłączone (2026-09-24, 2026-09-25, 2026-09-27).
- Zapisywalne encje nastawy zasilania (badanie F1, 2026-09-24): ESPHome `opentherm` (`number`,
  trzymana przez ESP, które samo ją powtarza), DIYLess (ESPHome albo jego własny `climate`), EMS-ESP
  (`selflowtemp` wygasający — powtarzany w ciągu minuty; `heatingtemp` zapisywany na stałe).
  Firmware OTGW do 2.0.0-alpha nie ma żadnej; jego komendy MQTT są ścieżką. Występują wszystkie trzy
  rodzaje, więc wybrana encja ma zadeklarowany typ zapisu: wygasający, zapisywany na stałe,
  trzymany albo nieznany. Sterowanie zapisuje tylko do celów wygasających lub trzymanych; wtyczka
  nigdy nie zapisuje do celu zapisywanego na stałe ani nieznanego (decyzja użytkownika z
  2026-09-25).
- OTGW (badania F3, F5–F7): topologia jest deklarowana w konfiguracji — trybu bramki i podłączonego
  termostatu nie da się wiarygodnie odczytać przez Home Assistant. Z termostatem każdy awaryjny
  powrót (`CS=0`, wygaśnięcie, zatrzymanie Home Assistanta) oddaje sterowanie termostatowi; bez
  termostatu (samodzielnie) każdy awaryjny powrót kończy grzanie; bramka w trybie monitora nie
  pozwala na sterowanie — tryb sterowania „tylko monitorowanie” (I8 B7: to już nie topologia;
  wersja podrzędna 16). „Każdy awaryjny powrót oddaje sterowanie termostatowi” dotyczy tylko
  termostatu OpenTherm; styk włącz/wyłącz na zaciskach blokuje sterowanie (decyzja 1, S-01). `CS`
  równe 8 °C lub więcej wygasa, jeśli nie jest powtórzone w ciągu minuty; poniżej 8 °C nigdy nie
  wygasa, więc wtyczka nigdy nie zapisuje go jako nastawy, a „wyłączone” zapisuje jako `CS` równe co
  najmniej 8 °C przy wyłączonym CH. Tryb bramki jest zapisany w bramce; wtyczka nigdy go nie zmienia
  i nigdy nie wysyła `HW=` ani `BW=`, więc bit włączenia c.w.u. zostaje taki, jaki był. `TSet` w
  firmware odzwierciedla to, co wysyła bramka, a nie to, co kocioł przyjmuje. `CH=` jest trzymane:
  bramka utrzymuje `CH=0` mimo `CS=0` i wygaśnięcia nadpisania, aż do `CH=1` albo do zresetowania
  jej PIC, i stosuje je do każdego późniejszego `CS` oraz do zapotrzebowania termostatu
  włącz/wyłącz, a `TSet` nadal niesie `CS` przy `CH=0` (firmware PIC 6.6, ustalone w przeglądzie z
  2026-09-24). Oddanie sterowania to bezpieczne oddanie sterowania: `CS` na najniższej temperaturze
  wody, `CH=1`, potem `CS=0`.
- Auto-TPI (badanie F2): bez centralnego kotła VT Auto-TPI nigdy nie uczy się w strefach oznaczonych
  jako „używane przez centralny kocioł”; wtyczka tworzy zgłoszenie naprawy z ich nazwami, które
  mówi, co kosztuje jego porada. Jest to wykrywane, a nie wstrzymywane, bo `set_auto_tpi_mode` nie
  jest czystym wstrzymaniem; wstrzymanie przyjdzie w wydaniu ustalonym przy K4 (S-29).
- Menedżer funkcji VT (badanie F4): rejestrowany, gdy tylko istnieje API VT; działający już
  termostat przejmuje go przy następnym przeładowaniu VT, którego wtyczka nigdy nie wywołuje.
- Decyzje użytkownika z 2026-09-25: VT decyduje, czy grzać, nic, co wtyczka liczy lub odmierza w
  czasie, nie powstrzymuje grzania wbrew VT, a to, czego wtyczka się uczy, mieści się w twardych
  granicach (zasady 12 i 13); ochrona przed mrozem jako wyjątek, dla wszystkich stref albo jednej
  wybranej (2026-09-26/27: jeden z wymienionych wyjątków zasady 12, grzanie tylko stref, które mogą
  przyjąć ciepło); lato i zimę wyznacza VT; tryby centralne VT działają przez zapotrzebowanie stref,
  a „Stopped” nie jest oddaniem sterowania; utrata łączności z kotłem podnosi alarm i oddaje
  sterowanie w każdej topologii — samodzielnie grzanie się zatrzymuje (2026-09-26/27: przekaźnik
  dostaje alarm, a nie oddanie sterowania); granice korekty komfortu; nic nie zapisywane w trwałej
  pamięci kotła; wartość, która nigdy nie została potwierdzona względem innej ustabilizowanej
  wartości, liczy się jako zmieniona z zewnątrz (2026-09-26/27: zastąpione czterema klasami z
  decyzji 6); gdy część stref jest nieznana, decydują znane, z alarmem (2026-09-26/27: po 10 min
  karencji, decyzja 3) (§7). Dla monitora: okno werdyktu, stopniodni i starty na godzinę (§10);
  „ciepła woda dostępna” jest nieznana, dopóki nieznane jest zasilanie (§5).
- Decyzje użytkownika z 2026-09-26/27 (`docs/en/development/plans/plan-0.2.2.md`):
  1. Obie topologie bramki pytają, co jest podłączone do zacisków termostatu; sterowanie jest
     zablokowane dla styku włącz/wyłącz i dla odpowiedzi „nie wiem”.
  2. Jedno ustawienie, najniższa temperatura wody, domyślnie 20 °C; 0.2.2 tylko sugeruje wartość.
  3. Okres rozpoznania i karencja 10 min; gdy wszystkie strefy są nieznane, oddanie sterowania
     działającemu termostatowi, w przeciwnym razie brak grzania, z alarmem.
  4. Ochrona przed mrozem grzeje tylko strefy, które mogą przyjąć ciepło; zgłoszenie naprawy dla
     zamkniętej.
  5. Opóźnienie włączenia VT przejęte, 0–600 s, domyślnie 0.
  6. Cztery klasy zmiany z zewnątrz: zgubiona komenda, zignorowana od początku, obcięta, inny
     sterownik.
  7. Tylko błąd wewnętrzny, utrata łączności, inny sterownik, awaria monitora i „grzanie
     wyłączone” zignorowane od początku oddają sterowanie; wszystko inne tylko informuje.
  8. Włączone do decyzji 6.
  9. Ostatnia wartość temperatury zewnętrznej obowiązuje 3 h, potem stała wartość awaryjna albo
     projektowa temperatura zasilania.
  10. Maksimum obiegu ogranicza nastawę; alarm informacyjny powyżej temperatury alarmowej.
  11. Sterowanie bez włącznika grzania jest zablokowane, dopóki użytkownik nie zdejmie blokady przy
      K4.
  12. Odbiegający czujnik temperatury zewnętrznej: wybierana jest niższa temperatura z czujnika i
      encji pogody.
  13. Klasa 3 wchodzi do 0.2.2 bez minimalnych czasów i bez limitu przełączeń; przeciwdziałanie
      cyklowaniu w 0.3 do rozstrzygnięcia wobec zasady 12.
  14. CI pobiera VT 10.5.1 (10.4.0 do 2026-10-13) i SmartPI 0.4.0 z ich tagów na serwerach GitHuba.
  15. J4 wywołuje nagły restart i utratę łączności tylko w kontenerze testowym.
  16. Pierwsza opublikowana wersja po niezależnym sprawdzeniu i przy K4; zawartość przy K5.
  Do tego: reguła braku danych, ochrona kotła na podstawie jego własnej usterki, bezpieczne oddanie
  sterowania, sterowanie włącz/wyłącz przez przekaźnik oraz termostat ścienny na bramce (§5, §7).
- Odpowiedzi użytkownika z 2026-09-27: C, D — przekaźnik przełączony, gdy jest dostępny, to inny
  sterownik, a znaleziony w stanie po zaniku zasilania to restart; E — pojedynczy niewyjaśniony
  powrót to zgubiona komenda, drugi w ciągu godziny, którego nie tłumaczy żadne wysłanie, to inny
  sterownik; F — bez odpowiedzi VT kocioł przechodzi do działającego termostatu, a jeśli go nie ma,
  grzanie ustaje; G — pole „osobny styk” przekaźnika; H — wycofanie się to pełne bezpieczne oddanie
  sterowania; I — awaria własnego monitora wtyczki trwająca 5 min oddaje sterowanie i sterowanie
  wznawia się samo; J — przycisk „Zresetuj korektę komfortu”; K — utracony magazyn danych oznacza
  „sterował”, przełącznik wraca tak, jak zostawił go użytkownik, werdykt liczy tylko to, co zmienia
  0.2.2, zdjęcie blokad czeka do K4, wpis bramki bez odpowiedzi o zaciskach zostaje zatrzymany; L —
  przekaźnik raz ustawiony w stan spoczynku przy wycofaniu się; M — pole „własny regulator
  pokojowy” liczy się na ścieżce przekaźnika tylko ze stanem spoczynku „włączony” i nie jest
  oferowane na bramce; N — czwarty restart przekaźnika w ciągu 24 h to inny sterownik; O —
  „grzanie wyłączone” zignorowane od początku blokuje sterowanie i oddaje je.
- Tymczasowe decyzje o sterowaniu (K4): sterowanie dla co najwyżej jednego obiegu zasilanego prosto
  z kotła, z obiegami za stałym zaworem albo sterowanymi przez inną automatykę obok niego (przy tych
  drugich woda jest trzymana na poziomie ich potrzeby, gdy o nią proszą), i kocioł klasy „nastawa
  zasilania” albo „włącz/wyłącz” (przekaźnik); projektowa temperatura zasilania krzywej jest
  wpisywana, nigdy domyślna; sterowanie jest odrzucane, gdy skonfigurowano własny centralny kocioł VT
  (żaden okres monitorowania go nie wstrzymuje: 2026-10-08); pierwsza nastawa sesji to wartość
  krzywej, a nie rampa od bieżącego zasilania; reakcje na alarmy jak w decyzji 7; ochrona przed
  mrozem w okresie rozpoznania dla stref już znanych; sterowanie wznawia się samo po oddaniu
  sterowania przy wszystkich strefach nieznanych.
- Tymczasowe decyzje o zapisie (K4): dane kotła są dostępne, gdy znany jest płomień i zasilanie —
  stały odczyt nie jest nieświeżym, bo wiele źródeł raportuje tylko przy zmianie; ich wiek liczy się
  tylko przy limicie ustawionym przez użytkownika albo takim, na jaki źródło zapracowało (I6,
  decyzja 9); bez danych nic nie jest zapisywane, a po 5 min podnoszony jest alarm i sterowanie
  zostaje oddane (samodzielnie bramka przestaje grzać w ciągu minuty od ostatniego podtrzymania);
  łącznością przekaźnika jest sam przekaźnik. Nieudany zapis jest wysyłany ponownie w następnym
  kroku; nastawa idzie przed włączeniem/wyłączeniem grzania, które jest powtarzane przy nastawie
  wygasającej. Zmiany widoczne w odczycie zwrotnym idą według czterech klas z decyzji 6, bez reakcji
  do wyboru; zmiana przez inny sterownik jest nadpisywana raz, a w ciągu doby nigdy więcej,
  cokolwiek wtyczka zapisała w międzyczasie; wtedy wtyczka wycofuje się pełnym bezpiecznym oddaniem
  sterowania (odpowiedź H) i nie podejmuje prób wbrew niemu. Wygaśnięcie, które wtyczka sama
  spowodowała (milczenie, gdy dane były nieświeże), nie jest zmianą z zewnątrz. „Wyłączone” idzie
  przez włącznik grzania (wbudowany OTGW: `CH=0` z `CS` równym co najmniej 8 °C); bez niego
  sterowanie jest zablokowane, dopóki użytkownik nie zdejmie blokady przy K4 (odpowiedź K); kocioł,
  który od początku ignoruje „grzanie wyłączone”, jest zablokowany, a sterowanie oddane, dopóki
  użytkownik nie wyłączy i nie włączy sterowania (odpowiedź O). Włącznik grzania jest włączany przy
  oddaniu sterowania tylko tam, gdzie kocioł wraca do termostatu albo do własnego sterowania.
  Oddanie sterowania przez upływ czasu wymaga zapisów wygasających. Nieudane oddanie sterowania jest
  pokazywane i ponawiane co minutę, aż zostanie potwierdzone; przy zatrzymaniu Home Assistanta
  oddanie sterowania następuje, zanim integracje się zatrzymają. Zatrzaski przeżywają restart;
  przełącznik sterowania wraca po restarcie tak, jak zostawił go użytkownik, a jego życzenie jest
  zapisywane od razu; wyłączona encja przełącznika oznacza wyłączone sterowanie (odpowiedź K);
  sterowanie czeka na swoje blokady. Awaria własnego monitora wtyczki trwająca 5 min oddaje
  sterowanie, a sterowanie wznawia się samo, gdy monitor znów działa (odpowiedź I).
- Odpowiedzi na pytania z przeglądu (tymczasowe, K4): 3 — „ciepło płynie” to płomień, gdy jest
  znany, w przeciwnym razie komenda; 5 — uszkodzony albo utracony magazyn danych jest nieczytelny:
  najpierw pełne oddanie sterowania, a dni werdyktu liczą się od utworzenia wpisu; 6 — przełącznik
  wraca tak, jak zostawił go użytkownik, życzenie zapisane od razu; 8 — „ciśnienie 0 = nieznane”
  tylko dla źródeł bramki; 9 — alarm z nieznanym wejściem trzyma swój stan 60 min, potem pokazuje
  „nieznane”; 10 — każdy zapis opcji oprócz poziomu przeładowuje wpis, co oddaje sterowanie, a
  sterowanie potem przywraca kocioł; opcje o tym mówią (tak jak zbudowano; K4 może to zawęzić do
  zapisów, które dotykają sterowania, Z4-08); 11 — ograniczona nauka obejmuje to, czego używa
  sterowanie, a model budynku zasila tylko monitor i jest widoczny i można go zresetować; 12 —
  wpisane obciążenie projektowe zawsze wygrywa; 19 — wybór strefy przyjmuje tylko klimaty VT,
  sprawdzane po stronie serwera (ostrzeżenie o strefach, których kocioł nie zasila, przyjdzie w
  0.3); 20 — diagnostyka działa dla wpisu z błędem konfiguracji.
- Wstrzymania nauki (SmartPI) tylko wtedy, gdy sterowanie działa; sprawdzanie wahań wody idzie za
  nastawą grzania, a nie za niską wartością „wyłączone” (K4).

## 12. Wydanie

Publiczne od 0.2.2 (tymczasowo, decyzja 16) — 0.2 poprawione po jego przeglądach (0.2.1, 0.2.2):
repozytorium GitHub, utworzone po 0.2.2 i instalowane przez HACS jako repozytorium niestandardowe.
0.2.2 przechodzi środowisko testowe, potem działa na instalacji autora — najpierw monitorując, bo
sterowanie jest domyślnie wyłączone — jako wersja wstępna 0.2.2b1, a potem jako wydanie. Która
wersja zostanie opublikowana pierwsza, rozstrzyga się po niezależnym sprawdzeniu 0.2.2 i przy K4;
czy repozytorium zawiera `CLAUDE.md`, plany i przeglądy, a więc czy startuje z czystą historią, przy
K5. HACS instaluje tylko z publicznych repozytoriów, więc repozytorium jest publiczne od pierwszej
wersji wstępnej. Wtyczka wymaga Home Assistanta 2026.9 lub nowszego, czyli wersji, na której jest
testowana. Zgłoszenie do domyślnej listy HACS i do listy wtyczek VT później (przegląd HACS trwa
miesiące). Utworzenie repozytorium i każda publikacja wymagają zgody autora.
