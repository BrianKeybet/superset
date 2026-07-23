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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { AIChatWidget } from './AIChatWidget';

// Mock fetch
global.fetch = jest.fn();

// Mock scrollIntoView
Element.prototype.scrollIntoView = jest.fn();

describe('AIChatWidget', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockClear();
  });

  it('should render the chat widget', () => {
    render(<AIChatWidget />);
    expect(screen.getByText('AI Assistant')).toBeInTheDocument();
  });

  it('should display empty state initially', () => {
    render(<AIChatWidget />);
    expect(screen.getByText(/no messages yet/i)).toBeInTheDocument();
  });

  it('should send a message and display it', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        response: 'Hello! How can I help?',
      }),
    });

    const { container } = render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);
    const sendButton = screen.getByTitle(/send/i);

    await userEvent.type(input, 'Hello AI');
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText('Hello AI')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText('Hello! How can I help?')).toBeInTheDocument();
    });
  });

  it('should handle API errors', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: false,
        error: 'API Error',
      }),
    });

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);
    const sendButton = screen.getByTitle(/send/i);

    await userEvent.type(input, 'Test message');
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText(/error: api error/i)).toBeInTheDocument();
    });
  });

  it('should clear chat history', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        response: 'Response',
      }),
    });

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);
    const sendButton = screen.getByTitle(/send/i);

    await userEvent.type(input, 'Message');
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText('Message')).toBeInTheDocument();
    });

    const clearButton = screen.getByTitle(/clear chat history/i);
    fireEvent.click(clearButton);

    await waitFor(() => {
      expect(screen.queryByText('Message')).not.toBeInTheDocument();
      expect(screen.getByText(/no messages yet/i)).toBeInTheDocument();
    });
  });

  it('should disable input while loading', async () => {
    let resolveResponse: any;
    (global.fetch as jest.Mock).mockReturnValueOnce(
      new Promise(resolve => {
        resolveResponse = resolve;
      }),
    );

    render(<AIChatWidget />);
    const input = screen.getByPlaceholderText(/ask me anything/i);
    const sendButton = screen.getByTitle(/send/i);

    await userEvent.type(input, 'Message');
    fireEvent.click(sendButton);

    // Verify loading state
    expect(screen.getByText(/ai is thinking/i)).toBeInTheDocument();
    expect(sendButton).toBeDisabled();

    // Resolve the response
    resolveResponse({
      ok: true,
      json: async () => ({
        success: true,
        response: 'Response',
      }),
    });

    await waitFor(() => {
      expect(screen.queryByText(/ai is thinking/i)).not.toBeInTheDocument();
    });
  });
});
