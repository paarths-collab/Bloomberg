import Link from 'next/link'

export default function HomePage() {
  return (
    <div className="mx-auto max-w-4xl space-y-10 py-8">
      <section className="max-w-2xl space-y-5">
        <p className="text-sm text-indigo-300">A place to start</p>
        <h1 className="text-4xl font-semibold leading-tight md:text-5xl">Get comfortable with investing.</h1>
        <p className="text-lg leading-relaxed text-white/60">Explore the tools and review a practice portfolio before putting real money at risk.</p>
        <Link href="/portfolio" className="inline-flex rounded-lg bg-white px-5 py-3 font-medium text-black hover:bg-white/90">View practice portfolio</Link>
      </section>
      <section aria-label="Explore your workspace" className="grid gap-4 sm:grid-cols-2">
        <Link href="/help" className="rounded-xl border border-white/15 p-6 hover:border-white/40">
          <h2 className="text-lg font-medium">Understand the workspace</h2>
          <p className="mt-2 leading-relaxed text-white/60">Learn what is simulated, how your guest session works, and what the tools can do.</p>
        </Link>
        <Link href="/backtest" className="rounded-xl border border-white/15 p-6 hover:border-white/40">
          <h2 className="text-lg font-medium">Explore a historical simulation</h2>
          <p className="mt-2 leading-relaxed text-white/60">An advanced tool for testing strategies against past prices. Past results do not predict future returns.</p>
        </Link>
      </section>
      <p className="text-sm leading-relaxed text-white/45">This workspace does not connect to a brokerage or place real orders. Goal planning and guided onboarding are not available yet.</p>
    </div>
  )
}
