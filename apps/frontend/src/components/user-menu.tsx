'use client'

import Image from 'next/image'
import { signIn, signOut, useSession } from 'next-auth/react'

type UserMenuVariant = 'desktop' | 'mobile'

export function UserMenu({ variant = 'desktop' }: { variant?: UserMenuVariant }) {
  const { data: session, status } = useSession()
  const loading = status === 'loading'

  if (loading) return null

  if (!session?.user) {
    const buttonClasses =
      variant === 'mobile'
        ? 'inline-flex w-full items-center justify-center rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent'
        : 'inline-flex items-center rounded-md border px-2 py-1 text-sm hover:bg-accent'
    return (
      <button
        type="button"
        className={buttonClasses}
        onClick={() => signIn('google')}
      >
        Sign in
      </button>
    )
  }

  const name = session.user.name || 'User'
  const image = session.user.image
  if (variant === 'mobile') {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
          {image ? (
            <Image src={image} alt={name} width={24} height={24} className="rounded-full" />
          ) : (
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-muted text-xs">
              {name.slice(0, 1)}
            </span>
          )}
          <span>{name.split(' ')[0]}</span>
        </div>
        <button
          type="button"
          className="inline-flex items-center justify-center rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent"
          onClick={() => signOut()}
        >
          Sign out
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-2 rounded-md border px-2 py-1 text-sm">
        {image ? (
          <Image src={image} alt={name} width={20} height={20} className="rounded-full" />
        ) : (
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-muted text-xs">
            {name.slice(0, 1)}
          </span>
        )}
        <span className="hidden sm:inline">{name.split(' ')[0]}</span>
      </div>
      <button
        type="button"
        className="inline-flex items-center rounded-md border px-2 py-1 text-sm hover:bg-accent"
        onClick={() => signOut()}
      >
        Sign out
      </button>
    </div>
  )
}
