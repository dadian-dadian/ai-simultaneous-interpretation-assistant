# 模型文件说明

## silero_vad.onnx

- 用途：系统音频流的语音活动检测。
- 来源：Silero VAD 官方仓库 `src/silero_vad/data/silero_vad.onnx`。
- 运行方式：通过 ONNX Runtime CPUExecutionProvider 推理，不引入 PyTorch / torchaudio。
- 输入格式：16 kHz、单声道、float32 音频帧。

模型文件用于比赛演示和本地验证，后续如需替换模型，应同步更新 README 和 PR 描述中的依赖来源说明。

