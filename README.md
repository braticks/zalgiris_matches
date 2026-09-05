# Zalgiris Matches (v2.0.5)

## Duomenų ribojimai ir 2.0.5 pakeitimai

Rezultatai atnaujinami integracijos nustatytu intervalu (numatyta 600 s, galima 60–3600 s), o ne realaus laiko srautu. Transliuotojas rodomas tik gavus duomenis iš šaltinio.

Integracija nepateikia patvirtinto `is_live` lauko. `finished` reiškia jau prasidėjusias rungtynes, nebūtinai baigtas. Korta 2.0.2 pirmas 3 valandas rodo „Prasidėjo pagal tvarkaraštį“, vėliau „Praėjusios rungtynės“. Tai laiko prielaida, ne patvirtinta būsena.

2.0.5 išsaugo lygiųjų rezultatus (taip pat 0:0), nemaišo HTML ir JSON kopijų, atnaujina HA nustatymų langą ir perkrauna integraciją pakeitus parinktis. Rekomenduojama kortos versija: 2.0.2 arba naujesnė.

Versijos numeris kode savaime nesukuria GitHub Release. Paskelbtus leidimus žiūrėkite [Releases](https://github.com/braticks/zalgiris_matches/releases).

Parserio testai: `python3 -m unittest discover -s tests -v`. Jie nepakeičia bandymo Home Assistant aplinkoje ir vykstant rungtynėms.

Home Assistant custom integration, kuri sukuria 2 sensorius:
- `schedule`
- `next`

## Dashboard korta

Šiai integracijai skirta atskira [Žalgiris Card](https://github.com/braticks/zalgiris-card) korta. Ji rodo artimiausias rungtynes, logotipus, turnyrą, transliuotoją, tiesioginį rezultatą ir artėjančių rungtynių sąrašą.

Kortą per HACS pridėkite kaip `Dashboard` tipo pasirinktinę repozitoriją.

```yaml
type: custom:zalgiris-card
entity: sensor.zalgiris_rungtyniu_sarasas
count: 5
show_league: true
```

## Diegimas per HACS

1. Repozitorijos adresas: `https://github.com/braticks/zalgiris_matches`.
2. Home Assistant -> HACS -> `Integrations` -> trys taškai -> `Custom repositories`.
3. Įklijuok repo URL.
4. Pasirink `Category: Integration`.
5. Surask `Zalgiris Matches` HACS sąraše ir `Download`.
6. Perkrauk Home Assistant.
7. `Settings -> Devices & Services -> Add Integration` ir pasirink `Zalgiris Matches`.

## Rankinis diegimas

Nukopijuok katalogą:

`custom_components/zalgiris_matches`

į tavo Home Assistant:

`config/custom_components/zalgiris_matches`

Po to restartuok Home Assistant ir pridėk integraciją per UI.

## Repo struktūra (HACS)

`custom_components/zalgiris_matches/`
- `__init__.py`
- `config_flow.py`
- `const.py`
- `coordinator.py`
- `manifest.json`
- `sensor.py`
- `strings.json`
- `translations/en.json`
- `translations/lt.json`

Papildomai root:
- `hacs.json`
- `README.md`

## Versija

`manifest.json` versija: `2.0.5`
