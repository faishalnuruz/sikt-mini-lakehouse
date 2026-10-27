with source as (select * from {{ source('raw', 'raw_ref_skpd') }})

select trim(kode_skpd) as kode_skpd, nama_skpd
from source
