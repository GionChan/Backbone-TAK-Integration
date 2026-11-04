# Julkaiseminen

**In English:** [../en/release.md](../en/release.md)

Julkaisu on yksi git-tagi. `.github/workflows/release.yml` hoitaa loput.

## Mitä julkaisu tuottaa

| Tuote | Missä | Sisältö |
| --- | --- | --- |
| Docker-image | `ghcr.io/<omistaja>/efdi-tak-relay:X.Y.Z`, `:X.Y`, `:latest` | Relay `linux/amd64`- ja `linux/arm64`-alustoille, mukana SBOM ja provenance |
| Kenttäpaketin pohja | GitHub Release: `efdi-tak-relay-X.Y.Z-windows-x64.zip` | Asennin, relay ja Python. **Ei varmennetta, slotia eikä laitteen nimeä** |
| Tarkisteet | GitHub Release: `SHA256SUMS` | ZIPin SHA256-tarkiste |

Pohjan voi jakaa turvallisesti: `install.cmd` kysyy EFDI-varmennepaketin (kansio, `.zip` tai
`.tar.gz`; se ehdottaa Lataukset-kansion `efdi-onboarding*`-tiedostoa) ja laitteen nimen.
Yksityisen repon uusi GHCR-paketti on yksityinen. Sen voi muuttaa julkiseksi paketin
asetuksista, kun halutaan.

## Vaiheet

1. Aseta versio tiedostoon `relay/tak_gateway.py` (`__version__`) ja `docker-compose.yml`
   (`image: efdi-tak-relay:X.Y.Z`), ja kirjaa muutokset `CHANGELOG.md`-tiedoston alkuun otsikon
   `## X.Y.Z — <päivämäärä>` alle.
2. Komennon `python tools/check_release.py` pitää tulostaa `versions agree`.
3. Yhdistä `main`iin, tee tagi ja pushaa se:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

Työnkulku pysähtyy ennen kuin mitään julkaistaan, jos tagi, `__version__`, CHANGELOGin uusin
luku ja composen image-tagi eivät täsmää.

## Mitä tarkistetaan ennen julkaisua

1. Versiot täsmäävät (`tools/check_release.py`).
2. Image rakentuu amd64- ja arm64-alustoille, ja kummallakin käynnistyvät Python kaikkine
   riippuvuuksineen, MediaMTX ja `doctor.py` (arm64 QEMU:lla).
3. Pohjassa ei ole `.pem`-, `.key`-, `.p12`- eikä `.cbor`-tiedostoja eikä slotia, laitteen nimeä
   tai TAK Server -asetuksia.
4. Täsmälleen julkaistava ZIP asennetaan Windowsiin niin, että jokainen Python on piilotettu
   `PATH`-polusta: varmenne `.zip`-tiedostosta, laitteen nimi kirjoitetaan, relay käy paketin
   omalla Pythonilla ja poistetaan lopuksi.

Image ja GitHub Release julkaistaan vasta, kun kaikki neljä tarkistusta ovat menneet läpi, joten
epäonnistunut tarkistus ei jätä mitään julkaistuksi. Puskut `feature/**`-haaroihin ajavat kaiken
tämän kuivaharjoituksena julkaisematta mitään.

## Laitekohtaiset paketit

Paketteja, joissa varmenne on mukana (`make_relay_package.py --system <nimi>`), ei julkaista
koskaan, koska niissä on yksityinen avain. Tee ne paikallisesti ja luovuta kuin salaisuus.
