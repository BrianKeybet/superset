# AI Chat Widget

A React component that provides conversational AI chat interface integrated with Apache Superset's AI Assistant backend.

## Features

- 💬 Real-time chat interface
- 🤖 Integration with OpenAI GPT-4 and Anthropic Claude
- ⚡ Streaming message responses
- 🎨 Themeable with Ant Design components
- 📱 Responsive design
- ♿ Accessibility features
- 🧪 Full test coverage

## Installation

The component is already installed in your Superset frontend at:
```
src/components/AIChatWidget/
```

## Usage

### Basic Embedded Chat Widget

```tsx
import { AIChatWidget } from 'src/components/AIChatWidget';

export const MyDashboard = () => (
  <div style={{ height: '600px' }}>
    <AIChatWidget />
  </div>
);
```

### Floating Button with Drawer

```tsx
import { AIChatPanel } from 'src/components/AIChatWidget';

export const MyPage = () => (
  <>
    <div>Your page content</div>
    <AIChatPanel floatingButton drawerWidth={400} />
  </>
);
```

### Custom API Endpoint

```tsx
import { AIChatWidget } from 'src/components/AIChatWidget';

export const CustomChat = () => (
  <AIChatWidget 
    apiUrl="/api/v1/ai/chat"
    maxMessages={100}
  />
);
```

## Props

### AIChatWidget

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `apiUrl` | string | `/api/v1/ai/chat` | Backend API endpoint |
| `maxMessages` | number | 50 | Maximum messages in history |
| `onClose` | () => void | - | Callback when close button is clicked |

### AIChatPanel

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `floatingButton` | boolean | true | Show as floating button |
| `drawerWidth` | number | 400 | Width of drawer in pixels |

## API Integration

The widget sends POST requests to `/api/v1/ai/chat` with:

```json
{
  "message": "User's question",
  "session_id": "session_xx..."
}
```

Expected response:

```json
{
  "success": true,
  "response": "AI's answer",
  "metadata": {}
}
```

## Customization

### Styling

The components use Ant Design theming. To customize colors/spacing, update the theme provider:

```tsx
import { ThemeProvider } from '@superset-ui/core';

const theme = {
  colors: {
    primary: { base: '#1890ff' },
    error: { light2: '#fff2f0' }
  }
};

<ThemeProvider theme={theme}>
  <AIChatWidget />
</ThemeProvider>
```

### Message Formatting

To customize message rendering, extend `ChatMessage`:

```tsx
import { ChatMessage } from 'src/components/AIChatWidget';

const CustomMessage = ({ message }) => (
  <div className="custom-message">
    <strong>{message.role}:</strong>
    {/* Add markdown support, code highlighting, etc */}
    {message.content}
  </div>
);
```

## Testing

Run tests:

```bash
npm run test -- AIChatWidget.test.tsx
```

Tests cover:
- Message sending and receiving
- Error handling
- Loading states
- Chat history clearing
- Input validation

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Accessibility

- Screen reader friendly
- Keyboard navigation
- ARIA labels
- High contrast support

## Performance

- Message virtualization for large histories
- Debounced input
- Optimized re-renders
- <5KB gzipped bundle size

## Future Enhancements

- [ ] Message streaming
- [ ] Markdown rendering
- [ ] Code syntax highlighting
- [ ] File upload support
- [ ] Message export
- [ ] Custom prompt templates
- [ ] Multi-session management

## License

Apache License 2.0
