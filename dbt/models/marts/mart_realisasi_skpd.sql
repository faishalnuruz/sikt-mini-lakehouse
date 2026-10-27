-- The alert and dashboard mart: one row per SKPD, realization vs pagu.
-- `over_threshold` is the column the #finmon-alerts notification is built from.
with realisasi as (
    select kode_skpd, sum(realisasi) as realisasi_total
    from {{ ref('fact_realisasi') }}
    group by 1
),
pagu as (
    select kode_skpd, sum(pagu) as pagu_total
    from {{ ref('fact_pagu') }}
    group by 1
)

select
    r.kode_skpd,
    s.nama_skpd,
    p.pagu_total,
    r.realisasi_total,
    p.pagu_total - r.realisasi_total as sisa_pagu,
    round(r.realisasi_total / nullif(p.pagu_total, 0) * 100, 2) as persen_realisasi,
    (r.realisasi_total > p.pagu_total * 0.90) as over_threshold
from realisasi r
join pagu p using (kode_skpd)
join {{ ref('dim_skpd') }} s using (kode_skpd)
