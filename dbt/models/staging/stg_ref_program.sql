with source as (select * from {{ source('raw', 'raw_ref_program') }})

select trim(kode_program) as kode_program, nama_program
from source
