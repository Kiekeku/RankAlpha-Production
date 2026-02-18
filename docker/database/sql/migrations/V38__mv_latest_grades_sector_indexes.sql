/* ------------------------------------------------------------
   V38__mv_latest_grades_sector_indexes.sql
   Composite indexes to speed sector + grade queries on MV.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- For queries like: sector=... & sort_by=grade & min/max grade filters
CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_grade_idx
  ON rankalpha.mv_latest_grades (sector, grade_order DESC, symbol);

-- Optional: if you often sort by symbol within a sector
CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_symbol_idx
  ON rankalpha.mv_latest_grades (sector, symbol);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

