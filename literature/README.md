# Literature

Open-licence sources behind Smart Boiler's rules, kept here so anyone can check them. Each file is
published under a licence that allows sharing it, given in the table with its source. Sources that
may not be shared are named in the analysis of 2026-11-26, not copied here.

Contains public sector information licensed under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
(the four DESNZ documents). The articles are under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) (CC BY); they are
shared unchanged.

| File | Source | Licence | What Smart Boiler takes from it |
|---|---|---|---|
| `2023_DESNZ_HEM-VAL-05_Lab_testing_boiler_cycling.pdf` | Department for Energy Security and Net Zero (with BRE and Kiwa), *Lab testing – boiler cycling*, Home Energy Model validation HEM-VAL-05, December 2023, [GOV.UK](https://assets.publishing.service.gov.uk/media/65785a000467eb000d55f5ce/hem-val-05-lab-testing-boiler-cycling.pdf) | OGL v3.0 | a boiler's efficiency falls once the demand is below its minimum output: the modulation cap and the short-burn information |
| `2026_DESNZ_NPL_Boiler_methane_emissions.pdf` | Department for Energy Security and Net Zero (National Physical Laboratory, Kiwa), *Boiler methane emissions report*, 2026, [GOV.UK](https://www.gov.uk/government/publications/boiler-methane-emissions-research) | OGL v3.0 | unburnt methane per start, mostly independent of the burn's length: the cost of frequent starts |
| `2026_DESNZ_SMETER_strategic_guide.pdf` | Department for Energy Security and Net Zero, *Smart Meter Enabled Thermal Efficiency Ratings (SMETER): strategic guide*, 2026, [GOV.UK](https://www.gov.uk/government/publications/smart-meter-enabled-thermal-efficiency-ratings-smeter-strategic-guide) | OGL v3.0 | the heat transfer coefficient from metered data: the building's heat loss and its range |
| `2026_DESNZ_SMETER_case_studies_and_evidence_base.pdf` | Department for Energy Security and Net Zero, *SMETER: case studies and evidence base*, 2026, [GOV.UK](https://www.gov.uk/government/publications/smart-meter-enabled-thermal-efficiency-ratings-smeter-strategic-guide) | OGL v3.0 | how accurate heat-loss estimates from metered data are: the building's range |
| `2024_Hart-Davis_Liu_Leach_To_zone_or_not_to_zone_Sustainability.pdf` | Hart-Davis, Liu, Leach, "To zone or not to zone when upgrading a wet heating system from gas to heat pump for maximum climate impact: a UK view", *Sustainability* 16 (2024) 4710, [doi:10.3390/su16114710](https://doi.org/10.3390/su16114710) | CC BY | weather compensation with zoned rooms (TRVs): rooms set back raise no extra demand under a weather-compensated water temperature — the curve beside VT's room control, and the comfort correction after a setback |
| `2024_Leiria_et_al_From_showers_to_heaters_energy_signature.pdf` | Leiria, Johra, Hu, Larsen, Marszal-Pomianowska, Frandsen, Pomianowski, "From showers to heaters: evaluating the different factors that play a role in buildings' energy signature", 2024, [doi:10.2139/ssrn.4900485](https://doi.org/10.2139/ssrn.4900485) (Aalborg University's repository copy) | CC BY 4.0 | what an energy signature leaves out (hot water, sun, setpoints): the building's fit and its range |
| `2024_Phillips_Wilson_Natural_gas_demand_GB_daily_data_Energies.pdf` | Phillips, Wilson, "Investigating changes in natural gas demand across Great Britain for domestic heating using daily data", *Energies* 17 (2024) 4884, [doi:10.3390/en17194884](https://doi.org/10.3390/en17194884) | CC BY | gas per degree-day from daily data, its scatter and the hot-water base: the weekly comparison and its band |
| `2026_Ramadane_Bohnet_Preventing_parasitic_learning_Energy_and_Buildings.pdf` | Ramadane, Bohnet, "Preventing parasitic learning in online identification of building RC thermal models: a stochastic-volatility Rao–Blackwellized particle filter", *Energy and Buildings* 369 (2026) 117997, [doi:10.1016/j.enbuild.2026.117997](https://doi.org/10.1016/j.enbuild.2026.117997) | CC BY 4.0 | unmeasured heat gains absorbed into a room model: why "Gives no heat" should say when a room is withheld heat |

The analysis that cites them, with every other source: the summary of 2026-11-26 in the project's
research notes (not in the repository).
