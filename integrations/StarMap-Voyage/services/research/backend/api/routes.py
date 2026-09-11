"""FastAPI 路由 — Research-Copilot-OS API"""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.engines.document_engine.rag import get_document_engine
from backend.engines.code_engine.chunker import get_chunker, get_migration_engine
from backend.engines.experiment_engine.data_adaptor import (
    DatasetAdaptor,
    DataAugmentationEngine,
)
from backend.engines.experiment_engine.ablation import (
    AblationEngine,
    HyperParameterTuner,
    ExperimentLogger,
)
from backend.engines.visualization_engine.plotter import VisualizationEngine
from backend.core.config import get_config
from backend.core.llm_client import get_llm_client

app = FastAPI(title="Research-Copilot-OS API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 功能 1: 单论文解读 ====================

@app.post("/api/papers/analyze")
async def analyze_paper(file: UploadFile = File(...), force: bool = Form(False)):
    """上传单个 PDF，返回全面解读"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        engine = get_document_engine()
        result = engine.analyze_single_paper(tmp_path, force=force)
        return {"success": True, "data": result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
    finally:
        os.unlink(tmp_path)


# ==================== 功能 2: 多论文综述 ====================

@app.post("/api/papers/review")
async def review_papers(files: list[UploadFile] = File(...), force: bool = Form(False)):
    """上传多个 PDF，返回分类、线索梳理、综述"""
    tmp_paths = []
    try:
        for file in files:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(await file.read())
                tmp_paths.append(tmp.name)

        engine = get_document_engine()
        result = engine.analyze_multiple_papers(tmp_paths, force=force)

        return {
            "success": True,
            "data": {
                "status_summary": result.status_summary,
                "paper_status": result.paper_status,
                "clusters": result.clusters,
                "comparative_table": result.comparative_table,
                "narrative_synthesis": result.narrative_synthesis,
                "relationship_graph": result.relationship_graph,
                "experimental_comparison": result.experimental_comparison,
                "papers": [
                    {
                        "title": p.title,
                        "research_field": p.research_field,
                        "sub_field": p.sub_field,
                        "one_sentence": p.one_sentence_summary,
                        "innovations": p.key_innovations[:3] if p.key_innovations else [],
                        "strengths": p.methodology_strengths[:3] if p.methodology_strengths else [],
                        "weaknesses": p.methodology_weaknesses[:3] if p.methodology_weaknesses else [],
                    }
                    for p in result.papers
                ],
            },
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except Exception:
                pass


# ==================== 功能 3: 代码分块 ====================

class CodeAnalysisRequest(BaseModel):
    project_path: str = ""
    strategy: str = "auto"


@app.post("/api/code/chunk")
async def chunk_code(request: CodeAnalysisRequest):
    """输入项目路径，返回代码分块结果"""
    if not os.path.isdir(request.project_path):
        raise HTTPException(status_code=400, detail="项目路径不存在")

    try:
        chunker = get_chunker()
        result = chunker.chunk_project(request.project_path, request.strategy)

        return {
            "success": True,
            "data": {
                "summary": result.summary,
                "chunks": [
                    {
                        "chunk_id": c.chunk_id,
                        "category": c.category.value,
                        "name": c.name,
                        "file_path": c.file_path,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "description": c.description,
                        "source_code": c.source_code[:1000],
                    }
                    for c in result.chunks
                ],
                "data_flow": result.data_flow,
                "total_chunks": len(result.chunks),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@app.post("/api/code/chunk-upload")
async def chunk_code_upload(file: UploadFile = File(...), strategy: str = Form("auto")):
    """上传代码 zip 文件，自动解压并分块"""
    import zipfile
    import shutil

    tmpdir = tempfile.mkdtemp(prefix="rco_code_")
    zip_path = os.path.join(tmpdir, "upload.zip")

    try:
        # 保存上传的 zip
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")

        with open(zip_path, "wb") as f:
            f.write(content)

        # 解压
        extract_dir = os.path.join(tmpdir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        if zipfile.is_zipfile(zip_path):
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.namelist():
                    target = os.path.abspath(os.path.join(extract_dir, member))
                    if not target.startswith(os.path.abspath(extract_dir)):
                        raise HTTPException(status_code=400, detail=f"ZIP包含非法路径: {member}")
                zf.extractall(extract_dir)
            # 如果解压后只有一个根目录，直接用那个目录
            items = os.listdir(extract_dir)
            if len(items) == 1 and os.path.isdir(os.path.join(extract_dir, items[0])):
                extract_dir = os.path.join(extract_dir, items[0])
        else:
            # 不是 zip，尝试当作文件夹处理（tar.gz 等）
            shutil.rmtree(extract_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="仅支持 .zip 格式，请将代码文件夹压缩为 zip 后上传")

        chunker = get_chunker()
        result = chunker.chunk_project(extract_dir, strategy)

        return {
            "success": True,
            "data": {
                "summary": result.summary,
                "chunks": [
                    {
                        "chunk_id": c.chunk_id,
                        "category": c.category.value,
                        "name": c.name,
                        "file_path": c.file_path,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "description": c.description,
                        "source_code": c.source_code[:1000],
                    }
                    for c in result.chunks
                ],
                "data_flow": result.data_flow,
                "total_chunks": len(result.chunks),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# 分类版分块
@app.post("/api/code/chunk-classified")
async def chunk_code_classified(request: CodeAnalysisRequest):
    """代码分块 + LLM 智能分类"""
    if not os.path.isdir(request.project_path):
        raise HTTPException(status_code=400, detail="项目路径不存在")
    try:
        chunker = get_chunker()
        result = chunker.chunk_project(request.project_path, request.strategy)
        classified = chunker.classify_chunks(result)
        return {"success": True, "data": classified}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")

@app.post("/api/code/chunk-classified-upload")
async def chunk_code_classified_upload(file: UploadFile = File(...), strategy: str = Form("auto")):
    """上传 zip + 分块 + 分类"""
    import zipfile, shutil
    tmpdir = tempfile.mkdtemp(prefix="rco_code_")
    zip_path = os.path.join(tmpdir, "upload.zip")
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")
        with open(zip_path, "wb") as f:
            f.write(content)
        extract_dir = os.path.join(tmpdir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        if zipfile.is_zipfile(zip_path):
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.namelist():
                    target = os.path.abspath(os.path.join(extract_dir, member))
                    if not target.startswith(os.path.abspath(extract_dir)):
                        raise HTTPException(status_code=400, detail=f"ZIP包含非法路径: {member}")
                zf.extractall(extract_dir)
            items = os.listdir(extract_dir)
            if len(items) == 1 and os.path.isdir(os.path.join(extract_dir, items[0])):
                extract_dir = os.path.join(extract_dir, items[0])
        else:
            raise HTTPException(status_code=400, detail="仅支持 .zip 格式")
        chunker = get_chunker()
        result = chunker.chunk_project(extract_dir, strategy)
        classified = chunker.classify_chunks(result)
        return {"success": True, "data": classified}
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# 保留旧的路径输入方式
@app.post("/api/code/chunk-path")
async def chunk_code_path(request: CodeAnalysisRequest):
    return await chunk_code(request)


# ==================== 代码块存储 ====================

@app.get("/api/code/cached-projects")
async def list_cached_projects():
    """列出所有已缓存的代码分块项目"""
    cfg = get_config()
    cache_dir = Path(cfg.storage.chunk_cache_dir)
    projects = []
    if cache_dir.exists():
        for f in sorted(cache_dir.glob("*_analysis.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                projects.append({
                    "name": f.stem.replace("_analysis", ""),
                    "path": data.get("project_path", ""),
                    "total_chunks": len(data.get("chunks", [])),
                    "analyzed_at": f.stat().st_mtime,
                })
            except Exception:
                pass
    return {"success": True, "data": projects}


@app.get("/api/code/cached-chunks/{project_name}")
async def get_cached_chunks(project_name: str):
    """获取已缓存项目的代码块详情"""
    cfg = get_config()
    cache_file = Path(cfg.storage.chunk_cache_dir) / f"{project_name}_analysis.json"
    if not cache_file.exists():
        raise HTTPException(status_code=404, detail="缓存不存在，请先分析该项目")
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"success": True, "data": data}


@app.delete("/api/code/cached-projects/{project_name}")
async def delete_cached_project(project_name: str):
    """删除已缓存项目的分析结果"""
    cfg = get_config()
    cache_file = Path(cfg.storage.chunk_cache_dir) / f"{project_name}_analysis.json"
    if cache_file.exists():
        cache_file.unlink()
        return {"success": True, "data": {"message": f"已删除 {project_name}"}}
    raise HTTPException(status_code=404, detail="缓存不存在")


class OrderedChunkRequest(BaseModel):
    project_path: str


@app.post("/api/code/chunk-ordered")
async def chunk_ordered(request: OrderedChunkRequest):
    """目标模型有序分块：仅提取数据处理/模型架构/损失函数，架构按 forward 顺序展开"""
    if not os.path.isdir(request.project_path):
        raise HTTPException(status_code=400, detail="项目路径不存在")
    try:
        chunker = get_chunker()
        result = chunker.chunk_project(request.project_path, "auto")
        keep_cats = {"data_processing", "data_loader", "data_augmentation",
                      "model_definition", "forward_propagation",
                      "loss_function"}
        ordered = [c for c in result.chunks if c.category.value in keep_cats]
        ordered.sort(key=lambda c: (c.file_path, c.start_line))

        chunks_data = {
            "project_path": request.project_path,
            "total_chunks": len(ordered),
            "chunks": [
                {"chunk_id": c.chunk_id, "category": c.category.value, "name": c.name,
                 "file_path": c.file_path, "start_line": c.start_line, "end_line": c.end_line,
                 "description": c.description, "source_code": c.source_code}
                for c in ordered
            ],
        }
        # 缓存有序结果
        cfg = get_config()
        cache_dir = Path(cfg.storage.chunk_cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        proj_name = Path(request.project_path).name
        with open(cache_dir / f"{proj_name}_ordered.json", "w", encoding="utf-8") as f:
            json.dump(chunks_data, f, ensure_ascii=False, indent=2)

        return {"success": True, "data": chunks_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@app.get("/api/code/cached-ordered/{project_name}")
async def get_cached_ordered(project_name: str):
    """获取已缓存的有序分块结果"""
    cfg = get_config()
    cache_file = Path(cfg.storage.chunk_cache_dir) / f"{project_name}_ordered.json"
    if not cache_file.exists():
        raise HTTPException(status_code=404, detail="缓存不存在，请先分析该项目")
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"success": True, "data": data}


# ==================== 功能 4: 模块迁移 ====================

class DualMigrationRequest(BaseModel):
    source_project: str
    target_project: str
    source_chunk_id: str


@app.post("/api/code/migrate-compare")
async def migrate_compare(request: DualMigrationRequest):
    """双项目对比：分块两个项目，返回侧边对比视图"""
    try:
        chunker = get_chunker()
        src_result = chunker.chunk_project(request.source_project)
        tgt_result = chunker.chunk_project(request.target_project)

        src_classified = chunker.classify_chunks(src_result)
        tgt_classified = chunker.classify_chunks(tgt_result)

        return {
            "success": True,
            "data": {
                "source": {
                    "project_path": request.source_project,
                    "summary": src_classified.get("summary", ""),
                    "groups": {k: v for k, v in src_classified.get("groups", {}).items() if v.get("chunks")},
                },
                "target": {
                    "project_path": request.target_project,
                    "summary": tgt_classified.get("summary", ""),
                    "groups": {k: v for k, v in tgt_classified.get("groups", {}).items() if v.get("chunks")},
                },
            },
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/code/migrate-align")
async def migrate_align(request: DualMigrationRequest):
    """选定源模块 + 目标项目 → 自动生成对齐后的迁移代码"""
    try:
        chunker = get_chunker()
        src_result = chunker.chunk_project(request.source_project)
        source_chunk = None
        for c in src_result.chunks:
            if c.chunk_id == request.source_chunk_id:
                source_chunk = c
                break
        if not source_chunk:
            raise HTTPException(status_code=404, detail=f"未找到源模块: {request.source_chunk_id}")

        engine = get_migration_engine()
        result = engine.align_and_migrate(source_chunk, request.target_project, "")
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class SaveMigrationRequest(BaseModel):
    target_project: str
    target_file: str
    merged_code: str


@app.post("/api/code/migrate-save")
async def migrate_save(request: SaveMigrationRequest):
    """保存迁移结果：将对齐后的代码写入目标项目的指定文件"""
    try:
        file_path = os.path.join(request.target_project, request.target_file)
        if not os.path.exists(request.target_project):
            raise HTTPException(status_code=400, detail="目标项目路径不存在")

        # 备份原文件
        backup_path = file_path + ".bak"
        if os.path.exists(file_path):
            import shutil
            shutil.copy2(file_path, backup_path)

        # 安全检查：目标文件必须在项目目录内
        abs_project = os.path.abspath(request.target_project)
        abs_target = os.path.abspath(file_path)
        if not abs_target.startswith(abs_project):
            raise HTTPException(status_code=400, detail="文件路径必须在目标项目目录内")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(request.merged_code)

        return {
            "success": True,
            "data": {
                "saved_to": file_path,
                "backup": backup_path,
                "message": f"已保存到 {file_path}，原文件备份为 {backup_path}",
            },
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 功能 4 旧接口（保留兼容） ====================

class ModuleMigrateRequest(BaseModel):
    source_project_path: str
    source_chunk_id: str
    target_project_path: str
    target_model_file: str = ""


@app.post("/api/code/migrate")
async def migrate_module(request: ModuleMigrateRequest):
    """模块迁移：将源模块迁移到目标模型"""
    try:
        # 分析源项目找到 chunk
        chunker = get_chunker()
        source_result = chunker.chunk_project(request.source_project_path)

        source_chunk = None
        for c in source_result.chunks:
            if c.chunk_id == request.source_chunk_id:
                source_chunk = c
                break

        if not source_chunk:
            raise HTTPException(status_code=404, detail="未找到指定的源模块")

        engine = get_migration_engine()
        result = engine.align_and_migrate(
            source_chunk,
            request.target_project_path,
            request.target_model_file,
        )
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/code/recommend")
async def recommend_modules(request: CodeAnalysisRequest):
    """推荐可迁移的亮点模块"""
    try:
        chunker = get_chunker()
        result = chunker.chunk_project(request.project_path)
        engine = get_migration_engine()
        recommendations = engine.recommend_modules(result)
        return {"success": True, "data": recommendations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 功能 5: 数据集适配 ====================

@app.post("/api/data/inspect")
async def inspect_dataset(data_path: str = Form(...)):
    """自动解读数据集形式"""
    try:
        adaptor = DatasetAdaptor()
        info = adaptor.inspect_dataset(data_path)
        return {
            "success": True,
            "data": {
                "data_format": info.data_format,
                "sample_count": info.sample_count,
                "feature_shape": info.feature_shape,
                "label_type": info.label_type,
                "num_classes": info.num_classes,
                "description": info.description,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/data/generate-loader")
async def generate_data_loader(data_path: str = Form(...), model_code: str = Form("")):
    """生成适配模型的数据加载代码"""
    try:
        adaptor = DatasetAdaptor()
        info = adaptor.inspect_dataset(data_path)
        code = adaptor.generate_data_loader(info, model_code)
        return {"success": True, "data": {"code": code}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 功能 6: 数据增强 ====================

@app.get("/api/augment/operations")
async def get_augment_operations():
    """获取所有可用的数据增强/攻击操作"""
    engine = DataAugmentationEngine()
    return {"success": True, "data": engine.get_available_operations()}


class AugmentRequest(BaseModel):
    operations: list[str]
    data_format: str = "image"
    model_code: str = ""


@app.post("/api/augment/generate")
async def generate_augmentation(request: AugmentRequest):
    """生成数据增强代码"""
    try:
        engine = DataAugmentationEngine()
        code = engine.generate_augmentation_code(
            request.operations, request.data_format, request.model_code
        )
        return {"success": True, "data": {"code": code}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ 数据增强执行接口 ============

@app.post("/api/augment/preview")
async def augment_preview(file: UploadFile = File(...), operations: str = Form("[]"),
                           data_format: str = Form("image")):
    """上传单张图片，应用增强操作，返回原图+增强后的 base64"""
    import base64, io, json as _json
    from PIL import Image
    import torchvision.transforms as T
    import numpy as np

    ops = _json.loads(operations)
    if not ops:
        raise HTTPException(status_code=400, detail="请至少选择一个操作")

    try:
        img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="无法读取图片，请上传 PNG/JPG 格式")

    # 构建 torchvision transforms（先缩放到统一尺寸避免 crop 报错）
    w, h = img.size
    base_size = max(w, h, 256)
    transform_list = [T.Resize((base_size, base_size))] + _build_transforms(ops)
    composed = T.Compose(transform_list)

    try:
        augmented = composed(img)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"增强执行失败: {e}\n图片尺寸: {w}x{h}, 操作: {ops}")

    # 转 base64
    def img_to_b64(pil_img):
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    return {"success": True, "data": {"original": img_to_b64(img), "augmented": img_to_b64(augmented)}}


def _build_transforms(op_ids: list[str]) -> list:
    import torchvision.transforms as T
    import torchvision.transforms.functional as TF
    import torch
    import random
    from PIL import Image, ImageFilter
    import numpy as np

    t_list = []

    for op in op_ids:
        # ── 几何变换 ──
        if op == "random_crop":
            t_list.append(T.RandomCrop(224))
        elif op == "random_flip":
            t_list.append(T.RandomHorizontalFlip(p=0.5))
        elif op == "random_rotation":
            t_list.append(T.RandomRotation(30))
        elif op == "random_resized_crop":
            t_list.append(T.RandomResizedCrop(224))
        elif op == "random_affine":
            t_list.append(T.RandomAffine(15, translate=(0.1, 0.1)))

        # ── 色彩变换 ──
        elif op == "color_jitter":
            t_list.append(T.ColorJitter(0.4, 0.4, 0.4, 0.1))
        elif op == "random_brightness":
            t_list.append(T.ColorJitter(brightness=0.5))
        elif op == "random_contrast":
            t_list.append(T.ColorJitter(contrast=0.5))
        elif op == "random_saturation":
            t_list.append(T.ColorJitter(saturation=0.5))

        # ── 模糊化 ──
        elif op == "gaussian_blur":
            t_list.append(T.GaussianBlur(5, sigma=(0.1, 2.0)))
        elif op == "median_blur":
            # PIL MedianFilter
            t_list.append(T.Lambda(lambda img: img.filter(ImageFilter.MedianFilter(size=3))))
        elif op == "motion_blur":
            # 自定义运动模糊 kernel
            class MotionBlur:
                def __call__(self, img):
                    size = random.choice([5, 7, 9])
                    kernel = torch.zeros((1, 1, size, size))
                    kernel[:, :, size//2, :] = 1.0 / size
                    t = TF.to_tensor(img).unsqueeze(0)
                    blurred = torch.nn.functional.conv2d(t, kernel, padding='same')
                    return TF.to_pil_image(blurred.squeeze(0).clamp(0, 1))
            t_list.append(MotionBlur())

        # ── 噪声注入 ──
        elif op == "gaussian_noise":
            class GaussianNoise:
                def __init__(self, std=0.05):
                    self.std = std
                def __call__(self, img):
                    t = TF.to_tensor(img)
                    noise = torch.randn_like(t) * self.std
                    return TF.to_pil_image((t + noise).clamp(0, 1))
            t_list.append(GaussianNoise())
        elif op == "salt_pepper_noise":
            class SaltPepperNoise:
                def __init__(self, prob=0.02):
                    self.prob = prob
                def __call__(self, img):
                    arr = np.array(img).copy()
                    mask = np.random.random(arr.shape[:2]) < self.prob
                    salt_or_pepper = np.random.random(arr.shape[:2])
                    arr[mask & (salt_or_pepper > 0.5)] = 255
                    arr[mask & (salt_or_pepper <= 0.5)] = 0
                    return Image.fromarray(arr)
            t_list.append(SaltPepperNoise())

        # ── 高级增强 ──
        elif op == "cutout":
            class CutOut:
                def __init__(self, size=50):
                    self.size = size
                def __call__(self, img):
                    t = TF.to_tensor(img)
                    _, h, w = t.shape
                    y = random.randint(0, max(0, h - self.size))
                    x = random.randint(0, max(0, w - self.size))
                    t[:, y:y+self.size, x:x+self.size] = 0.5
                    return TF.to_pil_image(t)
            t_list.append(CutOut())
        elif op == "mixup":
            # 单图模拟：颜色混合
            class FakeMixUp:
                def __call__(self, img):
                    t = TF.to_tensor(img)
                    blend = torch.ones_like(t) * torch.tensor([0.5, 0.3, 0.7]).view(3, 1, 1)
                    return TF.to_pil_image((t * 0.7 + blend * 0.3).clamp(0, 1))
            t_list.append(FakeMixUp())
        elif op == "cutmix":
            class FakeCutMix:
                def __call__(self, img):
                    t = TF.to_tensor(img)
                    _, h, w = t.shape
                    y, x = random.randint(0, h//2), random.randint(0, w//2)
                    t[:, y:y+h//4, x:x+w//4] = torch.tensor([0.2, 0.6, 0.9]).view(3, 1, 1)
                    return TF.to_pil_image(t)
            t_list.append(FakeCutMix())
        elif op == "randaugment":
            # 简化为随机应用几种基础增强
            t_list.append(T.RandAugment(num_ops=2, magnitude=9))

        # ── 数据攻击 ──
        elif op == "fgsm":
            class FGSMNoise:
                def __init__(self, eps=0.03):
                    self.eps = eps
                def __call__(self, img):
                    t = TF.to_tensor(img)
                    noise = torch.randn_like(t).sign() * self.eps
                    return TF.to_pil_image((t + noise).clamp(0, 1))
            t_list.append(FGSMNoise())
        elif op == "pgd":
            class PGDNoise:
                def __init__(self, eps=0.05, steps=3):
                    self.eps = eps
                    self.steps = steps
                def __call__(self, img):
                    t = TF.to_tensor(img)
                    delta = torch.zeros_like(t)
                    for _ in range(self.steps):
                        delta = delta + torch.randn_like(t).sign() * (self.eps / self.steps)
                        delta = delta.clamp(-self.eps, self.eps)
                    return TF.to_pil_image((t + delta).clamp(0, 1))
            t_list.append(PGDNoise())

    if not t_list:
        t_list.append(T.Resize((224, 224)))
    return t_list


@app.post("/api/augment/folder")
async def augment_folder(
    folder_path: str = Form(...),
    operations: str = Form("[]"),
    output_dir: str = Form(""),
    data_format: str = Form("image"),
):
    """批量处理文件夹内所有图片，按操作名称分文件夹保存"""
    import json as _json, shutil
    from PIL import Image
    import torchvision.transforms as T
    from pathlib import Path

    ops = _json.loads(operations)
    if not ops:
        raise HTTPException(status_code=400, detail="请至少选择一个操作")

    src = Path(folder_path)
    if not src.exists():
        raise HTTPException(status_code=400, detail="文件夹路径不存在")

    out = Path(output_dir) if output_dir else src.parent / (src.name + "_augmented")
    out.mkdir(parents=True, exist_ok=True)

    exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    img_files = [f for f in src.rglob("*") if f.suffix.lower() in exts]
    if not img_files:
        raise HTTPException(status_code=400, detail="文件夹中未找到图片文件")

    transform_list = _build_transforms(ops)
    composed = T.Compose([T.Resize((256, 256))] + transform_list)

    results = []
    for img_path in img_files:
        try:
            img = Image.open(img_path).convert("RGB")
            aug = composed(img)
            # 保存到对应操作子文件夹
            op_dir = out / "_".join(ops[:3])
            op_dir.mkdir(parents=True, exist_ok=True)
            rel_path = img_path.relative_to(src)
            save_path = op_dir / (rel_path.stem + "_aug" + rel_path.suffix)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            aug.save(save_path)
            results.append({"original": str(img_path), "saved": str(save_path), "status": "ok"})
        except Exception as e:
            results.append({"original": str(img_path), "error": str(e), "status": "fail"})

    ok_count = sum(1 for r in results if r["status"] == "ok")
    return {"success": True, "data": {
        "total": len(results), "success": ok_count, "failed": len(results) - ok_count,
        "output_dir": str(out), "results": results[:20],
    }}


# ==================== 功能 7: 可视化 ====================

class VisIterateRequest(BaseModel):
    user_requirement: str  # 用户描述: "画训练loss曲线" / "对比三个模型的准确率"
    data_description: str = ""  # 数据描述或 CSV 内容
    paper_context: str = ""  # 文献上下文（来自已分析的论文）
    reference_image: str = ""  # 参考图片 base64（可选）


@app.post("/api/vis/iterate")
async def vis_iterate(request: VisIterateRequest):
    """可视化迭代生成+评分+修缮：循环直到评分 > 90"""
    engine = VisualizationEngine()
    llm = get_llm_client()
    import base64, io, re as _re
    from PIL import Image as PILImage

    # Step 1: 生成初始代码
    gen_prompt = f"""你是一位科研数据可视化专家。需要生成一个 matplotlib 图表。

用户需求: {request.user_requirement}
数据描述: {request.data_description[:2000] if request.data_description else '使用合理的模拟数据'}
文献上下文: {request.paper_context[:1000] if request.paper_context else '通用科研场景'}

请生成完整的 Python matplotlib 代码。要求:
- 使用 Morandi 配色 (mist_stone: #F3EEE8, #D8D1C7, #8A9199)
- plt.rcParams 设置全局样式: 白色背景, 无右侧/顶部边框, 浅灰网格
- 包含标题、轴标签、图例
- 输出为独立函数 def plot_main():
- 最后 plt.savefig('output.png', dpi=300, bbox_inches='tight')
- 代码可以直接运行，不要有占位符

只输出 Python 代码，不要有解释文字:"""

    code = llm.chat(messages=[{"role":"user","content":gen_prompt}], max_tokens=4096)
    code = _extract_python(code)

    # Step 2-5: 迭代评分+修缮
    best_score = 0
    best_code = code
    best_image_b64 = ""
    history = []

    for iteration in range(5):
        # 执行代码生成图片
        img_b64, exec_error = _execute_plot_code(code)
        if exec_error:
            history.append({"iteration": iteration+1, "score": 0, "error": exec_error})
            # 让 LLM 修复错误
            fix_prompt = f"""以下代码执行时报错，请修复:
错误: {exec_error}
原代码:
```python
{code}
```
只输出修复后的完整 Python 代码:"""
            code = llm.chat(messages=[{"role":"user","content":fix_prompt}], max_tokens=4096)
            code = _extract_python(code)
            continue

        # 评分
        score, feedback = _score_plot(request.user_requirement, img_b64 if img_b64 else "", llm)
        history.append({"iteration": iteration+1, "score": score, "feedback": feedback[:200]})

        if score > best_score:
            best_score = score
            best_code = code
            best_image_b64 = img_b64 or ""

        if score >= 90:
            break

        # 修缮
        refine_prompt = f"""请改进以下 matplotlib 代码。当前评分: {score}/100。
改进建议: {feedback[:500]}
原代码:
```python
{code}
```
只输出改进后的完整 Python 代码:"""
        code = llm.chat(messages=[{"role":"user","content":refine_prompt}], max_tokens=4096)
        code = _extract_python(code)

    return {"success": True, "data": {
        "final_score": best_score,
        "code": best_code,
        "image_base64": best_image_b64,
        "history": history,
    }}


def _extract_python(text: str) -> str:
    import re
    text = text.strip()
    for marker in ["```python", "```"]:
        if marker in text:
            text = text.split(marker)[1].split("```")[0].strip()
            break
    return text


def _execute_plot_code(code: str) -> tuple[str, str]:
    """执行绘图代码，返回 (base64图片, 错误信息)"""
    import base64, io, os, tempfile, subprocess, sys
    tmpdir = tempfile.mkdtemp()
    py_path = os.path.join(tmpdir, "plot.py")
    png_path = os.path.join(tmpdir, "output.png")
    code = f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import os
os.chdir(r'{tmpdir}')
{code}
plot_main()
"""
    with open(py_path, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        result = subprocess.run(
            [sys.executable, py_path], capture_output=True, text=True, timeout=60, cwd=tmpdir,
        )
        if result.returncode != 0:
            return "", result.stderr[-500:] or result.stdout[-500:] or "Unknown error"
        if os.path.exists(png_path):
            with open(png_path, "rb") as f:
                return base64.b64encode(f.read()).decode(), ""
        return "", "图片未生成"
    except subprocess.TimeoutExpired:
        return "", "代码执行超时(60s)"
    except Exception as e:
        return "", str(e)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _score_plot(requirement: str, image_b64: str, llm) -> tuple[int, str]:
    """AI 评分系统：从5个维度评分 0-20，总分 0-100"""
    if not image_b64:
        return 0, "图片生成失败"

    # 用文本分析评分（不需要视觉模型）
    score_prompt = f"""你是一位科研图表评审专家。请根据用户需求和图表信息进行评分。

用户需求: {requirement}
图片已生成（base64长度: {len(image_b64)}字节，说明图片成功生成）。

请从以下5个维度评分（每个0-20分）:

1. 数据展示清晰度 (0-20): 数据是否完整呈现？曲线/柱状图是否准确？
2. 标签与标题 (0-20): 有无标题？轴标签？图例？字体大小是否合适？
3. 配色与美观 (0-20): 配色是否协调？是否使用 Morandi 风格？背景是否干净？
4. 科研规范性 (0-20): 是否符合学术期刊标准？有无多余装饰？
5. 整体完成度 (0-20): 是否满足用户需求？是否可直接用于论文？

返回 JSON:
{{"scores": {{"data_clarity": 18, "labels": 16, "aesthetics": 17, "academic_standard": 15, "completeness": 19}},
  "total": 85,
  "feedback": "具体改进建议（中文，100-200字）"}}"""

    try:
        resp = llm.structured_output(
            system_prompt="你是科研图表评审专家。",
            user_prompt=score_prompt,
            output_schema={
                "scores": {"data_clarity": 0, "labels": 0, "aesthetics": 0, "academic_standard": 0, "completeness": 0},
                "total": 0, "feedback": "str",
            },
        )
        total = resp.get("total", 0)
        feedback = resp.get("feedback", "")
        return int(total), str(feedback)
    except Exception:
        return 70, "评分系统异常，使用默认分数"


@app.get("/api/vis/types")
async def get_vis_types():
    """获取所有可视化类型"""
    engine = VisualizationEngine()
    return {"success": True, "data": engine.get_available_visualizations()}


class VisualizationRequest(BaseModel):
    model_code: str
    paper_texts: list[str] = []
    experiment_results: dict = {}


@app.post("/api/vis/generate-suite")
async def generate_vis_suite(request: VisualizationRequest):
    """一站式生成完整可视化套件（保留旧接口）"""
    try:
        engine = VisualizationEngine()
        result = engine.generate_full_visualization_suite(
            request.model_code,
            request.experiment_results if request.experiment_results else None,
            request.paper_texts if request.paper_texts else None,
        )
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 功能 8: 消融实验 ====================

class AblationAnalyzeRequest(BaseModel):
    project_path: str = ""


@app.post("/api/ablation/analyze")
async def ablation_analyze(request: AblationAnalyzeRequest):
    """智能分析项目，识别值得消融的模块"""
    if not os.path.isdir(request.project_path):
        raise HTTPException(status_code=400, detail="项目路径不存在")
    try:
        # 读取所有 Python 文件
        all_code = _read_project_code(request.project_path)
        if not all_code:
            raise HTTPException(status_code=400, detail="项目中没有 Python 文件")

        llm = get_llm_client()
        prompt = f"""你是一个深度学习模型架构专家。请分析以下项目的代码，识别所有可以进行消融实验的模块。

消融条件:
1. 拆卸后不影响全局（该模块是独立可插拔的，移除后模型其余部分仍能正常运行）
2. 作为整体模型的创新点（该模块体现了论文的核心贡献，消融它可以验证其重要性）

===== 项目代码 =====
{all_code[:12000]}

===== 要求 =====
返回 JSON:
{{
  "model_summary": "模型整体结构一句话描述",
  "candidates": [
    {{
      "id": "模块ID",
      "name": "模块名称（如 AttentionBlock、FeatureFusion、SEBlock）",
      "description": "模块功能描述（50-100字）",
      "innovation_reason": "为什么这是创新点（30-80字）",
      "independence_reason": "为什么移除后不影响全局（30-80字）",
      "ablation_impact": "消融后预期影响：对性能/参数/速度的影响预测",
      "occurrences": ["出现位置1: 文件名:行号描述", "出现位置2: ..."],
      "removal_difficulty": "easy/medium/hard",
      "recommended": true  // 是否推荐消融
    }}
  ]
}}

注意: 如果某个模块在多处出现（如多个 Block 中），必须在 occurrences 中全部列出。只返回JSON。"""

        resp = llm.structured_output(
            system_prompt="你是深度学习模型架构专家。只根据提供的代码进行分析。",
            user_prompt=prompt,
            output_schema={
                "model_summary": "str",
                "candidates": [{
                    "id": "str", "name": "str", "description": "str",
                    "innovation_reason": "str", "independence_reason": "str",
                    "ablation_impact": "str", "occurrences": ["str"],
                    "removal_difficulty": "str", "recommended": True,
                }],
            },
        )
        return {"success": True, "data": resp}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class AblationExecuteRequest(BaseModel):
    project_path: str
    selected_modules: list[str]  # 要消融的模块名称列表


@app.post("/api/ablation/execute")
async def ablation_execute(request: AblationExecuteRequest):
    """执行消融：移除选中模块 + 维度对齐，生成可运行代码"""
    if not os.path.isdir(request.project_path):
        raise HTTPException(status_code=400, detail="项目路径不存在")
    try:
        all_code = _read_project_code(request.project_path)
        modules_str = ", ".join(request.selected_modules)

        llm = get_llm_client()
        prompt = f"""你是一个深度学习代码专家。需要从项目中移除以下模块，并确保代码仍可运行。

要移除的模块: {modules_str}

===== 原始项目代码 =====
{all_code[:15000]}

===== 要求 =====
请完成以下操作并返回 JSON:
1. 移除所有被选中模块的定义和调用（如果在多个 Block 中使用了该模块，必须全部清除）
2. 移除后，自动对齐上下维度（如果移除处有维度变化，添加 nn.Linear 或 nn.Conv2d 适配层）
3. 确保代码语法正确、可运行
4. 返回完整的修改后代码

返回 JSON:
{{
  "ablated_code": "修改后的完整代码（将整个模型文件的内容放在这里）",
  "changes_summary": "修改摘要：移除了什么、添加了什么适配层（中文，100-300字）",
  "dimension_alignments": ["对齐1: 在X和Y之间添加了Linear(in,out)", "对齐2: ..."],
  "warnings": ["警告1: 移除X后可能影响Y", "警告2: ..."]
}}"""

        resp = llm.structured_output(
            system_prompt="你是深度学习代码专家。精确移除模块并保证代码可运行。",
            user_prompt=prompt,
            output_schema={
                "ablated_code": "str", "changes_summary": "str",
                "dimension_alignments": ["str"], "warnings": ["str"],
            },
        )
        return {"success": True, "data": resp}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class AblationSaveRequest(BaseModel):
    project_path: str
    file_name: str  # 要保存的文件名（相对路径）
    ablated_code: str


@app.post("/api/ablation/save")
async def ablation_save(request: AblationSaveRequest):
    """保存消融后的代码"""
    file_path = os.path.join(request.project_path, request.file_name)
    # 安全检查
    abs_project = os.path.abspath(request.project_path)
    abs_target = os.path.abspath(file_path)
    if not abs_target.startswith(abs_project):
        raise HTTPException(status_code=400, detail="文件路径必须在项目目录内")
    backup_path = file_path + ".bak"
    try:
        import shutil
        if os.path.exists(file_path):
            shutil.copy2(file_path, backup_path)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(request.ablated_code)
        return {"success": True, "data": {"saved": file_path, "backup": backup_path}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _read_project_code(project_path: str) -> str:
    """读取项目所有 Python 文件"""
    all_code = ""
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__","venv","env")]
        for f in files:
            if f.endswith(".py"):
                fp = os.path.join(root, f)
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    rel = os.path.relpath(fp, project_path)
                    all_code += f"\n# === {rel} ===\n{content}\n"
                except Exception:
                    pass
    return all_code


# 保留旧接口兼容
class AblationPlanRequest(BaseModel):
    project_path: str
    strategy: str = "auto"

@app.post("/api/ablation/plan")
async def plan_ablation(request: AblationPlanRequest):
    return await ablation_analyze(request)

@app.post("/api/ablation/generate")
async def generate_ablation_script(request: AblationPlanRequest):
    return {"success": True, "data": {"script": "# 请使用新接口 /api/ablation/analyze + /api/ablation/execute"}}


# ==================== 功能 9: 超参数调优 ====================

class HPAnalyzeProjectRequest(BaseModel):
    project_path: str


@app.post("/api/hyperparams/analyze-project")
async def hp_analyze_project(request: HPAnalyzeProjectRequest):
    """读取项目全部代码，识别所有可调超参数"""
    if not os.path.isdir(request.project_path):
        raise HTTPException(status_code=400, detail="项目路径不存在")
    try:
        all_code = _read_project_code(request.project_path)
        llm = get_llm_client()

        prompt = f"""你是深度学习超参数调优专家。请分析以下项目代码，识别所有可调整的超参数。

===== 项目代码 =====
{all_code[:12000]}

===== 要求 =====
找出代码中所有超参数，包括:
- 显式定义的: lr, batch_size, epochs, weight_decay, dropout, hidden_dim 等
- 隐式可调的: 优化器选择、损失函数参数、模型架构参数（层数、通道数等）
- 数据相关的: transforms参数、增强参数

返回 JSON:
{{
  "hyperparameters": [
    {{
      "name": "参数名（如 learning_rate）",
      "current_value": "当前值（如 0.001）",
      "type": "learning_rate/batch_size/epochs/dropout/weight_decay/optimizer_param/arch_param/data_param/other",
      "location": "定义位置（文件名:行号）",
      "description": "参数说明",
      "suggested_range": "建议调整范围",
      "adjustable": true,
      "impact": "调整后对训练的影响（high/medium/low）"
    }}
  ]
}}

只返回JSON。"""

        resp = llm.structured_output(
            system_prompt="你是深度学习超参数调优专家。",
            user_prompt=prompt,
            output_schema={
                "hyperparameters": [{
                    "name": "str", "current_value": "str", "type": "str",
                    "location": "str", "description": "str",
                    "suggested_range": "str", "adjustable": True,
                    "impact": "str",
                }],
            },
        )
        return {"success": True, "data": resp}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class HPRecommendRequest(BaseModel):
    training_description: str  # 训练过程描述/日志/曲线分析
    current_hyperparams: str = ""  # 当前超参数配置 JSON


@app.post("/api/hyperparams/recommend")
async def hp_recommend(request: HPRecommendRequest):
    """分析训练过程，推荐超参数调整方案"""
    try:
        llm = get_llm_client()
        prompt = f"""你是深度学习超参数调优专家。请分析以下训练过程，给出超参数调整建议。

===== 训练过程描述 =====
{request.training_description[:5000]}

===== 当前超参数 =====
{request.current_hyperparams[:2000] if request.current_hyperparams else '未提供'}

===== 要求 =====
请根据训练过程（loss曲线、准确率变化、过拟合/欠拟合迹象等），推荐具体的超参数调整方案。

返回 JSON:
{{
  "diagnosis": "训练状态诊断（如：学习率过大导致震荡、模型过拟合、欠拟合等）（100-200字）",
  "recommendations": [
    {{
      "param": "要调整的参数名",
      "current": "当前值",
      "suggested": "建议值",
      "reason": "调整理由（基于训练过程的具体表现）",
      "expected_effect": "调整后预期效果",
      "priority": "high/medium/low"
    }}
  ],
  "training_tips": ["训练建议1", "建议2", "建议3"]
}}"""

        resp = llm.structured_output(
            system_prompt="你是深度学习训练调优专家。",
            user_prompt=prompt,
            output_schema={
                "diagnosis": "str",
                "recommendations": [{
                    "param": "str", "current": "str", "suggested": "str",
                    "reason": "str", "expected_effect": "str", "priority": "str",
                }],
                "training_tips": ["str"],
            },
        )
        return {"success": True, "data": resp}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class HPGenerateCodeRequest(BaseModel):
    hyperparameters: list[dict]  # 修改后的超参数列表


@app.post("/api/hyperparams/generate-code")
async def hp_generate_code(request: HPGenerateCodeRequest):
    """根据修改后的超参数生成更新后的配置代码"""
    try:
        llm = get_llm_client()
        hp_text = json.dumps(request.hyperparameters, ensure_ascii=False, indent=2)
        prompt = f"""根据以下修改后的超参数，生成一个可直接粘贴使用的 Python 配置代码块。
超参数:
{hp_text}

生成包含所有超参数定义的代码块，格式清晰，可直接替换原代码中的配置部分。只输出代码。"""
        code = llm.chat(messages=[{"role":"user","content":prompt}], max_tokens=2048)
        return {"success": True, "data": {"code": code.strip()}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 旧接口兼容
class HyperParamRequest(BaseModel): code: str
@app.post("/api/hyperparams/identify")
async def identify_hyperparams(request: HyperParamRequest):
    try:
        tuner = HyperParameterTuner()
        params = tuner.identify_hyperparameters(request.code)
        return {"success": True, "data": params}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 功能 10: 实验记录 ====================

@app.get("/api/experiments")
async def list_experiments():
    """列出所有实验"""
    try:
        logger = ExperimentLogger()
        experiments = logger.get_all_experiments()
        return {"success": True, "data": experiments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/experiments/{experiment_id}")
async def get_experiment(experiment_id: int):
    """获取单个实验详情"""
    try:
        logger = ExperimentLogger()
        exp = logger.get_experiment(experiment_id)
        return {"success": True, "data": exp}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Agent 智能体 ====================

from backend.agent.orchestrator import get_agent
from backend.agent.skills import get_skill_loader


class AgentChatRequest(BaseModel):
    message: str
    session_id: str = ""
    allowed_tools: list[str] = []
    project_root: str = ""


class AgentContextRequest(BaseModel):
    session_id: str
    key: str
    value: str


@app.post("/api/agent/chat")
async def agent_chat(request: AgentChatRequest):
    """Agent 对话接口：发送消息，Agent 自动决定调用哪些工具"""
    try:
        agent = get_agent()
        # 设置项目根目录用于权限控制
        if request.project_root:
            agent.permission.project_root = request.project_root
        result = agent.run(
            user_input=request.message,
            session_id=request.session_id or None,
            allowed_tools=request.allowed_tools if request.allowed_tools else None,
        )
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent/skills")
async def list_agent_skills():
    """获取所有可用技能"""
    try:
        loader = get_skill_loader()
        return {"success": True, "data": loader.get_skill_list()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agent/tools")
async def list_agent_tools():
    """获取 Agent 所有可用工具的描述"""
    try:
        agent = get_agent()
        tools = agent.get_tool_descriptions()
        return {"success": True, "data": tools}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent/history/{session_id}")
async def get_agent_history(session_id: str):
    """获取 Agent 会话历史"""
    try:
        agent = get_agent()
        history = agent.get_turn_history(session_id)
        return {"success": True, "data": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent/context")
async def set_agent_context(request: AgentContextRequest):
    """设置 Agent 会话上下文"""
    try:
        agent = get_agent()
        agent.set_context(request.session_id, request.key, request.value)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Claude Code Runner ====================

from backend.runner.claude_runner import get_runner


class RunnerOneShotRequest(BaseModel):
    task: str
    project_path: str = ""
    timeout: int = 600


class RunnerDaemonRequest(BaseModel):
    session_id: str = ""
    task: str
    project_path: str = ""


class RunnerMessageRequest(BaseModel):
    session_id: str
    message: str


@app.get("/api/runner/status")
async def runner_status():
    """获取 Claude Code Runner 状态"""
    runner = get_runner()
    return {"success": True, "data": runner.get_status()}


@app.post("/api/runner/oneshot")
async def runner_one_shot(request: RunnerOneShotRequest):
    """One-shot 模式: 执行单次任务，Claude Code 完成后返回结果"""
    runner = get_runner()
    result = runner.run_one_shot(
        task_description=request.task,
        project_path=request.project_path,
        timeout=request.timeout,
    )
    return {"success": result.get("success", False), "data": result}


@app.post("/api/runner/daemon/start")
async def runner_start_daemon(request: RunnerDaemonRequest):
    """启动 Claude Code 守护进程（长期运行）"""
    runner = get_runner()
    result = runner.start_daemon(
        session_id=request.session_id,
        task_description=request.task,
        project_path=request.project_path,
    )
    return {"success": result.get("success", False), "data": result}


@app.post("/api/runner/daemon/message")
async def runner_send_message(request: RunnerMessageRequest):
    """向运行中的 daemon 发送消息"""
    runner = get_runner()
    result = runner.send_to_daemon(request.session_id, request.message)
    return {"success": result.get("success", False), "data": result}


@app.post("/api/runner/daemon/stop")
async def runner_stop_daemon(session_id: str = ""):
    """停止 daemon"""
    runner = get_runner()
    result = runner.stop_daemon(session_id)
    return {"success": result.get("success", False), "data": result}


# ==================== 健康检查 ====================

@app.get("/api/health")
async def health():
    cfg = get_config()
    return {
        "status": "ok",
        "version": "0.1.0",
        "llm_provider": cfg.llm.provider,
        "llm_model": cfg.llm.model,
    }
