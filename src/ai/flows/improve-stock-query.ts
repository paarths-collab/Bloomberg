'use server';

/**
 * @fileOverview An AI agent that improves stock queries based on user feedback.
 *
 * - improveStockQuery - A function that handles the stock query improvement process.
 * - ImproveStockQueryInput - The input type for the improveStockQuery function.
 * - ImproveStockQueryOutput - The return type for the improveStockQuery function.
 */

import {ai} from '@/ai/genkit';
import {z} from 'genkit';

const ImproveStockQueryInputSchema = z.object({
  query: z.string().describe('The user query about a stock.'),
  feedback: z.string().describe('The user feedback on the previous answer.'),
  previousAnswer: z.string().describe('The previous answer given to the user.'),
});
export type ImproveStockQueryInput = z.infer<typeof ImproveStockQueryInputSchema>;

const ImproveStockQueryOutputSchema = z.object({
  improvedQuery: z.string().describe('The improved stock query.'),
});
export type ImproveStockQueryOutput = z.infer<typeof ImproveStockQueryOutputSchema>;

export async function improveStockQuery(input: ImproveStockQueryInput): Promise<ImproveStockQueryOutput> {
  return improveStockQueryFlow(input);
}

const prompt = ai.definePrompt({
  name: 'improveStockQueryPrompt',
  input: {schema: ImproveStockQueryInputSchema},
  output: {schema: ImproveStockQueryOutputSchema},
  prompt: `You are an AI assistant that helps improve stock queries based on user feedback.

  Previous Answer: {{{previousAnswer}}}
  User Query: {{{query}}}
  User Feedback: {{{feedback}}}

  Please improve the original query to better address the user's needs based on their feedback.
  Improved Query:`,
});

const improveStockQueryFlow = ai.defineFlow(
  {
    name: 'improveStockQueryFlow',
    inputSchema: ImproveStockQueryInputSchema,
    outputSchema: ImproveStockQueryOutputSchema,
  },
  async input => {
    const {output} = await prompt(input);
    return {
      improvedQuery: output!,
    };
  }
);
