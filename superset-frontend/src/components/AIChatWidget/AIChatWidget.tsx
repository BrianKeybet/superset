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
import React, { useState, useRef, useEffect } from 'react';
import { t } from '@apache-superset/core';
import { styled } from '@apache-superset/core/ui';
import { Button, Space, Spin, Empty, message as antMessage } from 'antd';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import type { Message } from './types';

const ChatWidgetContainer = styled.div`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fafafa;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  overflow: hidden;
`;

const ChatHeader = styled.div`
  padding: 12px 16px;
  background: #1890ff;
  color: white;
  font-weight: 600;
  font-size: 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
`;

const ChatMessages = styled.div`
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;

  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-track {
    background: #f0f0f0;
  }
  &::-webkit-scrollbar-thumb {
    background: #bfbfbf;
    border-radius: 3px;
  }
`;

const ChatFooter = styled.div`
  padding: 12px;
  background: white;
  border-top: 1px solid #d9d9d9;
`;

interface AIChatWidgetProps {
  apiUrl?: string;
  maxMessages?: number;
  onClose?: () => void;
  dashboardId?: string | number;
  chartId?: string | number;
}

export const AIChatWidget: React.FC<AIChatWidgetProps> = ({
  apiUrl = '/api/v1/ai/chat',
  maxMessages = 50,
  onClose,
  dashboardId,
  chartId,
}) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => `session_${Date.now()}_${Math.random()}`);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async (text: string) => {
    if (!text.trim()) return;

    // Add user message
    const userMessage: Message = {
      id: `msg_${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    setLoading(true);

    try {
      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          conversation_id: conversationId,
          dashboard_id: dashboardId,
          chart_id: chartId,
        }),
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const data = await response.json();

      // Store conversation ID from first response to maintain history
      if (data.conversation_id && !conversationId) {
        setConversationId(data.conversation_id);
      }

      if (data.success) {
        const aiMessage: Message = {
          id: `msg_${Date.now()}`,
          role: 'assistant',
          content: data.response || 'No response received',
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, aiMessage]);
      } else {
        antMessage.error(data.error || 'Failed to get AI response');
        const errorMessage: Message = {
          id: `msg_${Date.now()}`,
          role: 'assistant',
          content: `Error: ${data.error || 'Unknown error'}`,
          timestamp: new Date(),
          isError: true,
        };
        setMessages(prev => [...prev, errorMessage]);
      }
    } catch (error) {
      const errorText = error instanceof Error ? error.message : 'Network error';
      antMessage.error(errorText);
      const errorMessage: Message = {
        id: `msg_${Date.now()}`,
        role: 'assistant',
        content: `Error: ${errorText}`,
        timestamp: new Date(),
        isError: true,
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  const handleClearChat = () => {
    setMessages([]);
  };

  return (
    <ChatWidgetContainer>
      <ChatHeader>
        <span>{t('AI Assistant')}</span>
        <Space size="small">
          {messages.length > 0 && (
            <Button
              type="text"
              size="small"
              onClick={handleClearChat}
              title={t('Clear chat history')}
              style={{ color: 'white' }}
            >
              🗑️
            </Button>
          )}
          {onClose && (
            <Button
              type="text"
              size="small"
              onClick={onClose}
              title={t('Close')}
              style={{ color: 'white' }}
            >
              ✕
            </Button>
          )}
        </Space>
      </ChatHeader>

      <ChatMessages>
        {messages.length === 0 ? (
          <Empty
            description={t('No messages yet')}
            style={{ marginTop: 'auto', marginBottom: 'auto' }}
          />
        ) : (
          <>
            {messages.map(msg => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
            {loading && (
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <Spin size="small" />
                <span style={{ fontSize: '12px', color: '#666' }}>
                  {t('AI is thinking...')}
                </span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </ChatMessages>

      <ChatFooter>
        <ChatInput
          onSend={handleSendMessage}
          disabled={loading}
          placeholder={t('Ask me anything about your data...')}
        />
      </ChatFooter>
    </ChatWidgetContainer>
  );
};
