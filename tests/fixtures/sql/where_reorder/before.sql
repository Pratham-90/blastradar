select
    customer_id,
    order_total
from raw.orders
where order_status = 'COMPLETE'
  and order_total > 0
