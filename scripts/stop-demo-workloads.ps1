$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DemoServices = @(
    "ob-redis-cart", "ob-currencyservice", "ob-productcatalogservice", "ob-paymentservice",
    "ob-shippingservice", "ob-emailservice", "ob-adservice", "ob-cartservice",
    "ob-recommendationservice", "ob-checkoutservice", "ob-frontend", "ob-loadgenerator", "ob-cadvisor",
    "rs-mongodb", "rs-redis", "rs-rabbitmq", "rs-mysql", "rs-catalogue", "rs-user", "rs-cart",
    "rs-shipping", "rs-ratings", "rs-payment", "rs-dispatch", "rs-web", "rs-load-gen",
    "rs-mysqld-exporter", "rs-redis-exporter", "rs-rabbitmq-exporter", "rs-mongodb-exporter"
)

Push-Location $RepoRoot
try {
    docker compose --profile demo-online-boutique --profile demo-robot-shop stop @DemoServices
    if ($LASTEXITCODE -ne 0) { throw "Unable to stop one or more demo services." }
    Write-Host "Demo workloads stopped. KaiMS core services and persistent volumes were preserved." -ForegroundColor Green
}
finally {
    Pop-Location
}
