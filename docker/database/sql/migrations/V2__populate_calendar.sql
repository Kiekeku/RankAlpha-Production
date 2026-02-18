-- V2__populate_calendar.sql
-- 2️⃣ Populate date dimension

INSERT INTO dim_date (date_key, full_date, day_of_week,
                      month_num, month_name, quarter, calendar_year)
SELECT  to_char(d,'YYYYMMDD')::INT      AS date_key,
        d                               AS full_date,
        EXTRACT(DOW     FROM d)::SMALLINT,
        EXTRACT(MONTH   FROM d)::SMALLINT,
        TO_CHAR(d,'Mon'),
        EXTRACT(QUARTER FROM d)::SMALLINT,
        EXTRACT(YEAR    FROM d)::SMALLINT
FROM generate_series('2015-01-01'::date,
                     '2035-12-31'::date,
                     '1 day') AS gs(d)
WHERE NOT EXISTS (SELECT 1 FROM dim_date);
