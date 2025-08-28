'use client';

import React from 'react';
import {
  Download,
  FileImage,
  FileText,
  ChevronRight,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { ThemeToggle } from './theme-toggle';
import { SidebarTrigger } from './ui/sidebar';

type AppHeaderProps = {
  onExportCSV?: () => void;
  onExportSVG?: () => void;
};

const AppHeader = ({ onExportCSV, onExportSVG }: AppHeaderProps) => {
  return (
    <header className="flex h-16 shrink-0 items-center gap-4 border-b bg-background px-4 md:px-6">
      <SidebarTrigger className="hidden lg:flex" />
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>Dashboard</span>
        <ChevronRight className="h-4 w-4" />
        <span className="font-semibold text-foreground">AAPL</span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline">
              <Download className="mr-2 h-4 w-4" />
              Export
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onExportSVG}>
              <FileImage className="mr-2 h-4 w-4" />
              <span>Export as SVG</span>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onExportCSV}>
              <FileText className="mr-2 h-4 w-4" />
              <span>Export as CSV</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled>
              <FileImage className="mr-2 h-4 w-4" />
              <span>Export as PNG</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <ThemeToggle />
      </div>
    </header>
  );
};

export default AppHeader;
