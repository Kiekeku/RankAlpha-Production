-- V3__create_partitions.sql
-- 3️⃣ Create monthly partitions (2015–2035)

DO
$$
DECLARE
    yr  INT := 2015;
    mo  INT := 1;
    start_key INT;
    end_key   INT;
    part_name TEXT;
BEGIN
  WHILE yr <= 2035 LOOP
        start_key := yr * 10000 + mo * 100 + 1;
        end_key   := yr * 10000 + mo * 100 + 32;
        part_name := format('fact_screener_rank_%s_%s',
                            yr,
                            lpad(mo::TEXT,2,'0'));

        EXECUTE format(
          'CREATE TABLE IF NOT EXISTS %I
             PARTITION OF fact_screener_rank
             FOR VALUES FROM (%s) TO (%s);',
          part_name, start_key, end_key);

        mo := mo + 1;
        IF mo > 12 THEN
            mo := 1;
            yr := yr + 1;
        END IF;
  END LOOP;
END;
$$;
