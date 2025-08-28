import { config } from 'dotenv';
config();

import '@/ai/flows/answer-stock-query.ts';
import '@/ai/flows/summarize-stock-data.ts';
import '@/ai/flows/improve-stock-query.ts';