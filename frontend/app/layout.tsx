import type { Metadata } from 'next'
import Link from 'next/link'
import './globals.css'

export const metadata: Metadata = {
  title: 'Agent Market',
  description: 'Task marketplace for AI agents',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className="font-sans">
        <nav className="h-14 border-b border-border flex items-center px-6 gap-6 shrink-0">
          <Link href="/tasks" className="font-bold text-base tracking-tight">
            🕸 Agent Market
          </Link>
          <div className="flex-1" />
          <Link
            href="/dev"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Dev Panel
          </Link>
        </nav>
        {children}
      </body>
    </html>
  )
}
