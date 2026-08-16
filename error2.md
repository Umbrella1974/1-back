[MANUS TCP] start this Python runner before SDKMinimalClient_Windows.
[MANUS TCP] listening on 127.0.0.1:8888
Waiting for manus_vive_com combined JSON TCP client...
[MANUS TCP] no client connected after 5 seconds.
[MANUS TCP] 1. 确认 SDKMinimalClient_Windows 是在本 程序启动后运行的；
[MANUS TCP] 2. 确认端口是 8888；
[MANUS TCP] 3. 确认没有 capture_raw_jsonl.py 或其他 程序占用 8888；
[MANUS TCP] 4. 如果 C++ 之前连接失败，需要重启 C++。
Open hand calibration: press Enter, then keep hand open...
[MANUS TCP] client connected
[MANUS TCP] first frame received
C-shape calibration: press Enter, then keep the task-ready C-shape posture...
Pinch calibration: press Enter, then pinch thumb and target finger...
Calibration threshold_a=0.102701
Wrist neutral calibration: press Enter, then keep wrist neutral...
[WRIST] neutral calibration collecting...
Wrist left calibration: press Enter, then rotate wrist left...
[WRIST] left calibration collecting...
Wrist right calibration: press Enter, then rotate wrist right...
[WRIST] right calibration collecting...
Wrist up calibration: press Enter, then move wrist up...
[WRIST] up calibration collecting...
Wrist down calibration: press Enter, then move wrist down...
[WRIST] down calibration collecting...
[WRIST] calibration passed: threshold=0.053599
[WRIST] up/down calibration passed: threshold=-0.083775
[WRIST] writing wrist_rotation_timeseries.csv
[CALIBRATION] saved D:\11111code\1-back\calibrations\12324075_exp2_cal_v01.json
Tactile-only task: press Enter to start the formal tactile session...
pending contact sampled delay: 1414
contact emitted
[HAPTIC] event=contact modality=vibration command_id=1 tcp=queued
[HAPTIC] trial=0 event=contact modality=vibration duration=1500ms
event emitted: slip
[HAPTIC] event=slip modality=vibration command_id=11 tcp=queued
[HAPTIC] trial=0 event=slip modality=vibration duration=2000ms
event emitted: left
[HAPTIC] event=left modality=vibration command_id=5 tcp=queued
[HAPTIC] trial=0 event=left modality=vibration duration=1000ms
event emitted: right
[HAPTIC] event=right modality=vibration command_id=9 tcp=queued
[HAPTIC] trial=0 event=right modality=vibration duration=1000ms
event emitted: up
[HAPTIC] event=up modality=vibration command_id=8 tcp=queued
[HAPTIC] trial=0 event=up modality=vibration duration=1000ms
event emitted: down
[HAPTIC] event=down modality=vibration command_id=10 tcp=queued
[HAPTIC] trial=0 event=down modality=vibration duration=1000ms
event emitted: release
[HAPTIC] event=release modality=vibration command_id=4 tcp=queued
[HAPTIC] trial=0 event=release modality=vibration duration=1500ms
[HAPTIC] release emitted.
single task complete. Haptic events: 7
[HAPTIC TCP] connecting vibration 192.168.106.58:12346...
[HAPTIC TCP] vibration connected 192.168.106.58:12346
Session: 12324075_exp2_001_02_motor_dual_plan1_20260816_224808
Output: D:\11111code\1-back\outputs\12324075_exp2_001\sessions\12324075_exp2_001_02_motor_dual_plan1_20260816_224808
[MANUS TCP] start this Python runner before SDKMinimalClient_Windows.
[MANUS TCP] listening on 127.0.0.1:8888
Waiting for manus_vive_com combined JSON TCP client...
[MANUS TCP] no client connected after 5 seconds.
[MANUS TCP] 1. 确认 SDKMinimalClient_Windows 是在本 程序启动后运行的；
[MANUS TCP] 2. 确认端口是 8888；
[MANUS TCP] 3. 确认没有 capture_raw_jsonl.py 或其他 程序占用 8888；
[MANUS TCP] 4. 如果 C++ 之前连接失败，需要重启 C++。
[CALIBRATION] loaded 12324075_exp2_cal_v01
Calibration quick check: press Enter, then keep hand open and wrist neutral...q
[CALIBRATION] quick check failed: not_enough_valid_open_quick_check_frames
Press Enter to run a full calibration and save a new version...q
Open hand calibration: press Enter, then keep hand open...
C-shape calibration: press Enter, then keep the task-ready C-shape posture...
Pinch calibration: press Enter, then pinch thumb and target finger...
Traceback (most recent call last):
  File "D:\11111code\1-back\run_participant_manifest.py", line 487, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "D:\11111code\1-back\run_participant_manifest.py", line 481, in main
    run_dir = run_participant_manifest(args.manifest, validate_only=args.validate_only)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\11111code\1-back\run_participant_manifest.py", line 125, in run_participant_manifest
    output_path = runner_fn(prepared.config_path)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\11111code\1-back\run_pinch_haptic_1back.py", line 758, in run_live_pinch_haptic_1back
    calibration = _run_live_pinch_calibration(
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\11111code\1-back\run_pinch_haptic_1back.py", line 1012, in _run_live_pinch_calibration
    return calibrate_from_samples(
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\11111code\1-back\pinch_calibration.py", line 145, in calibrate_from_samples
    return calibrate_from_distances(
           ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\11111code\1-back\pinch_calibration.py", line 177, in calibrate_from_distances
    raise ValueError(
ValueError: open hand valid frame count 0 is less than min_valid_frames 30.