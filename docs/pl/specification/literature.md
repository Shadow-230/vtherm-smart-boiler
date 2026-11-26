# Literatura

Źródła, na których opierają się reguły Smart Boilera i poprawki kroku I13
([plan](../../en/development/plans/plan-0.2-i13.md), tylko po angielsku), wyłącznie jako odnośniki:
pliki nie są trzymane w repozytorium. Przy każdej pozycji: co wtyczka z niej bierze.

## Temperatura wody

- Åström, K. J., Hägglund, T. (1995). *PID Controllers: Theory, Design, and Tuning*, wyd. 2. ISA.
  Selektory i podział jednego wyjścia między dwie pętle: wodę ustawia najbardziej wymagający obieg.
- Skogestad, S. (2023). Advanced control using decomposition and simple elements. *Annual Reviews
  in Control* 56, 100903. [doi:10.1016/j.arcontrol.2023.100903](https://doi.org/10.1016/j.arcontrol.2023.100903).
  Sterowanie położeniem zaworu i środkiem zakresu, wolna pętla zewnętrzna 4–10 razy wolniejsza od
  wewnętrznej: tempo korekty komfortu.
- Hägglund, T. (2021). A feedforward approach to mid-ranging control. *Control Engineering
  Practice* 108, 104713. Zawór w stanie ustalonym otwarty w około 90 %: „pełne otwarcie” od 95 %.
- Boegli, M., Stauffer, Y., Koch, N., Gorecki, T., Langou, R., Hutter, A. (2022). Smart
  thermostatic valves based heat generator control to cut heating bills. CLIMA 2022.
  [doi:10.34641/clima.2022.413](https://doi.org/10.34641/clima.2022.413). Zawory prowadzą wodę do
  najniższej temperatury, która pokrywa potrzeby: ujemna strona korekty.
- Dahlblom, M., Nordquist, B., Jensen, L. (2018). *Energy and Buildings* 166, 23–34.
  [doi:10.1016/j.enbuild.2018.01.013](https://doi.org/10.1016/j.enbuild.2018.01.013). Sprzężenie
  od średniego odchylenia temperatury wewnątrz, nałożone na krzywą pogodową: więcej niż jeden
  pokój.
- Olsson, Filipsson, Trüschel (2023, 2024). *Energies* 16, 6747 i 17, 261.
  [doi:10.3390/en16186747](https://doi.org/10.3390/en16186747),
  [doi:10.3390/en17010261](https://doi.org/10.3390/en17010261). Sprzężenie zwrotne na temperaturę
  zasilania w 107 budynkach.
- ASHRAE Guideline 36, *High-Performance Sequences of Operation for HVAC Systems*: przestawianie
  temperatury zasilania metodą „trim and respond”.
- Olesen, B. W. (2007). New European standards for design, dimensioning and testing embedded
  radiant heating and cooling systems. Clima 2007. Po stronie wody obieg podłogowy jest prawie
  liniowy: jego wykładnik to około 1,0.
- Gritzki, R. i inni (2021). Can we still trust in EN 442? *REHVA Journal*. Wzór na moc grzejnika i
  jego wykładnik 1,3.
- Kull, T. M., Simson, R., Thalfeldt, M., Kurnitski, J. (2017). Influence of time constants on
  low energy buildings' heating control. 11th Nordic Symposium on Building Physics, *Energy
  Procedia* 132, 75–80. Pokoje z podłogówką reagują w ciągu 20–70 godzin: dłuższa średnia
  temperatury zewnętrznej.
- Hart-Davis, D., Liu, L., Leach, M. (2024). To zone or not to zone when upgrading a wet heating
  system from gas to heat pump. *Sustainability* 16, 4710.
  [doi:10.3390/su16114710](https://doi.org/10.3390/su16114710). Regulacja pogodowa obok pokoi z
  własną regulacją.

## Taktowanie palnika

- Bennett, G., Elwell, C., Oreszczyn, T. (2019). Space heating operation of combination boilers in
  the UK. *Building Services Engineering Research and Technology* 40(1), 75–92.
  [doi:10.1177/0143624418794552](https://doi.org/10.1177/0143624418794552). 221 kotłów: połowa
  startowała ponad 50 razy na dobę; u 70 % kotłów średni start na grzanie trwał krócej niż
  10 minut.
- Bennett, G., Elwell, C. (2020). Effect of boiler oversizing on efficiency: a dynamic simulation
  study. *Building Services Engineering Research and Technology* 41(6), 709–726.
  [doi:10.1177/0143624420927352](https://doi.org/10.1177/0143624420927352). Przewymiarowanie i
  sprawność w domach brytyjskich: brzmienie werdyktu.
- Department for Energy Security and Net Zero (2023). *Lab testing – boiler cycling*, walidacja
  Home Energy Model HEM-VAL-05.
  [GOV.UK](https://assets.publishing.service.gov.uk/media/65785a000467eb000d55f5ce/hem-val-05-lab-testing-boiler-cycling.pdf).
  Sprawność poniżej najmniejszej mocy kotła: ograniczenie modulacji.
- Department for Energy Security and Net Zero (2026). *Boiler methane emissions report*.
  [GOV.UK](https://www.gov.uk/government/publications/boiler-methane-emissions-research).
  Niespalony metan przy każdym starcie: koszt częstych startów.
- BRE dla Department for Business, Energy and Industrial Strategy (2017). *Evidence gathering –
  compensation and TPI heating controls*. Czas cyklu TPI dla kotłów gazowych.
- Boháč, J. (2019). *Dynamic behaviour of heating appliances in relation to control of their heat
  output*. Praca doktorska, Politechnika Czeska w Pradze. Bartusek, J. (2014). *Dynamics of
  heating surfaces and radiators including control valves*. Praca magisterska, Politechnika w Brnie.
  Jak długo grzejniki trzymają ciepło przez krótki postój: przerwa przed ponownym startem.

## Monitorowanie i budynek

- Madsen, H., Bacher, P. i inni (2016). *Thermal performance characterisation using time series
  data – statistical guidelines*. IEA EBC Annex 58. Próbki dzienne ze skorelowanymi resztami dają
  za wąskie przedziały: przedział dla budynku.
- Bacher, P., Madsen, H. (2011). Identifying suitable models for the heat dynamics of buildings.
  *Energy and Buildings* 43, 1511–1522.
- Leiria, D. i inni (2024). From showers to heaters: evaluating the different factors that play a
  role in buildings' energy signature.
  [doi:10.2139/ssrn.4900485](https://doi.org/10.2139/ssrn.4900485). Czego nie uwzględnia sygnatura
  energetyczna.
- Phillips, G., Wilson, G. (2024). Investigating changes in natural gas demand across Great Britain
  for domestic heating using daily data. *Energies* 17, 4884.
  [doi:10.3390/en17194884](https://doi.org/10.3390/en17194884). Gaz na stopniodzień i jego rozrzut.
- Smertinas, Nielsen, Van Hove, Bacher, Madsen (2025). Bayesowska sygnatura energetyczna 2788
  duńskich domów (temat, nie tytuł). arXiv:2503.22321, preprint.
- Department for Energy Security and Net Zero (2026). *Smart Meter Enabled Thermal Efficiency
  Ratings (SMETER)*: przewodnik, studia przypadków i podstawy.
  [GOV.UK](https://www.gov.uk/government/publications/smart-meter-enabled-thermal-efficiency-ratings-smeter-strategic-guide).
- Hanmer, C. i inni (2026). *Buildings & Cities* 7(1), 176–195.
  [doi:10.5334/bc.670](https://doi.org/10.5334/bc.670).

## Bezpieczeństwo i jakość danych

- Adnan, N. A. (2013). *Performance assessment and systematic design of industrial alarm systems*.
  Praca doktorska, University of Alberta.
  [doi:10.7939/R3930P582](https://doi.org/10.7939/R3930P582). Opóźnienia potwierdzenia i strefy
  nieczułości: opóźnienia alarmów, powrót połączenia.
- Chen, W., Toueg, S., Aguilera, M. K. (2002). On the quality of service of failure detectors.
  *IEEE Transactions on Computers* 51(5). Szybkość wykrycia awarii a fałszywe alarmy: utrata
  połączenia z kotłem.
- The OpenTherm Association (2003). *OpenTherm Protocol Specification* v2.2. Odstęp między
  wiadomościami mastera.
- EEMUA 191, *Alarm systems – a guide to design, management and procurement*, wyd. 4 (2024).
  Histereza alarmów.

## Kocioł i regulatory pokoi

- Hägglund, T., Åström, K. J. (2000). Supervision of adaptive control algorithms. *Automatica*
  36(8), 1171–1180.
  [doi:10.1016/S0005-1098(00)00026-1](https://doi.org/10.1016/S0005-1098(00)00026-1). Nauka
  wstrzymana tylko wtedy, gdy regulator prosi o wejście, którego nie dostaje: „Nie daje ciepła”.
- Veronesi, M., Visioli, A. (2008). A technique for abrupt load disturbance detection in process
  control systems. 17th IFAC World Congress.
- Ramadane, M., Bohnet, M. (2026). Preventing parasitic learning in online identification of
  building RC thermal models. *Energy and Buildings* 369, 117997.
  [doi:10.1016/j.enbuild.2026.117997](https://doi.org/10.1016/j.enbuild.2026.117997).
  Niezmierzone zyski ciepła wchłaniane przez model pokoju.
