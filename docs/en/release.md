# Releasing

**Suomeksi:** [../fi/release.md](../fi/release.md)

A release is one git tag. `.github/workflows/release.yml` does the rest.

## What a release publishes

| Artifact | Where | Contents |
| --- | --- | --- |
| Docker image | `ghcr.io/<owner>/efdi-tak-relay:X.Y.Z`, `:X.Y`, `:latest` | Relay for `linux/amd64` and `linux/arm64`, with SBOM and provenance |
| Field-package template, Windows | GitHub Release: `efdi-tak-relay-X.Y.Z-windows-x64.zip` | Installer, relay, bundled Python. **No certificate, no slot, no device name** |
| Field-package template, Linux | GitHub Release: `efdi-tak-relay-X.Y.Z-linux.tar.gz` | Installer, relay, wheels for x86_64 and aarch64. **No certificate, no slot, no device name** |
| Checksums | GitHub Release: `SHA256SUMS` | SHA256 of both templates |

The template is safe to share: `install.cmd` asks for the EFDI bundle (folder, `.zip` or
`.tar.gz`; it suggests an `efdi-onboarding*` file in Downloads) and the device name. A new GHCR
package of a private repository is private; make it public in the package settings when wanted.

## Steps

1. Set the version in `relay/tak_gateway.py` (`__version__`) and in `docker-compose.yml`
   (`image: efdi-tak-relay:X.Y.Z`), and put the changes under `## X.Y.Z — <date>` at the top of
   `CHANGELOG.md`.
2. `python tools/check_release.py` must print `versions agree`.
3. Merge to `main`, then tag and push:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

The workflow stops before publishing anything if the tag, `__version__`, the newest CHANGELOG
section or the compose image tag disagree.

## What is checked before publishing

1. Versions agree (`tools/check_release.py`).
2. The image builds for amd64 and arm64, and each architecture starts Python with every
   dependency, MediaMTX and `doctor.py` (arm64 under QEMU).
3. Neither template contains a `.pem`, `.key`, `.p12` or `.cbor` file and no slot, device name or
   TAK Server setting.
4. The exact template ZIP is installed on Windows with every Python hidden from `PATH`: bundle
   from a `.zip`, device name typed in, relay running on the bundled Python, uninstalled.
5. The exact Linux template is installed on Ubuntu with no package index reachable: bundle from a
   `.tar.gz`, device name typed in, relay running, uninstalled.

The image is built once into an OCI archive. Check 2 and the push both use that archive, so the
published image is the tested one. The image and the GitHub Release are published only after all
five checks have passed: a failed check leaves nothing published. Pushes to `feature/**` run all of
this as a dry run, without publishing.

## Per-device packages

Packages with the certificate inside (`make_relay_package.py --system <name>`) are never
published: they hold the private key. Build them locally and hand them over like a secret.
