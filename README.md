# Žalgiris Matches (Home Assistant)

Custom HA integracija, kuri iš `https://zalgiris.lt/rungtynes` ištraukia informaciją apie artėjančias / live / praėjusias rungtynes.

## Diegimas per HACS (Custom repository)

1. HACS → **Integrations**
2. Viršuje dešinėje **⋮** → **Custom repositories**
3. Įrašyk šio repo URL ir pasirink **Category: Integration**
4. Susirask **Žalgiris Matches** ir paspausk **Download**
5. Perkrauk Home Assistant

## Konfigūracija

Settings → Devices & Services → Add integration → **Žalgiris Matches**

Options leidžia pakeisti:
- `scan_interval` (sek.)
- `live_scan_interval` (sek.)
- `store_days` (dienomis)

## Entitetai

- `sensor.zalgiris_rungtyniu_sarasas` – upcoming/finished/live + `fetched_at`
- `sensor.zalgiris_kitos_rungtynes` – kitos rungtynės (timestamp) + atributai
- `sensor.zalgiris_paskutines_rungtynes_su_rezultatu` – paskutinės (kai pavyksta gauti rezultatą)
