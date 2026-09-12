"""
Arduino Code Generation Agent.
Generates sensor reading, actuator control, and data logging code
for STEM projects. Supports compile checking via Arduino CLI.
"""
import os
import re
import subprocess
import tempfile
import json
from typing import Dict, List, Optional, Tuple

import requests
from agents.llm_config import resolve_chat_config

# ---- Config ----
_LLM_CONFIG = resolve_chat_config()
LLM_API_URL = _LLM_CONFIG["url"]
LLM_MODEL = _LLM_CONFIG["model"]
API_KEY = _LLM_CONFIG["api_key"]

# ---- Sensor Code Templates ----
SENSOR_TEMPLATES = {
    "DHT22": {
        "libs": ["DHT sensor library"],
        "init": "DHT dht({pin}, DHT22);",
        "read": """
float temperature = dht.readTemperature();
float humidity = dht.readHumidity();
if (isnan(temperature) || isnan(humidity)) {
  Serial.println("DHT22 read failed!");
  return;
}
""",
        "pins": "Any digital pin (e.g., D2)"
    },
    "DS18B20": {
        "libs": ["OneWire", "DallasTemperature"],
        "init": """OneWire oneWire({pin});
DallasTemperature sensors(&oneWire);""",
        "read": """
sensors.requestTemperatures();
float temperature = sensors.getTempCByIndex(0);
""",
        "pins": "Any digital pin (e.g., D3), need 4.7k pull-up"
    },
    "HC_SR04": {
        "libs": [],
        "init": "const int trigPin = {trig_pin};\nconst int echoPin = {echo_pin};",
        "read": """
digitalWrite(trigPin, LOW); delayMicroseconds(2);
digitalWrite(trigPin, HIGH); delayMicroseconds(10);
digitalWrite(trigPin, LOW);
long duration = pulseIn(echoPin, HIGH);
float distance = duration * 0.034 / 2;  // cm
""",
        "pins": "2 digital pins (trig + echo)"
    },
    "BH1750": {
        "libs": ["BH1750"],
        "init": """#include <Wire.h>
BH1750 lightMeter;""",
        "read": """
float lux = lightMeter.readLightLevel();
""",
        "pins": "I2C (A4=SDA, A5=SCL on Uno)"
    },
    "PMS5003": {
        "libs": ["PMS Library"],
        "init": """#include <PMS.h>
PMS pms(Serial1);
PMS::DATA data;""",
        "read": """
if (pms.read(data)) {
  int pm25 = data.PM_AE_UG_2_5;
}
""",
        "pins": "Serial1 (TX1=18, RX1=19 on Mega), SoftwareSerial otherwise"
    },
    "servo": {
        "libs": ["Servo"],
        "init": "Servo myservo;",
        "read": "myservo.write({angle});  // 0-180 degrees",
        "pins": "Any PWM pin (e.g., D9)"
    },
    "led_rgb": {
        "libs": ["Adafruit NeoPixel"],
        "init": """#define LED_PIN {pin}
#define LED_COUNT {count}
Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);""",
        "read": """
strip.setPixelColor({index}, strip.Color({r}, {g}, {b}));
strip.show();
""",
        "pins": "Any digital pin (e.g., D6)"
    },
    "buzzer": {
        "libs": [],
        "init": "const int buzzerPin = {pin};",
        "read": """
tone(buzzerPin, {frequency});  // Hz
delay({duration});
noTone(buzzerPin);
""",
        "pins": "Any PWM pin (e.g., D9)"
    },
    "oled": {
        "libs": ["Adafruit SSD1306", "Adafruit GFX Library"],
        "init": """#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);""",
        "read": """
display.clearDisplay();
display.setTextSize(1);
display.setTextColor(SSD1306_WHITE);
display.setCursor(0, 0);
display.print("Text here");
display.display();
""",
        "pins": "I2C (A4=SDA, A5=SCL on Uno)"
    },
    "lcd": {
        "libs": ["LiquidCrystal_I2C"],
        "init": "LiquidCrystal_I2C lcd(0x27, 16, 2);",
        "read": """
lcd.setCursor(0, 0);
lcd.print("Text here");
""",
        "pins": "I2C (A4=SDA, A5=SCL on Uno)"
    },
    "photoresistor": {
        "libs": [],
        "init": "const int ldrPin = {pin};",
        "read": """
int ldrValue = analogRead(ldrPin);  // 0-1023
int brightness = map(ldrValue, 0, 1023, 0, 100);
""",
        "pins": "Any analog pin (A0-A5)"
    }
}

# Arduino CLI detection
ARDUINO_CLI_AVAILABLE = False


def check_arduino_cli() -> bool:
    """Check if arduino-cli is installed."""
    global ARDUINO_CLI_AVAILABLE
    try:
        result = subprocess.run(
            ["arduino-cli", "version"],
            capture_output=True, text=True, timeout=10
        )
        ARDUINO_CLI_AVAILABLE = result.returncode == 0
    except FileNotFoundError:
        ARDUINO_CLI_AVAILABLE = False
    return ARDUINO_CLI_AVAILABLE


class ArduinoCodeGenerator:
    """Generates Arduino code for STEM projects."""

    def detect_sensors(self, plan_markdown: str) -> List[Dict]:
        """Detect sensors and actuators mentioned in the teaching plan."""
        detected = []

        sensor_keywords = {
            "DHT22": ["DHT22", "DHT11", "温湿度传感器"],
            "DS18B20": ["DS18B20", "温度传感器", "数字温度"],
            "HC_SR04": ["HC-SR04", "超声波", "超声波传感器", "测距"],
            "BH1750": ["BH1750", "光照传感器", "亮度传感器", "光强"],
            "PMS5003": ["PMS5003", "PM2.5", "PM10", "粉尘传感器", "空气质量"],
            "photoresistor": ["光敏电阻", "光敏传感器", "亮度检测"],
            "servo": ["舵机", "伺服电机", "servo"],
            "led_rgb": ["RGB LED", "WS2812", "NeoPixel", "灯带", "彩灯"],
            "buzzer": ["蜂鸣器", "buzzer", "喇叭", "扬声器", "报警"],
            "oled": ["OLED", "显示屏", "SSD1306"],
            "lcd": ["LCD", "液晶屏", "1602"],
        }

        for sensor_id, keywords in sensor_keywords.items():
            for kw in keywords:
                if kw.lower() in plan_markdown.lower():
                    detected.append({
                        "id": sensor_id,
                        "keyword": kw,
                        "template": SENSOR_TEMPLATES.get(sensor_id)
                    })
                    break

        return detected

    def generate_sketch(self, sensors: List[Dict], project_name: str = "STEM_Project",
                        board: str = "arduino:avr:uno") -> str:
        """Generate a complete Arduino sketch based on detected sensors."""
        if not sensors:
            return ""

        libs = set()
        includes = []
        defines = []
        globals_code = []
        setup_code = ["  Serial.begin(9600);", "  delay(1000);",
                      '  Serial.println("Starting...");']
        loop_code = []
        pin_assignments = []

        # Assign pins
        analog_pins = list(range(14, 20))  # A0-A5
        digital_pins = list(range(2, 14))  # D2-D13
        pwm_pins = [3, 5, 6, 9, 10, 11]

        for i, sensor in enumerate(sensors):
            tmpl = sensor.get("template")
            if not tmpl:
                continue

            # Collect libraries
            for lib in tmpl.get("libs", []):
                libs.add(lib)

            # Assign pins
            pins = tmpl.get("pins", "")
            sensor_id = sensor["id"]

            if "I2C" in pins:
                pass  # I2C uses fixed pins
            elif "analog" in sensor_id.lower() or sensor_id in ["photoresistor"]:
                pin = analog_pins.pop(0) if analog_pins else 14
                pin_name = f"A{pin - 14}"
                pin_assignments.append(f"// {sensor_id}: {pin_name} (analog)")
            elif "Servo" in pins or sensor_id in ["servo"]:
                pin = pwm_pins.pop(0) if pwm_pins else 9
                pin_assignments.append(f"// {sensor_id}: D{pin} (PWM)")
            elif "trig" in tmpl.get("init", "").lower():
                trig = digital_pins.pop(0) if digital_pins else 2
                echo = digital_pins.pop(0) if digital_pins else 3
                pin_assignments.append(f"// {sensor_id}: trig=D{trig}, echo=D{echo}")
            else:
                pin_count = 1
                if "RX" in pins or "TX" in pins or "Serial" in pins:
                    pass  # Use hardware serial
                else:
                    pin = digital_pins.pop(0) if digital_pins else 4
                    pin_assignments.append(f"// {sensor_id}: D{pin}")

            # Generate init code
            init = tmpl.get("init", "")
            init = init.replace("{pin}", str(pin) if 'pin' in dir() else "2")
            init = init.replace("{trig_pin}", str(trig) if 'trig' in dir() else "2")
            init = init.replace("{echo_pin}", str(echo) if 'echo' in dir() else "3")
            init = init.replace("{count}", "8")
            globals_code.append(init)

            # Include Wire.h for I2C devices
            if "Wire" in init:
                includes.append("#include <Wire.h>")
                setup_code.insert(0, "  Wire.begin();")

            # Generate read code
            read = tmpl.get("read", "")
            if read:
                read = read.replace("{angle}", "90")
                read = read.replace("{index}", "0")
                read = read.replace("{r}", "255").replace("{g}", "0").replace("{b}", "0")
                read = read.replace("{frequency}", "1000")
                read = read.replace("{duration}", "500")
                loop_code.append(f"  // Read {sensor_id}")
                for line in read.strip().split("\n"):
                    if line.strip():
                        loop_code.append(f"  {line.strip()}")
                loop_code.append(f'  Serial.print("{sensor_id}: ");')
                loop_code.append("  Serial.println(value);  // TODO: replace 'value' with actual reading")
                loop_code.append("  delay(500);")
                loop_code.append("")

        # Build the complete sketch
        sketch = f"""/*
 * {project_name}
 * Auto-generated Arduino sketch for STEM learning
 * Generated by 星图学航 2.0
 *
 * Board: {board}
 * Components: {', '.join(s['id'] for s in sensors)}
 */

// Libraries
"""
        for lib in sorted(libs):
            sketch += f"// Requires: {lib}\n"
        sketch += "\n"

        sketch += "\n".join(includes) + "\n\n"

        if pin_assignments:
            sketch += "// Pin Assignments\n"
            sketch += "\n".join(pin_assignments) + "\n\n"

        sketch += "// Global variables\n"
        sketch += "\n".join(globals_code) + "\n\n"

        sketch += "void setup() {\n"
        sketch += "\n".join(setup_code) + "\n"
        sketch += "}\n\n"

        sketch += "void loop() {\n"
        sketch += "\n".join(loop_code) if loop_code else "  // Add your code here\n"
        sketch += "}\n"

        return sketch

    def compile_check(self, sketch_code: str, board: str = "arduino:avr:uno") -> Dict:
        """Try to compile the sketch using arduino-cli (if available)."""
        if not ARDUINO_CLI_AVAILABLE:
            return {"success": False, "error": "Arduino CLI 未安装。请安装后使用编译检查功能。",
                    "hint": "下载: https://arduino.github.io/arduino-cli/"}

        # Write to temp file
        tmpdir = tempfile.mkdtemp()
        sketch_dir = os.path.join(tmpdir, "sketch")
        os.makedirs(sketch_dir, exist_ok=True)
        sketch_path = os.path.join(sketch_dir, "sketch.ino")

        with open(sketch_path, "w", encoding="utf-8") as f:
            f.write(sketch_code)

        try:
            result = subprocess.run(
                ["arduino-cli", "compile", "--fqbn", board, sketch_dir],
                capture_output=True, text=True, timeout=60
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[-1000:] if result.stdout else "",
                "stderr": result.stderr[-1000:] if result.stderr else "",
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "编译超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def generate_all(self, plan_markdown: str, project_path: str,
                     board: str = "arduino:avr:uno") -> Dict:
        """Detect components, generate code, and save to project."""
        sensors = self.detect_sensors(plan_markdown)

        if not sensors:
            return {"generated": False, "reason": "未检测到Arduino相关传感器或执行器", "files": []}

        code_dir = os.path.join(project_path, "code")
        os.makedirs(code_dir, exist_ok=True)

        generated_files = []

        # Generate main sketch
        sketch = self.generate_sketch(sensors, "STEM_Project", board)
        if sketch:
            sketch_path = os.path.join(code_dir, "main.ino")
            with open(sketch_path, "w", encoding="utf-8") as f:
                f.write(sketch)
            generated_files.append({
                "filename": "main.ino",
                "type": "arduino_sketch",
                "sensors": [s["id"] for s in sensors],
                "code": sketch
            })

        # Generate individual sensor test sketches
        for sensor in sensors:
            test_sketch = self.generate_test_sketch(sensor, board)
            if test_sketch:
                fname = f"test_{sensor['id'].lower()}.ino"
                fpath = os.path.join(code_dir, fname)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(test_sketch)
                generated_files.append({
                    "filename": fname,
                    "type": "sensor_test",
                    "sensor": sensor["id"]
                })

        # Try compile check if CLI available
        compile_result = None
        if sketch and ARDUINO_CLI_AVAILABLE:
            compile_result = self.compile_check(sketch, board)

        return {
            "generated": True,
            "files": generated_files,
            "sensors_detected": [s["id"] for s in sensors],
            "compile_result": compile_result
        }

    def generate_test_sketch(self, sensor: Dict, board: str) -> str:
        """Generate a simple test sketch for a single sensor."""
        tmpl = sensor.get("template")
        if not tmpl:
            return ""

        sensor_id = sensor["id"]
        init = tmpl.get("init", "")
        read = tmpl.get("read", "")
        pins = tmpl.get("pins", "")

        return f"""/*
 * Test sketch for {sensor_id}
 * Pin info: {pins}
 */

{init}

void setup() {{
  Serial.begin(9600);
  delay(1000);
  Serial.println("{sensor_id} Test Ready");
}}

void loop() {{
  {read.strip()}
  delay(1000);
}}
"""


# Check on import
check_arduino_cli()


if __name__ == "__main__":
    gen = ArduinoCodeGenerator()

    # Test with a sample plan
    sample = """
    ## 材料
    - Arduino Uno
    - DHT22 温湿度传感器
    - HC-SR04 超声波传感器
    - OLED显示屏
    - 蜂鸣器
    """

    sensors = gen.detect_sensors(sample)
    print(f"Detected {len(sensors)} components:")
    for s in sensors:
        print(f"  - {s['id']} (matched: {s['keyword']})")

    sketch = gen.generate_sketch(sensors, "智能气象站")
    if sketch:
        print(f"\nGenerated sketch ({len(sketch)} chars):")
        print(sketch[:1500])
