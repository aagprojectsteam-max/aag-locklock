# Publication verification — v2.0.0-beta.4

LockLock 2.0.0-beta.4 was published from the sanitized public repository on
2026-09-21. The private development/forensic Git history was not pushed.

## Identity

- repository: `aagprojectsteam-max/aag-locklock`
- release tag: `v2.0.0-beta.4`
- tag commit: `5ea9f45c0aba62dc90748fbf34e7139176babab2`
- tag object: `21f31c0b5774ca3edd3ed0d27fc7fb1d30463503`
- release state: published prerelease

## GitHub validation

- final pre-tag main CI: PASS
- tag CI run `35650352445`: PASS
- Release workflow run `35650352576`: PASS
- post-release workflow-portability CI run `35650659670`: PASS
- Linux job, package job, shellcheck and publication privacy scan: PASS
- shared matrix on Ubuntu and Windows / Python 3.11, 3.13 and 3.14: PASS
- Windows native named-pipe/ABI tests: PASS
- unsigned Windows executable build: PASS

## Release assets

- `aag_locklock-2.0.0b4-py3-none-any.whl`
  - SHA256: `49772e8f186d73c70fa70b5b110ec5a5e8e7095b0ecf38b218723d4b1079fe08`
  - size: 105423 bytes
- `aag_locklock-2.0.0b4.tar.gz`
  - SHA256: `29d79a881f4f0f157db1e3c662eb9aecf17d20d4e8a2bb729d4ebcc5b97751cd`
  - size: 2392646 bytes
- `SHA256SUMS`
- `release-manifest.json`

The four assets were downloaded again from the public GitHub Release.
`sha256sum -c SHA256SUMS` passed, and the JSON manifest was parsed and checked
against the downloaded wheel/sdist sizes and SHA256 values.

## Publication correction record

The first automatic Release attempt failed only because the workflow generated
an invalid shell continuation. No Release was created by that attempt. The tag
was recreated once on the corrected, fully CI-green commit before publication.

After successful publication, the metadata assets were normalized so
`SHA256SUMS` uses portable basename paths and `release-manifest.json` contains a
real trailing newline. The wheel and source archive were not replaced or
modified. The workflow on `main` was corrected so future releases generate both
metadata files correctly without manual normalization.

## Privacy boundary

The public repository starts from a sanitized source snapshot. Local machine
paths, user identity, hardware serials, private backups, forensic reports and
host-specific engineering/recovery evidence are excluded. A fail-closed
`tools/publication_scan.py` gate runs in CI and Release workflows.

## Post-publication MIT licensing

On 2026-09-22, AAG Projects Team adopted the MIT License for AAG LockLock.

- repository license detection: MIT
- source metadata: license = MIT
- package metadata: PEP 639 License-Expression: MIT
- future wheel builds include dist-info/licenses/LICENSE
- future source distributions include top-level LICENSE
- existing beta.4 tag remains unchanged
- original beta.4 wheel and source archive remain unchanged
- a standalone LICENSE asset was attached to the beta.4 Release
- Release SHA256SUMS and release-manifest.json were updated to include the standalone LICENSE asset

The final public-download verification passed for the original wheel, original
source archive and the standalone LICENSE asset.
