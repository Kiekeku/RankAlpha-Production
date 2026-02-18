# Scheduling Samples

Use these templates to automate the Daily Report. Adjust paths, times, and accounts as needed.

## Linux/macOS (cron)
- File: `docs/scheduling/cron.daily-report.example`
- Install: `crontab docs/scheduling/cron.daily-report.example`
- Notes:
  - Ensure `uv` is on PATH for the cron environment.
  - The example logs to `logs/daily-report.log`; create the folder or remove the redirection.

## Windows (Task Scheduler)
- File: `docs/scheduling/TaskScheduler-DailyReport.xml`
- Import in Task Scheduler: Action → Import Task…
- Edit after import:
  - Triggers: time/day (Mon–Fri)
  - Actions: confirm `WorkingDirectory` and command path
  - Set “Run whether user is logged on or not” if desired

Tip: To skip holidays as well, keep the daily trigger but call a tiny Python wrapper that checks `is_trading_day` from `tradeexec.utils.market_calendar` before sending the report.
