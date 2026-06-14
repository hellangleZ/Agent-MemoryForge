'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { useTheme } from '@/lib/theme';
import { clearToken, getMe, getWorkspace, isAuthError } from '@/lib/api';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Bot, User, Sparkles, Loader2, Wrench, RotateCcw } from 'lucide-react';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  status?: 'error';
  toolCalls?: ToolCall[];
}

interface ToolCall {
  name: string;
  status: 'running' | 'completed' | 'error';
}

interface ChatWindowProps {
  agentId?: string;
}

const MODEL_PROVIDER_ERROR =
  'The model provider is not configured for this deployment. Ask an administrator to configure credentials and restart the gateway.';
const SESSION_EXPIRED_MESSAGE = 'Session expired. Sign in again before sending messages.';

function formatChatError(error: unknown): string {
  if (isAuthError(error)) return SESSION_EXPIRED_MESSAGE;
  const raw = error instanceof Error ? error.message : String(error || '');
  if (/OPENAI|AZURE_OPENAI|LLM provider|model provider|provider credentials/i.test(raw)) {
    return MODEL_PROVIDER_ERROR;
  }
  return 'Chat request failed. Check the gateway logs and try again.';
}

// 流式 Chat 解析
async function streamChat(
  body: Record<string, unknown>,
  extraHeaders: Record<string, string> = {},
  onToken?: (text: string) => void,
  onMeta?: (meta: Record<string, unknown>) => void,
  onTool?: (tool: { tool_name: string; event: string }) => void
): Promise<void> {
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';
  const workspaceId = getWorkspace();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extraHeaders,
  };
  if (workspaceId) headers['x-workspace-id'] = workspaceId;

  const resp = await fetch(`${API_BASE}/v1/chat/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    credentials: 'include',
  });

  if (!resp.ok) {
    const txt = await resp.text();
    let json: Record<string, unknown> | null = null;
    try { json = JSON.parse(txt); } catch { json = { raw: txt }; }
    throw new Error(JSON.stringify({ status: resp.status, body: json }));
  }

  const reader = resp.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder('utf-8');
  let buf = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });
    let idx: number;

    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const rawEvent = buf.slice(0, idx);
      buf = buf.slice(idx + 2);

      const lines = rawEvent.split('\n');
      let eventType = 'message';
      let data = '';

      for (const line of lines) {
        if (line.startsWith('event:')) eventType = line.slice(6).trim();
        if (line.startsWith('data:')) data += line.slice(5).trim();
      }

      if (eventType === 'done') return;
      if (!data) continue;

      let payload: Record<string, unknown> | null = null;
      try { payload = JSON.parse(data); } catch { payload = { raw: data }; }

      if (eventType === 'error') {
        const msg = payload?.error || payload?.detail || 'unknown error';
        throw new Error(String(msg));
      }

      if (eventType === 'meta' && onMeta) onMeta(payload || {});
      if (eventType === 'tool' && onTool) onTool(payload as { tool_name: string; event: string });
      if (eventType === 'token' && onToken) {
        const text = (payload as { text?: string })?.text || '';
        onToken(text);
      }
    }
  }
}

export function ChatWindow({ agentId = 'code-assistant' }: ChatWindowProps) {
  const { isDark } = useTheme();
  const showToolTrace = process.env.NEXT_PUBLIC_SHOW_TOOL_TRACE === '1';
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'Hi! How can I help you today?',
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [currentTool, setCurrentTool] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [currentUserId, setCurrentUserId] = useState('');
  const [authReady, setAuthReady] = useState(false);
  const [authMessage, setAuthMessage] = useState<string | null>(null);
  const [isHydrated, setIsHydrated] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pendingMessageRef = useRef<string>('');

  useEffect(() => {
    setIsHydrated(true);
  }, []);

  // 从 localStorage 恢复 conversation_id
  useEffect(() => {
    const key = `portal_conversation_id__${agentId}__${getWorkspace()}`;
    const saved = localStorage.getItem(key);
    if (saved) setConversationId(saved);
  }, [agentId]);

  useEffect(() => {
    let cancelled = false;

    getMe()
      .then((me) => {
        if (cancelled) return;
        setCurrentUserId(me.id || '');
        setAuthMessage(null);
        setAuthReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        if (isAuthError(err)) clearToken();
        setCurrentUserId('');
        setAuthMessage(isAuthError(err) ? SESSION_EXPIRED_MESSAGE : 'Unable to verify session. Refresh or sign in again.');
        setAuthReady(true);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // 保存 conversation_id
  const saveConversationId = useCallback((cid: string) => {
    if (!cid) return;
    const key = `portal_conversation_id__${agentId}__${getWorkspace()}`;
    localStorage.setItem(key, cid);
    setConversationId(cid);
  }, [agentId]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    if (!authReady || !currentUserId) {
      setMessages((prev) => [...prev, {
        id: Date.now().toString(),
        role: 'assistant',
        content: authMessage || 'Checking session. Try again in a moment.',
        timestamp: new Date(),
        status: 'error',
      }]);
      return;
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);
    setThinking(true);
    pendingMessageRef.current = '';

    // 创建一个空的 assistant 消息用于流式更新
    const assistantId = (Date.now() + 1).toString();
    setMessages((prev) => [...prev, {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      toolCalls: [],
    }]);

    try {
      const body = {
        agent: agentId,
        user_id: currentUserId || 'me',
        conversation_id: conversationId || undefined,
        messages: [{ role: 'user', content: userMessage.content }],
      };

      await streamChat(
        body,
        {},
        // onToken
        (text) => {
          pendingMessageRef.current += text;
          setMessages((prev) => prev.map((m) =>
            m.id === assistantId ? { ...m, content: pendingMessageRef.current } : m
          ));
        },
        // onMeta
        (meta) => {
          const cid = meta.conversation_id as string;
          if (cid) saveConversationId(cid);
        },
        // onTool
        (toolEv) => {
          const name = toolEv.tool_name || '';
          const ev = toolEv.event || '';

          if (ev === 'tool.start') {
            setCurrentTool(name);
            setMessages((prev) => prev.map((m) =>
              m.id === assistantId ? {
                ...m,
                toolCalls: [...(m.toolCalls || []), { name, status: 'running' }],
              } : m
            ));
          } else if (ev === 'tool.end') {
            setCurrentTool(null);
            setMessages((prev) => prev.map((m) =>
              m.id === assistantId ? {
                ...m,
                toolCalls: (m.toolCalls || []).map((tc) =>
                  tc.name === name ? { ...tc, status: 'completed' } : tc
                ),
              } : m
            ));
          }
        }
      );

      // 如果没有收到任何内容
      if (!pendingMessageRef.current) {
        setMessages((prev) => prev.map((m) =>
          m.id === assistantId ? { ...m, content: '(No response received)' } : m
        ));
      }
    } catch (error) {
      const msg = formatChatError(error);
      setMessages((prev) => prev.map((m) =>
        m.id === assistantId ? { ...m, content: msg, status: 'error' } : m
      ));
    } finally {
      setLoading(false);
      setThinking(false);
      setCurrentTool(null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleNewChat = () => {
    const key = `portal_conversation_id__${agentId}__${getWorkspace()}`;
    localStorage.removeItem(key);
    setConversationId(null);
    setMessages([{
      id: Date.now().toString(),
      role: 'assistant',
      content: 'New conversation started. How can I help you?',
      timestamp: new Date(),
    }]);
  };

  return (
    <div className="flex flex-col h-[600px]">
      {/* Header */}
      <div className={cn(
        "flex items-center justify-between p-4 border-b transition-colors duration-300",
        isDark ? "border-white/10" : "border-slate-200"
      )}>
        <div className="flex items-center gap-3">
          <div className={cn(
            "w-10 h-10 rounded-md flex items-center justify-center border",
            isDark ? "border-white/10 bg-slate-900 text-white" : "border-slate-200 bg-white text-slate-900 shadow-sm"
          )}>
            <Bot className="w-5 h-5" />
          </div>
          <div>
            <h3 className={cn(
              "font-semibold transition-colors duration-300",
              isDark ? "text-white" : "text-slate-900"
            )}>{agentId}</h3>
            <p className={cn(
              "text-xs transition-colors duration-300",
              isDark ? "text-slate-400" : "text-slate-500"
            )}>
              {conversationId ? `Session: ${conversationId.slice(0, 8)}...` : 'New session'}
            </p>
          </div>
        </div>
        <Badge variant={currentUserId ? 'success' : authReady ? 'warning' : 'info'} dot>
          {currentUserId ? 'Active' : authReady ? 'Sign in required' : 'Checking session'}
        </Badge>
      </div>
      {authMessage && (
        <div className={cn(
          "mx-4 mt-3 rounded-lg border px-3 py-2 text-sm",
          isDark ? "border-white/10 bg-white/5 text-slate-300" : "border-slate-200 bg-slate-50 text-slate-700"
        )}>
          {authMessage}
        </div>
      )}

      {/* Messages */}
      <div className={cn(
        "flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin",
        isDark ? "scrollbar-thumb-white/10" : "scrollbar-thumb-slate-300"
      )}>
        <AnimatePresence>
          {messages.map((message) => (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className={cn(
                'flex gap-3',
                message.role === 'user' ? 'justify-end' : 'justify-start'
              )}
            >
              {message.role === 'assistant' && (
                <div className={cn(
                  "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 border",
                  isDark ? "border-white/10 bg-slate-900 text-white" : "border-slate-200 bg-white text-slate-900"
                )}>
                  <Bot className="w-4 h-4" />
                </div>
              )}
              <div className="flex flex-col max-w-[70%]">
                <div
                  className={cn(
                    'px-4 py-3 rounded-2xl transition-colors duration-300',
                    message.role === 'user'
                      ? isDark
                        ? 'bg-white border border-white text-slate-950 rounded-br-sm'
                        : 'bg-slate-900 border border-slate-900 text-white rounded-br-sm'
                      : message.status === 'error'
                        ? isDark
                          ? 'bg-slate-900 border border-white/20 rounded-bl-sm'
                          : 'bg-slate-50 border border-slate-300 shadow-sm rounded-bl-sm'
                      : isDark
                        ? 'bg-slate-800/80 border border-white/10 rounded-bl-sm'
                        : 'bg-white border border-slate-200 shadow-sm rounded-bl-sm'
                  )}
                >
                  <p className={cn(
                    "text-sm whitespace-pre-wrap transition-colors duration-300",
                    message.role === 'user'
                      ? isDark ? "text-slate-950" : "text-white"
                      : isDark ? "text-white" : "text-slate-900"
                  )}>{message.content}</p>
                  <p className={cn(
                    "text-xs mt-2 transition-colors duration-300",
                    message.role === 'user'
                      ? isDark ? "text-slate-600" : "text-slate-300"
                      : isDark ? "text-slate-500" : "text-slate-400"
                  )}>
                    {isHydrated ? message.timestamp.toLocaleTimeString() : ''}
                  </p>
                </div>
                {showToolTrace && message.toolCalls && message.toolCalls.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {message.toolCalls.map((tc, idx) => (
                      <div
                        key={idx}
                        className={cn(
                          "flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs",
                          isDark ? "bg-slate-800 border border-white/10" : "bg-slate-100 border border-slate-200",
                          tc.status === 'running' && "animate-pulse"
                        )}
                      >
                        <Wrench className={cn(
                          "w-3 h-3",
                          tc.status === 'completed' ? "text-slate-500" : "text-slate-700"
                        )} />
                        <span className={isDark ? "text-slate-300" : "text-slate-600"}>
                          {tc.name}
                        </span>
                        {tc.status === 'completed' && (
                          <span className="text-slate-500">✓</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              {message.role === 'user' && (
                <div className={cn(
                  "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 border",
                  isDark ? "border-white bg-white text-slate-950" : "border-slate-900 bg-slate-900 text-white"
                )}>
                  <User className="w-4 h-4" />
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {thinking && !messages[messages.length - 1]?.content && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex gap-3 justify-start"
          >
            <div className={cn(
              "w-8 h-8 rounded-full border flex items-center justify-center flex-shrink-0",
              isDark ? "border-white/10 bg-slate-900 text-white" : "border-slate-200 bg-white text-slate-900"
            )}>
              <Bot className="w-4 h-4" />
            </div>
            <div className={cn(
              "px-4 py-3 rounded-2xl rounded-bl-sm",
              isDark ? "bg-slate-800/80 border border-white/10" : "bg-white border border-slate-200"
            )}>
              <div className="flex items-center gap-2">
                <Sparkles className={cn(
                  "w-4 h-4 animate-pulse",
                  isDark ? "text-slate-300" : "text-slate-600"
                )} />
                <span className={cn(
                  "text-sm",
                  isDark ? "text-slate-300" : "text-slate-600"
                )}>
                  {showToolTrace && currentTool ? `Using ${currentTool}...` : 'Thinking'}
                </span>
                <span className="flex gap-1">
                  <span className={cn(
                    "w-1.5 h-1.5 rounded-full animate-bounce",
                    isDark ? "bg-slate-300" : "bg-slate-600"
                  )} style={{ animationDelay: '0ms' }} />
                  <span className={cn(
                    "w-1.5 h-1.5 rounded-full animate-bounce",
                    isDark ? "bg-slate-300" : "bg-slate-600"
                  )} style={{ animationDelay: '150ms' }} />
                  <span className={cn(
                    "w-1.5 h-1.5 rounded-full animate-bounce",
                    isDark ? "bg-slate-300" : "bg-slate-600"
                  )} style={{ animationDelay: '300ms' }} />
                </span>
              </div>
            </div>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className={cn(
        "p-4 border-t transition-colors duration-300",
        isDark ? "border-white/10" : "border-slate-200"
      )}>
        <div className="flex gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
            className={cn(
              "flex-1 px-4 py-3 rounded-xl border resize-none transition-all duration-300",
              "focus:outline-none focus:ring-2",
              isDark
                ? "bg-slate-800/50 border-white/10 text-white placeholder:text-slate-500 focus:ring-white/20 focus:border-white/30"
                : "bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:ring-slate-900/10 focus:border-slate-400"
            )}
            rows={2}
            disabled={loading}
          />
          <div className="flex flex-col gap-2 self-end">
            <Button
              aria-label={loading ? 'Message sending' : 'Send message'}
              title={loading ? 'Message sending' : 'Send message'}
              onClick={handleSend}
              disabled={!input.trim() || loading || !authReady || !currentUserId}
            >
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </Button>
            <Button
              aria-label="Start new conversation"
              title="Start new conversation"
              onClick={handleNewChat}
              variant="ghost"
              size="sm"
              disabled={loading}
            >
              <RotateCcw className="w-3 h-3" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
