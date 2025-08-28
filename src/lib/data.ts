export interface StockDataPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  prediction: number | null;
}

export function generateStockData(days: number): StockDataPoint[] {
  const data: StockDataPoint[] = [];
  let lastClose = 150;
  const today = new Date();

  for (let i = days - 1; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(today.getDate() - i);
    const dateString = date.toISOString().split('T')[0];

    const open = parseFloat((lastClose * (1 + (Math.random() - 0.5) * 0.02)).toFixed(2));
    const high = parseFloat((Math.max(open, lastClose) * (1 + Math.random() * 0.02)).toFixed(2));
    const low = parseFloat((Math.min(open, lastClose) * (1 - Math.random() * 0.02)).toFixed(2));
    const close = parseFloat((low + Math.random() * (high - low)).toFixed(2));
    const volume = Math.floor(1000000 + Math.random() * 5000000);

    let prediction: number | null = null;
    if (i < 10) { // Only provide predictions for the last 10 days
      prediction = parseFloat((close * (1 + (Math.random() - 0.45) * 0.05)).toFixed(2));
    }

    data.push({
      date: dateString,
      open,
      high,
      low,
      close,
      volume,
      prediction,
    });

    lastClose = close;
  }

  return data;
}

export const stockData = generateStockData(90);
