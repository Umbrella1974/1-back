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
   - C-shape / contact calibration
   - pinch calibration
   - 如果 `wrist_rotation.enabled=true`，继续完成 neutral / left / right wrist calibration
   - 进入正式 1-back + haptic 阶段

## 关键配置

主要配置文件是 `dualtask_config.yaml`。

### Session

```yaml
session:
  task_type: dual
  session_seed: null
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

- `task_type: dual` 表示触觉任务 + 1-back；`task_type: single` 表示只运行同一套触觉任务，不启动 1-back。
- release 前的 haptic event 按 `haptic_plan_config_example.yaml` 顺序和时间正常尽早发出。
- 如果 release 在第 40 试次前已经轮到发出，runner 会先 hold 住 release。
- 进入第 40 试次后，pending release 会真正发出。
- release 发出后，haptic 结束，但 1-back 继续到 50 试次完成。
- `post_release_recording_ms: 3000` 表示 release 后至少继续记录 3 秒；如果 1-back 还没完成，会继续记录到 1-back 完成。

这里的试次号是 1-based：`release_nback_trial_window: [40, 50]` 表示用户理解的第 40 到第 50 试次，不是 Python 内部的 index 39-49。

`session_seed` 用来控制整轮实验的可复现随机性：

- `session_seed: null`：每次运行自动生成一个 master seed。
- `session_seed: 381274`：使用指定 master seed 复现这一轮。
- 程序会从 master seed 派生独立的 `haptic_seed` 和 `nback_seed`，避免 haptic gap 抽样和 1-back 序列共用同一个随机流。
- `summary.json` 会同时记录 `session_seed`、`haptic_seed`、`nback_seed`、`haptic_plan_template_random_seed` 和实际使用的 `haptic_plan_random_seed`。
- haptic plan YAML 里的 `random_seed` 现在作为模板 seed 保留用于审计；正式运行时会被 session-level 派生出的 `haptic_seed` 覆盖。

### Tactile-only / single-task

只做触觉任务时，在同一个 config 里设置：

```yaml
session:
  task_type: single
```

然后仍然使用同一个入口：

```powershell
python run_pinch_haptic_1back.py --config only-matrix.yaml
```

`single` 模式会保留 MANUS、pinch/wrist calibration、haptic plan、haptic TCP、neutral gate 和所有触觉日志，但不会启动 1-back pygame 窗口，也不会记录 1-back response。`nback_events.csv` 仍会写 header-only 空文件，方便后续批量分析。

### Cue dispatch mode

`task_type` 决定是否有 1-back；`cue_dispatch_mode` 决定 haptic cue 怎么被触发。两者是不同概念。

默认模式：

```yaml
session:
  cue_dispatch_mode: zone_sequential
```

`zone_sequential` 是当前正式使用的旧逻辑：

- 每个 cue 单独、按 haptic plan 顺序发送。
- `contact` 先等待 `open_zone`，离开 open zone 会取消 pending contact。
- 后续 cue 等待 closed/open 流程、gap、trial window、soft wrist neutral gate 等旧逻辑。
- 这是默认值；旧 config / manifest 不写也等价于这个模式。

新增模式：

```yaml
session:
  cue_dispatch_mode: timed_grouped
```

`timed_grouped` 是时间调度模式：

- 不使用 pinch zone 作为发送条件；`trigger_zone` 会保留进日志，但不控制发送。
- no-zone plan 可以不写 event-level `trigger_zone`，也可以不写顶层 `zones`；但这种 plan 必须配 `cue_dispatch_mode: timed_grouped`，不能用默认 `zone_sequential`。
- 第一个 cue/group 按 `onset_delay_ms` 或 `haptic_defaults.contact_onset_delay_ms`。
- 后续 cue/group 按 `onset_gap_after_previous_ms` 或 `haptic_defaults.inter_event_gap_ms`。
- 连续 event 如果写了相同 `simultaneous_group`，会在同一个 tick 发出。
- 同组发送时，PC 端先 queue vibration，再 queue matrix。
- 第一版不套旧的 n-back trial gate / wrist neutral gate，避免 simultaneous group 被拆开；如果 event 写了 `nback_trial_window`，日志会标记 `trial_gate_ignored=True`。

示例：

```yaml
events:
  - name: contact
    modality: vibration
    command_id: 1
    duration_ms: 1500
    trigger_zone: open_zone
    onset_delay_ms: [1000, 2000]
    simultaneous_group: g1

  - name: up
    modality: matrix
    channel_list: [82, 84, 87]
    duration_ms: 1000
    trigger_zone: closed_zone
    simultaneous_group: g1

  - name: release
    modality: vibration
    command_id: 4
    duration_ms: 1500
    trigger_zone: closed_zone
    onset_gap_after_previous_ms: [8000, 12000]
```

如果要把多个 gesture 放进同一个 event（例如 contact 和 up 间隔 100ms、或 right 后面跟两步 slip），用 `matrix_sequence`，每步用 `step_label` 标注语义：

```yaml
- name: right-slip
  modality: matrix
  matrix_sequence:
    - offset_ms: 0
      channel_list: [87, 88, 89]
      step_label: right
    - offset_ms: 100
      channel_list: [82, 84, 87]
      step_label: slip
    - offset_ms: 200
      channel_list: [83, 86, 89]
      step_label: slip
  duration_ms: 1000
```

- `offset_ms` 相对本 event 的 onset；每步会作为独立的 `haptic_events.csv` 行记录。
- `step_label` 是可选字段，写进 CSV 的 `matrix_sequence_step_label` 列，用于区分同一个 event 里不同 gesture（如 contact/up、right/slip）。统计时直接按这列分组，不用解析 `event_name` 里的 `-` 连接符。
- 第一个 event 名必须仍是 `contact`、最后一个仍是 `release`；中间 event 名可自由起（如 `right-slip`），只作为标签。

`single` 模式下会显式关闭：

- n-back trial window gate
- digit onset guard
- post-release 继续/补齐 n-back

如果 haptic plan 或 session 里仍写了 `nback_trial_window` / `release_nback_trial_window`，不会报错；运行时按设计忽略，并在 `haptic_events.csv` 写 `trial_gate_enabled=False`。实际触觉 timing 仍由同一套 haptic gap、duration、refractory 和 neutral gate 决定。pilot 后需要比较 single vs dual 的实际 inter-event interval、contact-to-release 时长和 P1-P5 相对位置。

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
- `calibration_timeseries.csv`
  - `queue_depth`
  - `queue_depth_at_phase_start`
  - `queue_depth_before_flush`
  - `flushed_count`
  - `first_frame_index_after_flush`
  - `latest_received_frame_index`
  - `frame_age_ms`
- `summary.json`
- 如果启用 wrist rotation：
  - `wrist_rotation_calibration.json`
  - `wrist_rotation_timeseries.csv`

重点检查：

- `haptic_events.csv` 是否有 `slip_end command_id=4`
- `summary.json` 的 `end_reason`
- `summary.json` 的 `session_seed`、`haptic_seed`、`nback_seed`、`haptic_plan_id` 和 `haptic_plan_random_seed`
- `summary.json` 的 wrist rotation 字段
- `summary.json` 的 `manus_queue_flush_events`
- `nback_events.csv` 是否符合 post-release 期间的预期行为
- `calibration_timeseries.csv` 是否显示 Open / C-shape / Pinch 某一段存在跳变或过渡帧
- `calibration_timeseries.csv` 和 `pinch_timeseries.csv` 的 flush/queue/frame age 字段是否显示旧帧污染

`haptic_events.csv` 新增了用于事后排查调度的字段：

- `time_ready_ms`：时间 scheduler 本来准备发出 event 的时刻。
- `actual_emit_ms` / `monotonic_ms`：gate 后真正发出的时刻。
- `queued_monotonic_ms` / `sent_monotonic_ms`：TCP 层真实时间戳 —— 命令进入发送队列（queued）和真正 `sendall` 出去（sent）的 `time.monotonic()` 时刻。和 `actual_emit_ms`（调度计划时刻）不同，用于复核触觉信号实际发出的准确时间。
- `planned_emit_trial_number`：`time_ready_ms` 所在的 1-back 试次。
- `emit_trial_number`：真正发出时所在的 1-back 试次。
- `trial_gate_enabled`：本次运行是否启用 n-back trial gate；`single` 模式为 `False`。
- `trial_gate_ignored`：event 本来配置了 trial window，但因为 `task_type=single` 被按设计忽略。
- `trial_gate_window` / `trial_gate_open_trial`：本 event 使用的试次 gate。
- `held_by_trial_gate`：是否因为试次窗口过早而等待。
- `late_window_warning`：是否晚于窗口上界才发出。
- `wrist_neutral_gate_required`：是否要求回正。
- `held_by_wrist_neutral_gate`：是否曾经因为未回正而等待。
- `wrist_neutral_gate_passed`：真正发出时是否干净回正。`False` 通常表示 timeout 后仍发。
- `wrist_neutral_wait_ms`：等待回正的时间。
- `wrist_lr_class_at_emit` / `wrist_up_down_class_at_emit`：发出瞬间的手腕分类。

`pinch_timeseries.csv` 也记录了 queue 诊断字段：

- `phase`：正式任务中为 `formal`。
- `queue_depth`：读取当前 frame 前 Python MANUS queue 中等待的 frame 数。
- `queue_depth_at_phase_start`：phase/formal flush 之后、开始读取前的 queue 深度。
- `queue_depth_before_flush`：本 phase/formal 重新开始前，队列里积压的旧 frame 数。
- `flushed_count`：本 phase/formal 开始前实际清掉的 frame 数。
- `first_frame_index_after_flush`：flush 后第一次被当前 phase/formal 消费的 frame index。
- `latest_received_frame_index`：读取当前 frame 前 Python 接收线程已经收到的最新 frame index。
- `frame_age_ms`：当前 frame 从 TCP callback 收到，到正式被当前消费者处理之间的延迟。

`summary.json` 额外记录 `manus_queue_flush_events`，按顺序列出 quick check、pinch calibration、wrist calibration、formal start 前的 flush 情况。

MANUS queue 警示：

- 已实现所有“消费者暂停后重新开始”位置的 queue flush，包括 quick check、Open/C-shape/Pinch calibration、wrist calibration 和 formal loop start。
- formal loop 暂时继续使用 FIFO。不要在没有证据时切到 latest/drop policy，因为 RT onset 检测依赖连续帧；丢中间帧本身可能引入新的时间误差。
- 每次 pilot 后先看 `pinch_timeseries.csv`：如果 formal 期间 `queue_depth` 基本在 0-1、`frame_age_ms` 很低，保留 FIFO。
- 如果 formal 期间 `queue_depth` 或 `frame_age_ms` 持续增长，再查性能瓶颈；只有确认持续 backlog 后，才考虑 latest/drop policy。
- calibration 重跑后，重点看 contact/pinch 开头是否还出现上一阶段旧状态；如果 flush 生效，旧状态应该消失或大幅减少。
- 2026-08-17 的 single/dual pilot 中，formal loop 的 `max_queue_depth_during_formal` 约为 2，`max_frame_age_ms_during_formal` 约为 32 ms，没有持续增长。因此当前判断是：queue flush 第一层问题已基本解决，FIFO 可以暂时保留。

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

## Cue Cycle 分析

采集结束后可以基于现有 CSV 生成每个 tactile cue 的动作周期指标：

```powershell
python analyze_cue_cycles.py outputs\你的session目录
```

会写出：

- `cue_cycle_metrics.csv`
- `cue_cycle_summary.json`

当前算法：

- cue onset 使用 `haptic_events.csv` 的 `actual_emit_ms`。
- tactile response detection 只使用 `wrist_rotation_timeseries.csv`，不使用 `nback_events.csv`。
- 先找 cue 后第一个稳定有效动作。
- 如果方向错误，继续找第一次正确动作并记录 correction。
- 正确/最终动作之后，再找第一次稳定 `neutral` return。
- 默认稳定窗口是 `150ms`，默认 response timeout 是 `5000ms`。

`cue_cycle_metrics.csv` 包含 `feedback_condition`、`task_condition`、`plan_id`、`event_position`、`emit_trial_number`、`next_cue_onset_ms`、`response_timeout_ms`、RT、correction time、return time 和 full cycle 等字段。

`nback_events.csv` 暂时不参与 tactile response detection，只用于后续 dual-task performance 分析。

## Unified Cue Response 分析

新一版离线分析使用统一的 event-level 输出，但保留 wrist/slip 各自的行为指标：

```powershell
python analyze_cue_response_metrics.py outputs\你的session根目录 --output-dir analysis_outputs\你的输出目录
```

输出：

- `cue_response_metrics.csv`
- `wrist_neutral_reclass.csv`
- `up_diagnostics.csv`
- `cue_response_diagnostics.csv`
- `cue_response_summary.json`

当前 detector 版本是 `pilot_v0.3`，只用于 pilot 诊断。正式实验前需要冻结 detector 版本和 `clean / recoverable / contaminated` 规则，不要在正式数据出来后按结果重新调阈值。

`cue_response_metrics.csv` 和 `cue_response_diagnostics.csv` 会保留 `task_type` 与 `nback_enabled`，后续分析应使用这两个字段区分 `single` / `dual`，不要只凭 `nback_events.csv` 是否存在判断。

当前 S-R mapping：

- `left/right/up/down` 使用 `wrist_rotation_timeseries.csv` 的连续 score 离线重分类。
- `slip` 使用 `pinch_timeseries.csv` 的 `pinch_distance`，先转成 `pinch_closure = (max_distance - pinch_distance) / (max_distance - min_distance)`。
- 新采集数据会额外保存 `Open / C-shape / Pinch` 三个 pinch reference。reference QC 通过时，`contact/release/slip` 会进入三状态离线评分；旧数据或 reference QC 不足时会标记为 `insufficient_pinch_reference`。

统一字段里要区分两类质量：

- `response_quality`：是否检测到可用于 accuracy/RT 的行为反应。
- `cycle_quality`：完整动作周期是否结束，例如 wrist 是否回到 neutral，slip 是否完成 reopening。
- `response_sequence_complete`：语义动作序列是否完成；例如 contact 是 `Open -> C-shape`，slip 是 `C-shape -> Pinch -> C-shape`，release 是 `C-shape -> Open`。
- `trial_quality` 目前保留为兼容字段，优先看 `response_quality` 和 `cycle_quality`。

RT 字段也要分开使用：

- `first_response_rt_ms`：第一次检测到的行为，可能是错误方向；如果 cue onset 时已经预存动作，则留空。
- `correct_response_rt_ms`：第一次正确行为出现的时间，正式 RT 统计优先使用这个字段。
- `was_corrected` / `correction_time_ms`：先错后对时记录纠正。
- `response_rt_ms` 当前等同于 `correct_response_rt_ms`，作为主 RT 便捷字段。

Wrist 分析：

- 在线分类器的旧 neutral 区间会被记录到 `wrist_neutral_reclass.csv`。
- 离线候选算法使用 neutral-centered region：以 `score=0` 为标定 neutral，动作边界取 `0` 与动作 mean 的中点。
- 该算法目前只是候选修正，尚未替换 live gate。

Slip 分析：

- slip onset 使用 semantic slip 的第一行，即 `source_event_name` 为空的 `event_name=slip`；matrix sequence 的后续 step 不作为新的 semantic cue。
- 第一版观察窗口是当前 slip onset 到下一 semantic cue onset。
- `pinch_detected` 表示 cue 后相对 pre-cue baseline 出现显著进一步捏合。
- `release_detected` 表示 peak 后出现显著 reopening。
- 如果 `Open / C-shape / Pinch` reference 可用，`response_sequence_complete` 表示是否完成 `C-shape -> Pinch -> C-shape`；最后不要求回到 cue 前完全相同的 `pinch_distance`。
- `returned_to_precue_baseline` 只是附加 QC 字段，不决定三状态 slip 是否完成。

Pinch 三状态 reference：

- 新的 pinch calibration 会采集 `open_distance_*`、`contact_distance_*` 和 `pinch_distance_*` 分布摘要，包括 mean、median、MAD、p10、p90 和有效样本数。
- 候选状态边界只来自个人标定中点：`open_contact_boundary = (open_median + contact_median) / 2`，`contact_pinch_boundary = (contact_median + pinch_median) / 2`。
- reference QC 要求中位数顺序满足 `open > contact > pinch`，且 p10/p90 不明显跨过相邻中点边界；失败时只标记 reference quality 不足，不会用三状态硬评分。
- 这些边界是离线分析候选边界，不是给受试者理解或命中的隐藏目标，也不改变实时 `open_zone / closed_zone` haptic trigger。
- `contact` 的语义是 `Open -> C-shape`：`first_response_correct` 看第一次是否 closing，`response_sequence_complete` 看是否稳定进入 C-shape reference。
- `release` 的语义是 `C-shape -> Open`：`first_response_correct` 看第一次是否 opening，`response_sequence_complete` 看是否稳定进入 Open reference。

`up_diagnostics.csv` 专门检查 `up` cue，包含 pre-cue state、first stable direction、max up score、min down score 和 eventual up detected。当前 pilot 里 `up` 是最需要复查的 cue，不建议继续整体调 wrist detector 来“修”这些行为错误。

`cue_response_diagnostics.csv` 是通用 first-excursion 旁路诊断，不替换 `cue_response_metrics.csv` 的正式判定。它对 `left/right/up/down` 使用对应 wrist score 轴，对 `slip` 使用 `pinch_closure`，记录 cue 后第一次稳定偏离 neutral 的方向、RT、峰值、反向过冲，以及它是否和当前 first stable response 一致。这个文件优先用于解释 `up` 是否存在“小幅正确上抬后快速下冲”的情况。

下一次 pilot 起，`wrist_rotation_calibration.json` 会额外记录 score 分布摘要、旧 neutral 区间、neutral-centered 候选区间和 `score=0` 是否落在旧 neutral 区内。这些字段只增加日志，不改变实时实验行为。

Calibration reuse：

默认行为不变：如果 YAML 里没有 `calibration_reuse`，每个 session 都会完整采集 Open / C-shape / Pinch，以及启用时的 wrist neutral / left / right / up / down calibration。

如果要让同一个受试者后续 session 复用同一份 calibration，可以在当前运行的 config 里加：

```yaml
calibration_reuse:
  enabled: true
  calibration_in: calibrations/P001_exp2_cal_v01.json
  calibration_out: calibrations/P001_exp2_cal_v01.json
  calibration_id: P001_exp2_cal_v01
  quick_check_enabled: true
  quick_check_duration_s: 2.0
  open_mad_multiplier: 6.0
  wrist_neutral_min_ratio: 0.80
```

- 如果 `calibration_in` 存在，程序先读取这份 calibration bundle。
- 如果 `quick_check_enabled=true`，正式任务前会要求保持 open hand + neutral wrist。
- quick check 只检查旧 calibration 是否仍可用：open pinch distance 是否接近旧 Open reference、open 信号是否稳定、启用 wrist 时 wrist 是否大多数仍被旧 calibration 判为 neutral。
- quick check 通过时，不重新标定；当前 session 仍会写自己的 `calibration.json` / `wrist_rotation_calibration.json`，内容来自复用的 bundle。
- quick check 失败时，程序要求完整重标；新 calibration 不覆盖旧文件，而是保存成下一版，例如 `P001_exp2_cal_v02.json`。
- 如果旧 bundle 里的 `calibration_passed=false` 或 `pinch_reference_quality_passed=false`，程序不会复用它，即使 quick check 配置关闭也会要求完整重标。
- `summary.json` 会记录 `calibration_id`、`calibration_loaded_from_bundle`、`calibration_bundle_path`、`calibration_saved_path` 和 quick check 的距离/腕部检查字段。

第一版 quick check 没有固定 Open/C/Pinch 的人为百分比阈值；open 检查使用旧 Open reference 的 MAD 倍数。`open_mad_multiplier` 和 `wrist_neutral_min_ratio` 目前是 config 参数，下一批 pilot 后再根据真实漂移分布决定是否调整。

命令行 prompt 中止：

- 在 calibration、quick check、wrist calibration、tactile-only start 等命令行等待阶段，可以输入 `q` / `quit` / `exit` / `abort` 后回车。
- 当前 session 会记录 `operator_aborted`，participant manifest 会把该 session 标记为 `aborted` 并停止后续 session。
- 这个机制不影响正式 1-back 窗口里的反应键。

Single release 后记录：

```yaml
session:
  post_release_recording_ms: 3000
  single_post_release_recording_ms: 6000
```

`single_post_release_recording_ms` 只覆盖 tactile-only / single session。`dual` session 仍使用原来的 `post_release_recording_ms` 和 `finish_nback_after_haptic_release` 逻辑。

Participant manifest：

如果要按受试者级别连续跑多个 session，可以从 `participant_manifest_example.yaml` 复制一份并修改：

```yaml
participant_id: P001
run_id: P001_exp2_001
run_seed: null
output_root: outputs

calibration:
  path: calibrations/P001_exp2_cal_v01.json
  reuse: true
  quick_check: true

sessions:
  - session_label: motor_single_plan1
    order: 1
    task_type: single
    feedback_type: motor_only
    cue_dispatch_mode: zone_sequential
    config: only-motor.yaml
    haptic_plan_config: haptic-plan-only-motor-1.yaml
    plan_id: only-motor-1
```

先只校验，不连接 MANUS/ESP32：

```bash
python run_participant_manifest.py --manifest participant_manifest_example.yaml --validate-only
```

正式运行：

```bash
python run_participant_manifest.py --manifest participant_manifest_example.yaml
```

从某个 order 继续运行：

```bash
python run_participant_manifest.py --manifest participant_manifest_example.yaml --start-order 5 --calibration-in calibrations/P001_exp2_cal_v02.json
```

只运行某一个 order：

```bash
python run_participant_manifest.py --manifest participant_manifest_example.yaml --only-order 5 --calibration-in calibrations/P001_exp2_cal_v02.json
```

manifest runner 会：

- 检查 `participant_id`、`run_id`、session label/order 唯一性。
- 检查 `task_type`、`feedback_type`、config 文件、haptic plan 文件、`plan_id`。
- 检查 `feedback_type` 是否和 config 里的 `haptic` / `vibration_tcp` / `matrix_tcp` 开关明显矛盾。
- 为每个 session 从 `run_seed` 派生 `session_seed`，再由现有 session 逻辑派生 haptic/nback seed。
- 为每个 session 生成临时 config，写到 `outputs/<run_id>/configs/`。
- 把每个 session 的输出放到 `outputs/<run_id>/sessions/`。
- 写 `outputs/<run_id>/run_summary.json`，记录 planned/completed session、seed、condition、plan、output path、calibration path。
- 如果某个 session quick check 失败并保存了新版 calibration，后续 session 会自动改用新版 calibration path。
- 如果 formal session 中 haptic TCP 发送失败，session summary 会写 `end_reason: haptic_tcp_failed` / `haptic_tcp_failed: true`，manifest 会把该 order 标成 `failed` 并停止后续 session，方便之后用 `--start-order` 或 `--only-order` 续跑。

当前 manifest 不做自动 Latin square、不自动决定条件顺序、不自动选择 plan；它只忠实执行你写在 manifest 里的顺序。

Vibration ESP32 握手：

- 新建的 MicroPython 文件是 `esp32-test-main-1-handshake.py`，原 `esp32-test-main-1.py` 不改。
- Python 端在 `vibration_tcp.enabled: true` 时默认发送 `PING\n`，ESP32 必须返回包含 `OK` 的一行，例如 `OK PONG`。
- 如需临时兼容旧 ESP32 程序，可以在对应 YAML 的 `vibration_tcp` 下显式写 `handshake_enabled: false`；正式实验建议保持默认开启。

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
- `analyze_cue_cycles.py` 是旧版 wrist-only 周期分析；新分析优先使用 `analyze_cue_response_metrics.py`。
- cue cycle 分析目前是事后脚本，没有写回运行时主流程；如果正式流程需要自动生成分析结果，可以在 session 结束后再接入。
- 如果要正式采集，建议先用 `--validate-only` 检查 manifest，再用一位 pilot 完整跑一遍 manifest workflow，确认 calibration quick check 和连续 session 切换在真实设备上顺畅。
