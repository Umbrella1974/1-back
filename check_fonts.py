"""
字体检测工具
帮助用户找到系统中的中文字体
"""

import pygame
import os

def find_chinese_fonts():
    """检测系统中可用的中文字体"""
    pygame.init()

    # 常见中文字体列表
    font_candidates = {
        'Windows': [
            ('simhei', '黑体'),
            ('simsun', '宋体'),
            ('microsoftyahei', '微软雅黑'),
            ('msyh', '微软雅黑(缩写)'),
            ('nsimsun', '新宋体'),
            ('youyuan', '幼圆'),
            ('stsong', '华文宋体'),
            ('stheiti', '华文黑体'),
            ('stxihei', '华文细黑'),
            ('stfangsong', '华文仿宋'),
            ('stkaiti', '华文楷体'),
            ('simkai', '楷体'),
            ('simfang', '仿宋'),
        ],
        'Linux': [
            ('wqy-zenhei', '文泉驿正黑'),
            ('wqy-microhei', '文泉驿微米黑'),
            ('notosanscjksc', 'Noto Sans CJK SC'),
            ('notosanscjk', 'Noto Sans CJK'),
            ('droidsansfallback', 'Droid Sans Fallback'),
            ('freesans', 'FreeSans'),
            ('liberationsans', 'Liberation Sans'),
        ],
        'Mac': [
            ('pingfang sc', '苹方'),
            ('heiti sc', '黑体 SC'),
            ('stheiti', 'STHeiti'),
            ('hiraginosansgb', '冬青黑体'),
            ('yuanti sc', '圆体 SC'),
            ('yuanyuan sc', '圆圆 SC'),
        ]
    }

    print("=" * 50)
    print("系统中文字体检测")
    print("=" * 50)
    print()

    available_fonts = []

    for system, fonts in font_candidates.items():
        print(f"\n【{system} 字体】")
        found_any = False

        for font_name, font_desc in fonts:
            try:
                font = pygame.font.SysFont(font_name, 32)
                # 测试是否能渲染中文
                test_surface = font.render("中文测试", True, (0, 0, 0))
                if test_surface.get_width() > 30:  # 如果能渲染中文，宽度应该足够
                    print(f"  ✓ {font_desc} ({font_name})")
                    available_fonts.append((font_name, font_desc, system))
                    found_any = True
                else:
                    print(f"  ✗ {font_desc} ({font_name}) - 无法渲染中文")
            except Exception as e:
                print(f"  ✗ {font_desc} ({font_name}) - 不可用")

        if not found_any:
            print("  未找到可用字体")

    print()
    print("=" * 50)
    print("推荐的配置（复制到 config.py）")
    print("=" * 50)

    if available_fonts:
        # 推荐第一个找到的字体
        font_name, font_desc, system = available_fonts[0]
        print(f"""
# 在 config.py 中添加:
CHINESE_FONT_NAME = "{font_name}"  # {font_desc} ({system})
""")

        # 显示Windows字体文件路径
        if system == 'Windows':
            font_files = {
                'simhei': 'C:/Windows/Fonts/simhei.ttf',
                'simsun': 'C:/Windows/Fonts/simsun.ttc',
                'microsoftyahei': 'C:/Windows/Fonts/msyh.ttc',
                'msyh': 'C:/Windows/Fonts/msyh.ttc',
                'nsimsun': 'C:/Windows/Fonts/nsimsun.ttc',
            }
            if font_name.lower() in font_files:
                print(f"或使用字体文件路径:")
                print(f"FONT_PATH = \"{font_files[font_name.lower()]}\"")
    else:
        print("""
未找到任何中文字体！请尝试:
1. 安装中文字体（如思源黑体）
2. 手动设置 FONT_PATH 指向字体文件
""")

    # 列出所有系统字体（可选）
    print()
    print("=" * 50)
    print("系统所有字体名称（供参考）")
    print("=" * 50)
    all_fonts = pygame.font.get_fonts()
    chinese_like = [f for f in all_fonts if any(keyword in f.lower() for keyword in
                    ['chinese', 'hei', 'song', 'kai', 'fang', 'ming', 'yuan',
                     'noto', 'cjk', 'wqy', 'droid', 'simsun', 'simhei'])]

    if chinese_like:
        print("可能的中文字体关键字:")
        for font in sorted(chinese_like)[:20]:  # 只显示前20个
            print(f"  - {font}")

if __name__ == '__main__':
    find_chinese_fonts()
