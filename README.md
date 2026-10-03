# Žalgiris Matches + Card

Home Assistant integracija Žalgirio rungtynėms. Nuo `2.1.0-beta.3` tame pačiame HACS pakete yra ir `custom:zalgiris-card`, todėl **atskiro `zalgiris-card` HACS repo nebereikia**.

## Diegimas per HACS

1. HACS → `Integrations` → trys taškai → `Custom repositories`.
2. Įrašyk `https://github.com/braticks/zalgiris_matches`.
3. Pasirink `Category: Integration`.
4. Įdiek `Žalgiris Matches` ir perkrauk Home Assistant.
5. `Settings → Devices & Services → Add Integration` → `Zalgiris Matches`.

Kortos JavaScript failą integracija pateikia ir užregistruoja automatiškai. Atskiro `Dashboard` tipo HACS repo ir rankinio Lovelace `Resources` įrašo nereikia.

## Dashboard korta

```yaml
type: custom:zalgiris-card
entity: sensor.zalgiris_rungtyniu_sarasas
count: 5
show_league: true
```

Korta turi vizualų redaktorių ir gali filtruoti lygą bei rungtynių vietą.

### Jei anksčiau buvai įdiegęs atskirą `zalgiris-card`

Po perėjimo į sujungtą versiją seną `zalgiris-card` iš HACS `Dashboard` skilties galima pašalinti. Dashboard YAML keisti nereikia — kortos tipas lieka `custom:zalgiris-card`.

## Atnaujinimas

Integracija naudoja adaptyvų tikrinimą: tarp rungtynių tikrina rečiau, artėjant rungtynėms ir jų metu — dažniau. Duomenys priklauso nuo šaltinio, todėl tai nėra garantuotas oficialus realaus laiko rezultatų srautas.

`debug.next_poll_seconds` ir `debug.cooldown_seconds` rodo planuojamą intervalą bei pauzę paskutinio sėkmingai grąžinto atnaujinimo metu.

## Rankinis diegimas

Nukopijuok visą katalogą:

`custom_components/zalgiris_matches`

į:

`config/custom_components/zalgiris_matches`

Po to perkrauk Home Assistant ir pridėk integraciją per UI.

## Repo struktūra

```text
custom_components/zalgiris_matches/
├── __init__.py
├── config_flow.py
├── const.py
├── coordinator.py
├── frontend.py
├── live_clock_coordinator.py
├── manifest.json
├── polling.py
├── sensor.py
├── standings.py
├── strings.json
├── translations/
└── www/
    └── zalgiris-card.js
```

## Testai

```bash
python3 -m unittest discover -s tests -v
```

## Versija

Dabartinė sujungimo bandomoji versija: `2.1.0-beta.3`.
