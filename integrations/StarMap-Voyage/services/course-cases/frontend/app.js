let API_BASE = window.API_BASE || ""; // same origin
if (!API_BASE) {
    try {
        const loc = window.location;
        if (loc.protocol === 'file:') {
            API_BASE = 'http://127.0.0.1:8000';
        }
    } catch (_) { }
}

// DOM元素变量声明
let casesSection, singleQuestionSection, answerResultSection, questionsSection, evaluateSection, conceptsSection, conceptDetailSection, pathSection;
let questionCounter, singleQuestionContent, prevQuestionBtn, nextQuestionBtn, submitSingleAnswerBtn, generateSimilarBtn, backToCasesFromSingleBtn;
let answerResultContent, conceptsListSingle, nextQuestionAfterAnswerBtn, backToQuestionBtn;
let conceptTitle, conceptExplanation, backToConceptsBtn, viewLearningPathBtn;
let backToConceptDetailBtn, backToConceptsFromPathBtn;
let casesList, questionsList, submitAnswersBtn, backToCasesBtn, evaluateResult, backToQuestionsBtn, extractConceptsBtn, conceptsList, prePaths, postPaths;

// 全局状态
let currentCase = null;
let currentQuestions = [];
let currentQuestionIndex = 0;
let currentAnswers = {}; // question_id -> option key
let lastAnsweredTexts = [];
let currentConcept = null;
let currentConceptFromPath = null;
let generatedQuestions = []; // 存储生成的题目
let userAnswerHistory = {}; // 存储用户答题历史 {question_id: {answer: string, timestamp: number}}
let currentQuestionId = null; // 当前题目的ID
let isGeneratedQuestionMode = false; // 是否处于生成题目模式
let currentGeneratedQuestionIndex = 0; // 当前生成题目的索引
let returnToPathSection = false; // 是否从知识点详情返回到路径页面
let savedOriginalContext = null; // 进入生成题模式前的原题上下文 { caseId, questionIndex }

// 显示/隐藏section
function show(section) {
    if (!section) {
        console.error('Section is null:', section);
        return;
    }
    [casesSection, singleQuestionSection, answerResultSection, questionsSection,
        evaluateSection, conceptsSection, conceptDetailSection, pathSection]
        .forEach(s => {
            if (s) s.classList.add('hidden');
        });
    section.classList.remove('hidden');
}

// API请求
async function fetchJSON(url, options = {}) {
    try {
        const res = await fetch(url, options);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    } catch (error) {
        console.error('API请求失败:', error);
        throw error;
    }
}

// 渲染案例列表
function renderCases(cases) {
    if (!casesList) {
        console.error('casesList is not defined');
        return;
    }
    casesList.innerHTML = '';
    cases.forEach(c => {
        const div = document.createElement('div');
        div.className = 'case-item';
        div.innerHTML = `<div class="case-title">${c.title}</div><div class="case-desc">${c.desc || ''}</div>`;
        div.onclick = async () => {
            currentCase = c;
            currentQuestionIndex = 0;
            await loadSingleQuestion(c.id, 0);
        };
        casesList.appendChild(div);
    });

    // 添加"敬请期待"模块
    const comingSoonDiv = document.createElement('div');
    comingSoonDiv.className = 'case-item coming-soon';
    comingSoonDiv.innerHTML = `
        <div class="case-title">更多案例开发中</div>
        <div class="case-desc">敬请期待更多精彩的STEM学习案例！</div>
        <div class="coming-soon-badge">开发中</div>
    `;
    casesList.appendChild(comingSoonDiv);
}

// 加载案例列表
async function loadCases() {
    try {
        const data = await fetchJSON(`${API_BASE}/api/cases`);
        renderCases(data);
        show(casesSection);
    } catch (error) {
        console.error('加载案例列表失败:', error);
        alert('加载案例列表失败，请重试');
    }
}

// 渲染单个题目（支持多种题型）
function renderSingleQuestion(question, index, total) {
    if (!questionCounter) {
        console.error('questionCounter is not defined');
        return;
    }
    questionCounter.textContent = `${index + 1}/${total}`;
    currentQuestionId = question.id;

    if (!singleQuestionContent) {
        console.error('singleQuestionContent is not defined');
        return;
    }

    singleQuestionContent.innerHTML = '';

    // 题目类型标识
    const typeDiv = document.createElement('div');
    typeDiv.className = 'question-type';
    typeDiv.textContent = question.type || '选择题';
    singleQuestionContent.appendChild(typeDiv);

    // 题目文本
    const questionDiv = document.createElement('div');
    questionDiv.className = 'question';
    questionDiv.innerHTML = `<div>${question.text}</div>`;

    // 根据题目类型渲染不同的答题界面
    if (question.type === '选择题' || !question.type) {
        renderChoiceOptions(questionDiv, question);
    } else if (question.type === '填空题') {
        renderFillInOptions(questionDiv, question);
    } else if (question.type === '简答题') {
        renderShortAnswerOptions(questionDiv, question);
    } else if (question.type === '判断题') {
        renderTrueFalseOptions(questionDiv, question);
    }

    singleQuestionContent.appendChild(questionDiv);

    // 恢复用户之前的答案
    restoreUserAnswer(question.id);

    // 更新导航按钮状态
    if (prevQuestionBtn) {
        prevQuestionBtn.disabled = index === 0;
    }
    if (nextQuestionBtn) {
        const isLast = index === total - 1;
        nextQuestionBtn.disabled = false;
        if (isLast) {
            nextQuestionBtn.textContent = '完成练习';
            nextQuestionBtn.classList.add('finish-practice-btn');
        } else {
            nextQuestionBtn.textContent = '下一题';
            nextQuestionBtn.classList.remove('finish-practice-btn');
        }
    }
}

// 渲染选择题选项
function renderChoiceOptions(container, question) {
    if (!container || !question) {
        console.error('renderChoiceOptions: container or question is null');
        return;
    }
    const optionsDiv = document.createElement('div');
    optionsDiv.className = 'options';

    Object.entries(question.options).forEach(([key, text]) => {
        const label = document.createElement('label');
        label.className = 'option';

        const input = document.createElement('input');
        input.type = 'radio';
        input.name = 'single-question';
        input.value = key;
        input.id = `option-${key}`;

        label.appendChild(input);
        label.appendChild(document.createTextNode(`${key}. ${text}`));
        optionsDiv.appendChild(label);
    });

    container.appendChild(optionsDiv);
}

// 渲染填空题选项
function renderFillInOptions(container, question) {
    if (!container || !question) {
        console.error('renderFillInOptions: container or question is null');
        return;
    }
    const fillDiv = document.createElement('div');
    fillDiv.className = 'fill-options';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'fill-input';
    input.placeholder = '请输入答案';
    input.name = 'single-question';

    fillDiv.appendChild(input);
    container.appendChild(fillDiv);
}

// 渲染简答题选项
function renderShortAnswerOptions(container, question) {
    if (!container || !question) {
        console.error('renderShortAnswerOptions: container or question is null');
        return;
    }
    const textareaDiv = document.createElement('div');
    textareaDiv.className = 'short-answer-options';

    const textarea = document.createElement('textarea');
    textarea.className = 'short-answer-input';
    textarea.placeholder = '请输入你的答案...';
    textarea.rows = 4;
    textarea.name = 'single-question';

    textareaDiv.appendChild(textarea);
    container.appendChild(textareaDiv);
}

// 渲染判断题选项
function renderTrueFalseOptions(container, question) {
    if (!container || !question) {
        console.error('renderTrueFalseOptions: container or question is null');
        return;
    }
    const optionsDiv = document.createElement('div');
    optionsDiv.className = 'options';

    const trueLabel = document.createElement('label');
    trueLabel.className = 'option';

    const trueInput = document.createElement('input');
    trueInput.type = 'radio';
    trueInput.name = 'single-question';
    trueInput.value = '正确';
    trueInput.id = 'option-true';

    trueLabel.appendChild(trueInput);
    trueLabel.appendChild(document.createTextNode('正确'));
    optionsDiv.appendChild(trueLabel);

    const falseLabel = document.createElement('label');
    falseLabel.className = 'option';

    const falseInput = document.createElement('input');
    falseInput.type = 'radio';
    falseInput.name = 'single-question';
    falseInput.value = '错误';
    falseInput.id = 'option-false';

    falseLabel.appendChild(falseInput);
    falseLabel.appendChild(document.createTextNode('错误'));
    optionsDiv.appendChild(falseLabel);

    container.appendChild(optionsDiv);
}

// 加载单个题目
async function loadSingleQuestion(caseId, index) {
    try {
        const data = await fetchJSON(`${API_BASE}/api/question/${caseId}/${index}`);
        currentQuestions = await fetchJSON(`${API_BASE}/api/questions?case_id=${encodeURIComponent(caseId)}`);
        currentQuestionIndex = index;

        // 重置生成题目模式
        isGeneratedQuestionMode = false;
        currentGeneratedQuestionIndex = 0;

        renderSingleQuestion(data.question, data.index, data.total);
        show(singleQuestionSection);
    } catch (error) {
        console.error('加载题目失败:', error);
        alert('加载题目失败，请重试');
    }
}

// 提交单个题目答案
async function submitSingleAnswer() {
    if (!currentQuestionId) {
        console.error('currentQuestionId is not set');
        return;
    }
    const selectedAnswer = document.querySelector('input[name="single-question"]:checked');
    const textInput = document.querySelector('input[name="single-question"][type="text"]');
    const textarea = document.querySelector('textarea[name="single-question"]');

    let answer = '';
    if (selectedAnswer) {
        answer = selectedAnswer.value;
    } else if (textInput) {
        answer = textInput.value.trim();
    } else if (textarea) {
        answer = textarea.value.trim();
    }

    if (!answer) {
        alert('请选择或输入答案');
        return;
    }

    // 保存用户答案
    userAnswerHistory[currentQuestionId] = {
        answer: answer,
        timestamp: Date.now()
    };

    try {
        const data = await fetchJSON(`${API_BASE}/api/evaluate-single`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                case_id: currentCase.id,
                question_index: currentQuestionIndex,
                selected_answer: answer
            })
        });

        // 显示答题结果
        renderAnswerResult(data);

        // 重置按钮状态，确保显示"下一题"
        hideFinishPracticeButton();

        show(answerResultSection);
    } catch (error) {
        console.error('提交答案失败:', error);
        alert('提交答案失败，请重试');
    }
}

// 渲染答题结果
function renderAnswerResult(result) {
    if (!answerResultContent) {
        console.error('answerResultContent is not defined');
        return;
    }
    const statusClass = result.correct ? 'correct' : 'incorrect';
    const statusText = result.correct ? '✅ 回答正确' : '❌ 回答错误';

    answerResultContent.innerHTML = `
        <div class="answer-result ${result.correct ? 'result-correct' : 'result-incorrect'}">
            <div class="result-status ${statusClass}">${statusText}</div>
            <div class="correct-answer">
                <strong>参考答案：</strong><br>
                ${result.correct_answer}
            </div>
            <div class="explanation">
                <strong>答案解析：</strong><br>
                ${result.explanation}
            </div>
        </div>
    `;

    // 渲染知识点
    renderConceptsForSingle(result.concepts);
}

// 渲染单个题目的知识点
function renderConceptsForSingle(concepts) {
    if (!conceptsListSingle) {
        console.error('conceptsListSingle is not defined');
        return;
    }
    conceptsListSingle.innerHTML = '';
    if (!concepts || concepts.length === 0) {
        const noConceptDiv = document.createElement('div');
        noConceptDiv.className = 'no-concepts';
        noConceptDiv.textContent = '暂无相关知识点';
        conceptsListSingle.appendChild(noConceptDiv);
        return;
    }

    concepts.forEach(concept => {
        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.innerText = concept;
        chip.onclick = () => showConceptDetail(concept);
        conceptsListSingle.appendChild(chip);
    });
}

// 显示知识点详情
async function showConceptDetail(concept) {
    try {
        // 概念解析加载动画
        showLoading('正在分析知识点……');
        const data = await fetchJSON(`${API_BASE}/api/concept/${encodeURIComponent(concept)}`);
        currentConcept = concept;
        if (conceptTitle) conceptTitle.textContent = concept;
        if (conceptExplanation) conceptExplanation.textContent = sanitizeExplanation(data.explanation);

        // 检查是否从路径页面来
        if (returnToPathSection) {
            // 如果是从路径页面来的，显示返回路径的按钮
            if (backToConceptsBtn) backToConceptsBtn.textContent = '返回学习路径';
            if (backToConceptsBtn) backToConceptsBtn.onclick = () => {
                show(pathSection);
                returnToPathSection = false;
            };
            // 从路径进入：隐藏“查看学习路径”按钮
            if (viewLearningPathBtn) viewLearningPathBtn.style.display = 'none';
        } else {
            // 正常返回
            if (backToConceptsBtn) backToConceptsBtn.textContent = '返回知识点列表';
            if (backToConceptsBtn) backToConceptsBtn.onclick = () => {
                if (currentConceptFromPath) {
                    show(pathSection);
                    currentConceptFromPath = null;
                } else {
                    show(answerResultSection);
                }
            };
            // 普通进入：显示“查看学习路径”按钮
            if (viewLearningPathBtn) viewLearningPathBtn.style.display = '';
        }

        show(conceptDetailSection);
        hideLoading();
    } catch (error) {
        hideLoading();
        console.error('加载知识点详情失败:', error);
        alert('加载知识点详情失败，请重试');
    }
}

// 显示学习路径
async function showLearningPath() {
    if (!currentConcept) return;

    try {
        showLoading('正在智能生成学习路径......');
        const data = await fetchJSON(`${API_BASE}/api/learning-path`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ concepts: [currentConcept] })
        });

        // 基于知识图谱存在性对路径进行重排：不在知识图谱中的推荐知识点放入后继路径
        const adjusted = await rearrangePathsByKG(data);

        hideLoading();
        renderLearningPath(adjusted);
        show(pathSection);
    } catch (error) {
        hideLoading();
        console.error('加载学习路径失败:', error);
        alert('加载学习路径失败，请重试');
    }
}

// 检查单个知识点是否存在于知识图谱
async function conceptExistsInKG(concept) {
    try {
        const d = await fetchJSON(`${API_BASE}/api/concept/${encodeURIComponent(concept)}`);
        // 认为存在的条件：返回对象且存在非空解释文本
        if (d && typeof d.explanation === 'string' && d.explanation.trim().length > 0) {
            return true;
        }
        return false;
    } catch (_) {
        return false;
    }
}

// 依据知识图谱存在性调整学习路径：
// 规则：若某推荐知识点不在知识图谱中，则将其归入后继路径（去重并保序）
async function rearrangePathsByKG(data) {
    const pre = Array.isArray(data?.prerequisites) ? [...data.prerequisites] : [];
    const post = Array.isArray(data?.postrequisites) ? [...data.postrequisites] : [];

    // 并发检查存在性
    const checks = await Promise.all(pre.map(c => conceptExistsInKG(String(c).trim())));

    const newPre = [];
    const newPost = [...post];
    const postSet = new Set(newPost);

    pre.forEach((c, idx) => {
        const s = typeof c === 'string' ? c.trim() : String(c);
        if (!s) return;
        if (checks[idx] === true) {
            newPre.push(s);
        } else {
            if (!postSet.has(s)) {
                newPost.push(s);
                postSet.add(s);
            }
        }
    });

    return { prerequisites: newPre, postrequisites: newPost };
}

// 渲染学习路径（简化为“节点 + 箭头”样式，移除基础学科STEM四象限）
function renderLearningPath(data) {
    if (!prePaths || !postPaths) {
        console.error('prePaths or postPaths is not defined');
        return;
    }

    prePaths.innerHTML = '';
    postPaths.innerHTML = '';

    // 规范化与过滤路径：去重、裁剪空白、去除无效/过短/通用词/非知识点词（如“案例1”）
    const normalizePaths = (arr = []) => {
        const seen = new Set();
        const banned = new Set(['科学', '技术', '工程', '数学', 'STEM', '学科', '知识', '课程', '学习']);
        const cleaned = [];
        arr.forEach(item => {
            if (typeof item !== 'string') return;
            let s = item.trim();
            // 过滤过短、纯标点或通用词
            if (s.length < 2) return;
            if (banned.has(s)) return;
            if (/^[\p{P}\p{S}]+$/u.test(s)) return;
            // 过滤“案例X”或包含“案例”的非知识点项
            if (/^案例\s*\d*$/i.test(s) || s.includes('案例')) return;
            if (!seen.has(s)) {
                seen.add(s);
                cleaned.push(s);
            }
        });
        return cleaned;
    };

    const renderList = (container, paths, pathType) => {
        if (!container) {
            console.error('renderList: container is null');
            return;
        }

        const normalized = normalizePaths(paths);

        if (!normalized || normalized.length === 0) {
            const emptyDiv = document.createElement('div');
            emptyDiv.className = 'empty-path';
            emptyDiv.innerHTML = `
                <div>暂无${pathType === 'prerequisites' ? '前驱' : '后继'}学习路径</div>
                <small>继续学习当前知识点即可</small>
            `;
            container.appendChild(emptyDiv);
            return;
        }

        // 使用“节点 + 箭头”线性展示（垂直）
        const line = document.createElement('div');
        line.className = 'path-line';

        normalized.forEach((concept, idx) => {
            const node = document.createElement('button');
            node.type = 'button';
            node.className = 'path-node';
            node.textContent = concept;
            node.onclick = () => showConceptDetailFromPath(concept);
            line.appendChild(node);

            if (idx < normalized.length - 1) {
                const arrow = document.createElement('div');
                arrow.className = 'path-arrow';
                arrow.innerHTML = '➜';
                line.appendChild(arrow);
            }
        });

        container.appendChild(line);
    };

    // 渲染前驱路径
    renderList(prePaths, data.prerequisites || [], 'prerequisites');

    // 渲染后继路径
    renderList(postPaths, data.postrequisites || [], 'postrequisites');
}

// 从路径中显示知识点详情
async function showConceptDetailFromPath(concept) {
    try {
        // 概念解析加载动画
        showLoading('正在分析知识点……');
        const data = await fetchJSON(`${API_BASE}/api/concept/${encodeURIComponent(concept)}`);
        currentConceptFromPath = concept;
        currentConcept = concept;
        if (conceptTitle) conceptTitle.textContent = concept;
        if (conceptExplanation) conceptExplanation.textContent = sanitizeExplanation(data.explanation);

        // 设置返回按钮，直接返回学习路径
        if (backToConceptsBtn) backToConceptsBtn.textContent = '返回学习路径';
        if (backToConceptsBtn) backToConceptsBtn.onclick = () => {
            show(pathSection);
        };

        // 从路径进入：隐藏“查看学习路径”按钮
        if (viewLearningPathBtn) viewLearningPathBtn.style.display = 'none';

        show(conceptDetailSection);
        hideLoading();
    } catch (error) {
        hideLoading();
        console.error('加载知识点详情失败:', error);
        alert('加载知识点详情失败，请重试');
    }
}

// 清理可能误输出的提示词/系统指令内容，返回更干净的解释文本
function sanitizeExplanation(text) {
    if (typeof text !== 'string') return '';
    let t = String(text).trim();
    // 去除常见的提示词、角色标识、代码块等
    const patterns = [
        /<<[^>]*>>/g,
        /\bSYSTEM\b|\bASSISTANT\b|\bUSER\b/gi,
        /提示词|提示语|请根据|你是一个|角色设定|系统指令|Few[- ]Shot|示例输入|示例输出/gi,
        /^\s*#*\s*(system|assistant|user)\s*:?.*$/gim,
        /```[\s\S]*?```/g
    ];
    for (const p of patterns) t = t.replace(p, '');
    // 去除分隔线与多余空行
    t = t.replace(/-{3,}|={3,}|_{3,}|\*{3,}/g, '\n').replace(/\n{3,}/g, '\n\n');
    t = t.trim();
    if (t.length < 5) return '该知识点的解析正在生成或暂不可用，请稍后重试。';
    return t;
}

// 生成智能题目
async function generateSimilarQuestion() {
    try {
        showLoading('正在智能生成题目......');
        const data = await fetchJSON(`${API_BASE}/api/generate-similar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                case_id: currentCase.id,
                question_index: currentQuestionIndex,
                question_count: 3
            })
        });
        hideLoading();

        // 检查返回的数据
        if (!data.questions || data.questions.length === 0) {
            alert('生成题目失败，请重试');
            return;
        }

        // 原题文本（用于相似度校验）
        const originalQ = currentQuestions?.[currentQuestionIndex] || {};
        const originalText = getQuestionText(originalQ);

        // 将生成的题目添加到当前题目列表，且避免与原题完全一致
        generatedQuestions = data.questions.map((q) => {
            // 先做浅拷贝
            const gen = { ...q };
            // 若题干过于相似，则改写题干；若选择题且选项也高度相似，则打乱选项并保持答案
            if (isTooSimilar(originalText, getQuestionText(gen))) {
                gen.text = rewriteText(getQuestionText(gen));
            }
            if ((gen.type === '选择题' || !gen.type) && gen.options && isOptionsTooSimilar(originalQ.options, gen.options)) {
                const shuffled = shuffleOptionsMaintainAnswer(gen.options, gen.answer);
                gen.options = shuffled.options;
                gen.answer = shuffled.answer;
            }
            return gen;
        });

        // 确保生成的题目有正确的格式
        generatedQuestions = generatedQuestions.map((question, index) => {
            // 确保选项格式正确（ABCD而不是0123）
            if (question.type === '选择题' && question.options) {
                const newOptions = {};
                const optionKeys = Object.keys(question.options);
                const optionValues = Object.values(question.options);

                // 重新映射选项键为ABCD
                ['A', 'B', 'C', 'D'].forEach((key, i) => {
                    if (i < optionValues.length) {
                        newOptions[key] = optionValues[i];
                    }
                });

                // 更新答案键
                if (question.answer && typeof question.answer === 'string') {
                    const oldKey = question.answer;
                    const oldIndex = optionKeys.indexOf(oldKey);
                    if (oldIndex >= 0 && oldIndex < 4) {
                        question.answer = ['A', 'B', 'C', 'D'][oldIndex];
                    }
                }

                question.options = newOptions;
            }

            // 确保题目有完整的ID
            question.id = question.id || `gen_${index}`;

            // 再次兜底：若题干仍与原题完全一致，则附加轻微表述以避免完全相同
            const otext = getQuestionText(currentQuestions?.[currentQuestionIndex] || {});
            const gtext = getQuestionText(question);
            if (isTooSimilar(otext, gtext)) {
                question.text = rewriteText(gtext);
            }

            return question;
        });

        // 进入生成题模式前，保存原题上下文，便于结束后返回
        savedOriginalContext = {
            caseId: currentCase?.id,
            questionIndex: currentQuestionIndex
        };

        // 重置生成题目模式
        isGeneratedQuestionMode = true;
        currentGeneratedQuestionIndex = 0;

        // 直接显示第一个生成的题目，不显示提示
        startGeneratedQuestion(0);
    } catch (error) {
        hideLoading();
        console.error('生成智能题目失败:', error);
        alert('生成智能题目失败，请重试');
    }
}

// 显示生成的题目列表
function showGeneratedQuestions(questions) {
    // 创建题目列表界面
    const questionsListDiv = document.createElement('div');
    questionsListDiv.className = 'generated-questions-list';
    questionsListDiv.innerHTML = '<h3>生成的智能题目</h3>';

    questions.forEach((question, index) => {
        const questionDiv = document.createElement('div');
        questionDiv.className = 'generated-question';
        questionDiv.innerHTML = `
            <div class="question-type">${question.type || '选择题'}</div>
            <div class="question-text">${question.text || question.question || '题目内容'}</div>
            <button onclick="startGeneratedQuestion(${index})" class="primary">开始答题</button>
        `;
        questionsListDiv.appendChild(questionDiv);
    });

    // 替换当前内容
    if (singleQuestionContent) {
        singleQuestionContent.innerHTML = '';
        singleQuestionContent.appendChild(questionsListDiv);
    }
}

// 开始生成的题目
function startGeneratedQuestion(index) {
    if (index >= 0 && index < generatedQuestions.length) {
        const question = generatedQuestions[index];
        currentGeneratedQuestionIndex = index;

        // 确保题目数据结构完整
        const completeQuestion = {
            id: question.id || `gen_${index}`,
            type: question.type || '选择题',
            text: question.text || question.question || '题目内容',
            options: question.options || {},
            answer: question.answer || '',
            explanation: question.explanation || '暂无解析',
            concepts: question.concepts || []
        };

        renderSingleQuestion(completeQuestion, index, generatedQuestions.length);

        // 更新题目计数器
        if (questionCounter) questionCounter.textContent = `生成题 ${index + 1}/${generatedQuestions.length}`;

        // 更新上一题按钮（下一题按钮的文本与状态由 renderSingleQuestion 控制）
        if (prevQuestionBtn) prevQuestionBtn.disabled = index === 0;

        // 确保跳转到单题作答视图
        if (typeof show === 'function' && singleQuestionSection) {
            show(singleQuestionSection);
        }
    }
}

// 恢复用户之前的答案
function restoreUserAnswer(questionId) {
    if (!userAnswerHistory || !questionId) {
        console.error('restoreUserAnswer: userAnswerHistory or questionId is null');
        return;
    }
    const userAnswer = userAnswerHistory[questionId];
    if (userAnswer) {
        // 尝试恢复单选按钮
        const selectedAnswerElement = document.querySelector(`input[name="single-question"][value="${userAnswer.answer}"]`);
        if (selectedAnswerElement) {
            selectedAnswerElement.checked = true;
        } else {
            // 尝试恢复文本输入
            const textInput = document.querySelector(`input[name="single-question"][type="text"]`);
            if (textInput) {
                textInput.value = userAnswer.answer;
            }

            // 尝试恢复文本域（简答题）
            const textarea = document.querySelector(`textarea[name="single-question"]`);
            if (textarea) {
                textarea.value = userAnswer.answer;
            }
        }
    }
}

// 显示加载动画
function showLoading(message = '加载中...') {
    const loadingOverlay = document.createElement('div');
    loadingOverlay.className = 'loading-overlay';
    loadingOverlay.id = 'loading-overlay';

    loadingOverlay.innerHTML = `
        <div class="loading-modal">
            <div class="loading-spinner"></div>
            <div class="loading-text-shimmer">${message}</div>
        </div>
    `;

    document.body.appendChild(loadingOverlay);
}

// 隐藏加载动画
function hideLoading() {
    const loadingOverlay = document.getElementById('loading-overlay');
    if (loadingOverlay) {
        loadingOverlay.remove();
    }
}

// ===== 生成题目相似度与改写工具 =====
function getQuestionText(q = {}) {
    return (q && (q.text || q.question)) ? String(q.text || q.question) : '';
}

function normalizeTextForCompare(s) {
    if (typeof s !== 'string') return '';
    return s
        .toLowerCase()
        .replace(/[，。、“”‘’！!？?；;：（）()【】\[\]\-＿_—\-~·`'"<>＠@#＃$￥%^&*+=|\\/\n\r\t]/g, '')
        .replace(/\s+/g, '')
        .trim();
}

function jaccardSim(a, b) {
    const A = new Set(a.split(''));
    const B = new Set(b.split(''));
    let inter = 0;
    for (const x of A) if (B.has(x)) inter++;
    const union = A.size + B.size - inter || 1;
    return inter / union;
}

function isTooSimilar(a, b) {
    const na = normalizeTextForCompare(a);
    const nb = normalizeTextForCompare(b);
    if (!na || !nb) return false;
    if (na === nb) return true;
    return jaccardSim(na, nb) >= 0.92; // 阈值：高度相似则视为“过于相似”
}

function rewriteText(text) {
    if (typeof text !== 'string') return '';
    let t = text.trim();
    // 轻微改写：同义替换与措辞调整，尽量不改变考察知识点
    const replaces = [
        [/下列/g, '以下'],
        [/不正确/g, '不相符'],
        [/正确的是/g, '更为恰当的是'],
        [/最主要/g, '更关键'],
        [/主要/g, '关键'],
        [/方法/g, '方式'],
        [/现象/g, '表现'],
    ];
    replaces.forEach(([from, to]) => { t = t.replace(from, to); });
    // 若改动仍有限，则加上温和前缀/后缀避免完全相同
    if (isTooSimilar(text, t)) {
        t = `请基于理解进行判断：${t}`;
    }
    if (isTooSimilar(text, t)) {
        t = `${t}（请仔细审题后再作答）`;
    }
    return t;
}

function isOptionsTooSimilar(a = {}, b = {}) {
    const va = Object.values(a).map(v => normalizeTextForCompare(String(v || ''))).sort().join('|');
    const vb = Object.values(b).map(v => normalizeTextForCompare(String(v || ''))).sort().join('|');
    if (!va || !vb) return false;
    return va === vb || jaccardSim(va, vb) > 0.98;
}

function shuffleOptionsMaintainAnswer(options = {}, answer) {
    // 把选项转为数组 [{key:'A', value:'..'}, ...]
    const entries = Object.entries(options).map(([k, v]) => ({ key: k, value: v }));
    // 简单洗牌
    for (let i = entries.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [entries[i], entries[j]] = [entries[j], entries[i]];
    }
    // 重新映射到 A/B/C/D
    const mapKeys = ['A', 'B', 'C', 'D'];
    const newOptions = {};
    let newAnswer = answer;
    entries.forEach((item, idx) => {
        const newKey = mapKeys[idx] || String.fromCharCode(65 + idx);
        newOptions[newKey] = item.value;
        if (item.key === answer) newAnswer = newKey;
    });
    return { options: newOptions, answer: newAnswer };
}

// 事件监听器
if (prevQuestionBtn) {
    prevQuestionBtn.onclick = () => {
        if (isGeneratedQuestionMode && generatedQuestions.length > 0) {
            // 导航生成的题目
            if (currentGeneratedQuestionIndex > 0) {
                startGeneratedQuestion(currentGeneratedQuestionIndex - 1);
            }
        } else {
            // 导航原始题目
            if (currentQuestionIndex > 0) {
                loadSingleQuestion(currentCase.id, currentQuestionIndex - 1);
            }
        }
    };
}

if (nextQuestionBtn) {
    nextQuestionBtn.onclick = () => {
        if (isGeneratedQuestionMode && generatedQuestions.length > 0) {
            // 导航生成的题目
            if (currentGeneratedQuestionIndex < generatedQuestions.length - 1) {
                startGeneratedQuestion(currentGeneratedQuestionIndex + 1);
            }
        } else {
            // 导航原始题目
            if (currentQuestionIndex < currentQuestions.length - 1) {
                loadSingleQuestion(currentCase.id, currentQuestionIndex + 1);
            }
        }
    };
}

if (submitSingleAnswerBtn) {
    submitSingleAnswerBtn.onclick = submitSingleAnswer;
}

if (generateSimilarBtn) {
    generateSimilarBtn.onclick = generateSimilarQuestion;
}

if (backToCasesFromSingleBtn) {
    backToCasesFromSingleBtn.onclick = () => {
        // 重置生成题目模式
        isGeneratedQuestionMode = false;
        currentGeneratedQuestionIndex = 0;
        generatedQuestions = [];

        // 清空用户答题历史
        userAnswerHistory = {};
        currentAnswers = {};
        lastAnsweredTexts = [];

        // 重置当前状态
        currentCase = null;
        currentQuestions = [];
        currentQuestionIndex = 0;
        currentQuestionId = null;

        show(casesSection);
    };
}

if (nextQuestionAfterAnswerBtn) {
    nextQuestionAfterAnswerBtn.onclick = () => {
        // 检查按钮文本，如果是"完成练习"，则直接结束练习
        if (nextQuestionAfterAnswerBtn.textContent === '完成练习') {
            finishPracticeEarly();
            return;
        }

        if (isGeneratedQuestionMode) {
            if (currentGeneratedQuestionIndex < generatedQuestions.length - 1) {
                startGeneratedQuestion(currentGeneratedQuestionIndex + 1);
            } else {
                showFinishPracticeButton();
            }
        } else {
            if (currentQuestionIndex < currentQuestions.length - 1) {
                loadSingleQuestion(currentCase.id, currentQuestionIndex + 1);
            } else {
                showFinishPracticeButton();
            }
        }
    };
}

if (backToQuestionBtn) {
    backToQuestionBtn.onclick = () => show(singleQuestionSection);
}

if (backToConceptsBtn) {
    backToConceptsBtn.onclick = () => {
        if (currentConceptFromPath) {
            show(pathSection);
            currentConceptFromPath = null;
        } else {
            show(answerResultSection);
        }
    };
}

if (viewLearningPathBtn) {
    viewLearningPathBtn.onclick = showLearningPath;
}

if (backToConceptDetailBtn) {
    backToConceptDetailBtn.onclick = () => show(conceptDetailSection);
}

if (backToConceptsFromPathBtn) {
    backToConceptsFromPathBtn.onclick = () => {
        currentConceptFromPath = null;
        show(answerResultSection);
    };
}

// 原有功能的事件监听器
if (backToCasesBtn) {
    backToCasesBtn.onclick = () => show(casesSection);
}
if (backToQuestionsBtn) {
    backToQuestionsBtn.onclick = () => show(questionsSection);
}

if (extractConceptsBtn) {
    extractConceptsBtn.onclick = async () => {
        const merged = lastAnsweredTexts.join('；');
        const { concepts } = await fetchJSON(`${API_BASE}/api/concepts`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question_text: merged, top_k: 8 })
        });

        if (!conceptsList) {
            console.error('conceptsList is not defined');
            return;
        }
        conceptsList.innerHTML = '';
        concepts.forEach(c => {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.innerText = c;
            chip.onclick = () => showConceptDetail(c);
            conceptsList.appendChild(chip);
        });
        show(conceptsSection);
    };
}

// 提前结束练习
function finishPracticeEarly() {
    // 检查是否有未答题目
    let unansweredCount = 0;
    if (isGeneratedQuestionMode) {
        unansweredCount = generatedQuestions.length - Object.keys(userAnswerHistory).length;
    } else {
        unansweredCount = currentQuestions.length - Object.keys(userAnswerHistory).length;
    }

    if (unansweredCount > 0) {
        const confirmEnd = confirm(`还有 ${unansweredCount} 道题目未答，确定要结束练习吗？`);
        if (!confirmEnd) return;
    }

    // 使用居中覆盖层提示，并在短暂提示后自动跳转
    if (isGeneratedQuestionMode) {
        showLoading('练习已结束，正在返回原题...');
        setTimeout(() => {
            // 退出生成题模式并返回进入前的原题
            isGeneratedQuestionMode = false;
            currentGeneratedQuestionIndex = 0;
            generatedQuestions = [];

            if (savedOriginalContext && savedOriginalContext.caseId != null && savedOriginalContext.questionIndex != null) {
                try {
                    loadSingleQuestion(savedOriginalContext.caseId, savedOriginalContext.questionIndex);
                } catch (e) {
                    console.error('返回原题失败，回退到首页:', e);
                    clearAllState();
                    show(casesSection);
                }
            } else {
                // 若无上下文可恢复，则回首页
                clearAllState();
                show(casesSection);
            }

            hideFinishPracticeButton();
            hideLoading();
        }, 700);
    } else {
        showLoading('练习已结束，正在返回首页...');
        setTimeout(() => {
            clearAllState();
            show(casesSection);
            hideFinishPracticeButton();
            hideLoading();
        }, 700);
    }
}

// 显示练习完成选择
function showPracticeCompletion() {
    if (!answerResultSection) {
        console.error('answerResultSection is not defined');
        return;
    }
    answerResultSection.style.display = 'none';
    const practiceCompletionDiv = document.getElementById('practice-completion');
    if (practiceCompletionDiv) {
        practiceCompletionDiv.style.display = 'block';
    }
}

// 返回主页
function returnHome() {
    // 清空所有状态
    clearAllState();
    show(casesSection);
}

// 重新做题
async function restartPractice() {
    try {
        showLoading('正在智能生成新题目......');

        // 获取当前题目的知识点
        let concepts = [];
        if (isGeneratedQuestionMode && generatedQuestions.length > 0) {
            concepts = generatedQuestions[currentGeneratedQuestionIndex].concepts || [];
        } else if (currentQuestions.length > 0) {
            concepts = currentQuestions[currentQuestionIndex].concepts || [];
        }

        if (concepts.length === 0) {
            hideLoading();
            alert('无法获取知识点信息，请重新选择案例');
            return;
        }

        // 生成新的题目
        const data = await fetchJSON(`${API_BASE}/api/generate-similar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                case_id: currentCase.id,
                question_index: currentQuestionIndex,
                question_count: 5 // 生成更多题目
            })
        });

        hideLoading();

        if (!data.questions || data.questions.length === 0) {
            alert('生成新题目失败，请重试');
            return;
        }

        // 清空答题历史
        userAnswerHistory = {};

        // 设置新的题目
        generatedQuestions = data.questions.map((question, index) => {
            // 确保选项格式正确
            if (question.type === '选择题' && question.options) {
                const newOptions = {};
                const optionValues = Object.values(question.options);

                ['A', 'B', 'C', 'D'].forEach((key, i) => {
                    if (i < optionValues.length) {
                        newOptions[key] = optionValues[i];
                    }
                });

                question.options = newOptions;
            }

            question.id = `restart_${index}`;
            return question;
        });

        // 打乱题目顺序
        generatedQuestions = shuffleArray(generatedQuestions);

        // 重置状态
        isGeneratedQuestionMode = true;
        currentGeneratedQuestionIndex = 0;

        // 显示第一题
        startGeneratedQuestion(0);

        // 隐藏练习完成选择
        const practiceCompletionDiv = document.getElementById('practice-completion');
        if (practiceCompletionDiv) {
            practiceCompletionDiv.style.display = 'none';
        }

    } catch (error) {
        hideLoading();
        console.error('重新做题失败:', error);
        alert('重新做题失败，请重试');
    }
}

// 打乱数组顺序
function shuffleArray(array) {
    const shuffled = [...array];
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return shuffled;
}

// 清空所有状态
function clearAllState() {
    userAnswerHistory = {};
    currentAnswers = {};
    lastAnsweredTexts = [];
    currentCase = null;
    currentQuestions = [];
    currentQuestionIndex = 0;
    currentQuestionId = null;
    isGeneratedQuestionMode = false;
    currentGeneratedQuestionIndex = 0;
    generatedQuestions = [];
    savedOriginalContext = null;
}

// 初始化
document.addEventListener('DOMContentLoaded', function () {
    // 获取DOM元素
    casesSection = document.getElementById('cases-section');
    singleQuestionSection = document.getElementById('single-question-section');
    answerResultSection = document.getElementById('answer-result-section');
    questionsSection = document.getElementById('questions-section');
    evaluateSection = document.getElementById('evaluate-section');
    conceptsSection = document.getElementById('concepts-section');
    conceptDetailSection = document.getElementById('concept-detail-section');
    pathSection = document.getElementById('path-section');

    // 获取单题相关元素
    questionCounter = document.getElementById('question-counter');
    singleQuestionContent = document.getElementById('single-question-content');
    prevQuestionBtn = document.getElementById('prev-question');
    nextQuestionBtn = document.getElementById('next-question');
    submitSingleAnswerBtn = document.getElementById('submit-single-answer');
    generateSimilarBtn = document.getElementById('generate-similar');
    backToCasesFromSingleBtn = document.getElementById('back-to-cases-from-single');

    // 获取答题结果相关元素
    answerResultContent = document.getElementById('answer-result-content');
    conceptsListSingle = document.getElementById('concepts-list-single');
    nextQuestionAfterAnswerBtn = document.getElementById('next-question-after-answer');
    backToQuestionBtn = document.getElementById('back-to-question');

    // 获取知识点详情相关元素
    conceptTitle = document.getElementById('concept-title');
    conceptExplanation = document.getElementById('concept-explanation');
    backToConceptsBtn = document.getElementById('back-to-concepts');
    viewLearningPathBtn = document.getElementById('view-learning-path');

    // 获取学习路径相关元素
    backToConceptDetailBtn = document.getElementById('back-to-concept-detail');
    backToConceptsFromPathBtn = document.getElementById('back-to-concepts-from-path');

    // 获取原有元素
    casesList = document.getElementById('cases-list');
    questionsList = document.getElementById('questions-list');
    submitAnswersBtn = document.getElementById('submit-answers');
    backToCasesBtn = document.getElementById('back-to-cases');
    evaluateResult = document.getElementById('evaluate-result');
    backToQuestionsBtn = document.getElementById('back-to-questions');
    extractConceptsBtn = document.getElementById('extract-concepts');
    conceptsList = document.getElementById('concepts-list');
    prePaths = document.getElementById('pre-paths');
    postPaths = document.getElementById('post-paths');

    // 获取其他按钮元素
    const backToCasesFromResultBtn = document.getElementById('back-to-cases-from-result');
    const backToPathBtn = document.getElementById('back-to-path');
    const finishPracticeEarlyBtn = document.getElementById('finish-practice-early');
    const returnHomeBtn = document.getElementById('return-home');
    const restartPracticeBtn = document.getElementById('restart-practice');

    // 绑定事件监听器
    if (prevQuestionBtn) {
        prevQuestionBtn.onclick = () => {
            if (isGeneratedQuestionMode && generatedQuestions.length > 0) {
                if (currentGeneratedQuestionIndex > 0) {
                    startGeneratedQuestion(currentGeneratedQuestionIndex - 1);
                }
            } else {
                if (currentQuestionIndex > 0) {
                    loadSingleQuestion(currentCase.id, currentQuestionIndex - 1);
                }
            }
        };
    }

    if (nextQuestionBtn) {
        nextQuestionBtn.onclick = () => {
            // 若已到最后一题，触发结束
            if (nextQuestionBtn.textContent === '完成练习') {
                if (typeof finishPracticeEarly === 'function') {
                    finishPracticeEarly();
                } else {
                    // 回退方案：显示答题结果区的完成面板
                    const completion = document.getElementById('practice-completion');
                    if (completion) {
                        completion.style.display = '';
                        show(answerResultSection);
                    }
                }
                return;
            }

            if (isGeneratedQuestionMode && generatedQuestions.length > 0) {
                if (currentGeneratedQuestionIndex < generatedQuestions.length - 1) {
                    startGeneratedQuestion(currentGeneratedQuestionIndex + 1);
                }
            } else {
                if (currentQuestionIndex < currentQuestions.length - 1) {
                    loadSingleQuestion(currentCase.id, currentQuestionIndex + 1);
                }
            }
        };
    }

    if (submitSingleAnswerBtn) {
        submitSingleAnswerBtn.onclick = submitSingleAnswer;
    }

    if (generateSimilarBtn) {
        generateSimilarBtn.onclick = generateSimilarQuestion;
    }

    if (backToCasesFromSingleBtn) {
        backToCasesFromSingleBtn.onclick = () => {
            clearAllState();
            show(casesSection);
        };
    }

    if (backToCasesFromResultBtn) {
        backToCasesFromResultBtn.onclick = () => {
            clearAllState();
            show(casesSection);
        };
    }

    if (nextQuestionAfterAnswerBtn) {
        nextQuestionAfterAnswerBtn.onclick = () => {
            // 检查按钮文本，如果是"完成练习"，则直接结束练习
            if (nextQuestionAfterAnswerBtn.textContent === '完成练习') {
                finishPracticeEarly();
                return;
            }

            if (isGeneratedQuestionMode) {
                if (currentGeneratedQuestionIndex < generatedQuestions.length - 1) {
                    startGeneratedQuestion(currentGeneratedQuestionIndex + 1);
                } else {
                    showFinishPracticeButton();
                }
            } else {
                if (currentQuestionIndex < currentQuestions.length - 1) {
                    loadSingleQuestion(currentCase.id, currentQuestionIndex + 1);
                } else {
                    showFinishPracticeButton();
                }
            }
        };
    }

    if (backToQuestionBtn) {
        backToQuestionBtn.onclick = () => {
            show(singleQuestionSection);
        };
    }

    if (backToConceptsBtn) {
        backToConceptsBtn.onclick = () => {
            if (currentConceptFromPath) {
                show(pathSection);
                currentConceptFromPath = null;
            } else {
                show(answerResultSection);
            }
        };
    }

    if (viewLearningPathBtn) {
        viewLearningPathBtn.onclick = showLearningPath;
    }

    if (backToConceptDetailBtn) {
        backToConceptDetailBtn.onclick = () => show(conceptDetailSection);
    }

    if (backToConceptsFromPathBtn) {
        backToConceptsFromPathBtn.onclick = () => {
            currentConceptFromPath = null;
            show(answerResultSection);
        };
    }

    if (backToCasesBtn) {
        backToCasesBtn.onclick = () => show(casesSection);
    }

    if (backToQuestionsBtn) {
        backToQuestionsBtn.onclick = () => show(questionsSection);
    }

    if (extractConceptsBtn) {
        extractConceptsBtn.onclick = async () => {
            try {
                const merged = lastAnsweredTexts.join('；');
                const { concepts } = await fetchJSON(`${API_BASE}/api/concepts`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question_text: merged, top_k: 8 })
                });

                if (conceptsList) {
                    conceptsList.innerHTML = '';
                    concepts.forEach(c => {
                        const chip = document.createElement('span');
                        chip.className = 'chip';
                        chip.innerText = c;
                        chip.onclick = () => showConceptDetail(c);
                        conceptsList.appendChild(chip);
                    });
                    show(conceptsSection);
                }
            } catch (error) {
                console.error('提取知识点失败:', error);
                alert('提取知识点失败，请重试');
            }
        };
    }

    if (finishPracticeEarlyBtn) {
        finishPracticeEarlyBtn.onclick = finishPracticeEarly;
    }

    if (returnHomeBtn) {
        returnHomeBtn.onclick = returnHome;
    }

    if (restartPracticeBtn) {
        restartPracticeBtn.onclick = restartPractice;
    }

    // 初始加载案例
    loadCases();
});

// 显示提前结束练习按钮
function showFinishPracticeButton() {
    // 不再单独显示提前结束练习按钮
    // 而是修改下一题按钮的文本和行为
    if (nextQuestionAfterAnswerBtn) {
        nextQuestionAfterAnswerBtn.textContent = '完成练习';
        nextQuestionAfterAnswerBtn.className = 'primary finish-practice-btn';
    }
}

// 隐藏提前结束练习按钮
function hideFinishPracticeButton() {
    if (nextQuestionAfterAnswerBtn) {
        nextQuestionAfterAnswerBtn.textContent = '下一题';
        nextQuestionAfterAnswerBtn.className = 'primary';
    }
} 