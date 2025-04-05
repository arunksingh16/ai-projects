import { useState, useRef, useEffect } from 'react'

export default function Home() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant', text: string }[]>([])
  const [loading, setLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const handleSend = async () => {
    if (!input.trim()) return

    const userMessage = { role: 'user', text: input }
    setMessages(prev => [...prev, userMessage])
    setLoading(true)
    setInput('')

    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: input }),
    })

    const data = await res.json()
    const assistantMessage = { role: 'assistant', text: data.response }
    setMessages(prev => [...prev, assistantMessage])
    setLoading(false)
  }

  const handleEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSend()
    }
  }

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  return (
    <main style={{
      maxWidth: '700px',
      margin: '0 auto',
      padding: '2rem',
      fontFamily: 'Arial, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      height: '100vh'
    }}>
      <h1 style={{ fontSize: '1.8rem', fontWeight: 700, marginBottom: '1rem', textAlign: 'center' }}>🧠 Ollama Assistant</h1>

      <div style={{
        flex: 1,
        overflowY: 'auto',
        border: '1px solid #ccc',
        borderRadius: '8px',
        padding: '1rem',
        marginBottom: '1rem',
        background: '#fafafa'
      }}>
        {messages.map((m, i) => (
          <div key={i} style={{
            marginBottom: '1rem',
            textAlign: m.role === 'user' ? 'right' : 'left'
          }}>
            <div style={{
              display: 'inline-block',
              backgroundColor: m.role === 'user' ? '#d1e7dd' : '#e2e3e5',
              color: '#000',
              padding: '0.75rem 1rem',
              borderRadius: '16px',
              maxWidth: '80%'
            }}>
              {m.text}
            </div>
          </div>
        ))}
        {loading && <p>🧠 Thinking...</p>}
        <div ref={chatEndRef} />
      </div>

      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleEnter}
          placeholder="Type your question..."
          style={{
            flex: 1,
            padding: '0.75rem',
            fontSize: '1rem',
            borderRadius: '8px',
            border: '1px solid #ccc'
          }}
        />
        <button
          onClick={handleSend}
          style={{
            background: '#0070f3',
            color: '#fff',
            padding: '0.75rem 1rem',
            border: 'none',
            borderRadius: '8px',
            cursor: 'pointer'
          }}
        >
          Send
        </button>
      </div>
    </main>
  )
}
