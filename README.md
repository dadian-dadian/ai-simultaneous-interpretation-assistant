# AI 同声传译助手

AI 同声传译助手是一款面向 Windows 桌面端的实时翻译工具，适用于观看外语演讲、技术分享、国际会议、网课、直播或本地视频等场景。系统捕获电脑正在播放的单向音频流，通过 AI 语音识别、上下文翻译和字幕自动修正能力，将外语内容转换为中文字幕，并以悬浮窗形式展示，帮助用户降低语言门槛，跟上内容节奏。

## 项目定位

本项目不是简单的“音频转文字 + 逐句翻译”工具，而是一个面向真实桌面观看场景的 AI 同声传译助手。核心目标是通过系统音频捕获、低延迟流式字幕、上下文翻译、术语一致性和历史字幕回写修正机制，在流畅度与准确度之间取得可用体验。

## 核心功能

- 系统音频捕获：基于 Windows WASAPI Loopback 捕获当前播放设备输出的声音。
- 实时语音识别：将连续外语音频流转换为原文文本。
- 上下文翻译：结合最近几句上下文生成自然流畅的中文表达。
- 字幕流式展示：使用临时字幕和正式字幕兼顾速度与准确性。
- 历史字幕修正：根据后续语义自动修正之前的识别或翻译结果。
- 术语一致性：针对技术分享、会议和网课等场景维护专业词汇翻译。
- 悬浮字幕窗口：支持置顶、拖动、透明度、字号、双语显示和暂停翻译。

## 使用场景

- 观看英文技术演讲或公开课。
- 参加国际线上会议。
- 浏览外语直播、播客或课程视频。
- 播放本地外语视频文件。

## 技术路线

MVP 阶段优先使用 Python 快速验证核心链路：

- 桌面界面：PySide6 / Qt Quick
- 系统声音采集：Windows WASAPI Loopback
- 音频处理：持续音频流、环形缓冲、Silero VAD 分段和滑动窗口缓存
- 语音识别：mock ASR 与百度智能云短语音识别标准版 HTTP 适配器
- 中文翻译：大模型翻译接口
- 字幕修正：基于上下文的字幕段回写机制
- 打包发布：PyInstaller

## 系统流程

```text
Windows 系统声音
  -> WASAPI Loopback 音频采集
  -> 音频切片 / 重采样 / VAD 分段
  -> AI 实时语音识别
  -> 原文文本分段
  -> AI 上下文翻译
  -> 中文字幕显示
  -> 历史字幕自动修正
```

## 字幕状态设计

系统为每个字幕段分配 `segment_id`，并维护字幕状态，确保后续修正可以回写到指定字幕，而不是简单追加新内容。当前已实现字幕事件模型和状态容器，支持 `segment.partial`、`segment.final`、`segment.update` 三类事件。

```text
partial：临时字幕，优先保证低延迟
final：正式字幕，表示当前语音段已稳定
updated：修正字幕，表示系统根据后续上下文修正了历史内容
```

状态管理规则：

- `partial` 可以新增或更新临时字幕。
- `final` 会确认当前字幕段，并保留为正式结果。
- `update` 必须命中已有 `segment_id`，并回写原字幕段。
- 已确认或已修正的字幕不会被迟到的临时字幕覆盖。

示例：

```text
初始字幕：
我研究 AI 代理。

后续上下文：
They can use tools and complete tasks automatically.

修正后：
我研究能够使用工具并自动完成任务的 AI 智能体。
```

## 计划目录结构

```text
app/
  audio/          Windows 系统音频捕获与音频处理
  asr/            语音识别适配器
  translate/      翻译适配器
  correction/     字幕修正逻辑
  core/           字幕事件、配置和状态管理
  ui/             主控制窗口和悬浮字幕窗口
docs/
  方案设计.md
  PR计划.md
tests/
```

## 当前状态

项目处于核心链路逐步接入阶段，当前已具备 Python 应用入口、配置读取、基础日志输出、PySide6 主控制窗口、悬浮字幕窗口、字幕事件状态管理、模拟字幕流演示、Windows 系统音频捕获、Silero VAD 分段和 ASR 适配器命令行验证入口。桌面主流程目前仍使用模拟字幕流，真实 ASR 已可通过命令行验证，翻译和字幕修正 AI 能力将在后续 PR 接入。

## 依赖说明

当前阶段引入以下依赖：

- PySide6：用于构建 Windows 桌面主控制窗口和悬浮字幕窗口。
- soundcard：用于在 Windows 上枚举系统播放设备，并通过 loopback 捕获系统输出音频。
- numpy：由音频采集链路使用，用于保存和处理音频采样数据。
- ONNX Runtime：用于运行 Silero VAD ONNX 模型，进行语音活动检测。

开发依赖：

- ruff：用于检查 Python 代码风格、导入顺序和常见静态问题，不参与运行时功能。

项目内置 `assets/models/silero_vad.onnx`，来源为 Silero VAD 官方仓库。当前 VAD 路线只使用 ONNX Runtime，不引入 PyTorch / torchaudio。

ASR 真实服务通过 Python 标准库 `urllib` 调用百度智能云短语音识别标准版接口，目前未额外引入 HTTP 第三方库。mock ASR 为本项目自研演示适配器，用于没有 API Key 时验证音频段到原文文本的链路。

依赖版本通过 `pyproject.toml` 和 `uv.lock` 管理，确保后续评审时可以复现相同环境。后续每次新增第三方库或框架时，将同步更新 README，说明依赖用途和原创功能边界。

## 运行方式

当前版本提供基础桌面主窗口和命令行验证入口。

### 环境要求

- Windows 10 / Windows 11
- Python 3.11 或更高版本
- uv

### 安装依赖

```powershell
uv sync
```

### 启动主控制窗口

```powershell
uv run python -m app
```

当前主窗口提供开始、暂停、停止、状态展示、音频源选择、翻译模式和字幕样式等基础界面。点击“开始”会启动内置模拟字幕流，演示临时字幕、正式字幕和历史字幕回写修正；点击“悬浮字幕”可以单独显示置顶半透明字幕窗口，并支持通过主窗口调整字号、透明度和双语显示模式。系统音频捕获、VAD 和 ASR 已提供命令行验证入口，后续 PR 会继续接入桌面主流程和翻译链路。

### 演示模式

当前版本内置一段英文技术分享字幕脚本，用于在未接入音频和 AI 服务前验证核心体验：

- `segment.partial`：快速显示临时字幕。
- `segment.final`：确认稳定字幕。
- `segment.update`：根据后续上下文回写历史字幕，例如将 “AI 代理” 修正为 “AI 智能体”。

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

如需调用真实 ASR 服务，可配置百度智能云短语音识别标准版接口：

```powershell
$env:ASR_PROVIDER="baidu-cloud"
$env:ASR_API_KEY="你的百度 API Key"
$env:ASR_SECRET_KEY="你的百度 Secret Key"
uv run python -m app --transcribe-audio artifacts/audio/system_capture.wav
```

如果已经有可用的百度 `access_token`，也可以直接配置：

```powershell
$env:ASR_PROVIDER="baidu-cloud"
$env:ASR_ACCESS_TOKEN="你的百度 access_token"
uv run python -m app --transcribe-audio artifacts/audio/system_capture.wav
```

可选参数：

- `ASR_BAIDU_ENDPOINT`：默认 `http://vop.baidu.com/server_api`。
- `ASR_BAIDU_DEV_PID`：默认 `auto`。当识别语言是 `en` 时自动使用英语模型 `1737`，中文默认使用普通话模型 `1537`。
- `ASR_BAIDU_CUID`：默认 `ai_interpreter_windows`，用于标识本机客户端。
- `ASR_TIMEOUT_SECONDS`：默认 `30`。
- `--asr-language en`：指定识别语言，默认读取 `SOURCE_LANGUAGE`。
- `--asr-prompt "technical conference"`：预留给支持提示词的 ASR 适配器，当前百度云适配器不使用该参数。

### 预览系统音频 ASR 分段

播放一段包含英文人声的视频后执行：

```powershell
uv run python -m app --preview-asr-stream --stream-duration 10 --chunk-duration 0.25 --asr-provider mock
```

命令会捕获系统音频，通过 Silero VAD 切分语音段，并在每个 `speech_end` 后调用 ASR。mock 模式适合验证实时链路；配置百度云 ASR 后，可用同一命令测试实际识别效果。

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

