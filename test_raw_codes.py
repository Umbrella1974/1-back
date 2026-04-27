"""
原始键码测试 - 只打印不显示窗口
"""
import pygame
import sys

print("=== 原始键码测试 ===")
print("按 F 和 J 键查看输出")
print("按 ESC 键退出")
print("="*50)

pygame.init()

# 创建最小窗口
screen = pygame.display.set_mode((200, 100))
pygame.display.set_caption("按F/J键测试")

print("\n开始检测按键...")
print("按下按键时，将显示:")
print("  key: 键码 (整数)")
print("  pygame.key.name(key): 键名")
print("  unicode: Unicode字符")
print("-"*50)

# 已知键码
known_keys = {
    27: "ESC",
    32: "SPACE",
    102: "F",
    106: "J",
    97: "A", 98: "B", 99: "C", 100: "D", 101: "E", 102: "F",
    103: "G", 104: "H", 105: "I", 106: "J", 107: "K", 108: "L",
    109: "M", 110: "N", 111: "O", 112: "P", 113: "Q", 114: "R",
    115: "S", 116: "T", 117: "U", 118: "V", 119: "W", 120: "X",
    121: "Y", 122: "Z",
}

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN:
            key_code = event.key
            key_unicode = event.unicode if event.unicode else ""

            try:
                key_name = pygame.key.name(key_code)
            except:
                key_name = "未知"

            # 显示信息
            print(f"\n按键检测:")
            print(f"  键码: {key_code}")
            print(f"  键名: '{key_name}'")
            print(f"  unicode: '{key_unicode}'")

            # 检查是否是已知键
            if key_code in known_keys:
                print(f"  对应字母: {known_keys[key_code]}")

            # 检查是否是F或J
            if key_name.lower() == 'f':
                print("  → 这是F键!")
            elif key_name.lower() == 'j':
                print("  → 这是J键!")
            elif key_code == 102:
                print("  → 键码102 (应该是F键)")
            elif key_code == 106:
                print("  → 键码106 (应该是J键)")

            # ESC键退出
            if key_code == 27:
                print("\nESC键按下，退出...")
                running = False

    pygame.display.flip()

pygame.quit()

print("\n" + "="*50)
print("测试完成")
print("请将上面的输出截图或复制给我")