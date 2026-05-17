import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { HomePage } from './ui/HomePage'
import { MetaRecPage } from './ui/MetaRecPage'
import { ResearchPage } from './ui/ResearchPage'
import { DebugPage } from './ui/DebugPage'
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
        <Route path="/debug" element={<DebugPage />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)

