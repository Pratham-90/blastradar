select
    customer_id,
    order_total
from raw.orders
where order_total > 0
  and order_status = 'COMPLETE'
