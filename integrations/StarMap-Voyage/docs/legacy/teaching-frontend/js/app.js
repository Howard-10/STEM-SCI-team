/**
 * 星图学航 2.0 - Main Application
 */
const API_BASE = 'http://127.0.0.1:8002';

// ====== Navigation ======
const pages = ['home-page','project-page','star-map-page','achievement-page'];

function showPage(pageId) {
    pages.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('active');
    });
    const target = document.getElementById(pageId);
    if (target) target.classList.add('active');

    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === pageId.replace('-page',''));
    });

    if (pageId === 'star-map-page') setTimeout(loadKnowledgeMap, 200);
    if (pageId === 'achievement-page') loadAchievements();
}

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
        const page = item.dataset.page;
        showPage(page + '-page');
    });
});

// ====== Global State ======
let currentQuery = null;
let currentQuiz = null;
let currentAssessment = null;
let quizSubmitting = false;

// ====== Home: Bubbles ======
const ICONS = ['🔬','🧪','🌱','🏗️','💧','🤖','♻️','🗣️','📜','🌿','📷','🏙️'];
const DEFAULT_BUBBLES = [
    {id:'light_refraction',title:'光的折射与透镜探究',difficulty:2,subjects:['物理','数学']},
    {id:'acid_base_indicator',title:'自制酸碱指示剂',difficulty:2,subjects:['化学','生物']},
    {id:'seed_germination',title:'种子发芽条件探究',difficulty:2,subjects:['生物','环境']},
    {id:'paper_bridge',title:'纸桥承重挑战赛',difficulty:2,subjects:['物理','工程']},
    {id:'auto_watering',title:'智能自动浇花系统',difficulty:3,subjects:['生物','编程']},
    {id:'obstacle_robot',title:'避障机器人挑战',difficulty:4,subjects:['工程','编程']},
    {id:'waste_sorting_survey',title:'社区垃圾分类调查',difficulty:2,subjects:['环境','社会']},
    {id:'dialect_survey',title:'方言保护小调查',difficulty:2,subjects:['社会','语言']},
    {id:'history_timeline',title:'历史事件时间线可视化',difficulty:3,subjects:['社会','编程']},
    {id:'carbon_footprint',title:'我的家庭碳足迹计算',difficulty:3,subjects:['环境','数学']},
    {id:'campus_plant_atlas',title:'校园植物图鉴制作',difficulty:2,subjects:['生物','艺术']},
    {id:'future_city_design',title:'设计未来城市模型',difficulty:3,subjects:['工程','艺术']},
];

async function loadBubbles() {
    const grid = document.getElementById('bubble-grid');
    if (!grid) return;
    let bubbles = DEFAULT_BUBBLES;
    try {
        const resp = await fetch(`${API_BASE}/api/bubbles`);
        const data = await resp.json();
        if (data.bubbles && data.bubbles.length > 0) bubbles = data.bubbles;
    } catch(e) {}

    grid.innerHTML = bubbles.map((b,i) => `
        <div class="bubble-card" data-query="我想学习如何做一个${b.title}的STEM项目">
            <span class="bubble-badge">${'⭐'.repeat(b.difficulty||2)}</span>
            <div class="bubble-icon">${ICONS[i%ICONS.length]}</div>
            <div class="bubble-title">${b.title}</div>
            <div class="bubble-meta">${(b.subjects||[]).slice(0,2).join(' · ')}</div>
        </div>
    `).join('');

    grid.querySelectorAll('.bubble-card').forEach(card => {
        card.addEventListener('click', () => startQuiz(card.dataset.query));
    });
}

// ====== Search ======
document.getElementById('search-btn')?.addEventListener('click', () => {
    const q = document.getElementById('search-input')?.value.trim();
    if (q) startQuiz(q);
});
document.getElementById('search-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        const q = document.getElementById('search-input')?.value.trim();
        if (q) startQuiz(q);
    }
});

// ====== Quiz Flow ======
async function startQuiz(query) {
    currentQuery = query;
    const modal = document.getElementById('quiz-modal');
    modal?.classList.remove('hidden');

    // Reset state: hide questions and result, show start/skip buttons
    document.getElementById('quiz-questions').innerHTML = '';
    document.getElementById('quiz-result')?.classList.remove('show');
    document.getElementById('quiz-start-btn')?.classList.remove('hidden');
    document.getElementById('quiz-skip-btn')?.classList.remove('hidden');
    document.getElementById('quiz-start-btn').disabled = false;
    document.getElementById('quiz-start-btn').textContent = '开始测评';
    quizSubmitting = false;

    // Pre-generate quiz in background
    try {
        const resp = await fetch(`${API_BASE}/api/generate-quiz`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({topic:query, grade_level: getGrade()})
        });
        const data = await resp.json();
        if (data.success && data.quiz) currentQuiz = data.quiz;
    } catch(e) { /* Will retry on start click */ }
}

// Start quiz button → show questions and reveal submit
document.getElementById('quiz-start-btn')?.addEventListener('click', async function() {
    // If quiz wasn't pre-generated, generate now
    if (!currentQuiz || !currentQuiz.questions) {
        this.disabled = true; this.textContent = '加载中...';
        try {
            const resp = await fetch(`${API_BASE}/api/generate-quiz`, {
                method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({topic:currentQuery, grade_level: getGrade()})
            });
            const data = await resp.json();
            if (data.success && data.quiz) currentQuiz = data.quiz;
        } catch(e) { return; }
    }

    renderQuiz(currentQuiz);
    this.classList.add('hidden');
    // Reveal submit button
    const submitBtn = document.getElementById('quiz-start-btn');
    // Swap start button to submit mode
    document.getElementById('quiz-questions').insertAdjacentHTML('afterend',
        '<div class="quiz-actions" id="quiz-submit-actions"><button class="btn btn-primary" id="quiz-submit-btn">提交测评</button></div>');
    // Bind submit
    document.getElementById('quiz-submit-btn')?.addEventListener('click', submitQuiz);
});

// Skip button
document.getElementById('quiz-skip-btn')?.addEventListener('click', () => {
    document.getElementById('quiz-modal')?.classList.add('hidden');
    generatePlanDirect(currentQuery);
});

function renderQuiz(quiz) {
    const container = document.getElementById('quiz-questions');
    if (!container) return;
    container.innerHTML = (quiz.questions||[]).map((q,i) => `
        <div class="quiz-question">
            <div class="q-text">${i+1}. ${q.text}</div>
            <div class="q-concept">考察: ${q.concept||''}</div>
            <div class="q-options">
                ${Object.entries(q.options||{}).map(([k,v]) => `
                    <div class="quiz-option" data-qid="${q.id}" data-key="${k}">${k}. ${v}</div>
                `).join('')}
            </div>
        </div>
    `).join('');

    container.querySelectorAll('.quiz-option').forEach(opt => {
        opt.addEventListener('click', () => {
            container.querySelectorAll(`[data-qid="${opt.dataset.qid}"]`).forEach(o => o.classList.remove('selected'));
            opt.classList.add('selected');
        });
    });
}

// Submit quiz → go to hub
async function submitQuiz() {
    if (quizSubmitting) return;
    quizSubmitting = true;
    const btn = document.getElementById('quiz-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = '提交中...'; }

    const answers = {};
    document.querySelectorAll('.quiz-option.selected').forEach(opt => { answers[opt.dataset.qid] = opt.dataset.key; });

    try {
        const resp = await fetch(`${API_BASE}/api/assess-quiz`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({topic:currentQuery, grade_level:getGrade(),
                quiz_questions: currentQuiz?.questions||null, answers})
        });
        const data = await resp.json();
        if (data.success && data.assessment) {
            currentAssessment = data.assessment;
        }
    } catch(e) { console.error(e); }
    document.getElementById('quiz-modal')?.classList.add('hidden');
    generatePlanAdaptive(answers);
    quizSubmitting = false;
}

// ====== Plan Generation ======
function getGrade() { return document.getElementById('filter-grade')?.value || '初中'; }
function getInclude3D() { return document.getElementById('filter-3d')?.checked ?? true; }

async function generatePlanAdaptive() {
    showLoading('根据你的水平生成个性化教案...');
    try {
        const resp = await fetch(`${API_BASE}/api/generate-plan-adaptive`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({query:currentQuery, grade_level:getGrade(),
                quiz_questions: currentQuiz?.questions||null,
                answers: getAssessmentAnswers(), include_3d_print: getInclude3D()})
        });
        if (!resp.ok) throw new Error('生成失败');
        const data = await resp.json();
        if (data.success && data.plan) { hideLoading(); await publishAndOpen(data.plan); }
    } catch(e) { alert('教案生成失败: '+e.message); hideLoading(); }
}

async function generatePlanDirect(query) {
    showLoading('正在为你生成专属教案...');
    try {
        const resp = await fetch(`${API_BASE}/api/generate-plan`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({query, grade_level:getGrade(), include_3d_print: getInclude3D()})
        });
        if (!resp.ok) throw new Error('生成失败');
        const data = await resp.json();
        if (data.success && data.plan) { hideLoading(); await publishAndOpen(data.plan); }
    } catch(e) { alert('教案生成失败: '+e.message); hideLoading(); }
}

function getAssessmentAnswers() {
    const answers = {};
    document.querySelectorAll('.quiz-option.selected').forEach(opt => { answers[opt.dataset.qid] = opt.dataset.key; });
    return answers;
}

async function publishAndOpen(plan) {
    try {
        const resp = await fetch(`${API_BASE}/api/publish-project`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({plan_markdown:plan.markdown, title:plan.title, grade_level:plan.grade_level})
        });
        const data = await resp.json();
        if (data.success) { window.location.hash = data.project_id; loadProject(data.project_id); }
    } catch(e) { showPage('project-page'); renderPlan(plan.markdown); renderPlanContent(); }
}

// ====== Project Space ======
async function loadProject(projectId) {
    showPage('project-page');
    try {
        const resp = await fetch(`${API_BASE}/api/project/${projectId}`);
        if (!resp.ok) throw new Error('加载失败');
        const data = await resp.json();

        document.getElementById('project-title').textContent = data.meta?.title||'STEM项目';
        const badges = document.getElementById('project-badges');
        badges.innerHTML = '';
        if (data.meta?.grade_level) badges.innerHTML += `<span class="badge">${data.meta.grade_level}</span>`;
        if (data.meta?.has_3d_print) badges.innerHTML += `<span class="badge">🔧 3D打印</span>`;

        if (data.plan_markdown) { renderPlan(data.plan_markdown); renderPlanContent(); }
        setupSidebarTabs(projectId);
        if (data.files) { renderFileTree(data.files); renderCodeFiles(data.files, projectId); render3DModels(data.files, projectId); }
        const tab3d = document.getElementById('tab-3d');
        if (tab3d) tab3d.style.display = data.meta?.has_3d_print ? '' : 'none';
        await fetch(`${API_BASE}/api/tutor/start?project_id=${projectId}`, {method:'POST'});
    } catch(e) { console.error(e); }
}

let currentPlanMd = '';

function renderPlan(md) {
    currentPlanMd = md;
    // Populate step nav from markdown headings
    const select = document.getElementById('step-nav');
    if (select) {
        select.innerHTML = '<option value="">-- 跳转到步骤 --</option>';
        (md.match(/^## (.+)$/gm)||[]).forEach(h => {
            const t = h.replace('## ','');
            select.innerHTML += `<option value="${escapeHtml(t)}">${t}</option>`;
        });
        select.onchange = () => {
            if (!select.value) return;
            const container = document.getElementById('plan-content');
            container.querySelectorAll('h2').forEach(h2 => { if (h2.textContent===select.value) h2.scrollIntoView({behavior:'smooth'}); });
        };
    }
}

function renderPlanContent() {
    if (!currentPlanMd) return;
    injectStageCheckpoints(currentPlanMd);
}

function escapeHtml(t) { const m={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}; return t.replace(/[&<>"]/g,c=>m[c]); }

// ====== Stage Checkpoints (inline after each stage) ======
function injectStageCheckpoints(md) {
    const container = document.getElementById('plan-content');
    if (!container) return;

    const projectId = window.location.hash.replace('#','');
    let savedStages = {};
    try { savedStages = JSON.parse(localStorage.getItem(`stages_${projectId}`)||'{}'); } catch(e) {}

    // Find the boundary between Block1 (前置) and Block2 (学习流程)
    // Block2 starts at "# 第二大块" or "# 学习流程"
    const block2Match = md.match(/^#\s*(第二大块|学习流程)/m);
    const block2Start = block2Match ? block2Match.index : -1;

    // Split into prefix (Block1), and the sections within Block2
    const block1Content = block2Start > 0 ? md.substring(0, block2Start) : '';
    const block2Content = block2Start > 0 ? md.substring(block2Start) : md;

    // Wrap Block1 in a styled container
    let injectedMd = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:1.5rem 2rem;margin-bottom:2rem;">';
    injectedMd += block1Content;
    injectedMd += '</div>';

    // Block2 header with visual marker
    injectedMd += '<div style="background:linear-gradient(135deg, rgba(99,102,241,0.1), rgba(6,182,212,0.05));border:1px solid rgba(99,102,241,0.2);border-radius:var(--radius);padding:1rem 1.5rem;margin-bottom:1.5rem;text-align:center;">';
    injectedMd += '<span style="font-size:1.1rem;font-weight:700;color:var(--accent-light);">🚀 开始学习流程</span>';
    injectedMd += '<p style="font-size:0.8rem;color:var(--text-secondary);margin-top:4px;">完成每个阶段后，在下方小结中记录你的收获</p>';
    injectedMd += '</div>';

    // Process Block2: inject checkpoints after each ## section
    const sections = block2Content.split(/^(?=## )/m);
    let stageIndex = 0;

    for (let i = 0; i < sections.length; i++) {
        const section = sections[i];
        if (!section.trim()) continue;

        injectedMd += section;

        // Only inject checkpoint after ## sections (not after the # heading or non-section content)
        if (section.match(/^## /m)) {
            const title = section.replace(/^## /m, '').split('\n')[0].trim();
            const stageId = `stage_${stageIndex}`;
            const saved = savedStages[stageId] || {};
            const done = saved.completed;

            injectedMd += `

<div class="stage-checkpoint ${done?'completed':''}" id="checkpoint-${stageId}" style="background:var(--bg-card);border:1px solid ${done?'var(--green)':'var(--border)'};border-radius:var(--radius);padding:1.5rem;margin:1.5rem 0;">
<h3 style="font-size:1rem;margin-bottom:0.25rem;">📌 阶段小结：${title}</h3>
<div class="stage-status ${done?'done':'pending'}" style="font-size:0.8rem;margin-bottom:0.75rem;color:${done?'var(--green)':'var(--yellow)'};">${done?'✅ 已完成':'⏳ 待完成'}</div>
${done ? `<div class="stage-stars" style="display:flex;gap:4px;margin-bottom:0.5rem;">${'<span class="stage-star earned" style="font-size:1.5rem;">⭐</span>'.repeat(saved.stars||1)}</div>` : ''}
<p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:8px;">完成本阶段后，请总结你做了什么、学到了什么：</p>
<textarea id="summary-${stageId}" placeholder="例如：我搭建了传感器电路，学习了超声波测距原理..." style="width:100%;padding:10px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;color:var(--text-primary);font-family:inherit;font-size:0.9rem;resize:vertical;min-height:70px;outline:none;">${saved.summary||''}</textarea>
<div class="stage-upload-area" style="margin-top:8px;display:flex;gap:10px;align-items:center;">
    <input type="file" id="upload-${stageId}" accept="image/*" style="color:var(--text-secondary);font-size:0.85rem;" />
    <button class="btn btn-sm" onclick="submitStageCheckpoint('${stageId}',${stageIndex})">提交总结</button>
</div>
<div class="stage-feedback" id="feedback-${stageId}" style="margin-top:0.75rem;padding:0.75rem;background:var(--bg-secondary);border-radius:8px;font-size:0.9rem;line-height:1.7;display:${saved.feedback?'block':'none'};">
    ${saved.feedback ? `<p>${saved.feedback.replace(/\n/g,'<br>')}</p>` : ''}
</div>
</div>

`;
            stageIndex++;
        }
    }

    // Now render the injected markdown
    renderMarkdownRaw(container, injectedMd);
}

function renderMarkdownRaw(container, md) {
    if (!container || !md) return;
    md = md.replace(/^```markdown\s*\n?/i,'').replace(/```\s*$/,'');

    // Strategy: split by checkpoint divs, render markdown parts, then reassemble
    const parts = [];
    const checkpointPattern = /(<div class="stage-checkpoint[\s\S]*?<\/div>\s*)/g;
    let lastIdx = 0;
    let match;

    while ((match = checkpointPattern.exec(md)) !== null) {
        // Markdown part before this checkpoint
        if (match.index > lastIdx) {
            parts.push({type: 'md', content: md.substring(lastIdx, match.index)});
        }
        // Checkpoint HTML part
        parts.push({type: 'html', content: match[0]});
        lastIdx = checkpointPattern.lastIndex;
    }
    // Remaining markdown after last checkpoint
    if (lastIdx < md.length) {
        parts.push({type: 'md', content: md.substring(lastIdx)});
    }

    // Render each part
    let html = '';
    for (const part of parts) {
        if (part.type === 'html') {
            html += part.content;
        } else {
            html += renderMdToHtml(part.content);
        }
    }

    container.innerHTML = html;
}

function renderMdToHtml(md) {
    let html = md;

    // Code blocks (fenced)
    html = html.replace(/```(\w*)\s*\n([\s\S]*?)```/g, (_, lang, code) =>
        `<pre><code>${escapeHtml(code.trim())}</code></pre>`
    );

    // Headers
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold, italic, inline code
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Horizontal rule
    html = html.replace(/^---$/gm, '<hr>');

    // Tables: group consecutive table rows
    const lines = html.split('\n');
    const processed = [];
    let tableRows = [];
    let inTable = false;

    for (const line of lines) {
        if (/^\|.+\|$/.test(line.trim())) {
            if (line.includes('---')) continue; // skip separator
            const cells = line.split('|').filter(c => c.trim());
            tableRows.push('<tr>' + cells.map(c => `<td>${c.trim()}</td>`).join('') + '</tr>');
            inTable = true;
        } else {
            if (inTable) {
                processed.push('<table>' + tableRows.join('') + '</table>');
                tableRows = [];
                inTable = false;
            }
            processed.push(line);
        }
    }
    if (inTable) {
        processed.push('<table>' + tableRows.join('') + '</table>');
    }
    html = processed.join('\n');

    // Lists (unordered)
    html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

    // Blockquote
    html = html.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');

    // Paragraphs: wrap remaining text lines that aren't HTML tags
    html = html.replace(/^(?!<[a-z/!])(.+)$/gm, '<p>$1</p>');

    // Cleanup
    html = html.replace(/<p>\s*<\/p>/g, '');
    html = html.replace(/<\/ul>\s*<ul>/g, '\n');
    html = html.replace(/<\/blockquote>\s*<blockquote>/g, '<br>');

    return html;
}

async function submitStageCheckpoint(stageId, stageIndex) {
    const summary = document.getElementById(`summary-${stageId}`)?.value?.trim();
    if (!summary) { alert('请先填写你的阶段总结'); return; }

    const feedbackDiv = document.getElementById(`feedback-${stageId}`);
    if (feedbackDiv) { feedbackDiv.classList.add('show'); feedbackDiv.innerHTML = '<p style="color:var(--text-secondary)">⏳ AI正在分析你的总结...</p>'; }

    try {
        const resp = await fetch(`${API_BASE}/api/evaluate-stage`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({summary, stage_index: Number.isFinite(Number(stageIndex)) ? Math.max(0, Number(stageIndex)) : 0, project_id: window.location.hash.replace('#','') || ''})
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data?.detail?.[0]?.msg || data?.message || `提交失败（HTTP ${resp.status}）`);
        if (data.success) {
            const {completion, feedback, stars, missing} = data.evaluation;

            // Save to localStorage
            const projectId = window.location.hash.replace('#','');
            let saved = {};
            try { saved = JSON.parse(localStorage.getItem(`stages_${projectId}`)||'{}'); } catch(e) {}
            saved[stageId] = {completed: completion >= 70, completion, feedback, stars, summary};
            localStorage.setItem(`stages_${projectId}`, JSON.stringify(saved));

            // Update UI
            if (feedbackDiv) {
                const starHtml = '<span class="stage-star earned">⭐</span>'.repeat(stars||0);
                feedbackDiv.innerHTML = `
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <strong>完成度: ${completion}%</strong>
                        <div class="stage-stars">${starHtml}</div>
                    </div>
                    <p style="margin-top:8px;">${(feedback||'').replace(/\n/g,'<br>')}</p>
                    ${missing ? `<p style="margin-top:4px;color:var(--yellow)">⚠️ 还需加强: ${missing}</p>` : ''}
                `;
            }

            // Update checkpoint status
            const checkpoint = document.getElementById(`checkpoint-${stageId}`);
            if (checkpoint && completion >= 70) {
                checkpoint.classList.add('completed');
                const statusEl = checkpoint.querySelector('.stage-status');
                if (statusEl) { statusEl.textContent = '✅ 已完成'; statusEl.className = 'stage-status done'; }
            }
        }
    } catch(e) {
        console.error(e);
        if (feedbackDiv) feedbackDiv.innerHTML = `<p style="color:var(--red)">${e instanceof Error ? e.message : '提交失败，请重试'}</p>`;
    }
}

// ====== Sidebar Tabs ======
function setupSidebarTabs(projectId) {
    document.querySelectorAll('.sidebar-tab').forEach(tab => {
        tab.onclick = () => {
            document.querySelectorAll('.sidebar-tab').forEach(t=>t.classList.remove('active'));
            tab.classList.add('active');
            document.querySelectorAll('.sidebar-content').forEach(c=>c.classList.remove('active'));
            const content = document.getElementById(`tab-content-${tab.dataset.tab}`);
            if (content) content.classList.add('active');
        };
    });
}

// ====== AI Tutor ======
document.getElementById('chat-send-btn')?.addEventListener('click', sendChat);
document.getElementById('chat-input')?.addEventListener('keydown', e => {
    if (e.key==='Enter'&&!e.shiftKey) { e.preventDefault(); sendChat(); }
});

async function sendChat() {
    const input = document.getElementById('chat-input');
    const msg = input?.value.trim();
    if (!msg) return;
    appendChat('user', msg);
    input.value = '';
    const pid = window.location.hash.replace('#','');
    try {
        const resp = await fetch(`${API_BASE}/api/tutor/chat`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({project_id:pid, message:msg})
        });
        const data = await resp.json();
        appendChat('assistant', data.reply);
    } catch(e) { appendChat('assistant','抱歉，AI助教暂时无法响应。'); }
}

function appendChat(role, text) {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;
    div.innerHTML = `<div class="chat-avatar">${role==='assistant'?'🤖':'👤'}</div><div class="chat-bubble">${text.replace(/\n/g,'<br>')}</div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

document.getElementById('reset-tutor-btn')?.addEventListener('click', async () => {
    const pid = window.location.hash.replace('#','');
    await fetch(`${API_BASE}/api/tutor/reset?project_id=${pid}`, {method:'POST'});
    const container = document.getElementById('chat-messages');
    if (container) container.innerHTML = '';
    appendChat('assistant','对话已重置。有什么新问题吗？👋');
});

// ====== Code ======
async function renderCodeFiles(files, projectId) {
    const list = document.getElementById('code-files-list');
    if (!list||!files.code) return;
    list.innerHTML = '';
    files.code.forEach(fname => {
        const item = document.createElement('div');
        item.className = 'file-item';
        item.innerHTML = `<span>📄</span> ${fname}`;
        item.addEventListener('click', async () => {
            try {
                const resp = await fetch(`${API_BASE}/api/project/${projectId}/file/code/${fname}`);
                document.getElementById('code-editor').value = await resp.text();
                document.getElementById('code-filename').textContent = fname;
                list.querySelectorAll('.file-item').forEach(i=>i.classList.remove('selected'));
                item.classList.add('selected');
            } catch(e) {}
        });
        list.appendChild(item);
    });
}

document.getElementById('run-code-btn')?.addEventListener('click', async () => {
    const code = document.getElementById('code-editor').value;
    if (!code) return;
    const output = document.getElementById('code-output');
    output.textContent = '运行中...';
    try {
        const resp = await fetch(`${API_BASE}/api/run-code`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({code, language:'python'})
        });
        const data = await resp.json();
        output.textContent = data.stdout||data.stderr||'(无输出)';
        output.style.color = data.returncode!==0&&data.stderr ? 'var(--red)' : 'var(--text-secondary)';
    } catch(e) { output.textContent = '执行失败: '+e.message; }
});

// ====== Files & 3D ======
function renderFileTree(files) {
    const tree = document.getElementById('project-files-tree');
    if (!tree) return;
    tree.innerHTML = '';
    const folders = {'📄 项目文件':['教案.md'],'💻 代码':files.code||[],'🔧 3D模型':files['3d_models']||[],'📊 数据':files.data||[]};
    for (const [name,fileList] of Object.entries(folders)) {
        tree.innerHTML += `<div class="folder-name">${name}</div>`;
        fileList.forEach(f => { if (f!=='README.md') tree.innerHTML += `<div class="file-item" style="padding-left:20px"><span>📄</span> ${f}</div>`; });
    }
}

function render3DModels(files, projectId) {
    const list = document.getElementById('3d-models-list');
    if (!list||!files['3d_models']) return;
    list.innerHTML = '';
    files['3d_models'].forEach(fname => {
        if (fname.endsWith('.stl')||fname.endsWith('.scad')) {
            const item = document.createElement('div');
            item.className = 'file-item';
            item.innerHTML = `<span>${fname.endsWith('.stl')?'🔷':'📐'}</span> ${fname}`;
            item.addEventListener('click', () => window.open(`${API_BASE}/api/project/${projectId}/file/3d_models/${fname}`,'_blank'));
            list.appendChild(item);
        }
    });
    if (list.children.length===0) list.innerHTML = '<p class="hint-text">暂无3D模型</p>';
}

// ====== Code Assistant (Quick buttons) ======
document.getElementById('explain-code-btn')?.addEventListener('click', async () => {
    const code = document.getElementById('code-editor')?.value?.trim();
    if (!code) { alert('请先选择或输入代码'); return; }
    appendCodeDesignMsg('assistant', '⏳ AI正在分析代码...');
    try {
        const resp = await fetch(`${API_BASE}/api/code/explain`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({code, language:'python'})
        });
        const data = await resp.json();
        if (data.success) updateLastCodeDesignMsg(data.explanation);
    } catch(e) { updateLastCodeDesignMsg('解释失败: '+e.message); }
});

document.getElementById('debug-code-btn')?.addEventListener('click', async () => {
    const code = document.getElementById('code-editor')?.value?.trim();
    const error = document.getElementById('code-output')?.textContent?.trim();
    if (!code) { alert('请先选择或输入代码'); return; }
    appendCodeDesignMsg('assistant', '⏳ AI正在分析错误...');
    try {
        const resp = await fetch(`${API_BASE}/api/code/debug`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({code, error_msg: error||'', language:'python'})
        });
        const data = await resp.json();
        if (data.success) updateLastCodeDesignMsg(data.debug_result);
    } catch(e) { updateLastCodeDesignMsg('调试失败: '+e.message); }
});

// ====== Code Design Chat (Interactive) ======
let codeDesignSessionId = null;

document.getElementById('code-design-start-btn')?.addEventListener('click', async () => {
    const pid = window.location.hash.replace('#','');
    appendCodeDesignMsg('assistant', '⏳ 正在启动代码设计助手...');
    try {
        const resp = await fetch(`${API_BASE}/api/code/design/start`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({project_id: pid})
        });
        const data = await resp.json();
        codeDesignSessionId = data.session_id;
        updateLastCodeDesignMsg(data.reply);
    } catch(e) { updateLastCodeDesignMsg('启动失败: '+e.message); }
});

document.getElementById('code-design-send-btn')?.addEventListener('click', sendCodeDesignMsg);
document.getElementById('code-design-input')?.addEventListener('keydown', e => {
    if (e.key==='Enter') sendCodeDesignMsg();
});

async function sendCodeDesignMsg() {
    const input = document.getElementById('code-design-input');
    const msg = input?.value.trim();
    if (!msg) return;
    if (!codeDesignSessionId) {
        // Auto-start session
        const pid = window.location.hash.replace('#','');
        const resp = await fetch(`${API_BASE}/api/code/design/start`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({project_id: pid, requirements: msg})
        });
        const data = await resp.json();
        codeDesignSessionId = data.session_id;
        appendCodeDesignMsg('user', msg);
        appendCodeDesignMsg('assistant', data.reply);
        input.value = '';
        return;
    }

    appendCodeDesignMsg('user', msg);
    input.value = '';
    appendCodeDesignMsg('assistant', '⏳ ...');

    try {
        const currentCode = document.getElementById('code-editor')?.value || '';
        const resp = await fetch(`${API_BASE}/api/code/design/chat?session_id=${codeDesignSessionId}&message=${encodeURIComponent(msg)}&current_code=${encodeURIComponent(currentCode)}`, {
            method:'POST'
        });
        const data = await resp.json();
        updateLastCodeDesignMsg(data.reply);
        // Auto-insert generated code if found
        const codeMatch = data.reply.match(/```(?:\w+)?\s*\n([\s\S]*?)```/);
        if (codeMatch) {
            const editor = document.getElementById('code-editor');
            if (editor && !editor.value.trim()) {
                editor.value = codeMatch[1].trim();
            }
        }
    } catch(e) { updateLastCodeDesignMsg('请求失败: '+e.message); }
}

// Import code
document.getElementById('import-code-btn')?.addEventListener('click', () => {
    document.getElementById('code-import-file')?.click();
});

document.getElementById('code-import-file')?.addEventListener('change', async function() {
    const file = this.files[0];
    if (!file) return;
    const code = await file.text();
    // Put in editor
    const editor = document.getElementById('code-editor');
    if (editor) editor.value = code;
    document.getElementById('code-filename').textContent = file.name;

    // Send to design agent for analysis
    if (!codeDesignSessionId) {
        const pid = window.location.hash.replace('#','');
        const resp = await fetch(`${API_BASE}/api/code/design/start`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({project_id: pid})
        });
        const data = await resp.json();
        codeDesignSessionId = data.session_id;
    }
    appendCodeDesignMsg('user', `📥 导入了文件: ${file.name}`);
    appendCodeDesignMsg('assistant', '⏳ 正在分析导入的代码...');
    try {
        const resp = await fetch(`${API_BASE}/api/code/design/import`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({session_id: codeDesignSessionId, code})
        });
        const data = await resp.json();
        codeDesignSessionId = data.session_id;
        updateLastCodeDesignMsg(data.reply);
    } catch(e) { updateLastCodeDesignMsg('分析失败: '+e.message); }
    this.value = '';
});

function appendCodeDesignMsg(role, text) {
    const container = document.getElementById('code-design-messages');
    if (!container) return;
    if (container.querySelector('div[style]') && container.children.length === 1) {
        container.innerHTML = ''; // Clear placeholder
    }
    const div = document.createElement('div');
    div.style.cssText = `margin-bottom:8px;padding:6px 10px;border-radius:8px;${role==='assistant'?'background:rgba(99,102,241,0.08)':'background:rgba(6,182,212,0.06)'}`;
    div.innerHTML = `<strong style="font-size:0.75rem;">${role==='assistant'?'🤖 代码助手':'👤 你'}</strong><div style="margin-top:4px;">${text.replace(/```(\w*)\s*\n([\s\S]*?)```/g,'<pre style="background:rgba(0,0,0,0.3);padding:6px;border-radius:4px;font-size:0.78rem;overflow-x:auto;"><code>$2</code></pre>').replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\n/g,'<br>')}</div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function updateLastCodeDesignMsg(text) {
    const container = document.getElementById('code-design-messages');
    if (!container) return;
    const last = container.lastElementChild;
    if (last) last.remove();
    appendCodeDesignMsg('assistant', text);
}

// ====== Export ======
document.getElementById('export-plan-btn')?.addEventListener('click', () => {
    const content = document.getElementById('plan-content')?.innerText;
    if (!content) return;
    const blob = new Blob([content],{type:'text/markdown'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download='教案.md'; a.click();
});

// ====== Back navigation ======
document.getElementById('back-from-project')?.addEventListener('click', () => {
    window.location.hash = '';
    showPage('home-page');
});

// ====== Knowledge Star Map ======
let starMap = null;
async function loadKnowledgeMap() {
    const graph = document.getElementById('knowledge-graph');
    if (!graph||starMap) return;
    starMap = new KnowledgeStarMap('knowledge-graph');
    try {
        const [prog,proj] = await Promise.all([fetch(`${API_BASE}/api/progress/student_001`),fetch(`${API_BASE}/api/projects`)]);
        const progress = await prog.json();
        const projData = await proj.json();
        const concepts = new Set();
        (projData.projects||[]).forEach(p=>{if(p.title)concepts.add(p.title);});
        (progress.knowledge_stars||[]).forEach(c=>concepts.add(c));
        starMap.setData([...concepts],progress);
    } catch(e) { starMap.setData([],{}); }
}

// ====== Achievement ======
async function loadAchievements() {
    const grid = document.getElementById('achievement-grid');
    if (!grid) return;
    try {
        const resp = await fetch(`${API_BASE}/api/achievements`);
        const data = await resp.json();
        if (!data.achievements||data.achievements.length===0) {
            const projResp = await fetch(`${API_BASE}/api/projects`);
            const projData = await projResp.json();
            if (projData.projects&&projData.projects.length>0) {
                grid.innerHTML = projData.projects.map(p=>`
                    <div class="achievement-card" onclick="openProject('${p.id}')">
                        <div class="card-img-placeholder">🚀</div>
                        <div class="card-body"><h3>${p.title||'未命名'}</h3><div class="card-meta">${p.grade_level||''} · ${new Date(p.created_at).toLocaleDateString('zh-CN')}</div></div>
                    </div>
                `).join('');
            } else { grid.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:2rem;">还没有完成的项目，快去探索吧！🚀</p>'; }
            return;
        }
        grid.innerHTML = data.achievements.map(a=>`
            <div class="achievement-card" ${a.project_id?`onclick="openProject('${a.project_id}')"`:''}>
                <div class="card-img-placeholder">🏆</div>
                <div class="card-body"><h3>${a.project_title||'STEM项目'}</h3><div class="card-meta">👤 ${a.student_name} · ${new Date(a.published_at).toLocaleDateString('zh-CN')}</div></div>
            </div>
        `).join('');
    } catch(e) { console.error(e); }
}

function openProject(projectId) { window.location.hash = projectId; loadProject(projectId); }

// ====== Collaboration ======
document.getElementById('collab-create-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('collab-name-input')?.value.trim();
    const pid = window.location.hash.replace('#','');
    if (!name||!pid) return;
    await fetch(`${API_BASE}/api/collab/create-team?project_id=${pid}&leader_name=${encodeURIComponent(name)}`,{method:'POST'});
    loadCollabTeam(pid);
});

document.getElementById('collab-join-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('collab-name-input')?.value.trim();
    const pid = window.location.hash.replace('#','');
    if (!name||!pid) return;
    await fetch(`${API_BASE}/api/collab/join`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:pid,student_name:name,role:'member'})});
    loadCollabTeam(pid);
});

document.getElementById('collab-send-btn')?.addEventListener('click', sendCollabMsg);
document.getElementById('collab-msg-input')?.addEventListener('keydown', e => { if (e.key==='Enter') sendCollabMsg(); });

async function sendCollabMsg() {
    const input = document.getElementById('collab-msg-input');
    const name = document.getElementById('collab-name-input')?.value.trim()||'匿名';
    const pid = window.location.hash.replace('#','');
    const msg = input?.value.trim();
    if (!msg||!pid) return;
    input.value = '';
    try {
        const resp = await fetch(`${API_BASE}/api/collab/chat?project_id=${pid}&student_name=${encodeURIComponent(name)}&message=${encodeURIComponent(msg)}`,{method:'POST'});
        const data = await resp.json();
        renderCollabMsgs(data.chat_history||[]);
    } catch(e) {}
}

async function loadCollabTeam(projectId) {
    try {
        const resp = await fetch(`${API_BASE}/api/collab/team/${projectId}`);
        const team = await resp.json();
        if (!team.has_team) return;
        const membersDiv = document.getElementById('collab-members');
        if (membersDiv) membersDiv.innerHTML = (team.members||[]).map(m=>`<div class="collab-member"><span>${m.role==='leader'?'👑':'👤'}</span><span>${m.name}</span><span class="role-badge ${m.role}">${m.role==='leader'?'组长':'组员'}</span></div>`).join('');
        renderCollabMsgs(team.chat_history||[]);
    } catch(e) {}
}

function renderCollabMsgs(history) {
    const container = document.getElementById('collab-messages');
    if (!container) return;
    container.innerHTML = history.slice(-30).map(m => {
        if (m.type==='system') return `<div class="collab-msg system">${m.message}</div>`;
        return `<div class="collab-msg ${m.type}"><span class="msg-sender">${m.type==='assistant'?'🤖':'💬'} ${m.user||'AI助教'}</span><div>${m.message||''}</div></div>`;
    }).join('');
    container.scrollTop = container.scrollHeight;
}

// ====== Loading ======
function showLoading(text) { const el=document.getElementById('loading-overlay'); if(el){el.classList.remove('hidden'); document.getElementById('loading-text').textContent=text||'加载中...';} }
function hideLoading() { document.getElementById('loading-overlay')?.classList.add('hidden'); }

// ====== Init ======
document.addEventListener('DOMContentLoaded', () => {
    loadBubbles();
    const hash = window.location.hash.replace('#','');
    if (hash) loadProject(hash);
});

window.addEventListener('hashchange', () => {
    const hash = window.location.hash.replace('#','');
    if (hash) loadProject(hash); else showPage('home-page');
});
