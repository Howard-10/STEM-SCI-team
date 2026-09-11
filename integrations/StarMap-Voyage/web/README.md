# ResearchPilot

ResearchPilot 是一个基于 `React + TypeScript + Vite` 的前端科研工作台原型，当前阶段只使用前端 mock 数据与 `localStorage`，不依赖真实后端或真实大模型 API。

## 启动方式

```powershell
npm.cmd install
npm.cmd run dev
```

默认访问地址通常为：

```txt
http://127.0.0.1:5178
```

## 当前阶段说明

- 当前默认运行在 `mock` provider 模式
- 不需要后端服务
- 不需要数据库
- 不需要填写 `OPENAI_*` 环境变量
- 项目数据保存在浏览器 `localStorage`

## 环境变量

项目根目录提供了 `.env.example`，包含未来接入真实后端或代理层时会用到的配置：

```env
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
VITE_AI_PROVIDER=mock
VITE_API_BASE_URL=
```

约定如下：

- `OPENAI_BASE_URL`：未来后端或代理层调用 OpenAI 兼容接口时使用
- `OPENAI_API_KEY`：未来后端或代理层使用的密钥
- `OPENAI_MODEL`：未来默认模型名
- `VITE_AI_PROVIDER`：前端当前使用的 provider，支持 `mock` 或 `http`
- `VITE_API_BASE_URL`：当前前端请求后端 API 的基础地址

## Provider 模式

### `mock`

- 默认模式
- 页面通过 `aiService -> mockProvider` 生成结果
- 适合纯前端演示和本地原型开发

### `http`

- 预留给后续真实后端接入
- 页面通过 `aiService -> httpProvider -> fetch transport` 发起请求
- 当前项目已经具备前端请求骨架，但并未附带真实后端实现

## 质量检查

```powershell
npm.cmd run lint
npm.cmd run build
```

在当前环境里，`build` 若受本机 Vite/Tailwind 原生依赖限制，可能需要在沙箱外执行；代码本身应保持可编译通过。
