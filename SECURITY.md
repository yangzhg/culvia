# Security Policy

Culvia is local-first software for private photo workflows. Please report security and privacy-sensitive issues carefully and avoid posting secrets or private photo paths in public issues.

## Supported Versions

Culvia is currently an early-stage alpha project. Security fixes target the latest commit on the default branch and the latest published release, when releases are available.

## Reporting A Vulnerability

If the issue can expose credentials, private photo paths, local files, SQLite data, generated thumbnails, exports, or other private information, do not open a public GitHub issue with the sensitive details.

Open a minimal public issue that says a private security report is needed, or contact the maintainers through the repository owner channel. Include:

- A short summary of the risk.
- Affected version, commit, or release artifact.
- Reproduction steps using generic paths and test data.
- Impact scope: local-only, network, desktop packaging, credential storage, export, or external vision review.
- Any logs with API keys, tokens, absolute private paths, and personal image metadata removed.

## Privacy Expectations

- API keys must not be committed to Git, written to logs, stored in SQLite plaintext fields, or included in screenshots.
- Photo source paths and export destinations should be treated as private user data.
- Raw shoots, uploads, generated thumbnails, SQLite databases, model downloads, exports, and local logs should not be attached to issues or pull requests.
- External vision review is explicit opt-in. Local scoring paths should not upload photos by default.

## Release Integrity

When desktop release assets are available, download them only from the project GitHub Releases page. Compare the published checksum before running a package. Release assets may also include GitHub Artifact Attestations that can be verified with:

```bash
gh attestation verify <downloaded-asset> --repo yangzhg/culvia
```
