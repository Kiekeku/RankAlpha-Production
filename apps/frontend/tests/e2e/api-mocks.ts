import type { Page, Route } from '@playwright/test'

type JsonResponse = {
  status?: number
  body: unknown
}

function json({ status = 200, body }: JsonResponse) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  }
}

async function fulfillJson(route: Route, response: JsonResponse) {
  await route.fulfill(json(response))
}

export async function mockRankingsApi(page: Page) {
  await page.route('**/api/grading/grades**', async (route) => {
    await fulfillJson(route, {
      body: {
        stocks: [
          {
            symbol: 'AAA',
            company_name: 'Alpha Co',
            sector: 'Technology',
            momentum_score: 82,
            value_score: 71,
            sentiment_score: 64,
            overall_grade: 'A',
            grade_explanation: 'Strong trend and value support.',
            confidence: 'High',
            date: '2024-01-02',
          },
          {
            symbol: 'BBB',
            company_name: 'Bravo Inc',
            sector: 'Finance',
            momentum_score: 77,
            value_score: 68,
            sentiment_score: 58,
            overall_grade: 'B',
            grade_explanation: 'Solid factors with improving sentiment.',
            confidence: 'Medium',
            date: '2024-01-02',
          },
        ],
        total_count: 2,
        page: 1,
        page_size: 25,
        as_of_date: '2024-01-02',
        ai_preview: {
          AAA: { events_count: 1, base_price_target: 150, has_thesis: true },
          BBB: { events_count: 0, base_price_target: 72, has_thesis: false },
        },
      },
    })
  })

  await page.route('**/api/grading/weights**', async (route) => {
    await fulfillJson(route, {
      body: {
        as_of_date: '2024-01-02',
        method: 'hybrid',
        window_days: 504,
        horizon_days: 21,
        w_momentum: 0.4,
        w_value: 0.4,
        w_sentiment: 0.2,
        lambda_rp: 0.4,
        alpha_shrink: 0.2,
        sentiment_coverage: 0.65,
        source: 'db',
      },
    })
  })

  await page.route('**/api/grading/sectors**', async (route) => {
    await fulfillJson(route, { body: ['Technology', 'Finance'] })
  })

  await page.route('**/api/screener/setups/summary**', async (route) => {
    await fulfillJson(route, { body: { items: [] } })
  })

  await page.route('**/api/ai-analysis/preview**', async (route) => {
    await fulfillJson(route, { body: {} })
  })
}

export async function mockScreenerApi(page: Page) {
  await page.route('**/api/screener/consensus**', async (route) => {
    await fulfillJson(route, {
      body: {
        items: [
          {
            as_of_date: '2024-01-02',
            symbol: 'AAA',
            company_name: 'Alpha Co',
            sector: 'Technology',
            appearances: 4,
            styles_distinct: 2,
            sources_distinct: 2,
            rank_best: 12,
            rank_avg: 18,
            rank_median: 15,
            min_style_rank_pct: 92,
            consensus_score: 84,
            primary_style: 'momentum',
            primary_source: 'internal',
          },
        ],
        total_count: 1,
        page: 1,
        page_size: 25,
        as_of_date: '2024-01-02',
      },
    })
  })

  await page.route('**/api/screener/changes**', async (route) => {
    await fulfillJson(route, { body: { items: [], total_count: 0, page: 1, page_size: 25 } })
  })

  await page.route('**/api/screener/breadth/flow**', async (route) => {
    await fulfillJson(route, { body: { items: [], total_count: 0, page: 1, page_size: 25 } })
  })

  await page.route('**/api/screener/breadth**', async (route) => {
    await fulfillJson(route, { body: { items: [], total_count: 0, page: 1, page_size: 25 } })
  })

  await page.route('**/api/screener/styles/meta**', async (route) => {
    await fulfillJson(route, { body: [] })
  })

  await page.route('**/api/screener/sources/meta**', async (route) => {
    await fulfillJson(route, { body: [] })
  })

  await page.route('**/api/ai-analysis/preview**', async (route) => {
    await fulfillJson(route, { body: {} })
  })
}

export async function mockPipelineHealth(page: Page) {
  await page.route('**/api/pipeline/health**', async (route) => {
    await fulfillJson(route, {
      body: {
        overall_status: 'ok',
        last_check: '2024-01-02T22:10:00Z',
        components: [
          { component: 'ingestion', status: 'healthy', last_run: '2024-01-02T22:00:00Z', message: 'OK' },
          { component: 'scorer', status: 'healthy', last_run: '2024-01-02T22:05:00Z', message: 'OK' },
          { component: 'sentiment', status: 'healthy', last_run: '2024-01-02T22:08:00Z', message: 'OK' },
        ],
      },
    })
  })
}
