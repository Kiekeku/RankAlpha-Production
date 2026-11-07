# RankAlpha

RankAlpha is a team-built market research platform that ingests market data, calculates stock scores, and displays rankings and company research in a web app. This repository is a public snapshot of the project.

## My contributions

I’m Justin Hoang (@Kiekeku). I helped build the stock scoring, data pipeline, rankings, and automated research workflows.

- **Stock scoring.** I built the initial [scoring service](apps/scorer), implemented momentum calculations using a 200-day moving average and linear regression, and connected the service to the database so it could store score history.
- **Pipeline orchestration.** I built the initial [Apache Airflow workflow](infra/airflow/dags/pipeline.py) to run market-data ingestion before scoring.
- **Rankings and grading.** I built the first [Next.js rankings page](apps/frontend/src/app/rankings/page.tsx) and [FastAPI grading endpoints](apps/api/src/routers/grading.py) for viewing stock rankings and individual grades.
- **Automated research.** I added scheduling for company sentiment analysis and implemented an [LLM planner](apps/sentiment/src/llm/gpt5_responses_planner_llm.py) that produces structured outputs for the research workflow.

## Explore the code

- [Architecture overview](docs/architecture.md) explains how the services fit together.
- [Market-data ingestion](apps/ingestion) and [scoring methodology](docs/SCORING.md) cover how price data becomes stock scores.
- The [Next.js frontend](apps/frontend) uses the [FastAPI backend](apps/api) to display stock rankings and company research.
- The [Airflow pipeline](infra/airflow/dags/pipeline.py) coordinates data ingestion and scoring. The [sentiment service](apps/sentiment) runs automated company research.

## Snapshot limitations

- The full Docker Compose stack cannot start from a fresh checkout. Compose expects local environment files, and the frontend build requires `apps/frontend/package.json` and `apps/frontend/pnpm-lock.yaml`. Both frontend files are absent from this snapshot, which also prevents running the frontend with pnpm.
- A configured database starts without market data. Rankings populate after the ingestion and scoring jobs run.

### Env Profiles

The snapshot includes [example environment files](env/example/README.md). To configure individual services, create `env/local/`, copy the relevant templates from `env/example/`, remove the `.example` suffixes, and fill in local settings. Compose uses `ENV` to select the profile directory and passes the corresponding `RANKALPHA_ENV` to Python services that load profile settings.

## Operational reference

The original project’s operational docs are included for context. Their commands assume a configured checkout with the required build files and service credentials.

- [Docker Compose setup](DOCKER_DEPLOYMENT.md), [deployment reference](DEPLOYMENT.md), and [observability](docs/observability.md)
- [Broker and trading-signal integration](docs/TRADING_SIGNAL_INGESTION.md) and [portfolio construction](docs/PORTFOLIO_CONSTRUCTION.md)
