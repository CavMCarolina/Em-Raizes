variable "subscription_id" {
  description = "ID da assinatura Azure for Students (az account show --query id -o tsv)"
  type        = string
}

variable "project" {
  description = "Nome curto do projeto, só letras minúsculas e números"
  type        = string
  default     = "emraizes"

  validation {
    condition     = can(regex("^[a-z0-9]{3,12}$", var.project))
    error_message = "Use de 3 a 12 caracteres, só letras minúsculas e números."
  }
}

variable "location" {
  description = "Região Azure. brazilsouth mantém os dados no Brasil (argumento de LGPD)"
  type        = string
  default     = "brazilsouth"
}

variable "container_image" {
  description = "Imagem do primeiro deploy. Depois, quem troca a imagem é o pipeline"
  type        = string
}

variable "alert_email" {
  description = "E-mail que recebe os alertas"
  type        = string
}

# ---------- Segredos do app (vão para o tfvars, que NÃO vai para o Git) ----------
variable "admin_senha" {
  description = "Senha do administrador do app (EM_RAIZES_ADMIN_SENHA)"
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.admin_senha) >= 12
    error_message = "Use uma senha com pelo menos 12 caracteres."
  }
}

variable "openrouter_api_key" {
  description = "Chave do OpenRouter (opcional: sem ela o Guardião roda em modo offline)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "vapid_privada" {
  description = "Chave VAPID das notificações push (opcional)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "vapid_contato" {
  description = "Contato VAPID, ex.: mailto:equipe@exemplo.com"
  type        = string
  default     = "mailto:admin@example.com"
}
