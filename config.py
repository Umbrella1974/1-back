# 1-Back 任务配置文件

# 实验参数
NUM_TRIALS = 50              # 总试次数
TARGET_RATIO = 0.3           # 目标试次比例（当前数字与前一个相同）
BREAK_INTERVAL = 20          # 每N个试次后休息

# 刺激参数
STIMULUS_DURATION = 500      # 数字显示时长（毫秒）
ISI_MIN = 1000               # 刺激间间隔最小值（毫秒）
ISI_MAX = 1500               # 刺激间间隔最大值（毫秒）
FIXATION_DURATION = 500      # 注视点显示时长（毫秒）
FEEDBACK_DURATION = 500      # 反馈显示时长（毫秒）

# 数字范围
NUMBER_MIN = 0               # 最小数字
NUMBER_MAX = 9               # 最大数字

# 按键设置
# 使用左右箭头键（经过测试可用）
KEY_SAME = 'left'               # 相同按键（左箭头）
KEY_DIFFERENT = 'right'         # 不同按键（右箭头）

# 备选方案（如果左右箭头不可用）：
# KEY_SAME = 'a'              # A键
# KEY_DIFFERENT = 'd'         # D键
# KEY_SAME = '1'              # 数字1
# KEY_DIFFERENT = '2'         # 数字2

# 其他功能键
KEY_QUIT = 'escape'          # 退出按键（ESC键）
KEY_CONTINUE = 'k_space'       # 继续按键（空格键）

# 屏幕设置
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
BACKGROUND_COLOR = (200, 200, 200)
TEXT_COLOR = (0, 0, 0)
FEEDBACK_CORRECT_COLOR = (0, 200, 0)
FEEDBACK_WRONG_COLOR = (200, 0, 0)

# 字体设置
FONT_SIZE_STIMULUS = 120
FONT_SIZE_INSTRUCTION = 32
FONT_SIZE_FEEDBACK = 48

# 中文字体配置
# 方式1: 指定字体文件路径（最可靠，推荐Windows用户使用）
# Windows字体通常在 C:/Windows/Fonts/ 目录下：
#   - 黑体: C:/Windows/Fonts/simhei.ttf
#   - 宋体: C:/Windows/Fonts/simsun.ttc
#   - 微软雅黑: C:/Windows/Fonts/msyh.ttc
FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"

# 方式2: 指定系统字体名称（如果方式1为None或文件不存在）
# Windows常见: "simhei"(黑体), "simsun"(宋体), "microsoftyahei"(微软雅黑)
# Linux常见: "wqy-zenhei", "wqy-microhei", "Noto Sans CJK SC"
# Mac常见: "PingFang SC", "Heiti SC", "STHeiti"
CHINESE_FONT_NAME = "simhei"

# 提示: 运行 check_fonts.py 可以检测系统中可用的中文字体

# 数据存储
DATA_DIR = 'data'
LOG_DIR = 'logs'
FILE_PREFIX = '1back_data'
