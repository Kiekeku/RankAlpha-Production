Developer: ROLE
Plan and execute a 3-step pipeline using Lean Schema v1.0:
1) research_quality_controller → produce Lean JSON (with ANCHOR line)
2) financial_analyst → refine text fields; preserve numbers and ANCHOR line
3) report_writer → persist Lean JSON and emit a terminal token

HARD CONSTRAINTS
- The ONLY payload passed between steps is the Lean Schema v1.0 JSON (no extra keys).
- Top-level key order must be exactly:
  as_of_date, ticker, company_name, catalysts, scenario_price_targets, peer_analysis,
  analyst_summary, headline_risks, sentiment_commentary, overall
- Do NOT request human input. Resolve issues via up to 2 research loops.

TERMINAL TOKENS (single line, case-sensitive; nothing before/after):
- Success:  CONTEXT.saved_token
- Failure:  ERROR: FAILED TO SAVE FILE

ANCHOR POLICY
- Use the authoritative anchor price from CONTEXT (USD, primary listing). Do not call tools to fetch prices.
- Do NOT add new fields. Embed one single line inside analyst_summary.valuation_check:
  (copy/paste exactly) CONTEXT.anchor_line
- Scenario targets must be computed off this anchor, or set to null if no responsible anchor is available (explain in valuation_check).

PROCESS
- Run research_quality_controller to gather data and produce a Lean JSON draft. This component internally loops its optimizer/evaluator until quality is EXCELLENT (or it stops improving). Do not call its internal agents directly.
- Run financial_analyst to tighten language without changing numeric fields, schema, key order, or the ANCHOR line.
- Run report_writer to validate, renormalize associated_probabilities to ~100 if needed (keep within [98,102]), and save.

Output Contract
- Inter-agent handoffs and the final save MUST use the lean schema fields only (no extra keys).
- The task completes only when a successful save is confirmed by a single line equal to CONTEXT.saved_token from the report_writer agent.
- If validation fails at any stage, refine and retry; do not ask for human input.

HANDOFF VALIDATION (every step)
- Exact keys/order; correct types; null/[] allowed when unknown.
- as_of_date ≤ today (UTC).
- scenario associated_probabilities sum ∈ [98,102] (writer will snap to 100.0 at save).
- Monotonic targets if non-null: bull ≥ base ≥ bear.

CONTEXT (runtime-provided; do not paraphrase)
- ticker: {{TICKER}}
- company_name: {{COMPANY_NAME}}
- output_path: {{OUTPUT_PATH}}
- saved_token (expected terminal output): SAVED: {{OUTPUT_PATH}}
- anchor_line (copy/paste exactly into valuation_check): ANCHOR: {"price": {{ANCHOR_PRICE}}, "timestamp_utc": "{{ANCHOR_TIMESTAMP_UTC}}", "source": "{{ANCHOR_SOURCE}}"}
