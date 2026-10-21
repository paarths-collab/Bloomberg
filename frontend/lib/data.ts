/**
 * Static content for the marketing pages (home, ecosystem, network, blog).
 *
 * This module was never committed to the repository. It is restored here with
 * honest, minimal content so the app type-checks and builds: empty collections
 * (which render empty sections) and one neutral placeholder where a page
 * destructures its first item. Real content (copy, partner lists, statistics,
 * posts) is a frontend follow-up and must come from the product owners; nothing
 * here is a claim about the product, its performance or its partners.
 */

export type StatBarItem = { label: string; value: string }

export type ApyItem = { name: string; abbr: string; pct: number; color: string }

export type OnboardLink = { name: string; status: string }
export type OnboardCard = {
  title: string
  badge: string
  desc1: string
  desc2: string
  links: OnboardLink[]
}

export type TransparencyCard = Record<string, unknown>
export type TransparencyStat = Record<string, unknown>

export type HighlightItem = { title: string; tag: string; desc: string; link: string }

export type AccessTier = {
  tier: string
  badge: string
  price: string
  unit: string
  desc: string
  features: string[]
}

export type EcosystemItem = { name: string; type: string; color: string; apy: string }

export type NetworkCustodian = {
  name: string
  type: string
  desc: string
  tvl: string
  chains: number
  uptime: string
}

export type BlogPost = {
  title: string
  tag: string
  excerpt: string
  date: string
  readTime: string
  emoji: string
  color: string
}

export const statsBar: StatBarItem[] = []

export const apyData: ApyItem[] = []

export const onboardData: OnboardCard[] = []

// Imported by the home page but not rendered by it.
export const transparencyCards: TransparencyCard[] = []
export const transparencyStats: TransparencyStat[] = []

export const highlightsData: HighlightItem[] = []

export const accessTiers: AccessTier[] = []

// 'All' is the only filter the ecosystem page requires (it is its initial state).
export const ecosystemFilters: string[] = ['All']
export const ecosystemData: EcosystemItem[] = []

export const networkData: NetworkCustodian[] = []

// The blog page destructures `[featured, ...rest]` and reads featured.* unguarded,
// so this list needs one entry to render. It is a neutral placeholder, not a post.
export const blogData: BlogPost[] = [
  {
    title: 'No posts published yet',
    tag: 'Notice',
    excerpt: 'Articles will appear here once they are published.',
    date: '',
    readTime: '',
    emoji: '',
    color: 'transparent',
  },
]
