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
import { t } from '@apache-superset/core/translation';
import { styled } from '@apache-superset/core/theme';
import { Button, Icons, Input, Tooltip } from '@superset-ui/core/components';

const InputContainer = styled.div`
  display: flex;
  gap: ${({ theme }) => theme.sizeUnit * 2}px;
  align-items: flex-end;
`;

const StyledInput = styled(Input.TextArea)`
  resize: none;
  min-height: ${({ theme }) => theme.controlHeight}px;
  max-height: 120px;
  && {
    font-size: ${({ theme }) => theme.fontSize}px;
    border-radius: ${({ theme }) => theme.borderRadiusLG}px;
  }
`;

interface ChatInputProps {
  onSend: (message: string) => void;
  onStop?: () => void;
  loading?: boolean;
  /** Bump this to programmatically focus the input (e.g. on drawer open). */
  focusToken?: number;
  placeholder?: string;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  onStop,
  loading = false,
  focusToken,
  placeholder = t('Type your message...'),
}) => {
  const [input, setInput] = useState('');
  const [rows, setRows] = useState(1);
  const inputRef = useRef<React.ElementRef<typeof Input.TextArea>>(null);

  useEffect(() => {
    // Focus when the parent signals (drawer opened / conversation switched).
    if (focusToken) inputRef.current?.focus();
  }, [focusToken]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const { value } = e.target;
    setInput(value);
    const lineCount = value.split('\n').length;
    setRows(Math.min(lineCount, 4));
  };

  const handleSend = () => {
    if (input.trim() && !loading) {
      onSend(input);
      setInput('');
      setRows(1);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends the message; Shift+Enter inserts a newline.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <InputContainer>
      <StyledInput
        ref={inputRef}
        value={input}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={rows}
        autoFocus
        aria-label={t('Message')}
      />
      {loading ? (
        <Tooltip title={t('Stop generating')}>
          <Button
            buttonStyle="secondary"
            onClick={onStop}
            aria-label={t('Stop generating')}
            icon={<Icons.CloseOutlined />}
          />
        </Tooltip>
      ) : (
        <Tooltip title={t('Send (Enter · Shift+Enter for newline)')}>
          <Button
            buttonStyle="primary"
            onClick={handleSend}
            disabled={!input.trim()}
            aria-label={t('Send message')}
            icon={<Icons.SendOutlined />}
          />
        </Tooltip>
      )}
    </InputContainer>
  );
};

export default ChatInput;
