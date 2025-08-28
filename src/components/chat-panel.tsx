'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  Bot,
  LoaderCircle,
  Send,
  ThumbsDown,
  ThumbsUp,
  User,
} from 'lucide-react';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { summarizeStockData } from '@/ai/flows/summarize-stock-data';
import { answerStockQuery } from '@/ai/flows/answer-stock-query';
import { stockData } from '@/lib/data';
import ExplainabilityCard from './explainability-card';

interface Message {
  id: string;
  role: 'user' | 'ai' | 'loading';
  content: string;
}

const ChatPanel = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const getInitialSummary = async () => {
      setMessages([{ id: 'init-loading', role: 'loading', content: '' }]);
      try {
        const summary = await summarizeStockData({
          stockData: JSON.stringify(stockData.slice(-30)), // Summarize last 30 days
          context: 'Initial analysis of the AAPL stock chart.',
        });
        setMessages([
          {
            id: 'init-summary',
            role: 'ai',
            content: summary.summary,
          },
        ]);
      } catch (error) {
        setMessages([
          {
            id: 'init-error',
            role: 'ai',
            content: 'Sorry, I was unable to generate a summary for the chart.',
          },
        ]);
      }
    };
    getInitialSummary();
  }, []);

  useEffect(() => {
    if (scrollAreaRef.current) {
      scrollAreaRef.current.scrollTo({
        top: scrollAreaRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
    };
    setMessages((prev) => [
      ...prev,
      userMessage,
      { id: 'loading', role: 'loading', content: '' },
    ]);
    setInput('');

    try {
      const result = await answerStockQuery({
        query: input,
        chartDataSummary: messages.find(m => m.role === 'ai')?.content || 'No summary available.',
      });
      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'ai',
        content: result.answer,
      };
      setMessages((prev) => prev.filter((m) => m.role !== 'loading').concat(aiMessage));
    } catch (error) {
        const errorMessage: Message = {
            id: (Date.now() + 1).toString(),
            role: 'ai',
            content: "I'm having trouble connecting to my brain right now. Please try again later.",
        };
        setMessages((prev) => prev.filter((m) => m.role !== 'loading').concat(errorMessage));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-4">
        <h2 className="text-lg font-semibold">AI Analysis</h2>
        <Bot className="h-6 w-6 text-primary" />
      </header>
      <ScrollArea className="flex-1" ref={scrollAreaRef}>
        <div className="space-y-6 p-4">
          {messages.map((message) => (
            <div
              key={message.id}
              className={cn(
                'flex items-start gap-3',
                message.role === 'user' && 'justify-end'
              )}
            >
              {message.role !== 'user' && (
                <Avatar className="h-8 w-8 shrink-0">
                  <AvatarFallback>
                    <Bot className="h-5 w-5 text-primary" />
                  </AvatarFallback>
                </Avatar>
              )}
              {message.role === 'loading' ? (
                <div className="flex items-center justify-center rounded-lg bg-card p-3">
                  <LoaderCircle className="h-5 w-5 animate-spin text-primary" />
                </div>
              ) : (
                <div
                  className={cn(
                    'max-w-[85%] rounded-lg p-3 text-sm',
                    message.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted'
                  )}
                >
                  <p>{message.content}</p>
                  {message.role === 'ai' && message.id !== 'init-error' && message.id !== 'init-loading' && (
                    <div className="mt-3 flex items-center justify-between">
                       {message.id === 'init-summary' && <ExplainabilityCard />}
                      <div className="flex gap-1 ml-auto">
                        <Button variant="ghost" size="icon" className="h-7 w-7">
                          <ThumbsUp className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7">
                          <ThumbsDown className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {message.role === 'user' && (
                <Avatar className="h-8 w-8 shrink-0">
                  <AvatarFallback>
                    <User className="h-5 w-5" />
                  </AvatarFallback>
                </Avatar>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>
      <footer className="border-t p-4">
        <form onSubmit={handleSubmit} className="relative">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this stock..."
            className="pr-12"
          />
          <Button
            type="submit"
            size="icon"
            className="absolute right-1 top-1/2 -translate-y-1/2 h-8 w-8"
            disabled={!input.trim()}
          >
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </footer>
    </div>
  );
};

export default ChatPanel;
