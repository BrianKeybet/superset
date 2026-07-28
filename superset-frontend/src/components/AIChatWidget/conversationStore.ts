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
import {
  getItem,
  setItem,
  LocalStorageKeys,
} from 'src/utils/localStorageHelpers';
import type { Message, PersistedMessage, StoredConversation } from './types';

// Keep localStorage bounded; drop the least-recently-updated beyond this.
const MAX_CONVERSATIONS = 20;

export interface ChatContext {
  dashboardId?: string | number;
  chartId?: string | number;
  datasetId?: string | number;
}

/** Stable key identifying the view a conversation belongs to. */
export const contextKeyOf = (ctx: ChatContext): string => {
  if (ctx.chartId != null) return `chart:${ctx.chartId}`;
  if (ctx.dashboardId != null) return `dashboard:${ctx.dashboardId}`;
  if (ctx.datasetId != null) return `dataset:${ctx.datasetId}`;
  return 'global';
};

/** Human-readable label for a view context. */
export const contextLabelOf = (ctx: ChatContext): string => {
  if (ctx.chartId != null) return `Chart ${ctx.chartId}`;
  if (ctx.dashboardId != null) return `Dashboard ${ctx.dashboardId}`;
  if (ctx.datasetId != null) return `Dataset ${ctx.datasetId}`;
  return 'General';
};

/** Generate a client-side unique id. */
export const uid = (): string =>
  `${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;

const toPersisted = (m: Message): PersistedMessage => ({
  id: m.id,
  role: m.role,
  content: m.content,
  timestamp: m.timestamp instanceof Date ? m.timestamp.getTime() : Date.now(),
  isError: m.isError,
  steps: m.steps,
});

/** Revive a persisted message (numeric timestamp) into a UI Message (Date). */
export const toMessage = (m: PersistedMessage): Message => ({
  id: m.id,
  role: m.role,
  content: m.content,
  timestamp: new Date(m.timestamp),
  isError: m.isError,
  steps: m.steps,
});

const readMap = (): Record<string, StoredConversation> =>
  getItem(LocalStorageKeys.AiChatConversations, {});

/** All stored conversations, most-recently-updated first. */
export const loadConversations = (): StoredConversation[] =>
  Object.values(readMap()).sort((a, b) => b.updatedAt - a.updatedAt);

/** Most recent conversation for a given context key, if any. */
export const findByContext = (
  contextKey: string,
): StoredConversation | undefined =>
  loadConversations().find(c => c.contextKey === contextKey);

export interface SaveArgs {
  id: string;
  contextKey: string;
  contextLabel: string;
  conversationId: string | null;
  sessionId: string;
  messages: Message[];
}

/** Upsert a conversation, trimming the store to the most-recent N. */
export const saveConversation = (conv: SaveArgs): void => {
  const map = { ...readMap() };
  map[conv.id] = {
    id: conv.id,
    contextKey: conv.contextKey,
    contextLabel: conv.contextLabel,
    conversationId: conv.conversationId,
    sessionId: conv.sessionId,
    messages: conv.messages.map(toPersisted),
    updatedAt: Date.now(),
  };
  const trimmed = Object.values(map)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_CONVERSATIONS);
  const next: Record<string, StoredConversation> = {};
  trimmed.forEach(c => {
    next[c.id] = c;
  });
  setItem(LocalStorageKeys.AiChatConversations, next);
};

export const removeConversation = (id: string): void => {
  const map = { ...readMap() };
  delete map[id];
  setItem(LocalStorageKeys.AiChatConversations, map);
};
