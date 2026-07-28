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
import { t } from '@apache-superset/core';
import { styled } from '@apache-superset/core/ui';
import { Collapse, Icons } from '@superset-ui/core/components';
import type { TraceStep } from './types';

const StepList = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.sizeUnit}px;
`;

const StepRowWrap = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.sizeUnit * 2}px;
  font-size: ${({ theme }) => theme.fontSizeSM}px;
  color: ${({ theme }) => theme.colorTextSecondary};
`;

const CollapseLabel = styled.span`
  font-size: ${({ theme }) => theme.fontSizeSM}px;
  color: ${({ theme }) => theme.colorTextTertiary};
`;

interface StepRowProps {
  step: TraceStep;
}

// Icon-per-status; label text alone carries the meaning, icons are decorative.
const STATUS_ICONS = {
  running: Icons.LoadingOutlined,
  done: Icons.CheckCircleOutlined,
  error: Icons.CloseCircleOutlined,
};

const StepRow: React.FC<StepRowProps> = ({ step }) => {
  const StatusIcon = STATUS_ICONS[step.status];
  return (
    <StepRowWrap>
      <StatusIcon iconColor="currentColor" />
      <span>{step.label}</span>
    </StepRowWrap>
  );
};

interface TracePanelProps {
  steps: TraceStep[];
}

/** Collapsed-by-default, human-readable trace of the tool calls behind a reply. */
export const TracePanel: React.FC<TracePanelProps> = ({ steps }) => {
  if (!steps.length) return null;
  return (
    <Collapse
      ghost
      size="small"
      expandIconPosition="end"
      items={[
        {
          key: 'trace',
          label: (
            <CollapseLabel>
              {t('Show reasoning (%d steps)', steps.length)}
            </CollapseLabel>
          ),
          children: (
            <StepList>
              {steps.map(step => (
                <StepRow key={step.id} step={step} />
              ))}
            </StepList>
          ),
        },
      ]}
    />
  );
};

export default TracePanel;
