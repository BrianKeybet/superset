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
import { css, keyframes } from '@emotion/react';
import { styled } from '@apache-superset/core/theme';
import { addAlpha, FeatureFlag, isFeatureEnabled } from '@superset-ui/core';
import { Button, Drawer, Icons } from '@superset-ui/core/components';
import { AIChatWidget } from './AIChatWidget';

const pulse = keyframes`
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.12); }
`;

const FloatingButton = styled(Button)`
  && {
    ${({ theme }) => {
      const ringPulse = keyframes`
        0% { box-shadow: ${theme.boxShadow}, 0 0 0 0 ${addAlpha(theme.colorPrimary, 0.55)}; }
        70% { box-shadow: ${theme.boxShadow}, 0 0 0 16px ${addAlpha(theme.colorPrimary, 0)}; }
        100% { box-shadow: ${theme.boxShadow}, 0 0 0 0 ${addAlpha(theme.colorPrimary, 0)}; }
      `;
      return css`
        position: fixed;
        bottom: ${theme.sizeUnit * 6}px;
        right: ${theme.sizeUnit * 6}px;
        width: ${theme.sizeUnit * 16}px;
        height: ${theme.sizeUnit * 16}px;
        min-width: ${theme.sizeUnit * 16}px;
        border-radius: 50%;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: ${theme.fontSizeXL}px;
        z-index: ${theme.zIndexPopupBase};
        transition: transform ${theme.motionDurationMid};
        animation: ${pulse} 2s ease-in-out infinite, ${ringPulse} 2s ease-out infinite;

        &:hover {
          transform: scale(1.08);
          animation-play-state: paused;
        }
      `;
    }}
  }
`;

interface AIChatPanelProps {
  /**
   * Whether to show as a floating button that opens a drawer
   */
  floatingButton?: boolean;
  /**
   * Width of the drawer when using floating button mode
   */
  drawerWidth?: number;
  /**
   * Current dashboard ID for context
   */
  dashboardId?: string | number;
  /**
   * Current dashboard name, shown in the header instead of the ID
   */
  dashboardTitle?: string;
  /**
   * Current chart ID for context
   */
  chartId?: string | number;
  /**
   * Current dataset ID for context
   */
  datasetId?: string | number;
  /**
   * Callback when chat widget is closed
   */
  onClose?: () => void;
}

/**
 * AIChatPanel - Embeddable AI Chat Widget with optional floating button
 *
 * Usage in dashboard:
 * <AIChatPanel floatingButton />
 *
 * Or embed directly:
 * <AIChatPanel />
 */
export const AIChatPanel: React.FC<AIChatPanelProps> = ({
  floatingButton = true,
  drawerWidth = 400,
  dashboardId,
  dashboardTitle,
  chartId,
  datasetId,
  onClose,
}) => {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth : drawerWidth,
  );

  // Track viewport width so the drawer goes full-width on small screens.
  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Gate the whole widget behind the AI_ASSISTANT feature flag. The backend
  // enforces the same flag (plus auth/RBAC) on /api/v1/ai, so this only hides
  // the UI — it is not the security boundary.
  if (!isFeatureEnabled(FeatureFlag.AiAssistant)) {
    return null;
  }

  const handleClose = () => {
    setDrawerOpen(false);
    onClose?.();
  };

  // Size the drawer to a quarter of the viewport on desktop; go full-width on
  // small screens so the chat stays usable. `drawerWidth` acts as a floor so the
  // panel is never uncomfortably narrow on smaller desktop windows.
  const SMALL_SCREEN_BREAKPOINT = 768;
  const panelWidth =
    viewportWidth < SMALL_SCREEN_BREAKPOINT
      ? viewportWidth
      : Math.max(drawerWidth, Math.round(viewportWidth / 2));

  if (floatingButton) {
    return (
      <>
        <FloatingButton
          buttonStyle="primary"
          shape="circle"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open AI Assistant"
          icon={<Icons.CommentOutlined iconSize="xl" />}
        />
        <Drawer
          // Single header: the widget renders its own header, so suppress the
          // Drawer's built-in title bar + close icon to avoid a duplicate.
          closable={false}
          placement="right"
          onClose={handleClose}
          open={drawerOpen}
          width={panelWidth}
          // Esc + mask click still close (onClose above); keep the widget mounted
          // when closed so the conversation isn't reset on close/reopen.
          styles={{
            body: { padding: 0, display: 'flex', flexDirection: 'column' },
          }}
        >
          <AIChatWidget
            onClose={handleClose}
            open={drawerOpen}
            dashboardId={dashboardId}
            dashboardTitle={dashboardTitle}
            chartId={chartId}
            datasetId={datasetId}
          />
        </Drawer>
      </>
    );
  }

  return (
    <AIChatWidget
      dashboardId={dashboardId}
      dashboardTitle={dashboardTitle}
      chartId={chartId}
      datasetId={datasetId}
      onClose={onClose}
    />
  );
};

export default AIChatPanel;
