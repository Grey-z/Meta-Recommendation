import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { HomePage } from './ui/HomePage'
import { MetaRecPage } from './ui/MetaRecPage'
import { ResearchPage } from './ui/ResearchPage'
import { DashboardPage } from './ui/DashboardPage'
import 'bootstrap-icons/font/bootstrap-icons.css'
import './styles.css'

const container = document.getElementById('root')!
const root = createRoot(container)
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/MetaRec" element={<MetaRecPage />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        {/* Back-compat: the old debug page is now a tab in the admin dashboard. */}
        <Route path="/debug" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)

