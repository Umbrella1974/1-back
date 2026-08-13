# MANUS Pinch + Haptic + 1-Back Runner

这个仓库包含一个 1-back 双任务实验 runner：从 `manus_vive_com` 输出的 MANUS combined JSON 中读取手部数据，完成 pinch 标定、haptic 计划调度、可选 wrist rotation 记录，并同步运行 1-back 任务。

当前主入口是：

```powershell
python run_pinch_haptic_1back.py --config dualtask_config.yaml
```

## 运行顺序

1. 确认 `dualtask_config.yaml` 中的 haptic TCP、wrist rotation、post-release 配置符合本次实验。
2. 先启动 Python runner：

   ```powershell
   python run_pinch_haptic_1back.py --config dualtask_config.yaml
   ```

3. 等控制台显示 MANUS TCP 正在监听 `127.0.0.1:8888` 后，再启动 `SDKMinimalClient_Windows` / `manus_vive_com` 客户端。
4. 按控制台提示完成：
   - open hand calibration
   - pinch calibration
   - 如果 `wrist_rotation.enabled=true`，继续完成 neutral / left / right wrist calibration
   - 进入正式 1-back + haptic 阶段

## 关键配置

主要配置文件是 `dualtask_config.yaml`。

### Session

```yaml
session:
  duration_s: 140
  haptic_plan_config: haptic_plan_config_example.yaml
  end_policy: stop_on_haptic_release
  allow_multiple_haptic_trials: false
  finish_active_haptic_before_exit: true
  post_release_recording_ms: 3000
  post_release_continue_nback: true
  release_nback_trial_window: [40, 50]
  prerelease_haptic_complete_by_trial: 45
  hold_release_until_nback_trial: true
  finish_nback_after_haptic_release: true
```

当前行为：

- release 前的 haptic event 按 `haptic_plan_config_example.yaml` 顺序和时间正常尽早发出。
- 如果 release 在第 40 试次前已经轮到发出，runner 会先 hold 住 release。
- 进入第 40 试次后，pending release 会真正发出。
- release 发出后，haptic 结束，但 1-back 继续到 50 试次完成。
- `post_release_recording_ms: 3000` 表示 release 后至少继续记录 3 秒；如果 1-back 还没完成，会继续记录到 1-back 完成。

这里的试次号是 1-based：`release_nback_trial_window: [40, 50]` 表示用户理解的第 40 到第 50 试次，不是 Python 内部的 index 39-49。

`duration_s` 需要足够长。当前 1-back 单试次约为：

```text
500ms fixation + 500ms stimulus + 1000-1500ms ISI = 2000-2500ms
```

因此：

```text
第 40 试次约 80-100s，平均约 90s
第 45 试次约 90-112.5s，平均约 101s
第 50 试次约 100-125s，平均约 112.5s
```

所以双任务配置里 `duration_s` 不建议低于 130；当前用 `140` 是为了覆盖随机 ISI 和 release 后补完 1-back 的余量。

如果你在 haptic plan 里增加 release 前的触觉数量，需要重新估算间隔。推荐经验值：

```yaml
# release 前 3-6 个 haptic event
onset_gap_after_previous_ms: [8000, 12000]

# release 前 8-10 个 haptic event
onset_gap_after_previous_ms: [5000, 8000]
```

`prerelease_haptic_complete_by_trial: 45` 是检查约束，不会自动压缩触觉间隔。如果 release 前的触觉到第 45 试次还没完成，summary 会写入 warning：

```text
prerelease_haptic_not_complete_by_trial_45
```

这说明当前 haptic 数量或间隔太大，需要调整 `haptic_plan_config_example.yaml` 或你自己的 haptic plan 文件。

### MANUS TCP

```yaml
manus:
  tcp_host: 127.0.0.1
  tcp_port: 8888
  require_tracker: false
  save_raw_frames: true
```

当前 runner 不要求 Vive Tracker。MANUS TCP 8888 接口不要和其他采集程序同时占用。

### Haptic TCP

```yaml
haptic:
  vibration_enabled: true
  matrix_enabled: false

vibration_tcp:
  enabled: true
  required: false
  host: 192.168.1.22
  port: 12346

matrix_tcp:
  enabled: false
```

`required=false` 时，haptic TCP 连接失败会 warning 并继续实验；`required=true` 时连接失败会停止实验。

### Haptic Plan

当前 `dualtask_config.yaml` 指向：

```yaml
haptic_plan_config: haptic_plan_config_example.yaml
```

`haptic_plan_config_example.yaml` 的 vibration slip 已配置显式停止命令：

```yaml
- name: slip
  modality: vibration
  command_label: slip_start
  command_id: 3
  end_command_label: slip_end
  end_command_id: 4
  duration_ms: 1000
```

因此正式日志里应能看到 `slip` 和 `slip_end` 两行，避免 slip vibration 一直 latch 到实验结束。

每个 haptic event 还可以选择加 1-back 试次窗口和软回正检查：

```yaml
- name: left
  modality: matrix
  channel_list: [1, 2, 3]
  duration_ms: 1000
  trigger_zone: closed_zone
  onset_gap_after_previous_ms: [6000, 10000]
  nback_trial_window: [20, 25]
  require_wrist_neutral_before_emit: true
  wrist_neutral_timeout_ms: 3000
```

含义：

- `onset_delay_ms` / `onset_gap_after_previous_ms` 仍然决定这个 event 本来应该什么时候出现。
- `nback_trial_window: [20, 25]` 只做试次 gate：如果本来过早，会等到第 20 试次再发；如果已经晚于第 25 试次，不会取消，会立刻发并记录 `late_window_warning`。
- `require_wrist_neutral_before_emit: true` 表示发出前要求手腕左右和上下分类都回到 `neutral`。
- `wrist_neutral_timeout_ms` 是软回正等待时间。timeout 后仍然发，但 `haptic_events.csv` 会标记这次不是干净回正发出。

release 仍优先使用 `dualtask_config.yaml` 里的全局：

```yaml
release_nback_trial_window: [40, 50]
hold_release_until_nback_trial: true
```

普通 event 使用自己写在 haptic plan 里的 `nback_trial_window`。

### Wrist Rotation

```yaml
wrist_rotation:
  enabled: true
  node_id: 0
  quaternion_order: wxyz
  calibration_duration_s: 3.0
  min_valid_frames: 30
  feature_method: calibrated_axis_projection
  classification_margin: 0.15
  save_timeseries: true
  required: false
```

`wrist_rotation` 只做标定、分类和记录，不作为 haptic trigger。它只读取 MANUS skeleton node0 的 `rotation` quaternion，不使用 tracker，也不使用 node position。

## 输出文件

每次运行会在 `outputs/<session_id>/` 下写入：

- `raw_frames.jsonl`
- `pinch_timeseries.csv`
- `haptic_events.csv`
- `nback_events.csv`
- `calibration.json`
- `summary.json`
- 如果启用 wrist rotation：
  - `wrist_rotation_calibration.json`
  - `wrist_rotation_timeseries.csv`

重点检查：

- `haptic_events.csv` 是否有 `slip_end command_id=4`
- `summary.json` 的 `end_reason`
- `summary.json` 的 `haptic_plan_id` 和 `haptic_plan_random_seed`
- `summary.json` 的 wrist rotation 字段
- `nback_events.csv` 是否符合 post-release 期间的预期行为

`haptic_events.csv` 新增了用于事后排查调度的字段：

- `time_ready_ms`：时间 scheduler 本来准备发出 event 的时刻。
- `actual_emit_ms` / `monotonic_ms`：gate 后真正发出的时刻。
- `planned_emit_trial_number`：`time_ready_ms` 所在的 1-back 试次。
- `emit_trial_number`：真正发出时所在的 1-back 试次。
- `trial_gate_window` / `trial_gate_open_trial`：本 event 使用的试次 gate。
- `held_by_trial_gate`：是否因为试次窗口过早而等待。
- `late_window_warning`：是否晚于窗口上界才发出。
- `wrist_neutral_gate_required`：是否要求回正。
- `held_by_wrist_neutral_gate`：是否曾经因为未回正而等待。
- `wrist_neutral_gate_passed`：真正发出时是否干净回正。`False` 通常表示 timeout 后仍发。
- `wrist_neutral_wait_ms`：等待回正的时间。
- `wrist_lr_class_at_emit` / `wrist_up_down_class_at_emit`：发出瞬间的手腕分类。

这些字段和 n-back、pinch、wrist 数据使用同一个 `monotonic_ms` 时间系统，可以直接做时间差。

## 测试

常用 smoke check：

```powershell
python -m py_compile run_pinch_haptic_1back.py simple_haptic_sender.py haptic_trial_scheduler.py haptic_plan_config.py dualtask_logger.py wrist_rotation.py
python -m pytest tests\test_wrist_rotation.py tests\test_simple_haptic_sender_tcp.py tests\test_haptic_trial_scheduler.py tests\test_pinch_haptic_1back_core.py
```

全量测试：

```powershell
python -m pytest
```

## 不应修改的边界

除非有明确新需求，不要修改：

- `exp2`
- `manus_vive_com`
- MANUS TCP 8888 接口
- `nback_task_final.py`
- haptic scheduler 的事件顺序
- matrix 发送逻辑
- pinch calibration 语义

## 后续需要整理的地方

- 你后续写好 3 套 haptic plan 后，需要统一检查每套 plan 的 `plan_id`、`random_seed`、事件顺序、modality、TCP 开关是否和实验条件匹配。
- 建议保留一套快速 debug plan，把所有 gap 缩短，用来先验证 TCP、日志字段、trial window 和软回正 gate。
- 如果要把所有 haptic 条件做成正式实验批量入口，可以再新增一个小的条件选择层；当前最小做法仍是每次在 `dualtask_config.yaml` 里切换 `haptic_plan_config`。
