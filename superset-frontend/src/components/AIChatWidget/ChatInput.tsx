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
import React, { useState, useRef } from 'react';
import { styled } from '@apache-superset/core/ui';
import { Button, Input } from 'antd';

const InputContainer = styled.div`
  display: flex;
  gap: 8px;
  align-items: flex-end;
`;

const StyledInput = styled(Input.TextArea)`
  resize: none;
  min-height: 36px !important;
  max-height: 120px !important;
  && {
    font-size: 13px;
  }
`;

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  disabled = false,
  placeholder = 'Type your message...',
}) => {
  const [input, setInput] = useState('');
  const [rows, setRows] = useState(1);
  const inputRef = useRef<any>(null);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInput(value);

    // Calculate rows based on line breaks
    const lineCount = value.split('\n').length;
    setRows(Math.min(lineCount, 4));
  };

  const handleSend = () => {
    if (input.trim() && !disabled) {
      onSend(input);
      setInput('');
      setRows(1);
      inputRef.current?.focus();
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Send on Cmd/Ctrl + Enter
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
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
        onKeyPress={handleKeyPress}
        placeholder={placeholder}
        disabled={disabled}
        rows={rows}
        autoFocus
        bordered
        status={disabled ? 'warning' : undefined}
      />
      <Button
        type="primary"
        onClick={handleSend}
        disabled={disabled || !input.trim()}
        title="Send (Ctrl+Enter)"
      >
        ✉️
      </Button>
    </InputContainer>
  );
};
