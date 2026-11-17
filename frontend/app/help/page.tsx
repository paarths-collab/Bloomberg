import Link from 'next/link'

export default function HelpPage() {
  return (
    <div className="max-w-2xl space-y-8">
      <h1 className="text-3xl font-semibold">About this workspace</h1>
      <section className="space-y-2">
        <h2 className="text-xl font-medium">Practice, with no real orders</h2>
        <p className="leading-relaxed text-white/60">The portfolio shows simulated holdings stored by the backend. It does not represent money held at a bank or broker. Market values can be unavailable when a data provider cannot be reached.</p>
        <Link href="/portfolio" className="inline-block text-indigo-300 underline">Open practice portfolio</Link>
      </section>
      <section className="space-y-2">
        <h2 className="text-xl font-medium">Your guest session</h2>
        <p className="leading-relaxed text-white/60">The portfolio uses a guest credential saved in this browser. Clearing browser storage can lose access to that guest profile. Account sign-in, subscription management, and recovery are not available.</p>
      </section>
      <section className="space-y-2">
        <h2 className="text-xl font-medium">Advanced tools</h2>
        <p className="leading-relaxed text-white/60">Charts, news, research, and AI tools depend on external data services. Availability varies. Historical simulations describe past results and cannot guarantee what happens next.</p>
      </section>
      <section className="space-y-2">
        <h2 className="text-xl font-medium">What comes next</h2>
        <p className="leading-relaxed text-white/60">Guided onboarding, goal planning, and regular progress check-ins are planned. The old notification, theme, and subscription controls were placeholders and have been removed.</p>
      </section>
    </div>
  )
}
