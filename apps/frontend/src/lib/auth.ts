// Auth configuration for NextAuth (App Router)

import GoogleProvider from 'next-auth/providers/google'
import type { Account, NextAuthOptions } from 'next-auth'
import { syncUserProfile, fetchUserById } from '@/lib/server/auth-service'

const ROLE_REFRESH_INTERVAL_MS = Number(process.env.AUTH_ROLE_REFRESH_INTERVAL_MS || 300_000)

function getProviderAccountId(account: Account | null | undefined): string | undefined {
  if (!account) return undefined
  return (account as any)?.providerAccountId || (account as any)?.providerAccountID || undefined
}

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID || '',
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || '',
    }),
  ],
  session: {
    strategy: 'jwt',
  },
  callbacks: {
    async jwt({ token, account, profile, trigger }) {
      const now = Date.now()
      const email = ((profile as any)?.email || (token as any).email) as string | undefined

      if (account && profile && email) {
        try {
          const synced = await syncUserProfile({
            email,
            full_name: (profile as any)?.name ?? null,
            avatar_url: (profile as any)?.picture ?? null,
            provider: account.provider,
            providerAccountId: getProviderAccountId(account) ?? undefined,
          })
          token.userId = synced.user_id
          token.roles = synced.roles ?? []
          token.email = synced.email
          token.name = synced.full_name || synced.email
          token.picture = synced.avatar_url || token.picture
          token.rolesSyncedAt = now
        } catch (error) {
          console.error('Failed to sync user profile', error)
        }
      }

      const shouldRefreshRoles =
        !!token.userId && (!token.rolesSyncedAt || now - token.rolesSyncedAt > ROLE_REFRESH_INTERVAL_MS || trigger === 'update')

      if (shouldRefreshRoles && token.userId) {
        try {
          const user = await fetchUserById(Number(token.userId))
          token.roles = user.roles ?? []
          token.email = user.email
          token.name = user.full_name || user.email
          token.picture = user.avatar_url || token.picture
          token.rolesSyncedAt = now
        } catch (error) {
          console.error('Failed to refresh user roles', error)
        }
      }

      if (account?.provider) {
        ;(token as any).provider = account.provider
      }

      token.roles = token.roles || []
      return token
    },
    async session({ session, token }) {
      type SessionUser = NonNullable<typeof session.user>

      const user: SessionUser = session.user
        ? { ...session.user, roles: session.user.roles ?? [] }
        : ({ roles: [] } as SessionUser)

      if (Array.isArray(token.roles)) {
        user.roles = token.roles
      }
      if (token.userId) {
        user.id = Number(token.userId)
      }
      if ((token as any).name) {
        user.name = (token as any).name as string
      }
      if ((token as any).picture) {
        user.image = (token as any).picture as string
      }
      if ((token as any).email) {
        user.email = (token as any).email as string
      }
      if ((token as any).provider) {
        ;(session as any).provider = (token as any).provider
      }
      session.user = user
      return session
    },
  },
  secret: process.env.NEXTAUTH_SECRET,
}
