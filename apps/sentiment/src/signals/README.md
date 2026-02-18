Sentiment Signals Flow

Purpose
- Independent, doc-centric pipeline for sentiment and event intelligence that complements the existing orchestrated report flow. This path classifies per-document sentiment, extracts events, and aggregates daily ticker scores without modifying the existing prompts or workflow.

Components
- Prompts (see ../prompts/signals/):
  - doc_sentiment.md – classify sentiment, aspects, forward-looking flag.
  - event_extractor.md – extract structured events with direction/severity/horizon.
  - entity_resolver.md – map mentions to tickers with confidence and spans.
  - daily_aggregator.md – combine doc-level outputs into a ticker-day score.

Code Layout (initial scaffold)
- pipeline.py – entry points and helpers to wire fetch → classify → extract → aggregate.
- (future) writer.py – persistence to FactNewsArticles, FactNewsSentiment, FactScoreHistory.
- (future) sources/ – connectors for news and transcripts.

Notes
- This is a new, separate path. Existing sentiment app flows and prompts remain untouched.
- Configure via existing Settings keys under `sentiment_*` as needed when wiring execution.

