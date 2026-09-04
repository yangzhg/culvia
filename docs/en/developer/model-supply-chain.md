# Model Supply-Chain Security

Simplified Chinese: [../../zh-CN/developer/model-supply-chain.md](../../zh-CN/developer/model-supply-chain.md)

Culvia downloads local scoring models from Hugging Face. A repository name or a moving branch is not sufficient provenance for executable or serialized model data, so runtime downloads use immutable full commit revisions and verify the large weight artifacts before loading them.

## Trusted Artifacts

The following values were verified on 2026-09-04 against the Hugging Face model API with blob metadata enabled:

| Runtime | Repository | Pinned revision | Weight file | SHA-256 | Size |
| --- | --- | --- | --- | --- | ---: |
| Core aesthetic scorer | `rsinema/aesthetic-scorer` | `2e93f809b484701a79ecc046ae2057c9084e1d38` | `model.pt` | `59853d88e95c287d101bd692c876232f5cd4a860299060d370258ad68b36042d` | 349,912,662 bytes |
| CLIP reference | `openai/clip-vit-base-patch32` | `eaee4c876b93e66f7fac584b529025a96d71ad66` | `model.safetensors` | `99d28a652e6ec46629ab7047a0ac82c69b1fe11e0ce672c43af65d3a9a3fc05d` | 605,157,884 bytes |

Evidence sources:

- [Pinned aesthetic model API response](https://huggingface.co/api/models/rsinema/aesthetic-scorer/revision/2e93f809b484701a79ecc046ae2057c9084e1d38?blobs=true)
- [Pinned CLIP model API response](https://huggingface.co/api/models/openai/clip-vit-base-patch32/revision/eaee4c876b93e66f7fac584b529025a96d71ad66?blobs=true)
- [Verified CLIP safetensors conversion commit](https://huggingface.co/openai/clip-vit-base-patch32/commit/eaee4c876b93e66f7fac584b529025a96d71ad66)
- [Pinned CLIP repository tree](https://huggingface.co/openai/clip-vit-base-patch32/tree/eaee4c876b93e66f7fac584b529025a96d71ad66)

The CLIP repository's `main` revision resolved to `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268` during the audit and did not contain safetensors. Culvia deliberately pins the separate verified conversion commit in the same official repository. That commit has `3d74acf...` as its parent, adds only the safetensors artifact and its LFS rule, and preserves the parent's configuration/tokenizer blobs. It must not be described as a file from `main` unless the upstream branch changes and is audited again.

## Runtime Policy

- Every Hugging Face download passes the corresponding full commit revision. Cache discovery only accepts that revision's snapshot.
- The core `model.pt` SHA-256 is checked before a cached file is reused and before a completed partial download is atomically promoted. A mismatched partial file is discarded and fails closed.
- The CLIP safetensors SHA-256 is checked after download and immediately before `CLIPModel.from_pretrained(..., use_safetensors=True)`. A mismatched cached weight is force-downloaded again from the pinned revision; a second mismatch fails closed.
- The core loader opens `model.pt` once, hashes that file handle, seeks the same handle back to the start, and passes it to `torch.load(..., weights_only=True)`. File metadata is checked before hashing, after hashing, and after loading. A digest or fingerprint mismatch, an unsupported runtime, or any load error fails closed with a stable localized error.
- Successful full verification writes an atomic lightweight marker under the Culvia model cache. The marker filename hashes the absolute model path, and its contents bind the schema version, revision, expected digest, filename, size, nanosecond modification/change times, and inode. State reads use only metadata, memory, and this marker; they never hash the 350–605 MB weights. A changed fingerprint becomes `not_checked` and not ready until background preparation verifies it again. Marker write failure never weakens loading and only makes the next process verify again.
- On Windows, Linux, and Apple Silicon macOS, the package requires `torch>=2.10`, `torchvision>=0.25`, `transformers>=4.38,<5`, and `safetensors>=0.4.3`. macOS Intel selects the last compatible binary set explicitly: NumPy 1.x, Torch 2.2.2, torchvision 0.17.2, Transformers 4.38.2, and safetensors 0.4.3. Desktop Lite treats both `torch` and `safetensors` as required runtime modules.
- The release workflow imports the installed model stack and checks that `torch.load` exposes `weights_only` after a fresh wheel install. Its real macOS Intel full-package runner additionally checks the exact dependency versions, NumPy ABI range, and a local CLIP config/safetensors save-load round trip.

This follows Hugging Face's guidance to [download a specific full commit revision](https://huggingface.co/docs/huggingface_hub/main/en/guides/download#from-specific-version) and prefer [safetensors over pickle-based weights](https://huggingface.co/docs/transformers/models). PyTorch also warns to [never load data from an untrusted source](https://docs.pytorch.org/docs/stable/generated/torch.load.html) and documents how `weights_only=True` restricts the unpickler.

## Qualification Evidence

The 2026-09-04 qualification downloaded both weight files from their exact revision URLs and recomputed their SHA-256 values locally. In the project Python environment:

- the core artifact loaded with `weights_only=True` as an `OrderedDict` containing 213 state entries and loaded strictly into Culvia's 87,461,383-parameter scorer;
- the pinned CLIP safetensors had the same 400 keys and byte-exact tensor values as the pinned repository's `pytorch_model.bin`, then loaded through `CLIPProcessor` and `CLIPModel` with `use_safetensors=True`, producing the expected 151,277,313-parameter float32 model.

The exact Intel-compatible dependency set also loaded both audited artifacts: the core state dict loaded strictly after selecting the Transformers 4.x inner vision backbone, and the CLIP safetensors produced a `(2, 512)` text-feature tensor for a prompt pair.

These checks establish compatibility for the pinned bytes; they are not permission to trust later upstream bytes automatically. The minimum Torch capability is backed by the [`v2.2.0` `torch.load` signature](https://github.com/pytorch/pytorch/blob/v2.2.0/torch/serialization.py), which includes the explicit `weights_only` argument.

Modern platforms start at Torch 2.10, the patched version named by [GHSA-63cw-57p8-fm3p](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p). macOS Intel remains on 2.2.2 because the [official CPU wheel index](https://download.pytorch.org/whl/cpu/torch/) ends its CPython 3.11 macOS x86_64 packages there. A 2026-09-04 pip cross-platform dry run for `macosx_10_13_x86_64` resolved the exact Intel set above, and the same versions completed a local CLIP config/safetensors round trip; the GitHub `macos-15-intel` runner is the authoritative binary check.

On Intel, the core-artifact boundary relies on the fixed audited revision and digest plus same-file-handle verification, rather than treating `weights_only` as the only trust decision. It protects against moving remote content, cache replacement, and a path rename between verification and loading. It does not claim to defend against an attacker already running as the same OS user who can mutate an open file in place while preserving all checked metadata. A future audited core-model revision should publish safetensors so Culvia can remove the remaining Torch serialization format from this path.

## Updating A Pin

Treat a model revision update as a security-sensitive dependency change:

1. Resolve the proposed upstream revision to a full commit and retrieve file metadata with `blobs=true`.
2. Review the repository tree, model card, license, weight format, and upstream security scan. Prefer safetensors when an audited compatible artifact exists.
3. Download the exact candidate bytes, recompute SHA-256 locally, and run a real load and representative scoring smoke test.
4. Update the revision, digest, tests, and this document together. Never change only the revision or only the digest.
