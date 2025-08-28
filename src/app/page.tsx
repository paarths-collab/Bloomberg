'use client';

import {
  Banknote,
  LayoutDashboard,
  Settings,
  Wallet,
} from 'lucide-react';
import React from 'react';

import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarFooter,
  SidebarProvider,
  SidebarInset,
} from '@/components/ui/sidebar';
import StockFlowLogo from '@/components/stockflow-logo';
import AppHeader from '@/components/app-header';
import StockChart from '@/components/stock-chart';
import ChatPanel from '@/components/chat-panel';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

export default function Home() {
  const [isSidebarOpen, setIsSidebarOpen] = React.useState(true);

  return (
    <SidebarProvider open={isSidebarOpen} onOpenChange={setIsSidebarOpen}>
      <div className="flex h-screen w-full overflow-hidden">
        <Sidebar>
          <SidebarHeader>
            <StockFlowLogo />
          </SidebarHeader>
          <SidebarContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton tooltip="Dashboard" isActive>
                  <LayoutDashboard />
                  <span>Dashboard</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton tooltip="Portfolio">
                  <Wallet />
                  <span>Portfolio</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton tooltip="Transactions">
                  <Banknote />
                  <span>Transactions</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarContent>
          <SidebarFooter>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <div className="flex items-center gap-3 cursor-pointer p-2 rounded-md hover:bg-sidebar-accent">
                  <Avatar className="h-8 w-8">
                    <AvatarImage src="https://picsum.photos/100" alt="@shadcn" />
                    <AvatarFallback>SF</AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col text-sm group-data-[collapsible=icon]:hidden">
                    <span className="font-semibold text-sidebar-foreground">
                      StockFlow User
                    </span>
                    <span className="text-xs text-sidebar-foreground/70">
                      user@stockflow.com
                    </span>
                  </div>
                </div>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-56" align="end" forceMount>
                <DropdownMenuLabel className="font-normal">
                  <div className="flex flex-col space-y-1">
                    <p className="text-sm font-medium leading-none">
                      StockFlow
                    </p>
                    <p className="text-xs leading-none text-muted-foreground">
                      user@stockflow.com
                    </p>
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem>
                  <Settings className="mr-2 h-4 w-4" />
                  <span>Settings</span>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem>Log out</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarFooter>
        </Sidebar>

        <SidebarInset>
          <div className="grid lg:grid-cols-[1fr_400px] h-full overflow-hidden">
            <div className="flex flex-col h-full overflow-hidden">
              <AppHeader />
              <main className="flex-1 overflow-auto p-4 md:p-6 lg:p-8">
                <StockChart />
              </main>
            </div>
            <aside className="border-l border-border hidden lg:flex flex-col">
              <ChatPanel />
            </aside>
          </div>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}
