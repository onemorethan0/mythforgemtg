import { useEffect, useState } from 'react'

export default function HealthIndicator() {
  const [health, setHealth] = useState({ comfyui: 'checking', ollama: 'checking' })
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    // Check health immediately
    const checkHealth = async () => {
      try {
        const res = await fetch('/api/health')
        if (res.ok) {
          const data = await res.json()
          setHealth({ comfyui: data.comfyui, ollama: data.ollama })
        }
      } catch (err) {
        setHealth({ comfyui: 'down', ollama: 'down' })
      }
    }

    checkHealth()

    // Poll every 10 seconds
    const interval = setInterval(checkHealth, 10000)
    return () => clearInterval(interval)
  }, [])

  const getStatusColor = (status) => {
    if (status === 'up') return '#22c55e' // green
    if (status === 'down') return '#ef4444' // red
    return '#a8a29e' // gray
  }

  const getStatusLabel = (status) => {
    if (status === 'up') return '●'
    if (status === 'down') return '●'
    return '○'
  }

  const allUp = health.comfyui === 'up' && health.ollama === 'up'

  return (
    <div style={{
      position: 'fixed',
      bottom: 16,
      right: 16,
      zIndex: 100,
    }}>
      {/* Collapsed view - just show indicator */}
      {!expanded && (
        <button
          onClick={() => setExpanded(true)}
          style={{
            padding: '8px 12px',
            borderRadius: 8,
            border: `2px solid ${allUp ? '#22c55e' : '#ef4444'}`,
            background: '#1c1917',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            color: '#f5f5f4',
            fontSize: 12,
            fontWeight: 600,
            transition: 'all 0.2s',
            hover: 'background: #292524',
          }}
          onMouseEnter={(e) => e.target.style.background = '#292524'}
          onMouseLeave={(e) => e.target.style.background = '#1c1917'}
        >
          <span style={{ color: getStatusColor(health.comfyui === 'up' && health.ollama === 'up' ? 'up' : 'down') }}>
            ●
          </span>
          Status
        </button>
      )}

      {/* Expanded view - show details */}
      {expanded && (
        <div style={{
          background: '#1c1917',
          border: '1px solid #44403c',
          borderRadius: 12,
          padding: 16,
          minWidth: 220,
          boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
        }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#fde047' }}>
              System Health
            </div>
            <button
              onClick={() => setExpanded(false)}
              style={{
                background: 'none',
                border: 'none',
                color: '#78716c',
                cursor: 'pointer',
                fontSize: 16,
                padding: 0,
              }}
            >
              ✕
            </button>
          </div>

          {/* ComfyUI Status */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 10,
            padding: 8,
            background: '#0c0a09',
            borderRadius: 6,
          }}>
            <span style={{
              color: getStatusColor(health.comfyui),
              fontSize: 16,
            }}>
              {getStatusLabel(health.comfyui)}
            </span>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#f5f5f4' }}>
                ComfyUI
              </div>
              <div style={{ fontSize: 10, color: '#78716c' }}>
                {health.comfyui === 'up' ? 'Image generation ready' : 'Offline — restart ComfyUI'}
              </div>
            </div>
          </div>

          {/* Ollama Status */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: 8,
            background: '#0c0a09',
            borderRadius: 6,
          }}>
            <span style={{
              color: getStatusColor(health.ollama),
              fontSize: 16,
            }}>
              {getStatusLabel(health.ollama)}
            </span>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#f5f5f4' }}>
                Ollama
              </div>
              <div style={{ fontSize: 10, color: '#78716c' }}>
                {health.ollama === 'up' ? 'Card theming ready' : 'Offline — restart Ollama'}
              </div>
            </div>
          </div>

          <div style={{
            fontSize: 9,
            color: '#57534e',
            marginTop: 10,
            paddingTop: 10,
            borderTop: '1px solid #292524',
            textAlign: 'center',
          }}>
            Checking every 10s
          </div>
        </div>
      )}
    </div>
  )
}
