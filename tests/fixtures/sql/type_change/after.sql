select
    order_id,
    cast(order_total as float) as order_total
from raw.orders
