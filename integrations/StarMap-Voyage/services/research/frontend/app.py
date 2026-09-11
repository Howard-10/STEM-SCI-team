"""Research-Copilot-OS — AI 赋能科研全流程平台"""

import json, io, os, tempfile, zipfile, base64
from pathlib import Path
import streamlit as st
import requests

st.set_page_config(page_title="Research-Copilot-OS", page_icon="🧪", layout="wide", initial_sidebar_state="collapsed")

API_BASE = os.getenv("RCO_API_URL", "http://127.0.0.1:8000")

# ═══════════════════════════════════════════════════════════════
#  API Helpers
# ═══════════════════════════════════════════════════════════════
def api_post(endpoint, **kw):
    try: r = requests.post(f"{API_BASE}{endpoint}", timeout=600, **kw); return r.json()
    except: return {"success": False, "error": "连接后端失败"}

def api_get(endpoint):
    try: r = requests.get(f"{API_BASE}{endpoint}", timeout=30); return r.json()
    except: return {"success": False, "error": "连接后端失败"}

def api_delete(endpoint):
    try: r = requests.delete(f"{API_BASE}{endpoint}", timeout=30); return r.json()
    except: return {"success": False, "error": "连接后端失败"}

# ═══════════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════════
def safe_str(v, default=""):
    """安全转字符串，拦截 DeltaGenerator 泄露"""
    if v is None: return default
    if isinstance(v, str):
        if "DeltaGenerator" in v: return default
        return v
    if isinstance(v, (list, tuple)):
        return "\n".join(safe_str(i) for i in v if "DeltaGenerator" not in str(i))
    if isinstance(v, dict): return default
    s = str(v)
    return default if "DeltaGenerator" in s else s

# Monkey-patch st.markdown to filter DeltaGenerator
_orig_md = st.markdown
def _safe_md(body, *args, **kw):
    body = safe_str(body)
    return _orig_md(body, *args, **kw)
st.markdown = _safe_md

# Also patch st.caption, st.write, st.text
_orig_cap = st.caption
def _safe_cap(body, *args, **kw):
    body = safe_str(body)
    return _orig_cap(body, *args, **kw)
st.caption = _safe_cap

_orig_write = st.write
def _safe_write(*args, **kw):
    args = tuple(safe_str(a) for a in args)
    return _orig_write(*args, **kw)
st.write = _safe_write
def render_formula(text):
    """将 LaTeX 公式转为 Streamlit 可渲染的 markdown 格式"""
    import re
    if isinstance(text, list): return "\n\n".join(render_formula(i) for i in text)
    if not isinstance(text, str) or not text: return str(text) if text else ""
    # 1. 转换 \[...\] → $$...$$
    text = re.sub(r'\\\[([\s\S]*?)\\\]', r'$$\1$$', text)
    # 2. 转换 \(...\) → $...$
    text = re.sub(r'\\\(([\s\S]*?)\\\)', r'$\1$', text)
    # 3. 转换 \begin{equation}...\end{equation} → $$...$$
    text = re.sub(r'\\begin\{equation\}([\s\S]*?)\\end\{equation\}', r'$$\1$$', text)
    text = re.sub(r'\\begin\{align\*?\}([\s\S]*?)\\end\{align\*?\}', r'$$\1$$', text)
    return text

def clean_latex(text):
    """简化版 LaTeX → Unicode 转换（用于无法渲染的残留）"""
    import re
    if isinstance(text, list): return "\n".join(clean_latex(i) for i in text)
    if not isinstance(text, str):
        s = str(text)
        if "DeltaGenerator" in s or "LockedCursor" in s: return "未提取"
        return s
    if not text: return "未提取"
    if "DeltaGenerator" in text or "LockedCursor" in text: return "未提取"
    text = render_formula(text)  # 先转 markdown 公式格式
    symbols = {'\\alpha':'α','\\beta':'β','\\gamma':'γ','\\delta':'δ','\\epsilon':'ε','\\theta':'θ','\\lambda':'λ','\\mu':'μ','\\sigma':'σ','\\phi':'φ','\\omega':'ω','\\Sigma':'Σ','\\Delta':'Δ','\\Omega':'Ω','\\infty':'∞','\\approx':'≈','\\times':'×','\\cdot':'·','\\neq':'≠','\\leq':'≤','\\geq':'≥','\\partial':'∂','\\nabla':'∇'}
    for k,v in symbols.items(): text = text.replace(k, v)
    return text

# ═══════════════════════════════════════════════════════════════
#  CSS — 最小覆盖（保留 Streamlit 原生风格）
# ═══════════════════════════════════════════════════════════════
st.markdown("""
<style>
.hero { text-align: center; padding: 2rem 0 1rem; }
.hero h1 { font-size: 2.4rem; font-weight: 700; margin:0; color: #312E81; }
.hero p { color: #6366F1; font-size: 1rem; margin-top: 0.3rem; }
.module-card { border-radius: 14px; padding: 1.5rem 1.2rem; text-align: center; background: #ffffff; border: 1px solid #E0E3F8; transition: all 0.2s; }
.module-card:hover { border-color: #4F46E5; box-shadow: 0 4px 16px rgba(79,70,229,0.1); }
.module-card .icon { font-size: 2rem; }
.module-card .title { font-weight: 600; font-size: 1rem; color: #312E81; }
.module-card .subtitle { font-size: 0.78rem; color: #818CF8; }
.section-title { font-size: 1.3rem; font-weight: 600; margin: 1rem 0 0.5rem; padding-bottom: 0.4rem; border-bottom: 2px solid #e5e7eb; }
footer { visibility: hidden; }

/* 文件上传区域：虚线边框拖拽区 */
[data-testid="stFileUploader"] section {
    border: 2px dashed #c5c5c5 !important;
    border-radius: 8px !important;
    padding: 1.5rem !important;
    background: #fafafa !important;
    transition: border-color 0.2s, background 0.2s;
}
[data-testid="stFileUploader"] section:hover {
    border-color: #4285f4 !important;
    background: #f0f4ff !important;
}
[data-testid="stFileUploadDropzone"] {
    min-height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
#  Session State
# ═══════════════════════════════════════════════════════════════
for key, default in [("active_module","home"), ("agent_messages",[]), ("agent_session_id","")]:
    if key not in st.session_state: st.session_state[key] = default

# ═══════════════════════════════════════════════════════════════
#  Module Definitions
# ═══════════════════════════════════════════════════════════════
MODULES = [
    {"id":"literature_repo","icon":"📚","title":"文献仓库","subtitle":"来自文献阅读模块的项目与论文","color":"#4F46E5"},
    {"id":"fusion","icon":"🧩","title":"代码分析","subtitle":"代码分块 · 模块迁移","color":"#6366F1"},
    {"id":"data","icon":"🔬","title":"数据处理","subtitle":"数据集适配 · 数据增强","color":"#818CF8"},
    {"id":"experiment","icon":"⚡","title":"实验模块","subtitle":"可视化 · 消融 · 调参 · 记录","color":"#A5B4FC"},
]

# ═══════════════════════════════════════════════════════════════
#  HOME PAGE
# ═══════════════════════════════════════════════════════════════
if st.session_state.active_module == "home":
    st.markdown('<div class="hero"><h1>Research-Copilot-OS</h1><p>AI 赋能科研全流程 · DeepSeek V4 驱动 · 19 工具 Agent</p></div>', unsafe_allow_html=True)

    # 四个卡片入口
    cols = st.columns(4)
    for i, mod in enumerate(MODULES):
        with cols[i]:
            st.markdown(f'<div class="module-card"><div class="icon">{mod["icon"]}</div><div class="title">{mod["title"]}</div><div class="subtitle">{mod["subtitle"]}</div></div>', unsafe_allow_html=True)
            if st.button("进入", key=f"card_{mod['id']}", use_container_width=True):
                st.session_state.active_module = mod["id"]; st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns([2,1])
    with c1:
        st.markdown("### 🚀 平台概览")
        st.markdown("**Research-Copilot-OS** 是一个 AI 驱动的科研全流程智能平台，覆盖从文献阅读到实验管理的完整闭环。")
        for mod in MODULES:
            st.markdown(f"- **{mod['icon']} {mod['title']}** — {mod['subtitle']}")
    with c2:
        st.markdown("### 🔧 系统状态")
        try:
            h = api_get("/api/health")
            if h.get("status") == "ok": st.success(f"✅ 后端正常 | {h.get('llm_provider','')}/{h.get('llm_model','')}")
            else: st.warning("⚠️ 后端异常")
        except: st.error("❌ 后端未连接")

# ═══════════════════════════════════════════════════════════════
#  MODULE PAGES — Top Nav
# ═══════════════════════════════════════════════════════════════
else:
    # 顶栏导航
    nav_cols = st.columns([1.2, 1.2, 1.2, 1.2, 4])
    for i, mod in enumerate(MODULES):
        with nav_cols[i]:
            active = mod["id"] == st.session_state.active_module
            if st.button(f'{mod["icon"]} {mod["title"]}', key=f"nav_{mod['id']}",
                         type="primary" if active else "secondary", use_container_width=True):
                st.session_state.active_module = mod["id"]; st.rerun()
    st.markdown("---")

    # ═════════════════════════════════════════════════════════
    #  MODULE 1: 文献仓库 (桥接文献阅读模块)
    # ═════════════════════════════════════════════════════════
    if st.session_state.active_module == "literature_repo":
        st.markdown('<div class="section-title">📚 文献仓库</div>', unsafe_allow_html=True)
        st.caption("来自「文献阅读」模块的项目与论文，无需重复上传")

        # Try to load synced projects from shared data
        import glob as _glob
        shared_dir = os.environ.get(
            "STARMAP_SHARED_LITERATURE_DIR",
            str(Path(__file__).resolve().parents[2] / "teaching" / "data" / "literature" / "projects"),
        )

        projects_found = []
        if os.path.isdir(shared_dir):
            for fpath in _glob.glob(os.path.join(shared_dir, "*.json")):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        projects_found.append(json.load(f))
                except: pass

        if not projects_found:
            st.info("📭 暂未同步文献项目。请在「文献阅读」模块中创建项目并分析论文，然后点击同步按钮。")
            st.markdown("### 如何同步？")
            st.markdown("1. 切换到「📚 文献阅读」标签页")
            st.markdown("2. 创建或打开一个科研项目")
            st.markdown("3. 完成论文分析后，项目数据将同步到此")
        else:
            for proj in projects_found:
                with st.expander(f"📁 {proj.get('title','未命名项目')} — {proj.get('researchTopic','')}  ({len(proj.get('papers',[]))} 篇论文)", expanded=len(projects_found)==1):
                    st.markdown(f"**研究方向**: {proj.get('researchTopic','')}")
                    st.markdown(f"**描述**: {proj.get('description','')}")
                    papers = proj.get("papers",[])
                    if papers:
                        st.markdown(f"---")
                        st.markdown(f"### 📄 论文列表 ({len(papers)}篇)")
                        for i, paper in enumerate(papers, 1):
                            st.markdown(f"**{i}. {paper.get('title','未命名')}**")
                            c1, c2 = st.columns([3,1])
                            with c1:
                                st.markdown(f"_{paper.get('inspiration','')[:200]}_")
                            with c2:
                                if st.button(f"🔬 开始实验", key=f"exp_paper_{i}_{proj.get('id','')}"):
                                    st.session_state["active_paper"] = paper
                                    st.session_state["active_project"] = proj
                                    st.session_state.active_module = "experiment"
                                    st.rerun()
                            st.markdown(f"方法: {paper.get('method','')[:150]}")
                            st.markdown(f"创新: {', '.join(paper.get('innovation',[])[:3])}")
                            st.markdown("---")
                    if proj.get("overviewReport"):
                        ov = proj["overviewReport"]
                        with st.expander("📋 领域报告"):
                            st.markdown(f"**背景**: {ov.get('background','')[:300]}")
                            st.markdown(f"**核心概念**: {', '.join(ov.get('coreConcepts',[]))}")
                            st.markdown(f"**主流方法**: {', '.join(ov.get('mainstreamMethods',[]))}")

    # ═════════════════════════════════════════════════════════
    #  MODULE 2: 模型融合
    # ═════════════════════════════════════════════════════════
    elif st.session_state.active_module == "fusion":
        st.markdown('<div class="section-title">🧩 模型融合</div>', unsafe_allow_html=True)
        fus_tab = st.radio("", ["🧩 代码分块", "🔀 模块迁移"], horizontal=True)

        if fus_tab == "🧩 代码分块":
            st.caption("基于 AST + LLM 语义增强，将项目代码按功能/模块自动分块")
            use_classify = st.checkbox("🧠 智能分类（LLM → 6 个顶层类别）", value=True)
            input_mode = st.radio("", ["📁 上传代码 zip", "📝 输入本地路径"], horizontal=True)
            result = None
            if input_mode.startswith("📁"):
                uploaded_zip = st.file_uploader("上传代码文件夹 (.zip)", type=["zip"], key="code_zip")
                strategy = st.selectbox("分块策略", ["auto","function","module"], key="zip_strategy")
                if uploaded_zip and st.button("🔍 开始分析", use_container_width=True):
                    ep = "/api/code/chunk-classified-upload" if use_classify else "/api/code/chunk-upload"
                    with st.spinner("解压+分析中..."): result = api_post(ep, files={"file":(uploaded_zip.name, uploaded_zip.getvalue())}, data={"strategy":strategy})
            else:
                project_path = st.text_input("项目文件夹路径", placeholder="D:/你的论文代码文件夹")
                strategy = st.selectbox("分块策略", ["auto","function","module"])
                if project_path and st.button("🔍 开始分析", use_container_width=True):
                    ep = "/api/code/chunk-classified" if use_classify else "/api/code/chunk-path"
                    with st.spinner("AST 分析中..."): result = api_post(ep, json={"project_path":project_path,"strategy":strategy})
            if result and result.get("success"):
                d = result["data"]
                if "groups" in d:
                    st.session_state["chunk_result"] = d
                    st.success(f"✅ 分类完成，{d.get('total_chunks',0)} 个块 → 6 类"); st.markdown(d.get("summary",""))
                elif "chunks" in d:
                    st.session_state["chunk_result"] = d
                    st.success(f"✅ {d['total_chunks']} 个代码块")
            elif result: st.error(result.get("detail","分析失败"))

            # 从 session state 恢复并展示分块结果
            cached = st.session_state.get("chunk_result")
            if cached:
                try:
                    if "groups" in cached:
                        d = cached
                        btn_counter = [0]  # 可变计数器避免 key 重复
                        all_flat = []
                        for key,info in d["groups"].items():
                            for c in info.get("chunks",[]): all_flat.append(c)
                        for key,info in d["groups"].items():
                            chunks = info.get("chunks",[])
                            if chunks:
                                with st.expander(f"{info['label']} ({len(chunks)})"):
                                    for c in chunks:
                                        st.markdown(f"**{c['name']}** `{c['file_path']}:{c['start_line']}-{c['end_line']}`")
                                        st.caption(c.get("description","")); st.code(c["source_code"], language="python")
                                        prev_block = all_flat[all_flat.index(c)-1] if all_flat.index(c) > 0 else None
                                        btn_counter[0] += 1
                                        if st.button(f"💬 AI 解读: {c['name'][:30]}", key=f"explain_{btn_counter[0]}"):
                                            prev_info = f"\n上一个代码块: {prev_block['name']}\n```python\n{prev_block['source_code'][:500]}\n```" if prev_block else "\n(这是第一个代码块)"
                                            prompt = f"""请解读以下代码块:\n\n代码块: {c['name']} ({c.get('category','')})\n代码:\n```python\n{c['source_code'][:1500]}\n```\n{prev_info}\n\n请完成两项:\n1. 这个代码块的含义和用途\n2. 它与上一个代码块的连接关系"""
                                            st.session_state.pending_agent_count += 1; st.session_state.agent_messages.append({"role":"user","content":prompt}); st.rerun()
                    else:
                        d = cached
                        btn_counter = [0]
                        cats = sorted(set(c["category"] for c in d["chunks"]))
                        sel = st.multiselect("筛选", cats, default=cats)
                        filtered = [c for c in d["chunks"] if c["category"] in sel]
                        for idx, c in enumerate(filtered):
                            with st.expander(f"[{c['category']}] {c['name']}"): st.caption(c.get("description","")); st.code(c["source_code"], language="python")
                            prev = filtered[idx-1] if idx > 0 else None
                            btn_counter[0] += 1
                            if st.button(f"💬 AI 解读: {c['name'][:30]}", key=f"explain2_{btn_counter[0]}"):
                                prev_info = f"\n上一个块: {prev['name']}\n```python\n{prev['source_code'][:500]}\n```" if prev else "\n(首个代码块)"
                                prompt = f"""请解读此代码块:\n\n代码块: {c['name']} ({c.get('category','')})\n代码:\n```python\n{c['source_code'][:1500]}\n```\n{prev_info}\n\n请完成两项:\n1. 含义和用途\n2. 与上一个块的连接关系"""
                                st.session_state.pending_agent_count += 1; st.session_state.agent_messages.append({"role":"user","content":prompt}); st.rerun()
                except Exception as e:
                    import traceback
                    st.error(f"代码块展示异常: {e}")
                    st.code(traceback.format_exc())

        else:
            st.caption("左选源模块 → 右定插入位置 → AI 对齐 → 预览保存")
            left, right = st.columns(2)
            with left:
                st.markdown("#### 📂 源模块（待迁移）")
                src_source = st.radio("", ["📋 历史分块", "📁 直接输入"], horizontal=True, key="src_radio")
                source_chunks, source_project_path = [], ""
                if src_source.startswith("📋"):
                    cached = api_get("/api/code/cached-projects")
                    projects = cached.get("data",[]) if cached.get("success") else []
                    if not projects: st.info("暂无缓存")
                    else:
                        col_p,col_d = st.columns([3,1])
                        with col_p: selected_proj = st.selectbox("选择项目", [p["name"] for p in projects], key="cached_sel")
                        with col_d:
                            if selected_proj and st.button("🗑️", key="del_proj"): api_delete(f"/api/code/cached-projects/{selected_proj}"); st.rerun()
                        if selected_proj:
                            chunks_data = api_get(f"/api/code/cached-chunks/{selected_proj}")
                            if chunks_data.get("success"):
                                all_chunks = chunks_data["data"].get("chunks",[])
                                source_project_path = chunks_data["data"].get("project_path","")
                                SIX_LABELS = ["📐参数与配置","🏗️模型架构","📊数据处理","🔄训练与优化","📈评估与日志","🔧工具与入口"]
                                cat_map = {"config":"params_config","model_definition":"model_arch","forward_propagation":"model_arch","data_processing":"data_pipeline","data_augmentation":"data_pipeline","data_loader":"data_pipeline","loss_function":"train_optim","optimizer":"train_optim","training_loop":"train_optim","validation_loop":"eval_logging","evaluation":"eval_logging","utility":"utils_entry"}
                                cat_filter = st.selectbox("筛选类别", ["全部"]+SIX_LABELS, key="cat_filt")
                                if cat_filter != "全部":
                                    target_cat = ["params_config","model_arch","data_pipeline","train_optim","eval_logging","utils_entry"][SIX_LABELS.index(cat_filter)]
                                    source_chunks = [c for c in all_chunks if cat_map.get(c.get("category",""),"")==target_cat]
                                else: source_chunks = all_chunks
                                st.caption(f"{len(source_chunks)} 个模块")
                else:
                    src_path = st.text_input("源项目路径", placeholder="D:/paper-code", key="src_input")
                    if src_path and st.button("📊 分析源项目", use_container_width=True):
                        with st.spinner("分析中..."): r = api_post("/api/code/chunk-path", json={"project_path":src_path,"strategy":"auto"})
                        if r.get("success"): source_chunks = r["data"].get("chunks",[]); source_project_path = src_path; st.success(f"{len(source_chunks)} 个模块")
                if source_chunks: st.session_state["source_chunks_cache"] = source_chunks
                for c in source_chunks[:25]:
                    is_sel = st.session_state.get("picked_chunk_id")==c.get("chunk_id")
                    if st.button(f"{'🔵' if is_sel else '  '} {c.get('name','')[:45]} [{c.get('category','')}]", key=f"pick_{c.get('chunk_id','')}", use_container_width=True, type="primary" if is_sel else "secondary"):
                        st.session_state["picked_chunk"]=c; st.session_state["picked_chunk_id"]=c.get("chunk_id"); st.session_state["picked_src_path"]=source_project_path or st.session_state.get("src_input",""); st.rerun()
            with right:
                st.markdown("#### 🎯 目标模型")
                tgt_source = st.radio("", ["📁 输入路径", "📋 历史记录"], horizontal=True, key="tgt_radio")
                if tgt_source.startswith("📋"):
                    cached = api_get("/api/code/cached-projects")
                    projects = cached.get("data",[]) if cached.get("success") else []
                    if projects:
                        sel_name = st.selectbox("选择项目", [p["name"] for p in projects], key="tgt_cached")
                        if sel_name and st.button("📊 加载", use_container_width=True):
                            r = api_get(f"/api/code/cached-chunks/{sel_name}")
                            if r.get("success"):
                                all_c = r["data"].get("chunks",[])
                                keep = {"data_processing","data_loader","data_augmentation","model_definition","forward_propagation","loss_function"}
                                ordered = sorted([c for c in all_c if c.get("category") in keep], key=lambda c:(c.get("file_path",""),c.get("start_line",0)))
                                st.session_state["tgt_chunks"]=ordered; st.session_state["tgt_path"]=r["data"].get("project_path",""); st.success(f"{len(ordered)} 个模块")
                else:
                    tgt_path = st.text_input("目标项目路径", placeholder="D:/my-model", key="tgt_input")
                    if tgt_path and st.button("📊 分析目标模型", use_container_width=True):
                        with st.spinner("有序分析中..."): r = api_post("/api/code/chunk-ordered", json={"project_path":tgt_path})
                        if r.get("success"): st.session_state["tgt_chunks"]=r["data"].get("chunks",[]); st.session_state["tgt_path"]=tgt_path; st.success(f"{len(st.session_state['tgt_chunks'])} 个模块")
                tgt_chunks = st.session_state.get("tgt_chunks",[])
                if tgt_chunks:
                    for i,c in enumerate(tgt_chunks):
                        if st.button(f"↓ 插入此处（{c['name'][:30]} 之前）", key=f"ins_before_{i}", use_container_width=True): st.session_state["insert_pos"]=i; st.rerun()
                        with st.expander(f"{c['category']}: {c['name']}"): st.code(c.get("source_code","")[:600], language="python")
                    if st.button(f"↓ 插入此处（最后）", key=f"ins_end", use_container_width=True): st.session_state["insert_pos"]=len(tgt_chunks); st.rerun()
            st.markdown("---")
            picked = st.session_state.get("picked_chunk"); insert_pos = st.session_state.get("insert_pos")
            tgt_chunks = st.session_state.get("tgt_chunks",[])
            if picked: st.markdown(f"**已选**: {picked.get('name','')}"); st.code(picked.get("source_code","")[:1200], language="python")
            if insert_pos is not None and tgt_chunks: st.markdown(f"**插入位置**: {'第'+str(insert_pos+1)+'个模块之前' if insert_pos<len(tgt_chunks) else '最后'}")
            if picked and insert_pos is not None and tgt_chunks:
                if st.button("🔀 AI 自动对齐并生成", use_container_width=True, type="primary"):
                    src_p = st.session_state.get("picked_src_path",""); tgt_p = st.session_state.get("tgt_path","")
                    with st.spinner("AI 对齐中..."): ar = api_post("/api/code/migrate-align", json={"source_project":src_p or tgt_p,"target_project":tgt_p,"source_chunk_id":picked.get("chunk_id","")})
                    if ar.get("success"):
                        merged = ar["data"].get("merged_code",""); st.session_state["merged_code"]=merged; st.success("✅ 对齐完成"); st.code(merged, language="python")
                        risk = ar["data"].get("risk_assessment",{})
                        if risk:
                            with st.expander("⚠️ 风险评估"):
                                st.metric("总体风险", risk.get("overall_risk","unknown"))
                                for k in ["gradient_risk","dimension_risk","stability_risk"]:
                                    if risk.get(k): st.markdown(f"- {k}: {risk[k]}")
                        insert_idx = st.session_state.get("insert_pos",0)
                        tgt_file = tgt_chunks[insert_idx].get("file_path","model.py") if insert_idx<len(tgt_chunks) else (tgt_chunks[-1].get("file_path","model.py") if tgt_chunks else "model.py")
                        st.info(f"将保存到: `{tgt_file}`")
                        col_save,col_discard = st.columns(2)
                        with col_save:
                            if st.button("💾 保存",use_container_width=True,type="primary"):
                                save_r = api_post("/api/code/migrate-save", json={"target_project":tgt_p,"target_file":tgt_file,"merged_code":merged})
                                if save_r.get("success"): st.success(f"✅ {save_r['data']['message']}")
                                for k in ["picked_chunk","picked_chunk_id","insert_pos","merged_code"]: st.session_state[k]=None; st.rerun()
                        with col_discard:
                            if st.button("🗑️ 放弃",use_container_width=True):
                                for k in ["picked_chunk","picked_chunk_id","insert_pos","merged_code"]: st.session_state[k]=None; st.rerun()
            if st.button("🤖 AI 推荐迁移方案", use_container_width=True):
                st.session_state.pending_agent_count += 1; st.session_state.agent_messages.append({"role":"user","content":f"分析模块迁移: 源={st.session_state.get('picked_src_path','')} 目标={st.session_state.get('tgt_path','')}"}); st.rerun()

    # ═════════════════════════════════════════════════════════
    #  MODULE 3: 数据处理
    # ═════════════════════════════════════════════════════════
    elif st.session_state.active_module == "data":
        st.markdown('<div class="section-title">🔬 数据处理</div>', unsafe_allow_html=True)
        data_tab = st.radio("", ["📊 数据集适配", "🎨 数据增强"], horizontal=True)

        if data_tab == "📊 数据集适配":
            st.caption("自动解读数据集 → 结合模型代码 → 生成 DataLoader")
            left_ds, right_ds = st.columns(2)
            with left_ds:
                data_path = st.text_input("数据集路径（文件或文件夹）", placeholder="D:/dataset 或 D:/data/train.csv")
                model_source = st.radio("模型代码来源", ["📁 上传项目", "📝 手动粘贴"], horizontal=True, key="ds_src")
                model_code = ""
                if model_source.startswith("📁"):
                    ds_zip = st.file_uploader("上传代码文件夹 (.zip)", type=["zip"], key="ds_zip")
                    ds_path = st.text_input("或输入路径", placeholder="D:/model-project", key="ds_path")
                    if (ds_zip or ds_path) and st.button("🔍 提取数据相关代码", use_container_width=True):
                        with st.spinner("分析中..."):
                            if ds_zip: r = api_post("/api/code/chunk-upload", files={"file":(ds_zip.name, ds_zip.getvalue())})
                            else: r = api_post("/api/code/chunk-path", json={"project_path":ds_path,"strategy":"auto"})
                        if r.get("success"):
                            data_cats = {"data_processing","data_loader","data_augmentation","model_definition","forward_propagation"}
                            data_chunks = [c for c in r["data"]["chunks"] if c.get("category") in data_cats]
                            model_code = "\n\n".join(c.get("source_code","")[:800] for c in data_chunks[:5]); st.session_state["ds_model_code"] = model_code
                            st.success(f"提取 {len(data_chunks)} 个模块"); st.expander("预览").code(model_code[:3000], language="python")
                else:
                    model_code = st.text_area("模型代码", height=120, placeholder="class MyModel(nn.Module):...", key="ds_paste")
                    if model_code: st.session_state["ds_model_code"] = model_code
                effective_code = st.session_state.get("ds_model_code", model_code)
                if data_path:
                    col_i,col_g = st.columns(2)
                    with col_i:
                        if st.button("🔍 解读数据集", use_container_width=True):
                            with st.spinner("..."): r = api_post("/api/data/inspect", data={"data_path":data_path})
                            if r.get("success"): st.session_state["ds_info"] = r["data"]
                    with col_g:
                        if st.button("📝 生成 DataLoader", use_container_width=True):
                            with st.spinner("..."): r = api_post("/api/data/generate-loader", data={"data_path":data_path,"model_code":effective_code})
                            if r.get("success"): st.session_state["dl_code"] = r["data"]["code"]
            with right_ds:
                ds_info = st.session_state.get("ds_info")
                if ds_info:
                    st.success(f"✅ {ds_info.get('data_format','')} · {ds_info.get('sample_count',0)} 样本")
                    for label,key in [("特征维度","feature_shape"),("标签类型","label_type"),("类别数","num_classes")]:
                        st.metric(label, str(ds_info.get(key,""))[:20])
                    st.info(ds_info.get("description",""))
                dl_code = st.session_state.get("dl_code")
                if dl_code: st.code(dl_code, language="python"); st.download_button("📥 下载", dl_code, "dataloader.py", "text/plain")
            if data_path and st.button("🤖 AI 帮我适配", use_container_width=True):
                prompt = f"数据集: {data_path}\n{'代码已提取' if effective_code else '帮我判断数据形式'}"
                if effective_code: prompt += f"\n```python\n{effective_code[:2000]}\n```"
                st.session_state.pending_agent_count += 1; st.session_state.agent_messages.append({"role":"user","content":prompt}); st.rerun()

        else:
            st.caption("勾选增强操作 → 预览效果 → 批量处理 → 分文件夹保存")
            ops_r = api_get("/api/augment/operations")
            ops = ops_r.get("data",[]) if ops_r.get("success") else []
            if ops:
                st.markdown("### 1️⃣ 选择操作")
                cats = sorted(set(op["category"] for op in ops))
                selected_ops = []
                op_cols = st.columns(min(len(cats),3))
                for i,cat in enumerate(cats):
                    with op_cols[i%3]:
                        cat_ops = [op for op in ops if op["category"]==cat]
                        with st.expander(f"{cat} ({len(cat_ops)})", expanded=cat=="几何变换"):
                            for op in cat_ops:
                                if st.checkbox(op["name"], key=op["id"]): selected_ops.append(op["id"])
                st.caption(f"已选 **{len(selected_ops)}** 个: {', '.join(selected_ops[:8])}")
                if selected_ops:
                    st.markdown("### 2️⃣ 单图测试")
                    test_img = st.file_uploader("上传测试图片", type=["png","jpg","jpeg","bmp"], key="aug_preview")
                    if test_img:
                        st.session_state["aug_test_img"] = test_img.getvalue()
                        if st.button("🔍 预览效果", use_container_width=True):
                            with st.spinner("应用增强..."): r = api_post("/api/augment/preview", files={"file":(test_img.name, test_img.getvalue())}, data={"operations":json.dumps(selected_ops)})
                            if r.get("success"): st.session_state["aug_preview_result"] = r["data"]
                    preview = st.session_state.get("aug_preview_result")
                    if preview:
                        col_orig,col_aug = st.columns(2)
                        with col_orig: st.markdown("**原图**"); st.image(base64.b64decode(preview["original"]))
                        with col_aug: st.markdown("**增强后**"); st.image(base64.b64decode(preview["augmented"]))
                    st.markdown("### 3️⃣ 批量处理")
                    col_p,col_o = st.columns(2)
                    with col_p: folder_path = st.text_input("图片文件夹", placeholder="D:/dataset/images")
                    with col_o: output_dir = st.text_input("输出目录（留空=自动）", placeholder="")
                    if folder_path and st.button("⚡ 批量处理并保存", use_container_width=True, type="primary"):
                        with st.spinner("处理中..."): r = api_post("/api/augment/folder", data={"folder_path":folder_path,"operations":json.dumps(selected_ops),"output_dir":output_dir})
                        if r.get("success"): d=r["data"]; st.success(f"✅ {d['success']}/{d['total']} 张 → `{d['output_dir']}`")
                    st.markdown("### 4️⃣ 自定义")
                    tab_c,tab_g = st.tabs(["🤖 AI 自定义","📝 生成代码"])
                    with tab_c:
                        custom_desc = st.text_area("描述需求", height=80, placeholder="添加椒盐噪声，比例5%")
                        if custom_desc and st.button("🤖 生成",use_container_width=True): st.session_state.pending_agent_count += 1; st.session_state.agent_messages.append({"role":"user","content":f"自定义数据增强: {custom_desc}"}); st.rerun()
                    with tab_g:
                        if st.button("📝 生成增强代码", use_container_width=True):
                            with st.spinner("..."): r = api_post("/api/augment/generate", json={"operations":selected_ops,"data_format":"image","model_code":""})
                            if r.get("success"): st.session_state["aug_code"] = r["data"]["code"]
                        ac = st.session_state.get("aug_code")
                        if ac: st.code(ac, language="python"); st.download_button("📥 下载", ac, "augmentation.py", "text/plain")

    # ═════════════════════════════════════════════════════════
    #  MODULE 4: 实验模块
    # ═════════════════════════════════════════════════════════
    elif st.session_state.active_module == "experiment":
        st.markdown('<div class="section-title">⚡ 实验模块</div>', unsafe_allow_html=True)
        exp_tab = st.radio("", ["📈 可视化生成", "🧪 消融实验", "🎛️ 超参数调优", "📋 实验记录"], horizontal=True)

        if exp_tab == "📈 可视化生成":
            st.caption("AI 推荐图表 → 输入数据 → 迭代生成+评分修缮 → 90分+")
            st.markdown("### 1️⃣ 图表推荐")
            col_rec,col_data = st.columns(2)
            with col_rec:
                analyzed = st.session_state.get("analyzed_papers",[])
                if analyzed:
                    st.markdown(f"📚 已分析 {len(analyzed)} 篇")
                    sel_papers = st.multiselect("引用论文", [p.get("title","")[:40] for p in analyzed], key="vis_sel")
                    if sel_papers and st.button("📋 根据论文推荐", use_container_width=True):
                        ctx_parts = []
                        for p in analyzed:
                            if p.get("title","")[:40] in sel_papers: ctx_parts.append(f"{p['title']}\n领域:{p.get('research_field','')}/{p.get('sub_field','')}\n核心:{p.get('one_sentence','')}\n方法:{p.get('methodology','')[:300]}\n数据集:{p.get('datasets',[])}\n指标:{p.get('metrics',[])}")
                        paper_ctx = "\n---\n".join(ctx_parts); st.session_state["vis_paper_ctx"] = paper_ctx
                        st.session_state.pending_agent_count += 1; st.session_state.agent_messages.append({"role":"user","content":f"根据这些论文推荐可视化:\n{paper_ctx}"}); st.rerun()
                paper_ctx = st.text_area("文献上下文", height=80, value=st.session_state.get("vis_paper_ctx",""), placeholder="手动填写或由上方自动填充")
                user_req = st.text_area("需求描述", height=68, placeholder="三个模型准确率对比柱状图")
                ref_img = st.file_uploader("📷 参考样例（可选）", type=["png","jpg","jpeg"], key="vis_ref")
                if ref_img: st.image(ref_img, width=200)
                if st.button("🤖 AI 推荐方案", use_container_width=True):
                    st.session_state.pending_agent_count += 1; st.session_state.agent_messages.append({"role":"user","content":f"推荐可视化: 上下文={paper_ctx or '通用'} 需求={user_req or '根据上下文推荐'}"}); st.rerun()
            with col_data:
                data_m = st.radio("", ["📝 描述", "📁 CSV文件", "📋 粘贴"], horizontal=True)
                data_content = ""
                if data_m == "📁 CSV文件":
                    df = st.file_uploader("上传数据", type=["csv","json","txt"], key="vis_csv")
                    if df: data_content = df.getvalue().decode("utf-8")[:5000]; st.success(f"{len(data_content)} 字符")
                elif data_m == "📝 描述": data_content = st.text_area("描述数据", height=80, placeholder="ResNet 78.5%, ViT 82.1%")
                else: data_content = st.text_area("粘贴数据", height=100, placeholder="model,accuracy\nResNet,78.5")
            st.markdown("### 2️⃣ 迭代生成")
            if st.button("🎨 开始迭代生成（最多5轮）", use_container_width=True, type="primary"):
                if user_req or data_content:
                    with st.spinner("AI 生成+评分+修缮..."): r = api_post("/api/vis/iterate", json={"user_requirement":user_req or "根据数据生成图表","data_description":data_content,"paper_context":paper_ctx})
                    if r.get("success"): st.session_state["vis_iter_result"] = r["data"]
                else: st.warning("请输入需求或数据")
            vis_r = st.session_state.get("vis_iter_result")
            if vis_r:
                score = vis_r.get("final_score",0); color = "green" if score>=90 else ("orange" if score>=70 else "red")
                st.markdown(f"### 评分: :{color}[**{score}/100**]")
                st.dataframe([{"轮次":h["iteration"],"评分":h["score"],"反馈":str(h.get("feedback",h.get("error","")))[:80]} for h in vis_r.get("history",[])])
                img_b64 = vis_r.get("image_base64","")
                if img_b64: st.image(base64.b64decode(img_b64), caption=f"最终生图 ({score}/100)", use_container_width=True)
                code = vis_r.get("code","")
                if code:
                    with st.expander("📝 代码"): st.code(code, language="python"); st.download_button("📥 下载", code, "plot.py", "text/plain")

        elif exp_tab == "🧪 消融实验":
            st.caption("上传项目 → AI 识别可消融模块 → 选择 → 移除+对齐 → 保存")
            ab_source = st.radio("", ["📁 上传 zip", "📝 本地路径"], horizontal=True, key="ab_src")
            project_path = ""
            if ab_source.startswith("📁"):
                ab_zip = st.file_uploader("上传代码文件夹 (.zip)", type=["zip"], key="ab_zip")
                if ab_zip:
                    if "ab_tmpdir" not in st.session_state: st.session_state["ab_tmpdir"] = tempfile.mkdtemp(prefix="ab_")
                    tmpdir = st.session_state["ab_tmpdir"]
                    with zipfile.ZipFile(io.BytesIO(ab_zip.getvalue()),"r") as zf: zf.extractall(tmpdir)
                    items = os.listdir(tmpdir)
                    project_path = os.path.join(tmpdir,items[0]) if (len(items)==1 and os.path.isdir(os.path.join(tmpdir,items[0]))) else tmpdir; st.success(f"解压: {project_path}")
            else: project_path = st.text_input("项目路径", placeholder="D:/pytorch-project", key="ab_path")
            if project_path:
                if st.button("🔍 智能识别可消融模块", use_container_width=True, type="primary"):
                    with st.spinner("AI 分析中..."): r = api_post("/api/ablation/analyze", json={"project_path":project_path})
                    if r.get("success"): st.session_state["ab_candidates"] = r["data"]; st.success(r['data'].get('model_summary',''))
                cand_list = st.session_state.get("ab_candidates",{}).get("candidates",[])
                if cand_list:
                    st.markdown(f"### 可消融候选（{len(cand_list)} 个）")
                    selected = []
                    for c in cand_list:
                        with st.expander(f"{'⭐' if c.get('recommended') else '  '} **{c['name']}** — {c.get('description','')[:80]}"):
                            st.markdown(f"**创新**: {c.get('innovation_reason','')} | **独立**: {c.get('independence_reason','')}")
                            st.markdown(f"**影响**: {c.get('ablation_impact','')} | **难度**: {c.get('removal_difficulty','')}")
                            for o in c.get("occurrences",[]): st.caption(f"• {o}")
                            if st.checkbox("消融此模块", key=f"ab_sel_{c['id']}", value=c.get("recommended",False)): selected.append(c["name"])
                    if selected:
                        st.session_state["ab_selected_names"] = selected; st.markdown(f"已选 **{len(selected)}**: {', '.join(selected)}")
                        if st.button("⚡ 执行消融（移除+对齐）", use_container_width=True, type="primary"):
                            with st.spinner("移除+对齐..."): r = api_post("/api/ablation/execute", json={"project_path":project_path,"selected_modules":selected})
                            if r.get("success"): st.session_state["ab_result"] = r["data"]
                    ab_result = st.session_state.get("ab_result")
                    if ab_result:
                        st.success("✅ 消融完成"); st.markdown(f"**摘要**: {ab_result.get('changes_summary','')}")
                        for da in ab_result.get("dimension_alignments",[]): st.markdown(f"- 🔧 {da}")
                        for w in ab_result.get("warnings",[]): st.markdown(f"- ⚠️ {w}")
                        code = ab_result.get("ablated_code",""); st.code(code, language="python")
                        fn = st.text_input("文件名", "model_ablated.py", key="ab_fn")
                        col_s,col_d = st.columns(2)
                        with col_s:
                            if st.button("💾 保存", use_container_width=True, type="primary"):
                                save_r = api_post("/api/ablation/save", json={"project_path":project_path,"file_name":fn,"ablated_code":code})
                                if save_r.get("success"): st.success(f"✅ {save_r['data']['saved']}")
                        with col_d: st.download_button("📥 下载", code, fn, "text/plain")

        elif exp_tab == "🎛️ 超参数调优":
            st.caption("上传项目 → 识别所有超参数 → 手动调整 or AI 推荐")
            hp_src = st.radio("", ["📁 上传 zip", "📝 本地路径", "✏️ 粘贴代码"], horizontal=True, key="hp_src")
            project_path, all_code = "", ""
            if hp_src.startswith("📁"):
                hp_zip = st.file_uploader("上传 zip", type=["zip"], key="hp_zip")
                if hp_zip:
                    if "hp_tmpdir" not in st.session_state: st.session_state["hp_tmpdir"] = tempfile.mkdtemp(prefix="hp_")
                    tmpdir = st.session_state["hp_tmpdir"]
                    with zipfile.ZipFile(io.BytesIO(hp_zip.getvalue()),"r") as zf: zf.extractall(tmpdir)
                    items = os.listdir(tmpdir); project_path = os.path.join(tmpdir,items[0]) if (len(items)==1 and os.path.isdir(os.path.join(tmpdir,items[0]))) else tmpdir; st.success(project_path)
            elif hp_src.startswith("📝"): project_path = st.text_input("项目路径", key="hp_path")
            else: all_code = st.text_area("粘贴代码", height=200, key="hp_paste")
            if (project_path or all_code) and st.button("🔍 分析超参数", use_container_width=True, type="primary"):
                with st.spinner("扫描中..."):
                    if project_path: r = api_post("/api/hyperparams/analyze-project", json={"project_path":project_path})
                    else: r = api_post("/api/hyperparams/identify", json={"code":all_code})
                if r.get("success"):
                    hp_data = r["data"]; params = hp_data.get("hyperparameters", hp_data if isinstance(hp_data,list) else [])
                    st.session_state["hp_params"] = params; st.success(f"{len(params)} 个超参数")
            params = st.session_state.get("hp_params",[])
            if params:
                st.markdown("### 超参数配置")
                edited = []; changed_params = []
                for i in range(0,len(params),3):
                    cols = st.columns(3)
                    for j in range(3):
                        if i+j < len(params):
                            p = params[i+j]
                            with cols[j]:
                                cur = str(p.get("current_value",""))
                                nv = st.text_input(f"{p['name']} ({p.get('type','')})", value=cur, key=f"hp_{p['name']}", help=f"位置:{p.get('location','')}\n范围:{p.get('suggested_range','')}")
                                st.caption(f"影响:{p.get('impact','')}")
                                edited.append({**p,"new_value":nv})
                                if nv != cur: changed_params.append(p['name'])
                if changed_params: st.markdown(f"**{len(changed_params)}** 个已修改: {', '.join(changed_params)}")
                if changed_params and st.button("📝 生成配置代码", use_container_width=True):
                    with st.spinner("..."): r = api_post("/api/hyperparams/generate-code", json={"hyperparameters":edited})
                    if r.get("success"): st.session_state["hp_code"] = r["data"]["code"]
                if st.session_state.get("hp_code"): st.code(st.session_state["hp_code"], language="python")
            st.markdown("---"); st.markdown("### 🤖 训练过程分析")
            train_desc = st.text_area("描述训练过程", height=100, placeholder="loss在epoch 50后不下降，验证准确率75%波动...")
            if train_desc and st.button("🔬 AI 分析推荐", use_container_width=True, type="primary"):
                hp_json = json.dumps([{"name":p["name"],"value":p.get("current_value","")} for p in params], ensure_ascii=False) if params else ""
                with st.spinner("分析中..."): r = api_post("/api/hyperparams/recommend", json={"training_description":train_desc,"current_hyperparams":hp_json})
                if r.get("success"): st.session_state["hp_recommend"] = r["data"]
            hp_rec = st.session_state.get("hp_recommend")
            if hp_rec:
                st.markdown(f"**诊断**: {hp_rec.get('diagnosis','')}")
                for rec in hp_rec.get("recommendations",[]):
                    prio = {"high":"🔴","medium":"🟡","low":"🟢"}.get(rec.get("priority",""),"")
                    st.markdown(f"- {prio} **{rec['param']}**: {rec['current']} → **{rec['suggested']}** — {rec['reason']}")
                for tip in hp_rec.get("training_tips",[]): st.markdown(f"- 💡 {tip}")

        else:
            st.caption("查看所有历史实验")
            if st.button("🔄 刷新", use_container_width=True):
                r = api_get("/api/experiments")
                if r.get("success"): st.session_state["exp_list"] = r["data"]
            exps = st.session_state.get("exp_list",[])
            if exps:
                st.success(f"共 **{len(exps)}** 个实验")
                search = st.text_input("🔍 搜索", placeholder="关键词...")
                filtered = [e for e in exps if search.lower() in str(e.get("experiment_name","")).lower()] if search else exps
                for exp in filtered:
                    with st.expander(f"📦 {exp.get('experiment_name','?')} · {exp.get('created_at','')[:16]}"):
                        c1,c2 = st.columns(2)
                        with c1:
                            st.markdown(f"**模型**: {exp.get('model_name','')}"); st.markdown(f"**备注**: {exp.get('notes','')}")
                            try: st.json(json.loads(exp.get("hyperparameters","{}")))
                            except: pass
                        with c2:
                            try: st.json(json.loads(exp.get("test_metrics","{}")))
                            except: pass
                        if st.button("📊 Epoch 日志", key=f"ep_{exp['id']}"):
                            detail = api_get(f"/api/experiments/{exp['id']}")
                            if detail.get("success") and detail["data"].get("epochs"):
                                epochs = detail["data"]["epochs"]
                                st.line_chart([{"epoch":e["epoch"],"train_loss":e.get("train_loss",0),"val_loss":e.get("val_loss",0)} for e in epochs])
                                st.dataframe(epochs[-50:])
            else: st.info("暂无记录")

# ═══════════════════════════════════════════════════════════════
#  AI 助手 Sidebar
# ═══════════════════════════════════════════════════════════════
st.sidebar.markdown("## 🤖 AI 科研助手")
st.sidebar.caption("19 工具 · DeepSeek · 文件读写 · Shell · 论文 · 代码")

for msg in st.session_state.agent_messages[-6:]:
    with st.sidebar.chat_message(msg["role"]):
        content = msg.get("content", "")
        if not isinstance(content, str): content = str(content)
        st.sidebar.markdown(content[:300] + ("..." if len(content)>300 else ""))
        if msg.get("tool_calls"): st.sidebar.caption(f"🔧 {len(msg['tool_calls'])} 个工具调用")

# 处理待发送的消息
# 用待处理计数追踪，避免误判（>0 表示有未回复的 user 消息）
if "pending_agent_count" not in st.session_state:
    st.session_state.pending_agent_count = 0

# 新消息到达时计数+1，处理完计数-1
if st.session_state.pending_agent_count > 0:
    # 找到最后一条未处理的 user 消息
    pending_msg = None
    for m in reversed(st.session_state.agent_messages):
        if m["role"] == "user":
            pending_msg = m["content"]
            break
    if pending_msg:
        with st.sidebar.chat_message("assistant"):
            with st.spinner("..."): result = api_post("/api/agent/chat", json={"message":pending_msg,"session_id":st.session_state.agent_session_id})
            if result.get("success"):
                data = result["data"]; resp = data.get("response","")
                if not isinstance(resp, str): resp = str(resp)
                st.session_state.agent_session_id = data.get("session_id","")
                st.sidebar.markdown(resp[:600])
                st.session_state.agent_messages.append({"role":"assistant","content":resp,"tool_calls":data.get("tool_calls_made",[])})
        st.session_state.pending_agent_count -= 1

user_input = st.sidebar.chat_input("输入科研问题...")
if user_input:
    st.session_state.pending_agent_count += 1; st.session_state.agent_messages.append({"role":"user","content":user_input})
    st.rerun()

if st.sidebar.button("🗑️ 清空对话"):
    st.session_state.agent_messages = []; st.session_state.agent_session_id = ""; st.rerun()

st.markdown("---")
st.caption("Research-Copilot-OS v1.0 · Powered by DeepSeek V4 · AI 赋能科研")
