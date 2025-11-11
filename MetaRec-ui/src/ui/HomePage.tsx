import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import './HomePage.css'

export function HomePage(): JSX.Element {
  const navigate = useNavigate()
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 })
  const [showDropdown, setShowDropdown] = useState(false)

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      setMousePosition({ x: e.clientX, y: e.clientY })
    }
    window.addEventListener('mousemove', handleMouseMove)
    return () => window.removeEventListener('mousemove', handleMouseMove)
  }, [])

  const handleMetaRecClick = () => {
    navigate('/MetaRec')
  }

  return (
    <div className="homepage">
      {/* Animated background gradient */}
      <div className="homepage-background">
        <div 
          className="gradient-orb" 
          style={{
            left: `${mousePosition.x / window.innerWidth * 100}%`,
            top: `${mousePosition.y / window.innerHeight * 100}%`,
          }}
        />
        <div className="gradient-overlay" />
      </div>

      {/* Navigation */}
      <nav className="homepage-nav">
        <div className="nav-container">
          <div className="nav-logo">
            <span className="logo-text">Collective Intelligence</span>
          </div>
          <div className="nav-menu">
            <div 
              className="nav-dropdown"
              onMouseEnter={() => setShowDropdown(true)}
              onMouseLeave={() => setShowDropdown(false)}
            >
              <button className="nav-item">
                Products
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 4.5L6 7.5L9 4.5" />
                </svg>
              </button>
              {showDropdown && (
                <div className="dropdown-menu-home">
                  <button 
                    className="dropdown-item"
                    onClick={handleMetaRecClick}
                  >
                    <div className="dropdown-item-content">
                      <div className="dropdown-item-title">MetaRec</div>
                      <div className="dropdown-item-desc">Multi-modal cross-platform recommendation system</div>
                    </div>
                  </button>
                </div>
              )}
            </div>
            <a href="#about" className="nav-item">About</a>
            <a href="#research" className="nav-item">Research</a>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <main className="homepage-main">
        <div className="hero-content">
          <h1 className="hero-title">
            Collective Intelligence
            <span className="hero-subtitle">Singapore</span>
          </h1>
          <p className="hero-description">
            Led by Professor Zhang Jie from Nanyang Technological University (NTU), 
            we develop cutting-edge multi-modal cross-platform recommendation systems 
            that transform how people discover and interact with content.
          </p>
          
          <div className="hero-features">
            <div className="feature-card">
              <div className="feature-icon">🧠</div>
              <div className="feature-content">
                <h3>AI-Powered</h3>
                <p>Advanced machine learning algorithms</p>
              </div>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🌐</div>
              <div className="feature-content">
                <h3>Cross-Platform</h3>
                <p>Seamless experience across devices</p>
              </div>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🎯</div>
              <div className="feature-content">
                <h3>Multi-Modal</h3>
                <p>Understanding beyond text</p>
              </div>
            </div>
          </div>

          <div className="hero-cta">
            <button 
              className="cta-primary"
              onClick={handleMetaRecClick}
            >
              Try MetaRec
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 3L11 8L6 13" />
              </svg>
            </button>
            <button className="cta-secondary">
              Learn More
            </button>
          </div>
        </div>

        {/* Floating elements for visual interest */}
        <div className="floating-elements">
          <div className="floating-circle circle-1" />
          <div className="floating-circle circle-2" />
          <div className="floating-circle circle-3" />
        </div>
      </main>

      {/* Footer */}
      <footer className="homepage-footer">
        <div className="footer-content">
          <p>Nanyang Technological University</p>
          <p className="footer-muted">Led by Professor Zhang Jie</p>
        </div>
      </footer>
    </div>
  )
}

