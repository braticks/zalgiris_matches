# Zalgiris Matches (v2.0.3)

Home Assistant custom integration, kuri sukuria 2 sensorius:
- `schedule`
- `next`

## Diegimas per HACS

1. Įkelk šitą repo į GitHub (pvz. `https://github.com/braticks/zalgiris_matches`).
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

`manifest.json` versija: `2.0.3`
