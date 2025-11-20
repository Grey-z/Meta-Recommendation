import React, { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './ResearchPage.css'

export function ResearchPage(): JSX.Element {
  const navigate = useNavigate()
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // 加载research.html的内容
    const loadResearchContent = async () => {
      try {
        const response = await fetch('/research.html')
        const html = await response.text()
        
        if (contentRef.current) {
          // 创建一个临时容器来解析HTML
          const parser = new DOMParser()
          const doc = parser.parseFromString(html, 'text/html')
          
          // 提取body内容
          const body = doc.body || doc.documentElement
          
          // 提取并应用内联样式
          const inlineStyles = doc.querySelectorAll('style')
          inlineStyles.forEach(style => {
            const styleElement = document.createElement('style')
            styleElement.textContent = style.textContent
            // 添加唯一标识，方便后续清理
            styleElement.setAttribute('data-research-page', 'true')
            document.head.appendChild(styleElement)
          })
          
          // 处理外部CSS链接（修复路径）
          const cssLinks = doc.querySelectorAll('link[rel="stylesheet"]')
          cssLinks.forEach(link => {
            const linkElement = document.createElement('link')
            linkElement.rel = 'stylesheet'
            // 修复相对路径
            let href = (link as HTMLLinkElement).href
            if (href.startsWith('./')) {
              href = href.replace('./', '/')
            } else if (!href.startsWith('http') && !href.startsWith('/')) {
              href = '/' + href
            }
            linkElement.href = href
            linkElement.setAttribute('data-research-page', 'true')
            document.head.appendChild(linkElement)
          })
          
          // 设置body内容，并修复内部链接路径
          let bodyHTML = body.innerHTML
          // 修复相对路径的链接和图片
          bodyHTML = bodyHTML.replace(/href="\.\//g, 'href="/')
          bodyHTML = bodyHTML.replace(/src="\.\//g, 'src="/')
          
          contentRef.current.innerHTML = bodyHTML
        }
      } catch (error) {
        console.error('Error loading research content:', error)
        if (contentRef.current) {
          contentRef.current.innerHTML = '<p>Failed to load research content. Please try again later.</p>'
        }
      }
    }

    loadResearchContent()
    
    // 清理函数：移除动态添加的样式
    return () => {
      const researchStyles = document.querySelectorAll('[data-research-page="true"]')
      researchStyles.forEach(style => style.remove())
    }
  }, [])

  return (
    <div className="research-page">
      {/* Navigation */}
      <nav className="research-nav">
        <div className="research-nav-container">
          <button 
            className="research-back-btn"
            onClick={() => navigate('/')}
            title="返回主页"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 19l-7-7 7-7"/>
            </svg>
            <span>Back</span>
          </button>
          <div className="research-nav-title">Research</div>
        </div>
      </nav>

      {/* Content */}
      <main className="research-main">
        <div className="research-content" ref={contentRef}></div>
        
        {/* Source Attribution */}
        <div className="research-source">
          <div className="source-divider"></div>
          <p className="source-text">
            Source: <a 
              href="https://personal.ntu.edu.sg/zhangj/" 
              target="_blank" 
              rel="noopener noreferrer"
              className="source-link"
            >
              Professor Zhang Jie's Homepage
            </a>
          </p>
        </div>
      </main>
    </div>
  )
}

