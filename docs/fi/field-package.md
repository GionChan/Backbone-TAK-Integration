# Kenttälaitepaketti (Windows ja Linux, ei Dockeria)

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
| `--share-markers` | kysytään asennuksessa | `on` tai `off`: `TAK_SHARE_MARKERS`, merkit ja piirrokset backboneen |
| `--ingest-uids` | – | `TAK_INGEST_UIDS`: laitteiden uidit (`*` = kaikki), joiden sijainnin saa julkaista |
| `--cert-dir` | `./certs` | Mukaan otettava bundle (yksi sertifikaatti- ja avainpari + CA) |
| `--tak-host`, `--tak-udp-port` | `127.0.0.1`, `6969` | Missä TAK-pääte kuuntelee CoT:tä |
| `--tak-port` | `8087` | TCP-striimin portti |
| `--tak-udp-in-port` | `6971` | UDP-portti päätteen PLI:lle |
| `--no-ingest` | pois | Älä julkaise päätteen omaa sijaintia |
| `--router` | bundlen `NOTES.md` (pakollinen ilman sitä) | Zenohin mTLS-reititin |
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
   4. **Merkkien ja piirrosten jako:** pois tai päälle (kaikki CoT-merkit ja piirrokset, myös
      vihollismerkit, menevät backboneen; viestit eivät koskaan).

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

## Linux

Paketti rakennetaan valinnalla `--platform linux`:

```bash
python tools/make_relay_package.py --system field-relay-02 --platform linux   # → dist/field-relay-02-tak-relay-linux.tar.gz
```

`.tar.gz`-paketissa on yksi kansio, jossa ovat `app/`, `certs/`, `device.env`, `install.sh`,
`run.sh`, `uninstall.sh`, `common.sh`, `lang.txt` (kaikki viestit suomeksi ja englanniksi), ohjeet
molemmilla kielillä sekä riippuvuuksien wheelit x86_64- ja aarch64-koneille (Python 3.10–3.13,
noin 40 Mt). Valinnat ovat samat kuin Windows-paketissa; `--no-bundled-wheels` jättää wheelit
pois, jolloin laite tarvitsee verkkoyhteyden asennukseen. Skriptit ovat kansiossa
`tools/field_package/linux/`.

Laitteessa pitää olla glibc 2.28 tai uudempi (esim. Debian 10+, Ubuntu 20.04+ tai 64-bittinen
Raspberry Pi OS), Python 3.10+ venv-moduulin kanssa (`sudo apt install python3 python3-venv`) ja
bash. Musl-pohjaisia järjestelmiä, kuten Alpinea, ei tueta.

Asenna sillä käyttäjällä, joka ajaa relayta, ei pääkäyttäjänä:

```bash
tar -xzf field-relay-02-tak-relay-linux.tar.gz && cd field-relay-02-tak-relay-linux
./install.sh             # käyttäjän systemd-palvelu: käynnistyy, kun kirjaudut sisään
./install.sh --at-boot   # systemd-palvelu, joka käynnistyy koneen mukana; sudo vain asennukseen
```

Asennin kysyy samat asiat kuin Windows-asennin. Suorassa tilassa se kysyy lisäksi, minne CoT
lähtee UDP:llä (`TAK_UDP_TARGETS`) ja minkä muiden laitteiden oman sijainnin saa julkaista
(`TAK_INGEST_UIDS`): Linuxissa TAK-sovellukset ovat yleensä muissa laitteissa, ja ilman listaa
julkaistaan vain tämän koneen TAK-sovellusten sijainnit.

- `--at-boot`-palvelu ajetaan asentavana käyttäjänä, ei koskaan pääkäyttäjänä.
- Jos käyttäjän systemd-istuntoa ei ole, asennin lisää käyttäjän crontabiin `@reboot`-rivin.
- Pakettikansion ja `certs/`-kansion oikeuksiksi asetetaan 700, avaimen, .p12-tiedostojen ja
  `device.env`-tiedoston 600.
- `./run.sh --check-only` ajaa `doctor.py`-tarkistuksen, lokit ovat kansiossa `logs/`, ja
  `./uninstall.sh` poistaa automaattisen käynnistyksen ja pysäyttää relayn.
- Palomuurin (esim. ufw) pitää päästää TAK-laitteet TCP-porttiin 8087 ja UDP-porttiin 6971
  (suora tila) tai multicast-ryhmään (lähiverkko). Lähiverkkotila toimii Linuxissa natiivisti,
  toisin kuin Docker Desktopissa.

CI asentaa, tarkistaa ja poistaa Linux-paketin Ubuntussa jokaisen `main`-haaran pushin ja pull
requestin yhteydessä sekä ennen jokaista julkaisua. Paketti on vielä kokeilematta kenttälaitteella
oikeiden TAK-laitteiden kanssa.
