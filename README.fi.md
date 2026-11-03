# EFDI TAK -relay

[![Tests](https://github.com/GionChan/Backbone-TAK-Integration/actions/workflows/tests.yml/badge.svg)](https://github.com/GionChan/Backbone-TAK-Integration/actions/workflows/tests.yml)

**In English:** [README.md](README.md) · **Tekoälyagenteille:** [AGENTS.md](AGENTS.md)

Kaksisuuntainen silta **EFDI goat -fabricin** (Zenoh, mTLS, NetBird-mesh) ja
**TAK-sovellusten** (WinTAK, ATAK, TAK Server) välillä.

- **Backbone → TAK.** Jokainen tunnistettava sijaintiviesti muuttuu CoT-merkiksi: muiden
  valmistajien valmis CoT-XML, `goat.geo.track.v1`, MAVLink, Consilium, HYMOTS, Orion, ADS-B,
  protobuf-radat ja oma JSON-telemetria. Viestit tarkistetaan, niiden tahtia rajoitetaan ja
  kaksoiskappaleet poistetaan ennen kuin ne lähetetään asiakkaalle.
- **TAK → backbone.** Valinnaisesti omien TAK-käyttäjien sijainnit (PLI) julkaistaan backboneen.
- **Operointi.** Pakollinen heartbeat, `/healthz`, Prometheus-mittarit (`/metrics`), `/status`,
  `/streams`-näkymä backbonen liikenteeseen, watchdog, joka käynnistää relayn uudelleen yhteyden
  tai datan katketessa, sekä valinnainen videon uudelleenlähetys (RTSP) TAKiin.

## Repon sisältö

| Polku | Mikä se on | Käyttötarkoitus |
| --- | --- | --- |
| [`relay/`](relay/) | **Tuote: TAK-relay** (`tak_gateway.py` moduuleineen) | Ajo oikeaa fabricia vasten |
| [`tools/`](tools/) | Kenttälaitepaketin rakentaja, portaalin topic-rekisteröinti | Käyttöönotto |
| [`demo/scenarios/`](demo/scenarios/) | **Demoskenaariot**: lennokkiparvi, iskuosasto, massahyökkäys-CSV | Esittely |
| [`demo/sender.py`](demo/sender.py) | **Demon lähetin**: ainoa reitti demodatalle backboneen, merkitsee kaiken simuloiduksi | Uudet skenaariot |
| [`demo/`](demo/) (muut) | Kartta, paikallinen reititin, käynnistin, monitori, edge-AI-demo | Esittely |
| [`tests/`](tests/) | Yksikkötestit ja paikallinen päästä päähän -testi | Kehitys |
| [`docs/`](docs/) | Dokumentaatio [englanniksi](docs/en/) ja [suomeksi](docs/fi/), AsyncAPI-kuvaus | Lukeminen |

Relay ei tuo mitään `demo/`-kansiosta. Demodata merkitään aina harjoitusdataksi ja julkaistaan
omaan namespaceensa, joten sitä ei voi sekoittaa oikeaan sensoridataan.

## Pikaohje: relay

Edellytykset: NetBird-yhteys EFDI-meshiin, Docker ja oma onboarding-bundle.

```bash
mkdir certs && cp /polku/bundleen/{*-cert.pem,*-key.pem,efdi-ca-root.pem} certs/
cp .env.example .env           # valinnainen: TAK-kohteet, järjestelmänimi, PLI
docker compose up -d           # käynnistää pelkän relayn
docker compose exec tak-relay python3 relay/doctor.py   # esitarkistus: kertoo ongelman ja korjauksen
```

Tilasivu on osoitteessa <http://localhost:8088/>. Se muuttuu vihreäksi, kun yhteys on ylhäällä
ja dataa tulee.

Valitse `.env`-tiedostossa `TAK_MODE`-muuttujalla, miten TAK-laitteet saavat tilannekuvan:
`direct` (oletus), `multicast` (TAKiin ei aseteta mitään, vain suljetut verkot) tai `server` (syötä
TAK Serveriä). Ks. [tilan valinta](docs/fi/modes.md). `direct`-tilassa ohjaa TAK-sovellus relayhin:

- **TAK app:** UDP-tulo 6969 Docker-isännällä (oletuskohde).
- **WinTAK:** lisää `host.docker.internal:4242` muuttujaan `TAK_UDP_TARGETS` (`.env`).
- **ATAK tai WinTAK TCP:llä:** TAK Server → TCP Streaming → `<relayn-osoite>:8087`.
- **TAK Server:** aseta `.env`-tiedostoon `TAK_SERVER` ja sen .p12-tiedostot. Silloin jokainen
  serverin käyttäjä näkee backbonen. Ks. [relay: TAK Server](docs/fi/relay.md#tak-server).

Backboneen menevät vain omien laitteiden sijainnit ja vain, kun `TAK_INGEST=1`. TAK Serverin
käyttäjien sijainteja ei julkaista koskaan.

Kenttälaitteet ilman Dockeria: itseasentuva paketti komennolla
`python tools/make_relay_package.py --system <nimi>`, ks. [kenttäpaketti](docs/fi/field-package.md).

## Pikaohje: demo

```powershell
.\demo\run-backbone-demo.ps1 -BundleDir C:\polku\bundleen   # Windows, ensimmäinen kerta
```

tai millä tahansa käyttöjärjestelmällä:

```bash
docker compose --profile demo up -d          # relay + paikallinen reititin + kartta + lennokkiparvi
python demo/scenarios/strike_package.py      # toinen skenaario tältä koneelta
```

Kartta: <http://localhost:8080>, skenaariot ja CSV-toisto osoitteessa `/control`. Ilman
sertifikaatteja kaikki toimii paikallista reititintä vasten ilman verkkoyhteyttä. Ks.
[demo-ohje](docs/fi/demo.md).

## Dokumentaatio

| | Suomi | English |
| --- | --- | --- |
| Yleiskuva ja arkkitehtuuri selkokielellä | [yleiskuva](docs/fi/overview.md) | [overview](docs/en/overview.md) |
| Tilan valinta: suora, lähiverkko (multicast) tai TAK Server | [tilat](docs/fi/modes.md) | [modes](docs/en/modes.md) |
| Relay: asetukset, topicit, operointi, tietoturva | [relay](docs/fi/relay.md) | [relay](docs/en/relay.md) |
| Demo: skenaariot, lähetin, näkymät | [demo](docs/fi/demo.md) | [demo](docs/en/demo.md) |
| Kenttälaitepaketti (Windows, ei Dockeria) | [kenttäpaketti](docs/fi/field-package.md) | [field package](docs/en/field-package.md) |
| Vianetsintä | [vianetsintä](docs/fi/troubleshooting.md) | [troubleshooting](docs/en/troubleshooting.md) |
| Rajapintakuvaus | [`docs/asyncapi-tak-gateway.yaml`](docs/asyncapi-tak-gateway.yaml) | |
| Muutokset | [CHANGELOG](CHANGELOG.md) | |

## Kehitys

```bash
pip install -r relay/requirements.txt
python -m unittest discover -s tests                  # yksikkötestit
docker compose --profile demo up -d zenoh-router
python tests/e2e_gateway.py                           # päästä päähän paikallista reititintä vasten
```

CI ajaa yksikkötestit Windowsilla ja Linuxilla jokaisesta main-haaran pushista ja pull requestista.

## Tila

Relayn koko
polku (asennus → terve tila oikeaa fabricia vasten → CoT useilta valmistajilta → poisto) on
varmistettu Windows-kenttälaitteilla. Oikealla TAK-asiakkaalla ei ole varmistettu ATAK-
yhteyspakettia eikä CoT:n `<video>`-elementtiä (ks. [relay](docs/fi/relay.md#tunnetut-rajoitukset)).

## Lisenssi

Apache License 2.0, ks. [LICENSE](LICENSE).
