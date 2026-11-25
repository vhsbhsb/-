-- 只使用交易发生前七天的金额。同一秒发生的交易也排除。
CREATE TEMP TABLE features AS
SELECT *,
       COUNT(*) OVER history AS prior_count,
       AVG(amount) OVER history AS prior_avg
FROM transactions
WINDOW history AS (
    PARTITION BY customer ORDER BY ts
    RANGE BETWEEN 604800 PRECEDING AND 1 PRECEDING
);

-- 冷启动时采用开发期平均金额作为参考。五笔等效历史用于平滑。
CREATE INDEX customer_time ON transactions(customer, ts);

CREATE TEMP TABLE ranked AS
WITH history_stats AS (
    SELECT f.*, (SELECT median_amount(t.amount) FROM transactions AS t
                 WHERE t.customer = f.customer AND t.ts >= f.ts - 604800
                       AND t.ts < f.ts) AS prior_median
    FROM features AS f WHERE f.ts >= :test_start
), scored AS (
    SELECT *, amount / ((COALESCE(prior_avg, 0) * prior_count + 5 * :reference)
                        / (prior_count + 5)) AS relative_amount
    FROM history_stats
)
SELECT *,
       ROW_NUMBER() OVER (PARTITION BY date(ts, 'unixepoch')
                          ORDER BY amount DESC, id) AS amount_rank,
       ROW_NUMBER() OVER (PARTITION BY date(ts, 'unixepoch')
                          ORDER BY relative_amount DESC, id) AS relative_rank,
       ROW_NUMBER() OVER (PARTITION BY date(ts, 'unixepoch')
                          ORDER BY amount / COALESCE(prior_avg, :reference) DESC, id) AS mean_rank,
       ROW_NUMBER() OVER (PARTITION BY date(ts, 'unixepoch')
                          ORDER BY amount / COALESCE(prior_median, :reference) DESC, id) AS median_rank
FROM scored;
