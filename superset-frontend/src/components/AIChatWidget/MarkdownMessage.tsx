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
import { styled } from '@apache-superset/core/ui';
import { SafeMarkdown } from '@superset-ui/core/components';

/**
 * Renders an assistant message as Markdown (GFM: headings, bold, lists, links,
 * tables, code) via the shared, sanitized `SafeMarkdown`. All element styling is
 * scoped here with theme tokens so the output matches Superset and adapts to
 * dark mode. Wide tables and code blocks scroll horizontally within the bubble
 * so they never widen the chat drawer.
 */
const Container = styled.div`
  ${({ theme }) => `
  font-size: ${theme.fontSize}px;
  line-height: ${theme.lineHeight};
  color: ${theme.colorText};
  word-break: break-word;
  overflow-wrap: anywhere;

  /* Collapse outer margins so bubbles stay tight */
  & > *:first-child {
    margin-top: 0;
  }
  & > *:last-child {
    margin-bottom: 0;
  }

  p {
    margin: 0 0 ${theme.sizeUnit * 2}px;
  }

  h1, h2, h3, h4, h5, h6 {
    margin: ${theme.sizeUnit * 3}px 0 ${theme.sizeUnit * 1.5}px;
    font-weight: ${theme.fontWeightStrong};
    line-height: 1.3;
  }
  h1 { font-size: ${theme.fontSizeHeading4}px; }
  h2 { font-size: ${theme.fontSizeHeading5}px; }
  h3, h4, h5, h6 { font-size: ${theme.fontSizeLG}px; }

  ul, ol {
    margin: 0 0 ${theme.sizeUnit * 2}px;
    padding-left: ${theme.sizeUnit * 5}px;
  }
  li {
    margin-bottom: ${theme.sizeUnit * 0.5}px;
  }
  li > p {
    margin: 0;
  }

  a {
    color: ${theme.colorPrimary};
    text-decoration: none;
    &:hover {
      text-decoration: underline;
    }
  }

  strong {
    font-weight: ${theme.fontWeightStrong};
  }

  blockquote {
    margin: 0 0 ${theme.sizeUnit * 2}px;
    padding: ${theme.sizeUnit}px 0 ${theme.sizeUnit}px ${theme.sizeUnit * 3}px;
    border-left: 3px solid ${theme.colorSplit};
    color: ${theme.colorTextSecondary};
  }

  hr {
    border: none;
    border-top: 1px solid ${theme.colorSplit};
    margin: ${theme.sizeUnit * 3}px 0;
  }

  /* Inline code */
  code {
    font-family: ${theme.fontFamilyCode};
    font-size: ${theme.fontSizeSM}px;
    background: ${theme.colorBgLayout};
    border: 1px solid ${theme.colorBorder};
    border-radius: ${theme.borderRadiusSM}px;
    padding: 0 ${theme.sizeUnit}px;
  }

  /* Fenced code blocks */
  pre {
    margin: 0 0 ${theme.sizeUnit * 2}px;
    padding: ${theme.sizeUnit * 2}px;
    background: ${theme.colorBgLayout};
    border: 1px solid ${theme.colorBorder};
    border-radius: ${theme.borderRadius}px;
    overflow-x: auto;
  }
  pre code {
    background: none;
    border: none;
    padding: 0;
    font-size: ${theme.fontSizeSM}px;
    white-space: pre;
  }

  /* Tables — scroll horizontally instead of widening the drawer */
  table {
    display: block;
    width: max-content;
    max-width: 100%;
    overflow-x: auto;
    border-collapse: collapse;
    margin: 0 0 ${theme.sizeUnit * 2}px;
    font-size: ${theme.fontSizeSM}px;
  }
  th, td {
    border: 1px solid ${theme.colorBorder};
    padding: ${theme.sizeUnit}px ${theme.sizeUnit * 2}px;
    text-align: left;
  }
  th {
    background: ${theme.colorBgLayout};
    font-weight: ${theme.fontWeightStrong};
  }
  tr:nth-of-type(even) td {
    background: ${theme.colorBgLayout};
  }

  img {
    max-width: 100%;
  }
  `}
`;

export interface MarkdownMessageProps {
  content: string;
}

export const MarkdownMessage: React.FC<MarkdownMessageProps> = ({
  content,
}) => (
  <Container>
    <SafeMarkdown source={content} />
  </Container>
);

export default MarkdownMessage;
