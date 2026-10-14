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

# Współpraca z Versatile Thermostat

1. Ustaw termostaty VT dla pomieszczeń ogrzewanych przez kocioł. Jeśli w VT jest skonfigurowany
   kocioł centralny, odznacz go w centralnej konfiguracji VT i uruchom ponownie Home Assistant:
   jego miejsce zajmuje wtyczka.
2. Dodaj jeden wpis **Smart Boiler for Versatile Thermostat** i wybierz strefy VT, które ogrzewa ten
   kocioł.
3. Wybierz encję, która dostarcza każdy sygnał kotła — do sterowania co najmniej płomień i
   temperaturę zasilania.
4. Pozwól jej monitorować; werdykt pojawi się po 7 dniach danych (domyślnie).
5. Kiedy zechcesz — od pierwszego dnia albo po przeczytaniu werdyktu — ustaw sterowanie w opcjach
   i włącz **Sterowanie (eksperymentalne)**.

Krok po kroku: [przewodnik użytkownika][guide-pl].

## Obok algorytmów stref VT

Wtyczka czyta strefy VT i nigdy nie zmienia ich ustawień ani algorytmów. Termostat każdej strefy
dostaje jeden atrybut, `smart_boiler`: `heat_available` — czy ciepło z kotła dociera teraz do
strefy — i `supply_temperature`, zaokrągloną temperaturę wody, która do niej dociera. Algorytm
strefy może czytać pełne dane o wodzie ([interfejs][water]); SmartPI 0.4.0 z nich nie korzysta.
Nic w VT od niego nie zależy.

Krzywa grzewcza już podnosi temperaturę wody, gdy na zewnątrz robi się zimniej. Niektóre algorytmy
stref też liczą temperaturę zewnętrzną, więc pogoda działa wtedy dwa razy:

- **TPI** (algorytm VT oparty na proporcji czasu grzania) dodaje `tpi_coef_ext` × (nastawa −
  temperatura zewnętrzna) do czasu grzania każdej strefy. Z krzywą wtyczki chłodniejsza pogoda
  daje i cieplejszą wodę, i dłuższe grzanie. To ustawienie VT, osobne w każdej strefie; wtyczka go
  nie zmienia.
- **SmartPI** (0.4.0) uczy się własnego członu zewnętrznego (`u_ff1`, wyuczony współczynnik ×
  (nastawa − temperatura zewnętrzna)). Nie da się go ustawić ani wyłączyć; uczy się przy wodzie,
  którą ustawia wtyczka.

Jak strefa zachowuje się przy obu, zależy od pomieszczenia i algorytmu; wtyczka to opisuje i nie
doradza tych ustawień. Gdy ciepła woda albo duża zmiana temperatury wody zaburza pomieszczenia,
wtyczka wstrzymuje uczenie SmartPI (domyślnie włączone), żeby wywołane przez nią wahania nie
trafiły do modelu SmartPI.

# Obsługiwane urządzenia

| Wymaganie | Wersja |
|---|---|
| Home Assistant | 2026.9 lub nowszy |
| Versatile Thermostat | 10.2.0 lub nowszy (od 10.2.0 ładuje zewnętrzne menedżery funkcji); testowana wersja to 10.5.1 — tymczasowo, do pierwszego wydania |
| `vtherm_api` | 0.5.0 lub nowsza, instalowana z wtyczką |
| SmartPI, Auto-TPI | opcjonalne; działa każdy algorytm stref VT |

Monitorować można każdy kocioł, którego sygnały Home Assistant pokazuje jako encje. Do
sterowania wtyczka zapisuje przez:

| Połączenie | Co wtyczka zapisuje |
|---|---|
| OpenTherm Gateway przez `opentherm_gw` z Home Assistant | nastawę sterującą, powtarzaną co 30 s, i zezwolenie na grzanie |
| Firmware OpenTherm Gateway przez MQTT | to samo, jako polecenia MQTT firmware'u |
| ESPHome OpenTherm | jego liczbę nastawy i przełącznik grzania, trzymane przez ESP |
| EMS-ESP | jego nastawę zasilania, powtarzaną co 30 s; nastawa 0 jako „grzanie wył.” |
| Przekaźnik na zaciskach termostatu pokojowego (kocioł wł./wył.) | tylko włączanie i wyłączanie grzania |
| Inna encja do zapisu (poziom zaawansowany) | to, co wybierzesz, z zadeklarowanym typem zapisu |
| Moduł Wi-Fi kotła, integracja producenta, inna integracja tylko do odczytu | domyślnie nic: monitorowanie |

Nie jest zapisywane nic, co kocioł zachowałby w trwałej pamięci: cel zadeklarowany jako trwały
albo o nieznanym typie nigdy nie jest zapisywany. Do tej pory testowane tylko z symulowanym
kotłem. Szczegóły: [przewodnik, część 5][guide-pl-connect].

# Instalacja

**Nie ma jeszcze wydania.** Gdy się pojawi:

1. W HACS otwórz menu → **Custom repositories**, dodaj
   `https://github.com/Shadow-230/vtherm-smart-boiler` z typem **Integration**.
2. Znajdź **Smart Boiler for Versatile Thermostat** w HACS i pobierz.
3. Uruchom ponownie Home Assistant, potem dodaj integrację w Ustawienia → Urządzenia oraz usługi.

Instalacja ręczna: skopiuj `custom_components/vtherm_smart_boiler/` z wydania do folderu
`custom_components/` w konfiguracji Home Assistant i uruchom go ponownie.

Może istnieć tylko jeden wpis: prowadzi jeden kocioł.

# Encje

Wszystkie należą do jednego urządzenia, nazwanego tak jak wpis (domyślnie „Kocioł”). Encja
monitora istnieje tylko wtedy, gdy wskazane są potrzebne jej sygnały; czujnik **Funkcje** mówi,
które są nieaktywne i dlaczego. Część jest domyślnie ukryta (*ukryta*); **Migawki prognozy** są
domyślnie wyłączone.

**Monitor**

| Encja | Co pokazuje |
|---|---|
| Starty c.o. na godzinę | starty palnika do ogrzewania, na godzinę z ostatnich 24 h; cykle, które mogły być ciepłą wodą, osobno |
| Mediana palenia c.o. | typowa długość cyklu pracy palnika przy ogrzewaniu |
| Godziny palnika c.o. (24 h) *ukryta* | godziny pracy palnika do ogrzewania z ostatnich 24 h |
| Krótkie palenia c.o. *ukryta* | udział cykli krótszych niż długość krótkiego palenia (domyślnie 10 min) |
| Udział kondensacji | udział czasu palenia c.o. z powrotem poniżej 55 °C |
| Stopniodni (7 dni) *ukryta* | stopniodni z tygodnia, liczone od progu grzania |
| Gaz na stopniodzień | gaz na stopniodzień, mierzony wskazanym licznikiem gazu, inaczej szacowany |
| Zużycie wobec wczoraj *ukryta* | zmiana zużycia wobec dnia poprzedniego, rozbita na pogodę, ciepłą wodę, ustawienia i resztę |
| Werdykt sterowania | warto włączyć, nie warto włączać albo jeszcze za mało danych — z uzasadnieniem |
| Problemy z sygnałami | ile wskazanych sygnałów ma problem; stan każdego w atrybutach |
| Funkcje | ile funkcji jest teraz nieaktywnych i dlaczego |
| Współczynnik strat budynku, Próg grzania budynku *ukryte* | używane wartości budynku — twoje, zmierzone albo domyślne — ze źródłem |
| Proponowana najniższa temperatura wody | tylko propozycja, nigdy nie stosowana |
| Migawki prognozy *wyłączona* | ile zapisanych prognoz jest przechowywanych, na przyszłe wydania |
| Strefa krytyczna, obieg … | w każdym obiegu strefa, której własny regulator pracuje teraz najciężej |
| Sygnały | włączony, gdy płomień i zasilanie (oraz przekaźnik) są znane i świeże |
| Problem z czujnikiem zewnętrznym | czujnik zewnętrzny kotła stoi albo nie zgadza się z encją pogody |
| Długie palenie bez nagrzewania | płomień 3 h bez nagrzewania pomieszczeń, z prawdopodobną przyczyną |
| Alarmy (czujniki binarne, włączony = problem) | po jednym na sprawdzenie: ciśnienie wody, spaliny, starty, zapłon, brak przepływu, za gorąca woda w obiegu i pozostałe — [tabela w przewodniku][guide-pl-alarms] |

**Sterowanie**

| Encja | Co pokazuje albo robi |
|---|---|
| Sterowanie (eksperymentalne) | włącza i wyłącza sterowanie; jego atrybuty mówią, co je blokuje i co w twojej instalacji robi oddanie sterowania |
| Stan sterowania | wyłączone, niedozwolone, oddane kotłu, czeka na dane, grzanie, postój, ochrona przed mrozem, nastawa awaryjna albo usterka kotła — z przyczynami |
| Nastawa zasilania ze sterowania | nastawa, jaką potwierdza kocioł; inaczej nieznana, nigdy wartość żądana |
| Wezwanie do grzania | włączone, gdy wtyczka wzywa kocioł do grzania, wyłączone z powodem, gdy nie — w miejsce czujnika kotła centralnego VT; przy zmianie wysyłane jest zdarzenie |
| Wołające o ciepło, Moc wołających | wołające urządzenia (albo strefy) i zsumowana moc stref, każde obok swojego progu, tak jak pokazuje je kocioł centralny VT |
| Sterowanie: … (czujniki binarne) | alarmy sterowania: zapis nieudany lub zignorowany, inny sterownik, oddanie nieudane, utrata łączności z kotłem, nieznana strefa, mróz bez nagrzewania i pozostałe |
| Wyzeruj korektę komfortu | ustawia korektę komfortu z powrotem na 0 |
| Wyzeruj zmierzone straty ciepła, Wyzeruj zmierzony próg grzania | zapominają zmierzone wartości budynku |

Problemy, które wymagają twojej uwagi, pojawiają się też jako zgłoszenia w Ustawienia → Naprawy.

# Jak często odświeżają się dane

- Sygnały kotła i strefy są czytane przy każdej zmianie i co najmniej co **30 s**.
- Sterowanie robi krok co **10 s**; nastawa, która wygasa, jest powtarzana co **30 s**, trzymana
  przez urządzenie — przy zmianie i co 5 minut.
- Wskaźniki monitora i werdykt są liczone co **5 minut**.
- Z encją pogody prognozy są zapisywane co **30 minut** (na przyszłe wydania; sterowanie jeszcze
  z nich nie korzysta).
- Sygnał jest nieświeży po przekroczeniu swojego limitu wieku: domyślnie automatycznego,
  ustawianego osobno dla każdego sygnału ([Świeżość danych][guide-pl-fresh]).

# Co zostaje lokalnie

Wszystko. Wtyczka nie łączy się z żadną usługą w chmurze i nic nie wysyła poza Home Assistant.
Czyta encje, zapisuje tylko do wybranych przez ciebie celów, swój stan i zapisane prognozy trzyma
we własnym magazynie Home Assistant (`.storage`), a jej czujniki trafiają do rejestratora Home
Assistant jak każde inne. Pobrana diagnostyka (urządzenie integracji → Pobierz diagnostykę)
zastępuje identyfikatory encji i bramki, zanim ją komuś przekażesz.

# Opcje i ryzyko

Każda opcja ma ostrożną wartość domyślną, a jej opis w formularzu mówi, co robi i czym ryzykuje.
Najważniejsze — opisane, nie doradzane:

| Opcja | Domyślnie | Co robi i czym ryzykuje |
|---|---|---|
| Sterowanie (przełącznik) | wyłączone | włączone: wtyczka zapisuje do kotła; wyłączone: kocioł pracuje jak dotąd |
| Krzywa grzewcza | temperatura projektowa zasilania bez wartości domyślnej — wpisujesz ją | za wysoka marnuje gaz i każe palnikowi taktować; za niska zostawia pomieszczenia zimne |
| Najniższa temperatura wody | 20 °C (tymczasowo) | za niska: przy łagodnej pogodzie kocioł raz po raz sam staje, a kocioł niekondensacyjny skrapla się w kominie (wartość podaje jego instrukcja) |
| Najwyższa temperatura wody obiegu | 70 °C, gdy pole puste | ogranicza każdą nastawę w obiegach zasilanych prosto z kotła; kocioł może ją przekroczyć o własną histerezę |
| Jej alarm za gorącej wody | maksimum + 5 K przez 10 min | tylko informacja; za wysoki przepuszcza prawdziwe przekroczenie bez słowa |
| Korekta komfortu | włączona, do 3 K (najwyżej 10 K), rośnie najwyżej o 3 K na dobę | podnosi wodę dla pomieszczenia, które nie dochodzi do nastawy; ze strefami TPI może trzymać wodę wyżej i mnożyć starty palnika |
| Opóźnienie włączenia | 0 s | czeka przed włączeniem grzania, dla wolnych zaworów; w tym czasie pomieszczenia nie dostają ciepła |
| Typ zapisu wybranego celu | nieznany — bez zapisu | trzeba zadeklarować „wygasa” albo „trzymany”; zła deklaracja zużywa pamięć kotła albo pozwala wartości wygasnąć |
| Wartość przy oddaniu sterowania | brak — wpisywana razem ze skutkiem | ta sama liczba na jednym urządzeniu znaczy „własne sterowanie”, na innym „bez ciepła” |
| Ochrona przed mrozem | wł. przy 5 °C, wył. przy 7 °C, każda strefa | grzeje tylko strefy, których grzejniki mogą przyjąć ciepło; strefa trzymana przez VT zamknięta dostaje zgłoszenie w Naprawach |
| Reakcje na alarmy | informacja — kilka alarmów zawsze oddaje sterowanie | alarm ustawiony na oddanie zatrzymuje sterowanie, dopóki go nie wyłączysz i nie włączysz |
| Powrót sam po innym sterowniku | wyłączony | włączony: sterowanie wraca 60 minut po ostatniej obcej wartości, choć inny sterownik może wciąż działać |
| Wstrzymywanie uczenia (SmartPI) | włączone | wyłączone: wahania wywołane przez wtyczkę trafiają do modelu SmartPI |

Każda wartość domyślna i jej powód: tabela wartości domyślnych w [specyfikacji, część 7][scope-defaults].
Wartości oznaczone jako tymczasowe są przeglądane przed pierwszym wydaniem.

# Oddanie sterowania

Przy każdym wyjściu — wyłączenie sterowania, alarm ustawiony na oddanie, zatrzymanie Home
Assistant, utrata łączności z kotłem, błąd — wtyczka oddaje kocioł, sprawdza to odczytem zwrotnym
i ponawia aż do potwierdzenia ([bezpieczne oddanie sterowania][guide-pl-hand-back]). Co dalej,
zależy od ścieżki zapisu:

| Ścieżka zapisu | Po oddaniu sterowania |
|---|---|
| Bramka z termostatem OpenTherm | przejmuje termostat; grzanie trwa dalej |
| Bramka bez termostatu (samodzielna) | grzanie **staje**, dopóki sterowanie nie wróci albo nie zadziałasz |
| ESPHome OpenTherm, encja do zapisu | zadeklarowana wartość: „wraca własne sterowanie” albo „grzanie staje” |
| EMS-ESP | nastawa wygasa w około minutę; kocioł wraca do własnego ustawienia |
| Przekaźnik | jego stan po oddaniu: wyłączony (domyślnie) — bez ciepła, chyba że woła termostat podłączony do kotła; włączony — kocioł grzeje według własnego ustawienia |

Po oddaniu obowiązuje maksymalna temperatura wody kotła (albo termostatu ściennego), nie wtyczki.

**Gdy Home Assistant nie działa.** Nic z wtyczki wtedy nie pracuje, więc zaplanuj ręczną drogę
powrotu:

- **Bramka:** nastawa wygasa w ciągu minuty — przejmuje termostat na bramce; bramka samodzielna:
  grzanie staje, dopóki Home Assistant znów nie ruszy.
- **ESPHome OpenTherm:** ESP trzyma ostatnią nastawę i grzanie do swojego restartu (domyślnie po
  15 minutach bez Home Assistant), potem przyjmuje wartości startowe.
- **EMS-ESP:** nastawa wygasa w około minutę; kocioł grzeje według własnego ustawienia.
- **Przekaźnik:** zostaje, jak był; przełącz go ręcznie w jego aplikacji albo na jego stronie.
  Przekaźnik z własnym wyłącznikiem czasowym sam wyłączy grzanie.
- **Inna encja do zapisu:** zależy od urządzenia.

# Termostat ścienny

Na bramce z termostatem OpenTherm, dopóki steruje wtyczka, ustawienie grzania termostatu ściennego
i jego wyłącznik nic nie robią; jego ustawienia ciepłej wody nadal działają. Po oddaniu sterowania
znów grzeje według własnego ustawienia i programu. Jeśli wskażesz jego nastawę, wtyczka ostrzega,
gdy jest nieznana albo niższa niż 15 °C: po oddaniu sterowania dom byłby grzany tylko do niej.
Termostat wł./wył. (dwa przewody) na zaciskach termostatu bramki blokuje sterowanie: bramka po
awarii zachowałaby „grzanie wył.” wtyczki i taki termostat nie mógłby ogrzać domu.

# Ustawienia przekaźnika

Wtyczka nie potrafi odczytać własnych ustawień przekaźnika, więc formularz o nie pyta; każde jest
domyślnie „Nie wiem” i traktowane ostrożnie:

- **Osobny styk** (potwierdzenie) — przekaźnik to osobny styk, a nie ustawienie zapisywane w
  pamięci kotła. Bez tego sterowanie nie ruszy.
- **Zgłasza swój rzeczywisty stan** — tak: wtyczka zapisuje tylko przy różnicy i sprawdza
  przekaźnik; nie albo nie wiem: powtarza polecenie bez potwierdzenia.
- **Stan po zaniku zasilania** — wyłączony: kocioł czeka na Home Assistant; włączony, ostatni
  stan albo nie wiem: po zaniku zasilania kocioł może grzać bez sterowania, dopóki Home Assistant
  nie wróci.
- **Własny wyłącznik czasowy** — brak, długość (10–120 min; „wł.” jest powtarzane w połowie tego
  czasu) albo nie wiem. Czy Shelly liczy swój auto-off od nowa po powtórzonym „wł.”, nie jest
  udokumentowane.
- **Odstęp powtórzeń** — 10–300 s, domyślnie 300 s.
- **Przekaźnik po oddaniu sterowania** — wyłączony (domyślnie) albo włączony.

Więcej: [przewodnik, przekaźnik][guide-pl-relay].

# Przykłady automatyzacji

Identyfikatory encji poniżej są dla wpisu nazwanego „Boiler”; swoje znajdziesz na urządzeniu
integracji.

Powiadom, gdy oddanie kotła się nie powiodło:

```yaml
automation:
  - alias: "Kocioł: oddanie nieudane"
    triggers:
      - trigger: state
        entity_id: binary_sensor.boiler_control_hand_back_failed
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: "Oddanie kotła nie przeszło — sprawdź Ustawienia → Naprawy."
```

Powiadom, gdy werdykt jest gotowy:

```yaml
automation:
  - alias: "Kocioł: werdykt sterowania"
    triggers:
      - trigger: state
        entity_id: sensor.boiler_control_verdict
        to:
          - "worth_it"
          - "not_worth_it"
    actions:
      - action: notify.notify
        data:
          message: "Werdykt sterowania: {{ states('sensor.boiler_control_verdict') }}"
```

Oddaj kocioł przed wizytą serwisu — robi to wyłączenie sterowania:

```yaml
action: switch.turn_off
target:
  entity_id: switch.boiler_control_experimental
```

# Rozwiązywanie problemów

- **Sterowanie się nie włącza albo stan sterowania mówi „Niedozwolone”.** Atrybuty przełącznika
  (`blockers_text`, `blocked_by_text`) mówią, czego brakuje; zgłoszenie w Naprawach zwykle mówi,
  co zrobić.
- **Stan sterowania zostaje „Oddane kotłu”.** Wtyczka się wycofała — inny sterownik, kocioł
  ignorujący „grzanie wył.”, alarm ustawiony na oddanie. Usuń przyczynę, potem wyłącz i włącz
  sterowanie.
- **Werdykt mówi „Jeszcze za mało danych” albo brakuje czujnika.** Czujniki **Funkcje** i
  **Problemy z sygnałami** wskazują brakujące albo nieświeże sygnały.
- **„Sygnały” są wyłączone.** Płomień albo zasilanie jest nieświeże lub nieznane: sprawdź
  integrację kotła albo limit wieku sygnału ([Świeżość danych][guide-pl-fresh]).
- **Włączony alarm.** [Tabela alarmów][guide-pl-alarms] mówi, co każdy znaczy i co zrobić.
- **Logi.** Szczegółowe logowanie:

  ```yaml
  logger:
    logs:
      custom_components.vtherm_smart_boiler: debug
  ```

  Do zgłoszenia problemu dołącz pobraną diagnostykę.

# Znane ograniczenia

- Bez wydania i jeszcze bez pracy z prawdziwym kotłem: testowane z symulowanym kotłem i na
  testowym Home Assistant.
- **Zmiany, których nie widać w odczycie zwrotnym:** grzanie wyłączone albo tryb letni na panelu
  kotła, blokada kotła, aplikacja producenta, limit modulacji innego sterownika, zezwolenie na
  ciepłą wodę, kocioł obcinający nastawę za bramką — bramka wciąż pokazuje wartość wtyczki. Widać
  je tylko po skutkach: korekta komfortu na swoim limicie (po około 4,5 h) albo grzanie
  przeciwmrozowe, które nie ogrzewa pomieszczenia (po 2 h).
- **Kocioł obcinający stałą nastawę** wygląda jak inny sterownik: niższa wartość jest uznawana za
  własny limit kotła dopiero wtedy, gdy wtyczka wysłała wartości różniące się o co najmniej 1 K.
  Przy jednej stałej wartości jest raz zapisywana ponownie, a druga zmiana w ciągu 24 h każe
  wtyczce się wycofać.
- Jeden kocioł na Home Assistant (jeden wpis). Bez pomp ciepła, zaworów i sterowania ciepłą wodą.
- **Strefy VT z zaworem, który nie zamyka się do końca** (w VT „Maksymalny stopień zamknięcia”
  poniżej 100) wymagają VT 10.5 lub nowszego: VT 10.2–10.4 liczy taki zawór na jego minimum jako
  grzejący, więc strefa prosi o ciepło bez przerwy i kocioł może się nigdy nie wyłączać.
- Sterowanie temperaturą wody wymaga przełącznika grzania wł./wył. (poza EMS-ESP); bramka z
  termostatem wł./wył. na zaciskach to tylko monitor.
- Własny kocioł centralny VT musi być wyłączony, a Home Assistant raz uruchomiony ponownie.
- Prognozy są zapisywane, ale sterowanie jeszcze z nich nie korzysta.
- W instalacji Home Assistant poza jego kontenerem albo obrazem systemu Home Assistant instaluje
  razem z wtyczką biblioteki integracji MQTT i OpenTherm Gateway, nawet jeśli nie używasz żadnej z
  nich; bez dostępu do sieci w tym momencie wtyczka się nie uruchomi.
- Wiele wartości jest tymczasowych do przeglądu przed pierwszym wydaniem.

# Usuwanie

1. Możesz najpierw wyłączyć **Sterowanie (eksperymentalne)** i sprawdzić, że kocioł wrócił do
   własnego sterowania.
2. Usuń wpis: Ustawienia → Urządzenia oraz usługi → Smart Boiler for Versatile Thermostat → Usuń.
   Wtyczka oddaje kocioł, wznawia wstrzymane przez siebie uczenie SmartPI i usuwa swój zapisany
   stan i prognozy. Jeśli oddania nie dało się potwierdzić, po usunięciu zostaje zgłoszenie w
   Naprawach: oddaj kocioł ręcznie.
3. Usuń ją w HACS (albo usuń jej folder) i uruchom ponownie Home Assistant.
4. Aby wrócić do kotła centralnego VT, zaznacz go z powrotem w centralnej konfiguracji VT.

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

# Dokumentacja

| Dokument | Co zawiera |
|---|---|
| [Specyfikacja][scope] | co wtyczka robi, jej zasady i wszystkie decyzje |
| [Plan rozwoju][plan] | plan rozwoju, wydania i środowisko testowe |
| [Plany i przeglądy][docs] | historia: plan każdego wydania i przeglądy kodu (po angielsku) |
| 🇬🇧 [User guide][guide] · 🇵🇱 [Przewodnik użytkownika][guide-pl] | wymagania, instalacja, szybki start, jak to działa, podłączenie kotła, bezpieczeństwo, alarmy |
| 🇬🇧 [Technical documentation][technical] · 🇵🇱 [Dokumentacja techniczna][technical-pl] | części integracji, jeden krok sterowania, cykl życia, stan trwały, testy |
| [Dane o wodzie dla algorytmów stref][water] | interfejs, który daje SmartPI i innym algorytmom stref temperaturę wody docierającej do każdej strefy |
| [`CHANGELOG.md`][changelog] | co zmienia każde wydanie (po angielsku) |
| [`CONTRIBUTING.md`][contributing] | jak współtworzyć: gałęzie, testy, zasady (po angielsku) |
| [`LICENSE`][license] | Apache License 2.0 |

Gałąź `main` zawiera te dokumenty; rozwijany kod jest na gałęzi [`dev`][dev] i trafi do `main`
z pierwszym wydaniem.

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
[scope]: docs/pl/specification/scope.md
[scope-defaults]: docs/pl/specification/scope.md#7-funkcje-według-etapów
[plan]: docs/pl/development/plan.md
[docs]: docs/en/development/
[guide]: docs/en/user-guide/user-guide.md
[guide-pl]: docs/pl/user-guide/user-guide.md
[guide-pl-connect]: docs/pl/user-guide/user-guide.md#5-podłączenie-kotła
[guide-pl-hand-back]: docs/pl/user-guide/user-guide.md#61-bezpieczne-oddanie-sterowania
[guide-pl-relay]: docs/pl/user-guide/user-guide.md#54-przekaźnik-kocioł-włwył
[guide-pl-fresh]: docs/pl/user-guide/user-guide.md#68-świeżość-danych
[guide-pl-alarms]: docs/pl/user-guide/user-guide.md#7-alarmy-i-zgłoszenia-w-naprawach
[technical]: docs/en/technical/technical.md
[technical-pl]: docs/pl/technical/technical.md
[water]: docs/pl/specification/water-interface.md
[changelog]: CHANGELOG.md
[contributing]: CONTRIBUTING.md
[license]: LICENSE
[releases]: https://github.com/Shadow-230/vtherm-smart-boiler/releases
[commits]: https://github.com/Shadow-230/vtherm-smart-boiler/commits/dev
[status-shield]: https://img.shields.io/badge/status-in%20development-orange.svg?style=for-the-badge
[release-shield]: https://img.shields.io/badge/release-none%20yet-lightgrey.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/m/Shadow-230/vtherm-smart-boiler/dev.svg?style=for-the-badge
[license-shield]: https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=for-the-badge
[hacs-shield]: https://img.shields.io/badge/HACS-not%20yet-lightgrey.svg?style=for-the-badge
[bmc]: https://buymeacoffee.com/shadow23
[bmc-shield]: https://img.shields.io/badge/buy%20me%20a%20coffee-shadow23-ffdd00.svg?style=for-the-badge&logo=buymeacoffee&logoColor=black
