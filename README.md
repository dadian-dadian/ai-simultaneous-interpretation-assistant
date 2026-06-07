# AI 同声传译助手

AI 同声传译助手是一款面向 Windows 桌面端的实时翻译工具，适用于观看外语演讲、技术分享、国际会议、网课、直播或本地视频等场景。系统捕获电脑正在播放的单向音频流，通过实时语音识别、中文增量翻译和字幕稳定更新能力，将外语内容转换为中文字幕，并以悬浮窗形式展示，帮助用户降低语言门槛，跟上内容节奏。

## 演示视频

视频链接待补充。录制完成后，可以将演示视频链接放在这里，建议展示“开始转译、播放英文视频、悬浮字幕实时出现、窗口拖动缩放、停止后回看记录”这条完整链路。

## 项目定位

本项目不是简单的“音频转文字 + 逐句翻译”工具，而是一个面向真实桌面观看场景的 AI 同声传译助手。核心目标是通过系统音频捕获、低延迟流式字幕、中文增量翻译、稳定字幕展示和会话记录回看，在流畅度与准确度之间取得可用体验。

## 核心功能

- 系统音频捕获：基于 Windows WASAPI Loopback 捕获当前播放设备输出的声音。
- 实时语音识别：将连续外语音频流转换为原文文本。
- 中文增量翻译：对实时英文结果进行持续翻译，让中文先快速跟随，再随稳定结果更新。
- 悬浮字幕展示：中文优先显示，英文固定在底部作为参考，支持拖动、缩放、字号和透明度调整。
- 会话记录回看：按“开始到停止”持久化中英文记录，支持异常中断恢复。
- 运行稳定性：对实时 ASR WebSocket 断开、主动暂停、停止和异常关闭做了恢复与抑制处理。
- 产品化界面：主窗口提供浅色控制面板、当前/历史记录切换和更自然的产品提示文案。

## 使用场景

- 观看英文技术演讲或公开课。
- 参加国际线上会议。
- 浏览外语直播、播客或课程视频。
- 播放本地外语视频文件。

## 技术路线

MVP 阶段优先使用 Python 快速验证核心链路：

- 桌面界面：PySide6 Widgets
- 系统声音采集：Windows WASAPI Loopback
- 音频处理：独立采集线程、有界音频队列、环形缓冲、Silero VAD 分段和滑动窗口缓存
- 语音识别：mock ASR 与百度智能云实时语音识别 WebSocket 适配器
- 中文翻译：百度翻译 `baidu-mt` 增量翻译适配器
- 字幕展示：中文块稳定保留，最新译文持续更新，英文原文单行横向滚动
- 会话存储：本地 JSON 会话记录、后台合并写入和异常中断恢复
- 打包发布：PyInstaller

## 系统流程

```text
Windows 系统声音
  -> WASAPI Loopback 音频采集
  -> 音频切片 / 重采样 / VAD 分段
  -> AI 实时语音识别
  -> 原文实时字幕
  -> 中文增量翻译
  -> 悬浮字幕显示
  -> 会话记录持久化
```

## 字幕状态设计

系统为每个字幕段分配 `segment_id`，并维护字幕状态，确保实时预览、稳定结果和后续更新可以写回同一个字幕段，而不是简单追加新内容。当前已实现字幕事件模型和状态容器，支持 `segment.partial`、`segment.final`、`segment.update` 三类事件。

```text
partial：实时字幕，优先保证低延迟
final：稳定字幕，表示当前语音段已确认
updated：更新字幕，表示同一字幕段被更完整的结果替换
```

状态管理规则：

- `partial` 可以新增或更新实时字幕。
- `final` 会确认当前字幕段，并保留为稳定结果。
- `update` 必须命中已有 `segment_id`，并回写原字幕段。
- 已确认或已更新的字幕不会被迟到的实时字幕覆盖。

示例：

```text
初始字幕：
我们先回顾本季度的工作进展。

后续上下文：
We will begin with the progress from this quarter.

更新后：
首先，我们回顾本季度的工作进展。
```

## 目录结构

```text
app/
  audio/          Windows 系统音频捕获与音频处理
  asr/            语音识别适配器
  translate/      翻译适配器
  core/           字幕事件、配置、中文展示和会话模型
  storage/        转译记录本地持久化
  ui/             主控制窗口和悬浮字幕窗口
docs/
  方案设计.md
  PR计划.md
tests/
```

## 当前状态

项目已具备可演示的桌面主流程：配置百度实时 ASR 和百度翻译后，主窗口可以监听系统音频，将英文识别结果实时送入中文增量翻译，并在悬浮字幕窗中优先展示中文字幕，英文原文固定在底部作为参考。一次开始到停止之间的中英文记录会持久化到本地，主窗口支持在“当前”和“历史”之间切换并回看已完成会话。

当前仍处于 MVP 阶段，重点验证实时字幕体验、长时间运行稳定性和桌面 UI 交互；后续可继续优化翻译质量、更多语言和打包发布体验。

## 依赖说明

当前阶段引入以下依赖：

- PySide6：用于构建 Windows 桌面主控制窗口和悬浮字幕窗口。
- soundcard：用于在 Windows 上枚举系统播放设备，并通过 loopback 捕获系统输出音频。
- numpy：由音频采集链路使用，用于保存和处理音频采样数据。
- ONNX Runtime：用于运行 Silero VAD ONNX 模型，进行语音活动检测。
- websocket-client：用于连接百度智能云实时语音识别 WebSocket API。
- python-dotenv：用于从本地 `.env` 文件加载运行配置和密钥。

开发依赖：

- ruff：用于检查 Python 代码风格、导入顺序和常见静态问题，不参与运行时功能。

项目内置 `assets/models/silero_vad.onnx`，来源为 Silero VAD 官方仓库。当前 VAD 路线只使用 ONNX Runtime，不引入 PyTorch / torchaudio。

ASR 真实服务通过 `websocket-client` 调用百度智能云实时语音识别 WebSocket API。适配器会发送 `START` 控制帧、16k 单声道 PCM 二进制音频帧和 `FINISH` 控制帧，并解析 `MID_TEXT` 实时结果与 `FIN_TEXT` 最终结果。中文翻译通过百度翻译 `baidu-mt` 适配器完成；mock ASR 与内置演示用于没有 API Key 时验证界面和字幕链路。

依赖版本通过 `pyproject.toml` 和 `uv.lock` 管理，确保后续评审时可以复现相同环境。后续每次新增第三方库或框架时，将同步更新 README，说明依赖用途和原创功能边界。

## 运行方式

当前版本提供桌面主窗口、悬浮字幕窗和命令行验证入口。

### 环境要求

- Windows 10 / Windows 11
- Python 3.11 或更高版本
- uv

### 安装依赖

```powershell
uv sync
```

### 配置本地环境变量

项目启动时会自动读取仓库根目录下的 `.env` 文件。`.env` 已被 `.gitignore` 忽略，真实密钥不应提交到仓库。

仓库提供 `.env.example` 作为模板。百度实时 ASR 与百度翻译的关键配置如下：

```dotenv
ASR_PROVIDER=baidu-realtime
ASR_APP_ID=你的百度 AppID
ASR_API_KEY=你的百度 AppKey
ASR_BAIDU_WS_URL=wss://vop.baidu.com/realtime_asr
ASR_BAIDU_DEV_PID=auto

PARTIAL_TRANSLATION_PROVIDER=baidu-mt
PARTIAL_TRANSLATION_APP_ID=你的百度翻译 AppID
PARTIAL_TRANSLATION_API_KEY=你的百度翻译 API Key
PARTIAL_TRANSLATION_SECRET_KEY=你的百度翻译 Secret Key
```

转译记录默认保存在当前用户的本地应用数据目录。需要指定其他位置时，可设置
`TRANSCRIPT_STORAGE_DIR`；主窗口右侧可在“当前”和“历史”之间切换并回看已完成会话。

### 启动主控制窗口

```powershell
uv run python -m app
```

当前主窗口提供开始、暂停、停止、状态展示、音频源、转译模式、字幕样式和转译记录等界面。配置百度实时 ASR 与百度翻译后，点击“开始转译”会启动系统音频监听、Silero VAD 分段、百度 WebSocket 流式识别和中文增量翻译；点击“显示字幕窗”可以显示置顶悬浮字幕窗口，并支持拖动、自由缩放、调整字号、透明度和显示模式。未配置真实 ASR 时，可将 `ASR_PROVIDER` 设为 `mock` 使用内置演示模式。

### 演示模式

当前版本内置一段英文会议场景字幕脚本，用于在未接入音频和 AI 服务前验证核心体验：

- 实时字幕逐步出现。
- 稳定字幕进入转译记录。
- 同一会话在停止后可以从历史记录中回看。

### 查看配置

```powershell
uv run python -m app --show-config
```

### 查看系统音频设备

```powershell
uv run python -m app --list-audio-devices
```

### 录制系统音频测试文件

播放一段视频、会议或音乐后执行：

```powershell
uv run python -m app --record-system-audio artifacts/audio/system_capture.wav --record-duration 3
```

命令会通过 Windows loopback 捕获当前默认播放设备输出，并保存为 wav 文件。该能力用于验证系统音频链路，后续 ASR 模块会消费同一类音频数据。

### 预览 Silero VAD 分段

播放一段包含人声的系统音频后执行：

```powershell
uv run python -m app --preview-vad-stream --stream-duration 5
```

命令会持续捕获系统音频流，并通过 ONNX Runtime + Silero VAD 输出 `speech_start` / `speech_end` 分段事件。

### 识别本地音频文件

可以先录制系统音频，再使用 mock ASR 验证识别入口：

```powershell
uv run python -m app --transcribe-audio artifacts/audio/system_capture.wav --asr-provider mock
```

mock 模式不会调用外部服务，会输出固定英文识别文本，用于验证“音频文件 -> ASR 结果”的程序链路。

如需调用真实 ASR 服务，可配置百度智能云实时语音识别 WebSocket 接口：

```powershell
$env:ASR_PROVIDER="baidu-realtime"
$env:ASR_APP_ID="你的百度 AppID"
$env:ASR_API_KEY="你的百度 AppKey"
uv run python -m app --transcribe-audio artifacts/audio/system_capture.wav
```

可选参数：

- `ASR_BAIDU_WS_URL`：默认 `wss://vop.baidu.com/realtime_asr`。
- `ASR_BAIDU_DEV_PID`：默认 `auto`。当识别语言是 `en` 时自动使用英语实时模型 `17372`，中文默认使用普通话实时模型 `15372`。
- `ASR_BAIDU_CUID`：默认 `ai_interpreter_windows`，用于标识本机客户端。
- `ASR_TIMEOUT_SECONDS`：默认 `30`。
- `--asr-language en`：指定识别语言，默认读取 `SOURCE_LANGUAGE`。
- `--asr-prompt "technical conference"`：预留给支持提示词的 ASR 适配器，当前百度云适配器不使用该参数。

### 预览系统音频 ASR 分段

播放一段包含英文人声的视频后执行：

```powershell
uv run python -m app --preview-asr-stream --stream-duration 10 --chunk-duration 0.16 --asr-provider mock
```

命令会通过独立采集线程捕获系统音频，并使用有界队列把最新音频块交给 VAD/ASR 消费，避免识别处理阻塞录音线程。Silero VAD 判断语音开始和结束后，百度实时 ASR WebSocket 会在 `speech_start` 后立即建立会话，并随着系统音频持续发送 160ms PCM 音频帧；收到 `MID_TEXT` 时输出临时结果，在 `speech_end` 后发送 `FINISH` 并输出 `FIN_TEXT` 最终识别结果。mock 模式适合验证基础链路；配置百度实时 ASR WebSocket 后，可用同一命令测试实际识别效果。

### 启动无 UI 骨架

```powershell
uv run python -m app --no-ui
```

### 运行测试

```powershell
uv run python -m unittest discover -s tests
```

### 运行代码检查

```powershell
uv run ruff check app tests
```

## 开发规范

- 所有文档使用中文编写。
- 每个 PR 只实现或修改一个独立功能。
- PR 描述必须包含功能描述、实现思路和测试方式。
- 主分支代码在每次 PR 合并后应保持可运行或可预览。
- 引入第三方库时必须在 README 中说明依赖用途。
- 复用历史代码时必须在 PR 描述中注明来源。

