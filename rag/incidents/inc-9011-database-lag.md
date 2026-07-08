alert_id: INC-9011
alert_name: INC-9011 orders database replica lag
service: orders-db
severity: high
alert_type: replication
source_system: internal
source_ref: INC-9011

# INC-9011 orders database replica lag

Orders read replicas lagged behind the primary after a write-heavy campaign.
Failover and read traffic shaping restored order reads. The impact was stale
order status in customer support and checkout confirmation flows.
