'use client';

import * as React from 'react';
import {
  Bar,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
  Brush,
  Area,
} from 'recharts';

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { stockData, type StockDataPoint } from '@/lib/data';
import {
  ChartContainer,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import { Button } from './ui/button';
import { Brush as BrushIcon } from 'lucide-react';

const chartConfig = {
  volume: {
    label: 'Volume',
    color: 'hsl(var(--chart-4))',
  },
  close: {
    label: 'Close Price',
    color: 'hsl(var(--chart-1))',
  },
  prediction: {
    label: 'AI Prediction',
    color: 'hsl(var(--chart-2))',
  },
} satisfies ChartConfig;

export default function StockChart() {
  const chartRef = React.useRef<HTMLDivElement>(null);

  const handleExport = (format: 'csv' | 'svg') => {
    if (format === 'csv') {
      const headers = ['date', 'open', 'high', 'low', 'close', 'volume', 'prediction'];
      const csvContent = [
        headers.join(','),
        ...stockData.map(row => headers.map(header => row[header as keyof StockDataPoint]).join(',')),
      ].join('\n');
      
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement('a');
      const url = URL.createObjectURL(blob);
      link.setAttribute('href', url);
      link.setAttribute('download', 'stockflow_data.csv');
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
    
    if (format === 'svg') {
       if (chartRef.current) {
        const svgElement = chartRef.current.querySelector('svg');
        if (svgElement) {
          const serializer = new XMLSerializer();
          const svgString = serializer.serializeToString(svgElement);
          const blob = new Blob([svgString], { type: 'image/svg+xml' });
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = 'stockflow_chart.svg';
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
        }
      }
    }
  };

  // The AppHeader can't directly call handleExport, so we'll add export buttons here
  // The header buttons are for demonstration. A more robust solution would use context or state lifting.
  
  return (
    <Card>
      <CardHeader>
        <div className="flex justify-between items-start">
            <div>
                <CardTitle>Apple Inc. (AAPL)</CardTitle>
                <CardDescription>
                Showing data for the last 90 days.
                </CardDescription>
            </div>
            <div className="flex gap-2">
                <Button variant="outline" size="icon">
                    <BrushIcon className="h-4 w-4" />
                    <span className="sr-only">Annotate</span>
                </Button>
            </div>
        </div>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="aspect-video h-[500px] w-full" ref={chartRef}>
          <ComposedChart data={stockData}>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              tickFormatter={(value) => {
                const date = new Date(value);
                return date.toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                });
              }}
            />
            <YAxis
              yAxisId="left"
              orientation="left"
              domain={['dataMin - 10', 'dataMax + 10']}
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              tickFormatter={(value) => `$${value}`}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={['0', 'dataMax + 5000000']}
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              tickFormatter={(value) => `${Number(value) / 1000000}M`}
            />
            <Tooltip
              content={
                <ChartTooltipContent
                  nameKey="name"
                  labelFormatter={(value) => new Date(value).toLocaleDateString()}
                />
              }
            />
            <Legend />
            <Bar
              dataKey="volume"
              fill="var(--color-volume)"
              radius={4}
              yAxisId="right"
            />
            <Line
              dataKey="close"
              type="monotone"
              stroke="var(--color-close)"
              strokeWidth={2}
              dot={false}
              yAxisId="left"
            />
            <Line
              dataKey="prediction"
              type="monotone"
              stroke="var(--color-prediction)"
              strokeWidth={2}
              strokeDasharray="3 3"
              dot={false}
              yAxisId="left"
            />
            <Brush dataKey="date" height={30} stroke="hsl(var(--primary))" />
          </ComposedChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
