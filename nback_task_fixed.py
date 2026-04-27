"""
1-Back 任务 - 数字版 (修复按键检测)
用于测试工作记忆能力
"""

import pygame
import random
import csv
import os
import sys
from datetime import datetime
from config import *

# 初始化Pygame
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("1-Back 任务")
clock = pygame.time.Clock()

def get_font_with_chinese(size):
    """加载支持中文的字体

    优先级:
    1. 用户指定的字体文件路径 (config.FONT_PATH)
    2. 用户指定的系统字体名称 (config.CHINESE_FONT_NAME)
    3. 自动检测常见中文字体
    """
    # 方式1: 使用用户指定的字体文件
    if FONT_PATH and os.path.exists(FONT_PATH):
        try:
            font = pygame.font.Font(FONT_PATH, size)
            print(f"使用指定字体文件: {FONT_PATH}")
            return font
        except Exception as e:
            print(f"无法加载指定字体文件: {e}")

    # 方式2: 使用用户指定的系统字体名称
    if CHINESE_FONT_NAME:
        try:
            font = pygame.font.SysFont(CHINESE_FONT_NAME, size)
            test_surface = font.render("中文", True, (0, 0, 0))
            if test_surface.get_width() > 10:
                print(f"使用系统字体: {CHINESE_FONT_NAME}")
                return font
        except:
            pass

    # 方式3: 自动检测常见中文字体
    chinese_fonts = [
        # Windows
        'simhei', 'simsun', 'microsoftyahei', 'msyh', 'nsimsun',
        'youyuan', 'stsong', 'stheiti', 'stxihei',
        # Linux
        'wqy-zenhei', 'wqy-microhei', 'notosanscjksc', 'notosanscjk',
        'droidsansfallback', 'freesans',
        # Mac
        'pingfang sc', 'heiti sc', 'stheiti', 'hiraginosansgb',
        'yuanti sc', 'yuanyuan sc'
    ]

    for font_name in chinese_fonts:
        try:
            font = pygame.font.SysFont(font_name, size)
            test_surface = font.render("中文", True, (0, 0, 0))
            if test_surface.get_width() > 10:
                print(f"使用字体: {font_name}")
                return font
        except:
            continue

    # 如果没有找到中文字体，使用默认字体（中文会显示为方框）
    print("警告: 未找到中文字体，中文可能显示为方框")
    print("请在 config.py 中设置 FONT_PATH 指向有效的字体文件")
    return pygame.font.Font(None, size)


# 加载字体
font_stimulus = pygame.font.SysFont(None, FONT_SIZE_STIMULUS)  # 刺激用数字，不需要中文
font_instruction = get_font_with_chinese(FONT_SIZE_INSTRUCTION)
font_feedback = pygame.font.SysFont(None, FONT_SIZE_FEEDBACK)  # 反馈用符号，不需要中文

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# 生成日志和文件名
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
data_file = os.path.join(DATA_DIR, f"{FILE_PREFIX}_{timestamp}.csv")
log_file = os.path.join(LOG_DIR, f"log_{timestamp}.txt")


def log_message(msg):
    """记录日志信息"""
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    print(msg)


def show_text(text, color=TEXT_COLOR, font=None, wait_key=None):
    """显示文本，可选等待按键"""
    # 使用支持中文的字体作为默认
    if font is None:
        font = font_instruction

    screen.fill(BACKGROUND_COLOR)
    lines = text.split('\n')
    y_offset = SCREEN_HEIGHT // 2 - (len(lines) * font.get_height() // 2)

    for line in lines:
        text_surface = font.render(line, True, color)
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


def show_fixation(duration):
    """显示注视点"""
    screen.fill(BACKGROUND_COLOR)
    fixation = font_instruction.render("+", True, TEXT_COLOR)
    fixation_rect = fixation.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
    screen.blit(fixation, fixation_rect)
    pygame.display.flip()
    pygame.time.wait(duration)


def draw_stimulus(number):
    """绘制数字刺激到屏幕（不flip）"""
    screen.fill(BACKGROUND_COLOR)
    stim = font_stimulus.render(str(number), True, TEXT_COLOR)
    stim_rect = stim.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
    screen.blit(stim, stim_rect)
    pygame.display.flip()


def show_feedback(is_correct):
    """显示反馈"""
    screen.fill(BACKGROUND_COLOR)
    if is_correct:
        text = "✓"
        color = FEEDBACK_CORRECT_COLOR
    else:
        text = "✗"
        color = FEEDBACK_WRONG_COLOR

    feedback = font_feedback.render(text, True, color)
    feedback_rect = feedback.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
    screen.blit(feedback, feedback_rect)
    pygame.display.flip()
    pygame.time.wait(FEEDBACK_DURATION)


def generate_sequence(n_trials, target_ratio):
    """
    生成刺激序列
    确保：
    1. 第一个试次一定不是目标（无前一个可比较）
    2. 目标比例约为target_ratio
    3. 不会连续出现3个相同数字
    """
    sequence = []
    numbers = list(range(NUMBER_MIN, NUMBER_MAX + 1))

    # 确定哪些试次是目标（从第2个试次开始）
    potential_targets = list(range(1, n_trials))
    n_targets = int((n_trials - 1) * target_ratio)
    target_indices = set(random.sample(potential_targets, n_targets))

    for i in range(n_trials):
        if i == 0:
            # 第一个数字随机
            num = random.choice(numbers)
        elif i in target_indices:
            # 目标试次：与前一个相同
            num = sequence[i - 1]
        else:
            # 非目标：选择一个与之前不同的数字
            available = [n for n in numbers if n != sequence[i - 1]]
            # 避免连续3个相同（如果前两个相同，这次必须不同）
            if i >= 2 and sequence[i - 1] == sequence[i - 2]:
                available = [n for n in available if n != sequence[i - 1]]
            num = random.choice(available)

        sequence.append(num)

    return sequence


def save_data(data_list):
    """保存试次数据到CSV"""
    headers = ['trial_num', 'stimulus', 'prev_stimulus', 'is_target',
               'response', 'response_key', 'correct', 'rt', 'timestamp']

    with open(data_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data_list)

    log_message(f"数据已保存至: {data_file}")


def calculate_stats(data_list):
    """计算统计数据"""
    if not data_list:
        return {}

    # 排除第一个试次（无正确标准）
    valid_trials = [d for d in data_list if d['trial_num'] > 1]
    if not valid_trials:
        return {}

    # 计算正确率
    correct_count = sum(1 for d in valid_trials if d['correct'])
    accuracy = correct_count / len(valid_trials) * 100

    # 反应时统计（仅正确试次）
    rts = [d['rt'] for d in valid_trials if d['rt'] is not None]
    avg_rt = sum(rts) / len(rts) if rts else 0

    # 目标试次统计（漏报）
    target_trials = [d for d in valid_trials if d['is_target']]
    hits = sum(1 for d in target_trials if d['correct'])
    miss_rate = (len(target_trials) - hits) / len(target_trials) * 100 if target_trials else 0

    # 非目标试次统计（虚报）
    non_target_trials = [d for d in valid_trials if not d['is_target']]
    correct_rejections = sum(1 for d in non_target_trials if d['correct'])
    false_alarm_rate = (len(non_target_trials) - correct_rejections) / len(non_target_trials) * 100 if non_target_trials else 0

    return {
        'total_trials': len(valid_trials),
        'accuracy': accuracy,
        'avg_rt': avg_rt,
        'miss_rate': miss_rate,
        'false_alarm_rate': false_alarm_rate
    }


def show_break(completed, total):
    """显示休息界面"""
    text = f"已完成 {completed}/{total} 个试次\n\n请休息片刻\n\n按空格键继续"
    show_text(text, wait_key=pygame.K_SPACE)


def show_results(stats):
    """显示结果统计"""
    text = (
        "实验结束！\n\n"
        f"总试次数: {stats['total_trials']}\n"
        f"正确率: {stats['accuracy']:.1f}%\n"
        f"平均反应时: {stats['avg_rt']:.0f} ms\n"
        f"漏报率: {stats['miss_rate']:.1f}%\n"
        f"虚报率: {stats['false_alarm_rate']:.1f}%\n\n"
        "按任意键退出"
    )
    show_text(text, wait_key=True)


def is_valid_keypress(event, trial_idx, stim_onset):
    """
    检查按键是否有效，并返回响应信息
    返回: (is_valid, response, response_key, rt)
    """
    # 获取键名
    key_name = pygame.key.name(event.key).lower()

    # 检查是否是目标键
    if key_name == KEY_SAME.lower():
        return True, True, KEY_SAME, pygame.time.get_ticks() - stim_onset
    elif key_name == KEY_DIFFERENT.lower():
        return True, False, KEY_DIFFERENT, pygame.time.get_ticks() - stim_onset

    # 检查其他常见表示方式
    elif event.key == pygame.K_f:
        return True, True, 'f', pygame.time.get_ticks() - stim_onset
    elif event.key == pygame.K_j:
        return True, False, 'j', pygame.time.get_ticks() - stim_onset

    # 调试：记录所有按键
    log_message(f"试次 {trial_idx + 1}: 忽略按键 key={event.key}, name='{key_name}', unicode='{event.unicode}'")
    return False, None, None, None


def wait_for_window_focus():
    """等待窗口获得焦点"""
    log_message("等待窗口获得焦点...")

    waiting = True
    focus_gained = False

    while waiting:
        screen.fill(BACKGROUND_COLOR)

        if not focus_gained:
            text_lines = [
                "请点击窗口区域获取焦点",
                "",
                "重要: 必须点击窗口才能记录按键",
                "",
                "点击后按任意键继续"
            ]
        else:
            text_lines = [
                "窗口焦点已获得",
                "",
                "请按任意键开始实验"
            ]

        y_offset = SCREEN_HEIGHT // 2 - (len(text_lines) * font_instruction.get_height() // 2)

        for line in text_lines:
            text = font_instruction.render(line, True, TEXT_COLOR)
            text_rect = text.get_rect(center=(SCREEN_WIDTH // 2, y_offset))
            screen.blit(text, text_rect)
            y_offset += font_instruction.get_height() + 10

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()
                if focus_gained:
                    waiting = False
            elif event.type == pygame.WINDOWFOCUSGAINED:
                log_message("窗口获得焦点")
                focus_gained = True
            elif event.type == pygame.WINDOWFOCUSLOST:
                log_message("窗口失去焦点")
                focus_gained = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                log_message("检测到鼠标点击，假设窗口已获得焦点")
                focus_gained = True

        clock.tick(60)

    log_message("窗口焦点确认完成")


def main():
    """主实验流程"""
    log_message("实验开始")
    log_message(f"配置: {NUM_TRIALS}试次, 目标比例{TARGET_RATIO}")

    # 等待窗口焦点
    wait_for_window_focus()

    # 生成刺激序列
    sequence = generate_sequence(NUM_TRIALS, TARGET_RATIO)
    log_message(f"刺激序列: {sequence}")

    # 数据存储
    data_list = []

    # 显示指导语
    instructions = (
        "1-Back 任务\n\n"
        "屏幕上会依次显示数字\n"
        "请判断当前数字是否与前一个数字相同\n\n"
        f"相同按 [{KEY_SAME.upper()}] 键\n"
        f"不同按 [{KEY_DIFFERENT.upper()}] 键\n\n"
        "请尽量快速准确地反应\n\n"
        "按空格键开始"
    )
    show_text(instructions, wait_key=pygame.K_SPACE)

    # 正式实验
    for trial_idx in range(NUM_TRIALS):
        # 检查是否需要休息
        if trial_idx > 0 and trial_idx % BREAK_INTERVAL == 0:
            show_break(trial_idx, NUM_TRIALS)

        current_num = sequence[trial_idx]
        prev_num = sequence[trial_idx - 1] if trial_idx > 0 else None
        is_target = (current_num == prev_num) if trial_idx > 0 else False

        # 显示注视点
        show_fixation(FIXATION_DURATION)

        # 显示刺激并开始收集反应
        stim_onset = pygame.time.get_ticks()
        draw_stimulus(current_num)

        # 收集反应（刺激呈现期间+ISI期间）
        response_made = False
        response = None
        response_key = None
        rt = None
        isi = random.randint(ISI_MIN, ISI_MAX)
        stimulus_end_time = stim_onset + STIMULUS_DURATION
        response_window_end = stim_onset + STIMULUS_DURATION + isi

        while pygame.time.get_ticks() < response_window_end:
            current_time = pygame.time.get_ticks()

            # 刺激持续期间保持显示数字
            if current_time < stimulus_end_time and not response_made:
                draw_stimulus(current_num)
            elif current_time >= stimulus_end_time and not response_made:
                # ISI期间显示空屏
                screen.fill(BACKGROUND_COLOR)
                pygame.display.flip()

            # 处理事件
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    save_data(data_list)
                    pygame.quit()
                    sys.exit()

                if event.type == pygame.KEYDOWN and not response_made:
                    if event.key == pygame.K_ESCAPE:
                        save_data(data_list)
                        pygame.quit()
                        sys.exit()

                    # 使用新的按键检测逻辑
                    is_valid, resp, resp_key, reaction_time = is_valid_keypress(event, trial_idx, stim_onset)

                    if is_valid:
                        response = resp
                        response_key = resp_key
                        rt = reaction_time
                        response_made = True
                        log_message(f"试次 {trial_idx + 1}: 有效按键 {resp_key}, RT={rt}")

            clock.tick(60)

        # 判断正确性
        if trial_idx == 0:
            # 第一个试次无正确标准，默认正确
            correct = True
        else:
            if response is None:
                correct = False  # 没有反应算错误
            else:
                correct = (response == is_target)

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
            'timestamp': datetime.now().isoformat()
        }
        data_list.append(trial_data)

        log_message(f"试次 {trial_idx + 1}: 数字={current_num}, 目标={is_target}, "
                f"反应={response}, 正确={correct}, RT={rt}")

        # 显示反馈
        show_feedback(correct)

    # 实验结束
    log_message("实验结束")
    save_data(data_list)

    # 显示统计结果
    stats = calculate_stats(data_list)
    show_results(stats)

    pygame.quit()


if __name__ == '__main__':
    main()
