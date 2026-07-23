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
import { Button, Drawer } from 'antd';
import { AIChatWidget } from './AIChatWidget';

const FloatingButton = styled(Button)`
  position: fixed;
  bottom: 24px;
  right: 24px;
  border-radius: 50%;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  
  &:hover {
    transform: scale(1.1);
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
   * Current chart ID for context
   */
  chartId?: string | number;
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
  chartId,
  onClose,
}) => {
  const [drawerOpen, setDrawerOpen] = useState(false);

  const handleClose = () => {
    setDrawerOpen(false);
    onClose?.();
  };

  if (floatingButton) {
    return (
      <>
        <FloatingButton
          type="primary"
          size="large"
          onClick={() => setDrawerOpen(true)}
          title="Open AI Assistant"
        >
          💬
        </FloatingButton>
        <Drawer
          title="AI Assistant"
          placement="right"
          onClose={handleClose}
          open={drawerOpen}
          width={drawerWidth}
          destroyOnClose
          bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}
          contentWrapperStyle={{ display: 'flex' }}
          style={{ display: 'flex' }}
        >
          <AIChatWidget 
            onClose={handleClose}
            dashboardId={dashboardId}
            chartId={chartId}
          />
        </Drawer>
      </>
    );
  }

  return (
    <AIChatWidget 
      dashboardId={dashboardId}
      chartId={chartId}
      onClose={onClose}
    />
  );
};

export default AIChatPanel;
