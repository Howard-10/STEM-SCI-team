/**
 * Interactive Knowledge Star Map v2
 * Category-grouped constellation visualization
 */
class KnowledgeStarMap {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.canvas = document.createElement('canvas');
        this.canvas.style.width = '100%';
        this.canvas.style.height = '480px';
        this.container.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        this.nodes = [];
        this.edges = [];
        this.categories = [];
        this.hoveredNode = null;
        this.animFrame = null;
        this.dpr = window.devicePixelRatio || 1;

        this.resize();
        window.addEventListener('resize', () => this.resize());
        this.initEvents();
        this.startAnimation();
    }

    resize() {
        const rect = this.container.getBoundingClientRect();
        this.canvas.width = rect.width * this.dpr;
        this.canvas.height = 480 * this.dpr;
        this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
        this.W = rect.width;
        this.H = 480;
        if (this.nodes.length > 0) this._layout();
    }

    // ---- Category definitions ----
    static CATEGORIES = [
        { id: 'physics', name: '物理', icon: '⚡', color: '#74b9ff', angle: -Math.PI/2 },
        { id: 'chemistry', name: '化学', icon: '🧪', color: '#a29bfe', angle: -Math.PI/7 },
        { id: 'biology', name: '生物', icon: '🧬', color: '#00b894', angle: Math.PI/5 },
        { id: 'geoscience', name: '地学', icon: '🌍', color: '#fdcb6e', angle: Math.PI/2 },
        { id: 'engineering', name: '工程', icon: '⚙️', color: '#e17055', angle: 4*Math.PI/5 },
        { id: 'coding', name: '编程', icon: '💻', color: '#fd79a8', angle: 6*Math.PI/5 },
        { id: 'math', name: '数学', icon: '📐', color: '#00cec9', angle: 8*Math.PI/5 },
        { id: 'ai', name: 'AI', icon: '🤖', color: '#6366f1', angle: 9*Math.PI/5 },
    ];

    static DOMAIN_KEYWORDS = {
        physics: ['力','运动','光','声','电','磁','热','波','速度','加速度','能量','牛顿','欧姆','电路','电压','电流'],
        chemistry: ['反应','分子','元素','溶液','酸','碱','pH','化学','试剂','滴定'],
        biology: ['细胞','基因','DNA','植物','动物','生态','光合','呼吸','生物','酶'],
        geoscience: ['地球','气象','天文','地质','地震','火山','气候','环境','天气','太阳'],
        engineering: ['搭建','组装','机械','结构','设计','制作','传感器','Arduino','电路','电机','3D'],
        coding: ['代码','程序','算法','变量','函数','循环','Python','Scratch','编程','调试'],
        math: ['数','计算','几何','统计','概率','方程','函数','测量','体积','面积','角度'],
        ai: ['智能','机器','模型','训练','识别','AI','人工智能','学习'],
    };

    // ---- Data loading ----
    setData(concepts, progress) {
        this.nodes = [];
        this.edges = [];
        const litSet = new Set(progress?.knowledge_stars || []);
        const allConcepts = concepts.length > 0 ? concepts : [
            '传感器原理','电路基础','编程入门','力学基础','数据分析',
            '3D设计','化学实验','生物观察','数学建模','工程思维',
            '算法设计','物联网','人工智能','环保科学','能源技术',
            '光学','声学','电磁学','热力学','运动学',
        ];

        // Build categorized nodes
        this.categories = KnowledgeStarMap.CATEGORIES.map(cat => ({
            ...cat,
            nodes: [],
            litCount: 0,
        }));

        allConcepts.forEach(name => {
            const cat = this._classify(name);
            const isLit = litSet.has(name);
            cat.nodes.push({ id: name, category: cat.id, isLit, pulse: Math.random() * Math.PI * 2 });
            if (isLit) cat.litCount++;
        });

        this.categories = this.categories.filter(c => c.nodes.length > 0);
        this._layout();
    }

    _classify(name) {
        for (const cat of KnowledgeStarMap.CATEGORIES) {
            const kws = KnowledgeStarMap.DOMAIN_KEYWORDS[cat.id] || [];
            if (kws.some(kw => name.includes(kw))) {
                return this.categories.find(c => c.id === cat.id) || this.categories[4];
            }
        }
        return this.categories[4]; // default to engineering
    }

    _layout() {
        const W = this.W, H = this.H;
        const cx = W / 2, cy = H / 2 - 10;
        this.nodes = [];

        const nCats = this.categories.length;
        const baseRadius = Math.min(W, H) * 0.3;

        this.categories.forEach((cat, ci) => {
            const angle = (ci / nCats) * Math.PI * 2 - Math.PI / 2;
            const catCx = cx + Math.cos(angle) * baseRadius * 0.7;
            const catCy = cy + Math.sin(angle) * baseRadius * 0.55;
            cat.cx = catCx;
            cat.cy = catCy;

            const n = cat.nodes.length;
            cat.nodes.forEach((node, ni) => {
                const spreadR = 50 + n * 5;
                const nodeAngle = (ni / n) * Math.PI * 2 + (ci * 0.5);
                const dist = 15 + Math.random() * spreadR;
                node.x = catCx + Math.cos(nodeAngle) * dist;
                node.y = catCy + Math.sin(nodeAngle) * dist * 0.7;
                node.size = node.isLit ? 10 : 7;
                node.catColor = cat.color;
                node.category = cat.id;
                this.nodes.push(node);
            });

            // Intra-category edges
            for (let i = 0; i < cat.nodes.length - 1; i++) {
                for (let j = i + 1; j < Math.min(i + 3, cat.nodes.length); j++) {
                    this.edges.push({
                        from: cat.nodes[i], to: cat.nodes[j],
                        lit: cat.nodes[i].isLit && cat.nodes[j].isLit,
                        color: cat.color,
                    });
                }
            }
        });
    }

    // ---- Interaction ----
    initEvents() {
        this.canvas.addEventListener('mousemove', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;
            this.hoveredNode = null;
            for (const node of this.nodes) {
                const dx = node.x - mx, dy = node.y - my;
                if (Math.sqrt(dx*dx + dy*dy) < node.size + 6) {
                    this.hoveredNode = node; break;
                }
            }
            this.canvas.style.cursor = this.hoveredNode ? 'pointer' : 'default';
        });

        this.canvas.addEventListener('click', () => {
            if (this.hoveredNode) this._showTooltip(this.hoveredNode);
        });

        this.canvas.addEventListener('mouseleave', () => { this.hoveredNode = null; });
    }

    _showTooltip(node) {
        let tip = document.getElementById('star-tooltip');
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'star-tooltip';
            tip.style.cssText = 'position:absolute;background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:10px 14px;font-size:0.82rem;z-index:30;pointer-events:none;max-width:180px;box-shadow:0 4px 16px rgba(0,0,0,0.4);';
            this.container.appendChild(tip);
        }
        const cat = this.categories.find(c => c.id === node.category);
        tip.innerHTML = `<strong>${node.id}</strong><br><span style="color:${node.catColor}">${cat?.icon||''} ${cat?.name||''}</span><br><span style="color:${node.isLit?'var(--green)':'var(--text-muted)'}">${node.isLit?'✨ 已掌握':'🔒 待探索'}</span>`;
        tip.style.left = Math.min(node.x + 16, this.W - 190) + 'px';
        tip.style.top = Math.max(0, node.y - 40) + 'px';
        tip.style.display = 'block';
        clearTimeout(this._tipTimer);
        this._tipTimer = setTimeout(() => { if (tip) tip.style.display = 'none'; }, 3500);
    }

    // ---- Animation ----
    startAnimation() {
        const animate = () => {
            const ctx = this.ctx;
            ctx.clearRect(0, 0, this.W, this.H);

            // Category labels and background circles
            this.categories.forEach(cat => {
                // Subtle background
                ctx.beginPath();
                ctx.arc(cat.cx, cat.cy, 60, 0, Math.PI * 2);
                ctx.fillStyle = cat.color.replace(')', ',0.04)').replace('rgb', 'rgba');
                if (cat.color.startsWith('#')) {
                    ctx.fillStyle = cat.color + '0a';
                }
                ctx.fill();

                // Label
                ctx.fillStyle = cat.color;
                ctx.font = '600 13px "Microsoft YaHei","PingFang SC",sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(cat.icon + ' ' + cat.name, cat.cx, cat.cy - 48);

                // Lit count badge
                ctx.fillStyle = cat.color.replace(')', ',0.15)').replace('rgb', 'rgba');
                if (cat.color.startsWith('#')) ctx.fillStyle = cat.color + '22';
                ctx.beginPath();
                const bw = ctx.measureText(`${cat.litCount}/${cat.nodes.length}`).width + 16;
                ctx.roundRect(cat.cx - bw/2, cat.cy + 42, bw, 20, 10);
                ctx.fill();
                ctx.fillStyle = cat.color;
                ctx.font = '500 11px "Microsoft YaHei","PingFang SC",sans-serif';
                ctx.fillText(`${cat.litCount}/${cat.nodes.length}`, cat.cx, cat.cy + 56);
            });

            // Edges
            this.edges.forEach(edge => {
                ctx.beginPath();
                ctx.moveTo(edge.from.x, edge.from.y);
                ctx.lineTo(edge.to.x, edge.to.y);
                ctx.strokeStyle = edge.lit ? (edge.color + '55') : 'rgba(255,255,255,0.05)';
                ctx.lineWidth = edge.lit ? 1.2 : 0.5;
                ctx.stroke();
            });

            // Nodes
            const now = Date.now() / 1000;
            this.nodes.forEach(node => {
                node.pulse += (node.isLit ? 0.03 : 0.01);
                const pulse = 1 + Math.sin(node.pulse) * (node.isLit ? 0.2 : 0.08);
                const r = node.size * pulse;

                // Glow for lit nodes
                if (node.isLit) {
                    const glow = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, r * 3.5);
                    glow.addColorStop(0, node.catColor + '55');
                    glow.addColorStop(1, 'rgba(0,0,0,0)');
                    ctx.beginPath();
                    ctx.arc(node.x, node.y, r * 3.5, 0, Math.PI * 2);
                    ctx.fillStyle = glow;
                    ctx.fill();
                }

                // Core
                ctx.beginPath();
                ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
                ctx.fillStyle = node.isLit ? node.catColor : 'rgba(255,255,255,0.1)';
                ctx.fill();
                if (!node.isLit) {
                    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
                    ctx.lineWidth = 0.8;
                    ctx.stroke();
                }

                // Hover highlight
                if (node === this.hoveredNode) {
                    ctx.beginPath();
                    ctx.arc(node.x, node.y, r + 5, 0, Math.PI * 2);
                    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
                    ctx.lineWidth = 2;
                    ctx.setLineDash([3, 2]);
                    ctx.stroke();
                    ctx.setLineDash([]);
                }
            });

            this.animFrame = requestAnimationFrame(animate);
        };
        animate();
    }

    destroy() {
        if (this.animFrame) cancelAnimationFrame(this.animFrame);
        this.canvas.remove();
    }
}

window.KnowledgeStarMap = KnowledgeStarMap;
