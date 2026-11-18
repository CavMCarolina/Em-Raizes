resource "azurerm_monitor_action_group" "email" {
  name                = "ag-${var.project}"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = "emraizes"

  email_receiver {
    name          = "equipe"
    email_address = var.alert_email
  }
}

# Sinal de ouro "erros": mais de 5 respostas 5xx em 5 minutos
resource "azurerm_monitor_metric_alert" "http_5xx" {
  name                = "alerta-5xx-${var.project}"
  resource_group_name = azurerm_resource_group.rg.name
  scopes              = [azurerm_container_app.app.id]
  description         = "Mais de 5 respostas HTTP 5xx em 5 minutos"
  severity            = 1
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Requests"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 5

    dimension {
      name     = "statusCodeCategory"
      operator = "Include"
      values   = ["5xx"]
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.email.id
  }
}

# Alerta de segurança: rajada de 4xx (ex.: tentativas de login com senha errada)
resource "azurerm_monitor_metric_alert" "http_4xx" {
  name                = "alerta-4xx-forca-bruta-${var.project}"
  resource_group_name = azurerm_resource_group.rg.name
  scopes              = [azurerm_container_app.app.id]
  description         = "Mais de 20 respostas 4xx em 5 minutos: possível força bruta no login"
  severity            = 2
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Requests"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 20

    dimension {
      name     = "statusCodeCategory"
      operator = "Include"
      values   = ["4xx"]
    }
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
