[English version](../../en/specification/references.md)

# Kody odniesień

Status: aktualny.

Komentarze w kodzie, testy, plany i zakres używają krótkich kodów, takich jak `P-12` czy
`PB-25`. Każdy kod wskazuje miejsce, w którym problem, decyzję albo wynik testu zapisano po raz
pierwszy, żeby dało się odszukać, skąd wziął się dany fragment kodu. Ta strona mówi, gdzie
wyjaśniony jest każdy rodzaj kodu.

Prawie wszystkie te miejsca to dokumenty historyczne: zostają po angielsku i nie są przepisywane
(zob. [mapę dokumentacji](../README.md)). Dwa podobne kody mogą pochodzić z różnych dokumentów,
dlatego tabela poniżej podaje dokładną postać każdego z nich.

## Problemy znalezione w przeglądach kodu

Każdy przegląd numeruje swoje problemy osobno. Postać kodu mówi, z którego przeglądu pochodzi.

| Kod | Przykład | Co to jest | Gdzie jest wyjaśniony |
|---|---|---|---|
| `P01`…`P66` (dwie cyfry, bez myślnika) | `P02` | problem w kodzie | [przegląd z 2026-09-24](../../en/development/reviews/review-2026-09-24.md), §3 |
| `S01`…`S20` (dwie cyfry, bez myślnika) | `S04` | problem w specyfikacji | przegląd z 2026-09-24, §4 |
| `P-n` | `P-60` | problem w kodzie | [przegląd z 2026-09-26](../../en/development/reviews/review-2026-09-26.md), §3 |
| `S-n` | `S-34` | problem w specyfikacji | przegląd z 2026-09-26, §4 |
| `T-n` | `T-01` | brakujący test | przegląd z 2026-09-26, §6 |
| `PB-n` | `PB-25` | problem w kodzie | [przegląd z 2026-10-04](../../en/development/reviews/review-2026-10-04.md), §3 |
| `SB-n` | `SB-02` | problem w specyfikacji | przegląd z 2026-10-04, §4 |
| `TB-n` | `TB-03` | brakujący test | przegląd z 2026-10-04, §6 |
| `SC1-n`, `SC2-n`, `PL-n`, `P21-n`, `P22-n`, `VT-n`, `HA-n` | `SC2-140` | jedno wymaganie w tabeli wymagań i testów | §5 przeglądu z 2026-09-26 albo z 2026-10-04 (każdy przegląd numeruje swoje wiersze osobno) |

Co zrobiono z każdym problemem, jest wypisane na końcu planu, który go naprawił: „Index: review
problem → step" w [planie 0.2.2](../../en/development/plans/plan-0.2.2.md) i
[planie 0.2.3](../../en/development/plans/plan-0.2.3.md). [Porównanie z 2026-09-26](../../en/development/reviews/review-2026-09-26-vs-0.2.md)
mówi, co stało się z każdym problemem pierwszego przeglądu.

## Wyniki niezależnych sprawdzeń wersji 0.2.2

| Kod | Co to jest | Gdzie jest wyjaśniony |
|---|---|---|
| `Z4-n` | wynik niezależnego sprawdzenia wydania 0.2.2 (krok Z4) | [plan 0.2.2](../../en/development/plans/plan-0.2.2.md), „Open after 0.2.2" |
| `Z4R-n`, `Z4R2-n`, `Z4R3-n` | wynik pierwszego, drugiego i trzeciego powtórzenia tego sprawdzenia | to samo miejsce |
| `KD-n`, `KDF-n` | test zablokowanego przełącznika grzania i czasomierz przekaźnika, rozstrzygnięte 2026-10-03 | plan 0.2.2, „Open after 0.2.2", punkty 35 do 37 |

Pełne raporty z tych sprawdzeń zostają w katalogu `research/` na komputerze autora; nie należy
on do repozytorium. To, co postanowiono, jest w planie.

## Decyzje użytkownika

| Kod | Przykład | Gdzie jest wyjaśniony |
|---|---|---|
| „decision n" (1 do 16) | „decision 6" | plan 0.2.2, „Decisions 1–16" |
| „answer A" do „answer O" | „answer H" | plan 0.2.2, „Decisions of 2026-09-26/27", odpowiedzi użytkownika z 2026-09-27; szczegóły w [szczegółach planu 0.2.2](../../en/development/plans/plan-0.2.2-details.md) |
| numerowana decyzja z 2026-10-05 | „decision 4 of 0.2.3" | [plan 0.2.3](../../en/development/plans/plan-0.2.3.md), „Decisions of 2026-10-05" |
| litera i liczba w kroku I8 | „F3", „A4" | [plan kroku I8](../../en/development/plans/plan-0.2-i8.md), „Decisions of 2026-10-10": grupy od A (zakres) do I (plany) |
| „decision n of I6" | „decision 4 of I6" | [plan kroku I6](../../en/development/plans/plan-0.2-i6.md), „Decisions of 2026-10-08 and 2026-10-09" |
| „review question n" | „review question 4" | dodatek E przeglądu, „Open questions for the user" |

## Kroki planów

Krok to litera i liczba. Każda litera należy do jednego planu:

| Litery | Plan |
|---|---|
| A, B, C, D | [plan 0.1](../../en/development/plans/plan-0.1.md) |
| F, G, H, I, J, K, S | [plan 0.2](../../en/development/plans/plan-0.2.md); kroki I6, I7, I8, I9 i G11 mają własne plany w tym samym katalogu |
| L, M, N, O, R, U, W | [plan 0.2.1](../../en/development/plans/plan-0.2.1.md) |
| Q, V, X, Y, Z | [plan 0.2.2](../../en/development/plans/plan-0.2.2.md); `Q3.n` to jedno pytanie kroku badawczego Q3 |

Plan 0.2.3 jest podzielony na części od 1 do 4, a za kroki służą mu kody z przeglądów powyżej.

## Testy w testowym Home Assistancie (J4)

| Kod | Przykład | Co to jest | Gdzie jest wyjaśniony |
|---|---|---|---|
| scenariusz | `C5`, `N2`, `L1` | jeden test, który odgrywa program J4 | `devenv/j4/run.py`; wyniki w [raporcie z testów w trakcie](../testing/reports/unreleased.md), §4 |
| `F-n` w ustaleniach raportu | `F7` | ustalenie z przebiegu J4 | raport z testów, §7 |
| `L-n` w ustaleniach raportu | `L6` | znane ograniczenie znalezione w przebiegu J4 | raport z testów, §7 |

Scenariusz i ustalenie mogą mieć ten sam kod (scenariusz `F1` to usterka niskiego ciśnienia w
kotle, ustalenie `F1` to brakujący plik w symulatorze); tabela, w której kod stoi, mówi, o które
chodzi. Ustalenie, którego raport jeszcze nie wymienia — `F14`, z przebiegów z
2026-10-14 — jest wyjaśnione w komentarzu w kodzie, który je przywołuje, dopóki raport go nie
doda.
