import NextAuth, { DefaultSession } from 'next-auth'
import { JWT } from 'next-auth/jwt'

declare module 'next-auth' {
  interface Session {
    user?: DefaultSession['user'] & {
      id?: number
      roles: string[]
    }
    provider?: string
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    userId?: number
    roles?: string[]
    rolesSyncedAt?: number
  }
}
