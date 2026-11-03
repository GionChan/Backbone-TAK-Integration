# Kenttälaitepaketti (Windows, ei Dockeria)

**In English:** [../en/field-package.md](../en/field-package.md)

Laitteille, joissa on TAK-pääte mutta ei Dockeria. Yksi itseasentuva
ZIP-paketti ajaa samaa `relay/tak_gateway.py`-koodia natiivisti.

## Rakentaminen

```bash
python tools/register_portal_topics.py --add-system field-relay-01 --apply   # rekisteröi heartbeat ensin
python tools/make_relay_package.py --system field-relay-01                   # → dist/field-relay-01-tak-relay.zip
```

| Valitsin | Oletus | Merkitys |
| --- | --- | --- |
| `--system` | pakollinen | Laitteen yksilöllinen nimi: `GATEWAY_SYSTEM`, heartbeat-topic, tiedostonimi |
| `--cert-dir` | `./certs` | Mukaan otettava bundle (yksi sertifikaatti- ja avainpari + CA) |
| `--tak-host`, `--tak-udp-port` | `127.0.0.1`, `6969` | Missä TAK-pääte kuuntelee CoT:tä |
| `--tak-port` | `8087` | TCP-striimin portti |
| `--tak-udp-in-port` | `6971` | UDP-portti päätteen PLI:lle |
| `--no-ingest` | pois | Älä julkaise päätteen omaa sijaintia |
| `--router` | EFDI-reititin | Zenohin mTLS-reititin |

Paketissa ovat `app/` (relayn moduulit muuttamattomina), `certs/`, `device.env` (kaikki
asetukset, myös sertifikaatista luettu slot), `bootstrap.ps1`, `run.ps1`, `install.cmd/.ps1`,
`uninstall.cmd/.ps1` ja suomenkielinen pikaohje. Rekisteröi järjestelmänimi **ennen**
toimitusta, muuten heartbeat näkyy tuntemattomana.

**ZIP sisältää yksityisen avaimen.** Siirrä se kuin salaisuus; `dist/` on rajattu
versionhallinnan ulkopuolelle.

## Asennus laitteelle

1. Liity meshiin (`netbird up …`); reitittimen nimi ratkeaa vain sen sisällä.
2. Pura paketti ja kaksoisnapsauta `install.cmd`. Se luo virtuaaliympäristön, asentaa
   `eclipse-zenoh`:n, rekisteröi automaattisen käynnistyksen ja käynnistää relayn heti.
   - Automaattinen käynnistys yrittää ensin ajastettua tehtävää (kirjautuessa, ei
     ylläpito-oikeuksia). Jos tili ei saa luoda ajastettuja tehtäviä, asennus käyttää
     Käynnistys-kansion pikakuvaketta.
   - Kioskikoneet ilman kirjautunutta käyttäjää: `install.ps1 -AtSystemStartup`
     ylläpitäjän PowerShellissä (käynnistyy järjestelmän mukana SYSTEM-tilillä).
3. Ohjaa päätteen CoT-tulo `device.env`-tiedoston porttiin `TAK_UDP_PORT` (TAK-sovelluksen oletus 6969)
   ja tarvittaessa sen UDP-ulostulo porttiin `TAK_UDP_IN_PORT` PLI:tä varten.
4. Tarkista `http://localhost:8088/status` → `"healthy": true`. Lokit:
   `logs/relay-VVVVKKPP.log`.

Asetusten muuttaminen: muokkaa `device.env`-tiedostoa, aja `uninstall.cmd` ja sitten
`install.cmd`. `uninstall` poistaa kumman tahansa käynnistystavan ja pysäyttää sekä
käynnistinsilmukan että relayn.

`run.ps1 -CheckOnly` tarkistaa Pythonin, zenohin ja sertifikaatit käynnistämättä relayta.

Koko sykli (asennus → terve tila oikeaa fabricia vasten ja CoT useilta valmistajilta → poisto →
ei uudelleenkäynnistystä) on varmistettu Windows-kenttälaitteilla.
