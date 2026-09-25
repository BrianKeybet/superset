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
import { t } from '@apache-superset/core/translation';
import { styled } from '@apache-superset/core/theme';
import { Button, Icons, Tooltip } from '@superset-ui/core/components';
import type { Message } from './types';
import { MarkdownMessage } from './MarkdownMessage';
import { TracePanel } from './TracePanel';

const Row = styled.div<{ messageRole: 'user' | 'assistant' }>`
  display: flex;
  flex-direction: ${({ messageRole: role }) =>
    role === 'user' ? 'row-reverse' : 'row'};
  align-items: flex-start;
  gap: ${({ theme }) => theme.sizeUnit * 2}px;

  /* Reveal the copy action on row hover (plain class selector — avoids emotion
     component selectors, which need @emotion/babel-plugin). */
  &:hover .ai-chat-copy {
    opacity: 1;
  }
`;

const Avatar = styled.div<{ messageRole: 'user' | 'assistant' }>`
  flex: 0 0 auto;
  width: ${({ theme }) => theme.sizeUnit * 7}px;
  height: ${({ theme }) => theme.sizeUnit * 7}px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: ${({ theme }) => theme.fontSizeLG}px;
  background: ${({ theme, messageRole: role }) =>
    role === 'user' ? theme.colorPrimary : theme.colorPrimaryBg};
  color: ${({ theme, messageRole: role }) =>
    role === 'user' ? theme.colorTextLightSolid : theme.colorPrimary};
`;

const Column = styled.div<{ messageRole: 'user' | 'assistant' }>`
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 85%;
  gap: ${({ theme }) => theme.sizeUnit}px;
  align-items: ${({ messageRole: role }) =>
    role === 'user' ? 'flex-end' : 'flex-start'};
`;

const Bubble = styled.div<{
  messageRole: 'user' | 'assistant';
  isError?: boolean;
}>`
  ${({ theme, messageRole: role, isError }) => `
    max-width: 100%;
    padding: ${theme.sizeUnit * 2}px ${theme.sizeUnit * 3}px;
    border-radius: ${theme.borderRadiusLG}px;
    font-size: ${theme.fontSize}px;
    line-height: ${theme.lineHeight};
    background: ${
      isError
        ? theme.colorErrorBg
        : role === 'user'
          ? theme.colorPrimary
          : theme.colorBgLayout
    };
    color: ${
      isError
        ? theme.colorError
        : role === 'user'
          ? theme.colorTextLightSolid
          : theme.colorText
    };
    border: 1px solid ${isError ? theme.colorError : 'transparent'};
  `}
`;

const PlainText = styled.div`
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
`;

const Meta = styled.div<{ messageRole: 'user' | 'assistant' }>`
  display: flex;
  flex-direction: ${({ messageRole: role }) =>
    role === 'user' ? 'row-reverse' : 'row'};
  align-items: center;
  gap: ${({ theme }) => theme.sizeUnit}px;
  color: ${({ theme }) => theme.colorTextTertiary};
  font-size: ${({ theme }) => theme.fontSizeSM}px;
`;

// Copy action is revealed on hover/focus to keep the transcript clean.
const CopyButton = styled(Button)`
  opacity: 0;
  transition: opacity ${({ theme }) => theme.motionDurationMid};
  &:focus-visible {
    opacity: 1;
  }
`;

interface ChatMessageProps {
  message: Message;
}

export const ChatMessage: React.FC<ChatMessageProps> = ({ message }) => {
  const [copied, setCopied] = useState(false);
  const { role, isError, content, steps } = message;
  const timeStr = message.timestamp.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      // The check icon + "Copied!" tooltip are the success feedback.
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Failed to copy message to clipboard', err);
    }
  };

  // Assistant replies are Markdown; user input and errors render verbatim.
  const renderMarkdown = role === 'assistant' && !isError;

  return (
    <Row messageRole={role}>
      <Avatar messageRole={role} aria-hidden>
        {role === 'user' ? <Icons.UserOutlined /> : <Icons.RobotOutlined />}
      </Avatar>
      <Column messageRole={role}>
        <Bubble messageRole={role} isError={isError}>
          {renderMarkdown ? (
            <MarkdownMessage content={content} />
          ) : (
            <PlainText>{content}</PlainText>
          )}
        </Bubble>
        {role === 'assistant' && !!steps?.length && (
          <TracePanel steps={steps} />
        )}
        <Meta messageRole={role}>
          <span>{timeStr}</span>
          {role === 'assistant' && !!content && (
            <Tooltip title={copied ? t('Copied!') : t('Copy message')}>
              <CopyButton
                className="ai-chat-copy"
                type="text"
                size="small"
                onClick={handleCopy}
                aria-label={t('Copy message')}
                icon={
                  copied ? (
                    <Icons.CheckOutlined iconSize="s" />
                  ) : (
                    <Icons.CopyOutlined iconSize="s" />
                  )
                }
              />
            </Tooltip>
          )}
        </Meta>
      </Column>
    </Row>
  );
};

export default ChatMessage;
