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
import React from 'react';
import { keyframes } from '@emotion/react';
import { t } from '@apache-superset/core';
import { styled } from '@apache-superset/core/ui';
import { Icons } from '@superset-ui/core/components';

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

/** Animated "assistant is typing" indicator shown before the first token. */
export const TypingIndicator: React.FC = () => (
  <Wrapper role="status" aria-label={t('AI is thinking')}>
    <Avatar aria-hidden>
      <Icons.RobotOutlined />
    </Avatar>
    <Dots aria-hidden>
      <span />
      <span />
      <span />
    </Dots>
  </Wrapper>
);

export default TypingIndicator;
