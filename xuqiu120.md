现在不要新增功能。先做 repository consistency + smoke check，然后只修阻塞问题。

目标：
确认 GitHub main、本地工作区、实际运行代码是一致的；确认 slip_end、post-release、wrist_rotation 不是只写在配置或模块里，而是真的进入 runner。

请按顺序做：

1. 打印并检查当前版本：
   git status
   git log -1 --oneline
   git rev-parse HEAD

2. 检查当前实际文件内容：
   python - <<'PY'
from pathlib import Path
for p in [
    "dualtask_config.yaml",
    "run_pinch_haptic_1back.py",
    "simple_haptic_sender.py",
    "haptic_trial_scheduler.py",
    "dualtask_logger.py",
    "wrist_rotation.py",
]:
    text = Path(p).read_text(encoding="utf-8")
    print(p, "lines=", text.count("\\n") + 1, "chars=", len(text))
    for key in [
        "wrist_rotation",
        "post_release_recording_ms",
        "poll_due_control_commands",
        "PendingVibrationEndCommand",
        "end_command_id",
        "event_end_monotonic_ms",
        "distance_to_left",
        "required",
    ]:
        print(" ", key, key in text)
PY

3. 检查 YAML 是否真的能被解析：
   python - <<'PY'
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path("dualtask_config.yaml").read_text(encoding="utf-8"))
print(type(cfg), cfg.keys())
print("session", cfg.get("session"))
print("wrist_rotation", cfg.get("wrist_rotation"))
PY

如果 dualtask_config.yaml 变成一整行或解析失败，先恢复成正常多行 YAML。

4. 检查 slip_end 是否完整：
   - haptic_plan_config.py 支持 end_command_id
   - haptic_plan_config_example.yaml 的 slip 有 end_command_id: 4
   - ScheduledHapticEvent 必须包含 end_command_id / end_command_label / event_end_monotonic_ms
   - SimpleHapticSender 必须有 PendingVibrationEndCommand
   - SimpleHapticSender 必须有 poll_due_control_commands(now_ms)
   - run_pinch_haptic_1back.py 主循环必须每轮调用 poll_due_control_commands(now_ms)
   - post-release 阶段也必须继续调用 poll_due_control_commands(now_ms)

如果缺任何一项，请补最小实现，不要重构 scheduler。

5. 检查 post-release 是否完整：
   - dualtask_config.yaml 里 session.post_release_recording_ms 存在
   - run_pinch_haptic_1back.py 读取它
   - release 发出后不立刻 break，而是继续记录 pinch 到 release_emit_ms + release_duration_ms + post_release_recording_ms
   - summary end_reason 应为 haptic_release_post_recording_complete

如果缺失，请补最小实现。

6. 检查 wrist_rotation 是否完整：
   - dualtask_config.yaml 有 wrist_rotation 配置段
   - run_pinch_haptic_1back.py import wrist_rotation.py
   - run_pinch_haptic_1back.py 读取 wrist_rotation_config_from_dict
   - enabled=true 时执行 neutral / left / right 三段 calibration
   - 正式阶段每帧调用 classify_wrist_rotation_frame
   - dualtask_logger.py 写 wrist_rotation_calibration.json
   - dualtask_logger.py 写 wrist_rotation_timeseries.csv
   - summary.json 写 wrist_rotation_enabled / calibration_passed / failure_reason / csv path

如果缺失，请只做最小 wiring。

7. 修 logger 字段：
   dualtask_logger.py 的 WRIST_ROTATION_TIMESERIES_FIELDS 必须包含：
   - distance_to_left
   - distance_to_right

8. 修 required：
   WristRotationConfig 增加 required: bool = False
   wrist_rotation_config_from_dict 读取 required
   enabled=true 且 calibration failed:
     - required=false: warning 后继续
     - required=true: raise RuntimeError

9. 清理运行产物：
   确认 .gitignore 包含：
   __pycache__/
   *.py[cod]
   .pytest_cache/
   outputs/
   data/
   logs/

   然后执行：
   git rm -r --cached __pycache__ data logs || true

10. 最后运行：
   python -m py_compile run_pinch_haptic_1back.py simple_haptic_sender.py haptic_trial_scheduler.py haptic_plan_config.py dualtask_logger.py wrist_rotation.py
   python -m pytest tests/test_wrist_rotation.py tests/test_simple_haptic_sender_tcp.py tests/test_haptic_trial_scheduler.py tests/test_pinch_haptic_1back_core.py

不要修改：
- exp2
- manus_vive_com
- MANUS TCP 8888
- pinch calibration 语义
- nback 任务语义
- matrix 逻辑