-- APBD spending control: an SKPD's realization must never exceed its pagu.
-- A violation here is a data problem or a real overspend; either way it must stop the pipeline.
select *
from {{ ref('mart_realisasi_skpd') }}
where realisasi_total > pagu_total
