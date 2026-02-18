# RankAlpha Common Library

## Purpose
The Common library serves as the shared foundation for all RankAlpha services, providing centralized database models, CRUD operations, configuration management, and utility functions. This ensures consistency across all microservices and eliminates code duplication.

## Technologies & Tools

### Core Technologies
- **SQLAlchemy 2.0**: ORM for database model definitions
- **Pydantic**: Configuration and settings management
- **Python 3.12**: Type hints and modern Python features

### Database Support
- **PostgreSQL**: Primary database with advanced features
- **Table Partitioning**: Date-based partitioning for fact tables
- **JSON/JSONB**: For flexible schema fields

## Design Principles

### 1. **Single Source of Truth**
- All database models defined in one place
- Shared across all services for consistency
- Central schema evolution point

### 2. **DRY (Don't Repeat Yourself)**
- Reusable CRUD operations for all models
- Common utility functions
- Shared configuration patterns

### 3. **Type Safety**
- Comprehensive type hints throughout
- Pydantic models for runtime validation
- SQLAlchemy 2.0 typed queries

### 4. **Separation of Concerns**
- Models: Database schema definitions
- CRUD: Data access layer operations
- Settings: Configuration management
- Logging: Centralized logging setup

## Project Structure

### Core Files

#### `models.py`
- **Purpose**: Complete database schema definitions
- **Key Components**:
  - **Base Models**: Abstract base classes with common fields
  - **Dimension Tables** (`dim_*`):
    - `DimStock`: Stock master data (symbol, company, sector, exchange)
    - `DimDate`: Trading calendar (date_key, full_date, is_trading_day, …)
    - `DimScoreType`: Score type registry (e.g., `momentum score`, `value score`)
    - `DimStyle`: Screener style registry
    - `DimFinMetric`: Fundamentals metric registry
    - `DimSource`: Data sources (for provenance)
  - **Fact / View Tables**:
    - `FactScoreHistory`: Historical scores (momentum, value, AI factors, sentiment)
    - `FactFinFundamentals`: Financial metrics (ratios and raw items)
    - `FactNewsSentiment`: Article‑level sentiment (optional)
    - `FactSecurityPrice`: Daily OHLCV snapshot used by views
    - `FactTechnicalIndicator`: Daily indicators written by ingestion
    - `VwStockPriceHistory`, `VwLatestAdjClose`: Read‑only price views for API
    - `VwLatestTechnicals`: Pivoted indicator snapshot for API
  - **Staging Tables**: Temporary data for ETL processes
  - **Utility Tables**: Schedule tracking, metadata

#### `crud.py`
- **Purpose**: Generic CRUD operations for all models
- **Key Features**:
  - **Create Operations**:
    - Single record creation
    - Bulk insert with conflict handling
    - Upsert functionality
  - **Read Operations**:
    - Get by ID
    - List with pagination
    - Complex filtering
    - Sorting and ordering
  - **Update Operations**:
    - Partial updates
    - Bulk updates
    - Conditional updates
  - **Delete Operations**:
    - Soft deletes
    - Cascade handling
    - Bulk deletion
  - **Special Operations**:
    - Get or create patterns
    - Transaction management
    - Query optimization

#### `settings.py`
- **Purpose**: Centralized configuration management
- **Key Features**:
  - Environment-based configuration
  - Pydantic settings for validation
  - Default values with overrides
  - Secret management
  - Database connection strings

#### `logging.py`
- **Purpose**: Standardized logging configuration
- **Key Features**:
  - Structured logging format
  - Log level configuration
  - Service-specific loggers
  - Performance logging

## Database Schema Details

### Dimension Tables

#### Stock Dimension (`dim_stock`)
```python
- symbol: Primary identifier
- name: Company name
- sector: Sector classification
- exchange: Trading exchange
- market_cap: Market capitalization
- metadata: JSONB for flexible attributes
```

#### Metric Dimension (`dim_metric`)
```python
- metric_id: Unique identifier
- metric_name: Human-readable name
- category: Metric category (momentum, value, sentiment)
- description: Detailed description
- calculation_method: How metric is calculated
```

### Fact Tables

#### Score History (`fact_score_history`)
```python
- Partitioned by date for performance
- Stores all calculated scores
- Links to stock and metric dimensions
- Includes rank and percentile data
```

#### Fundamentals (`fact_fundamentals`)
```python
- Financial metrics and ratios
- Quarterly and annual data
- P/E, P/B, ROE, debt ratios
- Growth metrics
```

#### News Sentiment (`fact_news_sentiment`)
```python
- Article-level sentiment scores
- Entity extraction results
- Theme categorization
- Catalyst dates and events
```

### Partitioning Strategy

#### Date-Based Partitioning
- Fact tables partitioned by date
- Monthly or quarterly partitions
- Automatic partition management
- Query optimization for time-series data

## CRUD Operation Patterns

### Basic CRUD
```python
# Create
crud.create(db, model_class, data)

# Read
crud.get(db, model_class, id)
crud.get_multi(db, model_class, skip=0, limit=100)

# Update
crud.update(db, model_class, id, data)

# Delete
crud.delete(db, model_class, id)
```

### Advanced Operations
```python
# Bulk operations
crud.bulk_create(db, model_class, data_list)
crud.bulk_update(db, model_class, updates)

# Upsert
crud.get_or_create(db, model_class, defaults, **kwargs)

# Complex queries
crud.filter(db, model_class, filters)
crud.aggregate(db, model_class, group_by, aggregates)
```

## Configuration Management

### Environment Variables
Loaded from `env/<ENV>/*.env` (API/ingestion/sentiment/scorer) via Settings.
```env
RANKALPHA_ENV=local            # profile selector
# Database (shared field names across apps)
DATABASE_NAME=rankalpha
DB_USERNAME=rankalpha
PASSWORD=rankalpha
HOST=database
DB_PORT=5432                   # API also honors DB_PORT_CONTAINER
# Optional cache
REDIS_URL=redis://cache:6379/0
LOG_LEVEL=INFO
```

### Settings Loading
```python
from apps.common.src.settings_base import BaseAppSettings

settings = BaseAppSettings()  # loads /env/{RANKALPHA_ENV}/shared.env
```

## Usage Examples

### Importing Models
```python
from common.src.models import DimStock, FactScoreHistory
from common.src.crud import get_or_create
```

### Database Operations
```python
# Get stock by symbol
stock = crud.get_by_field(db, DimStock, "symbol", "AAPL")

# Create score record
score_data = {
    "symbol": "AAPL",
    "metric_id": 1,
    "score": 85.5,
    "date": datetime.now()
}
crud.create(db, FactScoreHistory, score_data)
```

## Testing

### Unit Tests
```bash
pytest tests/common/
```

### Test Coverage
- Model validation
- CRUD operations
- Settings loading
- Utility functions

## Performance Considerations

### Query Optimization
- Proper indexing on frequently queried fields
- Eager loading for related objects
- Query result caching
- Batch operations for bulk data

### Connection Management
- Connection pooling configuration
- Session lifecycle management
- Transaction scoping
- Deadlock prevention

## Database Migrations

### Migration Strategy
- Migrations managed by Flyway (in docker/database/sql/migrations/)
- Version controlled SQL scripts
- Backward compatibility maintained
- Zero-downtime migrations where possible

## Best Practices

### When Adding New Models
1. Define model in `models.py`
2. Add appropriate indexes
3. Consider partitioning for large tables
4. Create Flyway migration script
5. Update documentation

### When Adding CRUD Operations
1. Follow existing patterns
2. Include proper error handling
3. Add logging for debugging
4. Consider performance implications
5. Write unit tests

## Dependencies

### Required Packages
- sqlalchemy>=2.0.41
- pydantic>=2.11.7
- pydantic-settings>=2.10.1
- psycopg2-binary>=2.9.0

## Future Enhancements

### Planned Features
- Caching layer with Redis
- Query result memoization
- Database read replicas support
- Automated index recommendations
- Performance monitoring hooks
- Schema versioning system

## Troubleshooting

### Common Issues

1. **Import Errors**
   - Ensure package is installed in editable mode
   - Check PYTHONPATH configuration

2. **Database Connection**
   - Verify DATABASE_URL format
   - Check network connectivity
   - Ensure migrations have run

3. **Model Changes**
   - Create migration before deploying
   - Update dependent services
   - Test with sample data

## Contributing

- Maintain backward compatibility
- Add comprehensive docstrings
- Include type hints
- Write unit tests
- Document breaking changes
