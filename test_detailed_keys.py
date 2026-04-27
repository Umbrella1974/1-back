"""
详细按键调试测试
"""
import sys
import pygame

# 检查pygame
try:
    pygame.init()
    print(f"✓ pygame初始化成功 (版本: {pygame.__version__})")
except Exception as e:
    print(f"✗ pygame初始化失败: {e}")
    sys.exit(1)

# 创建窗口
screen = pygame.display.set_mode((600, 400))
pygame.display.set_caption("详细按键调试 - 点击窗口获取焦点")
clock = pygame.time.Clock()

# 字体（尝试加载）
try:
    font = pygame.font.SysFont('simhei', 24)
    font_large = pygame.font.SysFont('simhei', 32)
    print("✓ 字体加载成功")
except:
    font = pygame.font.Font(None, 24)
    font_large = pygame.font.Font(None, 32)
    print("⚠ 使用默认字体")

print("\n" + "="*60)
print("详细按键调试开始")
print("="*60)
print("\n重要提示:")
print("1. 请点击窗口区域确保获得焦点")
print("2. 按 F 键 (相同)")
print("3. 按 J 键 (不同)")
print("4. 按 ESC 键退出")
print("5. 按其他键测试键码")
print("\n所有事件将实时显示在窗口和控制台")
print("="*60 + "\n")

# 数据收集
events_log = []
key_presses = []
mouse_events = []
window_events = []

running = True
frame_count = 0
last_event_time = pygame.time.get_ticks()

# 设置窗口位置（可选）
try:
    pygame.display.set_mode((600, 400), pygame.RESIZABLE)
except:
    pass

while running:
    current_time = pygame.time.get_ticks()
    frame_count += 1

    # 清屏
    screen.fill((240, 240, 240))

    # 处理所有事件
    events_this_frame = []
    for event in pygame.event.get():
        events_this_frame.append(event)

        # 分类记录事件
        event_info = f"帧{frame_count}: {event.type}"

        if event.type == pygame.QUIT:
            event_info += " (QUIT)"
            running = False

        elif event.type == pygame.KEYDOWN:
            key_name = pygame.key.name(event.key)
            key_unicode = event.unicode if event.unicode else 'None'
            event_info += f" (KEYDOWN: key={event.key}, name='{key_name}', unicode='{key_unicode}')"
            key_presses.append((current_time, event.key, key_name, key_unicode))

            # 特别关注的键
            if event.key == pygame.K_ESCAPE:
                print("检测到ESC键，退出...")
                running = False
            elif event.key == pygame.K_f:
                print("✓ 检测到F键 (相同)")
            elif event.key == pygame.K_j:
                print("✓ 检测到J键 (不同)")
            else:
                print(f"检测到其他键: {key_name} (key={event.key}, unicode='{key_unicode}')")

        elif event.type == pygame.KEYUP:
            key_name = pygame.key.name(event.key)
            event_info += f" (KEYUP: key={event.key}, name='{key_name}')"

        elif event.type == pygame.MOUSEBUTTONDOWN:
            event_info += f" (MOUSEBUTTONDOWN: pos={event.pos}, button={event.button})"
            mouse_events.append((current_time, 'DOWN', event.pos, event.button))

        elif event.type == pygame.MOUSEBUTTONUP:
            event_info += f" (MOUSEBUTTONUP: pos={event.pos}, button={event.button})"
            mouse_events.append((current_time, 'UP', event.pos, event.button))

        elif event.type == pygame.MOUSEMOTION:
            event_info += f" (MOUSEMOTION: pos={event.pos}, rel={event.rel})"

        elif event.type == pygame.ACTIVEEVENT:
            event_info += f" (ACTIVEEVENT: gain={event.gain}, state={event.state})"
            window_events.append((current_time, 'ACTIVE', event.gain, event.state))
            print(f"窗口焦点变化: gain={event.gain}, state={event.state}")

        elif event.type == pygame.WINDOWFOCUSGAINED:
            event_info += " (WINDOWFOCUSGAINED)"
            window_events.append((current_time, 'FOCUS_GAINED'))
            print("✓ 窗口获得焦点")

        elif event.type == pygame.WINDOWFOCUSLOST:
            event_info += " (WINDOWFOCUSLOST)"
            window_events.append((current_time, 'FOCUS_LOST'))
            print("⚠ 窗口失去焦点")

        elif event.type == pygame.WINDOWENTER:
            event_info += " (WINDOWENTER)"
            window_events.append((current_time, 'WINDOW_ENTER'))

        elif event.type == pygame.WINDOWLEAVE:
            event_info += " (WINDOWLEAVE)"
            window_events.append((current_time, 'WINDOW_LEAVE'))

        # 添加到日志
        events_log.append(event_info)

        # 控制台输出
        print(event_info)
        last_event_time = current_time

    # 如果30秒没有事件，提示用户
    if current_time - last_event_time > 30000 and len(events_log) == 0:
        print("\n⚠ 警告: 30秒内没有检测到任何事件!")
        print("  请确保:")
        print("  1. 点击窗口区域获取焦点")
        print("  2. 窗口没有被其他窗口遮挡")
        print("  3. 尝试按任意键或点击鼠标")

    # 保持日志长度
    if len(events_log) > 50:
        events_log = events_log[-50:]

    # === 绘制界面 ===
    y_pos = 20

    # 标题
    title = font_large.render("按键调试工具", True, (0, 0, 0))
    screen.blit(title, (20, y_pos))
    y_pos += 50

    # 状态信息
    status_text = [
        f"运行时间: {current_time//1000}秒",
        f"事件总数: {len(events_log)}",
        f"按键次数: {len(key_presses)}",
        f"鼠标事件: {len(mouse_events)}",
        f"窗口事件: {len(window_events)}",
        "",
        "【操作说明】",
        "1. 点击窗口获取焦点",
        "2. 按 F 键测试'相同'",
        "3. 按 J 键测试'不同'",
        "4. 按 ESC 键退出",
        "",
        "【最后10个事件】"
    ]

    for line in status_text:
        text = font.render(line, True, (0, 0, 128))
        screen.blit(text, (20, y_pos))
        y_pos += 25

    y_pos += 10

    # 显示最近事件
    for i, event_str in enumerate(reversed(events_log[-10:])):
        color = (0, 100, 0) if "KEYDOWN" in event_str else (100, 0, 0) if "KEYUP" in event_str else (50, 50, 50)
        text = font.render(event_str, True, color)
        screen.blit(text, (20, y_pos))
        y_pos += 22

    # 按键统计
    y_pos = 20
    x_pos = 320

    stats_title = font_large.render("按键统计", True, (0, 0, 0))
    screen.blit(stats_title, (x_pos, y_pos))
    y_pos += 50

    if key_presses:
        # 按键频率
        key_counts = {}
        for _, key, name, _ in key_presses:
            key_counts[name] = key_counts.get(name, 0) + 1

        stats_lines = ["按键频率:"]
        for key_name, count in sorted(key_counts.items(), key=lambda x: x[1], reverse=True):
            stats_lines.append(f"  {key_name}: {count}次")
    else:
        stats_lines = ["按键频率:", "  无按键记录"]

    stats_lines.extend([
        "",
        "特殊键检测:",
        f"  F键: {'✓' if any(k[2]=='f' for k in key_presses) else '✗'}",
        f"  J键: {'✓' if any(k[2]=='j' for k in key_presses) else '✗'}",
        "",
        "窗口焦点:",
        f"  获得焦点: {'✓' if any(e[1]=='FOCUS_GAINED' for e in window_events) else '?'}",
        f"  失去焦点: {'✓' if any(e[1]=='FOCUS_LOST' for e in window_events) else '?'}"
    ])

    for line in stats_lines:
        text = font.render(line, True, (0, 0, 128))
        screen.blit(text, (x_pos, y_pos))
        y_pos += 22

    # 更新显示
    pygame.display.flip()

    # 控制帧率
    clock.tick(60)

# 退出前总结
print("\n" + "="*60)
print("调试总结")
print("="*60)

print(f"\n总运行时间: {pygame.time.get_ticks()//1000}秒")
print(f"总事件数: {len(events_log)}")
print(f"按键次数: {len(key_presses)}")

if key_presses:
    print("\n按键详情:")
    for time_ms, key, name, unicode in key_presses[-20:]:  # 显示最后20次
        time_sec = time_ms / 1000.0
        print(f"  {time_sec:.1f}s: 键='{name}' (码={key}, unicode='{unicode}')")
else:
    print("\n⚠ 未检测到任何按键!")
    print("\n可能原因:")
    print("1. 窗口没有获得焦点 - 需要点击窗口")
    print("2. 键盘布局特殊 - 尝试其他键")
    print("3. 系统权限问题 - 尝试以管理员运行")
    print("4. 防病毒软件阻止 - 暂时禁用")
    print("5. pygame版本兼容性问题")

print("\n窗口焦点事件:")
if window_events:
    for time_ms, event_type, *extra in window_events:
        time_sec = time_ms / 1000.0
        extra_str = f", {extra}" if extra else ""
        print(f"  {time_sec:.1f}s: {event_type}{extra_str}")
else:
    print("  无窗口焦点事件记录")

print("\n" + "="*60)
pygame.quit()