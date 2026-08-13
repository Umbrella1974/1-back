(1-back-3) D:\11111code\1-back>python run_pinch_haptic_1back.py --config dualtask_config.yaml
[HAPTIC TCP] connecting vibration 192.168.1.22:12346...
[HAPTIC TCP] vibration connected 192.168.1.22:12346
[HAPTIC TCP] connecting matrix 192.168.1.9:12345...
Traceback (most recent call last):
  File "D:\11111code\1-back\vendor_exp2_abc\haptic_tcp_worker.py", line 75, in start
    sock = self.socket_factory(
           ^^^^^^^^^^^^^^^^^^^^
  File "D:\Anaconda2020\Anaconda\envs\1-back-3\Lib\socket.py", line 865, in create_connection
    raise exceptions[0]
  File "D:\Anaconda2020\Anaconda\envs\1-back-3\Lib\socket.py", line 850, in create_connection
    sock.connect(sa)
TimeoutError: timed out
The above exception was the direct cause of the following exception:
Traceback (most recent call last):
  File "D:\11111code\1-back\run_pinch_haptic_1back.py", line 2147, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "D:\11111code\1-back\run_pinch_haptic_1back.py", line 761, in main
    run_live_pinch_haptic_1back(args.config)
  File "D:\11111code\1-back\run_pinch_haptic_1back.py", line 541, in run_live_pinch_haptic_1back
    sender = SimpleHapticSender(sender_config, session_id=session_id)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\11111code\1-back\simple_haptic_sender.py", line 270, in __init__
    self._start_tcp_workers()
  File "D:\11111code\1-back\simple_haptic_sender.py", line 651, in _start_tcp_workers
    self._matrix_worker = self._start_matrix_worker()
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\11111code\1-back\simple_haptic_sender.py", line 697, in _start_matrix_worker
    worker.start()
  File "D:\11111code\1-back\vendor_exp2_abc\haptic_tcp_worker.py", line 83, in start
    raise MatrixHapticConnectionError(
vendor_exp2_abc.haptic_tcp_worker.MatrixHapticConnectionError: matrix haptic connect failed: 192.168.1.9:12345: timed out
