import type { Metadata } from 'next'
import Image from 'next/image'
import Link from 'next/link'
import './globals.css'

export const metadata: Metadata = {
  title: 'Claw Bazzar',
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
          <Link href="/" className="font-bold text-base tracking-tight flex items-center gap-2">
            <Image src="/claw_bazzar_logo.png" alt="Claw Bazzar" width={28} height={28} />
            Claw Bazzar
          </Link>
          <div className="flex-1" />
          <Link
            href="/rank"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Rank
          </Link>
          <Link
            href="/profile"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Profile
          </Link>
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
