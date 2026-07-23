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
import React, { useState } from 'react';
import { styled } from '@apache-superset/core/ui';
import { Button, Tooltip, message as antMessage } from 'antd';
import { CopyOutlined, CheckOutlined } from '@ant-design/icons';
import type { Message } from './types';

const MessageBubble = styled.div<{ role: 'user' | 'assistant' }>`
  display: flex;
  align-self: ${props => (props.role === 'user' ? 'flex-end' : 'flex-start')};
  max-width: 80%;
  padding: 10px 12px;
  border-radius: 8px;
  background: ${props => (props.role === 'user' ? '#e6f7ff' : '#f5f5f5')};
  color: ${props => (props.role === 'user' ? '#0050b3' : '#000000')};
  font-size: 13px;
  line-height: 1.5;
  word-wrap: break-word;
  white-space: pre-wrap;
`;

const ErrorBubble = styled(MessageBubble)`
  background: #fff1f0;
  color: #d4380d;
`;

const MessageTime = styled.span`
  font-size: 11px;
  color: #666666;
  opacity: 0.7;
`;

const MessageWrapper = styled.div<{ role: 'user' | 'assistant' }>`
  display: flex;
  gap: 8px;
  align-items: flex-start;
  align-self: ${props => (props.role === 'user' ? 'flex-end' : 'flex-start')};
`;

const MessageContentWrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
`;

const CopyButton = styled(Button)`
  opacity: 1;
  transition: opacity 0.2s ease-in-out;
  padding: 4px 8px;
  height: auto;
  font-size: 12px;
  
  &:hover {
    opacity: 1;
  }
`;

const MessageBubbleWrapper = styled.div`
  display: flex;
  align-items: flex-end;
  gap: 4px;
  
  &:hover button {
    opacity: 1;
  }
`;

interface ChatMessageProps {
  message: Message;
}

export const ChatMessage: React.FC<ChatMessageProps> = ({ message }) => {
  const [copied, setCopied] = useState(false);
  const BubbleComponent = message.isError ? ErrorBubble : MessageBubble;
  const timeStr = message.timestamp.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      antMessage.success('Copied to clipboard');
      
      // Reset icon after 2 seconds
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      antMessage.error('Failed to copy');
    }
  };

  return (
    <MessageWrapper role={message.role}>
      <MessageContentWrapper>
        <MessageBubbleWrapper>
          <BubbleComponent role={message.role}>
            {message.content}
          </BubbleComponent>
          {message.role === 'assistant' && (
            <Tooltip title={copied ? 'Copied!' : 'Copy message'}>
              <CopyButton
                type="text"
                size="small"
                onClick={handleCopy}
                icon={copied ? <CheckOutlined /> : <CopyOutlined />}
              />
            </Tooltip>
          )}
        </MessageBubbleWrapper>
        <MessageTime>{timeStr}</MessageTime>
      </MessageContentWrapper>
    </MessageWrapper>
  );
};
