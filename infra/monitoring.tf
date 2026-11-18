resource "azurerm_monitor_action_group" "email" {
  name                = "ag-${var.project}"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = "emraizes"

  email_receiver {
    name          = "equipe"
    email_address = var.alert_email
  }
}

# Observação: neste ambiente a métrica Requests do Container Apps não traz as dimensões
# statusCode/statusCodeCategory (o filtro por 4xx/5xx fica vazio). Por isso os alertas
# usam o total de requisições e o teste de disponibilidade, que têm dados confirmados.

# Alerta de segurança: pico de requisições. O uso normal fica entre 0 e 3 por minuto;
# mais de 40 em 5 minutos indica força bruta no login ou varredura automatizada.
resource "azurerm_monitor_metric_alert" "pico_requisicoes" {
  name                = "alerta-pico-requisicoes-${var.project}"
  resource_group_name = azurerm_resource_group.rg.name
  scopes              = [azurerm_container_app.app.id]
  description         = "Mais de 40 requisições em 5 minutos: possível força bruta ou varredura"
  severity            = 2
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Requests"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 40
  }

  action {
    action_group_id = azurerm_monitor_action_group.email.id
  }
}

# Sinal de ouro "erros" / disponibilidade: o /api/saude falhou no teste externo
resource "azurerm_monitor_metric_alert" "indisponivel" {
  name                = "alerta-indisponivel-${var.project}"
  resource_group_name = azurerm_resource_group.rg.name
  scopes              = [azurerm_application_insights.appi.id]
  description         = "O /api/saude falhou no teste de disponibilidade (São Paulo e Virgínia)"
  severity            = 1
  frequency           = "PT1M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "availabilityResults/availabilityPercentage"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 90
  }

  action {
    action_group_id = azurerm_monitor_action_group.email.id
  }
}

# Sinal de ouro "latência" (e disponibilidade): /api/saude testado de fora,
# a partir de São Paulo e da Virgínia, a cada 5 minutos
resource "azurerm_application_insights_standard_web_test" "saude" {
  name                    = "disponibilidade-${var.project}"
  resource_group_name     = azurerm_resource_group.rg.name
  location                = azurerm_resource_group.rg.location
  application_insights_id = azurerm_application_insights.appi.id
  geo_locations           = ["latam-br-gru-edge", "us-va-ash-azr"]
  frequency               = 300
  timeout                 = 30
  enabled                 = true
  tags                    = local.tags

  request {
    url = "https://${azurerm_container_app.app.ingress[0].fqdn}/api/saude"
  }

  validation_rules {
    expected_status_code        = 200
    ssl_check_enabled           = true
    ssl_cert_remaining_lifetime = 7
  }
}
