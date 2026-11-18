#!/usr/bin/env bash
# Prepara a assinatura Azure for Students e cria o storage do Terraform state.
# Rodar uma única vez, a partir da raiz do repositório.
set -euo pipefail

LOCATION="${LOCATION:-brazilsouth}"
TFSTATE_RG="rg-tfstate"
STORAGE="sttfstate${RANDOM}${RANDOM}"

az account show > /dev/null 2>&1 || az login

echo ">> Registrando provedores de recursos (pode levar alguns minutos)"
for p in Microsoft.App Microsoft.ContainerRegistry Microsoft.OperationalInsights \
         Microsoft.Insights Microsoft.ManagedIdentity Microsoft.Storage; do
  az provider register --namespace "$p" --wait
done

echo ">> Criando storage do Terraform state em $LOCATION"
az group create -n "$TFSTATE_RG" -l "$LOCATION" -o none
az storage account create -n "$STORAGE" -g "$TFSTATE_RG" -l "$LOCATION" \
  --sku Standard_LRS --min-tls-version TLS1_2 \
  --allow-blob-public-access false -o none
az storage container create --name tfstate --account-name "$STORAGE" \
  --auth-mode key -o none

cat > infra/backend.hcl << HCL
resource_group_name  = "$TFSTATE_RG"
storage_account_name = "$STORAGE"
container_name       = "tfstate"
key                  = "em-raizes.tfstate"
HCL

echo ">> Pronto. infra/backend.hcl gerado (fica fora do Git)."
echo ">> Subscription ID: $(az account show --query id -o tsv)"
