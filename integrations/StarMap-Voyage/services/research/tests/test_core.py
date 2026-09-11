"""核心模块基础测试"""

import os
import sys
import tempfile

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config():
    """测试配置模块"""
    from backend.core.config import Config, get_config, init_config

    cfg = init_config(debug=True)
    assert cfg.llm.provider == "deepseek"
    assert cfg.llm.model == "deepseek-chat"
    assert cfg.storage.project_root.exists()
    print("✅ 配置模块: 通过")


def test_llm_client_creation():
    """测试 LLM 客户端创建"""
    from backend.core.llm_client import LLMClient

    client = LLMClient()
    assert client.model == "deepseek-chat"
    print("✅ LLM 客户端: 创建成功 (需要 API Key 才能调用)")


def test_code_analysis_with_sample():
    """测试 AST 代码分析（使用示例代码）"""
    from backend.engines.code_engine.ast_analyzer import analyze_project

    # 创建示例 PyTorch 项目
    with tempfile.TemporaryDirectory() as tmpdir:
        # model.py
        model_code = '''
import torch
import torch.nn as nn
import torch.nn.functional as F

class SimpleCNN(nn.Module):
    def __init__(self, num_classes=10):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 32, 3, padding=1)
        self.bn1 = nn.BatchNorm2d(32)
        self.conv2 = nn.Conv2d(32, 64, 3, padding=1)
        self.bn2 = nn.BatchNorm2d(64)
        self.fc1 = nn.Linear(64 * 8 * 8, 256)
        self.fc2 = nn.Linear(256, num_classes)
        self.dropout = nn.Dropout(0.5)

    def forward(self, x):
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.max_pool2d(x, 2)
        x = F.relu(self.bn2(self.conv2(x)))
        x = F.max_pool2d(x, 2)
        x = x.view(x.size(0), -1)
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        return x

class MyDataset(torch.utils.data.Dataset):
    def __init__(self, data_path, transform=None):
        self.data_path = data_path
        self.transform = transform

    def __len__(self):
        return 1000

    def __getitem__(self, idx):
        x = torch.randn(3, 32, 32)
        y = torch.randint(0, 10, (1,)).item()
        return x, y

def train_epoch(model, dataloader, optimizer, criterion, device):
    model.train()
    total_loss = 0
    for batch_idx, (data, target) in enumerate(dataloader):
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(dataloader)

def validate(model, dataloader, criterion, device):
    model.eval()
    total_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in dataloader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            loss = criterion(output, target)
            total_loss += loss.item()
            pred = output.argmax(dim=1)
            correct += pred.eq(target).sum().item()
    return total_loss / len(dataloader), correct / 1000

def preprocess_data(data):
    # data preprocessing
    return data / 255.0

def augment_data(data):
    # data augmentation
    import random
    if random.random() > 0.5:
        data = torch.flip(data, dims=[-1])
    return data

LEARNING_RATE = 0.001
BATCH_SIZE = 64
EPOCHS = 100
'''
        with open(os.path.join(tmpdir, "model.py"), "w") as f:
            f.write(model_code)

        # train.py
        train_code = '''
import torch
import torch.nn as nn
from model import SimpleCNN, MyDataset, train_epoch, validate

def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SimpleCNN(num_classes=10).to(device)
    dataset = MyDataset("./data")
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=64, shuffle=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(100):
        train_loss = train_epoch(model, dataloader, optimizer, criterion, device)
        val_loss, val_acc = validate(model, dataloader, criterion, device)
        print(f"Epoch {{epoch}}: train_loss={{train_loss:.4f}}, val_acc={{val_acc:.4f}}")

if __name__ == "__main__":
    main()
'''
        with open(os.path.join(tmpdir, "train.py"), "w") as f:
            f.write(train_code)

        # 分析项目
        result = analyze_project(tmpdir)

        assert len(result.chunks) > 0, "应至少识别出一些代码块"
        assert result.summary, "应有分析摘要"

        # 检查类别识别
        categories = {c.category.value for c in result.chunks}
        expected = {"model_definition", "forward_propagation", "data_processing",
                     "data_augmentation", "training_loop", "validation_loop",
                     "loss_function"}
        found = expected & categories

        print(f"✅ 代码分析: {len(result.chunks)} 个代码块")
        print(f"   类别: {categories}")
        print(f"   模型模块: {len(result.model_architecture)} 个")
        for mod in result.model_architecture:
            print(f"   - {mod.name}: {len(mod.children)} 个子模块")

        assert "model_definition" in categories, "应识别出模型定义"
        assert "forward_propagation" in categories, "应识别出前向传播"
        assert "training_loop" in categories, "应识别出训练循环"


def test_data_augment_engine():
    """测试数据增强引擎"""
    from backend.engines.experiment_engine.data_adaptor import DataAugmentationEngine

    engine = DataAugmentationEngine()
    ops = engine.get_available_operations()
    assert len(ops) > 0
    print(f"✅ 数据增强引擎: {len(ops)} 个可用操作")
    print(f"   示例: {ops[0]['name']} ({ops[0]['category']})")


def test_visualization_engine():
    """测试可视化引擎"""
    from backend.engines.visualization_engine.plotter import VisualizationEngine

    engine = VisualizationEngine()
    vis_types = engine.get_available_visualizations()
    assert len(vis_types) > 0
    print(f"✅ 可视化引擎: {len(vis_types)} 个可视化类型")


def test_experiment_logger():
    """测试实验日志记录器"""
    from backend.engines.experiment_engine.ablation import ExperimentLogger

    import tempfile
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.db")

    logger = ExperimentLogger(db_path=db_path)

    # 记录实验
    exp_id = logger.log_experiment(
        experiment_name="Test_Experiment_1",
        model_name="SimpleCNN",
        hyperparameters={"lr": 0.001, "batch_size": 64},
        train_metrics={"loss": 0.5, "acc": 0.85},
        test_metrics={"loss": 0.6, "acc": 0.82, "f1": 0.80},
        notes="测试实验",
    )
    assert exp_id == 1

    # 记录 epoch
    logger.log_epoch(exp_id, epoch=1, train_loss=0.7, val_loss=0.65, train_acc=0.70, val_acc=0.72, learning_rate=0.001)
    logger.log_epoch(exp_id, epoch=2, train_loss=0.5, val_loss=0.55, train_acc=0.80, val_acc=0.78, learning_rate=0.001)

    # 获取实验
    experiments = logger.get_all_experiments()
    assert len(experiments) == 1
    assert experiments[0]["experiment_name"] == "Test_Experiment_1"

    # 获取详情
    exp = logger.get_experiment(exp_id)
    assert len(exp.get("epochs", [])) == 2

    print(f"✅ 实验日志: 记录了 {len(experiments)} 个实验, {len(exp['epochs'])} 个 epoch")

    # 清理
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_hyperparam_tuner():
    """测试超参数识别"""
    from backend.engines.experiment_engine.ablation import HyperParameterTuner

    tuner = HyperParameterTuner()
    # 这个测试验证对象创建正常，实际 LLM 调用需要 API Key
    assert tuner is not None
    print("✅ 超参数调优器: 创建成功")


if __name__ == "__main__":
    print("=" * 60)
    print("Research-Copilot-OS 核心模块测试")
    print("=" * 60)
    print()

    tests = [
        test_config,
        test_llm_client_creation,
        test_code_analysis_with_sample,
        test_data_augment_engine,
        test_visualization_engine,
        test_experiment_logger,
        test_hyperparam_tuner,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        print()

    print("=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
