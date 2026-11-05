# Demo

**In English:** [../en/demo.md](../en/demo.md)

Demo näyttää relayn toiminnan päästä päähän: simuloidut jäljet tulevat backboneen, relay muuttaa
ne TAK-merkeiksi ja kartta näyttää samat jäljet selaimessa. Relayn ajamiseen ei tarvita mitään
`demo/`-kansiosta.

## Osat

| Osa | Tiedosto | Tehtävä |
| --- | --- | --- |
| **Skenaariot** | `demo/scenarios/swarm_orbit.py` | 4 UAV:ta idästä, kiertävät kohdealueen yllä, 10 minuutin sykli |
| | `demo/scenarios/strike_package.py` | 10 UAV:ta lähtöalueelta kohteeseen eri nopeuksilla ja korkeuksilla |
| | `demo/scenarios/mass_raid.csv` | Massahyökkäys lähtöalueelta kohteeseen, toistetaan kartan ohjauspaneelista |
| **Lähetin** | `demo/sender.py` | Ainoa reitti demodatalle backboneen; lisää harjoitusmerkinnät |
| **Näkymät** | `demo/live_map.py` | Leaflet-kartta portissa `:8080`, ohjauspaneeli `/control` |
| | `demo/tools/live_monitor.py` | Harjoitus- ja sensorijäljet päätteessä |
| | `demo/tools/read_cot.py` | Tulostaa relayn TCP-portin CoT-virran |
| | `demo/tools/verify_efdi.py` | Tarkistaa, että mTLS-istunto fabriciin aukeaa |
| **Infra** | `demo/local_router.py` | Paikallinen Zenoh-reititin ilman verkkoyhteyttä |
| | `demo/run-backbone-demo.ps1` | Yhden komennon käynnistin Windowsille |
| | `demo/setup-certs.ps1` | Kopioi bundlen `certs/`-kansioon |
| **Edge-AI-demo** | `demo/edge_ai/` | Tunnistus ja paikannus → CoT, ks. sen [README](../../demo/edge_ai/README.md) |

## Lähettimen sopimus

Skenaariot vain laskevat sijainnit ja kutsuvat funktiota `Sender.track(uid, lat, lon, alt,
heading, speed_kmh, phase=…, cot_type=…, lost=…, **extra)`. Lähetin julkaisee:

| Avain | Sisältö |
| --- | --- |
| `<slot>/exercise/<skenaario>/v1/<uid>` | JSON, jossa `"exercise": true`, `"classification": "SIMULATED"`, selite, `seq`, `ts_ms` |
| `<slot>/tak/cot/v1/EXERCISE.<uid>` | CoT-merkki, kutsutunnus `EXERCISE <uid>`, huomautus alkaa sanalla `SIMULATED` |

Säännöt, joita jokainen skenaario noudattaa:

- Julkaise vain `demo/sender.py`:n kautta. Älä koskaan kirjoita demodataa polkuun
  `<slot>/sensor/v1/**`.
- Relay vie merkit TAKiin; skenaariot eivät lähetä suoraan TAK-asiakkaille.
- Kadonneesta jäljestä (`lost=True`) julkaistaan vain JSON; TAK-merkki vanhenee 15 sekunnissa.

Uusi skenaario on lyhyt skripti:

```python
import sender
with sender.open_session("oma-skenaario") as s:
    out = sender.Sender(s, "oma-skenaario")
    out.track("uav-1", 61.0, 25.0, alt=300, heading=90, speed_kmh=200, phase="ingress")
```

## Käynnistys

### Windows yhdellä komennolla

```powershell
.\demo\run-backbone-demo.ps1 -BundleDir C:\polku\bundleen   # ensimmäinen kerta kopioi sertifikaatit
.\demo\run-backbone-demo.ps1                                # myöhemmät kerrat
.\demo\run-backbone-demo.ps1 -NoSwarm | -EdgeAI | -EdgeApi | -Stop
```

Käynnistin tarkistaa meshin, käynnistää relayn demoasetuksilla (CoT UDP:llä porttiin 6969
ja WinTAKille porttiin 4242, PLI ja video päällä), demoprofiilin sekä iskuosastoskenaarion
natiivisti. Lokit tallentuvat kansioon `logs/`. Relay toimii Dockerissa, joten isännän
TAK-sovellusten PLI julkaistaan vain `TAK_INGEST_UIDS`-listan uideille (aseta muuttuja
komentotulkissa ennen käynnistystä).

### Linux tai macOS yhdellä komennolla

```bash
demo/run-backbone-demo.sh --bundle-dir /polku/bundleen   # ensimmäinen kerta kopioi sertifikaatit
demo/run-backbone-demo.sh                                # myöhemmät kerrat
demo/run-backbone-demo.sh --no-swarm | --edge-ai | --edge-api | --stop
```

Toimii kuten Windows-käynnistin. CoT lähtee UDP:llä isännän porttiin 6969 (muutettavissa
muuttujalla `TAK_UDP_TARGETS`). Linuxissa `demo/setup-certs.sh` antaa relayn kontille (UID 10001)
lukuoikeuden `certs/`-kansioon ryhmän 10001 kautta sudo-oikeudella.

### Mikä tahansa käyttöjärjestelmä

```bash
docker compose --profile demo up -d        # relay + paikallinen reititin + kartta + lennokkiparvi
python demo/scenarios/strike_package.py    # vaatii: pip install -r relay/requirements.txt
```

### Ilman verkkoyhteyttä (ei sertifikaatteja, ei meshiä)

Jätä `certs/` tyhjäksi. Silloin kaikki osat käyttävät paikallista reititintä (`zenoh-router`,
portti `:7447`) ja namespacea `local/…`. Relay, kartta ja skenaariot toimivat kuten fabricissa,
mutta heartbeatia ei lähetetä.

## Seuranta

- **Kartta:** <http://localhost:8080>. **Ohjauspaneeli:** `/control`: syötä yksittäinen jälki,
  käynnistä valmis skenaario tai vedä ja pudota tehtävä-CSV tai -JSON
  (`demo/scenarios/mass_raid.csv`, esimerkki osoitteessa `/example.csv`). Syötetyt
  jäljet kulkevat lähettimen kautta.
- **TAK:** WinTAK ottaa CoT:n vastaan UDP-portissa 4242, muut UDP-sovellukset portissa 6969 ja
  ATAK TCP:llä osoitteessa `<osoite>:8087`.
- **Relay:** `http://localhost:8088/status` ja `/streams`.
- **Pääte:** `python demo/tools/live_monitor.py`.

## Ennen demoa jaetussa fabricissa

- [ ] `netbird status`: Management ja Signal yhdistettyinä, nimipalvelimet käytettävissä.
- [ ] `goat doctor` menee läpi (tai `python demo/tools/verify_efdi.py`).
- [ ] `curl localhost:8088/status` → `"healthy": true`.
- [ ] TAKissa kutsutunnukset alkavat sanalla `EXERCISE`.
- [ ] Edge-AI-demo: `EDGE_COT_AFFIL=u`, jotta sen merkkejä ei näytetä varmistettuina vihollisina.
- [ ] Oikeilla varmenteilla demo julkaisee jaettuun fabriciin. Kartta (`:8080`) näkyy verkkoon,
      jotta muut voivat seurata sitä. `/inject` hyväksyy vain JSONin, joten verkkosivu ei voi
      syöttää jälkiä, mutta kuka tahansa verkossa voi. Aja demo luotetussa verkossa. Edge-AI:n
      rajapinta (`:8090`) julkaistaan vain tälle koneelle; aseta `EDGE_API_TOKEN`.
- [ ] Video: `GATEWAY_VIDEO_HOST` on TAKin videomerkkien osoite. Käynnistin asettaa arvon
      `127.0.0.1` (tämän koneen TAK-sovellukset); puhelimia varten aseta ensin lähiverkon osoite.
- [ ] Lopuksi `.\demo\run-backbone-demo.ps1 -Stop`, jotta simuloitua dataa ei jää virtaamaan.
