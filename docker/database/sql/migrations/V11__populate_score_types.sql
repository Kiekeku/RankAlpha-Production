INSERT INTO dim_score_type (score_type_name) VALUES
  ('SMA 200'),
  ('linear regression 200'),
  ('linear regression 90'),
  ('linear regression 50'),
  ('linear regression 30')
ON CONFLICT (score_type_name) DO NOTHING;