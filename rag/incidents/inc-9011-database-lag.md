kind: incident
title: INC-9011 orders database replica lag
services: orders-db, orders

# INC-9011 orders database replica lag

Orders read replicas lagged behind the primary after a write-heavy campaign.
Failover and read traffic shaping restored order reads. The impact was stale
order status in customer support and checkout confirmation flows.
