-- DRAFT: the schema name, the logins and the read access are still to be
-- agreed with the database administrators, and this has not been run on a
-- database yet.
--
-- The behavior table and its per-fix summary, for the e-ecology database.
-- Run once on the main database (not the read-only copy pub.e-ecology.nl),
-- logged in as the login that will load the rows:
--     psql "postgresql://<writer>:<password>@<main host>:5432/eecology" -v ON_ERROR_STOP=1 -f sql/behavior.sql
-- That login then owns the table and the summary, which it needs to refresh
-- the summary. The schema name bird_behavior can be changed; change it in
-- load_behavior.sql too.
--
-- The rows come from the month files of scripts/backfill.sh and
-- scripts/nightly.sh; sql/load_behavior.sql loads them.

CREATE SCHEMA IF NOT EXISTS bird_behavior;

-- One row per burst per model. A burst is 20 acceleration samples (1 s at
-- 20 Hz) taken at one GPS fix; a fix holds 1 to 10 bursts. The columns are
-- those of the CSV of bird_behavior_map.write_behavior, plus created_at.
CREATE TABLE IF NOT EXISTS bird_behavior.behavior (
    device_info_serial integer NOT NULL,                -- tracker, as in gps.ee_tracking_speed_limited
    date_time timestamp(0) without time zone NOT NULL,  -- time of the GPS fix, UTC, as in the GPS table
    first_index smallint NOT NULL,                      -- index of the first sample of the burst: 0, 20, ...
    burst_time timestamp(3) without time zone NOT NULL, -- time of that sample: date_time + first_index x 0.05 s
    model text NOT NULL,                                -- the model that made the class, e.g. exp197
    class_id smallint NOT NULL,                         -- class number
    class_name text NOT NULL,                           -- class name, e.g. Flap
    confidence real NOT NULL,                           -- probability of the class, 0 to 1
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    -- A burst has one row per model. Ordered model first, so reading one
    -- model and one tracker is fast.
    PRIMARY KEY (model, device_info_serial, date_time, first_index)
);

-- One row per GPS fix, for the model apps should show. Stored, not computed
-- on every read; refresh it after loading (see load_behavior.sql).
-- To show another model: DROP MATERIALIZED VIEW bird_behavior.behavior_per_fix;
-- then run this statement and the index below again with the new name.
CREATE MATERIALIZED VIEW IF NOT EXISTS bird_behavior.behavior_per_fix AS
SELECT
    device_info_serial,
    date_time,
    model,
    (array_agg(class_name ORDER BY first_index))[1] AS first_class,  -- colour a point by this
    string_agg(class_name, ',' ORDER BY first_index) AS all_classes, -- e.g. TerLoco,TerLoco,Pecking
    count(*) AS n_bursts
FROM bird_behavior.behavior
WHERE model = 'exp197'
GROUP BY device_info_serial, date_time, model;

-- One row per fix. Also lets the summary be refreshed while apps keep reading
-- it (REFRESH MATERIALIZED VIEW CONCURRENTLY needs a unique index).
CREATE UNIQUE INDEX IF NOT EXISTS behavior_per_fix_fix
    ON bird_behavior.behavior_per_fix (device_info_serial, date_time);

-- Let an app's login read both, e.g. the API's or the waakvogels website's.
-- To be agreed: the existing gps.*_limited views show each login only the
-- trackers of its own projects; apps should read through a view that keeps
-- that rule.
-- GRANT USAGE ON SCHEMA bird_behavior TO <app login>;
-- GRANT SELECT ON bird_behavior.behavior, bird_behavior.behavior_per_fix TO <app login>;
