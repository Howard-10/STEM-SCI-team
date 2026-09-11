import type { UserProfile } from "../api/auth";

type WorkspaceMode = "research" | "teaching";

type Props = {
  user: UserProfile;
  onSelect: (mode: WorkspaceMode) => void;
  onSignOut: () => void;
};

export function WorkspaceModeSelector({ user, onSelect, onSignOut }: Props) {
  const displayName = user.display_name ?? user.username;

  return (
    <main className="workspace-mode-page">
      <section className="workspace-mode-shell" aria-labelledby="workspace-mode-title">
        <div className="workspace-mode-heading">
          <div className="research-logo large">S</div>
          <div>
            <span className="chat-kicker">STEM-SCI 统一入口</span>
            <h1 id="workspace-mode-title">你好，{displayName}</h1>
            <p>请选择今天要进入的工作空间</p>
          </div>
          <button className="workspace-mode-signout" type="button" onClick={onSignOut}>
            退出登录
          </button>
        </div>

        <div className="workspace-mode-options">
          <button
            className="workspace-mode-card workspace-mode-card-research"
            type="button"
            onClick={() => onSelect("research")}
          >
            <span className="workspace-mode-symbol">研</span>
            <span className="workspace-mode-card-copy">
              <strong>助研</strong>
              <small>论文助研与科研工作流</small>
              <em>文献证据、研究设计、数据分析、论文写作</em>
            </span>
            <span className="workspace-mode-arrow" aria-hidden="true">→</span>
          </button>

          <button
            className="workspace-mode-card workspace-mode-card-teaching"
            type="button"
            onClick={() => onSelect("teaching")}
          >
            <span className="workspace-mode-symbol">学</span>
            <span className="workspace-mode-card-copy">
              <strong>助学</strong>
              <small>星图学航 STEM 教学平台</small>
              <em>教案设计、课程案例、学习路径、知识星图</em>
            </span>
            <span className="workspace-mode-arrow" aria-hidden="true">→</span>
          </button>
        </div>

        <p className="workspace-mode-note">两个工作空间使用独立服务，项目数据彼此隔离。</p>
      </section>
    </main>
  );
}
