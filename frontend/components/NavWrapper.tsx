import TerminalLayout from './TerminalLayout'

export default function NavWrapper({ children }: { children: React.ReactNode }) {
  return <TerminalLayout>{children}</TerminalLayout>
}
