'use server';

/**
 * @fileOverview Answers questions about stock charts using AI.
 *
 * - answerStockQuery - A function that answers stock-related questions.
 * - AnswerStockQueryInput - The input type for the answerStockQuery function.
 * - AnswerStockQueryOutput - The return type for the answerStockQuery function.
 */

import {ai} from '@/ai/genkit';
import {z} from 'genkit';

const AnswerStockQueryInputSchema = z.object({
  query: z.string().describe('The question about the stock chart.'),
  chartDataSummary: z
    .string()
    .describe('A summary of the data displayed on the stock chart.'),
});
export type AnswerStockQueryInput = z.infer<typeof AnswerStockQueryInputSchema>;

const AnswerStockQueryOutputSchema = z.object({
  answer: z.string().describe('The AI-powered answer to the question.'),
});
export type AnswerStockQueryOutput = z.infer<typeof AnswerStockQueryOutputSchema>;

export async function answerStockQuery(input: AnswerStockQueryInput): Promise<AnswerStockQueryOutput> {
  return answerStockQueryFlow(input);
}

const prompt = ai.definePrompt({
  name: 'answerStockQueryPrompt',
  input: {schema: AnswerStockQueryInputSchema},
  output: {schema: AnswerStockQueryOutputSchema},
  prompt: `You are an AI assistant that answers questions about stock charts.

  Here is a summary of the data displayed on the stock chart:
  {{chartDataSummary}}

  Now, answer the following question:
  {{query}}`,
});

const answerStockQueryFlow = ai.defineFlow(
  {
    name: 'answerStockQueryFlow',
    inputSchema: AnswerStockQueryInputSchema,
    outputSchema: AnswerStockQueryOutputSchema,
  },
  async input => {
    const {output} = await prompt(input);
    return output!;
  }
);
