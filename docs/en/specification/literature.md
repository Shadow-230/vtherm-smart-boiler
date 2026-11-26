# Literature

The sources behind Smart Boiler's rules and behind the corrections of step I13
([plan](../development/plans/plan-0.2-i13.md)), as references only: the files are not kept in the
repository. Each line says what the plugin takes from the source.

## The water temperature

- Åström, K. J., Hägglund, T. (1995). *PID Controllers: Theory, Design, and Tuning*, 2nd ed. ISA.
  Selectors and splitting one output between two loops: the most demanding circuit sets the
  water.
- Skogestad, S. (2023). Advanced control using decomposition and simple elements. *Annual Reviews
  in Control* 56, 100903. [doi:10.1016/j.arcontrol.2023.100903](https://doi.org/10.1016/j.arcontrol.2023.100903).
  Valve-position and mid-ranging control, a slow outer loop 4 to 10 times slower than the inner
  one: the comfort correction's pace.
- Hägglund, T. (2021). A feedforward approach to mid-ranging control. *Control Engineering
  Practice* 108, 104713. A valve held about 90 % open in steady state: "fully open" from 95 %.
- Boegli, M., Stauffer, Y., Koch, N., Gorecki, T., Langou, R., Hutter, A. (2022). Smart
  thermostatic valves based heat generator control to cut heating bills. CLIMA 2022.
  [doi:10.34641/clima.2022.413](https://doi.org/10.34641/clima.2022.413). Valves steering the
  water to the lowest temperature that meets demand: the correction's negative side.
- Dahlblom, M., Nordquist, B., Jensen, L. (2018). *Energy and Buildings* 166, 23–34.
  [doi:10.1016/j.enbuild.2018.01.013](https://doi.org/10.1016/j.enbuild.2018.01.013). Feedback
  on the mean indoor deviation on top of the outdoor curve: more than one room.
- Olsson, Filipsson, Trüschel (2023, 2024). *Energies* 16, 6747 and 17, 261.
  [doi:10.3390/en16186747](https://doi.org/10.3390/en16186747),
  [doi:10.3390/en17010261](https://doi.org/10.3390/en17010261). Feedback on the supply
  temperature in 107 buildings.
- ASHRAE Guideline 36, *High-Performance Sequences of Operation for HVAC Systems*: the hot-water
  supply temperature reset by trim and respond.
- Olesen, B. W. (2007). New European standards for design, dimensioning and testing embedded
  radiant heating and cooling systems. Clima 2007. The water side of an underfloor circuit is
  nearly linear: its exponent is about 1.0.
- Gritzki, R. et al. (2021). Can we still trust in EN 442? *REHVA Journal*. The radiator output
  formula and its exponent 1.3.
- Siemens. *LMS14 boiler management unit*, user documentation. A minimum off time between
  heating starts, and the outdoor temperature filtered over 10–20 hours: the outdoor mean.
- Kull, T. M., Simson, R., Thalfeldt, M., Kurnitski, J. (2017). Influence of time constants on
  low energy buildings' heating control. 11th Nordic Symposium on Building Physics, *Energy
  Procedia* 132, 75–80. Rooms with underfloor
  heating respond over 20–70 hours: a longer outdoor mean.
- Hart-Davis, D., Liu, L., Leach, M. (2024). To zone or not to zone when upgrading a wet heating
  system from gas to heat pump. *Sustainability* 16, 4710.
  [doi:10.3390/su16114710](https://doi.org/10.3390/su16114710). Weather compensation beside
  zoned rooms.

## Burner cycling

- Bennett, G., Elwell, C., Oreszczyn, T. (2019). Space heating operation of combination boilers in
  the UK. *Building Services Engineering Research and Technology* 40(1), 75–92.
  [doi:10.1177/0143624418794552](https://doi.org/10.1177/0143624418794552). 221 boilers: half
  started more than 50 times a day; 70 % of the boilers averaged heating starts under 10 minutes.
- Bennett, G., Elwell, C. (2020). Effect of boiler oversizing on efficiency: a dynamic simulation
  study. *Building Services Engineering Research and Technology* 41(6), 709–726.
  [doi:10.1177/0143624420927352](https://doi.org/10.1177/0143624420927352). Oversizing and
  efficiency in UK houses: the verdict's wording.
- Department for Energy Security and Net Zero (2023). *Lab testing – boiler cycling*, Home Energy
  Model validation HEM-VAL-05.
  [GOV.UK](https://assets.publishing.service.gov.uk/media/65785a000467eb000d55f5ce/hem-val-05-lab-testing-boiler-cycling.pdf).
  Efficiency below the boiler's minimum output: the modulation cap.
- Department for Energy Security and Net Zero (2026). *Boiler methane emissions report*.
  [GOV.UK](https://www.gov.uk/government/publications/boiler-methane-emissions-research).
  Unburnt methane at each start: the cost of frequent starts.
- BRE for the Department for Business, Energy and Industrial Strategy (2017). *Evidence gathering –
  compensation and TPI heating controls*. The TPI cycle time for gas boilers.
- Boháč, J. (2019). *Dynamic behaviour of heating appliances in relation to control of their heat
  output*. Doctoral thesis, Czech Technical University in Prague. Bartusek, J. (2014). *Dynamics
  of heating surfaces and radiators including control valves*. Master's thesis, Brno University of
  Technology. How long radiators keep their heat through a short stop: the restart pause.

## Monitoring and the building

- Madsen, H., Bacher, P. et al. (2016). *Thermal performance characterisation using time series
  data – statistical guidelines*. IEA EBC Annex 58. Daily samples with correlated residuals give
  ranges too narrow: the building's range.
- Bacher, P., Madsen, H. (2011). Identifying suitable models for the heat dynamics of buildings.
  *Energy and Buildings* 43, 1511–1522.
- Leiria, D. et al. (2024). From showers to heaters: evaluating the different factors that play a
  role in buildings' energy signature.
  [doi:10.2139/ssrn.4900485](https://doi.org/10.2139/ssrn.4900485). What an energy signature
  leaves out.
- Phillips, G., Wilson, G. (2024). Investigating changes in natural gas demand across Great Britain
  for domestic heating using daily data. *Energies* 17, 4884.
  [doi:10.3390/en17194884](https://doi.org/10.3390/en17194884). Gas per degree-day and its
  scatter.
- Smertinas, Nielsen, Van Hove, Bacher, Madsen (2025). A Bayesian energy signature of 2,788
  Danish homes (subject, not the title). arXiv:2503.22321, preprint.
- Department for Energy Security and Net Zero (2026). *Smart Meter Enabled Thermal Efficiency
  Ratings (SMETER)*: strategic guide, case studies and evidence base.
  [GOV.UK](https://www.gov.uk/government/publications/smart-meter-enabled-thermal-efficiency-ratings-smeter-strategic-guide).
- Hanmer, C. et al. (2026). *Buildings & Cities* 7(1), 176–195.
  [doi:10.5334/bc.670](https://doi.org/10.5334/bc.670).

## Safety and data quality

- Adnan, N. A. (2013). *Performance assessment and systematic design of industrial alarm systems*.
  Doctoral thesis, University of Alberta.
  [doi:10.7939/R3930P582](https://doi.org/10.7939/R3930P582). Delay timers and deadbands: the
  alarms' delays, the link's recovery.
- Chen, W., Toueg, S., Aguilera, M. K. (2002). On the quality of service of failure detectors.
  *IEEE Transactions on Computers* 51(5). How fast a failure is detected against false alarms:
  the boiler link's loss.
- The OpenTherm Association (2003). *OpenTherm Protocol Specification* v2.2. The master's message
  interval.
- EEMUA 191, *Alarm systems – a guide to design, management and procurement*, 4th ed. (2024).
  Alarm hysteresis.

## The boiler and the rooms' controllers

- Hägglund, T., Åström, K. J. (2000). Supervision of adaptive control algorithms. *Automatica*
  36(8), 1171–1180.
  [doi:10.1016/S0005-1098(00)00026-1](https://doi.org/10.1016/S0005-1098(00)00026-1). Learning
  held only while the controller asks for an input it does not get: "Gives no heat".
- Veronesi, M., Visioli, A. (2008). A technique for abrupt load disturbance detection in process
  control systems. 17th IFAC World Congress.
- Ramadane, M., Bohnet, M. (2026). Preventing parasitic learning in online identification of
  building RC thermal models. *Energy and Buildings* 369, 117997.
  [doi:10.1016/j.enbuild.2026.117997](https://doi.org/10.1016/j.enbuild.2026.117997).
  Unmeasured heat gains absorbed by a room model.
