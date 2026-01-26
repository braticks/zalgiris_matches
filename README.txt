# Žalgiris Matches (Home Assistant custom integration)

Ši integracija parsiunčia rungtynių informaciją iš **https://zalgiris.lt/rungtynes** ir sukuria sensorius:

- **Žalgiris – rungtynių sąrašas** (state = kiek rungtynių žinome)
  - atributai: `live`, `upcoming`, `finished`, `fetched_at` ir t.t.
- **Žalgiris – kitos rungtynės** (timestamp)
- **Žalgiris – paskutinės rungtynės** (timestamp)
- **Žalgiris – paskutinės rungtynės (su rezultatu)** (timestamp)
- **Žalgiris – live rungtynės** (state = `live` / `85-72` / `none`)

## Kodėl „finished“ gali būti tuščias?
`zalgiris.lt/rungtynes` dažnai rodo tik artėjančias rungtynes. Kai rungtynės būna matomos puslapyje (tą pačią dieną),
integracija jas įsimena lokaliai (HA saugykloje) ir rodo kaip `finished` ateityje.

## Atnaujinimo dažnis ir „ban“ rizika
- `scan_interval` – kaip dažnai traukiamas pagrindinis tvarkaraštis (rekomenduojama 10 min).
- `live_scan_interval` – kai aptinkamos live rungtynės, integracija persijungia į dažnesnį atnaujinimą (numatytai 20 sek).

Integracija naudoja **ETag/If-Modified-Since** (kai serveris palaiko) – tai mažina realių duomenų parsisiuntimų skaičių.

## Diegimas
1. Išarchyvuok į `config/custom_components/zalgiris_matches/`
2. Perkrauk Home Assistant.
3. Settings → Devices & Services → **Add integration** → „Žalgiris Matches“.
