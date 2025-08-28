import { cn } from '@/lib/utils';
import { TrendingUp, DollarSign } from 'lucide-react';
import React from 'react';

const StockFlowLogo = ({ className }: { className?: string }) => {
  return (
    <div className={cn('flex items-center gap-2 text-primary', className)}>
      <div className="relative">
        <TrendingUp className="h-8 w-8" />
        <DollarSign className="h-4 w-4 absolute -bottom-1 -right-1" />
      </div>
      <h1 className="text-2xl font-bold text-foreground group-data-[collapsible=icon]:hidden">
        StockFlow
      </h1>
    </div>
  );
};

export default StockFlowLogo;
