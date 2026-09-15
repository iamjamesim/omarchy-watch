# Release and marketplace checklist

Use this checklist to prepare a release, then publish from a clean `main`
checkout. The manifest, firmware, tag, release title, and artifact names use the
same semantic version.

## Prepare the release separately

Merge feature and fix PRs with their tests, feature documentation, and photos.
Keep the version fields at the latest published version during development;
describe new behavior as unreleased until the release-preparation PR.

After those changes land, open a separate `Prepare vX.Y.Z` PR that updates:

- `manifest.json`, `firmware/CMakeLists.txt`, and the firmware version constants
  in `firmware/main/watch_profile.h` to the same version.
- README release requirements and download artifact names.
- `.github/release-notes/vX.Y.Z.md` with the final release behavior and update
  steps. Write body copy only; the workflow uses the tag as the release title.

Protocol versions describe wire compatibility and belong with the feature
changes that introduce them; they are independent of the release version.

Finish QA and required checks before merging the preparation PR, then tag the
exact merged commit. Re-run affected checks if further fixes are needed.

## Validate

```bash
./tools/validate-plugin.sh
./tools/lint-plugin.sh
./tools/render-watchface.sh
ctest --test-dir simulator/build --output-on-failure
python3 -m unittest discover -s desktop/tests
```

Also test click, Escape, shell open and close, disable, re-enable, shell
restart, uninstall, and reinstall on Omarchy 4.0 or newer. On hardware, test a
fresh flash and an upgrade of an already-paired watch. The upgrade must retain
the bond, owner identity, settings, and cached profile.
Use [the hardware acceptance checks](agent-local-test.md#acceptance-checks)
for activity, allowance, and offline behavior. Record what was actually tested
in the release PR; the checklist itself is not evidence of a passed run.

## Build the firmware bundle

Activate ESP-IDF 5.5.x, then run:

```bash
./tools/package-release.sh
version=$(jq -r .version manifest.json)
(cd dist && sha256sum -c "omarchy-watch-v${version}-flash.tar.gz.sha256")
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
an annotated tag matching the manifest version on that exact commit and push it. The release
workflow rebuilds the firmware with ESP-IDF 5.5.5, verifies the archive, and
creates a draft GitHub release using the matching `.github/release-notes/vX.Y.Z.md`. Review
the draft and its attached archive and checksum before publishing it.

```bash
git push origin main
version=$(jq -r .version manifest.json)
git tag -a "v${version}" -m "Omarchy Watch v${version}"
git push origin "v${version}"
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
