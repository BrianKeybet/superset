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
import React, { useEffect, useState } from 'react';
import { keyframes } from '@emotion/react';
import { t } from '@apache-superset/core/translation';
import { styled } from '@apache-superset/core/theme';
import { Icons } from '@superset-ui/core/components';
import type { TraceStep } from './types';
import { TracePanel } from './TracePanel';

const bounce = keyframes`
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40% { transform: translateY(-3px); opacity: 1; }
`;

const Wrapper = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.sizeUnit * 2}px;
  color: ${({ theme }) => theme.colorTextTertiary};
  font-size: ${({ theme }) => theme.fontSizeSM}px;
`;

const Avatar = styled.div`
  flex: 0 0 auto;
  width: ${({ theme }) => theme.sizeUnit * 7}px;
  height: ${({ theme }) => theme.sizeUnit * 7}px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: ${({ theme }) => theme.fontSizeLG}px;
  background: ${({ theme }) => theme.colorPrimaryBg};
  color: ${({ theme }) => theme.colorPrimary};
`;

const Dots = styled.div`
  display: inline-flex;
  gap: ${({ theme }) => theme.sizeUnit}px;
  span {
    width: ${({ theme }) => theme.sizeUnit}px;
    height: ${({ theme }) => theme.sizeUnit}px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colorTextTertiary};
    animation: ${bounce} 1.4s infinite ease-in-out both;
  }
  span:nth-of-type(2) {
    animation-delay: 0.2s;
  }
  span:nth-of-type(3) {
    animation-delay: 0.4s;
  }
`;

const StatusText = styled.span`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Column = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.sizeUnit}px;
  min-width: 0;
`;

// Generic filler shown whenever no tool is currently running (before the
// first tool call resolves, or in any gap) — keeps the status line from ever
// going stale even if the backend emits nothing for a while.
const FALLBACK_MESSAGES = [
  t('Thinking…'),
  t('Working on it…'),
  t('Putting it together…'),
  t('One moment…'),
];
const FALLBACK_ROTATE_MS = 2800;

interface TypingIndicatorProps {
  /** Live trace of tool calls for the in-progress turn, if any. */
  steps?: TraceStep[];
}

/** Animated "assistant is typing" indicator shown before the first token. */
export const TypingIndicator: React.FC<TypingIndicatorProps> = ({
  steps = [],
}) => {
  const runningStep = [...steps].reverse().find(s => s.status === 'running');
  const [fallbackIndex, setFallbackIndex] = useState(0);

  // Rotate the generic filler only while there's no backend-driven status to
  // show; the effect re-arms whenever we fall back to it again.
  useEffect(() => {
    if (runningStep) return undefined;
    const interval = setInterval(() => {
      setFallbackIndex(i => (i + 1) % FALLBACK_MESSAGES.length);
    }, FALLBACK_ROTATE_MS);
    return () => clearInterval(interval);
  }, [runningStep]);

  const label = runningStep?.label ?? FALLBACK_MESSAGES[fallbackIndex];

  return (
    <Column>
      <Wrapper
        role="status"
        aria-live="polite"
        aria-label={t('AI is thinking')}
      >
        <Avatar aria-hidden>
          <Icons.RobotOutlined />
        </Avatar>
        <Dots aria-hidden>
          <span />
          <span />
          <span />
        </Dots>
        <StatusText>{label}</StatusText>
      </Wrapper>
      <TracePanel steps={steps} />
    </Column>
  );
};

export default TypingIndicator;
