# 2.1.0-beta.4

- Pataisytas LKL rezultato nuskaitymas: tikrinama data ir abi komandos vienoje rungtynių eilutėje. Gretimų rungtynių rezultatai nebebus priskiriami Žalgiriui.
- Atkuriamas atnaujinimas rungtynėms, kurias ankstesnė beta klaidingai pažymėjo baigtomis. Nepatvirtinti seni LKL rezultatai išvalomi.
- LKL rungtynių identifikatorius išsaugomas kartu su patikrinta data. Rungtynių komandos nebeperrašomos pagal nesusietą „GYVAI“ bloką.
- LKL kėlinio ir laikrodžio duomenys šiame pataisyme nepridėti; jų pagrindinio puslapio rezultatų blokas nepateikia.

Patikra: 20 automatinių testų, įskaitant 8 LKL regresijos testus ir 2026-10-04 oficialaus puslapio rezultatų bloko pavyzdį. Tikroje Home Assistant aplinkoje dar nepatikrinta.

Leidimui: žyma `v2.1.0-beta.4`, šaka `beta-live-score`, pažymėti „Pre-release“. Atnaujinus per HACS perkrauti Home Assistant.
