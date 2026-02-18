FROM node:18-alpine AS deps
RUN apk add --no-cache libc6-compat curl
WORKDIR /app

# Enable pnpm via corepack
RUN corepack enable && corepack prepare pnpm@10.27.0 --activate

# Copy package files
COPY package.json ./
COPY pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:18-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NEXT_TELEMETRY_DISABLED 1
ARG NEXT_PUBLIC_API_URL=http://localhost:6080
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG NEXTAUTH_URL=http://localhost:3000
ENV NEXTAUTH_URL=$NEXTAUTH_URL
ARG NEXT_PUBLIC_SITE_URL=http://localhost:3000
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_GTM_ID=
ENV NEXT_PUBLIC_GTM_ID=$NEXT_PUBLIC_GTM_ID
ARG NEXT_PUBLIC_SHOW_RAW_DATA=true
ENV NEXT_PUBLIC_SHOW_RAW_DATA=$NEXT_PUBLIC_SHOW_RAW_DATA

RUN corepack enable && corepack prepare pnpm@10.27.0 --activate && pnpm run build

FROM node:18-alpine AS runner
WORKDIR /app

ENV NODE_ENV production
ENV NEXT_TELEMETRY_DISABLED 1
ENV FRONTEND_BIND_HOST 0.0.0.0

RUN apk add --no-cache curl
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

ENV PORT 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD sh -c "curl -f http://localhost:${PORT:-3000} || exit 1"

CMD ["sh", "-c", "HOSTNAME=${FRONTEND_BIND_HOST:-0.0.0.0} exec node server.js"]
