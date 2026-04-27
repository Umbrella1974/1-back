"""
极简按键测试 - 验证最基本的pygame功能
"""
import pygame
import sys

print("=== Pygame极简按键测试 ===")
print(f"Python版本: {sys.version}")
print(f"Pygame版本: {pygame.__version__}")

# 初始化
try:
    pygame.init()
    print("✓ Pygame初始化成功")
except Exception as e:
    print(f"✗ Pygame初始化失败: {e}")
    sys.exit(1)

# 创建窗口
try:
    screen = pygame.display.set_mode((300, 200))
    pygame.display.set_caption("极简测试 - 按任意键")
    print("✓ 窗口创建成功")
except Exception as e:
    print(f"✗ 窗口创建失败: {e}")
    sys.exit(1)

print("\n重要: 请点击窗口区域，然后按任意键")
print("按ESC键退出")
print("="*50)

# 设置窗口标题
pygame.display.set_caption("点击我！然后按任意键")

# 简单主循环
running = True
key_detected = False
click_detected = False

while running:
    # 清屏
    screen.fill((220, 220, 220))

    # 显示状态
    font = pygame.font.Font(None, 24)

    status = [
        "状态:",
        f"按键检测: {'✓' if key_detected else '✗ 等待按键...'}",
        f"点击检测: {'✓' if click_detected else '✗ 等待点击...'}",
        "",
        "操作:",
        "1. 点击此窗口",
        "2. 按任意键",
        "3. 按ESC退出"
    ]

    for i, line in enumerate(status):
        text = font.render(line, True, (0, 0, 0))
        screen.blit(text, (20, 20 + i * 25))

    pygame.display.flip()

    # 事件处理
    for event in pygame.event.get():
        print(f"事件类型: {event.type}")

        if event.type == pygame.QUIT:
            print("接收到QUIT事件")
            running = False

        elif event.type == pygame.KEYDOWN:
            print(f"按键事件: key={event.key}, unicode='{event.unicode}'")
            key_detected = True

            if event.key == pygame.K_ESCAPE:
                print("ESC键按下，退出")
                running = False

        elif event.type == pygame.MOUSEBUTTONDOWN:
            print(f"鼠标点击: pos={event.pos}, button={event.button}")
            click_detected = True

        elif event.type == pygame.ACTIVEEVENT:
            print(f"激活事件: gain={event.gain}, state={event.state}")

        elif event.type == pygame.WINDOWFOCUSGAINED:
            print("窗口获得焦点")

        elif event.type == pygame.WINDOWFOCUSLOST:
            print("窗口失去焦点")

    # 如果30秒没有事件，退出
    pygame.time.Clock().tick(60)

pygame.quit()

print("\n" + "="*50)
print("测试总结:")
print(f"按键检测: {'成功' if key_detected else '失败'}")
print(f"点击检测: {'成功' if click_detected else '失败'}")

if not key_detected or not click_detected:
    print("\n⚠ 问题诊断:")
    print("1. 确保点击了窗口区域")
    print("2. 尝试以管理员身份运行")
    print("3. 检查防病毒软件设置")
    print("4. 尝试其他Python环境")

print("测试完成")