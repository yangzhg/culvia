# 模型供应链安全

英文版：[../../en/developer/model-supply-chain.md](../../en/developer/model-supply-chain.md)

Culvia 从 Hugging Face 下载本地评分模型。仅有仓库名或可移动分支不足以证明可执行或序列化模型数据的来源，因此运行时下载固定到不可变的完整 commit revision，并在加载前校验大体积权重文件。

## 可信制品

以下值于 2026-09-04 通过启用 blob 元数据的 Hugging Face 模型 API 核验：

| 运行时 | 仓库 | 固定 revision | 权重文件 | SHA-256 | 大小 |
| --- | --- | --- | --- | --- | ---: |
| 核心审美评分 | `rsinema/aesthetic-scorer` | `2e93f809b484701a79ecc046ae2057c9084e1d38` | `model.pt` | `59853d88e95c287d101bd692c876232f5cd4a860299060d370258ad68b36042d` | 349,912,662 字节 |
| CLIP 参考评分 | `openai/clip-vit-base-patch32` | `eaee4c876b93e66f7fac584b529025a96d71ad66` | `model.safetensors` | `99d28a652e6ec46629ab7047a0ac82c69b1fe11e0ce672c43af65d3a9a3fc05d` | 605,157,884 字节 |

证据来源：

- [固定审美模型 API 响应](https://huggingface.co/api/models/rsinema/aesthetic-scorer/revision/2e93f809b484701a79ecc046ae2057c9084e1d38?blobs=true)
- [固定 CLIP 模型 API 响应](https://huggingface.co/api/models/openai/clip-vit-base-patch32/revision/eaee4c876b93e66f7fac584b529025a96d71ad66?blobs=true)
- [已验证的 CLIP safetensors 转换 commit](https://huggingface.co/openai/clip-vit-base-patch32/commit/eaee4c876b93e66f7fac584b529025a96d71ad66)
- [固定 CLIP 仓库文件树](https://huggingface.co/openai/clip-vit-base-patch32/tree/eaee4c876b93e66f7fac584b529025a96d71ad66)

审查时，CLIP 仓库的 `main` 解析为 `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`，其中没有 safetensors。Culvia 有意固定到同一官方仓库内已验证的转换 commit；该 commit 以 `3d74acf...` 为 parent，只新增 safetensors 制品及其 LFS 规则，并保留 parent 的配置与 tokenizer blob。除非上游分支发生变化并重新完成审查，否则不能把这个安全权重描述成来自 `main`。

## 运行时策略

- 每次 Hugging Face 下载都会传入对应的完整 commit revision；缓存发现也只接受该 revision 的 snapshot。
- 核心 `model.pt` 在复用缓存前校验 SHA-256，分段下载完成后也会先校验再原子发布。分段文件不匹配时会被丢弃并安全失败。
- CLIP safetensors 在下载后以及调用 `CLIPModel.from_pretrained(..., use_safetensors=True)` 前校验 SHA-256。缓存权重不匹配时会从固定 revision 强制重新下载；再次不匹配则安全失败。
- 核心 loader 只打开一次 `model.pt`：先通过该文件句柄计算摘要，再把同一句柄 seek 回起点并交给 `torch.load(..., weights_only=True)`。加载前、摘要完成后和加载完成后都会检查文件元数据。摘要或 fingerprint 不匹配、运行时不支持或任何加载错误都会以稳定的本地化错误安全失败。
- 完整校验成功后，会在 Culvia 模型缓存下原子写入轻量 marker。marker 文件名使用模型绝对路径的 SHA-256，内容绑定 schema 版本、revision、预期摘要、文件名、大小、纳秒级修改/变更时间和 inode。状态读取只查询元数据、内存和 marker，绝不对 350–605 MB 权重做同步哈希；fingerprint 变化后会立即回到 `not_checked` 和未就绪，等待后台准备流程重新校验。marker 写入失败不会放宽加载，只会让下一个进程重新校验。
- Windows、Linux 和 Apple Silicon macOS 要求 `torch>=2.10`、`torchvision>=0.25`、`transformers>=4.38,<5` 和 `safetensors>=0.4.3`。macOS Intel 显式选择最后一组兼容二进制：NumPy 1.x、Torch 2.2.2、torchvision 0.17.2、Transformers 4.38.2 和 safetensors 0.4.3。Desktop Lite 把 `torch` 与 `safetensors` 都列为必需运行模块。
- 发布 workflow 在全新 wheel 安装后实际 import 模型栈，并检查 `torch.load` 暴露 `weights_only`。真实 macOS Intel Full 包 runner 还会检查精确依赖版本、NumPy ABI 范围，以及本地 CLIP config/safetensors 保存和加载回环。

这遵循 Hugging Face 关于[使用完整 commit 固定下载版本](https://huggingface.co/docs/huggingface_hub/main/en/guides/download#from-specific-version)和[优先使用 safetensors](https://huggingface.co/docs/transformers/models)的说明。PyTorch 也明确警告[不要加载不可信来源的数据](https://docs.pytorch.org/docs/stable/generated/torch.load.html)，并说明了 `weights_only=True` 对反序列化能力的限制。

## 核验结果

2026-09-04 的核验从两个精确 revision URL 下载权重，并在本地重新计算 SHA-256。在项目 Python 环境中：

- 核心制品通过 `weights_only=True` 加载为含 213 个 state 条目的 `OrderedDict`，并严格装入 Culvia 的 87,461,383 参数评分器；
- 固定的 CLIP safetensors 与该仓库固定 `pytorch_model.bin` 的 400 个 key 及 tensor 值逐项完全一致，随后通过 `CLIPProcessor` 和 `CLIPModel` 以 `use_safetensors=True` 成功加载，得到预期的 151,277,313 参数 float32 模型。

精确的 Intel 兼容依赖组合也真实加载了两个已审查制品：核心 state dict 在选择 Transformers 4.x 内层 vision backbone 后严格加载成功，CLIP safetensors 对一组提示词生成了 `(2, 512)` 文本特征 tensor。

这些检查只证明固定字节的兼容性，不能自动把未来的上游文件视为可信。Torch 最低能力以 [`v2.2.0` 的 `torch.load` 签名](https://github.com/pytorch/pytorch/blob/v2.2.0/torch/serialization.py)为依据，其中已经包含显式 `weights_only` 参数。

现代平台从 Torch 2.10 起步，这是 [GHSA-63cw-57p8-fm3p](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p)列出的修复版本。macOS Intel 保持在 2.2.2，因为[官方 CPU wheel 索引](https://download.pytorch.org/whl/cpu/torch/)中的 CPython 3.11 macOS x86_64 包止于该版本。2026-09-04 针对 `macosx_10_13_x86_64` 的 pip 跨平台 dry run 解析出上述精确 Intel 组合，同版本也完成了本地 CLIP config/safetensors 回环；GitHub `macos-15-intel` runner 是最终二进制验证依据。

在 Intel 上，核心制品的安全边界建立在固定、已审查的 revision 与摘要以及同一文件句柄校验加载之上，而不是把 `weights_only` 当作唯一信任判断。该边界防止远端内容移动、缓存替换以及校验和加载之间的路径重命名；它不声称防御已经以同一 OS 用户身份运行、并且能在保留全部受检元数据的同时原地修改已打开文件的攻击者。后续经过审查的核心模型 revision 应发布 safetensors，让 Culvia 从这条路径中移除 Torch 序列化格式。

## 更新固定版本

模型 revision 更新属于安全敏感的依赖变更：

1. 把候选上游 revision 解析为完整 commit，并通过 `blobs=true` 获取文件元数据。
2. 审查仓库文件树、模型卡、许可证、权重格式和上游安全扫描；存在经过核验且兼容的制品时优先使用 safetensors。
3. 下载精确候选字节，在本地重新计算 SHA-256，并执行真实加载和代表性评分烟测。
4. 同时更新 revision、摘要、canonical result-version 契约、测试和本文档；不能只改 revision 或只改摘要。
5. 验证旧结果版本会被识别为 stale、只补算已选择的 capability，并且成功 checkpoint 会把新结果版本与分数字段一起保存。

结果版本按 capability 独立生成，由精确模型身份、revision、权重摘要和评分契约共同决定。CLIP 契约会直接
纳入真实 prompt pairs，因此修改提示词会自动改变对应结果版本。即使模型字节未变，只要预处理、输出映射、
校准或分值尺度会影响结果语义，也必须同步更新评分契约。

模型分析图的缓存 key 由同一份输入契约派生，包含尺寸边界、JPEG 质量、色彩模式和缓存 profile。
因此预处理改变后，不会拿旧的缓存 JPEG 生成新版本评分。
