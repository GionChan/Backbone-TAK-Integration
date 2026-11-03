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
| `identity.py` | Etsii sertifikaattibundlen ja slotin (vain standardikirjasto) |
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
| `GOAT_CERT_DIR` | `<repo>/certs`, `./certs`, `/certs` | Bundlen hakemisto. Kun asetettu, haetaan vain siitä |
| `GOAT_ORG` | sertifikaatin CN | Slot. Tarvitaan vain, jos CN ei ole slot |
| `GOAT_ROUTER` | `tls/router.example:7447` | mTLS-reititin. Ota bundlesta, jos se on eri |
| `GOAT_LOCAL_ROUTER` | `tcp/localhost:7447` | Reititin, kun bundlea ei löydy |
| `GOAT_LEASE_MS` | `60000` | Zenohin lease-aika; pitkä, koska välitetyt mesh-yhteydet takkuavat |

Bundlehakemistossa pitää olla täsmälleen yksi `<etuliite>-cert.pem`- ja `<etuliite>-key.pem`-pari
sekä CA-juuri (`efdi-ca-root.pem`). Jos sertifikaatti löytyy mutta slotia ei saada selville, relay
ei käynnisty, koska slotin ulkopuolelle kirjoitetut viestit hylättäisiin ilman virheilmoitusta.

## Backbone → TAK

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `GATEWAY_INGEST_ALL` | `0` natiivisti, `1` composessa | `1`: tilaa `**` ja muunna kaikki tunnistetut muodot. `0`: vain `GATEWAY_COT_KE` |
| `GATEWAY_COT_KE` | `*/tak/cot/v1/**` | Minkä tahansa valmistajan valmis CoT (kun `GATEWAY_INGEST_ALL=0`) |
| `GATEWAY_SOURCES` | kaikki | Osajoukko: `xml,geotrack,consilium,mavlink,hymots,orion,adsb,alerts,roi,proto` |
| `GATEWAY_HYMOTS_INTERVAL_S` | `10` | HYMOTS-jäljen lyhin päivitysväli |
| `XV_MAX_HZ_PER_UID` | `2` | Tahtiraja uidia kohden `GATEWAY_COT_KE`-liikenteelle |
| `COT_TYPE` | `a-h-A-M-F-Q` | CoT-varatyyppi |

Oma JSON-telemetria polussa `<slot>/sensor/v1/**` (`{source, lat, lon, alt, heading,
speed_kmh, type, phase, lost}`) muunnetaan aina. `"lost": true` lähettää vanhentuneen merkin,
jolloin TAK poistaa jäljen. Avaimia, joissa on `video`, `keyframe` tai `asterix-raw`, sekä
heartbeateja ja relayn omaa PLI:tä ei koskaan muunneta.

## Ulostulot

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `TAK_UDP_TARGETS` | `TAK_HOST:TAK_UDP_PORT` | `osoite:portti[,osoite:portti…]`, CoT UDP:llä. TAK app 6969, WinTAK 4242 |
| `TAK_HOST`, `TAK_UDP_PORT` | `127.0.0.1`, `6969` | Yksi UDP-kohde (vanhempi muoto) |
| `TAK_PORT` | `8087` | TCP-palvelin ATAK- ja WinTAK-striimausasiakkaille |
| `GATEWAY_CONFIG` | – | JSON-tiedosto, joka korvaa yllä olevat; myös TAK Server -yhteydet TCP:llä tai TLS:llä |

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

## TAK → backbone (PLI)

| Muuttuja | Oletus | Merkitys |
| --- | --- | --- |
| `TAK_INGEST` | `0` | `1`: julkaise omat (friendly) CoT-tapahtumat polkuun `<slot>/tak/pli/v1/<uid>` |
| `TAK_INGEST_TYPES` | `a-f-` | Hyväksytyt tyyppietuliitteet pilkulla erotettuina |
| `TAK_UDP_IN_PORT` | `0` (compose: `6971`) | UDP-portti TAK-asiakkaiden CoT:lle (esim. TAK-sovelluksen ulostulo) |

Myös porttiin `:8087` yhdistäneiden TCP-asiakkaiden lähettämät tapahtumat luetaan. Enintään
yksi päivitys sekunnissa uidia kohden; tehtävätyyppejä (`t-*`) ja muita kuin omia tyyppejä ei
julkaista. Tämä kirjoittaa jaettuun backboneen, joten se on oletuksena pois päältä.

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

| Polku | Sisältö |
| --- | --- |
| `/healthz` | 200, kun yhteys fabriciin on ylhäällä, muuten 503 |
| `/metrics` | Prometheus-teksti: lähetykset, virheet ja pudotukset ulostuloittain, pudotusten syyt, nähdyt tyypit |
| `/status` | JSON: terveystila syineen, laskurit, ulostulot, PLI, video |
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
- **Porteissa 8087, 8088, 6971 ja 8554 ei ole tunnistautumista.** `/api/sample` palauttaa
  puskuroitua backbone-dataa. Avaa portit vain paikalliselle koneelle tai luotettuun verkkoon ja
  estä ne palomuurilla muualta.
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
