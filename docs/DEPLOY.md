# Deploy com CI/CD (GitHub Actions + Render)

O app inteiro (API em `/api` + app do administrador em `/`) roda numa imagem Docker só. O caminho até o ar:

```text
push na main ──► GitHub Actions: backend · frontend · notebook · docker   (testes)
                         │ todos passaram?
                         ▼
                 job "Deploy (Render)": pede ao Render o deploy DESTE commit (Deploy Hook)
                         │
                         ▼
                 espera /api/saude mostrar o commit novo ──► teste de fumaça no site publicado
```

- **Pull request:** só roda os testes (não publica nada).
- **Push na `main`:** testes e, se todos passarem, deploy.
- **Tag `v*`** (ex.: `v0.2.0`): também publica a imagem no GitHub Container Registry (`ghcr.io/<usuario>/<repo>`),
  que serve para qualquer outro serviço de containers.

Arquivos: [`render.yaml`](../render.yaml) (o serviço no Render), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
(CI/CD) e [`Dockerfile`](../Dockerfile) (a imagem).

## Por que Render e não Vercel

A Vercel roda Python como funções *serverless*: cada requisição pode cair numa instância nova. O Em Raízes guarda os
comandos, o voo e o progresso do robô **na memória de um processo** e atualiza a chuva numa thread em segundo plano;
numa função serverless isso se perde entre uma requisição e outra. O Render roda o container como um processo
contínuo, que é o que o app precisa.

## Passo a passo (uma vez só)

### 1. Código no GitHub

Crie um repositório vazio no GitHub e envie o projeto (o `.env` fica de fora, está no `.gitignore`):

```bash
git remote add origin https://github.com/<usuario>/em-raizes.git
```

```bash
git push -u origin main
```

O CI roda sozinho. Enquanto o deploy não estiver configurado, o job "Deploy (Render)" só deixa um aviso e o CI fica
verde.

### 2. Gerar a chave das notificações (opcional)

Sem ela o app funciona, só as notificações no celular ficam desligadas. Com o ambiente do projeto ativado:

```bash
python -c "from em_raizes.operacoes.notificacoes import gerar_chave_privada as g; print(g())"
```

Guarde o valor para o próximo passo. Não coloque no Git.

### 3. Criar o serviço no Render

1. Entre em <https://render.com> com a conta do GitHub.
2. **New → Blueprint** e escolha o repositório. O Render lê o `render.yaml` e mostra o serviço `em-raizes`.
3. Preencha os valores que ele pedir:

   | Variável | Valor |
   |---|---|
   | `EM_RAIZES_ADMIN_SENHA` | senha forte do administrador (o site é público) |
   | `OPENROUTER_API_KEY` | a chave do OpenRouter (conta gratuita basta) |
   | `EM_RAIZES_VAPID_PRIVADA` | a chave do passo 2 (ou deixe vazio) |
   | `EM_RAIZES_VAPID_CONTATO` | `mailto:` + um e-mail de contato (ex.: `mailto:equipe@exemplo.com`) |

   `EM_RAIZES_SEGREDO_JWT` é gerado pelo próprio Render; os modelos gratuitos e o modo produção já vêm no arquivo.
4. **Apply**. O primeiro deploy começa na hora (o build leva alguns minutos). O endereço fica parecido com
   `https://em-raizes.onrender.com` (o Render pode acrescentar um sufixo se o nome já existir).
5. Abra o endereço e entre com `admin` e a senha que você definiu.

### 4. Ligar o deploy automático (CD)

1. No Render: serviço `em-raizes` → **Settings** → **Deploy Hook** → copie a URL (ela é um segredo).
2. No GitHub: repositório → **Settings → Secrets and variables → Actions**:
   - aba **Secrets** → *New repository secret*: nome `RENDER_DEPLOY_HOOK_URL`, valor = a URL do passo anterior;
   - aba **Variables** → *New repository variable*: nome `APP_URL`, valor = o endereço do site (ex.:
     `https://em-raizes.onrender.com`).
3. Faça um push na `main` (ou rode o workflow de novo em **Actions**). O job "Deploy (Render)" deve terminar com
   `No ar: <commit>` e `ok: Em Raízes ...`.

O `render.yaml` usa `autoDeployTrigger: "off"`: o Render não publica sozinho a cada commit; quem publica é o CI, só
depois dos testes, e sempre o commit que foi testado (`?ref=<commit>`).

## Bom saber

- **Plano gratuito do Render:** o serviço "dorme" depois de um tempo sem acesso e acorda na próxima visita (a primeira
  resposta demora). Como o estado fica na memória, ao acordar o app recomeça: voo inicial e histórico vazio. Para um
  MVP de demonstração isso basta; o próximo passo seria um banco de dados. Confira os limites atuais do plano no site do
  Render.
- **Cota da IA:** o site, o chat de terminal e o notebook usam a mesma conta do OpenRouter (50 chamadas gratuitas por
  dia). Quando acaba, o Guardião responde em modo offline até as 21h (horário de Brasília).
- **Conferir o que está no ar:** `https://<seu-site>/api/saude` mostra a versão e o commit em execução.
- **Trocar de serviço:** a imagem publicada no GHCR (tag `v*`) roda em Railway, Fly.io, Google Cloud Run ou Azure
  Container Apps com as mesmas variáveis. Basta trocar o passo de deploy no workflow.
- **Segurança:** só há um usuário (admin). Use senha forte, não coloque dados reais de moradores e nunca publique o
  `.env`. Se a URL do Deploy Hook vazar, gere outra no Render (**Regenerate Hook**) e atualize o secret.
