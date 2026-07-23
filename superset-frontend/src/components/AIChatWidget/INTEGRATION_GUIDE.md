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

/**
 * INTEGRATION GUIDE: Adding AI Chat Widget to Dashboard
 *
 * This file documents how to integrate the AIChatWidget into various parts of Superset.
 */

// ============================================================================
// Method 1: Add Floating Chat Button to Dashboard Page
// ============================================================================
// File: src/dashboard/containers/DashboardPage.tsx
//
// import { AIChatPanel } from 'src/components/AIChatWidget';
//
// export default function Dashboard() {
//   return (
//     <div>
//       {/* Existing dashboard content */}
//       <AIChatPanel floatingButton drawerWidth={420} />
//     </div>
//   );
// }

// ============================================================================
// Method 2: Add Chat Widget to Dashboard Sidebar
// ============================================================================
// File: src/dashboard/v1/components/DashboardHeader.tsx
//
// import { AIChatWidget } from 'src/components/AIChatWidget';
//
// const DashboardHeader = () => {
//   const [showChat, setShowChat] = useState(false);
//
//   return (
//     <div>
//       <Button
//         onClick={() => setShowChat(!showChat)}
//         icon={<BgColorsOutlined />}
//       >
//         AI Assistant
//       </Button>
//       {showChat && (
//         <Drawer open={showChat} onClose={() => setShowChat(false)}>
//           <AIChatWidget onClose={() => setShowChat(false)} />
//         </Drawer>
//       )}
//     </div>
//   );
// };

// ============================================================================
// Method 3: Embed Chat Widget in Explore/SQL Lab
// ============================================================================
// File: src/SqlLab/SqlLab.tsx
//
// import { AIChatWidget } from 'src/components/AIChatWidget';
// import { Row, Col } from 'antd';
//
// const SqlLab = () => {
//   return (
//     <Row gutter={16}>
//       <Col span={16}>
//         {/* SQL Editor */}
//       </Col>
//       <Col span={8}>
//         <AIChatWidget maxMessages={100} />
//       </Col>
//     </Row>
//   );
// };

// ============================================================================
// Method 4: Add to Explorer/Chart Builder
// ============================================================================
// File: src/explore/ExploreViewContainer.tsx
//
// import { AIChatPanel } from 'src/components/AIChatWidget';
//
// export const ExploreViewContainer = () => {
//   return (
//     <div>
//       {/* Chart builder UI */}
//       <AIChatPanel floatingButton />
//     </div>
//   );
// };

// ============================================================================
// Method 5: Custom Hook for Chat Management
// ============================================================================
// File: src/hooks/useAIChat.ts
//
// import { useState, useCallback } from 'react';
// import type { Message } from 'src/components/AIChatWidget';
//
// export const useAIChat = () => {
//   const [messages, setMessages] = useState<Message[]>([]);
//   const [loading, setLoading] = useState(false);
//
//   const sendMessage = useCallback(async (text: string) => {
//     setLoading(true);
//     try {
//       const response = await fetch('/api/v1/ai/chat', {
//         method: 'POST',
//         headers: { 'Content-Type': 'application/json' },
//         body: JSON.stringify({ message: text }),
//       });
//       const data = await response.json();
//       // Handle response...
//     } finally {
//       setLoading(false);
//     }
//   }, []);
//
//   return { messages, loading, sendMessage };
// };

// ============================================================================
// Method 6: Add to Settings/Admin Panel
// ============================================================================
// File: src/pages/Admin/index.tsx
//
// import { AIChatPanel } from 'src/components/AIChatWidget';
// import { Card, Row, Col } from 'antd';
//
// const AdminPage = () => {
//   return (
//     <Row gutter={[16, 16]}>
//       <Col span={18}>
//         {/* Admin settings */}
//       </Col>
//       <Col span={6}>
//         <Card title="AI Assistant">
//           <AIChatWidget apiUrl="/api/v1/ai/chat" />
//         </Card>
//       </Col>
//     </Row>
//   );
// };

// ============================================================================
// Feature Flag Integration
// ============================================================================
// To conditionally show the AI chat widget based on feature flags:
//
// import { isFeatureEnabled, FeatureFlag } from 'src/featureFlags';
// import { AIChatPanel } from 'src/components/AIChatWidget';
//
// export const MyComponent = () => {
//   if (!isFeatureEnabled(FeatureFlag.AI_ASSISTANT)) {
//     return null;
//   }
//   return <AIChatPanel />;
// };

// ============================================================================
// Environment Configuration
// ============================================================================
// Backend configuration (in docker/.env-local or environment):
//
// # Enable AI Assistant
// AI_LLM_PROVIDER=openai  # or 'anthropic'
// OPENAI_API_KEY=sk-...   # Your OpenAI API key
// ANTHROPIC_API_KEY=sk-ant-...  # Your Anthropic API key
// 
// Frontend will automatically detect if backend has AI enabled via
// the /api/v1/ai/health endpoint

// ============================================================================
// Advanced: Custom Message Processing
// ============================================================================
// For custom message handling or integration:
//
// import { AIChatWidget } from 'src/components/AIChatWidget';
// import { useState } from 'react';
//
// const CustomIntegration = () => {
//   const onSendMessage = async (message: string) => {
//     // Custom processing
//     console.log('Processing:', message);
//     // Could integrate with other parts of Superset
//   };
//
//   return <AIChatWidget />;
// };

// ============================================================================
// Performance Considerations
// ============================================================================
// 1. Message History: Keep maxMessages < 100 for optimal performance
// 2. API Throttling: Backend handles rate limiting
// 3. Lazy Loading: Chat widget only loads when needed
// 4. Caching: Consider caching frequent queries
// 5. Session: Each instance gets unique session_id

// ============================================================================
// Troubleshooting
// ============================================================================
// Issue: "Cannot connect to AI API"
// Solution: Check /api/v1/ai/health endpoint. Backend must have LangChain installed.
//
// Issue: "API Key Missing"
// Solution: Set AI_LLM_PROVIDER and corresponding API key in docker/.env-local
//
// Issue: "Styling doesn't match theme"
// Solution: Wrap component in theme provider with Superset theme config
//
// Issue: "Messages not sending"
// Solution: Check CSRF settings - use @csrf.exempt decorator on endpoint

export {};
