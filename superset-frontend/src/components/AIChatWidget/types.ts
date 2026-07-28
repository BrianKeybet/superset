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

export type TraceStepStatus = 'running' | 'done' | 'error';

// One MCP tool call surfaced to the user as a human-readable step, for the
// collapsible "reasoning" trace under an assistant message. Carries only a
// label + status — never raw tool args/results.
export interface TraceStep {
  id: string;
  tool: string;
  label: string;
  status: TraceStepStatus;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  isError?: boolean;
  steps?: TraceStep[];
}

export interface ChatResponse {
  success: boolean;
  response?: string;
  error?: string;
  metadata?: Record<string, unknown>;
  conversation_id?: string;
}

// A message as persisted to localStorage (timestamp stored as epoch ms, since
// Date does not survive JSON round-tripping).
export interface PersistedMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  isError?: boolean;
  steps?: TraceStep[];
}

// A conversation persisted to localStorage, keyed by view context so the user
// can keep separate threads per chart/dashboard and switch between them.
export interface StoredConversation {
  id: string; // client-generated local id
  contextKey: string; // e.g. "chart:5", "dashboard:1", "global"
  contextLabel: string; // human label, e.g. "Chart 5"
  conversationId: string | null; // backend conversation id
  sessionId: string;
  messages: PersistedMessage[];
  updatedAt: number; // epoch ms
}
