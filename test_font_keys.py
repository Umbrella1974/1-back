"""
字体和按键综合测试
"""
import pygame
import sys
import os

print("=== 字体和按键综合测试 ===")
print(f"Python版本: {sys.version}")
print(f"Pygame版本: {pygame.__version__}")

# 初始化
pygame.init()

# 检查字体文件
FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"
print(f"\n检查字体文件: {FONT_PATH}")
if os.path.exists(FONT_PATH):
    print("✓ 字体文件存在")
    file_size = os.path.getsize(FONT_PATH)
    print(f"  文件大小: {file_size/1024/1024:.2f} MB")
else:
    print("✗ 字体文件不存在")
    # 尝试其他字体
    alt_fonts = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\msyh.ttc"
    ]
    for font_path in alt_fonts:
        if os.path.exists(font_path):
            print(f"✓ 找到备选字体: {font_path}")
            FONT_PATH = font_path
            break

# 创建窗口
screen = pygame.display.set_mode((800, 600))
pygame.display.set_caption("字体和按键测试 - 按F/J测试，ESC退出")
clock = pygame.time.Clock()

# 尝试加载字体
fonts = {}
font_loaded = False

print("\n尝试加载字体:")
try:
    # 方法1: 使用字体文件
    fonts['file'] = pygame.font.Font(FONT_PATH, 32)
    print("✓ 方法1: pygame.font.Font() 成功")
    font_loaded = True
except Exception as e:
    print(f"✗ 方法1失败: {e}")

try:
    # 方法2: 使用系统字体名
    fonts['sys'] = pygame.font.SysFont('simhei', 32)
    print("✓ 方法2: pygame.font.SysFont('simhei') 成功")
    font_loaded = True
except Exception as e:
    print(f"✗ 方法2失败: {e}")

try:
    # 方法3: 使用微软雅黑
    fonts['yahei'] = pygame.font.SysFont('microsoftyahei', 32)
    print("✓ 方法3: pygame.font.SysFont('microsoftyahei') 成功")
    font_loaded = True
except Exception as e:
    print(f"✗ 方法3失败: {e}")

try:
    # 方法4: 默认字体
    fonts['default'] = pygame.font.Font(None, 32)
    print("✓ 方法4: pygame.font.Font(None) 成功")
    font_loaded = True
except Exception as e:
    print(f"✗ 方法4失败: {e}")

if not font_loaded:
    print("⚠ 所有字体加载方法都失败!")
    sys.exit(1)

# 测试渲染中文
print("\n测试渲染中文文本:")
test_texts = ["中文测试", "1-Back 任务", "按F键:相同", "按J键:不同"]
rendered = {}

for name, font in fonts.items():
    rendered[name] = {}
    for text in test_texts:
        try:
            surface = font.render(text, True, (0, 0, 0))
            width = surface.get_width()
            height = surface.get_height()
            rendered[name][text] = (width, height)
            print(f"  {name:8} '{text}': {width}x{height}")
        except Exception as e:
            rendered[name][text] = None
            print(f"  {name:8} '{text}': 渲染失败 - {e}")

print("\n" + "="*60)
print("测试说明:")
print("1. 点击窗口获取焦点")
print("2. 按 F 键 (应该显示'相同')")
print("3. 按 J 键 (应该显示'不同')")
print("4. 按 ESC 键退出")
print("5. 观察中文是否正常显示")
print("="*60)

# 主循环
running = True
last_key = None
key_history = []
font_index = 0
font_names = list(fonts.keys())

while running:
    screen.fill((240, 240, 240))

    # 当前字体
    current_font_name = font_names[font_index]
    current_font = fonts[current_font_name]

    # 显示标题
    title = current_font.render(f"字体测试: {current_font_name}", True, (0, 0, 128))
    screen.blit(title, (20, 20))

    # 显示中文测试
    y_pos = 70
    for text in test_texts:
        try:
            text_surface = current_font.render(text, True, (0, 0, 0))
            screen.blit(text_surface, (20, y_pos))
        except:
            error_text = fonts['default'].render(f"渲染失败: {text}", True, (255, 0, 0))
            screen.blit(error_text, (20, y_pos))
        y_pos += 40

    # 显示按键信息
    y_pos = 250
    key_info = current_font.render(f"最后按键: {last_key}", True, (0, 100, 0))
    screen.blit(key_info, (20, y_pos))
    y_pos += 40

    key_history_text = current_font.render(f"按键历史: {len(key_history)} 次", True, (0, 100, 0))
    screen.blit(key_history_text, (20, y_pos))
    y_pos += 40

    # 显示操作说明
    instructions = [
        "操作:",
        "1. 点击窗口获取焦点",
        "2. 按 F 键 (相同)",
        "3. 按 J 键 (不同)",
        "4. 按 ESC 键退出",
        "5. 按 空格键 切换字体",
        "",
        f"当前字体: {current_font_name}"
    ]

    for i, line in enumerate(instructions):
        text_surface = current_font.render(line, True, (100, 50, 0))
        screen.blit(text_surface, (400, 20 + i * 35))

    # 显示按键历史（最后10次）
    y_pos = 350
    history_title = current_font.render("最近按键:", True, (0, 0, 128))
    screen.blit(history_title, (20, y_pos))
    y_pos += 40

    for i, (key_name, key_code) in enumerate(reversed(key_history[-5:])):
        text = f"{key_name} (码={key_code})"
        text_surface = current_font.render(text, True, (50, 50, 150))
        screen.blit(text_surface, (20, y_pos))
        y_pos += 30

    pygame.display.flip()

    # 事件处理
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN:
            key_name = pygame.key.name(event.key)
            key_unicode = event.unicode if event.unicode else 'None'
            last_key = f"{key_name} (码={event.key}, unicode='{key_unicode}')"
            key_history.append((key_name, event.key))

            print(f"按键: {key_name} (码={event.key}, unicode='{key_unicode}')")

            # 特殊按键处理
            if event.key == pygame.K_ESCAPE:
                print("ESC键，退出...")
                running = False
            elif event.key == pygame.K_f:
                print("F键 - 应该表示'相同'")
            elif event.key == pygame.K_j:
                print("J键 - 应该表示'不同'")
            elif event.key == pygame.K_SPACE:
                font_index = (font_index + 1) % len(font_names)
                print(f"切换字体到: {font_names[font_index]}")

        elif event.type == pygame.MOUSEBUTTONDOWN:
            print(f"鼠标点击: pos={event.pos}, button={event.button}")

        elif event.type == pygame.WINDOWFOCUSGAINED:
            print("窗口获得焦点")

        elif event.type == pygame.WINDOWFOCUSLOST:
            print("窗口失去焦点")

    clock.tick(60)

pygame.quit()

print("\n" + "="*60)
print("测试总结:")
print(f"字体加载: {'成功' if font_loaded else '失败'}")
print(f"总按键次数: {len(key_history)}")
print(f"F键检测: {'✓' if any(k[0]=='f' for k in key_history) else '✗'}")
print(f"J键检测: {'✓' if any(k[0]=='j' for k in key_history) else '✗'}")

if key_history:
    print("\n按键详情:")
    for key_name, key_code in key_history:
        print(f"  {key_name} (码={key_code})")

print("\n测试完成")