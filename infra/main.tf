resource "random_string" "suffix" {
  length  = 5
  special = false
  upper   = false
}

# Segredo JWT gerado pelo próprio Terraform: nenhuma pessoa precisa ver ou digitar
resource "random_password" "jwt" {
  length  = 48
  special = false
}

locals {
  suffix = random_string.suffix.result
  tags = {
    projeto    = "em-raizes"
    disciplina = "secure-devops"
    gerenciado = "terraform"
  }

  # Segredos do Container App -> variável de ambiente que o app lê
  segredos = {
    "admin-senha"    = var.admin_senha
    "segredo-jwt"    = random_password.jwt.result
    "openrouter-key" = var.openrouter_api_key
    "vapid-privada"  = var.vapid_privada
  }
  env_dos_segredos = {
    "admin-senha"    = "EM_RAIZES_ADMIN_SENHA"
    "segredo-jwt"    = "EM_RAIZES_SEGREDO_JWT"
    "openrouter-key" = "OPENROUTER_API_KEY"
    "vapid-privada"  = "EM_RAIZES_VAPID_PRIVADA"
  }
  # Só cria os segredos preenchidos (os nomes não são sensíveis, os valores sim)
  segredos_ativos = nonsensitive(toset([for k, v in local.segredos : k if v != ""]))

  env_publicas = {
    EM_RAIZES_AMBIENTE         = "producao"
    EM_RAIZES_ADMIN_USUARIO    = "admin"
    EM_RAIZES_SIM_CENARIO      = "real"
    EM_RAIZES_VAPID_CONTATO    = var.vapid_contato
    OPENROUTER_MODEL           = "google/gemma-4-31b-it:free"
    OPENROUTER_FALLBACK_MODELS = "nvidia/nemotron-3.5-super-vl:free,google/gemma-4-26b-a4b-it:free"
  }
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${var.project}"
  location = var.location
  tags     = local.tags
}

# ---------- Observabilidade ----------
resource "azurerm_log_analytics_workspace" "law" {
  name                = "log-${var.project}-${local.suffix}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_application_insights" "appi" {
  name                = "appi-${var.project}-${local.suffix}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"
  tags                = local.tags
}

# ---------- Registro de imagens ----------
resource "azurerm_container_registry" "acr" {
  name                = "acr${var.project}${local.suffix}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Basic"
  admin_enabled       = false # sem usuário/senha de admin: pull via identidade gerenciada
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.project}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# ---------- Execução ----------
# Container Apps é serverless: não há VM, SSH ou RDP, então nenhuma porta
# administrativa existe para ser aberta a 0.0.0.0/0. Só o HTTPS (443) é público.
resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${var.project}"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  tags                       = local.tags
}

resource "azurerm_container_app" "app" {
  name                         = "ca-${var.project}"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = local.segredos_ativos
    content {
      name  = secret.value
      value = local.segredos[secret.value]
    }
  }

  ingress {
    external_enabled           = true
    target_port                = 8000
    transport                  = "auto"
    allow_insecure_connections = false # só HTTPS

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # O app guarda comandos e eventos na memória de um único processo (ver README,
    # "Limitações"): exatamente 1 réplica, sempre ligada, para não perder o estado.
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "em-raizes"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.env_publicas
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.segredos_ativos
        content {
          name        = local.env_dos_segredos[env.value]
          secret_name = env.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/api/saude"
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/api/saude"
      }
    }
  }

  lifecycle {
    # A imagem passa a ser atualizada pelo pipeline (deploy automático)
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}
