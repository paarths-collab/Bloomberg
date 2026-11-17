'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { primaryNavigation, advancedNavigation, navigation } from '@/lib/navigation'

export default function TerminalLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const advanced = advancedNavigation.some(item => item.href === pathname)
  const links = (items: typeof primaryNavigation) => items.map(item => (
    <Link key={item.href} href={item.href}
      aria-current={pathname === item.href ? 'page' : undefined}
      className={`block rounded-lg px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400 ${pathname === item.href ? 'bg-white/10 text-white' : 'text-white/60 hover:bg-white/5 hover:text-white'}`}>
      {item.label}
    </Link>
  ))

  return (
    <div className="min-h-screen bg-black text-white md:flex">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-black focus:p-4">Skip to content</a>
      <aside className="border-b border-white/15 p-4 md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:overflow-y-auto md:border-b-0 md:border-r">
        <Link href="/" className="mb-6 block px-3 text-lg font-semibold">Investing workspace</Link>
        <nav aria-label="Main navigation" className="space-y-1">
          {links(primaryNavigation)}
          <details key={advanced ? 'advanced' : 'primary'} open={advanced || undefined} className="pt-4">
            <summary className="cursor-pointer px-3 py-2 text-sm text-white/60">Advanced tools</summary>
            <div className="mt-2 space-y-1">{links(advancedNavigation)}</div>
          </details>
        </nav>
        <p className="mt-8 px-3 text-xs leading-relaxed text-white/45">Practice portfolios use simulated trades. No money is invested here.</p>
      </aside>
      <main id="main-content" className="min-w-0 flex-1">
        <header className="border-b border-white/15 px-4 py-5 md:px-8">
          <p className="text-sm text-white/60">{navigation.find(item => item.href === pathname)?.label ?? 'Investing workspace'}</p>
        </header>
        <div className="p-4 md:p-8">{children}</div>
      </main>
    </div>
  )
}
