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
| `--system` | pakollinen (ei `--template`-valinnan kanssa) | Laitteen yksilöllinen nimi: `GATEWAY_SYSTEM`, heartbeat-topic, tiedostonimi |
| `--template` | pois | Ei varmennetta eikä laitteen nimeä (voi jakaa); `install.cmd` kysyy molemmat. Tämä julkaistaan [julkaisussa](release.md) |
| `--lang` | kysytään asennuksessa | `fi` tai `en`: asentimen ja sen viestien kieli |
| `--mode` | kysytään asennuksessa | `direct`, `multicast` tai `server` ([tilat](modes.md)) |
| `--tak-server`, `--tak-p12`, `--tak-trust-p12` | – | `server`-tila: osoite ja .p12-tiedostot (kopioidaan kansioon `certs/tak/`). Salasana kysytään asennuksessa |
| `--ingest-uids` | – | `TAK_INGEST_UIDS`: laitteiden uidit, joiden sijainnin saa julkaista |
| `--cert-dir` | `./certs` | Mukaan otettava bundle (yksi sertifikaatti- ja avainpari + CA) |
| `--tak-host`, `--tak-udp-port` | `127.0.0.1`, `6969` | Missä TAK-pääte kuuntelee CoT:tä |
| `--tak-port` | `8087` | TCP-striimin portti |
| `--tak-udp-in-port` | `6971` | UDP-portti päätteen PLI:lle |
| `--no-ingest` | pois | Älä julkaise päätteen omaa sijaintia |
| `--router` | bundlen `NOTES.md`, muuten EFDI-reititin | Zenohin mTLS-reititin |
| `--no-bundled-python` | pois | Jätä Python pois (pienempi ZIP). Laite tarvitsee silloin Python 3.10:n ja verkkoyhteyden asennukseen |

Paketissa ovat `app/` (relayn moduulit muuttamattomina), `certs/`, `device.env` (kaikki
asetukset, myös sertifikaatista luettu slot), `bootstrap.ps1`, `run.ps1`, `install.cmd/.ps1`,
`uninstall.cmd/.ps1`, `lang.ps1` (kaikki viestit suomeksi ja englanniksi) sekä ohjeet
molemmilla kielillä. Skriptit ovat kansiossa `tools/field_package/`. Rekisteröi järjestelmänimi **ennen**
toimitusta, muuten heartbeat näkyy tuntemattomana.

**Python on mukana** (Windows amd64, yhteensä noin 25 Mt): python.orgin embeddable-Python
3.14.10, joka on lukittu julkaistuun SHA256-tarkisteeseen, sekä `eclipse-zenoh`:n ja
`cryptography`:n Windows-wheelit PyPI:stä. Laite ei tarvitse Pythonia eikä verkkoyhteyttä
asennukseen. Lataukset tallentuvat välimuistiin `dist/cache/`, ja ZIPin `python/SOURCE.txt`
luettelee jokaisen tiedoston ja sen SHA256-tarkisteen.

**ZIP sisältää yksityisen avaimen.** Siirrä se kuin salaisuus; `dist/` on rajattu
versionhallinnan ulkopuolelle.

## Asennus laitteelle

1. Liity meshiin (`netbird up …`); reitittimen nimi ratkeaa vain sen sisällä.
2. Pura paketti ja kaksoisnapsauta `install.cmd`. Se kysyy tässä järjestyksessä:
   1. **Kielen** (Suomi / English). Kaikki tämän jälkeen, myös myöhemmät käynnistykset ja
      poisto, tapahtuu valitulla kielellä.
   2. **Tilan:** suora, lähiverkko tai TAK Server ([tilat](modes.md)).
   3. **Tilan lisätiedot:** TAK Serverin osoite, .p12-tiedostot ja salasana; lähiverkkotilassa
      niiden laitteiden uidit, joiden sijainnin saa julkaista.

   Mitä on valittu valmiiksi `make_relay_package.py`:llä, sitä ei kysytä. Vastaukset tallentuvat
   tiedostoon `device.env`. Sen jälkeen asennin rekisteröi automaattisen käynnistyksen
   (`--no-bundled-python`-paketissa se luo ensin virtuaaliympäristön ja asentaa `eclipse-zenoh`:n,
   TAK Server -tilassa myös `cryptography`:n), käynnistää relayn ja kertoo, mitä TAKiin pitää asettaa.
   - Automaattinen käynnistys yrittää ensin ajastettua tehtävää (kirjautuessa, ei
     ylläpito-oikeuksia). Jos tili ei saa luoda ajastettuja tehtäviä, asennus käyttää
     Käynnistys-kansion pikakuvaketta.
   - Kioskikoneet ilman kirjautunutta käyttäjää: `install.ps1 -AtSystemStartup`
     ylläpitäjän PowerShellissä (käynnistyy järjestelmän mukana SYSTEM-tilillä).
3. Vain suorassa tilassa: ohjaa päätteen CoT-tulo `device.env`-tiedoston porttiin `TAK_UDP_PORT`
   (oletus 6969) ja tarvittaessa sen UDP-ulostulo porttiin `TAK_UDP_IN_PORT` PLI:tä
   varten. Lähiverkko- ja TAK Server -tiloissa TAKiin ei aseteta mitään.
4. Avaa <http://localhost:8088/>: tilasivulla pitää lukea **Healthy**. Lokit:
   `logs/relay-VVVVKKPP.log`.

Asetusten muuttaminen: muokkaa `device.env`-tiedostoa (poista rivi `TAK_MODE` tai `RELAY_LANG`,
jos haluat, että se kysytään uudelleen), aja `uninstall.cmd` ja sitten `install.cmd`.
`device.env` voi sisältää TAK Server -varmenteen salasanan, joten suojaa kansio kuten avain. `uninstall` poistaa kumman tahansa käynnistystavan ja pysäyttää sekä
käynnistinsilmukan että relayn.

`run.ps1 -CheckOnly` ajaa `doctor.py`-tarkistuksen (Python, zenoh, sertifikaatit, NetBird, reititin,
portit) käynnistämättä relayta ja kertoo jokaiseen virheeseen korjauksen.

Jos haluat julkaista vain laitteen oman sijainnin, poista risuaita `device.env`-tiedoston
`TAK_INGEST_UIDS`-riviltä ja kirjoita päätteen uid.

Koko sykli (asennus → terve tila oikeaa fabricia vasten ja CoT useilta valmistajilta → poisto →
ei uudelleenkäynnistystä) on varmistettu Windows-kenttälaitteilla.
