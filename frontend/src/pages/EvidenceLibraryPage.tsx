import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  DiscoveryAssetResponse,
  KnowledgeAssetSummary,
  SharedContextMode,
  SharedCorpusSummary,
  SharedRetrievalResponse,
} from "../types/context";
import { CitationDetailDrawer } from "../components/CitationDetailDrawer";
import { GateSummary } from "../components/GateSummary";
import { TechnicalTrace } from "../components/TechnicalTrace";
import { buildCorpusView, buildEvidenceCoverage, evidenceView } from "../utils/researchViewModel";
import type { EvidenceViewModel } from "../types/research";
import { demoCorpus, demoDiscoveryAssets, demoKnowledgeAssetSummary, demoRetrieval } from "../demo/data";

export function EvidenceLibraryPage() {
  const demoMode = import.meta.env.VITE_DEMO_MODE === "true";
  const [projectId, setProjectId] = useState(
    import.meta.env.VITE_PROJECT_ID && import.meta.env.VITE_PROJECT_ID !== "demo"
      ? import.meta.env.VITE_PROJECT_ID
      : "physics-ai-demo",
  );
  const [query, setQuery] = useState("生成式 AI 支架 物理建模 师范生");
  const [mode, setMode] = useState<SharedContextMode>("discovery");
  const [corpus, setCorpus] = useState<SharedCorpusSummary | null>(demoMode ? demoCorpus : null);
  const [knowledgeAssets, setKnowledgeAssets] = useState<KnowledgeAssetSummary | null>(demoMode ? demoKnowledgeAssetSummary : null);
  const [discoveryAssets, setDiscoveryAssets] = useState<DiscoveryAssetResponse | null>(demoMode ? demoDiscoveryAssets : null);
  const [result, setResult] = useState<SharedRetrievalResponse | null>(demoMode ? demoRetrieval : null);
  const [selected, setSelected] = useState<EvidenceViewModel | null>(null);
  const [bundleReady, setBundleReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    void api.listSharedCorpora().then((items) => setCorpus(items.find((item) => item.corpus_id === "physics_stem_v1") ?? null)).catch(() => setError("无法读取共享语料状态"));
    void api.getKnowledgeAssetSummary().then(setKnowledgeAssets).catch(() => setKnowledgeAssets(null));
    void api.getDiscoveryAssets().then(setDiscoveryAssets).catch(() => setDiscoveryAssets(null));
  }, []);
  const corpusView = buildCorpusView(corpus);
  const evidence = useMemo(() => result?.chunk_hits.map(evidenceView) ?? [], [result]);
  const gates = [{ kind: "evidence" as const, label: "证据核验", tone: evidence.some((item) => item.gateTone === "verified") ? "pending" as const : "insufficient" as const, detail: evidence.length ? `${evidence.filter((item) => item.gateTone === "verified").length} 条已核验` : "暂无检索证据" }];
  const search = async () => { setBusy(true); setError(""); try { setResult(await api.searchSharedCorpus(projectId, query, mode)); } catch (caught) { setError(caught instanceof Error ? caught.message : "检索失败"); } finally { setBusy(false); } };
  const buildBundle = async () => { setBusy(true); setError(""); try { await api.buildSharedBundle(projectId, query, mode); setBundleReady(true); } catch (caught) { setError(caught instanceof Error ? caught.message : "证据包暂时无法构建"); } finally { setBusy(false); } };
  return <div className="workspace library-workspace"><header className="workspace-intro compact-intro"><div><span className="eyebrow">EVIDENCE LIBRARY / PHYSICS-STEM</span><h1>把研究问题连接到原文证据</h1><p>共享语料只读，图谱用于发现关联，原文摘录经过核验后可进入正式证据包。</p></div><div className="corpus-status"><strong>{corpusView.status}</strong><span>{corpusView.detail}</span></div></header><section className="library-toolbar"><label className="search-field"><span>检索 Physics-STEM 语料</span><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} /></label><label className="mode-field"><span>证据模式</span><select value={mode} onChange={(event) => setMode(event.target.value as SharedContextMode)}><option value="discovery">发现探索</option><option disabled={!corpus?.formal_evidence_ready} value="formal">正式证据</option></select></label><button className="secondary-action" disabled={busy || !query.trim()} onClick={() => void search()} type="button">{busy ? "检索中…" : "检索"}</button><button className="primary-action" disabled={busy || !query.trim() || (mode === "formal" && !corpus?.formal_evidence_ready)} onClick={() => void buildBundle()} type="button">构建证据包</button></section><div className="corpus-strip"><span><strong>{corpus?.paper_count ?? "—"}</strong> 篇正式论文</span><span><strong>{corpus?.vector_chunk_count ?? "—"}</strong> 个正式文本片段</span><span>检索质量：<strong>{result?.retrieval_status ?? "尚未检索"}</strong></span><GateSummary gates={gates} compact /></div>{knowledgeAssets && <section className="output-section compact-section knowledge-assets-section"><div className="output-section-heading"><div><h3>知识库更新</h3><p className="section-subtitle">正式证据与发现资料分开管理，发现资料不会自动进入论文结论。</p></div><span className="review-tag">{discoveryAssets?.status === "LOCAL_DISCOVERY_ONLY" ? "发现层" : "读取中"}</span></div><div className="asset-stat-grid"><div><strong>{knowledgeAssets.formal_corpus.papers}</strong><small>正式论文</small></div><div><strong>{knowledgeAssets.formal_corpus.vector_chunks}</strong><small>正式文本块</small></div><div><strong>{knowledgeAssets.structured_assets.discovery_candidates}</strong><small>发现候选</small></div><div><strong>{knowledgeAssets.structured_assets.discovery_fulltext_chunks}</strong><small>全文发现块</small></div></div>{discoveryAssets && <><div className="asset-discovery-heading"><span>已下载全文发现集</span><small>{discoveryAssets.downloaded_count} 篇 · {discoveryAssets.chunk_count} 个页码块 · 不进入正式证据</small></div><div className="asset-discovery-list">{discoveryAssets.records.map((record) => <div className="asset-discovery-row" key={record.candidate_id}><span className="asset-discovery-year">{record.year ?? "—"}</span><span><strong>{record.title}</strong><small>{record.doi ?? record.candidate_id} · {record.detail ?? "页码已记录"}</small></span><span className="review-tag">发现</span></div>)}</div></>}<p className="asset-boundary-note">只有完成授权、身份映射、全文定位和来源核验后，发现资料才可提升为正式证据。</p></section>}<div className="library-grid"><section className="search-results"><div className="panel-heading"><div><span className="eyebrow">RETRIEVAL RESULTS</span><h2>检索结果</h2></div><span className="result-count">{evidence.length} 条原文命中</span></div>{evidence.length ? <div className="library-result-list">{evidence.map((item) => <button className="library-result" key={item.id} onClick={() => setSelected(item)} type="button"><div className="result-title"><strong>{item.title}</strong><span className={`status-label status-${item.gateTone}`}>{item.verification}</span></div><p>{item.excerpt}</p><small>{item.source} · {item.page ?? "定位待补充"} · {item.doi ?? "DOI 未提供"}</small></button>)}</div> : <div className="empty-state large-empty"><strong>输入关键词开始检索</strong><span>结果会按照论文和原文片段分开呈现，便于核验引用。</span></div>}</section><aside className="library-detail"><span className="eyebrow">EVIDENCE PACKAGE</span><h2>证据资格</h2><div className="qualification-list"><div className="qualification verified"><strong>{evidence.filter((item) => item.gateTone === "verified").length}</strong><span>可用于正式结论</span></div><div className="qualification pending"><strong>{evidence.filter((item) => item.gateTone === "pending").length}</strong><span>可用于探索但未核验</span></div><div className="qualification blocked"><strong>{evidence.filter((item) => item.gateTone === "insufficient").length}</strong><span>不可使用 + 原因</span></div></div><p className="muted">{bundleReady ? "证据包已生成，可在研究流程中继续使用。" : "构建证据包后，系统会保存当前检索上下文和风险信息。"}</p><details className="private-sources"><summary>私有资料（二级入口）</summary><p>上传前请完成脱敏。私有资料与共享 Physics-STEM 语料严格分区。</p></details><TechnicalTrace><pre>{JSON.stringify(result?.retrieval_trace ?? { status: "尚未检索" }, null, 2)}</pre></TechnicalTrace></aside></div>{error && <p className="error-text" role="alert">{error}</p>}<CitationDetailDrawer item={selected} onClose={() => setSelected(null)} /></div>;
}
