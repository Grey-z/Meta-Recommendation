import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import './HomePage.css'

// Default content data (fallback)
const defaultContent = {
  footer: {
    contactEmail: "ZhangJ@ntu.edu.sg",
    copyright: "© 2025 Collective Intelligence of Singapore. All rights reserved."
  }
}

export function HomePage(): JSX.Element {
  const navigate = useNavigate()
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 })
  const [showDropdown, setShowDropdown] = useState(false)
  const [contentData, setContentData] = useState(defaultContent)

  useEffect(() => {
    // Set page title
    document.title = 'Collective Intelligence of Singapore'
    
    // Update favicon for homepage
    const updateFavicon = (href: string) => {
      let link = document.querySelector("link[rel~='icon']") as HTMLLinkElement
      if (!link) {
        link = document.createElement('link')
        link.rel = 'icon'
        document.getElementsByTagName('head')[0].appendChild(link)
      }
      link.href = href
    }
    updateFavicon('/assets/CISG_logo.png')
    
    const handleMouseMove = (e: MouseEvent) => {
      setMousePosition({ x: e.clientX, y: e.clientY })
    }
    window.addEventListener('mousemove', handleMouseMove)
    
    // Load content.json
    fetch('/content.json')
      .then(res => res.json())
      .then(data => setContentData(data))
      .catch(() => setContentData(defaultContent))
    
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      // Restore original favicon when leaving homepage
      updateFavicon('/assets/MR_orange_round.png')
    }
  }, [])

  const handleMetaRecClick = () => {
    navigate('/MetaRec')
  }

  const { footer } = contentData
  
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
        {/* Singapore background image */}
        <div className="singapore-background" />
      </div>

      {/* Navigation */}
      <nav className="homepage-nav">
        <div className="nav-container">
          <div className="nav-logo">
            <img 
              src="/assets/CISG_logo.png" 
              alt="CISG Logo" 
              className="nav-logo-image"
            />
            <span className="logo-text">Collective Intelligence of Singapore</span>
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
            <button 
              className="nav-item" 
              onClick={() => navigate('/research')}
              style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
            >
              Research
            </button>
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
          <p className="hero-tagline">Intelligent Brain for Embodied Robots</p>
          <p className="hero-description">
            We provide <strong>intelligent brain solutions</strong> for robotics companies, 
            empowering robots with advanced AI capabilities. Our brain system, 
            built on <strong>Vision-Language-Action (VLA) foundation models</strong> and 
            enhanced by <strong>multimodal perception</strong>, significantly improves 
            human-robot interaction across diverse application scenarios.
          </p>
          
          <div className="hero-features">
            <div className="feature-card">
              <div className="feature-icon">🤖</div>
              <div className="feature-content">
                <h3>Robot Brain</h3>
                <p>Intelligent brain for home service robots</p>
              </div>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🧠</div>
              <div className="feature-content">
                <h3>VLA Foundation</h3>
                <p>Vision-Language-Action models with multimodal perception</p>
              </div>
            </div>
            <div className="feature-card">
              <div className="feature-icon">👥</div>
              <div className="feature-content">
                <h3>Human-Robot Interaction</h3>
                <p>Natural interaction enhanced by multimodal understanding</p>
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
            <button 
              className="cta-secondary"
              onClick={() => {
                const aboutSection = document.getElementById('about')
                aboutSection?.scrollIntoView({ behavior: 'smooth' })
              }}
            >
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

      {/* About Section */}
      <section id="about" className="about-section">
        <div className="about-container">
          <div className="about-content">
            <h2 className="section-title">Our Mission</h2>
            <p className="section-description" style={{ marginTop: '16px' }}>
              Our core business is providing <strong>intelligent brain systems</strong> for robots, 
              enabling them to understand, reason, and interact naturally with humans through 
              multimodal perception and advanced AI. While home care for aging populations is 
              one of our key application scenarios, our technology is designed to be adaptable 
              across diverse use cases.
            </p>
            
            <h2 className="section-title" style={{ marginTop: '64px' }}>Core Technology</h2>
            <p className="section-description">
              Our robot brain system is built on <strong>Vision-Language-Action (VLA) foundation models</strong>, 
              enhanced with <strong>multimodal perception capabilities</strong> to significantly improve 
              human-robot interaction. The system processes visual, linguistic, and sensory inputs to 
              understand context and enable natural, intelligent responses.
            </p>
            
            <div className="technology-components">
              <div className="tech-component">
                <div className="tech-icon">🔬</div>
                <h3>VLA Foundation Models</h3>
                <p className="tech-desc">
                  Built on large language models (LLMs) with Vision-Language-Action architecture, 
                  enabling robots to understand, reason, and act in complex home environments.
                </p>
                <ul className="tech-points">
                  <li>Unifies vision, language, audio, and action modalities</li>
                  <li>Learns from human demonstrations and home environments</li>
                  <li>Adapts to unseen tasks with few-shot learning</li>
                </ul>
              </div>
              
              <div className="tech-component">
                <div className="tech-icon">👁️</div>
                <h3>Multimodal Perception</h3>
                <p className="tech-desc">
                  Advanced sensor fusion and perception layer that understands home environments, 
                  detects human states, and interprets gestures, emotions, and context.
                </p>
                <ul className="tech-points">
                  <li>Real-time environment understanding via sensor fusion</li>
                  <li>Human state detection: routines, risks, and needs</li>
                  <li>Context-aware interpretation of gestures and emotions</li>
                </ul>
              </div>
              
              <div className="tech-component">
                <div className="tech-icon">🤝</div>
                <h3>Enhanced Interaction</h3>
                <p className="tech-desc">
                  Intelligent behavior and interaction engine that plans actions with safety 
                  and user preferences, generating natural human-friendly interactions.
                </p>
                <ul className="tech-points">
                  <li>Safety-first action planning with user preferences</li>
                  <li>Natural dialogue generation and conversation</li>
                  <li>Optimized for daily companionship and assistance</li>
                </ul>
              </div>
            </div>

            <h2 className="section-title" style={{ marginTop: '80px' }}>Application Scenarios</h2>
            <p className="section-description">
              Our intelligent brain technology can be applied across various scenarios. 
              One key application area is <strong>aging-in-place support</strong>, where robots 
              provide comprehensive care and assistance for elderly individuals living independently.
            </p>
            
            <div className="use-cases-grid">
              <div className="use-case-card">
                <div className="use-case-icon">🏠</div>
                <h3>Home Care & Assistance</h3>
                <p>Comprehensive elderly care support including daily monitoring, companionship, 
                and assistance with routine activities to enable independent living.</p>
              </div>
              
              <div className="use-case-card">
                <div className="use-case-icon">📅</div>
                <h3>Schedule Management</h3>
                <p>Intelligent scheduling and reminders for medications, appointments, 
                daily routines, and important activities to maintain healthy lifestyles.</p>
              </div>
              
              <div className="use-case-card">
                <div className="use-case-icon">💡</div>
                <h3>Personalized Recommendations</h3>
                <p>Context-aware recommendations for lifestyle choices, health activities, 
                entertainment content, and wellness suggestions tailored to individual needs.</p>
              </div>
              
              <div className="use-case-card">
                <div className="use-case-icon">🚨</div>
                <h3>Emergency Response</h3>
                <p>Real-time monitoring and rapid response to emergencies such as falls, 
                health incidents, or safety hazards with immediate alert and assistance.</p>
              </div>
              
              <div className="use-case-card">
                <div className="use-case-icon">💬</div>
                <h3>Natural Interaction</h3>
                <p>Conversational assistance with speech, gesture recognition, and 
                environment-aware dialogue for intuitive human-robot communication.</p>
              </div>
              
              <div className="use-case-card">
                <div className="use-case-icon">📊</div>
                <h3>Health Monitoring</h3>
                <p>Continuous health and safety monitoring with risk assessment, 
                activity tracking, and proactive health management support.</p>
              </div>
            </div>

            <h2 className="section-title" style={{ marginTop: '80px' }}>Our Vision</h2>
            <p className="section-description" style={{ marginTop: '16px' }}>
              By providing intelligent brain solutions to robotics companies, we enable 
              the next generation of robots with enhanced perception, reasoning, and interaction 
              capabilities. Our technology empowers robots to adapt to diverse scenarios, 
              from home care to industrial applications, making human-robot collaboration 
              more natural and effective.
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="homepage-footer">
        <div className="footer-content">
          <p>Nanyang Technological University, Singapore</p>
          <p className="footer-muted">Led by Professor Zhang Jie</p>
          <p className="footer-contact">
            <a href={`mailto:${footer.contactEmail}`}>{footer.contactEmail}</a>
          </p>
          <p className="footer-copyright">{footer.copyright}</p>
        </div>
      </footer>
    </div>
  )
}

