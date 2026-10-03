# 音乐大模型部署总览

> 部署日期: 2026-10-01 · 硬件: RTX 4080 16GB / 32GB 内存 / Windows 10
> 三个项目均已独立部署、测试通过，并配有 Web 页面与启停脚本。

## 一、三个项目一览

| # | 项目 | GitHub | 功能 | 页面地址 | 测试结果 |
|---|------|--------|------|---------|---------|
| 1 | **MusicGen** (audiocraft) | facebookresearch/audiocraft | 文本 → 5~30s 纯音乐 (32kHz) | http://127.0.0.1:7861 | 16/16 通过 |
| 2 | **AudioLDM 2** | haoheliu/audioldm2 | 文本 → 音乐/音效 (16kHz, 支持反向提示词) | http://127.0.0.1:7862 | 13/13 通过 |
| 3 | **DiffRhythm** | ASLP-lab/DiffRhythm | 歌词+风格 → 95s 带人声完整歌曲 (44.1kHz) | http://127.0.0.1:7863 | 11/11 通过 |

## 二、使用方法

每个项目文件夹里有一对脚本（双击即可）：

- **启动_xxx.bat** — 后台启动模型服务 → 自动等待就绪 → 自动打开浏览器页面
- **关闭_xxx.bat** — 按端口结束进程释放显存 → 打印当前显存占用

> 首次生成需等模型加载（MusicGen 约 1 分钟 / AudioLDM2 约 1-2 分钟 / DiffRhythm 约 1-2 分钟），
> 页面会有进度提示。生成过的音频保存在各项目 `outputs/` 文件夹。

## 三、测试资料（明天查看）

每个项目下的 **测试结果/** 文件夹包含：

```
测试报告.md        详细测试报告(部署说明/踩坑记录/用例表格/性能数据/已知限制)
test_results.json  自动化用例的原始结构化结果
test_run.log       测试运行完整日志
run_tests.py       可复跑的自动化测试脚本
页面截图.png       Web 页面实际渲染截图
samples/           测试生成的全部音频样例(WAV, 可直接试听)
```

## 四、文件夹结构

```
G:\xmgousi\音乐大模型\
├── audiocraft\      项目1 MusicGen (含 venv\ 独立环境)
├── audioldm2\       项目2 AudioLDM2 (含 venv\ 独立环境)
├── DiffRhythm\      项目3 DiffRhythm (含 venv\ 独立环境)
├── hf_cache\        模型权重共享缓存 (musicgen/audioldm2/xlm-roberta)
├── wheels\          torch 离线安装包 (含并行下载工具 pdl.sh)
├── logs\            三个服务的运行日志
└── 总览_README.md   本文件
```

## 五、关键部署经验（踩坑记录）

1. **网络**: GitHub 直连不通 → 用 `gh-proxy.com` 克隆；HuggingFace → `hf-mirror.com`；
   pip → 清华镜像；PyTorch CUDA 轮子 → curl 12 线程并行分段下载（`wheels/pdl.sh`）。
2. **torch 2.5.0 Windows bug**: `torch.load(weights_only=True)` 加载大 pickle 会无声崩溃
   (exit 1 无堆栈)。MusicGen 已转为 fp16 safetensors 绕开（`audiocraft/models/`，加载仅 2.8s）。
3. **muq 0.1.0 兼容性**: 与 huggingface_hub≥0.26 的 mixin 不兼容，`diffrhythm_app.py`
   中用加载垫片 `_patch_muq_loader()` 手动读缓存构造模型。
4. **eSpeak NG**: DiffRhythm 歌词音素化依赖，已装 1.52.0，启动脚本自动设置环境变量。
5. **bat 编码**: 中文 Windows 的 cmd 按 GBK 解析批处理，所有脚本以 GBK 编码保存。
6. **显存管理**: 模型惰性加载(首次生成时才进显存)；页面有「释放显存」按钮；
   关闭脚本杀进程即完全释放。DiffRhythm 峰值 13.15GB，不要与其它大模型同时跑。

## 六、当前状态

**所有服务已关闭，显存已完全释放**（约 0.9GB 为系统桌面占用基线）。
明天想用哪个项目，双击对应的 `启动_xxx.bat` 即可。
