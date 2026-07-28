/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import React, { useState, useRef, useEffect, useMemo } from 'react';
import { t } from '@apache-superset/core';
import { SupersetClient } from '@superset-ui/core';
import { styled } from '@apache-superset/core/ui';
import {
  Button,
  Dropdown,
  EmptyState,
  Icons,
  Tooltip,
} from '@superset-ui/core/components';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { TypingIndicator } from './TypingIndicator';
import { getSuggestedPrompts } from './suggestedPrompts';
import type { Message, StoredConversation, TraceStep } from './types';
import {
  contextKeyOf,
  contextLabelOf,
  findByContext,
  loadConversations,
  removeConversation,
  saveConversation,
  toMessage,
  uid,
} from './conversationStore';

const ChatWidgetContainer = styled.div`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: ${({ theme }) => theme.colorBgContainer};
  overflow: hidden;
`;

const ChatHeader = styled.div`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: ${theme.sizeUnit * 2}px;
    padding: ${theme.sizeUnit * 2}px ${theme.sizeUnit * 3}px;
    background: ${theme.colorPrimary};
    color: ${theme.colorTextLightSolid};
  `}
`;

const HeaderTitle = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.sizeUnit * 2}px;
  min-width: 0;
  font-size: ${({ theme }) => theme.fontSizeLG}px;
  font-weight: ${({ theme }) => theme.fontWeightStrong};
`;

const ContextChip = styled.span`
  ${({ theme }) => `
    font-size: ${theme.fontSizeSM}px;
    font-weight: ${theme.fontWeightNormal};
    padding: 0 ${theme.sizeUnit * 2}px;
    border-radius: ${theme.borderRadius}px;
    /* deeper primary shade reads as a subtle chip on the brand header */
    background: ${theme.colorPrimaryActive};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: ${theme.sizeUnit * 30}px;
  `}
`;

const HeaderActions = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.sizeUnit}px;
`;

// Header buttons sit on the brand-colored bar, so force light-solid content
// and a subtle hover overlay rather than the default text-button colors.
const HeaderButton = styled(Button)`
  ${({ theme }) => `
    color: ${theme.colorTextLightSolid};
    &:hover,
    &:focus {
      color: ${theme.colorTextLightSolid};
      background: ${theme.colorPrimaryHover};
    }
  `}
`;

const ChatMessages = styled.div`
  ${({ theme }) => `
    position: relative;
    flex: 1;
    overflow-y: auto;
    padding: ${theme.sizeUnit * 4}px;
    display: flex;
    flex-direction: column;
    gap: ${theme.sizeUnit * 4}px;
    background: ${theme.colorBgLayout};

    &::-webkit-scrollbar {
      width: 6px;
    }
    &::-webkit-scrollbar-track {
      background: transparent;
    }
    &::-webkit-scrollbar-thumb {
      background: ${theme.colorBorder};
      border-radius: 3px;
    }
  `}
`;

const EmptyWrap = styled.div`
  margin: auto 0;
  display: flex;
  flex-direction: column;
  align-items: center;
`;

const SuggestionChips = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: ${({ theme }) => theme.sizeUnit * 2}px;
  margin-top: ${({ theme }) => theme.sizeUnit * 2}px;
`;

const JumpToLatest = styled(Button)`
  position: absolute;
  right: ${({ theme }) => theme.sizeUnit * 4}px;
  bottom: ${({ theme }) => theme.sizeUnit * 3}px;
  box-shadow: ${({ theme }) => theme.boxShadow};
`;

const ChatFooter = styled.div`
  padding: ${({ theme }) => theme.sizeUnit * 3}px;
  background: ${({ theme }) => theme.colorBgContainer};
  border-top: 1px solid ${({ theme }) => theme.colorBorder};
`;

interface AIChatWidgetProps {
  apiUrl?: string;
  maxMessages?: number;
  onClose?: () => void;
  /** True when the containing drawer is open; used to focus the input. */
  open?: boolean;
  dashboardId?: string | number;
  /** Dashboard name, shown in the header chip instead of the raw ID */
  dashboardTitle?: string;
  chartId?: string | number;
  datasetId?: string | number;
}

export const AIChatWidget: React.FC<AIChatWidgetProps> = ({
  apiUrl = '/api/v1/ai/chat',
  onClose,
  open,
  dashboardId,
  dashboardTitle,
  chartId,
  datasetId,
}) => {
  const context = useMemo(
    () => ({ dashboardId, chartId, datasetId }),
    [dashboardId, chartId, datasetId],
  );
  const contextKey = contextKeyOf(context);
  const contextLabel = dashboardTitle ?? contextLabelOf(context);
  const hasContext = contextKey !== 'global';

  // Pick the initial conversation once: reuse the stored thread for this view
  // context if one exists, otherwise start a fresh one. Using a ref so this
  // runs on the first render only (localStorage read), avoiding a flash.
  const initRef = useRef<{
    id: string;
    messages: Message[];
    conversationId: string | null;
    sessionId: string;
  }>();
  if (!initRef.current) {
    const existing = findByContext(contextKey);
    initRef.current = existing
      ? {
          id: existing.id,
          messages: existing.messages.map(toMessage),
          conversationId: existing.conversationId,
          sessionId: existing.sessionId,
        }
      : {
          id: uid(),
          messages: [],
          conversationId: null,
          sessionId: `session_${uid()}`,
        };
  }

  const [activeId, setActiveId] = useState(initRef.current.id);
  const [messages, setMessages] = useState<Message[]>(initRef.current.messages);
  const [conversationId, setConversationId] = useState<string | null>(
    initRef.current.conversationId,
  );
  const [sessionId, setSessionId] = useState(initRef.current.sessionId);
  const [conversations, setConversations] =
    useState<StoredConversation[]>(loadConversations);
  const [loading, setLoading] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const [focusToken, setFocusToken] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const dirtyRef = useRef(false);

  // The streaming endpoint is the non-streaming apiUrl with a `/stream` suffix.
  const streamUrl = `${apiUrl}/stream`;

  // Persist the active conversation to localStorage (skips empty threads).
  const persist = () => {
    if (messages.length === 0) return;
    saveConversation({
      id: activeId,
      contextKey,
      contextLabel,
      conversationId,
      sessionId,
      messages,
    });
    setConversations(loadConversations());
  };

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior });
  };

  // Only auto-scroll when the user is already near the bottom, so we don't
  // yank them away while they're reading earlier messages.
  useEffect(() => {
    if (atBottom) scrollToBottom();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAtBottom(distanceFromBottom < 80);
  };

  // Focus the input whenever the drawer opens.
  useEffect(() => {
    if (open) setFocusToken(token => token + 1);
  }, [open]);

  // Abort any in-flight stream if the widget unmounts (e.g. drawer closes).
  useEffect(() => () => abortRef.current?.abort(), []);

  // Persist once each turn finishes (loading -> false), not on every token.
  useEffect(() => {
    if (loading || !dirtyRef.current) return;
    dirtyRef.current = false;
    persist();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  const handleSendMessage = async (text: string) => {
    if (!text.trim() || loading) return;
    dirtyRef.current = true;
    setAtBottom(true);

    const base = Date.now();
    const assistantId = `msg_${base}_ai`;
    const userMessage: Message = {
      id: `msg_${base}_user`,
      role: 'user',
      content: text,
      timestamp: new Date(),
    };
    // Add the user turn and an empty assistant turn that fills in as tokens stream.
    const assistantMessage: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage, assistantMessage]);
    setLoading(true);

    const appendToAssistant = (delta: string) =>
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantId ? { ...m, content: m.content + delta } : m,
        ),
      );
    const upsertStep = (step: TraceStep) =>
      setMessages(prev =>
        prev.map(m => {
          if (m.id !== assistantId) return m;
          const steps = m.steps ?? [];
          const idx = steps.findIndex(s => s.id === step.id);
          const nextSteps =
            idx === -1
              ? [...steps, step]
              : steps.map((s, i) => (i === idx ? step : s));
          return { ...m, steps: nextSteps };
        }),
      );
    const markAssistantError = (errText: string) =>
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantId
            ? { ...m, content: `Error: ${errText}`, isError: true }
            : m,
        ),
      );

    let receivedError: string | null = null;
    let streamedAny = false;

    const handleEvent = (rawEvent: string) => {
      let eventName = 'message';
      const dataLines: string[] = [];
      rawEvent.split('\n').forEach(line => {
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      });
      if (!dataLines.length) return;
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(dataLines.join('\n')) as Record<string, unknown>;
      } catch {
        return;
      }
      if (eventName === 'token') {
        const { delta } = payload;
        if (typeof delta === 'string' && delta) {
          appendToAssistant(delta);
          streamedAny = true;
        }
      } else if (eventName === 'trace_step') {
        const { id, tool, label, status } = payload;
        if (
          typeof id === 'string' &&
          typeof label === 'string' &&
          (status === 'running' || status === 'done' || status === 'error')
        ) {
          upsertStep({
            id,
            tool: typeof tool === 'string' ? tool : '',
            label,
            status,
          });
        }
      } else if (eventName === 'done') {
        const cid = payload.conversation_id;
        if (typeof cid === 'string' && !conversationId) setConversationId(cid);
        const note = payload.verification_note;
        if (typeof note === 'string' && note) appendToAssistant(note);
      } else if (eventName === 'error') {
        const err = payload.error;
        receivedError = typeof err === 'string' ? err : 'Unknown error';
      }
    };

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // Use SupersetClient (adds CSRF token, credentials, and app-root prefix)
      // with parseMethod 'raw' so we get the streaming Response body directly.
      // retries: 0 — never replay a mutating agent request.
      const response = (await SupersetClient.post({
        endpoint: streamUrl,
        jsonPayload: {
          message: text,
          session_id: sessionId,
          conversation_id: conversationId,
          dashboard_id: dashboardId,
          chart_id: chartId,
          dataset_id: datasetId,
        },
        parseMethod: 'raw',
        signal: controller.signal,
        fetchRetryOptions: { retries: 0 },
      })) as Response;

      if (!response.ok || !response.body) {
        throw new Error(`API error: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // Read the SSE byte stream and dispatch complete events (separated by \n\n).
      let streaming = true;
      while (streaming) {
        // eslint-disable-next-line no-await-in-loop
        const { done, value } = await reader.read();
        if (done) {
          streaming = false;
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        let sep = buffer.indexOf('\n\n');
        while (sep !== -1) {
          const rawEvent = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          if (rawEvent.trim()) handleEvent(rawEvent);
          sep = buffer.indexOf('\n\n');
        }
      }
      if (buffer.trim()) handleEvent(buffer);

      if (receivedError) {
        // The error is surfaced in-line as a red error bubble (markAssistantError).
        markAssistantError(receivedError);
      } else if (!streamedAny) {
        appendToAssistant(t('No response received'));
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        // Stream canceled (e.g. Stop pressed / widget closed) — keep whatever
        // streamed so far, or note the stop if nothing had arrived yet.
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId && !m.content
              ? { ...m, content: t('_Generation stopped._') }
              : m,
          ),
        );
      } else {
        const errorText =
          error instanceof Error ? error.message : 'Network error';
        markAssistantError(errorText);
      }
    } finally {
      abortRef.current = null;
      setLoading(false);
    }
  };

  const handleStop = () => abortRef.current?.abort();

  // Reset to a fresh, empty conversation for the current view context.
  const resetToNew = () => {
    abortRef.current?.abort();
    setActiveId(uid());
    setMessages([]);
    setConversationId(null);
    setSessionId(`session_${uid()}`);
  };

  const handleClearChat = () => {
    if (loading) return;
    removeConversation(activeId);
    resetToNew();
    setConversations(loadConversations());
  };

  const startNewChat = () => {
    if (loading) return;
    persist(); // keep the outgoing thread
    resetToNew();
  };

  const switchTo = (conv: StoredConversation) => {
    if (loading || conv.id === activeId) return;
    persist(); // keep the outgoing thread
    abortRef.current?.abort();
    setActiveId(conv.id);
    setMessages(conv.messages.map(toMessage));
    setConversationId(conv.conversationId);
    setSessionId(conv.sessionId);
  };

  const conversationMenuItems = [
    ...conversations.map(c => ({
      key: c.id,
      icon:
        c.id === activeId ? (
          <Icons.CheckOutlined iconSize="s" />
        ) : (
          <Icons.CommentOutlined iconSize="s" />
        ),
      label: `${c.contextLabel} · ${new Date(c.updatedAt).toLocaleString()}`,
      onClick: () => switchTo(c),
    })),
    ...(conversations.length ? [{ type: 'divider' as const }] : []),
    {
      key: '__new__',
      icon: <Icons.PlusOutlined iconSize="s" />,
      label: t('New chat'),
      onClick: startNewChat,
    },
  ];

  const suggestions = getSuggestedPrompts(context);

  return (
    <ChatWidgetContainer>
      <ChatHeader>
        <HeaderTitle>
          <Icons.RobotOutlined iconColor="currentColor" aria-hidden />
          <span>{t('AI Assistant')}</span>
          {hasContext && (
            <ContextChip title={contextLabel}>{contextLabel}</ContextChip>
          )}
        </HeaderTitle>
        <HeaderActions>
          <Dropdown
            menu={{ items: conversationMenuItems }}
            trigger={['click']}
            placement="bottomRight"
            disabled={loading}
          >
            <HeaderButton
              type="text"
              size="small"
              aria-label={t('Conversations')}
              icon={<Icons.HistoryOutlined iconColor="currentColor" />}
            />
          </Dropdown>
          <Tooltip title={t('New chat')}>
            <HeaderButton
              type="text"
              size="small"
              onClick={startNewChat}
              disabled={loading}
              aria-label={t('New chat')}
              icon={<Icons.PlusOutlined iconColor="currentColor" />}
            />
          </Tooltip>
          {messages.length > 0 && (
            <Tooltip title={t('Clear chat history')}>
              <HeaderButton
                type="text"
                size="small"
                onClick={handleClearChat}
                disabled={loading}
                aria-label={t('Clear chat history')}
                icon={<Icons.DeleteOutlined iconColor="currentColor" />}
              />
            </Tooltip>
          )}
          {onClose && (
            <Tooltip title={t('Close')}>
              <HeaderButton
                type="text"
                size="small"
                onClick={onClose}
                aria-label={t('Close AI Assistant')}
                icon={<Icons.CloseOutlined iconColor="currentColor" />}
              />
            </Tooltip>
          )}
        </HeaderActions>
      </ChatHeader>

      <ChatMessages
        ref={listRef}
        onScroll={handleScroll}
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        aria-label={t('Conversation')}
      >
        {messages.length === 0 ? (
          <EmptyWrap>
            <EmptyState
              image="document.svg"
              size="small"
              title={t('Ask the AI Assistant')}
              description={t(
                'I can explore your data, explain charts, and help build dashboards.',
              )}
            />
            <SuggestionChips>
              {suggestions.map(prompt => (
                <Button
                  key={prompt}
                  buttonStyle="secondary"
                  buttonSize="small"
                  onClick={() => handleSendMessage(prompt)}
                >
                  {prompt}
                </Button>
              ))}
            </SuggestionChips>
          </EmptyWrap>
        ) : (
          <>
            {messages.map(msg =>
              msg.role === 'assistant' && !msg.content && loading ? (
                <TypingIndicator key={msg.id} steps={msg.steps} />
              ) : (
                <ChatMessage key={msg.id} message={msg} />
              ),
            )}
            <div ref={messagesEndRef} />
          </>
        )}
        {!atBottom && messages.length > 0 && (
          <JumpToLatest
            shape="circle"
            onClick={() => {
              setAtBottom(true);
              scrollToBottom();
            }}
            aria-label={t('Scroll to latest')}
            icon={<Icons.DownOutlined />}
          />
        )}
      </ChatMessages>

      <ChatFooter>
        <ChatInput
          onSend={handleSendMessage}
          onStop={handleStop}
          loading={loading}
          focusToken={focusToken}
          placeholder={t('Ask me anything about your data...')}
        />
      </ChatFooter>
    </ChatWidgetContainer>
  );
};

export default AIChatWidget;
