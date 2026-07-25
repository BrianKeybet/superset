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
import { t } from '@apache-superset/core';

export interface PromptContext {
  dashboardId?: string | number;
  chartId?: string | number;
  datasetId?: string | number;
}

/**
 * Return a few starter prompts tailored to what the user is currently viewing.
 * Shown as clickable chips in the empty state to help users get going.
 */
export function getSuggestedPrompts(ctx: PromptContext): string[] {
  if (ctx.chartId != null) {
    return [
      t('Explain this chart'),
      t('What dataset does this chart use?'),
      t('How could I improve this chart?'),
    ];
  }
  if (ctx.dashboardId != null) {
    return [
      t('Summarize this dashboard'),
      t('What charts are on this dashboard?'),
      t('What are the key takeaways?'),
    ];
  }
  if (ctx.datasetId != null) {
    return [
      t('Describe the columns in this dataset'),
      t('Show me a sample of this data'),
      t('Suggest a chart for this dataset'),
    ];
  }
  return [
    t('What dashboards do we have?'),
    t('List the available datasets'),
    t('What can you help me with?'),
  ];
}
