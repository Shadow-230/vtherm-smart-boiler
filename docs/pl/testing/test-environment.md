[English version](../../en/testing/test-environment.md)

# Testowy Home Assistant

Home Assistant 2026.9.3 w Dockerze, w dedykowanym kontenerze LXC na Proxmox, z wtyczką, Versatile
Thermostat 10.5.1 (do 2026-10-13: 10.4.0) i SmartPI 0.4.0 w wersji dołączonej do projektu (vendored) oraz
symulatorem kotła tylko do testów (`sim/custom_components/boiler_sim`). Scenariusze akceptacyjne działają tu
(`docs/en/development/plans/plan-0.2.md`, J4), zanim cokolwiek trafi do prawdziwego kotła.

Claude łączy się z tą instancją dopiero po tym, jak powiesz, że zaczynamy, tylko pod adresem z
`devenv/local.env` i z żadną inną instancją Home Assistant.

## 1. Kontener LXC (ty — J2)

Nowy LXC tylko do testów. SSH Claude'a sięga tego kontenera i niczego więcej. Zapora sieciowa stoi
na hoście Proxmox, poza kontenerem, więc nic w jego wnętrzu — ani Docker, ani użytkownik wdrożeniowy,
ani Claude — nie może jej zmienić (decyzja użytkownika z 2026-10-08).

- Nowy, nieuprzywilejowany kontener Debian 13 z `nesting=1` i `keyctl=1`, używany do niczego innego:
  2 rdzenie, 2 GB pamięci (4 GB jest wygodniejsze), 32 GB dysku.
- Sieć: stały adres IPv4 (zapora kontenera opisana niżej ma wyłączone DHCP), bez adresu IPv6
  (IPv6 „Static” z pustym polem) i publiczny serwer DNS w ustawieniach DNS kontenera (na przykład
  `1.1.1.1`), żeby kontener nie potrzebował niczego w sieci domowej. Jeśli sieć domowa nie wypuszcza
  DNS do internetu, zezwól zamiast tego na DNS routera, regułą
  `OUT ACCEPT -dest <router-ip> -p udp -dport 53` i tą samą z `-p tcp`, nad
  regułami `OUT DROP`.
- Docker Engine z wtyczką compose, z repozytorium Dockera dla Debiana.
- Użytkownik wdrożeniowy, który loguje się kluczem SSH i należy do grupy `docker`.
- Zapora na hoście Proxmox, filtrująca tylko ten kontener:
  1. Najpierw sprawdź, co już tam jest, w powłoce hosta (węzeł → Shell):
     `ls /etc/pve/firewall/`. Plik gościa z `enable: 1` zaczyna filtrować tego gościa,
     gdy zapora Datacenter jest włączona; gość bez pliku zachowuje swój ruch bez zmian.
     `cluster.fw` i `host.fw` węzła nie powinny zawierać reguł, których nie znasz.
  2. Kontener → Network → `net0` → zaznaczone Firewall.
  3. Reguły kontenera: zapisz poniższy plik jako `/etc/pve/firewall/<CT ID>.fw` w powłoce hosta
     albo wpisz to samo w kontener → Firewall. Sprawdź tam, czy każda reguła pokazuje „On” i czy
     jego Options mówią: Firewall: Yes, DHCP: No (Proxmox może domyślnie pokazywać Yes),
     Input policy DROP, Output policy ACCEPT.
  4. Datacenter → Firewall → Options: najpierw Input Policy ACCEPT, żeby host i inni goście
     byli osiągalni jak dotąd (domyślnie Proxmox odrzuca cały ruch do hosta, oprócz jego strony
     WWW i SSH z sieci lokalnej); potem Firewall: Yes. Ustawienie Firewall z powrotem na No
     albo `pve-firewall stop` w powłoce hosta cofa to od razu.

  ```
  [OPTIONS]
  enable: 1
  dhcp: 0
  policy_in: DROP
  policy_out: ACCEPT

  [RULES]
  IN ACCEPT -p tcp -dport 22
  IN ACCEPT -p tcp -dport 8123
  OUT DROP -dest 10.0.0.0/8
  OUT DROP -dest 172.16.0.0/12
  OUT DROP -dest 192.168.0.0/16
  OUT DROP -dest 100.64.0.0/10
  OUT DROP -dest 169.254.0.0/16
  OUT DROP -dest fc00::/7
  OUT DROP -dest 2000::/3
  ```

  Wchodzące (In): tylko SSH i strona Home Assistanta; odpowiedzi na nie przechodzą. Wychodzące
  (Out): internet (obraz, repozytorium Dockera, PyPI, DNS), ale żadnych nowych połączeń z czymkolwiek
  w sieci domowej, bez względu na adres — z produkcyjnym Home Assistantem, jego brokerem i bramką oraz
  z każdym innym urządzeniem (przekaźniki, ESPHome, moduł Wi-Fi kotła); przy wyłączonym IPv6 w ogóle
  bez IPv6. Kontener Home Assistanta też wychodzi z LXC przez `net0`, więc reguły go obejmują; ruch
  między kontenerami wewnątrz LXC (na przykład testowy broker) nigdy go nie opuszcza.
- Sprawdzenie (T-25), przy włączonej zaporze: każda próba połączenia TCP z każdym portem usługi
  produkcyjnego Home Assistanta, jego brokera i bramki oraz z jeszcze jednym urządzeniem w domu (na
  przykład ze stroną WWW routera) musi skończyć się przekroczeniem czasu — z kontenera i z samego LXC.
  Odmowa to porażka: oznacza, że pakiet dotarł do celu. Przez IPv6 (tam, gdzie sieć domowa go ma)
  zaliczone jest też „brak trasy”: IPv6 jest wyłączone. Z kontenera z obrazem, na którym
  działa Home Assistant (polecenie pobiera obraz), dla każdego adresu i portu:

  ```
  docker run --rm --entrypoint python3 ghcr.io/home-assistant/home-assistant:2026.9.3 -c "
  import errno, socket, sys
  host = sys.argv[1]
  try:
      socket.create_connection((host, int(sys.argv[2])), 5); print('REACHABLE')
  except TimeoutError:
      print('blocked')
  except OSError as e:
      if e.errno == errno.ENETUNREACH and ':' in host:
          print('blocked (no IPv6 route)')
      else:
          print('REACHABLE or rejected:', e)" '<ip>' <port>
  ```

  Z samego LXC, jako użytkownik wdrożeniowy — kod wyjścia 124 oznacza „blocked”, a dla adresu IPv6
  także „Network is unreachable”:

  ```
  timeout 6 bash -c 'exec 3<>/dev/tcp/<ip>/<port>'; echo $?
  ```

  Zalicza się tylko „blocked”. Najpierw uruchom oba sprawdzenia raz dla adresu i portu, do których muszą
  się dostać (np. publiczny serwer WWW na porcie 443): muszą wypisać REACHABLE i 0, co pokazuje, że samo
  sprawdzenie działa. Powtórz całe sprawdzenie po ponownym uruchomieniu LXC. Ty robisz je w J2; Claude
  powtarza je przez SSH dopiero po tym, jak powiesz, że zaczynamy J4, a wtedy także jako
  `docker exec ha-test python3 -c "…"` wewnątrz działającego Home Assistanta.
- Dostęp do internetu, żeby pobrać obraz i wymagania Pythona dla VT (`vtherm_api` z PyPI).
  Home Assistant instaluje najnowszy `vtherm_api` przy pierwszym uruchomieniu, a nie wersję 0.5.0,
  do której przypięte są testy; raport z J4 zapisuje zainstalowaną wersję (zadanie CI z najnowszym
  `vtherm_api` uruchamia to samo zestawienie).

## 2. Dostęp dla Claude'a (ty — J2)

Claude dostaje SSH tylko do tego kontenera, jako użytkownik wdrożeniowy: bez konta, klucza ani tokena do
hosta Proxmox, więc zapora na nim jest poza jego zasięgiem.

1. Wygeneruj parę kluczy tylko dla tego projektu, wewnątrz projektu (ignorowaną przez git):
   `ssh-keygen -t ed25519 -N "" -f devenv/ssh/id_ed25519`. Dodaj `devenv/ssh/id_ed25519.pub` do
   `~/.ssh/authorized_keys` użytkownika wdrożeniowego na LXC.
2. Skopiuj `devenv/local.env.example` do `devenv/local.env` i wpisz host, użytkownika SSH, katalog na
   LXC i adres URL.
   Tego katalogu wdrożenie nie tworzy: utwórz go sam na LXC, a w nim pusty plik znacznika
   `.vtherm-smart-boiler-test-ha` (`touch .vtherm-smart-boiler-test-ha`), który mówi wdrożeniu, że ten
   host to testowy LXC — bez niego nic nie jest kopiowane i Home Assistant nie jest restartowany
   (PB-87).
3. Po pierwszym uruchomieniu i pierwszej konfiguracji, czyli onboardingu (sekcja 3): utwórz długoterminowy token dostępu
   (profil → Security → Long-lived access tokens) i wpisz go do `TEST_HA_TOKEN`.

## 3. Wdrożenie

- `scripts/deploy_test.sh --dry-run` pokazuje, co zostałoby skopiowane; nie potrzebuje klucza i nigdzie
  się nie łączy.
- `scripts/deploy_test.sh` kopiuje wtyczkę, dołączone VT i SmartPI, symulator (który niesie ze sobą swoją
  fizykę) i `configuration.yaml` jako pliki — dowiązania do `vendor/` są zamieniane na pliki — jednym
  strumieniem tar przez SSH, więc po obu stronach potrzeba tylko `tar` i `ssh`; każda integracja
  zastępuje swoją starą kopię w całości. Potem uruchamia lub restartuje kontener.
- Pierwsze uruchomienie: otwórz adres URL, utwórz konto właściciela, ustaw lokalizację i jednostki metryczne.

W `configuration.yaml` nie ma `default_config`, więc nic nie skanuje sieci lokalnej. Do `config/`
kopiowany jest tylko `configuration.yaml`; własne pliki instancji w tym katalogu zostają nietknięte.

## 4. Instalacja testowa

Ustawiana w interfejsie użytkownika — albo przez Claude'a przez API w J4, gdy powiesz, że zaczynamy:

1. **Konfiguracja centralna VT**: z listą wyboru trybu centralnego. Nie konfiguruj centralnego kotła
   VT — zastępuje go wtyczka, a sterowanie odmawia uruchomienia, dopóki on istnieje.
2. **Jeden termostat VT na każdą symulowaną strefę** (`zone_living`, `zone_bedroom`, `zone_bath`):
   typ „over switch”; przełącznik bazowy `switch.boiler_sim_<zone>_valve`; temperatura pokojowa
   `sensor.boiler_sim_<zone>_temperature`; temperatura zewnętrzna `sensor.boiler_sim_outdoor`. W jednej
   strefie użyj SmartPI, żeby sprawdzić wstrzymania nauki. W ustawieniach zaawansowanych każdej strefy
   ustaw jej własne opóźnienie bezpieczeństwa 1440 min: VT uznaje za martwy czujnik, którego stan nie był
   zapisany przez czas tego opóźnienia (domyślnie 60 min), i przełącza strefę w tryb bezpieczeństwa,
   a ustabilizowane pokoje symulatora albo stała temperatura zewnętrzna trzymają jedną wartość dłużej.
3. **Smart Boiler for Versatile Thermostat**:
   - Sygnały: `binary_sensor.boiler_sim_flame`, `sensor.boiler_sim_flow`,
     `sensor.boiler_sim_return`, `sensor.boiler_sim_modulation`,
     `binary_sensor.boiler_sim_dhw_active`, `sensor.boiler_sim_pressure` i
     `sensor.boiler_sim_outdoor`. Na poziomie zaawansowanym także nastawa sterowania
     `sensor.boiler_sim_ch_setpoint`, `binary_sensor.boiler_sim_ch_active` i
     `binary_sensor.boiler_sim_pump_running`.
   - Pogoda: `weather.boiler_sim_weather`.
   - Kocioł: klasa „Nastawa zasilania”, c.w.u. „combi”; jeden obieg niemieszany; trzy strefy VT.
4. **Symulowana bramka**: Settings → Devices & services → Add integration → „OpenTherm Gateway
   (simulator stub, test only)” → Submit. Jej wpis ma identyfikator bramki `sim`. To zamiennik tylko do
   testów, na symulatorze, w miejsce własnej integracji OpenTherm Gateway Home Assistanta, którą
   nadpisuje tylko w tej instancji (`scripts/deploy_test.sh` nigdzie indziej go nie wdraża).
5. **Sterowanie** (menu opcji, I8): **Interfejs kotła** — połączenie bramki „Bramka z termostatem”,
   zaciski termostatu „Termostat OpenTherm” (identyfikator bramki `sim` jest pytany tylko tam, gdzie
   bramek jest kilka); **Sygnały kotła** — odczyty zwrotne
   `sensor.otgw_sim_boiler_control_setpoint` (nastawa grzania, którą dostał kocioł) i
   `binary_sensor.otgw_sim_boiler_master_ch_enabled` (grzanie włączone/wyłączone); **Urządzenie sterujące** —
   ścieżka zapisu „OpenTherm Gateway”, tylko dla wpisu utworzonego przed pytaniem o połączenie;
   **Krzywa grzewcza** — projektowa temperatura zasilania 55 °C. Program uruchamiający przywraca ten stan
   bazowy po każdym scenariuszu, który go zmienia (`devenv/j4/options.py`, zapisywany pozycja po pozycji
   w menu przez `devenv/j4/walk.py`; `tests/integration/test_j4_walk.py` przeprowadza ten sam stan
   bazowy przez prawdziwy przepływ opcji).
   - Na poziomie zaawansowanym sygnał „Nastawa termostatu przewodowego”
     `sensor.otgw_sim_thermostat_room_setpoint` (własne ustawienie termostatu ściennego, 21 °C w godzinach 06:00–22:00
     i 17 °C poza tym czasem, UTC).

Żaden okres monitorowania nie wstrzymuje sterowania (decyzja użytkownika z 2026-10-08): sterowanie można
włączyć, gdy tylko instalacja jest skonfigurowana; werdykt przychodzi po 7 dniach danych.

Inne ścieżki zapisu: ustaw `write_type: held` (lub `persistent`) i `ch_write_type` w
`configuration.yaml` i użyj ścieżki przez encje z `number.boiler_sim_flow_setpoint` i
`switch.boiler_sim_ch_enable`; oddanie sterowania przełącznikiem używa `switch.boiler_sim_external_control`. Przekaźnik
(kocioł typu włącz/wyłącz): odkomentuj blok przekaźnika w `configuration.yaml` (i usuń
`wall_thermostat`), wdróż ponownie, ustaw klasę kotła „Włącz/wyłącz” i użyj ścieżki przekaźnika z
`switch.boiler_sim_relay`, podając jego ustawienia tak, jak daje je blok, i zaznaczając „to jest osobny
styk przekaźnika”. Ścieżka MQTT przez firmware bramki wymaga brokera w LXC i `mqtt_topic` w
`configuration.yaml` — tylko jeśli droga przez atrapę zawiedzie.

## 5. Co działa w J4

Program uruchamiający to `devenv/j4/`, a jego wyniki tworzą raport z testów danej wersji
(`docs/pl/testing/reports/README.md`).

Scenariusze akceptacyjne z `docs/en/development/plans/plan-0.2.md` (J4) działają najpierw w jednym procesie
(`tests/integration/test_acceptance.py`), a potem tutaj, przez API. Scenariusze używają usług symulatora
— `boiler_sim.set_outdoor`, `fail_signal` (sygnał kotła; `gateway`: bramka poza zasięgiem, jej polecenia
są gubione — utrata łączności; `relay`: stan przekaźnika nieznany;
`thermostat_setpoint`; sygnał usterki), `force_setpoint` (inny sterownik), `ignore_writes`,
`refuse_id1` (potwierdzone, potem porzucone), `clip_setpoint`, `drop_override` (pojedynczy powrót awaryjny),
`start_dhw`, `set_topology`, `set_zone_mode` (strefa wyłączona przez VT zamyka swój zawór),
`set_room_temperature` (jeden pokój ustawiany od razu, na przykład na 4 °C jak przy ochronie przed mrozem), `reset_gateway` i
`restart_device` (utracone polecenie ze śladem), `relay_restart` (zauważony albo, z `reported: false`,
niezauważony), `relay_wifi_loss`, `relay_switch` (automatyka albo jego przycisk), `set_wall_setpoint`,
`set_fault` — oraz własnej usługi atrapy `opentherm_gw.reset_gateway`, przełącznika sterowania i opcji, a także
testowego wstrzykiwacza usterek `j4_faults` (w instancji 1, przez `configuration.yaml`): `monitor` (własny
monitor wtyczki zawodzi albo znów działa), `restart_with_stores` (wpis zatrzymany, jego magazyny danych
podmienione lub usunięte tak, jak zostawia je awaria, utrata pliku albo inna wersja, i wpis uruchomiony ponownie) oraz
`remove_options` (odpowiedzi zabrane z jego opcji, tak jak brakuje ich we wpisie utworzonym przed 0.2.2). Trafia
tylko do testowego Home Assistanta i nigdy nie jest częścią wydania wtyczki. `configuration.yaml`
instancji 1 zawiera też `input_boolean.j4_circuit_asks`, przełącznik, przez który obieg sterowany przez
inną automatykę z E7 woła o ciepło; E7 dodaje ten obieg przez „Dodaj obieg” i usuwa go na końcu.
Ich wyniki biorą się
ze stanów encji i liczników poleceń symulatora (atrybuty
`sensor.boiler_sim_persistent_writes`: polecenia na ścieżkę, `ch_writes`, `relay_commands`,
`dhw_enable_writes`; jego stan liczy tylko zapisy typu „zapisywany na stałe” (`persistent`)). Kryterium startów
(decyzja 8 z `docs/en/development/plans/plan-0.2.3.md`; `docs/pl/specification/scope.md`, wartości stałe) odczytuje starty na godzinę z monitora
w ciągu 24 h przy +8 °C i przy −5 °C, każdy z dobowym wahaniem temperatury zewnętrznej ±3 K, i porównuje je ze startami
przy własnej regulacji kotła, przy czym pokoje są tak samo ciepłe jak przy niej (równy komfort); dopuszczalny stosunek zostanie przesądzony
w K4 (do tego czasu 1.10), a test z wahaniem, uruchamiany w jednym procesie, jest do K4 ścisłym xfail. W Z3
zmierzono, że kryterium jest spełnione tylko przy wyłączonej korekcie komfortu
(`research/2026-10-02-z3-starts-ratio.md`). Jedyne kontaktowane adresy to `TEST_HA_URL` i
`TEST_HA_URL_N` instancji.

### Kryterium startów na czterech instancjach

Cztery przebiegi kryterium idą obok siebie na instancjach od 2 do 5, każda wdrożona poleceniem
`scripts/deploy_test.sh --instance N --config starts`: `devenv/config/starts.yaml` to dom z porównania
w `tests/sim/test_control_loop.py` — duży kocioł kondensacyjny, trzy strefy z grzejnikami, bez
termostatu ściennego, tak że bez wtyczki kocioł działa według własnej regulacji (własna krzywa, grzeje
zawsze, gdy zawór którejś strefy jest otwarty) — z dobowym wahaniem ±3 K wokół średniej z
`input_number.j4_outdoor_mean`. Instancja 1 zachowuje `configuration.yaml` dla pozostałych scenariuszy.

| Instancja | Port | Przebieg |
|---|---|---|
| 1 | 8123 | pozostałe scenariusze, jeden po drugim |
| 2 | 8124 | pod sterowaniem, +8 °C ±3 K |
| 3 | 8125 | własna regulacja kotła (sterowanie wyłączone), +8 °C ±3 K |
| 4 | 8126 | pod sterowaniem, −5 °C ±3 K |
| 5 | 8127 | własna regulacja kotła (sterowanie wyłączone), −5 °C ±3 K |

Na każdej: trzy strefy VT na TPI, ogrzewające do 20.5, 19.5 i 22 °C (cele symulatora);
krzywa wtyczki taka jak własna krzywa kotła (projektowa temperatura zasilania 55 °C przy −15 °C, wykładnik 1, przesunięcie 5 K, najniższa
temperatura wody 25 °C, najwyższa 70 °C), każda inna opcja z wartością domyślną — korekta komfortu wyłączona; średnia
ustawiona w `input_number.j4_outdoor_mean`; sterowanie włączone tylko na 2 i 4. Po dobie na ustabilizowanie się
porównuje się kolejne 24 h: starty palnika na godzinę (`binary_sensor.boiler_sim_flame` wyłączony → włączony),
przełączenia grzania i średnią temperaturę każdego pokoju (równy komfort: co najwyżej 0.3 K poniżej wartości
przy własnej regulacji kotła); kryterium to co najwyżej 1.10 razy starty na godzinę przy tej regulacji
(tymczasowe, K4).

Instancję, która w międzyczasie obsługiwała inne scenariusze (`--config configuration`), przywraca się
jej wdrożeniem, a potem jej opcje przeprowadza się do bazy dla startów — najpierw sterowanie wyłączone
i jego oddanie zakończone: `HA_INSTANCE=N scripts/env.sh python devenv/j4/base.py starts`
(`--correction` dla przebiegu porównującego korektę komfortu, K4: F8); `base.py gateway` przeprowadza
instancję do bazy instancji 1 (`devenv/j4/options.py`).

## 6. Więcej instancji (opcjonalnie)

W tym samym LXC może działać do ośmiu instancji Home Assistant, więc długie scenariusze idą obok siebie —
cztery 24-godzinne przebiegi kryterium startów (pod sterowaniem i przy własnej regulacji kotła, przy +8 °C i
przy −5 °C) w jeden dzień zamiast czterech, a w tym czasie piąta instancja na krótkie scenariusze, albo
ścieżka bramki na jednej, a ścieżka przekaźnika na drugiej. Instancja N = 2 do 8 dzieli obraz, ma własny
katalog, konfigurację, plik znacznika i kontener (`ha-test-N`) i nasłuchuje na porcie 8122 + N (8124 do
8130). Każda kosztuje około 0.2–0.3 GB pamięci (zmierzone) i 1 GB dysku, plus przyrost danych recordera
w ciągu dnia pracy: osiem mieści się w 8 GB, 4 rdzeniach i około 24 GB dysku.

1. Na hoście Proxmox zezwól na jej port do kontenera: dodaj `IN ACCEPT -p tcp -dport 8124`
   (8125 do 8130) do reguł kontenera (`/etc/pve/firewall/<CT ID>.fw` albo kontener →
   Firewall). Reguły wychodzące (Out) zostają bez zmian.
2. W LXC, jako root: `mkdir -p /opt/ha-test-2 && touch
   /opt/ha-test-2/.vtherm-smart-boiler-test-ha && chown -R deploy:deploy /opt/ha-test-2`
   (`-3` do `-8` tak samo).
3. W `devenv/local.env`: `TEST_HA_DIR_N` i `TEST_HA_URL_N` z jej portem.
4. `scripts/deploy_test.sh --instance N` (najpierw próbny przebieg z `--dry-run --instance N`).
   Potem albo otwórz adres URL, utwórz konto właściciela i wpisz długoterminowy token dostępu do
   `TEST_HA_TOKEN_N`; albo — prościej, i tak robi testowy LXC — daj jej dane logowania pierwszej instancji:
   zatrzymaj ją (`docker compose stop homeassistant` w jej katalogu), skopiuj cztery pliki
   za pomocą `docker cp ha-test:/config/.storage/<file> - | docker cp - ha-test-N:/config/.storage/`
   dla `auth`, `auth_provider.homeassistant`, `onboarding` i `core.config`, i uruchom ją
   ponownie. Wtedy nie potrzebuje własnego konta właściciela, `TEST_HA_TOKEN` działa tam, a
   `TEST_HA_TOKEN_N` zostaje pusty.
5. Ustaw tam instalację testową tak jak w sekcji 4. Claude powtarza w niej też T-25
   (`docker exec ha-test-N …`).
