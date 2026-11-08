# Kenttätesti

**In English:** [../en/field-test.md](../en/field-test.md)

Mitä CI ei voi testata: oikeat TAK-laitteet, kaksi relayta oikean fabricin yli ja
Linux-kenttälaite. Aja tämä harjoitusverkossa ennen kuin merkkien jakoa tai Linux-pakettia
käytetään operatiivisesti. Merkitse jokainen rivi ja kirjaa relayn versio (`/status`) sekä
TAK-sovellusten versiot.

## Kokoonpano

| | Relay A | Relay B |
| --- | --- | --- |
| Slot | Organisaatio 1 | Organisaatio 1 tai toinen (kohdat 8–9 vaativat toisen) |
| Asetukset | `TAK_SHARE_MARKERS=1`, `TAK_INGEST=1` | Oletukset |
| TAK-laite | ATAK tai WinTAK, yhdistetty relayhin A | ATAK tai WinTAK, yhdistetty relayhin B |

Merkit kulkevat myös saman organisaation kahden relayn välillä. Sijainnit eivät: relay ei näytä
oman slottinsa julkaisemia sijainteja, joten kohdat 8–9 vaativat relayn B toisessa slotissa.

Ennen aloitusta molemmissa: `python relay/doctor.py` (kenttäpaketissa `run.ps1 -CheckOnly` tai
`./run.sh --check-only`) ei näytä yhtään FAIL-riviä, ja `http://localhost:8088/` näyttää
**Healthy**.

## Merkit ja piirrokset (A → B)

| # | Laitteella A | Odotettu tulos laitteella B | Jos ei, katso relaysta A |
| --- | --- | --- | --- |
| 1 | Lisää vihollismerkki | Näkyy muutamassa sekunnissa | `/metrics`: `gateway_markers_published_total` kasvaa; muuten `gateway_ingest_dropped_total{reason=...}` |
| 2 | Siirrä merkkiä | Siirtyy uuteen paikkaan | Sama; `reason="relayed"` tarkoittaa, että A lähetti merkin takaisin omalle laitteelleen (raportoi) |
| 3 | Siirrä merkkiä kahdesti sekunnin sisällä | Päätyy viimeiseen paikkaan | `gateway_ingest_deferred_total` kasvaa |
| 4 | Piirrä viiva tai alue | Näkyy | Kuten kohta 1 |
| 5 | Poista merkki | Katoaa | `gateway_marker_deletes_published_total`; `reason="delete-unknown"` tai `"not-allowed"` |
| 6 | Lähetä GeoChat-viesti | **Ei** tule perille | `reason="chat"` kasvaa |
| 7 | Laitteen A oma merkki laitteella A | Näkyy **kerran**, ei kahdesti | `gateway_cot_dropped_total{reason="own-marker"}` kasvaa |

## Toiseen suuntaan (B → A)

| # | Tarkistus | Odotettu tulos |
| --- | --- | --- |
| 8 | Laite A näkee relayn B sijainnin (B:ssä `TAK_INGEST=1`) | Näkyy laitteella A |
| 9 | Laite A jakaa takaisin B:ltä saamansa merkin (esim. lähettää sen uudelleen) | Relay A ei julkaise sitä: `reason="relayed"` tai `"echo"` |

## Uudelleenkäynnistys (relay A)

| # | Vaihe | Odotettu tulos |
| --- | --- | --- |
| 10 | Käynnistä relay A uudelleen ja poista merkki, joka jaettiin ennen uudelleenkäynnistystä | Jää laitteelle B, kunnes se vanhenee (tunnettu rajoitus); kun merkkiä on muutettu kerran, poisto menee perille |

## Linux-kenttälaite

| # | Vaihe | Odotettu tulos |
| --- | --- | --- |
| 11 | `./install.sh --at-boot`, sitten uudelleenkäynnistys kirjautumatta | `http://localhost:8088/` vastaa |
| 12 | Verkon TAK-laite yhdistää TCP-porttiin 8087 | Saa backbonen tilannekuvan (avaa portti tarvittaessa palomuurissa) |
| 13 | `./uninstall.sh` | Relayn prosessia ei ole, portti 8088 on vapaa |

## Raportointi

Jokaisesta epäonnistuneesta rivistä: vaihe, mitä tapahtui, relayn A `/status` ja olennaiset
`/metrics`-rivit sekä TAK-sovellus ja sen versio.
