-- One row per program.
select kode_program, nama_program
from {{ ref('stg_ref_program') }}
