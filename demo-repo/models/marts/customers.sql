-- Customer dimension: one row per customer, enriched for analytics + ML feature builds.
-- Materialized as ORDER_ENTRY_DB.analytics.customers and registered in DataHub, where it
-- is the upstream of the `customer_features` feature table (churn / LTV / reactivation).
-- (Compiled form shown; the authored model reads {{ ref('stg_customers') }} and
--  {{ ref('stg_orders') }}.)
with customers as (

    select * from stg_customers

),

order_rollup as (

    select
        customer_id,
        count(*)          as lifetime_order_count,
        max(order_date)   as most_recent_order_date
    from stg_orders
    group by 1

)

select
    c.customer_id,
    c.first_name,
    c.last_name,
    c.email,
    c.customer_since,                                   -- account-age driver for ML features
    c.loyalty_tier,
    c.credit_limit,
    c.phone_number,
    c.town_city,
    c.country_id,
    coalesce(o.lifetime_order_count, 0) as lifetime_order_count,
    o.most_recent_order_date
from customers c
left join order_rollup o
    on c.customer_id = o.customer_id
