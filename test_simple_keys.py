"""
简化版按键测试
"""
import sys

# 首先检查并安装pygame
try:
    import pygame
    print(f"✓ pygame已安装 (版本: {pygame.__version__})")
except ImportError:
    print("✗ pygame未安装")
    print("\n请先安装pygame:")
    print("1. 如果使用conda环境:")
    print("   conda activate 1-back")
    print("   pip install pygame")
    print("\n2. 或者直接运行:")
    print("   pip install pygame")
    print("\n3. 安装后再次运行此测试")
    sys.exit(1)

# 初始化pygame
pygame.init()

# 创建窗口
screen = pygame.display.set_mode((400, 300))
pygame.display.set_caption("按键测试 - 按F/J键测试")
clock = pygame.time.Clock()

# 字体
font = pygame.font.SysFont(None, 32)

print("\n=== 按键测试开始 ===")
print("按 F 键表示'相同'")
print("按 J 键表示'不同'")
print("按 ESC 键退出")
print("=================\n")

running = True
key_presses = []

while running:
    screen.fill((200, 200, 200))

    # 显示说明
    text_lines = [
        "按键测试",
        "",
        "按 F 键: 表示'相同'",
        "按 J 键: 表示'不同'",
        "按 ESC 键: 退出",
        "",
        f"已按按键: {len(key_presses)} 次"
    ]

    for i, line in enumerate(text_lines):
        text = font.render(line, True, (0, 0, 0))
        screen.blit(text, (50, 20 + i * 35))

    # 显示按键历史
    if key_presses:
        last_keys = key_presses[-5:]  # 显示最后5次按键
        for i, (key, desc) in enumerate(last_keys):
            text = font.render(f"{desc} (key={key})", True, (50, 50, 150))
            screen.blit(text, (50, 200 + i * 25))

    pygame.display.flip()

    # 事件处理
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            key_name = pygame.key.name(event.key)

            if event.key == pygame.K_ESCAPE:
                print("检测到ESC键，退出...")
                running = False
            elif event.key == pygame.K_f:
                print("检测到F键 (相同)")
                key_presses.append((event.key, "F键"))
            elif event.key == pygame.K_j:
                print("检测到J键 (不同)")
                key_presses.append((event.key, "J键"))
            else:
                print(f"检测到其他键: {key_name} (key={event.key})")
                key_presses.append((event.key, f"其他键: {key_name}"))

    clock.tick(60)

pygame.quit()

print("\n=== 测试结果 ===")
if key_presses:
    print(f"总共检测到 {len(key_presses)} 次按键:")
    for key, desc in key_presses:
        print(f"  - {desc} (key={key})")
else:
    print("未检测到任何按键")
    print("可能原因:")
    print("1. 窗口没有获得焦点（请点击窗口）")
    print("2. 键盘布局问题")
    print("3. pygame版本问题")

print("测试完成")