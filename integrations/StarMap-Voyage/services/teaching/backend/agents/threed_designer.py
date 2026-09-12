"""
3D Model Generation Agent.
Analyzes teaching plans for 3D printing opportunities and generates
OpenSCAD parametric designs for common STEM apparatus.
"""
import os
import re
import json
import sys
from typing import Dict, List, Optional, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.llm_config import resolve_chat_config

# ---- Config ----
_LLM_CONFIG = resolve_chat_config()
LLM_API_URL = _LLM_CONFIG["url"]
LLM_MODEL = _LLM_CONFIG["model"]
API_KEY = _LLM_CONFIG["api_key"]

# ---- OpenSCAD Template Library ----
TEMPLATES = {
    "sensor_mount": {
        "name": "传感器固定支架",
        "description": "通用传感器安装支架，可调尺寸",
        "params": ["sensor_width", "sensor_length", "sensor_height", "mount_hole_dia", "wall_thickness"],
        "code": """
// 传感器固定支架 - 参数化设计
sensor_width = {sensor_width};    // 传感器宽度 mm
sensor_length = {sensor_length};  // 传感器长度 mm
sensor_height = {sensor_height};  // 传感器高度 mm
mount_hole_dia = {mount_hole_dia}; // 安装孔直径 mm
wall_thickness = {wall_thickness};  // 壁厚 mm

difference() {{
    // 外壳
    cube([sensor_width + wall_thickness*2,
          sensor_length + wall_thickness*2,
          sensor_height + wall_thickness]);

    // 传感器腔体
    translate([wall_thickness, wall_thickness, wall_thickness])
        cube([sensor_width, sensor_length, sensor_height + 1]);

    // 线缆出口
    translate([sensor_width/2 + wall_thickness - 5,
               wall_thickness - 1,
               sensor_height/2 + wall_thickness])
        cube([10, wall_thickness + 2, 8]);

    // 安装孔
    for (x = [wall_thickness + mount_hole_dia,
              sensor_width + wall_thickness - mount_hole_dia]) {{
        for (y = [wall_thickness + mount_hole_dia,
                  sensor_length + wall_thickness - mount_hole_dia]) {{
            translate([x, y, -1])
                cylinder(h = wall_thickness + 2, d = mount_hole_dia, $fn=32);
        }}
    }}
}}
"""
    },
    "enclosure_box": {
        "name": "项目外壳/盒体",
        "description": "电子项目外壳，含盖子",
        "params": ["box_width", "box_length", "box_height", "wall_thickness", "corner_radius"],
        "code": """
// 项目外壳 - 参数化设计
box_width = {box_width};
box_length = {box_length};
box_height = {box_height};
wall_thickness = {wall_thickness};
corner_radius = {corner_radius};

module rounded_box(w, l, h, r) {{
    hull() {{
        translate([r, r, 0]) cylinder(h=h, r=r, $fn=32);
        translate([w-r, r, 0]) cylinder(h=h, r=r, $fn=32);
        translate([r, l-r, 0]) cylinder(h=h, r=r, $fn=32);
        translate([w-r, l-r, 0]) cylinder(h=h, r=r, $fn=32);
    }}
}}

// 底座
difference() {{
    rounded_box(box_width + wall_thickness*2,
                box_length + wall_thickness*2,
                box_height, corner_radius + wall_thickness);
    translate([wall_thickness, wall_thickness, wall_thickness])
        rounded_box(box_width, box_length, box_height + 1, corner_radius);
}}

// 盖子
translate([0, box_length + wall_thickness*2 + 10, 0])
    rounded_box(box_width + wall_thickness*2,
                box_length + wall_thickness*2,
                wall_thickness*2, corner_radius + wall_thickness);
"""
    },
    "test_tube_holder": {
        "name": "试管/样品架",
        "description": "实验室试管架，可调孔数和孔径",
        "params": ["tube_dia", "tube_count", "rows", "spacing", "base_height"],
        "code": """
// 试管架 - 参数化设计
tube_dia = {tube_dia};       // 试管直径 mm
tube_count = {tube_count};   // 每排数量
rows = {rows};               // 排数
spacing = {spacing};         // 间距 mm
base_height = {base_height}; // 底座高度 mm

total_width = tube_count * spacing + spacing;
total_length = rows * spacing + spacing;

// 底座
cube([total_width, total_length, 3]);

// 上层板
translate([0, 0, base_height * 0.6])
difference() {{
    cube([total_width, total_length, 3]);
    for (x = [0:tube_count-1]) {{
        for (y = [0:rows-1]) {{
            translate([spacing + x*spacing,
                       spacing + y*spacing, -1])
                cylinder(h=5, d=tube_dia + 0.5, $fn=48);
        }}
    }}
}}

// 支撑柱
for (x = [0, total_width - 8]) {{
    for (y = [0, total_length - 8]) {{
        translate([x + 4, y + 4, 0])
            cylinder(h=base_height * 0.6, d=6, $fn=24);
    }}
}}
"""
    },
    "wheel_mount": {
        "name": "电机/车轮安装座",
        "description": "直流电机和车轮的安装支架",
        "params": ["motor_dia", "motor_length", "wheel_offset", "mount_plate_w", "mount_plate_l"],
        "code": """
// 电机安装座 - 参数化设计
motor_dia = {motor_dia};
motor_length = {motor_length};
wheel_offset = {wheel_offset};
mount_plate_w = {mount_plate_w};
mount_plate_l = {mount_plate_l};

// 底板
cube([mount_plate_w, mount_plate_l, 3]);

// 电机固定环
translate([mount_plate_w/2, mount_plate_l/2, 3])
difference() {{
    cylinder(h=motor_length/2, d=motor_dia + 6);
    translate([0, 0, -1])
        cylinder(h=motor_length/2 + 2, d=motor_dia + 0.5);
}}

// 加强筋
for (x = [0, mount_plate_w - 4]) {{
    translate([x + 2, 0, 0])
        cube([4, mount_plate_l, motor_length/2 + 3]);
}}

// 安装孔
for (x = [6, mount_plate_w - 6]) {{
    for (y = [6, mount_plate_l - 6]) {{
        translate([x, y, -1])
            cylinder(h=5, d=3.2, $fn=24);
    }}
}}
"""
    },
    "lever_arm": {
        "name": "杠杆/连杆机构",
        "description": "用于力学实验的杠杆臂",
        "params": ["arm_length", "arm_width", "arm_thickness", "pivot_hole_dia", "load_holes_count"],
        "code": """
// 杠杆臂 - 参数化设计
arm_length = {arm_length};
arm_width = {arm_width};
arm_thickness = {arm_thickness};
pivot_hole_dia = {pivot_hole_dia};
load_holes_count = {load_holes_count};

difference() {{
    // 主体
    hull() {{
        translate([0, -arm_width/2, 0])
            cylinder(h=arm_thickness, d=arm_width, $fn=32);
        translate([arm_length, 0, 0])
            cylinder(h=arm_thickness, d=arm_width, $fn=32);
    }}

    // 支点孔
    translate([arm_length * 0.3, 0, -1])
        cylinder(h=arm_thickness + 2, d=pivot_hole_dia, $fn=32);

    // 砝码悬挂孔
    for (i = [0:load_holes_count-1]) {{
        translate([arm_length * (0.5 + i * 0.5/load_holes_count),
                   0, -1])
            cylinder(h=arm_thickness + 2, d=3, $fn=24);
    }}
}}
"""
    }
}


class ThreeDDesignerAgent:
    """Agent that generates 3D printable designs for STEM projects."""

    def __init__(self):
        self.template_cache = {}

    def analyze_plan(self, plan_markdown: str) -> List[Dict]:
        """
        Analyze a teaching plan and identify 3D printing opportunities.
        Returns list of design tasks.
        """
        design_tasks = []

        # Detect sensor types mentioned
        sensor_patterns = {
            "temperature": ["温度传感器", "DS18B20", "DHT22", "DHT11", "热电偶"],
            "light": ["光照传感器", "光敏", "BH1750", "TSL2561", "LDR", "光敏电阻"],
            "distance": ["超声波", "HC-SR04", "VL53L0X", "红外测距", "ToF"],
            "motion": ["加速度", "MPU6050", "ADXL345", "陀螺仪"],
            "gas": ["气体传感器", "MQ-", "烟雾传感器", "CO2", "PM2.5", "PMS5003"],
            "ph": ["pH传感器", "pH计"],
            "sound": ["声音传感器", "麦克风", "蜂鸣器", "扬声器"],
            "force": ["力传感器", "称重", "HX711", "压力传感器"],
        }

        detected_sensors = []
        for sensor_type, keywords in sensor_patterns.items():
            for kw in keywords:
                if kw.lower() in plan_markdown.lower():
                    detected_sensors.append(sensor_type)
                    break

        # Detect structural needs
        needs_enclosure = any(kw in plan_markdown for kw in
            ["外壳", "盒子", "封装", "机箱", "容器", "底座", "平台"])

        needs_holder = any(kw in plan_markdown for kw in
            ["支架", "固定", "安装", "夹持", "试管", "样品", "支撑"])

        needs_mechanism = any(kw in plan_markdown for kw in
            ["齿轮", "连杆", "杠杆", "滑轮", "轮子", "电机", "车轮", "传动"])

        needs_labware = any(kw in plan_markdown for kw in
            ["量筒", "烧杯", "试管", "培养皿", "试剂", "溶液", "化学", "生物实验"])

        # Generate design tasks based on detected needs
        if detected_sensors:
            design_tasks.append({
                "type": "sensor_mount",
                "priority": "high",
                "reason": f"检测到传感器: {', '.join(detected_sensors)}",
                "sensor_types": detected_sensors,
                "template": "sensor_mount",
                "params": self._suggest_params("sensor_mount", {"sensor_types": detected_sensors})
            })

        if needs_enclosure:
            design_tasks.append({
                "type": "enclosure_box",
                "priority": "high",
                "reason": "项目需要外壳/封装",
                "template": "enclosure_box",
                "params": self._suggest_params("enclosure_box", {})
            })

        if needs_holder or needs_labware:
            design_tasks.append({
                "type": "test_tube_holder",
                "priority": "medium",
                "reason": "需要样品架/支架" if needs_holder else "需要实验器材",
                "template": "test_tube_holder",
                "params": self._suggest_params("test_tube_holder", {})
            })

        if needs_mechanism:
            design_tasks.append({
                "type": "wheel_mount",
                "priority": "high" if "电机" in plan_markdown or "马达" in plan_markdown else "medium",
                "reason": "需要机械结构件",
                "template": "wheel_mount",
                "params": self._suggest_params("wheel_mount", {})
            })

            design_tasks.append({
                "type": "lever_arm",
                "priority": "medium",
                "reason": "可用于力学实验",
                "template": "lever_arm",
                "params": self._suggest_params("lever_arm", {})
            })

        return design_tasks

    def _suggest_params(self, template_name: str, context: Dict) -> Dict:
        """Suggest reasonable default parameters for a template."""
        defaults = {
            "sensor_mount": {
                "sensor_width": 25, "sensor_length": 35,
                "sensor_height": 12, "mount_hole_dia": 3,
                "wall_thickness": 2
            },
            "enclosure_box": {
                "box_width": 80, "box_length": 60,
                "box_height": 35, "wall_thickness": 2,
                "corner_radius": 5
            },
            "test_tube_holder": {
                "tube_dia": 16, "tube_count": 6,
                "rows": 2, "spacing": 25,
                "base_height": 60
            },
            "wheel_mount": {
                "motor_dia": 24, "motor_length": 30,
                "wheel_offset": 10, "mount_plate_w": 40,
                "mount_plate_l": 50
            },
            "lever_arm": {
                "arm_length": 200, "arm_width": 15,
                "arm_thickness": 6, "pivot_hole_dia": 5,
                "load_holes_count": 5
            }
        }
        params = defaults.get(template_name, {}).copy()

        # Adjust based on sensor type
        sensor_types = context.get("sensor_types", [])
        if template_name == "sensor_mount":
            if "distance" in sensor_types:
                params.update({"sensor_width": 45, "sensor_length": 20, "sensor_height": 15})
            elif "gas" in sensor_types:
                params.update({"sensor_width": 38, "sensor_length": 50, "sensor_height": 22})

        return params

    def generate_openscad(self, template_name: str, params: Dict,
                          custom_description: str = "") -> str:
        """Generate OpenSCAD code from template with custom parameters."""
        template = TEMPLATES.get(template_name)
        if not template:
            return ""

        code = template["code"]
        # Fill in parameters
        for key, value in params.items():
            code = code.replace("{" + key + "}", str(value))

        # Add comment header
        header = f"""// STEM项目3D打印部件
// 类型: {template['name']}
// 生成时间: 自动生成
"""
        if custom_description:
            header += f"// 说明: {custom_description}\n"

        header += "// 参数: " + ", ".join(f"{k}={v}" for k, v in params.items()) + "\n"
        header += "// 请在OpenSCAD中打开并调整参数后导出STL\n\n"

        return header + code

    def generate_all(self, plan_markdown: str, project_path: str) -> List[Dict]:
        """
        Analyze plan and generate all 3D models for the project.
        Returns list of generated files.
        """
        tasks = self.analyze_plan(plan_markdown)
        models_dir = os.path.join(project_path, "3d_models")
        os.makedirs(models_dir, exist_ok=True)

        generated = []
        for i, task in enumerate(tasks):
            template_name = task["template"]
            params = task["params"]
            description = task.get("reason", "")

            # Check if we should use AI to customize params
            if task["priority"] == "high":
                params = self._ai_optimize_params(template_name, params, plan_markdown)

            code = self.generate_openscad(template_name, params, description)
            if not code:
                continue

            filename = f"{template_name}_{i+1}.scad"
            filepath = os.path.join(models_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)

            generated.append({
                "filename": filename,
                "filepath": filepath,
                "template": template_name,
                "name": TEMPLATES[template_name]["name"],
                "params": params,
                "priority": task["priority"],
                "reason": description,
                "scad_code": code
            })

        # Generate summary README
        if generated:
            self._write_summary(models_dir, generated)

        return generated

    def _ai_optimize_params(self, template_name: str, defaults: Dict,
                            plan_markdown: str) -> Dict:
        """Use LLM to suggest better parameters based on project context."""
        # Truncate plan for context
        plan_summary = plan_markdown[:2000]

        prompt = f"""你是3D打印设计专家。请根据以下STEM项目教案，为{template_name}推荐合适的尺寸参数。

项目教案摘要：
{plan_summary}

当前默认参数：
{json.dumps(defaults, ensure_ascii=False, indent=2)}

请返回JSON格式的优化参数。注意：
- 尺寸单位为毫米(mm)
- 考虑实际使用场景的合理性
- 保持参数名称不变
- 直接返回JSON，不要其他文字"""

        try:
            resp = requests.post(
                LLM_API_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=30
            )

            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    optimized = json.loads(json_match.group())
                    # Merge with defaults (keep all keys)
                    defaults.update(optimized)
        except Exception as e:
            print(f"AI参数优化失败，使用默认值: {e}")

        return defaults

    def _write_summary(self, models_dir: str, generated: List[Dict]):
        """Write a summary README for the 3D models directory."""
        lines = ["# 3D打印模型清单\n"]
        lines.append("| # | 部件名称 | 类型 | 优先级 | 说明 |")
        lines.append("|---|---------|------|-------|------|")
        for i, g in enumerate(generated, 1):
            lines.append(f"| {i} | {g['name']} | {g['template']} | {g['priority']} | {g['reason']} |")

        lines.append("\n## 使用说明")
        lines.append("1. 在 [OpenSCAD](https://openscad.org/) 中打开 .scad 文件")
        lines.append("2. 根据需要调整参数")
        lines.append("3. 渲染并导出为 STL 格式")
        lines.append("4. 在切片软件(Cura/PrusaSlicer)中打开STL，设置打印参数")
        lines.append("5. 打印并测试装配\n")
        lines.append("## 打印建议")
        lines.append("- 材料: PLA (易打印，适合教学) 或 PETG (更耐用)")
        lines.append("- 层高: 0.2mm (平衡速度与质量)")
        lines.append("- 填充: 20-30% (结构件建议30%+，外壳20%即可)")
        lines.append("- 支撑: 根据模型悬空情况决定")

        with open(os.path.join(models_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


# ---- Standalone test ----
if __name__ == "__main__":
    agent = ThreeDDesignerAgent()

    # Test with sample plan
    sample_plan = """
    # 智能空气监测器

    ## 材料清单
    - Arduino Uno
    - PMS5003 PM2.5传感器
    - DHT22 温湿度传感器
    - OLED显示屏
    - 3D打印外壳
    """
    tasks = agent.analyze_plan(sample_plan)
    print(f"Detected {len(tasks)} design tasks:")
    for t in tasks:
        print(f"  - {t['type']} ({t['priority']}): {t['reason']}")
        print(f"    params: {t['params']}")
