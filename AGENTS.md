# 1-Back 认知心理学任务

## 项目概述

这是一个用 Python 和 Pygame 实现的 1-Back 认知心理学任务。1-Back 是一种工作记忆测试，要求被试判断当前呈现的数字是否与前一个数字相同。

**核心功能：**
- 视觉呈现数字刺激 (0-9)
- 被试按键判断"相同"或"不同"
- 记录反应时间、正确率等数据
- 实时反馈（正确/错误符号）
- 定时休息界面
- 中文显示支持

## 文件说明

### 主要程序文件
- `nback_task_final.py` - **主程序**（最终修复版，推荐使用）
- `nback_task_smart.py` - 智能按键版（自动检测可用按键）
- `nback_task.py` - 原始版本
- `nback_task_fixed.py` - 修复版本

### 配置文件
- `config.py` - 所有实验参数设置

### 测试工具
- `test_raw_codes.py` - 原始键码测试
- `debug_keys_raw.py` - 详细按键调试
- `test_simple_keys.py` - 简单按键测试
- `test_font_keys.py` - 字体和按键综合测试
- `check_fonts.py` - 中文字体检测工具
- `test_minimal.py` - 最小测试程序
- `test_detailed_keys.py` - 详细按键测试
- `test_keys.py` - 按键测试

### 支持文件
- `SOLUTION.md` - 按键问题解决方案
- `data/` - 数据存储目录（自动创建）
- `logs/` - 日志文件目录（自动创建）

## 快速开始

### 1. 安装依赖
```bash
pip install pygame
```

### 2. 运行主程序
```bash
python nback_task_final.py
```

### 3. 按键说明
- **左箭头（←）**：相同
- **右箭头（→）**：不同
- **ESC**：退出程序
- **空格**：继续/开始

## 详细配置

### 修改配置文件 (`config.py`)

#### 实验参数
```python
NUM_TRIALS = 50              # 总试次数
TARGET_RATIO = 0.3           # 目标试次比例（当前数字与前一个相同）
BREAK_INTERVAL = 20          # 每20个试次后休息
```

#### 刺激参数
```python
STIMULUS_DURATION = 500      # 数字显示时长（毫秒）
ISI_MIN = 1000               # 刺激间间隔最小值（毫秒）
ISI_MAX = 1500               # 刺激间间隔最大值（毫秒）
FIXATION_DURATION = 500      # 注视点显示时长（毫秒）
FEEDBACK_DURATION = 500      # 反馈显示时长（毫秒）
```

#### 按键设置（可修改）
```python
# 默认使用左右箭头键
KEY_SAME = 'left'            # 相同按键（左箭头）
KEY_DIFFERENT = 'right'      # 不同按键（右箭头）

# 备选方案：
# KEY_SAME = 'a'             # A键
# KEY_DIFFERENT = 'd'        # D键
# KEY_SAME = '1'             # 数字1
# KEY_DIFFERENT = '2'        # 数字2
```

#### 中文字体配置
```python
# 方式1: 指定字体文件路径（推荐）
FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"  # 黑体

# 方式2: 指定系统字体名称
CHINESE_FONT_NAME = "simhei"  # 黑体
```

## 运行程序

### 标准版（推荐）
```bash
python nback_task_final.py
```

### 智能按键版
如果遇到按键检测问题，使用智能版：
```bash
python nback_task_smart.py
```
此版本会引导你选择两个可用的按键。

### 测试工具
```bash
# 测试中文字体
python check_fonts.py

# 测试原始键码
python test_raw_codes.py

# 详细按键调试
python debug_keys_raw.py
```

## 数据管理

### 数据文件
程序运行后会在 `data/` 目录下生成 CSV 文件：
```
data/
├── 1back_data_YYYYMMDD_HHMMSS.csv
└── ...
```

### 数据字段
CSV 文件包含以下字段：
- `trial_num` - 试次编号
- `stimulus` - 当前数字
- `prev_stimulus` - 前一个数字
- `is_target` - 是否是目标试次
- `response` - 被试反应 (True=相同, False=不同, 'N/A'=无反应)
- `response_key` - 实际按下的键
- `correct` - 是否正确
- `rt` - 反应时间（毫秒）
- `timestamp` - 时间戳

### 日志文件
程序在 `logs/` 目录下生成详细的日志文件，记录运行过程和调试信息。

## 故障排除

### 常见问题

#### 1. 汉字显示为方框
**解决方法：**
1. 运行字体检测工具：
   ```bash
   python check_fonts.py
   ```
2. 根据输出结果修改 `config.py` 中的 `FONT_PATH` 或 `CHINESE_FONT_NAME`

#### 2. 按键无法检测
**解决方法：**
1. 运行原始键码测试：
   ```bash
   python test_raw_codes.py
   ```
2. 查看按 F/J 键时显示的键码和键名
3. 根据测试结果修改 `config.py` 中的按键设置
4. 或使用智能按键版程序

#### 3. 反应时未被记录
**原因：** 可能是窗口焦点问题
**解决方法：**
1. 运行程序时点击窗口区域确保焦点
2. 程序有自动焦点检测功能

### 测试工具说明

1. **`test_raw_codes.py`** - 显示所有按键的原始键码和键名
2. **`debug_keys_raw.py`** - 详细调试工具，显示所有按键信息
3. **`check_fonts.py`** - 检测系统中可用的中文字体
4. **`test_font_keys.py`** - 同时测试字体渲染和按键检测

## 程序流程

1. **启动程序** - 显示版本信息和字体加载状态
2. **窗口焦点检测** - 等待用户点击窗口获取焦点
3. **指导语** - 显示任务说明，按空格键开始
4. **正式实验** - 呈现数字序列
   - 注视点 (+) 显示 500ms
   - 数字刺激显示 500ms
   - 刺激间间隔 1000-1500ms
   - 反馈符号（✓/✗）显示 500ms
5. **休息界面** - 每 20 个试次后显示休息界面
6. **结果统计** - 显示正确率、平均反应时等统计信息

## 实验设计特点

### 刺激生成算法
- 第一个试次永远不会是目标（无前一个数字可比较）
- 目标试次比例约为配置的 `TARGET_RATIO`
- 避免连续出现 3 个相同数字
- 非目标试次确保与前一个数字不同

### 数据记录
- 实时记录每个试次的数据
- 无论何时退出程序都会保存已完成试次的数据
- 支持异常退出时的数据保存

### 反馈机制
- 正确：绿色 ✓
- 错误：红色 ✗
- 无反应：视为错误

## 开发者信息

### 技术栈
- **Python 3.x**
- **Pygame 2.6.1+** (图形界面)
- **CSV 模块** (数据存储)

### 代码结构
```python
# 主程序结构
1. 初始化和配置加载
2. 字体安全加载系统
3. 刺激序列生成
4. 实验主循环
5. 数据收集和保存
6. 结果统计和显示
```

### 关键函数
- `load_font_safe()` - 安全加载字体，支持中文字体回退
- `generate_sequence()` - 生成刺激序列
- `show_text()` - 显示文本界面（支持退出时保存数据）
- `check_key_event()` - 检测按键事件
- `save_data()` - 保存试次数据到 CSV
- `calculate_stats()` - 计算统计数据

## 许可证

本项目用于研究目的，可以自由修改和使用。

## 更新历史

- **最终修复版** (`nback_task_final.py`) - 修复了字体显示、按键检测和数据保存问题
- **智能按键版** (`nback_task_smart.py`) - 添加自动按键检测功能
- **配置分离** - 所有参数移至 `config.py`
- **数据保存优化** - 确保所有退出路径都保存数据

## 支持

如有问题，请：
1. 检查 `SOLUTION.md` 中的解决方案
2. 运行相关的测试工具
3. 查看 `logs/` 目录中的日志文件
4. 检查 `data/` 目录中的数据文件