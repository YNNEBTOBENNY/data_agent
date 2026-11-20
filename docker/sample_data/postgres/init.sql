-- 电商样例库（PostgreSQL）。时间字段统一存 UTC。
CREATE TABLE fact_orders (
    id BIGSERIAL PRIMARY KEY,
    order_amount NUMERIC(12, 2) NOT NULL,
    region VARCHAR(32) NOT NULL,
    province VARCHAR(32) NOT NULL,
    city VARCHAR(32) NOT NULL,
    store VARCHAR(32) NOT NULL,
    order_time TIMESTAMP NOT NULL,
    customer_id BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL
);

COMMENT ON TABLE fact_orders IS '订单事实表';
COMMENT ON COLUMN fact_orders.order_amount IS '订单金额';
COMMENT ON COLUMN fact_orders.region IS '大区';
COMMENT ON COLUMN fact_orders.province IS '省';
COMMENT ON COLUMN fact_orders.city IS '市';
COMMENT ON COLUMN fact_orders.store IS '门店';
COMMENT ON COLUMN fact_orders.order_time IS '下单时间(UTC)';
COMMENT ON COLUMN fact_orders.customer_id IS '客户ID';
COMMENT ON COLUMN fact_orders.status IS '订单状态';

CREATE TABLE dim_customers (
    customer_id BIGINT PRIMARY KEY,
    customer_name VARCHAR(64) NOT NULL,
    city VARCHAR(32) NOT NULL,
    vip_level VARCHAR(16) NOT NULL
);

COMMENT ON TABLE dim_customers IS '客户维度表';
COMMENT ON COLUMN dim_customers.customer_name IS '客户姓名';
COMMENT ON COLUMN dim_customers.vip_level IS '会员等级';

INSERT INTO fact_orders (order_amount, region, province, city, store, order_time, customer_id, status) VALUES
(120.50, '华东', '浙江', '杭州', '杭州西湖店', '2026-10-05 08:00:00', 1, 'paid'),
(340.00, '华东', '浙江', '杭州', '杭州西湖店', '2026-10-12 09:30:00', 2, 'paid'),
(89.90, '华东', '江苏', '南京', '南京新街口店', '2026-10-15 14:00:00', 3, 'paid'),
(500.00, '华北', '北京', '北京', '北京朝阳店', '2026-10-20 10:00:00', 4, 'paid'),
(150.00, '华北', '北京', '北京', '北京朝阳店', '2026-10-22 16:20:00', 1, 'paid'),
(60.00, '华南', '广东', '深圳', '深圳南山店', '2026-11-01 11:00:00', 5, 'paid'),
(210.00, '华南', '广东', '广州', '广州天河店', '2026-11-05 13:45:00', 2, 'paid'),
(75.00, '华东', '上海', '上海', '上海静安店', '2026-11-10 18:30:00', 6, 'paid'),
(430.00, '华东', '上海', '上海', '上海静安店', '2026-11-12 10:15:00', 3, 'paid'),
(99.00, '华北', '天津', '天津', '天津和平店', '2026-11-14 12:00:00', 4, 'paid');

INSERT INTO dim_customers (customer_id, customer_name, city, vip_level) VALUES
(1, '张三', '杭州', 'gold'),
(2, '李四', '杭州', 'silver'),
(3, '王五', '南京', 'gold'),
(4, '赵六', '北京', 'platinum'),
(5, '钱七', '深圳', 'silver'),
(6, '孙八', '上海', 'gold');

-- 只读账号：仅 SELECT 权限
CREATE ROLE readonly LOGIN PASSWORD 'readonly_pw';
GRANT CONNECT ON DATABASE ecommerce TO readonly;
GRANT USAGE ON SCHEMA public TO readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly;
