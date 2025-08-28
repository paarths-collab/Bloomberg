// Summarize the key insights from the current stock chart data using the current context.

'use server';

import {ai} from '@/ai/genkit';
import {z} from 'genkit';

const SummarizeStockDataInputSchema = z.object({
  stockData: z.string().describe('The current stock chart data in JSON format.'),
  context: z.string().describe('Any relevant context about the stock or user query.'),
});
export type SummarizeStockDataInput = z.infer<typeof SummarizeStockDataInputSchema>;

const SummarizeStockDataOutputSchema = z.object({
  summary: z.string().describe('A summary of the key insights from the stock data.'),
});
export type SummarizeStockDataOutput = z.infer<typeof SummarizeStockDataOutputSchema>;

export async function summarizeStockData(input: SummarizeStockDataInput): Promise<SummarizeStockDataOutput> {
  return summarizeStockDataFlow(input);
}

const summarizeStockDataPrompt = ai.definePrompt({
  name: 'summarizeStockDataPrompt',
  input: {schema: SummarizeStockDataInputSchema},
  output: {schema: SummarizeStockDataOutputSchema},
  prompt: `You are an AI assistant that provides summaries of stock chart data.

  Analyze the following stock data and provide a concise summary of the key insights, taking into account any provided context.

  Stock Data:
  {{stockData}}

  Context:
  {{context}}

  Summary:`,
});

const summarizeStockDataFlow = ai.defineFlow(
  {
    name: 'summarizeStockDataFlow',
    inputSchema: SummarizeStockDataInputSchema,
    outputSchema: SummarizeStockDataOutputSchema,
  },
  async input => {
    const {output} = await summarizeStockDataPrompt(input);
    return output!;
  }
);
