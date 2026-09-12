# Release and marketplace checklist

Use this checklist from a clean `main` checkout. The manifest, firmware, tag,
release title, and artifact names use the same semantic version.

## Validate

```bash
./tools/validate-plugin.sh
./tools/lint-plugin.sh
python3 -m unittest discover -s desktop/tests
```

Also test click, Escape, shell open and close, disable, re-enable, shell
restart, uninstall, and reinstall on Omarchy 4.0 or newer. On hardware, test a
fresh flash and an upgrade of an already-paired watch. The upgrade must retain
the bond, owner identity, settings, and cached profile.

## Build the firmware bundle

Activate ESP-IDF 5.5.x, then run:

```bash
./tools/package-release.sh
(cd dist && sha256sum -c omarchy-watch-v0.5.2-flash.tar.gz.sha256)
```

The packaging command creates the archive checksum alongside the archive.
Extract the archive, run `sha256sum -c SHA256SUMS`, and flash one fresh and one
paired watch with its `flash.sh` helper.

Do not publish a merged binary as the routine upgrade image. A merged image
writes `0xFF` across the NVS partition and resets pairing. If a merged image is
ever offered for recovery, name it `factory-reset.bin` and label that behavior
prominently.

## Tag and publish

Commit and push every release change before building final artifacts. Create
an annotated `v0.5.2` tag on that exact commit and push the tag. The release
workflow rebuilds the firmware with ESP-IDF 5.5.5, verifies the archive, and
creates a draft GitHub release using `.github/release-notes/v0.5.2.md`. Review
the draft and its attached archive and checksum before publishing it.

```bash
git push origin main
git tag -a v0.5.2 -m "Omarchy Watch v0.5.2"
git push origin v0.5.2
```

Keep `main` unchanged while the marketplace submission is under review. The
marketplace records and verifies an exact commit; a later upstream commit will
appear as an unverified update until it completes the update workflow.

## Marketplace submission

Use the public repository root URL and request a manual-setup listing:

- Category: `Hardware`
- Tags: `ai`, `bar`
- Suggested missing tag: none
- Maintainer note: `omarchy plugin add` alone cannot produce a functioning
  installation because the watch requires the bundled user systemd bridge,
  control command, and Bluetooth setup. The README installer and uninstaller
  are the supported setup path.

Show the completed submission issue to the repository owner and confirm every
marketplace checklist statement before creating it.
