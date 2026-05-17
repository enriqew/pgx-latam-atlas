CREATE DATABASE IF NOT EXISTS bronze_pgx
COMMENT 'Raw ingested data, minimal transformations, partitioned by ingest_date';

CREATE DATABASE IF NOT EXISTS silver_pgx
COMMENT 'Conformed, typed, deduplicated tables with stable business keys';

CREATE DATABASE IF NOT EXISTS gold_pgx
COMMENT 'Business-logic tables ready for analytical consumption and portfolio export';
