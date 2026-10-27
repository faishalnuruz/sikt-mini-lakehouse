-- One row per SKPD.
select kode_skpd, nama_skpd
from {{ ref('stg_ref_skpd') }}
