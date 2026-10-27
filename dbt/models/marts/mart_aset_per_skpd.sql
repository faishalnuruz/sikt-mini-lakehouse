-- Fixed-asset exposure per SKPD, from the legacy Oracle extract.
select
    kode_skpd,
    count(*)              as jumlah_aset,
    sum(nilai_aset)       as total_nilai_aset
from {{ ref('stg_aset') }}
group by 1
