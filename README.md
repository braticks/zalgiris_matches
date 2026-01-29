# Žalgiris Matches (Home Assistant)

Custom Home Assistant integracija, kuri iš `https://zalgiris.lt/rungtynes` ištraukia informaciją apie artėjančias / live / praėjusias rungtynes.

## Diegimas per HACS (Custom repository)

1. HACS → **Integrations**
2. Viršuje dešinėje **⋮** → **Custom repositories**
3. Įrašyk šio repo URL ir pasirink **Category: Integration**
4. Susirask **Žalgiris Matches** ir paspausk **Download**
5. Perkrauk Home Assistant

## Konfigūracija

Po įdiegimo:
Settings → Devices & Services → Add integration → **Žalgiris Matches**

Options leidžia pakeisti:
- `scan_interval` (pvz. 600s)
- `live_scan_interval` (pvz. 20s)
- `store_days` (kiek dienų laikyti istoriją)

## Entitetai

- `sensor.zalgiris_rungtyniu_sarasas`
- `sensor.zalgiris_kitos_rungtynes`
- `sensor.zalgiris_paskutines_rungtynes_su_rezultatu`
