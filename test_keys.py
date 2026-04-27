"""
测试pygame按键检测
"""
import pygame

pygame.init()

# 测试键码转换
KEY_SAME = 'f'
KEY_DIFFERENT = 'j'

print("测试键码转换:")
print(f"getattr(pygame, 'K_{KEY_SAME}'): {getattr(pygame, f'K_{KEY_SAME}', 'NOT FOUND')}")
print(f"getattr(pygame, 'K_{KEY_DIFFERENT}'): {getattr(pygame, f'K_{KEY_DIFFERENT}', 'NOT FOUND')}")

# 列出所有K_开头的常量
print("\n所有K_开头的常量 (前20个):")
key_constants = [attr for attr in dir(pygame) if attr.startswith('K_')]
for i, const in enumerate(sorted(key_constants)[:20]):
    print(f"  {const}: {getattr(pygame, const)}")

print("\n完整键盘映射:")
# 常用键
common_keys = {
    'K_f': 'f键',
    'K_j': 'j键',
    'K_SPACE': '空格键',
    'K_ESCAPE': 'ESC键',
    'K_RETURN': '回车键',
    'K_LEFT': '左箭头',
    'K_RIGHT': '右箭头',
    'K_UP': '上箭头',
    'K_DOWN': '下箭头',
    'K_a': 'a键',
    'K_b': 'b键',
    'K_c': 'c键',
    'K_d': 'd键',
    'K_e': 'e键',
    'K_g': 'g键',
    'K_h': 'h键',
    'K_i': 'i键',
    'K_k': 'k键',
    'K_l': 'l键',
    'K_m': 'm键',
    'K_n': 'n键',
    'K_o': 'o键',
    'K_p': 'p键',
    'K_q': 'q键',
    'K_r': 'r键',
    'K_s': 's键',
    'K_t': 't键',
    'K_u': 'u键',
    'K_v': 'v键',
    'K_w': 'w键',
    'K_x': 'x键',
    'K_y': 'y键',
    'K_z': 'z键',
}

for py_const, desc in common_keys.items():
    if hasattr(pygame, py_const):
        print(f"  {desc}: {py_const}")

# 测试按键检测
screen = pygame.display.set_mode((200, 200))
pygame.display.set_caption("按键测试")
clock = pygame.time.Clock()

print("\n按任意键测试 (按ESC退出)...")
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            print(f"按键: key={event.key}, unicode={event.unicode}")

            # 检查是否是F或J键
            if event.key == getattr(pygame, 'K_f', None):
                print("  -> 这是F键 (相同)")
            elif event.key == getattr(pygame, 'K_j', None):
                print("  -> 这是J键 (不同)")
            elif event.key == pygame.K_ESCAPE:
                running = False

    pygame.display.flip()
    clock.tick(60)

pygame.quit()