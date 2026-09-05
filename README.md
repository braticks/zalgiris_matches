# Zalgiris Matches (v2.0.6)

## Adaptyvus atnaujinimas (2.0.6)

- Tarp rungtynių: maždaug kas 2 valandas.
- Likus iki 6 valandų: naudojamas `scan_interval` (numatyta 600 s).
- Nuo 15 min. iki pradžios iki 4 val. po pradžios: 60–120 s pagal `scan_interval`, ne daugiau kaip 120 s.
- Pridedamas iki 10 % atsitiktinis vėlavimas; atsižvelgiama į artėjančią greito tikrinimo ribą.
- Gavus HTTP ar ryšio klaidą: pauzė nuo 5 min., pakartotinai dvigubinama iki 6 val. Gavus 403: bent 1 val.
- `Retry-After` (sekundės arba HTTP data) yra minimali pauzė, net jei viršija 6 val. Papildomi rungtynių puslapiai tikrinami nuosekliai; gavus klaidą kiti nebetikrinami.
- Pauzė galioja ir rankinėms užklausoms, ir integracijos perkrovimui toje pačioje HA sesijoje. Po viso HA paleidimo iš naujo pauzė nėra išsaugoma.

`debug.next_poll_seconds` ir `debug.cooldown_seconds` rodo planuojamą intervalą bei pauzę paskutinio sėkmingai grąžinto atnaujinimo metu. Tai nėra nuolat mažėjantys skaitikliai. Greitas langas nustatomas pagal laiką, ne pagal patvirtintą „Live“ būseną.

## Duomenų ribojimai ir 2.0.5 pakeitimai

Rezultatai atnaujinami pagal aukščiau aprašytą adaptyvią tvarką, o ne realaus laiko srautu. `scan_interval` nustatymas galioja artėjant rungtynėms; kitais laikotarpiais taikomos adaptyvios ribos. Transliuotojas rodomas tik gavus duomenis iš šaltinio.

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

`manifest.json` versija: `2.0.6`
