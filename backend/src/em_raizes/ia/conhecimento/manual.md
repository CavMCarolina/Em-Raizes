# Manual do app do administrador

Este manual é a base de conhecimento do Guardião, o chat de IA do aplicativo.
Cada seção abaixo vira um "trecho" que o Guardião pode consultar para responder.

## O que é o Em Raízes (o app)

O Em Raízes é o aplicativo do ADMINISTRADOR do projeto de prevenção de deslizamentos em morros de comunidades.
O nome vem das raízes do capim-vetiver, que firmam o morro.
Por ele o administrador acompanha o morro e controla a frota: o drone de mapeamento com IA e o robô
jardineiro que planta capim-vetiver, rega mudas e inspeciona fissuras. Nesta primeira versão (MVP) o drone,
o robô, os sensores e a visão computacional são SIMULADOS: os dados são realistas, mas fictícios.
Os moradores ainda não usam o app.

## Primeiros passos: entrar no app

1. Abra o endereço do app no celular ou no computador (em desenvolvimento: http://localhost:5173).
2. Entre com o usuário e a senha de administrador (definidos no servidor em EM_RAIZES_ADMIN_USUARIO e EM_RAIZES_ADMIN_SENHA).
3. Você cai na tela Início. A barra colorida no topo mostra o nível de alerta atual.
4. Use a barra de baixo para trocar de tela: Início, Mapa, Operações, Alertas e Guardião.
No celular dá para instalar o app na tela inicial: no navegador, toque em "Adicionar à tela inicial".

## Tela Início: frota e ações

A tela Início mostra a frota (drone DRN-01 e robô ROB-01) com status (na base, em missão, parado),
bateria e o progresso da missão atual. Logo abaixo ficam os botões de ação: Enviar drone, Plantar capim,
Irrigar mudas, Inspecionar fissuras, Recolher robô e Parada de emergência. Quando um botão está bloqueado,
o motivo aparece escrito nele (por exemplo "Robô recolhido: Alerta" ou "Bateria baixa").
Mais abaixo: Ações sugeridas, Clima e último voo, Trabalho do robô e a ferramenta de Simulação.

## Como enviar o drone

Toque em "Enviar drone" na tela Início. O drone faz um voo de mapeamento (cerca de 12 segundos na simulação)
e, ao terminar, o mapa, o risco, os alertas e as missões do robô são recalculados com os dados novos.
O drone precisa estar na base e com pelo menos 30% de bateria; ele recarrega sozinho na base.
O drone pode voar mesmo com alerta ativo, porque o monitoramento é ainda mais importante na chuva.
Envie o drone sempre que o clima mudar ou depois de plantar/irrigar, para medir o efeito.

## Como mandar o robô plantar capim

Toque em "Plantar capim". O sistema escolhe até 8 células prioritárias (solo exposto, inclinação e risco)
e o robô planta capim-vetiver em linhas de nível. Para escolher o lugar, vá em Mapa, toque na célula e use
"Plantar aqui". O robô não planta em células com casas, em rocha, com mais de 35° de inclinação
(fica para a equipe técnica) ou que já têm vegetação suficiente; essas células aparecem como "ignoradas"
com o motivo, na tela Operações. O efeito na vegetação só aparece no próximo voo do drone.

## Irrigação: quando o sistema manda regar

O botão "Irrigar mudas" só rega células onde TODAS as condições valem: umidade do solo abaixo de 18%
(a meta é chegar a 25%), sem casas, risco baixo ou moderado e sem chuva prevista (menos de 10 mm em 24 h).
Uma encosta encharcada ou com risco alto NUNCA é irrigada, porque água a mais aumenta o risco de deslizamento.
Por isso, em dias de chuva o robô não encontra células para irrigar e o comando é recusado com o código
sem_alvos_validos. A nova umidade aparece no próximo voo do drone.

## Inspeção de fissuras

O botão "Inspecionar fissuras" manda o robô conferir de perto as fissuras que a visão computacional detectou
em áreas sem casas. Cada fissura volta como "confirmada" ou "descartada" (falso positivo) e o próximo voo
já usa esse resultado. Fissuras em áreas com casas não são inspecionadas pelo robô: elas devem ser
encaminhadas para a Defesa Civil.

## Recolher robô e parada de emergência

"Recolher robô" cancela a missão atual do robô e o traz de volta à base (pede confirmação).
"Parada de emergência" cancela TODAS as missões em andamento e bloqueia o drone e o robô; enquanto ela estiver
ativa qualquer comando é recusado com o código frota_parada. Para voltar a operar, toque em "Liberar frota".
Com nível Alerta ou Alerta máximo o robô é recolhido automaticamente por segurança.

## Ações sugeridas

O cartão "Ações sugeridas" lista o que o sistema recomenda fazer agora, com prioridade (alta, média, baixa)
e o motivo. Exemplos: enviar o drone porque o clima mudou depois do último voo; inspecionar fissuras;
plantar nas células prioritárias; irrigar mudas em solo seco. O botão "Executar" de cada sugestão envia o
comando correspondente.

## Chuva real (Cemaden e Open-Meteo)

Por padrão o app usa a chuva REAL de Petrópolis/RJ, cidade com histórico grave de deslizamentos.
A chuva acumulada vem dos pluviômetros automáticos do Cemaden (dados abertos): o app usa só os pluviômetros que
mandaram dado nas últimas 6 horas e o percentil 75 do acumulado de 72 horas, para ser cauteloso sem depender de um
sensor isolado. A previsão das próximas 24 horas vem do Open-Meteo. A leitura é atualizada a cada 10 minutos.
O cartão "Clima e último voo" mostra a fonte e o horário da última leitura. Se a chuva mudar 10 mm ou mais desde o
último voo, aparece a sugestão de enviar o drone, e se a chuva piorar de faixa sai um evento e uma notificação.
Sem internet, o app mantém a última leitura válida; se nunca conseguiu ler, começa com a chuva simulada.
Para usar outra cidade ou um pluviômetro específico, ajuste EM_RAIZES_CHUVA_CIDADE, EM_RAIZES_CHUVA_UF,
EM_RAIZES_CHUVA_IBGE, EM_RAIZES_CHUVA_LAT, EM_RAIZES_CHUVA_LON e EM_RAIZES_CHUVA_ESTACAO no servidor.
O drone, o morro e as casas continuam simulados: só a chuva é real.

## Clima: trocar entre chuva real e simulada

No fim da tela Início, abra "Clima: chuva real ou simulada", escolha a opção e toque em "Aplicar".
"Chuva real" volta para os pluviômetros. Os cenários simulados servem para testar o app em qualquer tempo:
seco = 4 mm em 72 h; moderada = 45 mm e 25 mm previstos; forte = 110 mm e 60 mm previstos;
extrema = 190 mm e 120 mm previstos. O mapa não muda na hora: aparece o aviso de mapa desatualizado e a sugestão
de enviar o drone.

## Notificações no celular

O cartão "Notificações no celular", na tela Início, ativa os avisos neste aparelho: toque em "Ativar notificações"
e permita no navegador. Depois use "Enviar teste" para conferir. Os avisos chegam mesmo com o app fechado quando:
o nível de alerta muda, a chuva real piora de faixa, alguém aciona a parada de emergência, o robô confirma uma
fissura ou uma foto analisada pela IA mostra risco alto ou crítico. Tocar no aviso abre o app na tela certa.
No Android funciona no Chrome e no Edge. No iPhone (iOS 16.4 ou mais novo) é preciso primeiro adicionar o app
à tela inicial (Compartilhar, Adicionar à Tela de Início) e abrir por lá.

## Analisar foto com IA

Tire ou escolha uma foto de encosta, trinca, muro ou terreno e a IA faz uma triagem visual: aponta os sinais
que aparecem (trinca no solo ou em parede, erosão, solo exposto, água ou vazamento, muro, poste ou árvore
inclinados, degrau no terreno, entulho), dá um risco (baixo, moderado, alto, crítico ou indeterminado) e diz o que
fazer. Há dois caminhos: o botão de câmera ao lado da caixa de texto do Guardião, ou "Analisar foto" no detalhe de
uma célula do mapa, que já leva o código da célula. O app reduz a foto antes de enviar. Se o risco for alto ou
crítico, a primeira recomendação é acionar a Defesa Civil (199), sai um evento e uma notificação.
A análise precisa da IA online (chave do OpenRouter) e não substitui a vistoria. A foto vai para o provedor de IA:
evite fotografar pessoas, rostos e placas.

## Mapa: como ler as cores

A tela Mapa mostra o morro em células de 10 m x 10 m; a parte de cima é o topo e a de baixo é a base (rua).
Cores do risco: verde = baixo (0 a 29), amarelo = moderado (30 a 54), laranja = alto (55 a 74),
vermelho = crítico (75 a 100). Pontos pretos são casas, o quadrado roxo marca casas a evacuar ou preparar,
o X vermelho marca fissuras e os ícones mostram onde estão o drone e o robô.
Camadas: Risco agora, Risco 24 h, Umidade, Vegetação e Foto do drone (imagem aérea simulada).
Toque numa célula para ver os dados, os pontos de cada fator e os botões "Plantar aqui", "Irrigar aqui",
"Inspecionar" e "Explicar com IA". Cada célula tem um código como L05C12 (linha 5, coluna 12) e um setor.

## Como o índice de risco é calculado

O índice vai de 0 a 100 e soma seis fatores com pesos: declividade (28%), saturação do solo (22%),
chuva acumulada em 72 h (18%), falta de vegetação (12%), tipo de solo (10%; aterro e solo arenoso pesam mais,
rocha pesa menos) e sinais visíveis (10%; fissuras, erosão e vazamentos). Terreno quase plano tem o risco
reduzido. Os pesos são ilustrativos e precisariam ser calibrados com dados reais e validados por geólogos.

## Previsão de 24 horas

O sistema estima o risco de amanhã somando a chuva prevista: a umidade do solo sobe e a chuva acumulada muda.
A camada "Risco 24 h" do mapa mostra quais células devem piorar. É isso que permite avisar as pessoas ANTES
do deslizamento.

## Níveis de alerta e evacuação

- Normal: nenhum trecho com risco alto. Robô liberado.
- Atenção: há trechos com risco alto ou chuva relevante prevista, mas sem casas diretamente expostas.
- Alerta: casas podem entrar em risco crítico nas próximas 24 h. Preparar evacuação. Robô recolhido.
- Alerta máximo — evacuar: há casas em risco crítico agora ou até 2 células morro abaixo de um trecho crítico.
A tela Alertas lista as casas a evacuar, estima as pessoas (2,8 moradores por casa, média do Censo 2022)
e o ponto de apoio simulado é a Escola Municipal na base do morro.

## Tela Operações: comandos e eventos

A aba "Comandos" mostra o histórico de tudo o que foi pedido ao drone e ao robô: código (CMD-0001),
tipo, status (em execução, concluído, recusado, cancelado), origem (admin ou sistema), horário e
resultado. Toque num comando para ver as células, as que ficaram de fora e o motivo, e o código de recusa.
A aba "Eventos" é o diário da central: comandos, mudanças de clima, mudança do nível de alerta,
fissuras confirmadas e paradas de emergência.

## Tela Alertas: SMS e plano de ação

A tela Alertas mostra o nível, as casas e pessoas em risco, a chuva dos últimos 7 dias com a previsão,
a lista de casas a evacuar e dois botões de IA: "Gerar SMS de alerta" (no máximo 160 caracteres,
validado antes de mostrar) e "Gerar plano de ação" (lista de ações em JSON validado).
O MVP não envia SMS de verdade.

## Por que capim-vetiver

O capim-vetiver é usado em bioengenharia de encostas porque tem raízes que descem na vertical por 2 a 3 metros
(às vezes mais), formando um "grampo vivo" que segura o solo. Aguenta seca e encharcamento, e as variedades
usadas em contenção são plantadas por mudas e praticamente não se espalham por sementes. É plantado em linhas
que seguem as curvas de nível, com mudas a cada 15 cm. Importante: a vegetação reduz erosão e deslizamentos
rasos, mas NÃO substitui obras de contenção e drenagem feitas por engenheiros nem a Defesa Civil.

## Visão computacional (simulada)

A camada "Foto do drone" mostra uma imagem aérea sintética. A IA de visão (simulada) detecta fissuras,
vazamentos de água ou esgoto e entulho/aterro e classifica o tipo de solo com uma confiança.
Ela erra de propósito em cerca de 12% das classificações, para mostrar que a visão computacional precisa
de conferência humana; por isso existe a inspeção de fissuras pelo robô.

## Guardião: o chat de IA

O Guardião responde dúvidas sobre como usar o app, explica o mapeamento e o estado da frota, os códigos de
recusa e os erros comuns. Ele usa IA generativa pelo OpenRouter e recebe, a cada pergunta, trechos deste manual
e um resumo da situação (voo, alerta, frota, últimos comandos e ações sugeridas). Sem chave de API funciona em
"modo offline", com regras simples e trechos do manual. O Guardião não executa comandos: só explica.
Ele não substitui a Defesa Civil: em situação de perigo, ligue 199.

## Configurar a chave do OpenRouter

1. Crie uma conta em openrouter.ai e gere uma chave em openrouter.ai/keys.
2. Copie o arquivo .env.example para .env na raiz do projeto.
3. Preencha OPENROUTER_API_KEY com a chave. O app usa só modelos gratuitos (nome terminado em ":free"), então a
   conta não precisa de créditos. Para trocar o modelo, mude OPENROUTER_MODEL e mantenha um ":free".
4. Reinicie o servidor. No Guardião deve aparecer "IA online" com o nome do modelo.
Nunca publique o arquivo .env (ele está no .gitignore).

## Erros comuns e soluções

### Erro no login: usuário ou senha incorretos
Confira EM_RAIZES_ADMIN_USUARIO e EM_RAIZES_ADMIN_SENHA no .env do servidor. Se aparecer "login desativado",
a senha não foi definida: preencha EM_RAIZES_ADMIN_SENHA e reinicie o servidor.

### Sessão expirada ou voltou para a tela de login
O login vale 12 horas (EM_RAIZES_MINUTOS_TOKEN). Reiniciar o servidor sem EM_RAIZES_SEGREDO_JWT também derruba as
sessões. Entre de novo.

### Sem conexão com o servidor
O app não está alcançando a API. Confira se o backend está rodando (porta 8000) e a internet do celular.

### Recusa alerta_ativo: robô recolhido por segurança
Com nível Alerta ou Alerta máximo o robô não trabalha. Envie o drone para atualizar o mapa; quando o nível
cair para Atenção ou Normal, o robô é liberado.

### Recusa dispositivo_ocupado
O drone ou o robô já está em missão. Espere terminar (veja o progresso na tela Início) ou recolha o robô.

### Recusa bateria_baixa
O drone precisa de 30% e o robô de 20% de bateria. Eles recarregam sozinhos na base em poucos segundos na simulação.

### Recusa frota_parada
A parada de emergência está ativa. Toque em "Liberar frota" na tela Início.

### Recusa sem_alvos_validos
Nenhuma célula atende às regras da missão (por exemplo: irrigar com chuva prevista, plantar em área com casas).
Veja em Operações as células ignoradas e o motivo de cada uma.

### Erro 401 da IA: chave do OpenRouter recusada
A chave da IA está errada, foi apagada ou tem espaços sobrando. Gere outra em openrouter.ai/keys.
Enquanto isso o Guardião responde em modo offline.

### Erro 402: sem créditos
O modelo configurado é pago e a conta do OpenRouter está sem saldo. Volte para um modelo gratuito (que termina
em ":free") em OPENROUTER_MODEL.

### Erro 429: muitas requisições
O limite de uso da IA gratuita foi atingido: 20 perguntas por minuto e 50 por dia na conta do OpenRouter (o
contador zera às 21h de Brasília). O sistema já espera cerca de 3 segundos entre chamadas, tenta de novo com espera
crescente e troca para o modelo de reserva. Se o limite do dia acabou, o Guardião responde em modo offline até o
dia seguinte.

### Erro: modelo inválido, timeout ou sem conexão com a IA
Confira o nome do modelo em OPENROUTER_MODEL (lista em openrouter.ai/models) e a internet do servidor.
O sistema tenta os modelos de OPENROUTER_FALLBACK_MODELS e, se nada funcionar, responde em modo offline.

### Erro: "npm não é reconhecido como comando"
O Node.js não está instalado ou não está no PATH. Instale o Node.js 22 ou mais novo e abra um terminal novo.

### Erro: ModuleNotFoundError: No module named 'em_raizes'
O backend não foi instalado no ambiente virtual. Na raiz do projeto rode pip install -r requirements.txt
(instala o pacote em modo editável) com o .venv ativado.

### Erro: porta 8000 ou 5173 já está em uso
Outro servidor está aberto. Feche-o ou mude a porta (uvicorn --port 8001; para o Vite, ajuste vite.config.ts).

### Erro: tela em branco ou desatualizada
Recarregue a página. Se você instalou o app no celular, feche e abra de novo para pegar a versão nova.

### Notificações bloqueadas ou "o navegador recusou a inscrição"
A permissão foi negada ou o navegador não tem serviço de push (navegadores embutidos, modo anônimo).
Libere as notificações nas configurações do site, ou use o Chrome ou o Edge no celular, ou o app instalado
na tela inicial. No iPhone, só funciona com o app adicionado à tela inicial.

### Análise de foto: "precisa da IA online"
O servidor está sem chave do OpenRouter. Configure OPENROUTER_API_KEY e reinicie. Fotos acima de 4 MB
ou que não sejam JPG, PNG ou WEBP também são recusadas.

### Recusa chuva_indisponivel
Não foi possível ler os pluviômetros do Cemaden ou a previsão naquele momento. Tente de novo em alguns minutos;
enquanto isso, use um cenário simulado.

## Sinais de perigo no morro

Procure a Defesa Civil se notar: trincas novas no chão ou nas paredes, portas e janelas que começam a emperrar,
muros, postes ou árvores inclinando, água barrenta descendo ou minando do chão, estalos ou barulho de terra,
degraus ou "barrigas" que aparecem no terreno. Durante chuva forte, se notar qualquer um desses sinais,
saia de casa e vá para um local seguro antes de ligar.

## Limitações do MVP

- Drone, robô, sensores e visão computacional do drone são simulados; o morro é fictício. A chuva é real.
- A chuva real é da cidade (percentil 75 dos pluviômetros), não do ponto exato do morro, e a previsão é de modelo.
- A análise de foto é uma triagem visual da IA: pode errar e não substitui vistoria.
- O índice de risco é uma fórmula explicável com pesos ilustrativos, não um modelo validado.
- Os dados ficam na memória do servidor: reiniciar o servidor apaga o histórico de comandos.
- O chat pode errar; respostas da IA precisam de conferência humana.
- O app não envia SMS de verdade e não aciona a Defesa Civil.

## Emergência: telefones

Defesa Civil: 199. Bombeiros: 193. SAMU: 192.
Para receber alertas oficiais da Defesa Civil por SMS, envie o seu CEP para 40199.
