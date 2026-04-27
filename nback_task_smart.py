"""
1-Back 任务 - 智能按键版
自动检测可用的按键或让用户选择
"""

import pygame
import random
import csv
import os
import sys
from datetime import datetime
from config import *

print("=== 1-Back 任务 (智能按键版) ===")
print(f"Python版本: {sys.version}")
print(f"Pygame版本: {pygame.__version__}")

# 初始化Pygame
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("1-Back 任务 - 按键配置")
clock = pygame.time.Clock()

# ========== 字体加载 ==========
def load_font_safe(size, is_chinese=False):
    """安全加载字体函数"""
    if not is_chinese:
        try:
            return pygame.font.Font(None, size)
        except:
            return pygame.font.SysFont(None, size)

    # 需要中文
    if FONT_PATH and os.path.exists(FONT_PATH):
        try:
            font = pygame.font.Font(FONT_PATH, size)
            test_surface = font.render("中文", True, (0, 0, 0))
            if test_surface.get_width() > 10:
                return font
        except:
            pass

    # 尝试常见字体
    font_names = ['simhei', 'microsoftyahei', 'simsun', 'msyh', 'nsimsun']
    for name in font_names:
        try:
            font = pygame.font.SysFont(name, size)
            test_surface = font.render("中文", True, (0, 0, 0))
            if test_surface.get_width() > 10:
                return font
        except:
            continue

    # 默认字体
    return pygame.font.Font(None, size)

# 加载字体
font_stimulus = load_font_safe(FONT_SIZE_STIMULUS, is_chinese=False)
font_instruction = load_font_safe(FONT_SIZE_INSTRUCTION, is_chinese=True)
font_feedback = load_font_safe(FONT_SIZE_FEEDBACK, is_chinese=False)

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# 生成文件名
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
data_file = os.path.join(DATA_DIR, f"{FILE_PREFIX}_{timestamp}.csv")
log_file = os.path.join(LOG_DIR, f"log_{timestamp}.txt")


def log_message(msg):
    """记录日志信息"""
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    print(msg)


def show_text(text, color=TEXT_COLOR, font=None, wait_key=None):
    """显示文本"""
    if font is None:
        font = font_instruction

    screen.fill(BACKGROUND_COLOR)
    lines = text.split('\n')
    y_offset = SCREEN_HEIGHT // 2 - (len(lines) * font.get_height() // 2)

    for line in lines:
        try:
            text_surface = font.render(line, True, color)
            text_rect = text_surface.get_rect(center=(SCREEN_WIDTH // 2, y_offset))
            screen.blit(text_surface, text_rect)
        except:
            fallback = pygame.font.Font(None, FONT_SIZE_INSTRUCTION)
            text_surface = fallback.render(line, True, color)
            text_rect = text_surface.get_rect(center=(SCREEN_WIDTH // 2, y_offset))
            screen.blit(text_surface, text_rect)

        y_offset += font.get_height() + 10

    pygame.display.flip()

    if wait_key:
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit()
                    if wait_key == True or event.key == wait_key:
                        waiting = False


def detect_available_keys():
    """
    检测可用的按键
    返回: (same_key, diff_key) - 可用的按键配置
    """
    print("\n=== 按键检测 ===")
    print("请按以下键测试:")
    print("1. 首先按您想用于'相同'的键")
    print("2. 然后按您想用于'不同'的键")
    print("3. 按ESC跳过使用默认设置")

    screen.fill(BACKGROUND_COLOR)
    text_lines = [
        "按键配置",
        "",
        "请按两个不同的键来设置:",
        "",
        "1. 按第一个键用于'相同'",
        "2. 按第二个键用于'不同'",
        "",
        "按ESC键使用默认设置(F/J键)"
    ]

    y_offset = SCREEN_HEIGHT // 2 - (len(text_lines) * font_instruction.get_height() // 2)
    for line in text_lines:
        text = font_instruction.render(line, True, TEXT_COLOR)
        text_rect = text.get_rect(center=(SCREEN_WIDTH // 2, y_offset))
        screen.blit(text, text_rect)
        y_offset += font_instruction.get_height() + 10

    pygame.display.flip()

    # 等待按键
    keys_detected = []
    key_names = []
    waiting = True

    while waiting and len(keys_detected) < 2:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.KEYDOWN:
                key_code = event.key

                if key_code == pygame.K_ESCAPE:
                    print("使用默认按键设置")
                    return 'f', 'j'  # 默认值

                try:
                    key_name = pygame.key.name(key_code)
                except:
                    key_name = f"key_{key_code}"

                # 避免重复按键
                if key_code not in keys_detected:
                    keys_detected.append(key_code)
                    key_names.append(key_name)

                    print(f"检测到按键 {len(keys_detected)}: '{key_name}' (码={key_code})")

                    # 更新显示
                    screen.fill(BACKGROUND_COLOR)
                    status_lines = [
                        "按键配置",
                        "",
                        f"按键 {len(keys_detected)}/2 已设置:",
                        "",
                        f"键1 ('相同'): {key_names[0] if len(key_names) > 0 else '未设置'}",
                        f"键2 ('不同'): {key_names[1] if len(key_names) > 1 else '未设置'}",
                        "",
                        "继续按第二个键..." if len(keys_detected) == 1 else "按任意键确认"
                    ]

                    y_offset = SCREEN_HEIGHT // 2 - (len(status_lines) * font_instruction.get_height() // 2)
                    for line in status_lines:
                        text = font_instruction.render(line, True, TEXT_COLOR)
                        text_rect = text.get_rect(center=(SCREEN_WIDTH // 2, y_offset))
                        screen.blit(text, text_rect)
                        y_offset += font_instruction.get_height() + 10

                    pygame.display.flip()

        clock.tick(60)

    if len(keys_detected) >= 2:
        print(f"按键配置完成: '{key_names[0]}'=相同, '{key_names[1]}'=不同")
        return key_names[0], key_names[1]
    else:
        print("使用默认按键设置")
        return 'f', 'j'


def check_key_event(event, same_key_name, diff_key_name, stim_onset):
    """
    检查按键事件
    same_key_name: '相同'键的名称
    diff_key_name: '不同'键的名称
    """
    if event.type != pygame.KEYDOWN:
        return False, None, None, None

    key_code = event.key

    try:
        key_name = pygame.key.name(key_code)
    except:
        key_name = f"key_{key_code}"

    # 调试信息
    log_message(f"按键检测: '{key_name}' (码={key_code})")

    # 检查是否匹配
    if key_name.lower() == same_key_name.lower():
        rt = pygame.time.get_ticks() - stim_onset
        return True, True, same_key_name, rt
    elif key_name.lower() == diff_key_name.lower():
        rt = pygame.time.get_ticks() - stim_onset
        return True, False, diff_key_name, rt

    # 检查常见键码（备用）
    key_map = {
        'f': pygame.K_f,
        'j': pygame.K_j,
        'left': pygame.K_LEFT,
        'right': pygame.K_RIGHT,
        'a': pygame.K_a,
        'd': pygame.K_d,
    }

    # 检查same_key
    if same_key_name.lower() in key_map and key_code == key_map[same_key_name.lower()]:
        rt = pygame.time.get_ticks() - stim_onset
        return True, True, same_key_name, rt

    # 检查diff_key
    if diff_key_name.lower() in key_map and key_code == key_map[diff_key_name.lower()]:
        rt = pygame.time.get_ticks() - stim_onset
        return True, False, diff_key_name, rt

    return False, None, None, None


def run_experiment(same_key, diff_key):
    """运行主实验"""
    log_message(f"实验开始 - 按键: '{same_key}'=相同, '{diff_key}'=不同")

    # 生成刺激序列
    sequence = []
    numbers = list(range(NUMBER_MIN, NUMBER_MAX + 1))
    potential_targets = list(range(1, NUM_TRIALS))
    n_targets = int((NUM_TRIALS - 1) * TARGET_RATIO)
    target_indices = set(random.sample(potential_targets, n_targets))

    for i in range(NUM_TRIALS):
        if i == 0:
            sequence.append(random.choice(numbers))
        elif i in target_indices:
            sequence.append(sequence[i - 1])
        else:
            available = [n for n in numbers if n != sequence[i - 1]]
            if i >= 2 and sequence[i - 1] == sequence[i - 2]:
                available = [n for n in available if n != sequence[i - 1]]
            sequence.append(random.choice(available))

    log_message(f"刺激序列: {sequence[:20]}..." if len(sequence) > 20 else f"刺激序列: {sequence}")

    # 数据存储
    data_list = []

    # 显示指导语
    instructions = (
        "1-Back 任务\n\n"
        "屏幕上会依次显示数字\n"
        "请判断当前数字是否与前一个数字相同\n\n"
        f"相同按 [{same_key.upper()}] 键\n"
        f"不同按 [{diff_key.upper()}] 键\n\n"
        "请尽量快速准确地反应\n\n"
        "按空格键开始"
    )
    show_text(instructions, wait_key=pygame.K_SPACE)

    # 正式实验
    for trial_idx in range(NUM_TRIALS):
        # 休息
        if trial_idx > 0 and trial_idx % BREAK_INTERVAL == 0:
            show_text(f"已完成 {trial_idx}/{NUM_TRIALS} 个试次\n\n请休息片刻\n\n按空格键继续",
                     wait_key=pygame.K_SPACE)

        current_num = sequence[trial_idx]
        prev_num = sequence[trial_idx - 1] if trial_idx > 0 else None
        is_target = (current_num == prev_num) if trial_idx > 0 else False

        # 注视点
        screen.fill(BACKGROUND_COLOR)
        fixation = font_instruction.render("+", True, TEXT_COLOR)
        fixation_rect = fixation.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
        screen.blit(fixation, fixation_rect)
        pygame.display.flip()
        pygame.time.wait(FIXATION_DURATION)

        # 显示刺激
        stim_onset = pygame.time.get_ticks()
        screen.fill(BACKGROUND_COLOR)
        stim = font_stimulus.render(str(current_num), True, TEXT_COLOR)
        stim_rect = stim.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
        screen.blit(stim, stim_rect)
        pygame.display.flip()

        # 收集反应
        response_made = False
        response = None
        response_key = None
        rt = None
        isi = random.randint(ISI_MIN, ISI_MAX)
        stimulus_end_time = stim_onset + STIMULUS_DURATION
        response_window_end = stim_onset + STIMULUS_DURATION + isi

        while pygame.time.get_ticks() < response_window_end:
            current_time = pygame.time.get_ticks()

            # 保持显示
            if current_time < stimulus_end_time and not response_made:
                screen.fill(BACKGROUND_COLOR)
                screen.blit(stim, stim_rect)
                pygame.display.flip()
            elif current_time >= stimulus_end_time and not response_made:
                screen.fill(BACKGROUND_COLOR)
                pygame.display.flip()

            # 事件处理
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    save_data(data_list, same_key, diff_key)
                    pygame.quit()
                    sys.exit()

                if event.type == pygame.KEYDOWN and not response_made:
                    if event.key == pygame.K_ESCAPE:
                        save_data(data_list, same_key, diff_key)
                        pygame.quit()
                        sys.exit()

                    is_valid, resp, resp_key, reaction_time = check_key_event(
                        event, same_key, diff_key, stim_onset)

                    if is_valid:
                        response = resp
                        response_key = resp_key
                        rt = reaction_time
                        response_made = True
                        log_message(f"试次 {trial_idx + 1}: 有效按键 '{resp_key}', RT={rt}")

            clock.tick(60)

        # 判断正确性
        if trial_idx == 0:
            correct = True
        else:
            correct = (response == is_target) if response is not None else False

        # 记录数据
        trial_data = {
            'trial_num': trial_idx + 1,
            'stimulus': current_num,
            'prev_stimulus': prev_num if prev_num is not None else 'N/A',
            'is_target': is_target,
            'response': response if response is not None else 'N/A',
            'response_key': response_key if response_key else 'N/A',
            'correct': correct,
            'rt': rt,
            'timestamp': datetime.now().isoformat(),
            'same_key': same_key,
            'diff_key': diff_key
        }
        data_list.append(trial_data)

        # 反馈
        screen.fill(BACKGROUND_COLOR)
        feedback_text = "✓" if correct else "✗"
        feedback_color = (0, 200, 0) if correct else (200, 0, 0)
        feedback = font_feedback.render(feedback_text, True, feedback_color)
        feedback_rect = feedback.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
        screen.blit(feedback, feedback_rect)
        pygame.display.flip()
        pygame.time.wait(FEEDBACK_DURATION)

    # 结束
    log_message("实验结束")
    save_data(data_list, same_key, diff_key)

    # 显示结果
    show_text("实验结束！\n\n按任意键退出", wait_key=True)


def save_data(data_list, same_key, diff_key):
    """保存数据"""
    headers = ['trial_num', 'stimulus', 'prev_stimulus', 'is_target',
               'response', 'response_key', 'correct', 'rt', 'timestamp',
               'same_key', 'diff_key']

    with open(data_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data_list)

    log_message(f"数据已保存至: {data_file}")


def main():
    """主程序"""
    log_message("=" * 60)
    log_message("1-Back 任务启动")
    log_message("=" * 60)

    # 等待焦点
    show_text("请点击窗口获取焦点\n\n然后按任意键继续", wait_key=True)

    # 检测按键
    same_key, diff_key = detect_available_keys()

    # 确认按键
    confirm_text = (
        f"按键配置确认:\n\n"
        f"相同: [{same_key.upper()}]\n"
        f"不同: [{diff_key.upper()}]\n\n"
        f"按空格键开始实验\n"
        f"按R键重新配置"
    )

    confirming = True
    while confirming:
        show_text(confirm_text, wait_key=None)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()
                elif event.key == pygame.K_SPACE:
                    confirming = False
                elif event.key == pygame.K_r:
                    same_key, diff_key = detect_available_keys()
                    confirm_text = (
                        f"按键配置确认:\n\n"
                        f"相同: [{same_key.upper()}]\n"
                        f"不同: [{diff_key.upper()}]\n\n"
                        f"按空格键开始实验\n"
                        f"按R键重新配置"
                    )

        clock.tick(60)

    # 运行实验
    run_experiment(same_key, diff_key)

    pygame.quit()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log_message(f"程序异常: {e}")
        import traceback
        traceback.print_exc()
        pygame.quit()
        sys.exit(1)