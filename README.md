# RankAlpha

RankAlpha is a team-built market research platform that ingests market data, calculates stock scores, and displays rankings and company research in a web app. This repository is a public snapshot of the project.

## My contributions

I’m Justin Hoang (@Kiekeku). I helped build the stock scoring, data pipeline, rankings, and automated research workflows.

- **Stock scoring.** I built the initial [scoring service](apps/scorer), implemented momentum calculations using a 200-day moving average and linear regression, and connected the service to the database so it could store score history.
- **Pipeline orchestration.** I built the initial [Apache Airflow workflow](infra/airflow/dags/pipeline.py) to run market-data ingestion before scoring.
- **Rankings and grading.** I built the first [Next.js rankings page](apps/frontend/src/app/rankings/page.tsx) and [FastAPI grading endpoints](apps/api/src/routers/grading.py) for viewing stock rankings and individual grades.
- **Automated research.** I added scheduling for company sentiment analysis and implemented an [LLM planner](apps/sentiment/src/llm/gpt5_responses_planner_llm.py) that produces structured outputs for the research workflow.

## Start here

| To see | Start with |
| --- | --- |
| How a price series becomes a momentum input | [Momentum calculator](apps/scorer/src/services/momentum.py) and [scorer tests](tests/scorer/test_utils.py) |
| Why ingestion runs before scoring | [Airflow pipeline](infra/airflow/dags/pipeline.py) |
| How rankings and grades are exposed | [FastAPI grading endpoints](apps/api/src/routers/grading.py) |
| How the services fit together | [Architecture overview](docs/architecture.md) |

## Run the scoring demo

From the repository root, use Python 3.12 and uv. The demo generates 200 synthetic closing prices and calls the same moving-average and log-price regression code used by the scorer. It runs without a database, market data feed, or credentials.

```bash
uv run --no-project --python 3.12 --with pandas --with numpy python -m examples.momentum_demo
uv run --no-project --python 3.12 --with pandas --with numpy --with pytest python -m pytest -q tests/scorer/test_utils.py
```

The synthetic series rises from 100 to 199.50, with a 200-session average of 149.75. The 30-session regression reports a positive trend. The calculator withholds a regression estimate when too few observations in the window have valid prices. The example also shows that case.

## Snapshot limitations

- The full Docker Compose stack cannot start from a fresh checkout. Compose expects local environment files, and the frontend build requires `apps/frontend/package.json` and `apps/frontend/pnpm-lock.yaml`. Both frontend files are absent from this snapshot, which also prevents running the frontend with pnpm.
- A configured database starts without market data. Rankings populate after the ingestion and scoring jobs run.

### Env Profiles

The snapshot includes [example environment files](env/example/README.md). To configure individual services, create `env/local/`, copy the relevant templates from `env/example/`, remove the `.example` suffixes, and fill in local settings. Compose uses `ENV` to select the profile directory and passes the corresponding `RANKALPHA_ENV` to Python services that load profile settings.

## Operational reference

The original project’s operational docs are included for context. Their commands assume a configured checkout with the required build files and service credentials.

- [Docker Compose setup](DOCKER_DEPLOYMENT.md), [deployment reference](DEPLOYMENT.md), and [observability](docs/observability.md)
- [Broker and trading-signal integration](docs/TRADING_SIGNAL_INGESTION.md) and [portfolio construction](docs/PORTFOLIO_CONSTRUCTION.md)
