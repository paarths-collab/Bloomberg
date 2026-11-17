import type { Metadata } from 'next'
import './globals.css'
import { Inter, Syne, DM_Mono } from 'next/font/google'
import NavWrapper from '@/components/NavWrapper'

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' })
const syne = Syne({ subsets: ['latin'], variable: '--font-syne' })
const dmMono = DM_Mono({ weight: ['400', '500'], subsets: ['latin'], variable: '--font-mono' })

export const metadata: Metadata = {
  title: 'Investing workspace',
  description: 'Explore investing, review a practice portfolio, and understand the tools available.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${syne.variable} ${dmMono.variable}`}>
      <body className="bg-background text-white selection:bg-accent/30 overflow-x-hidden font-inter">
        <NavWrapper>
          <div className="min-h-screen overflow-x-hidden page-shine-shell">
            <div className="page-shine-veil" aria-hidden />
            {children}
          </div>
        </NavWrapper>
      </body>
    </html>
  )
}


