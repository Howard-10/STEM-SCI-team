import { useEffect, useState } from "react";
import { App } from "./App";
import { LatexFormatterPage } from "./pages/LatexFormatterPage";

type ManuscriptContext = {
  projectId: string;
  title: string;
  content: string;
};

export function AppShell() {
  const [open, setOpen] = useState(false);
  const [manuscriptContext, setManuscriptContext] = useState<ManuscriptContext | null>(null);
  const projectId = import.meta.env.VITE_PROJECT_ID && import.meta.env.VITE_PROJECT_ID !== "demo"
    ? import.meta.env.VITE_PROJECT_ID
    : "physics-ai-demo";

  useEffect(() => {
    const handleManuscriptContext = (event: Event) => {
      const detail = (event as CustomEvent<ManuscriptContext>).detail;
      if (!detail?.projectId || !detail.content) return;
      setManuscriptContext(detail);
    };
    window.addEventListener("stem-sci:manuscript-context", handleManuscriptContext);
    return () => window.removeEventListener("stem-sci:manuscript-context", handleManuscriptContext);
  }, []);

  return <>
    <App />
    <button className="latex-launch-button" type="button" onClick={() => setOpen(true)}>
      {manuscriptContext ? "用当前论文投稿格式化" : "投稿格式化 / LaTeX"}
    </button>
    {open && <div className="latex-modal" role="dialog" aria-modal="true" aria-label="投稿格式化">
      <button className="latex-close-button" type="button" onClick={() => setOpen(false)}>关闭</button>
      <LatexFormatterPage
        projectId={manuscriptContext?.projectId ?? projectId}
        initialTitle={manuscriptContext?.title}
        initialContent={manuscriptContext?.content}
      />
    </div>}
  </>;
}
