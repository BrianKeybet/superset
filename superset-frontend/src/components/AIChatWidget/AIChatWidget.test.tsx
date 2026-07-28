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
import { TextEncoder, TextDecoder } from 'util';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  userEvent,
  act,
} from 'spec/helpers/testing-library';
import '@testing-library/jest-dom';
import { SupersetClient } from '@superset-ui/core';
import { AIChatWidget } from './AIChatWidget';

// The widget consumes an SSE byte stream via TextDecoder; jsdom lacks these.
Object.assign(global, { TextEncoder, TextDecoder });

// Render assistant Markdown as plain text so tests don't depend on
// react-markdown's async ESM import; the wrapper is covered by its own concern.
jest.mock('./MarkdownMessage', () => ({
  MarkdownMessage: ({ content }: { content: string }) => <div>{content}</div>,
}));

// The widget streams via SupersetClient.post({ parseMethod: 'raw' }); mock it.
const postMock = jest.fn();
jest.spyOn(SupersetClient, 'post').mockImplementation(postMock);

// Mock scrollIntoView
Element.prototype.scrollIntoView = jest.fn();

const encoder = new TextEncoder();

// Build a mock streaming Response whose body yields the given SSE frames.
const makeStreamResponse = (frames: string[], ok = true) => {
  let i = 0;
  return {
    ok,
    body: {
      getReader: () => ({
        read: () => {
          if (i >= frames.length) {
            return Promise.resolve({ done: true, value: undefined });
          }
          const value = encoder.encode(frames[i]);
          i += 1;
          return Promise.resolve({ done: false, value });
        },
      }),
    },
  };
};

const tokenFrame = (delta: string) =>
  `event: token\ndata: ${JSON.stringify({ delta })}\n\n`;
const doneFrame = (conversationId = 'conv-1') =>
  `event: done\ndata: ${JSON.stringify({ conversation_id: conversationId, verification_note: '' })}\n\n`;
const errorFrame = (error: string) =>
  `event: error\ndata: ${JSON.stringify({ error })}\n\n`;
const traceStepFrame = (
  id: string,
  label: string,
  status: 'running' | 'done' | 'error',
  tool = 'some_tool',
) =>
  `event: trace_step\ndata: ${JSON.stringify({ id, tool, label, status })}\n\n`;

// A streaming Response whose frames are pushed in on demand, so a test can
// assert on state between two SSE events instead of only after the stream ends.
const makeControllableStreamResponse = () => {
  const queue: string[] = [];
  let pendingResolve:
    | ((v: { done: boolean; value?: Uint8Array }) => void)
    | null = null;
  let ended = false;

  const flush = () => {
    if (pendingResolve && queue.length) {
      const resolve = pendingResolve;
      pendingResolve = null;
      resolve({ done: false, value: encoder.encode(queue.shift() as string) });
    } else if (pendingResolve && ended) {
      const resolve = pendingResolve;
      pendingResolve = null;
      resolve({ done: true, value: undefined });
    }
  };

  return {
    response: {
      ok: true,
      body: {
        getReader: () => ({
          read: () =>
            new Promise<{ done: boolean; value?: Uint8Array }>(resolve => {
              pendingResolve = resolve;
              flush();
            }),
        }),
      },
    },
    push: (frame: string) => {
      queue.push(frame);
      flush();
    },
    end: () => {
      ended = true;
      flush();
    },
  };
};

const sendButton = () => screen.getByRole('button', { name: /send message/i });

describe('AIChatWidget', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    postMock.mockReset();
    // The widget persists/loads conversations from localStorage; isolate tests.
    localStorage.clear();
  });

  test('renders the chat widget header', () => {
    render(<AIChatWidget />);
    expect(screen.getByText('AI Assistant')).toBeInTheDocument();
  });

  test('shows the suggested-prompt empty state initially', () => {
    render(<AIChatWidget />);
    expect(screen.getByText(/ask the ai assistant/i)).toBeInTheDocument();
    // Generic (no context) suggestion chip.
    expect(
      screen.getByRole('button', { name: /what dashboards do we have/i }),
    ).toBeInTheDocument();
  });

  test('sends a suggested prompt when its chip is clicked', async () => {
    postMock.mockResolvedValueOnce(
      makeStreamResponse([tokenFrame('Here you go'), doneFrame()]),
    );
    render(<AIChatWidget />);
    fireEvent.click(
      screen.getByRole('button', { name: /what dashboards do we have/i }),
    );
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
  });

  test('sends a message and streams the response', async () => {
    postMock.mockResolvedValueOnce(
      makeStreamResponse([
        tokenFrame('Hello! '),
        tokenFrame('How can I help?'),
        doneFrame(),
      ]),
    );

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);

    await userEvent.type(input, 'Hello AI');
    fireEvent.click(sendButton());

    await waitFor(() => {
      expect(screen.getByText('Hello AI')).toBeInTheDocument();
    });
    // Deltas accumulate into a single assistant message.
    await waitFor(() => {
      expect(screen.getByText('Hello! How can I help?')).toBeInTheDocument();
    });
  });

  test('handles a streamed error event', async () => {
    postMock.mockResolvedValueOnce(
      makeStreamResponse([errorFrame('API Error')]),
    );

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);

    await userEvent.type(input, 'Test message');
    fireEvent.click(sendButton());

    await waitFor(() => {
      expect(screen.getByText(/error: api error/i)).toBeInTheDocument();
    });
  });

  test('clears chat history', async () => {
    postMock.mockResolvedValueOnce(
      makeStreamResponse([tokenFrame('Response'), doneFrame()]),
    );

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);

    await userEvent.type(input, 'Message');
    fireEvent.click(sendButton());

    await waitFor(() => {
      expect(screen.getByText('Message')).toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByRole('button', { name: /clear chat history/i }),
    );

    await waitFor(() => {
      expect(screen.queryByText('Message')).not.toBeInTheDocument();
      expect(screen.getByText(/ask the ai assistant/i)).toBeInTheDocument();
    });
  });

  test('shows a typing indicator and a Stop button while loading', async () => {
    let resolveResponse: (value: unknown) => void = () => {};
    postMock.mockReturnValueOnce(
      new Promise(resolve => {
        resolveResponse = resolve;
      }),
    );

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);

    await userEvent.type(input, 'Message');
    fireEvent.click(sendButton());

    // Loading: typing indicator + Stop button; Send is replaced.
    expect(
      screen.getByRole('button', { name: /stop generating/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/ai is thinking/i)).toBeInTheDocument();

    resolveResponse(makeStreamResponse([tokenFrame('Response'), doneFrame()]));

    await waitFor(() => {
      expect(
        screen.queryByLabelText(/ai is thinking/i),
      ).not.toBeInTheDocument();
    });
  });

  test('shows the running tool label before any token arrives', async () => {
    const stream = makeControllableStreamResponse();
    postMock.mockResolvedValueOnce(stream.response);

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);
    await userEvent.type(input, 'What charts do we have?');
    fireEvent.click(sendButton());

    act(() => {
      stream.push(
        traceStepFrame(
          'call_1',
          'Looking through your charts',
          'running',
          'list_charts',
        ),
      );
    });

    await waitFor(() => {
      expect(
        screen.getByText('Looking through your charts'),
      ).toBeInTheDocument();
    });

    act(() => {
      stream.push(
        traceStepFrame(
          'call_1',
          'Looking through your charts',
          'done',
          'list_charts',
        ),
      );
      stream.push(tokenFrame('Here you go'));
      stream.push(doneFrame());
      stream.end();
    });

    await waitFor(() => {
      expect(screen.getByText('Here you go')).toBeInTheDocument();
    });
  });

  test('renders a collapsed trace panel that expands to show completed steps', async () => {
    postMock.mockResolvedValueOnce(
      makeStreamResponse([
        traceStepFrame(
          'call_1',
          'Looking through your charts',
          'running',
          'list_charts',
        ),
        traceStepFrame(
          'call_1',
          'Looking through your charts',
          'done',
          'list_charts',
        ),
        tokenFrame('Here you go'),
        doneFrame(),
      ]),
    );

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);
    await userEvent.type(input, 'What charts do we have?');
    fireEvent.click(sendButton());

    await waitFor(() => {
      expect(screen.getByText('Here you go')).toBeInTheDocument();
    });

    // Collapsed by default: the step detail isn't in the DOM until expanded.
    expect(
      screen.queryByText('Looking through your charts'),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText(/show reasoning/i));

    await waitFor(() => {
      expect(
        screen.getByText('Looking through your charts'),
      ).toBeInTheDocument();
    });
  });

  test('rotates the fallback status message while no tool is running', async () => {
    jest.useFakeTimers();
    let resolveResponse: (value: unknown) => void = () => {};
    postMock.mockReturnValueOnce(
      new Promise(resolve => {
        resolveResponse = resolve;
      }),
    );

    render(<AIChatWidget />);
    fireEvent.change(screen.getByPlaceholderText(/ask me anything/i), {
      target: { value: 'Hi' },
    });
    fireEvent.click(sendButton());

    const indicator = screen.getByLabelText(/ai is thinking/i);
    const firstText = indicator.textContent;

    act(() => {
      jest.advanceTimersByTime(3000);
    });
    expect(indicator.textContent).not.toBe(firstText);

    resolveResponse(makeStreamResponse([tokenFrame('Done'), doneFrame()]));
    jest.useRealTimers();
  });

  test('calls onClose when the close button is clicked', () => {
    const onClose = jest.fn();
    render(<AIChatWidget onClose={onClose} />);
    fireEvent.click(
      screen.getByRole('button', { name: /close ai assistant/i }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
