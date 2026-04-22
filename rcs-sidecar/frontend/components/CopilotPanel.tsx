import { useState } from 'react'

export default function CopilotPanel() {
  const [brief, setBrief] = useState('')
  const [chat, setChat] = useState<{role: string, content: string}[]>([])
  
  const handleStart = async () => {
    // mock starting
    setChat([{role: 'assistant', content: 'What is the main goal?'}])
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 text-white p-4">
      {chat.length === 0 ? (
        <div>
          <textarea value={brief} onChange={e => setBrief(e.target.value)} className="w-full text-black p-2"/>
          <button onClick={handleStart} className="bg-indigo-600 px-4 py-2 mt-2 rounded">Start Copilot</button>
        </div>
      ) : (
        <div className="flex-1 overflow-auto space-y-4">
          {chat.map((msg, i) => <div key={i} className={msg.role === 'user' ? 'text-right text-blue-400' : 'text-left text-green-400'}>{msg.content}</div>)}
        </div>
      )}
    </div>
  )
}
