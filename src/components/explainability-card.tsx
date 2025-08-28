import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';

const ExplainabilityCard = () => {
  const factors = [
    { name: 'Market Sentiment', influence: 0.5, direction: 'positive' },
    { name: 'Volatility Index', influence: -0.2, direction: 'negative' },
    { name: 'News Coverage', influence: 0.3, direction: 'positive' },
    { name: 'Moving Average', influence: 0.15, direction: 'positive' },
  ];

  return (
    <div className="mt-2 text-xs">
      <p className="font-semibold text-muted-foreground mb-2">Key Prediction Factors:</p>
      <div className="flex flex-wrap gap-2">
        {factors.map((factor) => (
          <Badge
            key={factor.name}
            variant={factor.direction === 'positive' ? 'default' : 'destructive'}
            className="flex gap-1.5"
          >
            <span>{factor.name}</span>
            <span className="font-mono">{factor.influence > 0 ? `+${factor.influence}` : factor.influence}</span>
          </Badge>
        ))}
      </div>
    </div>
  );
};

export default ExplainabilityCard;
