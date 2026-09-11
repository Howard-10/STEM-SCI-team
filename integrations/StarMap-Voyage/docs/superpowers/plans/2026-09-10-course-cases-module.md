# 课程案例模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ResearchPilot 顶部新增“课程案例”并行入口，承载现有自适应 STEM 学习路径系统，同时保持两套项目职责清晰、地址可配置、旧系统功能不复制不改写。

**Architecture:** React 端新增独立 `CourseCasesPage` 路由，通过 `VITE_COURSE_CASE_URL` 指向旧课程案例服务的 `/app/` 页面。导航只负责模块入口和激活态，课程页负责嵌入、连接错误提示和新窗口兜底；旧系统继续作为独立服务运行。

**Tech Stack:** React 19, TypeScript, React Router 7, Vite 8, lucide-react, Tailwind CSS 4, FastAPI 静态页面服务。

## Global Constraints

- 不复制或重写旧自适应 STEM 学习路径系统的前端业务代码。
- 课程案例服务地址必须通过 `VITE_COURSE_CASE_URL` 配置，默认值为 `http://127.0.0.1:8800/app/`。
- 教学设计现有路由、接口和页面行为不能改变。
- 课程案例服务不可用时，页面必须显示明确的连接提示，并提供新窗口打开入口。
- 必须通过 TypeScript 构建检查，并验证新路由返回正确页面。

### Task 1: 配置与课程案例页面

**Files:**
- Modify: `web/src/config.ts`
- Create: `web/src/routes/CourseCasesPage.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Produces `COURSE_CASES_URL: string` for the new page.
- Produces route `/course-cases` rendering `CourseCasesPage`.

- [x] **Step 1: Add the configurable course-case URL**

  In `web/src/config.ts`, add:

  ```ts
  export const COURSE_CASES_URL = trimTrailingSlash(
    import.meta.env.VITE_COURSE_CASE_URL || 'http://127.0.0.1:8800/app/',
  )
  ```

- [x] **Step 2: Create the isolated page shell**

  Create `web/src/routes/CourseCasesPage.tsx` with a `Layout` wrapper, a heading, an iframe using `COURSE_CASES_URL`, a visible fallback link, and an iframe error note. The iframe must use `title="自适应 STEM 学习路径规划系统"`, `className="min-h-[720px] w-full"`, and `loading="eager"`.

- [x] **Step 3: Register the route**

  Import `CourseCasesPage` in `web/src/App.tsx` and add:

  ```tsx
  <Route path="/course-cases" element={<CourseCasesPage />} />
  ```

### Task 2: Navigation and environment documentation

**Files:**
- Modify: `web/src/components/layout/Navbar.tsx`
- Modify: `web/.env.example`
- Modify: `README.md`
- Modify: `start-all.bat`

**Interfaces:**
- Navigation exposes `/course-cases` with the label `课程案例`.
- Local setup documents `VITE_COURSE_CASE_URL` and the legacy service dependency.

- [x] **Step 1: Add the parallel navigation item**

  Add a `BookOpen` icon module entry `{ path: '/course-cases', label: '课程案例', icon: BookOpen }`, and make `getActiveModule()` recognize `/course-cases`.

- [x] **Step 2: Document the environment variable**

  Add `VITE_COURSE_CASE_URL=http://127.0.0.1:8800/app/` to `web/.env.example` with a comment identifying the legacy adaptive STEM learning-path service.

- [x] **Step 3: Document startup ordering**

  Update `README.md` and `start-all.bat` to state that the course-case page requires the legacy service at port `8800`, while preserving the existing four-service launcher behavior.

### Task 3: Verification

**Files:**
- Test: `web` build output and local HTTP routes.

- [x] **Step 1: Build the frontend**

  Run `npm.cmd run build` in `D:\揭榜挂帅\ResearchPilot\web` and require exit code `0`.

- [x] **Step 2: Start the Vite dev server on an available port**

  Run `npm.cmd run dev -- --host 127.0.0.1 --port 5178` and require `GET http://127.0.0.1:5178/` to return `200`.

- [x] **Step 3: Verify the backend dependency**

  Require `GET http://127.0.0.1:8800/app/` to return `200` and verify the page includes the legacy system title.
