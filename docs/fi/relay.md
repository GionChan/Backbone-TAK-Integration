# TAK-relay

**In English:** [../en/relay.md](../en/relay.md)

`relay/tak_gateway.py` ja sen vieressä olevat moduulit. Python 3.10+, yksi pakollinen riippuvuus
(`eclipse-zenoh==1.9.0`). Ajetaan Dockerissa (`docker compose up -d`) tai natiivisti
(`python relay/tak_gateway.py` tai [kenttäpaketti](field-package.md)).

## Moduulit

| Tiedosto | Tehtävä |
| --- | --- |
| `tak_gateway.py` | Käynnistyspiste: tilaukset, ulostulot, PLI, HTTP-rajapinnat, watchdog |
| `goat_connect.py` | Zenoh-istunnon asetukset: mTLS fabriciin tai paikallinen reititin ilman sertifikaatteja |
| `identity.py` | Etsii sertifikaattibundlen, slotin ja reitittimen (vain standardikirjasto) |
| `tak_links.py` | TAK-puolen asetukset: UDP-kohteet, TAK Server -yhteys ja sen TLS (.p12 tai PEM) |
| `doctor.py` | Esitarkistus: `python relay/doctor.py` |
| `status_page.py` | Tilasivu osoitteessa `/` |
| `backbone_cot.py` | Tunnistaa valmistajien datamuodot ja muuntaa ne CoT-muotoon |
| `cot_guard.py` | CoT-tarkistus ja avainkohtainen tahdinrajoitin |
| `symbology.py` | CoT-tyyppi (osapuoli, ulottuvuus) tekstistä, SIDC-koodista tai liiketiedoista |
| `heartbeat.py` | Pakollinen heartbeat |
| `stream_view.py` | `/streams`-sivu: backbonen liikenne ja esikatselut |
| `video_relay.py` | Backbonen MPEG-TS → MediaMTX → RTSP, CoT-merkki `<video>`-elementillä |
| `gateway_core.py` | Puhtaat apufunktiot: CoT-virran pilkonta, Prometheus-teksti, ATAK-paketti |
| `make_atak_package.py` | Komentorivityökalu: ATAK/WinTAK-yhteyspaketti (`<osoite> [portti] [out.zip]`) |

## Identiteetti ja yhteys

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `GOAT_CERT`, `GOAT_KEY`, `GOAT_CA` | – | PEM-tiedostojen polut (kaikki kolme) |
| `GOAT_CERT_DIR` | `<repo>/certs`, `./certs`, `/certs`, sitten `~/Downloads/efdi-onboarding-*` | Bundlen hakemisto. Kun asetettu, haetaan vain siitä |
| `GOAT_ORG` | sertifikaatin CN | Slot. Tarvitaan vain, jos CN ei ole slot |
| `GOAT_ROUTER` | bundlen `NOTES.md`-tiedoston `Router endpoint`, muuten `tls/router.example:7447` | mTLS-reititin |
| `GOAT_LOCAL_ROUTER` | `tcp/localhost:7447` | Reititin, kun bundlea ei löydy |
| `GOAT_LEASE_MS` | `60000` | Zenohin lease-aika; pitkä, koska välitetyt mesh-yhteydet takkuavat |

Bundlehakemistossa pitää olla täsmälleen yksi `<etuliite>-cert.pem`- ja `<etuliite>-key.pem`-pari
sekä CA-juuri (`efdi-ca-root.pem`). Jos sertifikaatti löytyy mutta slotia ei saada selville, relay
ei käynnisty, koska slotin ulkopuolelle kirjoitetut viestit hylättäisiin ilman virheilmoitusta.

Jos muuta bundlea ei löydy, relay käyttää Lataukset-kansioon purettua onboarding-bundlea
(`~/Downloads/efdi-onboarding-*`), kun tällaisia hakemistoja on täsmälleen yksi. Jos niitä on
useampia, aseta `GOAT_CERT_DIR`.

## Backbone → TAK

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `GATEWAY_INGEST_ALL` | `0` natiivisti, `1` composessa | `1`: tilaa `**` ja muunna kaikki tunnistetut muodot. `0`: vain `GATEWAY_COT_KE` |
| `GATEWAY_COT_KE` | `*/tak/cot/v1/**` | Minkä tahansa valmistajan valmis CoT (kun `GATEWAY_INGEST_ALL=0`) |
| `GATEWAY_SOURCES` | kaikki | Osajoukko: `xml,geotrack,consilium,mavlink,hymots,orion,adsb,alerts,roi,proto` ([muodot](#tunnistetut-muodot)) |
| `GATEWAY_HYMOTS_INTERVAL_S` | `10` | `hymots`-lähteen jäljen lyhin päivitysväli |
| `XV_MAX_HZ_PER_UID` | `2` | Tahtiraja uidia kohden `GATEWAY_COT_KE`-liikenteelle |
| `COT_TYPE` | `a-h-A-M-F-Q` | CoT-varatyyppi |

Oma JSON-telemetria polussa `<slot>/sensor/v1/**` (`{source, lat, lon, alt, heading,
speed_kmh, type, phase, lost}`) muunnetaan aina. `"lost": true` lähettää vanhentuneen merkin,
jolloin TAK poistaa jäljen. Avaimia, joissa on `video`, `keyframe` tai `asterix-raw`, sekä
heartbeateja ja relayn omaa PLI:tä ei koskaan muunneta.

### Tunnistetut muodot

| Lähde (`GATEWAY_SOURCES`) | Sisältö |
| --- | --- |
| `xml` | Valmis CoT-`<event>` millä tahansa avaimella, välitetään sellaisenaan tarkistuksen jälkeen |
| `geotrack` | JSON, jonka skeema on `goat.geo.track.v1` |
| `consilium` | Consilium-JSON: `ci_uuid`, `location.latitude/longitude` |
| `mavlink` | MAVLink-JSON: `mavpackettype` `GLOBAL_POSITION_INT` |
| `hymots` | HYMOTS-JSON: `agents[]`, joissa `location` ja `sidc` |
| `orion` | Orion-JSON: `entityId`, `location.position` |
| `adsb` | ADS-B-JSON: `kind` `uk-adsb-assessment`, `aircraft[]` |
| `alerts` | Hälytys-JSON: `alert_text`, `event.locations[]` |
| `roi` | Kiinnostava alue: `MAV_CMD_DO_SET_ROI_LOCATION` |
| `proto` | Protobuf-radat |

## Ulostulot

`TAK_MODE` valitsee kokoonpanon; ks. [tilan valinta](modes.md). Alla olevilla muuttujilla sitä
voi hienosäätää.

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `TAK_MODE` | `direct` | `direct`, `multicast` tai `server` |
| `TAK_LOCAL_OUTPUTS` | `0` | `server`-tila: `1` pitää myös UDP- ja TCP-lähdöt päällä |
| `TAK_MULTICAST_GROUP`, `TAK_MULTICAST_IF`, `TAK_MULTICAST_TTL` | `239.2.3.1:6969`, käyttöjärjestelmän valinta, `1` | `multicast`-tila, ks. [tilat](modes.md#multicast) |
| `TAK_UDP_TARGETS` | `TAK_HOST:TAK_UDP_PORT` | `osoite:portti[,osoite:portti…]`, CoT UDP:llä. Oletusportti 6969; WinTAK kuuntelee porttia 4242 |
| `TAK_HOST`, `TAK_UDP_PORT` | `127.0.0.1`, `6969` | Yksi UDP-kohde (vanhempi muoto) |
| `TAK_PORT` | `8087` | TCP-palvelin ATAK- ja WinTAK-striimausasiakkaille |
| `TAK_MAX_CLIENTS` | `64` | TCP-asiakkaiden enimmäismäärä; sen ylittävät yhteydet hylätään |
| `TAK_SERVER` | – | TAK Serverin `osoite[:portti]`, jolle virta lähetetään (ks. alla) |
| `GATEWAY_CONFIG` | – | JSON-tiedosto, joka korvaa kaikki yllä olevat |

```json
{"outputs": [{"type": "udp", "host": "host.docker.internal", "port": 6969},
             {"type": "tcp_server", "port": 8087},
             {"type": "tcp_client", "host": "tak.example", "port": 8089,
              "tls": {"cert": "c.pem", "key": "k.pem", "ca": "ca.pem", "verify_hostname": true}}],
 "ingest": false}
```

Jokaisella TCP-asiakkaalla on oma jono (1 000 tapahtumaa) ja kirjoitussäie. Asiakas, joka
lakkaa lukemasta, täyttää vain oman jononsa, ja yhteys katkaistaan, jos lähetys ei etene
10 sekuntiin (`gateway_output_dropped_total`).

## TAK Server

Kun `TAK_SERVER` on asetettu, relay lähettää virran myös TAK Serverille, ja jokainen serverin
käyttäjä näkee backbonen tilannekuvan. Yksi relay TAK Serveriä kohden riittää; serverin laitteet
eivät tarvitse omaa relayta.

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `TAK_SERVER` | – | `osoite[:portti]`, portti 8089, jos sitä ei anneta |
| `TAK_SERVER_TLS` | `1` (portissa 8087 `0`) | TLS ja asiakasvarmenne |
| `TAK_SERVER_P12`, `TAK_SERVER_P12_PASSWORD` | – | TAK Serverin myöntämä asiakasvarmenne (.p12) |
| `TAK_SERVER_TRUST_P12`, `TAK_SERVER_TRUST_PASSWORD` | –, P12-salasana | Truststore, jossa on TAK Serverin CA (.p12) |
| `TAK_SERVER_CERT`, `TAK_SERVER_KEY`, `TAK_SERVER_CA` | – | PEM-tiedostot .p12:n sijaan |
| `TAK_SERVER_VERIFY_HOSTNAME` | `1` | `0`, jos serverin varmenteessa ei ole käyttämääsi osoitetta |

.p12-tiedostot tarvitsevat `cryptography`-kirjaston (mukana `relay/requirements.txt`-tiedostossa
ja Docker-imagessa). Purettua avainta ei jätetä levylle. Dockerissa tiedostot laitetaan
kansioon `certs/tak/`, ja polut ovat muotoa `/certs/tak/…`. Väärä salasana tai tiedosto
pysäyttää relayn käynnistyksessä selkeään virheilmoitukseen, ja `doctor.py` testaa yhteyden
muodostuksen. TAK Serverin käyttäjiä ei koskaan julkaista backboneen (ks. seuraava luku).

Älä syötä samoja laitteita sekä suoraan (UDP tai `:8087`) että TAK Serverin kautta, koska silloin
jokainen merkki tulee kahdesti. Valitse jokaiselle laitteelle yksi reitti.

## TAK → backbone (PLI)

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `TAK_INGEST` | `0` | `1`: julkaise omat (friendly) CoT-tapahtumat polkuun `<slot>/tak/pli/v1/<uid>` |
| `TAK_INGEST_TYPES` | `a-f-` | Hyväksytyt tyyppietuliitteet pilkulla erotettuina |
| `TAK_INGEST_FROM` | `local` (`multicast`-tilassa `local,lan`) | Mistä yhteyksistä saa julkaista: `local` (UDP-sisääntulo, porttiin `:8087` yhdistäneet asiakkaat), `lan` (multicast-ryhmä, vain `TAK_INGEST_UIDS`-listan kanssa), `server` (TAK Server -yhteys). Pilkulla erotettuina |
| `TAK_INGEST_UIDS` | tyhjä | Julkaistavien laitteiden uidit pilkulla erotettuina (esim. `ANDROID-abc123`). Tyhjä = vain tämän koneen TAK-sovellukset (loopback) |
| `TAK_UDP_IN_PORT` | `0` (compose: `6971`) | UDP-portti TAK-asiakkaiden CoT:lle (niiden UDP-ulostulo) |

Myös porttiin `:8087` yhdistäneiden TCP-asiakkaiden lähettämät tapahtumat luetaan. Enintään
yksi päivitys sekunnissa uidia kohden; tehtävätyyppejä (`t-*`) ja muita kuin omia tyyppejä ei
julkaista. Tämä kirjoittaa jaettuun backboneen, joten se on oletuksena pois päältä.

Backboneen julkaistaan vain omien laitteiden sijainnit:

- **TAK Serverin käyttäjät pysyvät TAK Serverillä.** `tcp_client`-yhteydessä kulkevat kaikkien
  serverin käyttäjien tiedot. Ne näytetään TAKissa, mutta niitä ei julkaista backboneen, ellei
  asetuksena ole `TAK_INGEST_FROM=local,server`.
- **Vain tämä kone, ellei laitetta ole listattu.** Ilman `TAK_INGEST_UIDS`-listaa julkaistaan
  vain tältä koneelta (127.0.0.1) tulevat tapahtumat. Muuten kuka tahansa verkossa voisi
  julkaista sijainteja backboneen sinun slotissasi. Jos haluat julkaista toisen koneen laitteen,
  lisää sen uid listaan.
- **Sallittujen lista.** Kun `TAK_INGEST_UIDS` on asetettu, julkaistaan vain listatut uidit,
  vaikka terminaali välittäisi muidenkin sijainteja. Laite ilmoittaa uidinsa itse, joten lista
  estää vahingot mutta ei tahallista väärentäjää: pidä portit 6971 ja 8087 poissa
  epäluotettavista verkoista.
- **Ei kaikua.** Uidia, jonka relay on itse lähettänyt TAKiin viimeisen 60 sekunnin aikana, ei
  julkaista takaisin.

Dockerissa isännän paketit eivät tule osoitteesta 127.0.0.1, joten siellä `TAK_INGEST=1` vaatii
`TAK_INGEST_UIDS`-listan.

Hylätyt tapahtumat lasketaan mittariin
`gateway_ingest_dropped_total{reason="not-local"|"not-loopback"|"not-allowed"|"echo"|"relayed"}` (`relayed`:
tapahtumassa on toisen relayn merkintä, ks. [tilat](modes.md#kaikissa-tiloissa)), ja `/status` näyttää
asetukset `ingest_from` ja `ingest_uids`.

## Heartbeat ja terveystila

Oikeaan fabriciin yhdistettynä relay julkaisee viestin `<slot>/<GATEWAY_SYSTEM>/heartbeat/v1`
`GOAT_HEARTBEAT_INTERVAL_S` sekunnin välein (60 s): `{key, system, status, version, sent_at,
seq, interval_seconds}`. `status` on `ok` vain, kun yhteys fabriciin on ylhäällä, dataa on
tullut viimeisen 120 sekunnin aikana ja kaikki ulostulot ovat kytkettyinä, muuten `degraded`.
`GATEWAY_SYSTEM` (oletus `tak-gateway`) pitää rekisteröidä portaaliin
(`tools/register_portal_topics.py`). `GATEWAY_HEARTBEAT=0` poistaa heartbeatin käytöstä, ja
`GATEWAY_VERSION` korvaa raportoidun version.

Watchdog: prosessi päättyy (Docker tai kenttäpaketin käynnistin käynnistää sen uudelleen), kun
yhteys fabriciin on ollut poikki `GATEWAY_LOST_S` sekuntia (300) tai dataa ei ole tullut
`GATEWAY_WATCHDOG_S` sekuntiin (300).

## HTTP-rajapinnat (`GATEWAY_HTTP_PORT`, oletus 8088)

HTTP-portti kuuntelee osoitetta `GATEWAY_HTTP_BIND`, oletuksena `127.0.0.1` (vain tämä kone),
koska siinä ei ole tunnistautumista ja `/api/sample` palauttaa backbonen dataa. Docker-image
asettaa kontin sisällä arvon `0.0.0.0`, ja `docker-compose.yml` julkaisee portin vain isännän
osoitteeseen `127.0.0.1`. Jos porttiin pitää päästä toiselta koneelta, aseta
`GATEWAY_HTTP_BIND=0.0.0.0` (natiivisti) tai muuta composen porttimääritystä, ja rajaa pääsy
palomuurilla.

| Polku | Sisältö |
| --- | --- |
| `/` | Tilasivu ihmisille: terveystila, syyt, ulostulot, liikenne, pudotukset |
| `/healthz` | 200, kun yhteys fabriciin on ylhäällä, muuten 503 (Dockerin `HEALTHCHECK`) |
| `/metrics` | Prometheus-teksti: lähetykset, virheet ja pudotukset ulostuloittain, pudotusten syyt, nähdyt tyypit |
| `/status` | JSON: terveystila syineen, versio, slot, järjestelmänimi, laskurit, ulostulot, PLI-asetukset, video |
| `/streams` | Selainnäkymä backbonen liikenteeseen avainryhmittäin, kuva- ja videoesikatselu |
| `/api/streams`, `/api/sample?g=`, `/api/preview?g=`, `/api/video?g=` | `/streams`-näkymän data |

## Video (valinnainen)

`GATEWAY_VIDEO=1` (vaatii `GATEWAY_INGEST_ALL=1`) lähettää backbonen MPEG-TS-videon uudelleen:
jokaiselle kameralle käynnistyy oma ffmpeg-prosessi, joka työntää kuvan MediaMTX-palvelimelle.
TAK-asiakkaat hakevat sen osoitteesta `rtsp://GATEWAY_VIDEO_HOST:GATEWAY_VIDEO_PORT/<kamera>` ja
saavat CoT-merkin, jossa on `<video>`-elementti ("Play Video"). `GATEWAY_VIDEO_HOST` on osoite,
jota TAK-asiakkaat käyttävät, ei koskaan `host.docker.internal`. `GATEWAY_VIDEO_IDLE_S` (120)
pysäyttää käyttämättömän kameran, ja `GATEWAY_VIDEO_REPUBLISH_S` (30) päivittää merkin. ffmpeg ja
mediamtx ovat Docker-imagessa valmiina.

## Tietoturva

- **Sertifikaatit** (`certs/`, `*.pem`, `*.key`, `*.cbor`) ja **kenttäpaketit** (`dist/`) on
  rajattu versionhallinnan ulkopuolelle, koska ne sisältävät yksityisen avaimen. Älä koskaan
  commitoi tai jaa niitä.
- **Porteissa 8087, 8088, 6971 ja 8554 ei ole tunnistautumista.** Näin TAKin tavalliset
  CoT-tulot toimivat: verkon TAK-laitteiden pitää tavoittaa portit 8087, 6971 ja 8554, joten ne
  kuuntelevat kaikkia liitäntöjä. Portti 8088 (`/api/sample` palauttaa puskuroitua
  backbone-dataa) kuuntelee oletuksena vain tätä konetta. Pidä relay luotetussa verkossa ja estä
  portit palomuurilla muualta.
- **TCP-asiakkaiden määrä on rajattu** muuttujalla `TAK_MAX_CLIENTS` (64); sen ylittävät
  yhteydet hylätään (`gateway_output_rejected_total`).
- **Vähimmät oikeudet fabricissa.** Relay lukee laajasti (`**`, kun `GATEWAY_INGEST_ALL=1`), mutta
  kirjoittaa vain heartbeateja ja `TAK_INGEST=1`-asetuksella PLI:tä omaan slotiinsa.
- **Epäluotettava syöte.** Muiden valmistajien CoT tarkistetaan ennen välittämistä (ei DTD:tä,
  koko- ja koordinaattirajat, vanhenemistarkistus). Generoidun CoT:n kenttäarvot escapetaan.
- **Kontti** ajetaan käyttäjänä UID 10001. Linuxilla liitetyn avaimen pitää olla sen luettavissa.

## Tunnetut rajoitukset

- ATAK-yhteyspaketti (`make_atak_package.py`) ja CoT:n `<video>`-elementti on kirjoitettu
  TAK-dokumentaation perusteella, eikä niitä ole vielä varmistettu oikealla TAK-asiakkaalla.
  MediaMTX-putki itsessään on varmistettu päästä päähän.
- Kenttälaitteet käyttävät organisaation yhteistä sertifikaattia; laitekohtaisesti eroaa vain
  `GATEWAY_SYSTEM`.
- TAK Server -yhteys on testattu paikallista TLS-palvelinta ja asiakasvarmennetta vasten, mutta
  ei vielä oikeaa TAK Serveriä vasten.
