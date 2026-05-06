import React from 'react'
import type { Message } from '../utils/types'

export interface ChatBubbleProps {
    message: Message,
    footer?: React.ReactNode
}

export const ChatBubble = ({ 
    message,
    footer 
}: ChatBubbleProps ) => {
    const m = message;

          return (
            <div className="bubble" data-role={m.role} style={{ position: 'relative' }}>
              <div className="who">{m.role === 'user' ? 'You' : 'MetaRec'}</div>
              <div>
                <code>{m.id}</code>
              </div>
              <div className="content">{m.content}</div>
              {footer}
            </div>
          )
}
