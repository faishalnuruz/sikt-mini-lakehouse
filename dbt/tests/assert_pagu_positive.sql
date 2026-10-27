-- A non-positive pagu breaks every percentage downstream; refuse it here.
select *
from {{ ref('stg_pagu') }}
where pagu <= 0
