import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import HomePage from './routes/HomePage'
import TeachPage from './routes/TeachPage'
import StarMapPage from './routes/StarMapPage'
import AchievementPage from './routes/AchievementPage'
import TeachProjectsPage from './routes/teaching/TeachProjectsPage'
import CourseCasesPage from './routes/CourseCasesPage'

function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />

        {/* 教学设计模块 */}
        <Route path="/teach" element={<TeachPage />} />
        <Route path="/teach/projects" element={<TeachProjectsPage />} />
        {/* 课程案例模块：承载独立的自适应 STEM 学习路径服务 */}
        <Route path="/course-cases" element={<CourseCasesPage />} />
        <Route path="/star-map" element={<StarMapPage />} />
        <Route path="/achievements" element={<AchievementPage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  )
}

export default App
