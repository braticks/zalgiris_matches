# 2.1.0-beta.5

- Rungtynių dieną rezultatų sensoriai pasirenka tos dienos rungtynes, net jei tiesioginis šaltinis dar nepateikia duomenų.
- Iki pirmo patvirtinto rezultato rodoma `0:0` ir tos dienos varžovas. Būsena: `scheduled` iki pradžios, `waiting` po pradžios, kol laukiama rezultato.
- `score_pending: true` atskiria laikiną `0:0` nuo tikro rezultato. Seni kėlinio, laikrodžio ir pertraukos atributai nerodomi.
- Gavus patvirtintą rezultatą rodomi tikrieji taškai, įskaitant galutinį rezultatą. Istoriniai duomenys neperrašomi.
- Diena nustatoma pagal Home Assistant laiko juostą; pasirinkimas perskaičiuojamas atnaujinant sensorių.
- Įtraukti beta.4 LKL rungtynių atpažinimo pataisymai. LKL laikrodžio palaikymas dar nepridėtas.

Leidimui: `v2.1.0-beta.5`, šaka `beta-live-score`, „Pre-release“. Atnaujinus perkrauti Home Assistant.
