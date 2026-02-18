import { NextRequest, NextResponse } from 'next/server';
import { revalidateTag } from 'next/cache';

// Declare the global type for TypeScript
declare global {
  var lastDataRefresh: string | undefined;
}

export async function POST(request: NextRequest) {
  /**
   * This endpoint is called by Airflow after data updates complete.
   * It triggers a refresh of the data displayed in the frontend.
   */
  // Simple bearer token guard to prevent public abuse. Accept either
  // Authorization: Bearer <token> or X-RA-Refresh-Token: <token>.
  const required = (process.env.FRONTEND_REFRESH_TOKEN || '').trim()
  if (!required) {
    return NextResponse.json({ error: 'Refresh token not configured' }, { status: 503 })
  }
  const auth = request.headers.get('authorization') || ''
  const bearer = auth.startsWith('Bearer ') ? auth.slice(7).trim() : ''
  const alt = request.headers.get('x-ra-refresh-token') || ''
  if (bearer !== required && alt !== required) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  try {
    // In a production app, you might:
    // 1. Clear client-side caches
    // 2. Trigger a WebSocket event to all connected clients
    // 3. Invalidate server-side caches
    // 4. Update a timestamp in Redis that clients check
    
    // For now, log and trigger tag-based cache invalidation for server fetches
    console.log(`Data refresh triggered at ${new Date().toISOString()}`);
    
    // You could store the last refresh time in memory or Redis
    // This can be checked by the frontend to know when to refetch data
    global.lastDataRefresh = new Date().toISOString();

    // Revalidate cached fetches tagged in BFF routes
    try {
      revalidateTag('grades');
      revalidateTag('grade');
      revalidateTag('asset');
      revalidateTag('pipeline');
      revalidateTag('health');
      // AI Analysis pages
      revalidateTag('ai-analysis');
      revalidateTag('ai-analysis-list');
      revalidateTag('ai-analysis-latest');
      // Prices pages
      revalidateTag('prices');
      revalidateTag('prices-history');
      revalidateTag('prices-latest');
      // Macro / regime dashboard (new home page)
      revalidateTag('macro');
      revalidateTag('liquidity');
      revalidateTag('benchmarks');
      revalidateTag('breadth');
      revalidateTag('money-flow');
      revalidateTag('rates');
      revalidateTag('fx');
      revalidateTag('fra-ois');
      revalidateTag('vol-regime');
      // Nowcast (Risk Nowcast cards + macro dashboard)
      revalidateTag('nowcast');
      revalidateTag('nowcast-latest');
      revalidateTag('risk');
      revalidateTag('hy-stress');
      // Upcoming earnings strip on overview page
      revalidateTag('earnings');
      revalidateTag('earnings-upcoming');
      // Per-stock technicals (stock detail modal)
      revalidateTag('technicals');
      // Per-stock fundamentals (stock detail modal)
      revalidateTag('fundamentals');
    } catch (e) {
      // If running in an environment that doesn't support revalidation, ignore
      console.warn('Cache revalidation skipped or failed:', e);
    }
    
    return NextResponse.json({
      status: 'success',
      message: 'Data refresh triggered',
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    console.error('Error during data refresh:', error);
    return NextResponse.json(
      { status: 'error', message: 'Failed to trigger refresh' },
      { status: 500 }
    );
  }
}

export async function GET() {
  /**
   * Get the last refresh timestamp
   */
  return NextResponse.json({
    lastRefresh: global.lastDataRefresh || null
  });
}
