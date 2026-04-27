"""
原始按键调试 - 捕获所有键盘事件
"""
import pygame
import sys

print("=== 原始按键调试 ===")
print("按 F 和 J 键查看原始数据")
print("按 ESC 键退出")
print("="*50)

pygame.init()

# 设置窗口
screen = pygame.display.set_mode((800, 600))
pygame.display.set_caption("原始按键调试 - 按F/J键")
clock = pygame.time.Clock()

# 加载字体
try:
    font = pygame.font.Font(None, 32)
    small_font = pygame.font.Font(None, 24)
except:
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 24)

# 数据收集
events = []
last_event = None
special_keys = {}

# 已知键码映射（供参考）
known_keys = {
    27: "ESC",
    32: "SPACE",
    102: "F",
    106: "J",
    1073741903: "RIGHT",
    1073741904: "LEFT",
    1073741905: "DOWN",
    1073741906: "UP",
    13: "ENTER",
    8: "BACKSPACE",
    9: "TAB",
}

print("\n准备就绪，按任意键开始测试...")
print("重点测试: F键 (应该显示 key=102) 和 J键 (应该显示 key=106)")
print("-"*50)

running = True
while running:
    screen.fill((240, 240, 240))

    # 显示说明
    y = 20
    instructions = [
        "原始按键调试",
        "",
        "操作:",
        "1. 点击窗口获取焦点",
        "2. 按 F 键",
        "3. 按 J 键",
        "4. 按 ESC 键退出",
        "",
        f"事件总数: {len(events)}",
        f"最后事件: {last_event}" if last_event else "无事件"
    ]

    for line in instructions:
        text = font.render(line, True, (0, 0, 128))
        screen.blit(text, (20, y))
        y += 35

    # 显示事件历史（最后15个）
    y = 300
    title = font.render("最近事件:", True, (0, 0, 0))
    screen.blit(title, (20, y))
    y += 40

    for i, event_info in enumerate(reversed(events[-15:])):
        text = small_font.render(event_info, True, (50, 50, 150))
        screen.blit(text, (20, y))
        y += 25

    # 显示键码表
    y = 20
    x = 400
    key_table = [
        "键码参考:",
        "  ESC: 27",
        "  SPACE: 32",
        "  F: 102",
        "  J: 106",
        "  ENTER: 13",
        "  TAB: 9",
        "",
        "特殊键码:"
    ]

    for line in key_table:
        text = small_font.render(line, True, (0, 100, 0))
        screen.blit(text, (x, y))
        y += 25

    # 显示检测到的特殊键
    if special_keys:
        for key_code, count in list(special_keys.items())[:10]:
            name = known_keys.get(key_code, f"未知{key_code}")
            text = small_font.render(f"  {name}: {key_code} ({count}次)", True, (150, 50, 0))
            screen.blit(text, (x, y))
            y += 22

    pygame.display.flip()

    # 事件处理
    for event in pygame.event.get():
        event_info = None

        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN:
            # 获取所有可能的信息
            key_code = event.key
            key_name = "未知"
            try:
                key_name = pygame.key.name(key_code)
            except:
                pass

            key_unicode = event.unicode if event.unicode else "None"

            event_info = f"KEYDOWN: 键码={key_code}, 名称='{key_name}', unicode='{key_unicode}'"

            # 记录特殊键
            if key_code not in [32, 27]:  # 排除空格和ESC
                special_keys[key_code] = special_keys.get(key_code, 0) + 1

            # 检查是否是F或J键
            if key_name.lower() == 'f':
                print(f"✓ 检测到F键: {event_info}")
            elif key_name.lower() == 'j':
                print(f"✓ 检测到J键: {event_info}")
            elif key_code == 102:
                print(f"✓ 检测到键码102 (应该是F键): {event_info}")
            elif key_code == 106:
                print(f"✓ 检测到键码106 (应该是J键): {event_info}")
            else:
                print(f"其他键: {event_info}")

            if key_code == pygame.K_ESCAPE:
                print("检测到ESC键，退出...")
                running = False

        elif event.type == pygame.KEYUP:
            key_code = event.key
            try:
                key_name = pygame.key.name(key_code)
            except:
                key_name = "未知"
            event_info = f"KEYUP: 键码={key_code}, 名称='{key_name}'"

        elif event.type == pygame.MOUSEBUTTONDOWN:
            event_info = f"MOUSE: pos={event.pos}, button={event.button}"

        elif event.type == pygame.WINDOWFOCUSGAINED:
            event_info = "WINDOW: 获得焦点"

        elif event.type == pygame.WINDOWFOCUSLOST:
            event_info = "WINDOW: 失去焦点"

        if event_info:
            events.append(event_info)
            last_event = event_info
            # 控制事件列表长度
            if len(events) > 50:
                events = events[-50:]

    clock.tick(60)

pygame.quit()

print("\n" + "="*50)
print("调试总结:")
print(f"总事件数: {len(events)}")

keydown_events = [e for e in events if "KEYDOWN" in e]
print(f"按键事件: {len(keydown_events)}")

print("\n检测到的特殊键:")
for key_code, count in sorted(special_keys.items()):
    name = known_keys.get(key_code, f"未知{key_code}")
    print(f"  {name}: 键码={key_code}, 次数={count}")

# 特别检查F和J键
print("\nF/J键检测情况:")
f_found = any('f' in e.lower() for e in events) or 102 in special_keys
j_found = any('j' in e.lower() for e in events) or 106 in special_keys
print(f"  F键: {'✓' if f_found else '✗'}")
print(f"  J键: {'✓' if j_found else '✗'}")

if not f_found or not j_found:
    print("\n⚠ 问题分析:")
    print("1. 键盘布局可能不是QWERTY")
    print("2. 尝试其他位置的键（如D/K键）")
    print("3. 检查键盘区域设置")
    print("4. F/J键可能被系统拦截")

print("\n调试完成")