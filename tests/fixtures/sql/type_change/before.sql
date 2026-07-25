select
    order_id,
    cast(order_total as number(10, 2)) as order_total
from raw.orders
