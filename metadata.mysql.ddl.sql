-- Metadata-driven validation ruleset storage (MySQL)
-- Stores a JSON ruleset that controls which sections/checks run and their parameters.

CREATE TABLE IF NOT EXISTS validation_ruleset (
  ruleset_name VARCHAR(128) PRIMARY KEY,
  version INT NOT NULL,
  rules_json JSON NOT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Example insert (adjust ruleset_name/version as needed):
-- INSERT INTO validation_ruleset (ruleset_name, version, rules_json)
-- VALUES ('default', 1, CAST('{
--   "workflow": { "sections": [
--     {"id":"ach_mdv_validator","enabled": true},
--     {"id":"aba_entropy","enabled": true},
--     {"id":"batch_data_check","enabled": true}
--   ]},
--   "ach_mdv_validator": {
--     "max_error_percent": 2,
--     "checks": {
--       "Bad SEC Codes": {"enabled": true},
--       "Bad Keys": {"enabled": true}
--     }
--   },
--   "batch_data_check": {
--     "required_days_by_type": {"ODFI": 90, "RDFI": 180},
--     "record_type_to_count": 5
--   }
-- }' AS JSON));

