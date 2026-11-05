-- DRAFT: not run on a database yet.
--
-- Load one month file of scripts/backfill.sh or scripts/nightly.sh, for
-- example behavior_6004_2013-05.csv, into bird_behavior.behavior. The file
-- comes in on standard input:
--     psql "$WRITE_URL" -v ON_ERROR_STOP=1 -f sql/load_behavior.sql < behavior_6004_2013-05.csv
--
-- The rows already in the table for that tracker, model and month are
-- replaced, so loading a file again gives no duplicates. Everything happens
-- in one transaction: if something fails, the table stays as it was.
--
-- After the last file of a run, refresh the per-fix summary once:
--     psql "$WRITE_URL" -c "REFRESH MATERIALIZED VIEW CONCURRENTLY bird_behavior.behavior_per_fix"

BEGIN;

-- The columns of the CSV, in its order.
CREATE TEMP TABLE incoming (
    device_info_serial integer,
    date_time timestamp(0) without time zone,
    first_index smallint,
    burst_time timestamp(3) without time zone,
    model text,
    class_id smallint,
    class_name text,
    confidence real
) ON COMMIT DROP;

-- pstdin is psql's standard input, the CSV given with <.
\copy incoming FROM pstdin WITH (FORMAT csv, HEADER true)

DELETE FROM bird_behavior.behavior AS b
USING (
    SELECT DISTINCT device_info_serial, model, date_trunc('month', date_time) AS month
    FROM incoming
) AS m
WHERE b.device_info_serial = m.device_info_serial
    AND b.model = m.model
    AND b.date_time >= m.month
    AND b.date_time < m.month + interval '1 month';

INSERT INTO bird_behavior.behavior
    (device_info_serial, date_time, first_index, burst_time, model, class_id, class_name, confidence)
SELECT device_info_serial, date_time, first_index, burst_time, model, class_id, class_name, confidence
FROM incoming;

COMMIT;
