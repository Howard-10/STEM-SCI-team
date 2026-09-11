"""生成 Research-Copilot-OS 答辩 PPT"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

# ═══════════════════════════════════════════════════════
#  配色方案
# ═══════════════════════════════════════════════════════
DARK_BG = RGBColor(0x0F, 0x17, 0x2A)       # 深蓝黑
MID_BG = RGBColor(0x1E, 0x29, 0x3B)        # 中蓝
ACCENT = RGBColor(0x7C, 0x3A, 0xED)         # 紫色强调
ACCENT2 = RGBColor(0x06, 0xB6, 0xD4)        # 青色
ACCENT3 = RGBColor(0x10, 0xB9, 0x81)        # 绿色
ACCENT4 = RGBColor(0xF5, 0x9E, 0x0B)        # 橙色
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xE2, 0xE8, 0xF0)
GRAY = RGBColor(0x94, 0xA3, 0xB8)
CARD_BG = RGBColor(0x1A, 0x22, 0x3A)

def add_bg(slide, color=DARK_BG):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_shape(slide, left, top, width, height, color=CARD_BG, radius=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape

def add_text_box(slide, left, top, width, height, text, font_size=18, color=WHITE, bold=False, alignment=PP_ALIGN.LEFT, font_name='Arial'):
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    return txBox

def add_title_bar(slide, title_text, accent=ACCENT):
    """添加顶部标题条"""
    bar = add_shape(slide, Inches(0), Inches(0), prs.slide_width, Inches(1.2), MID_BG)
    bar.fill.solid()
    bar.fill.fore_color.rgb = MID_BG
    # 左侧彩色条
    accent_bar = add_shape(slide, Inches(0), Inches(0), Inches(0.15), Inches(1.2), accent)
    accent_bar.fill.solid()
    accent_bar.fill.fore_color.rgb = accent
    add_text_box(slide, Inches(0.6), Inches(0.15), Inches(12), Inches(0.9), title_text, 36, WHITE, True)

def add_card(slide, left, top, width, height, icon, title, desc, border_color=ACCENT):
    """添加卡片"""
    card = add_shape(slide, left, top, width, height, CARD_BG)
    # 顶部彩色线
    line = add_shape(slide, left, top, width, Inches(0.06), border_color)
    line.fill.solid()
    line.fill.fore_color.rgb = border_color
    add_text_box(slide, left + Inches(0.2), top + Inches(0.2), width - Inches(0.4), Inches(0.5), icon, 28, border_color, True)
    add_text_box(slide, left + Inches(0.2), top + Inches(0.7), width - Inches(0.4), Inches(0.35), title, 16, WHITE, True)
    add_text_box(slide, left + Inches(0.2), top + Inches(1.1), width - Inches(0.4), height - Inches(1.3), desc, 11, GRAY)
    return card

# ═══════════════════════════════════════════════════════
#  Slide 1: 封面
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
add_bg(slide)
# 装饰图形
for i, color in enumerate([ACCENT, ACCENT2, ACCENT3, ACCENT4]):
    bar = add_shape(slide, Inches(2 + i*2.5), Inches(3), Inches(2), Inches(0.04), color)
add_text_box(slide, Inches(1), Inches(1.8), Inches(11.3), Inches(1.5), "Research-Copilot-OS", 60, WHITE, True, PP_ALIGN.CENTER)
add_text_box(slide, Inches(1), Inches(3.5), Inches(11.3), Inches(0.8), "AI 赋能科研全流程智能平台", 28, ACCENT, False, PP_ALIGN.CENTER)
add_text_box(slide, Inches(1), Inches(4.5), Inches(11.3), Inches(0.6), "19 工具 Agent · DeepSeek V4 驱动 · 四大引擎协同", 18, GRAY, False, PP_ALIGN.CENTER)
add_text_box(slide, Inches(1), Inches(6.0), Inches(11.3), Inches(0.5), "科技论文写作课程汇报", 16, GRAY, False, PP_ALIGN.CENTER)

# ═══════════════════════════════════════════════════════
#  Slide 2: Motivation — 科研痛点
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "Motivation — 科研工作者的真实痛点", ACCENT2)

pain_points = [
    ("📄", "文献阅读耗时", "每天海量论文涌现，逐篇阅读效率低下\n难以快速对比多篇论文的方法和实验"),
    ("🧩", "代码理解困难", "论文代码结构复杂，学习成本高\n想要复现或迁移模块，缺少自动化工具"),
    ("🔬", "实验管理混乱", "超参数调优凭经验、消融实验靠手工\n数据增强和可视化代码重复编写"),
]
for i, (icon, title, desc) in enumerate(pain_points):
    add_card(slide, Inches(0.8 + i*4), Inches(1.8), Inches(3.6), Inches(4.5), icon, title, desc, [ACCENT, ACCENT2, ACCENT3][i])

add_text_box(slide, Inches(0.8), Inches(6.6), Inches(11.7), Inches(0.5), "💡 核心洞察：需要一个覆盖「读论文→懂代码→做实验」全流程的 AI 科研助手", 20, ACCENT, True, PP_ALIGN.CENTER)

# ═══════════════════════════════════════════════════════
#  Slide 3: 整体架构
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "整体架构 — 四大引擎 + Agent 智能体")

engines = [
    ("📖", "文献理解引擎", "PDF 多策略解析\nRAG 检索增强\n单论文深度解读\n多论文综述对比", ACCENT),
    ("🧩", "代码分析引擎", "AST 静态分析\n按功能/模块分块\n智能模块迁移\n自动维度对齐", ACCENT2),
    ("🔬", "实验编排引擎", "数据集自动适配\n包装化数据增强\n消融实验自动化\n超参数智能调优", ACCENT3),
    ("📈", "可视化生成引擎", "文献驱动推荐\n迭代评分修缮\nMorandi 学术配色\nCSV/文本数据输入", ACCENT4),
]
for i, (icon, title, desc, color) in enumerate(engines):
    add_card(slide, Inches(0.5 + i*3.2), Inches(1.8), Inches(2.95), Inches(3.5), icon, title, desc, color)

# Agent 层
agent_card = add_shape(slide, Inches(0.5), Inches(5.6), Inches(12.3), Inches(1.5), MID_BG)
add_text_box(slide, Inches(0.8), Inches(5.7), Inches(11.7), Inches(0.4), "🤖 AI Agent 智能体层", 22, ACCENT, True)
add_text_box(slide, Inches(0.8), Inches(6.1), Inches(11.7), Inches(0.9),
             "19 个标准化工具 · Claude 式 Think→Act→Observe 循环 · 4 项领域 Skill · 文件系统 + Shell 执行 · 权限控制",
             14, LIGHT)

# ═══════════════════════════════════════════════════════
#  Slide 4: 技术栈
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "技术架构", ACCENT3)

layers = [
    ("前端层", "Streamlit · 深色主题 · 响应式布局 · 四大模块导航 · 侧边栏 AI 助手"),
    ("API 层", "FastAPI · 40+ REST 端点 · 异步处理 · 文件上传 · 请求验证"),
    ("Agent 层", "Claude 式编排器 · 技能系统 · 权限控制 · 会话管理 · 并行分析"),
    ("引擎层", "PyMuPDF + pdfplumber · AST 静态分析 · PyTorch Transform · SQLite"),
    ("LLM 层", "DeepSeek V4 (deepseek-chat) · OpenAI 兼容接口 · 结构化输出"),
]
for i, (layer, desc) in enumerate(layers):
    y = Inches(1.6 + i * 1.1)
    bar = add_shape(slide, Inches(0.8), y, Inches(11.7), Inches(0.9), CARD_BG)
    accent_bar = add_shape(slide, Inches(0.8), y, Inches(0.08), Inches(0.9), [ACCENT, ACCENT2, ACCENT3, ACCENT4, GRAY][i])
    add_text_box(slide, Inches(1.2), y + Inches(0.1), Inches(2), Inches(0.7), layer, 20, [ACCENT, ACCENT2, ACCENT3, ACCENT4, GRAY][i], True)
    add_text_box(slide, Inches(3.5), y + Inches(0.1), Inches(9), Inches(0.7), desc, 14, LIGHT)

# ═══════════════════════════════════════════════════════
#  Slide 5: 文献整理与解读
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "功能 1: 文献整理与解读", ACCENT)

add_card(slide, Inches(0.5), Inches(1.6), Inches(5.8), Inches(5.2),
         "📄", "单论文深度解读",
         "• 多策略 PDF 解析 (PyMuPDF + pdfplumber)\n• 自动提取: 标题/作者/摘要/章节/参考文献\n• 全文一次性发送 LLM，5 维度分析:\n  - 动机与背景\n  - 方法论深度 (架构/算法/公式/创新点)\n  - 实验全面 (数据集/指标/结果/消融/效率)\n  - 深度评价 (优势/局限/说服力/可复现)\n• 文本质量预检 + 强制读取模式", ACCENT)

add_card(slide, Inches(7), Inches(1.6), Inches(5.8), Inches(5.2),
         "📚", "多论文综述对比",
         "• 并行分析 N 篇论文 (ThreadPoolExecutor)\n• 自动分类聚类\n• 模块对模块对比 (22 字段 × N 篇)\n  - 方法论对比: 问题定义→架构→算法→创新\n  - 实验对比: 数据集→指标→结果→消融→效率\n• 对比表 + 综述报告 + 关系图谱\n• 每篇质量评分 (success/partial/failed)", ACCENT2)

# ═══════════════════════════════════════════════════════
#  Slide 6: 模型融合
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "功能 2: 模型融合 — 代码分块 + 模块迁移", ACCENT2)

add_card(slide, Inches(0.5), Inches(1.6), Inches(5.8), Inches(3.5),
         "🧩", "代码智能分块",
         "• AST 静态分析 PyTorch 项目\n• 自动识别: nn.Module / Dataset / Forward / Loss / Optimizer\n• LLM 语义增强 → 归入 6 个顶层类别:\n  参数配置 / 模型架构 / 数据处理 / 训练优化 / 评估日志 / 工具入口\n• 支持 zip 上传 + 本地路径 + 历史缓存", ACCENT2)

add_card(slide, Inches(7), Inches(1.6), Inches(5.8), Inches(3.5),
         "🔀", "智能模块迁移",
         "• 双重路径: 历史分块选择 / 双项目实时对比\n• 左(源模块) + 右(目标模型) 分栏布局\n• 目标模型有序分块 (数据→架构→损失，按顺序)\n• 点击选模块 → 点击插位置 → AI 对齐 → 保存\n• 自动维度对齐 + 风险评估 + 原文件 .bak 备份", ACCENT2)

# 代码块解读
add_card(slide, Inches(0.5), Inches(5.4), Inches(12.3), Inches(1.6),
         "💬", "AI 代码块解读",
         "• 每个分块侧面设「💬 AI 解读」按钮\n• Agent 预先读取全部代码块建立全貌认知\n• 解读内容: 1) 代码块含义和用途  2) 与上一个块的连接关系（数据流/依赖）\n• 结果在侧边栏 AI 助手实时展示", ACCENT)

# ═══════════════════════════════════════════════════════
#  Slide 7: 数据处理
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "功能 3: 数据处理 — 数据集适配 + 数据增强", ACCENT3)

add_card(slide, Inches(0.5), Inches(1.6), Inches(5.8), Inches(5.2),
         "📊", "数据集自动适配",
         "• 支持文件/文件夹/zip 输入\n• 自动检测格式: image_folder/csv/json/npy/hdf5\n• 采样分析: 样本数/特征维度/标签类型/类别数\n• 智能提取模型代码中数据相关模块\n• 生成适配 DataLoader 代码(训练/验证/测试划分)\n• 预览 + 下载", ACCENT3)

add_card(slide, Inches(7), Inches(1.6), Inches(5.8), Inches(5.2),
         "🎨", "包装化数据增强与攻击",
         "• 20 种操作全覆盖: 几何/色彩/模糊/噪声/高级/攻击\n• 四步工作流:\n  1) 选择增强操作 (分类折叠+全选)\n  2) 单图测试 (上传→预览原图vs增强后)\n  3) 批量处理 (文件夹→按操作分目录保存)\n  4) 自定义增强 (AI 交互 or 生成代码)\n• torchvision 实时执行 + base64 预览", ACCENT3)

# ═══════════════════════════════════════════════════════
#  Slide 8: 实验模块
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "功能 4: 实验模块 — 可视化 + 消融 + 调参 + 记录", ACCENT4)

exps = [
    ("📈", "可视化生成", "AI 推荐图表 → 输入数据 → 迭代生成+5维评分 → 修缮至90分+\nMorandi 配色 · CSV/文本输入 · 参考样例上传 · 下载脚本", ACCENT4),
    ("🧪", "消融实验", "上传项目 → AI 按双条件识别(独立+创新) → 列出所有出现位置\n用户勾选 → 全量移除+自动对齐 → 预览 → 保存(.bak备份)", ACCENT),
    ("🎛️", "超参数调优", "三种输入(zip/路径/粘贴) → 识别所有可调参数 → 文本框编辑\n训练过程分析 → AI 诊断 (过拟合/欠拟合/震荡) → 推荐调整方案", ACCENT2),
    ("📋", "实验记录", "SQLite 自动存储 · 搜索筛选 · Epoch折线图 · 多实验对比", ACCENT3),
]
for i, (icon, title, desc, color) in enumerate(exps):
    row = i // 2
    col = i % 2
    add_card(slide, Inches(0.5 + col*6.4), Inches(1.6 + row*2.7), Inches(6.1), Inches(2.4), icon, title, desc, color)

# ═══════════════════════════════════════════════════════
#  Slide 9: Agent 系统
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "AI Agent 智能体系统", ACCENT)

agent_features = [
    ("🔄", "Claude 式循环", "Think→Act→Observe→Reflect\nDeepSeek Function Calling\n多轮记忆持久化", ACCENT),
    ("🔧", "19 个工具", "文件系统 (6个) · 科研引擎 (13个)\nGlob/Grep/Read/Write/Edit\nBash 执行 · 危险命令拦截", ACCENT2),
    ("📋", "4 项技能", "文献整理 / 模型融合\n数据处理 / 实验管理\n触发词自动匹配激活\nSOP 工作流注入", ACCENT3),
    ("🛡️", "权限控制", "只读自动允许\n项目内写入自动通过\n危险命令拦截\nAPI 路径穿越防护", ACCENT4),
]
for i, (icon, title, desc, color) in enumerate(agent_features):
    add_card(slide, Inches(0.5 + i*3.2), Inches(1.6), Inches(2.95), Inches(5.2), icon, title, desc, color)

# ═══════════════════════════════════════════════════════
#  Slide 10: 创新点
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "创新点总结", ACCENT2)

innovations = [
    ("全流程覆盖", "从文献阅读到实验管理的完整闭环，填补现有工具间的空白"),
    ("Claude 框架 + DeepSeek 模型", "复用成熟的 Agent 设计模式，底层用国产大模型驱动，成本可控"),
    ("模块对模块对比综述", "22 字段 × N 篇论文的结构化对比，远超传统文献工具的单篇摘要"),
    ("可执行的操作闭环", "不只是分析建议——代码分块、模块迁移、消融实验均可落地执行"),
    ("技能系统", "4 项领域 Skill 自动匹配激活，Agent 行为更精准、输出更稳定"),
    ("安全与鲁棒", "路径穿越防护 · ZIP 攻击拦截 · 危险命令过滤 · 原文件自动备份"),
]
for i, (title, desc) in enumerate(innovations):
    row = i // 2
    col = i % 2
    color = [ACCENT, ACCENT2, ACCENT3, ACCENT4, ACCENT, ACCENT2][i]
    card = add_card(slide, Inches(0.5 + col*6.4), Inches(1.6 + row*1.8), Inches(6.1), Inches(1.5), "", "", "", color)
    add_text_box(slide, Inches(0.8 + col*6.4), Inches(1.7 + row*1.8), Inches(5.5), Inches(0.4), f"{i+1}. {title}", 18, color, True)
    add_text_box(slide, Inches(0.8 + col*6.4), Inches(2.1 + row*1.8), Inches(5.5), Inches(0.8), desc, 13, LIGHT)

# ═══════════════════════════════════════════════════════
#  Slide 11: 总结
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_title_bar(slide, "总结与展望", ACCENT3)

add_card(slide, Inches(0.5), Inches(1.6), Inches(6), Inches(5.2),
         "✅", "已完成工作",
         "• 四大引擎全部实现并测试通过\n• 40+ API 端点 · Streamlit 完整前端\n• 19 工具 AI Agent + 4 项技能系统\n• 多策略 PDF 解析 (PyMuPDF + pdfplumber)\n• AST 代码分块 + 智能模块迁移\n• 20 种数据增强实时预览和批量处理\n• 可视化迭代生成 + 五维自动评分\n• 消融实验自动识别 + 维度对齐\n• 超参数全量识别 + 训练诊断推荐", ACCENT3)

add_card(slide, Inches(7), Inches(1.6), Inches(5.8), Inches(5.2),
         "🔮", "未来展望",
         "• 接入 OCR 策略处理扫描版 PDF\n• 代码模块拖拽式交互\n• 训练过程实时监控集成\n• 更多模型后端支持 (Claude/GPT)\n• 实验结果自动撰写论文初稿\n• 多用户协作支持\n• 容器化部署 (Docker)", ACCENT4)

# ═══════════════════════════════════════════════════════
#  Slide 12: 致谢
# ═══════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
for i, color in enumerate([ACCENT, ACCENT2, ACCENT3, ACCENT4]):
    bar = add_shape(slide, Inches(2 + i*2.5), Inches(3.5), Inches(2), Inches(0.04), color)
add_text_box(slide, Inches(1), Inches(2), Inches(11.3), Inches(1.2), "感谢聆听", 56, WHITE, True, PP_ALIGN.CENTER)
add_text_box(slide, Inches(1), Inches(3.8), Inches(11.3), Inches(0.6), "Research-Copilot-OS", 28, ACCENT, False, PP_ALIGN.CENTER)
add_text_box(slide, Inches(1), Inches(4.5), Inches(11.3), Inches(0.5), "AI 赋能科研全流程 · DeepSeek V4 · 19 工具 Agent", 18, GRAY, False, PP_ALIGN.CENTER)
add_text_box(slide, Inches(1), Inches(5.8), Inches(11.3), Inches(0.5), "科技论文写作课程汇报", 16, GRAY, False, PP_ALIGN.CENTER)

# ═══════════════════════════════════════════════════════
#  保存
# ═══════════════════════════════════════════════════════
output_path = "d:/科技论文写作/agent/Research-Copilot-OS/Research-Copilot-OS_答辩PPT.pptx"
prs.save(output_path)
print(f"PPT saved to: {output_path}")
print(f"Total slides: {len(prs.slides)}")
