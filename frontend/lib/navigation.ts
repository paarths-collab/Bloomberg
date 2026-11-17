// Shared by the app shell: every entry points to an implemented page.
export const primaryNavigation = [
  { label: 'Home', href: '/' },
  { label: 'Practice portfolio', href: '/portfolio' },
  { label: 'Help', href: '/help' },
]

export const advancedNavigation = [
  { label: 'Market dashboard', href: '/dashboard' },
  { label: 'Markets', href: '/markets' },
  { label: 'Sectors', href: '/sectors' },
  { label: 'Technical analysis', href: '/technical' },
  { label: 'Backtest', href: '/backtest' },
  { label: 'Compare companies', href: '/peers' },
  { label: 'News', href: '/news' },
  { label: 'Research', href: '/research' },
  { label: 'AI chat', href: '/chat' },
]

export const navigation = [...primaryNavigation, ...advancedNavigation]
