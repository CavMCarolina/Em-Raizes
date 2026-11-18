# Deploy na Azure com CI/CD (Terraform + GitHub Actions)

O app inteiro (API em `/api` + app do administrador em `/`) roda numa imagem Docker só, no **Azure Container Apps**.
Ninguém publica pelo portal: o **Terraform** cria a infraestrutura e o **pipeline** publica cada versão.

```text
push / PR ──► GitHub Actions
               ├─ Gitleaks (segredos) · Semgrep (SAST) · backend · frontend · notebook
               │        qualquer falha barra o build
               ├─ Imagem: docker compose build → Trivy → sobe a stack e testa /api/saude
               │        na main: push para o Azure Container Registry (tag = SHA do commit)
               └─ Deploy (só push na main, só se tudo passou):
                        az containerapp update → espera /api/saude mostrar o commit → teste de fumaça
```

- **Pull request:** roda tudo, menos o push da imagem e o deploy.
- **Push na `main`:** tudo, e publica se todos os jobs passarem.
- **Tag `v*`:** também publica a imagem no GitHub Container Registry.

Arquivos: [`infra/`](../infra/) (Terraform), [`scripts/bootstrap-azure.sh`](../scripts/bootstrap-azure.sh),
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml), [`Dockerfile`](../Dockerfile) e
[`docker-compose.yml`](../docker-compose.yml).

> **Por que um processo contínuo (e não funções serverless):** o Em Raízes guarda comandos, voos e o progresso do robô
> **na memória de um processo**. Por isso o Container App roda com exatamente **1 réplica sempre ligada**.

## Pré-requisitos

Git (no Windows, use o **Git Bash** para todos os comandos), Docker Desktop, Azure CLI e Terraform 1.6 ou mais novo.

```bash
git --version && docker --version && az version && terraform version
az login
az account show --query "{nome:name, id:id}" -o table
```

## 1. Preparar a assinatura e o state (uma vez só)

```bash
LOCATION=eastus2 bash scripts/bootstrap-azure.sh
```

O script registra os provedores de recursos, cria o Storage Account do Terraform state (`rg-tfstate`) e gera
`infra/backend.hcl`, que fica fora do Git.

> **Azure for Students:** a assinatura só permite algumas regiões. `brazilsouth` é recusada com
> `RequestDisallowedByAzure`. Use `eastus2` (ou consulte as permitidas com
> `az policy assignment list --query "[].parameters.listOfAllowedLocations.value"`). Se o script falhar no meio,
> apague o grupo antes de tentar outra região: `az group delete -n rg-tfstate --yes`.

## 2. Variáveis do Terraform

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # NÃO vai para o Git
```

Preencha `subscription_id`, `location = "eastus2"`, `alert_email` e `admin_senha` (12 caracteres ou mais).
`openrouter_api_key` é opcional: sem ela, o Guardião roda em modo offline. O segredo JWT é gerado pelo Terraform.

## 3. Registro de imagens e primeira imagem

O Container App precisa de uma imagem que já exista, então o registro vem primeiro:

```bash
terraform init -backend-config=backend.hcl
terraform apply -target=azurerm_container_registry.acr

ACR=$(terraform output -raw acr_name)
cd ..
az acr login -n $ACR
docker build --build-arg EM_RAIZES_COMMIT=v1 -t $ACR.azurecr.io/em-raizes:v1 .
docker push $ACR.azurecr.io/em-raizes:v1
```

Coloque essa imagem em `container_image` no `infra/terraform.tfvars`.

## 4. Resto da infraestrutura

```bash
cd infra
terraform apply
```

Cria o ambiente e o app do Container Apps, a identidade gerenciada com `AcrPull`, Log Analytics, Application Insights,
o teste de disponibilidade e os alertas. O output `app_url` é a URL pública. Se o primeiro apply falhar ao puxar a
imagem, espere 1 a 2 minutos (a permissão leva um tempo para propagar) e rode de novo.

A partir daqui, a imagem do app é trocada **só pelo pipeline**: o Terraform ignora mudanças nela.

## 5. Ligar o GitHub Actions à Azure

```bash
SUB=$(az account show --query id -o tsv)
MSYS_NO_PATHCONV=1 az ad sp create-for-rbac --name sp-github-emraizes --role Contributor \
  --scopes /subscriptions/$SUB/resourceGroups/rg-emraizes --json-auth
```

> `MSYS_NO_PATHCONV=1` é necessário no Git Bash: sem ele, `/subscriptions/...` vira um caminho do Windows.

O JSON impresso é uma **credencial**: não cole em chat nem em arquivo do repositório. Em
**Settings → Secrets and variables → Actions**:

| Tipo | Nome | Valor |
|---|---|---|
| Secret | `AZURE_CREDENTIALS` | o JSON inteiro |
| Variable | `ACR_NAME` | `terraform output -raw acr_name` |
| Variable | `RESOURCE_GROUP` | `rg-emraizes` |
| Variable | `CONTAINER_APP` | `ca-emraizes` |

> Em repositório de **conta pessoal**, só a dona do repo acessa Settings → Secrets; colaboradores não.
> Se algum push na `main` rodou antes do secret existir, o deploy aparece como "pulado": abra essa execução e use
> **Re-run all jobs**.

## 6. Conferir

Depois de um push na `main`, o job **Deploy** só fica verde quando `/api/saude` responde com o commit novo:

```bash
curl https://<app_url>/api/saude   # {"status":"ok","versao":"0.2.0","commit":"<sha do commit>"}
```

## Observabilidade

- **Painel:** no portal, abra **Métricas** e fixe os quatro gráficos num painel: `Requests` (tráfego), CPU e memória
  (saturação) do Container App, e duração e disponibilidade do teste do Application Insights (latência e erros).
- **Alertas:** `alerta-pico-requisicoes-emraizes` (mais de 40 requisições em 5 min) e `alerta-indisponivel-emraizes`.
  Para testar o primeiro:

```bash
URL=https://<app_url>
for r in 1 2; do for i in $(seq 1 30); do curl -s -o /dev/null -w "%{http_code} " -X POST $URL/api/auth/login \
  -H "Content-Type: application/json" -d '{"usuario":"admin","senha":"errada"}'; done; echo; done
```

Em 5 a 10 minutos o alerta aparece em **Azure Monitor → Alertas** e chega por e-mail. Neste ambiente, a métrica
`Requests` não traz as dimensões de código HTTP; por isso não há alerta por 4xx/5xx.

## Solução de problemas

| Sintoma | Causa e solução |
|---|---|
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop fechado: abra e espere "Engine running" |
| `lookup registry-1.docker.io: no such host` | DNS do Docker: `wsl --shutdown`, reabra o Docker Desktop ou fixe `"dns": ["8.8.8.8"]` em Settings → Docker Engine |
| Gitleaks acusa um valor de teste | Confirme que não é segredo e adicione o fingerprint ao `.gitleaksignore` |
| Trivy barra a imagem com CVE "fixed" | Atualização do Debian ainda não está na imagem base: o `apt-get upgrade` do Dockerfile resolve no próximo build |

## Depois da avaliação

```bash
cd infra && terraform destroy
az ad sp delete --id $(az ad sp list --display-name sp-github-emraizes --query "[0].appId" -o tsv)
az group delete -n rg-tfstate --yes
```
