type Props = {
  url: string;
  userLabel: string;
  onBack: () => void;
  onSignOut: () => void;
};

export function TeachingWorkspaceFrame({ url, userLabel, onBack, onSignOut }: Props) {
  return (
    <main className="teaching-workspace-page">
      <header className="teaching-workspace-toolbar">
        <div className="teaching-workspace-brand">
          <span className="teaching-workspace-mark">学</span>
          <span>
            <strong>智研育航助学</strong>
            <small>独立教学服务</small>
          </span>
        </div>
        <div className="teaching-workspace-actions">
          <span className="teaching-workspace-user">{userLabel}</span>
          <button type="button" onClick={onBack}>切换空间</button>
          <button type="button" onClick={onSignOut}>退出登录</button>
          <a href={url} target="_blank" rel="noreferrer" aria-label="在新窗口打开助学平台">
            ↗
          </a>
        </div>
      </header>
      <section className="teaching-workspace-frame" aria-label="智研育航助学平台">
        <iframe title="智研育航助学平台" src={url} />
      </section>
    </main>
  );
}
