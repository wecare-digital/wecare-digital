/**
 * Floating Agent - Internal Admin Task Assistant
 * WECARE.DIGITAL Admin Platform
 * 
 * AI-powered assistant for internal task automation
 * Direct Bedrock AI via API (no FAQ/auto-reply - task-focused only)
 * Voice input supported via Web Speech API
 * 
 * Model: Amazon Nova Lite (~$0.06/1M input tokens)
 * 
 * Note: External (WhatsApp auto-reply) uses separate AI pipeline with KB
 */

import React, { useState, useRef, useEffect } from 'react';
import { useConfirm } from '../contexts/ConfirmContext';
import { useToastContext } from '../contexts/ToastContext';
import { API_BASE } from '../config/constants';
// Configures Amplify before this module's first Auth call; see lib/amplifyConfig.ts.
import '../lib/amplifyConfig';
import { fetchAuthSession } from 'aws-amplify/auth';
import { randomToken } from '../lib/randomToken';
import { scrollToEnd } from '../lib/scroll-to-end';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  status?: 'sending' | 'sent' | 'error';
}

// API Gateway endpoint for AI generate (same as client.ts)
const API_ENDPOINT = `${API_BASE}/ai/generate`;

const MAX_MESSAGES = 80;

// Ids were `Date.now().toString()`, so two messages created in the same millisecond
// collided, and the loading placeholder's `Date.now() + 1` could collide with the next
// real message. A module-scope counter is monotonic and is not render scope, so it is
// also pure from the component's point of view.
let messageSeq = 0;
const nextMessageId = (): string => `m${++messageSeq}-${randomToken(4)}`;

const FloatingAgent: React.FC = () => {
  const confirm = useConfirm();
  const toast = useToastContext();
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'Hi! I\'m your WECARE.DIGITAL task assistant. I can help you:\n\n• Send WhatsApp messages\n• Find and manage contacts\n• Check stats and analytics\n• Execute admin tasks\n\nType or use voice input!',
      timestamp: new Date(),
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  // crypto.getRandomValues, not Math.random. CodeQL flags the latter as
  // `js/insecure-randomness` here and is right to: this id is sent to the agent
  // backend as the conversation key, so a guessable value lets one visitor address
  // another's session. getRandomValues rather than randomUUID because it needs no
  // secure context and keeps the same short id shape.
  const [sessionId] = useState(() => `session-${Date.now()}-${randomToken()}`);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<any>(null);

  const scrollToBottom = () => {
    scrollToEnd(messagesEndRef.current);
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 100) + 'px';
    }
  }, [input]);

  // Keyboard shortcut: Ctrl+. to toggle
  useEffect(() => {
    const handleGlobalKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === '.') {
        e.preventDefault();
        setIsOpen(prev => !prev);
      }
    };
    document.addEventListener('keydown', handleGlobalKey);
    return () => document.removeEventListener('keydown', handleGlobalKey);
  }, []);

  const toggleVoiceInput = () => {
    if (!recognitionRef.current) {
      toast.warning('Voice input is not supported in your browser. Please use Chrome, Edge, or Safari.');
      return;
    }

    if (isListening) {
      try {
        recognitionRef.current.stop();
      } catch (e) {
        console.error('Error stopping recognition:', e);
      }
      setIsListening(false);
    } else {
      try {
        recognitionRef.current.start();
        setIsListening(true);
      } catch (e) {
        console.error('Error starting recognition:', e);
        setIsListening(false);
      }
    }
  };

  /** Strip <thinking>...</thinking> tags from AI responses */
  const cleanResponse = (text: string): string => {
    return text.replace(/<thinking>[\s\S]*?<\/thinking>\s*/gi, '').trim();
  };

  /** Extract the AI response text from any response shape */
  const extractResponse = (data: any): string | null => {
    if (!data) return null;

    let raw: string | null = null;

    // Direct normalized format from proxy
    if (data.suggestedResponse) raw = data.suggestedResponse;
    else if (data.suggestion) raw = data.suggestion;

    // API Gateway wrapped format (fallback if proxy didn't unwrap)
    if (!raw && data.body) {
      try {
        const parsed = typeof data.body === 'string' ? JSON.parse(data.body) : data.body;
        if (parsed.suggestedResponse) raw = parsed.suggestedResponse;
        else if (parsed.suggestion) raw = parsed.suggestion;
        else if (parsed.error) {
          console.error('Backend error in body:', parsed.error);
          return 'Something went wrong on the server. Please try again.';
        }
      } catch {
        // body wasn't parseable
      }
    }

    return raw ? cleanResponse(raw) : null;
  };

  const processCommand = async (text: string): Promise<string> => {
    const lowerText = text.toLowerCase();

    try {
      // Quick local help command only
      if (lowerText === 'help' || lowerText === 'what can you do' || lowerText === 'what can you do?') {
        // Names what it does, not what it runs on. Which model answers is not a
        // decision the operator makes or can act on.
        return 'I\'m your task assistant. I can:\n\n' +
          '- Send WhatsApp/SMS/Email messages\n' +
          '- Send interactive messages (buttons, lists)\n' +
          '- Make voice calls with TTS\n' +
          '- Find and manage contacts\n' +
          '- Schedule messages\n' +
          '- View message history\n' +
          '- Check dashboard stats\n' +
          '- Manage templates\n\n' +
          'Just tell me what you need in natural language.\n' +
          'Example: "send hi message to Jignesh"';
      }

      // Check for dangerous operations and confirm
      const dangerousKeywords = ['delete all', 'clear all', 'remove all', 'delete contact', 'clear data'];
      const isDangerous = dangerousKeywords.some(keyword => lowerText.includes(keyword));

      if (isDangerous) {
        const confirmed = await confirm({
          title: 'Dangerous Operation',
          message: 'This action may delete data and cannot be undone. Are you sure you want to continue?',
          confirmText: 'Continue',
        });
        if (!confirmed) {
          return 'Operation cancelled.';
        }
      }

      setStatusMessage('Understanding your request...');

      // Call AI via API Gateway with auth
      let aiRes: Response;
      try {
        const session = await fetchAuthSession();
        const token = session.tokens?.accessToken?.toString() ?? '';
        aiRes = await fetch(API_ENDPOINT, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
          },
          body: JSON.stringify({
            messageContent: text,
            context: 'internal-admin',
            sessionId: sessionId,
          }),
        });
      } catch (fetchErr: any) {
        setStatusMessage('');
        console.error('Fetch error:', fetchErr);
        return 'Unable to reach the server. Please check your connection and try again.';
      }

      setStatusMessage('Processing...');

      // Parse response — always try to extract JSON
      let data: any;
      try {
        data = await aiRes.json();
      } catch {
        setStatusMessage('');
        return 'Received an invalid response from the server. Please try again.';
      }

      setStatusMessage('');

      // The proxy normalizes to { suggestedResponse, error? }
      // But handle all possible shapes defensively
      const response = extractResponse(data);

      if (response) {
        return response;
      }

      // If we got an error but no response text
      if (data.error) {
        console.error('Backend error:', data.error);
        return 'Something went wrong on the server. Please try again.';
      }

      console.error('Unexpected response format:', JSON.stringify(data).substring(0, 500));
      return 'Received an unexpected response. Please try again.';

    } catch (error: any) {
      console.error('Agent error:', error);
      setStatusMessage('');
      return 'Something went wrong. Please try again.';
    }
  };

  // Declared above the Web Speech API effect below, which calls it on a transcript.
  const handleSendVoice = async (text: string) => {
    if (!text || isLoading) return;

    const userMessage: ChatMessage = {
      id: nextMessageId(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    };

    setMessages(prev => {
      const updated = [...prev, userMessage];
      return updated.length > MAX_MESSAGES ? updated.slice(-MAX_MESSAGES) : updated;
    });
    setInput('');
    setIsLoading(true);

    const loadingId = nextMessageId();
    setMessages(prev => [...prev, {
      id: loadingId,
      role: 'assistant',
      content: '...',
      timestamp: new Date(),
      status: 'sending',
    }]);

    const response = await processCommand(userMessage.content);

    setMessages(prev => prev.map(m => 
      m.id === loadingId ? { ...m, content: response, status: response.startsWith('Something went wrong') || response.startsWith('Unable to reach') ? 'error' : 'sent' } : m
    ));
    setIsLoading(false);
  };

  // Initialize Web Speech API
  useEffect(() => {
    if (typeof window !== 'undefined' && ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
      const SpeechRecognition = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
      recognitionRef.current = new SpeechRecognition();
      recognitionRef.current.continuous = false;
      recognitionRef.current.interimResults = false;
      recognitionRef.current.lang = 'en-US';

      recognitionRef.current.onstart = () => {
        setIsListening(true);
      };

      recognitionRef.current.onresult = (event: any) => {
        const transcript = event.results[0][0].transcript;
        setInput(transcript);
        setIsListening(false);
        // Auto-send voice input
        setTimeout(() => {
          if (transcript.trim()) {
            handleSendVoice(transcript.trim());
          }
        }, 100);
      };

      recognitionRef.current.onerror = (event: any) => {
        console.error('Speech recognition error:', event.error);
        setIsListening(false);
      };

      recognitionRef.current.onend = () => {
        setIsListening(false);
      };
    }

    return () => {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch (e) {
          // Ignore errors on cleanup
        }
      }
    };
  }, []);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      id: nextMessageId(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages(prev => {
      const updated = [...prev, userMessage];
      return updated.length > MAX_MESSAGES ? updated.slice(-MAX_MESSAGES) : updated;
    });
    setInput('');
    setIsLoading(true);

    const loadingId = nextMessageId();
    setMessages(prev => [...prev, {
      id: loadingId,
      role: 'assistant',
      content: '...',
      timestamp: new Date(),
      status: 'sending',
    }]);

    const response = await processCommand(userMessage.content);

    setMessages(prev => prev.map(m => 
      m.id === loadingId ? { ...m, content: response, status: response.startsWith('Something went wrong') || response.startsWith('Unable to reach') ? 'error' : 'sent' } : m
    ));
    setIsLoading(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const LOGO_URL = 'https://wecare.digital/get/o/stream/media/m/wecaredigital.png';

  const retryMessage = async (messageId: string) => {
    // Find the user message before this error message
    const idx = messages.findIndex(m => m.id === messageId);
    if (idx <= 0) return;
    const userMsg = messages[idx - 1];
    if (userMsg.role !== 'user') return;
    
    setIsLoading(true);
    setMessages(prev => prev.map(m => m.id === messageId ? { ...m, content: '...', status: 'sending' } : m));
    const response = await processCommand(userMsg.content);
    setMessages(prev => prev.map(m => m.id === messageId ? { ...m, content: response, status: response.startsWith('Something went wrong') || response.startsWith('Unable to reach') ? 'error' : 'sent' } : m));
    setIsLoading(false);
  };

  const clearChat = () => {
    setMessages([{
      id: Date.now().toString(),
      role: 'assistant',
      content: 'Chat cleared. How can I help you?',
      timestamp: new Date(),
    }]);
  };

  if (!isOpen) {
    return (
      <button className="agent-fab" onClick={() => setIsOpen(true)} title="Open Assistant (Ctrl+.)" aria-label="Open assistant chat">
        <img src={LOGO_URL} alt="" className="agent-fab-logo" />
      </button>
    );
  }

  return (
    <div className="agent-panel">
      <div className="agent-header">
        <div className="agent-header-info">
          <img src={LOGO_URL} alt="WECARE.DIGITAL" className="agent-avatar-logo" />
          <div className="agent-header-text">
            <span className="agent-name">WECARE.DIGITAL</span>
            <span className="agent-subtitle">Task Assistant</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <button
            onClick={clearChat}
            title="Clear chat"
            aria-label="Clear chat history"
            style={{
              background: 'transparent', border: 'none', color: 'rgba(255,255,255,0.7)',
              cursor: 'pointer', padding: '4px', borderRadius: '4px', fontSize: '12px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
          <button className="agent-close" onClick={() => setIsOpen(false)} aria-label="Close assistant">×</button>
        </div>
      </div>

      <div className="agent-messages" aria-live="polite" aria-relevant="additions">
        {messages.map((msg) => (
          <div key={msg.id} className={`agent-message ${msg.role}`}>
            <div className="agent-message-content">
              {msg.content.split('\n').map((line, i) => (
                <React.Fragment key={i}>
                  {line}
                  {i < msg.content.split('\n').length - 1 && <br />}
                </React.Fragment>
              ))}
            </div>
            <div className="agent-message-time" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              {msg.status === 'error' && msg.role === 'assistant' && (
                <button
                  onClick={() => retryMessage(msg.id)}
                  disabled={isLoading}
                  style={{
                    background: 'none', border: 'none', color: '#1a3a2a', cursor: 'pointer',
                    fontSize: '11px', padding: '0 4px', textDecoration: 'underline',
                  }}
                >
                  Retry
                </button>
              )}
            </div>
          </div>
        ))}
        {statusMessage && (
          <div className="agent-status-message" style={{
            padding: '8px 12px',
            margin: '8px',
            background: '#f9fafb',
            border: '1px solid #e5e7eb',
            borderRadius: '8px',
            color: '#1a3a2a',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span className="status-spinner" style={{
              width: '12px',
              height: '12px',
              border: '2px solid #1a3a2a',
              borderTopColor: 'transparent',
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite'
            }} />
            {statusMessage}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="agent-input-area">
        <button
          className="agent-voice-btn"
          onClick={toggleVoiceInput}
          disabled={isLoading}
          aria-label={isListening ? 'Stop voice input' : 'Start voice input'}
          title={isListening ? 'Stop listening' : 'Voice input'}
          style={{
            position: 'absolute',
            left: '20px',
            top: '50%',
            transform: 'translateY(-50%)',
            width: '28px',
            height: '28px',
            border: 'none',
            background: isListening ? '#1a3a2a' : 'transparent',
            color: isListening ? '#fff' : '#1a3a2a',
            borderRadius: '50%',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all 0.2s',
            zIndex: 10,
          }}
        >
          {isListening ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="4" width="4" height="16" rx="1" />
              <rect x="14" y="4" width="4" height="16" rx="1" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </svg>
          )}
        </button>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isListening ? 'Listening...' : 'Type or use voice...'}
          disabled={isLoading}
          rows={1}
          aria-label="Chat message input"
          style={{ paddingLeft: 56, paddingRight: 42 }}
        />
        <button 
          className="agent-send-btn" 
          onClick={handleSend} 
          disabled={!input.trim() || isLoading}
          aria-label="Send message"
        >
          {isLoading ? '·' : <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>}
        </button>
      </div>
    </div>
  );
};

export default FloatingAgent;
