# Frontend Overview

> **Original sources:**
> [`REACT_CHAT_WIDGET_SUMMARY.md`](../../../REACT_CHAT_WIDGET_SUMMARY.md) ·
> [`superset-frontend/src/components/AIChatWidget/AIchatReadME.md`](../../../superset-frontend/src/components/AIChatWidget/AIchatReadME.md) ·
> [`superset-frontend/src/components/AIChatWidget/INTEGRATION_GUIDE.md`](../../../superset-frontend/src/components/AIChatWidget/INTEGRATION_GUIDE.md) ·
> [`superset-frontend/src/components/AIChatWidget/MODULE.md`](../../../superset-frontend/src/components/AIChatWidget/MODULE.md)

---

## Directory Layout

```
superset-frontend/src/components/AIChatWidget/
├── index.ts                 Public exports
├── AIChatWidget.tsx         Root widget component (floating button + panel)
├── ChatPanel.tsx            Slide-out chat panel container
├── MessageList.tsx          Scrollable message history
├── MessageInput.tsx         Textarea + send button
├── types.ts                 All TypeScript interfaces
├── hooks/
│   └── useAIChat.ts         Core state + fetch logic
└── __tests__/               Jest + React Testing Library
```

---

## Quick Start
## N:B AIChatWidget or AIChatPanel can be used
### Option 1 — Drop-in anywhere

```tsx
import AIChatWidget from 'src/components/AIChatWidget';

export function MyPage() {
  return (
    <div>
      <AIChatWidget />
    </div>
  );
}
```

### Option 2 — Dashboard-aware context

```tsx
<AIChatWidget
  dashboardId={dashboard.id}
  chartId={selectedChartId}
  position="bottom-right"
/>
```

### Option 3 — Controlled visibility

```tsx
const [open, setOpen] = useState(false);

<AIChatWidget
  isOpen={open}
  onToggle={setOpen}
  initialMessage="How can I help you with this dashboard?"
/>
```

---

## Props Reference (`AIChatWidget`)

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `dashboardId` | `number` | — | Passed as context to the AI backend |
| `chartId` | `number` | — | Passed as context to the AI backend |
| `position` | `'bottom-right' \| 'bottom-left'` | `'bottom-right'` | Widget anchor position |
| `isOpen` | `boolean` | — | Controlled open state |
| `onToggle` | `(open: boolean) => void` | — | Controlled toggle callback |
| `initialMessage` | `string` | — | Pre-filled greeting shown on open |
| `placeholder` | `string` | `'Ask me anything...'` | Input placeholder text |

---

## `useAIChat` Hook

The hook owns all chat state and the `fetch` call to `/api/v1/ai/chat`.

```ts
const {
  messages,        // ChatMessage[]
  isLoading,       // boolean
  error,           // string | null
  sendMessage,     // (text: string) => Promise<void>
  clearHistory,    // () => void
  conversationId,  // string | null  — send back as session_id
} = useAIChat({ dashboardId, chartId });
```

**Request flow:**

1. Appends `{ role: 'user', content: text }` optimistically.
2. `POST /api/v1/ai/chat` with `{ message, session_id, context }`.
3. On success, appends `{ role: 'assistant', content: response }`.
4. Stores `conversationId` for multi-turn continuity.

---

## Building & Testing

```bash
cd superset-frontend

# Run all tests in the widget
npm run test -- src/components/AIChatWidget

# Build production bundle
npm run build

# Development server (hot-reload, port 9000)
npm run dev
```

---

## Theming

The widget respects Ant Design tokens from `@superset-ui/core`. Override via the
parent `ThemeProvider` — no custom CSS should be needed.

---

## Related Files

- [REACT_CHAT_WIDGET_SUMMARY.md](../../../REACT_CHAT_WIDGET_SUMMARY.md) — full
  feature narrative and design decisions.
- [AIChatWidget/INTEGRATION_GUIDE.md](../../../superset-frontend/src/components/AIChatWidget/INTEGRATION_GUIDE.md) — step-by-step integration walkthroughs.
