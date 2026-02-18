import Link from 'next/link'

export function Footer() {
  const year = new Date().getFullYear()
  return (
    <footer className="border-t bg-background/80 py-6 text-sm text-muted-foreground">
      <div className="container flex flex-col gap-2 text-center sm:flex-row sm:items-center sm:justify-between sm:text-left">
        <div>&copy; {year} RankAlpha</div>
        <div className="flex flex-wrap justify-center gap-x-4 gap-y-2 sm:justify-end">
          <Link href="/methodology" className="hover:text-foreground">Docs</Link>
          <Link href="/disclaimer" className="hover:text-foreground">Disclaimer</Link>
          <Link href="/about" className="hover:text-foreground">About</Link>
        </div>
      </div>
    </footer>
  )
}
