# PITWALL: roteiro de slides

Base para montar os slides da apresentação de 16/11/2026. Cada seção `##` é um slide e traz:
- **Conteúdo:** o que vai no slide.
- **Visual:** a imagem ou o diagrama sugerido.
- **Fala:** o que dizer.

A ordem segue o roteiro de demonstração do documento do trabalho.

---

## 1. Capa: PITWALL

**Conteúdo**
- PITWALL: telemetria de Fórmula 1 com gêmeo digital 3D
- Projeto AIoT do 2º bimestre: Web + IoT + IA
- Nomes dos integrantes · UNIFACEF · 16/11/2026

**Visual:** print da tela Garagem (o carro grande no centro, com os cards).

**Fala:** "O muro dos boxes de uma equipe de F1 enxergando o carro em tempo real."

---

## 2. O problema

**Conteúdo**
- No 1º bimestre: monitor de ambiente (temperatura, umidade, luz), Arduino → MQTT → InfluxDB → dashboard.
- No 2º bimestre: o mesmo pipeline aplicado a um domínio mais rico, a **estratégia de uma equipe de F1**.
- Perguntas que a equipe precisa responder a cada volta:
  - Quantas voltas o pneu aguenta antes do *cliff*?
  - O combustível chega até o fim?
  - O motor está superaquecendo? A Power Unit está se desgastando?
  - Quando parar no box?

**Visual:** antes e depois, com o dashboard do 1º bimestre ao lado da tela Corrida.

---

## 3. Evolução sobre o 1º bimestre

**Conteúdo**

| 1º bimestre | PITWALL |
|---|---|
| Arduino + serial | Simulador Python (6 carros, 10 Hz) |
| `Broker` com paho | `pitwall_common/mqtt.py`: paho v2, autenticação, reconexão |
| `on_message` → InfluxDB | Serviço `influx-writer` com lotes e DLQ |
| Polling em `/datas` | WebSocket com ticket de uso único |
| Só InfluxDB | InfluxDB + PostgreSQL |
| Rodava manualmente | 14 containers no Docker Compose |
| Gráficos 2D | Gráficos 2D + duas cenas 3D |
| Sem IA | Dados sintéticos, 2 regressões ao vivo e LLM local |

**Fala:** "Nada foi jogado fora: cada peça do 1º bimestre virou um serviço."

---

## 4. Stack utilizada

**Conteúdo**
- **Frontend:** Vue 3 + TypeScript + Vite, Three.js, Chart.js
- **Backend:** Python + FastAPI (REST + WebSocket)
- **IoT:** MQTT + Mosquitto, com o simulador em Python e numpy
- **Mensageria:** RabbitMQ (AMQP)
- **Dados:** PostgreSQL e InfluxDB 2.7
- **Infra:** Docker + Docker Compose, nginx sem root
- **IA:** scikit-learn (RandomForest) + numpy
- **LLM local:** Ollama com `qwen2.5:1.5b` (gratuito, roda em CPU)

**Visual:** grade de logos por camada.

---

## 5. Arquitetura geral

**Conteúdo**
```
Simulador ─MQTT─▶ Mosquitto ─▶ Gateway ─AMQP─▶ RabbitMQ (exchange topic "f1")
                     ▲                              ├─ q.influx   → influx-writer → InfluxDB
                     │                              ├─ q.rules    → rules-engine  → PostgreSQL
                     └──── MQTT ◀── Gateway ◀───────├─ q.commands (volta ao carro)
                                                    ├─ q.ws       → FastAPI → WebSocket → Vue + Three.js
                                                    ├─ q.inference → inference → prediction.<id> + alertas
                                                    ├─ q.jobs.*   → ml-worker (gera dados e treina)
                                                    └─ f1.dlx     → q.dead (DLQ)
FastAPI ─▶ Ollama (LLM local) para o Assistente
```
- **Todo dado passa pelo RabbitMQ.**
- O Mosquitto fica na **borda** (dispositivo ⇄ aplicação); o RabbitMQ é o **barramento interno**.

**Visual:** redesenhar o diagrama com ícones. É o slide mais importante para as perguntas da banca.

---

## 6. O dispositivo: simulador de F1

**Conteúdo**
- 6 carros (2 da equipe + 4 rivais), cada um publicando a 10 Hz em `f1/<carro>/telemetry`.
- Circuito original de cerca de 5 km, feito com spline Catmull-Rom. O perfil de velocidade vem da curvatura, e há zonas de DRS e pit lane.
- Física simplificada:
  - o desgaste do pneu depende da carga e do composto (SOFT, MEDIUM ou HARD) e tem *cliff*;
  - o combustível cai conforme o modo do motor;
  - o ERS carrega na frenagem;
  - a temperatura do motor sobe no PUSH.
- O mesmo JSON da pista vai para o frontend, então existe uma só fonte da verdade.

**Visual:** print da pista vista de cima.

---

## 7. Sensores

**Conteúdo**
- **Carro:** velocidade, RPM, marcha, acelerador e freio, combustível (kg) e bateria ERS (%).
- **Power Unit:** temperatura do motor, temperatura e pressão do óleo e vibração.
- **Por roda (FL, FR, RL, RR):** temperatura, desgaste e pressão do pneu e temperatura do freio.
- **Posição:** volta, distância na volta, setor e gaps.
- Total: **210 dispositivos** cadastrados no PostgreSQL, cada um com faixa normal e crítica.

**Visual:** carro explodido com as peças rotuladas (print da Garagem no modo raio-X).

---

## 8. Atuadores

**Conteúdo**
- **Automático, por regra:** resfriamento (lift-and-coast).
  - Motor acima de 118 °C por 5 leituras liga o resfriamento.
  - Abaixo de 108 °C por 20 leituras desliga. Essa histerese evita que ele fique ligando e desligando.
  - A regra fica na tabela `rules` e pode ser editada pela interface.
- **Pela Web:**
  - modo do motor (PUSH, STANDARD ou CONSERVE);
  - modo ERS (HARVEST, BALANCED ou OVERTAKE);
  - **chamada para o BOX** com troca de composto.
- O atuador **muda o estado no simulador e aparece nas leituras seguintes**. Exemplo: PUSH aumenta o RPM e o consumo; o BOX zera o desgaste.

**Visual:** GIF das aletas do radiador abrindo na Garagem.

---

## 9. Equipamento monitorado: Power Unit

**Conteúdo**
- Equipamento que se desgasta e pode falhar, pensado para a manutenção preditiva.
- **4 variáveis** mudam aos poucos com a degradação: vibração, temperatura do óleo, pressão do óleo e temperatura do motor.
- Falha injetável pela tela ("desgaste de rolamento"). A vibração sobe, a pressão cai, a peça vai de verde a âmbar e depois a vermelho, e por fim vem o DNF.
- O desgaste real fica **só dentro do simulador**. Esse rótulo nunca vai nas mensagens, para a IA não "colar".

**Visual:** gráfico de vibração subindo até o DNF.

---

## 10. MQTT + Mosquitto: a borda

**Conteúdo**
- Tópicos: `f1/<carro>/telemetry`, `f1/<carro>/event` e `f1/<carro>/cmd`.
- **Os dois sentidos:** o simulador publica a telemetria e assina os comandos.
- Sem acesso anônimo e com ACL por tópico:
  - `sim` publica telemetria e eventos e lê comandos;
  - `gateway` faz o inverso;
  - `monitor` só lê.
- O gateway faz a ponte MQTT ⇄ AMQP.

**Demonstração:** `mosquitto_sub` com usuário recebe os dados; sem usuário, a conexão é recusada.

---

## 11. RabbitMQ: o barramento interno

**Conteúdo**
- Exchange **topic** `f1`, com as routing keys:
  - `telemetry.<equipe>.car.<id>`
  - `event.<tipo>.<id>`
  - `command.<id>`
  - `alert.<id>`
- Filas e consumidores:
  - `q.influx` → gravação no InfluxDB
  - `q.rules` → regras de negócio
  - `q.ws` → entrega ao WebSocket
  - `q.commands` → volta ao dispositivo
  - `q.inference`, `q.jobs.generate` e `q.jobs.train` → IA e jobs demorados
- **DLQ:** `f1.dlx` → `q.dead`, com a mensagem preservada.
- Envelope JSON único: `{id, ts, type, device, source, payload}`.
- Um usuário por serviço, com o mínimo de permissões, e **sem o guest**.

**Visual:** tabela fila → consumidor → usuário.

---

## 12. Página Mensageria

**Conteúdo**
- Mostra ao vivo as mensagens em cada fila, as taxas de publicação e entrega, os consumidores, as últimas mensagens e a DLQ.
- O backend consulta a API de gerenciamento do RabbitMQ; **o navegador nunca fala com o broker**.
- **Demonstração:** `docker compose stop influx-writer` faz a fila `q.influx` crescer, e `start` faz ela esvaziar.

**Visual:** print da Mensageria com a fila cheia.

---

## 13. Dois bancos, dois papéis

**Conteúdo**

| PostgreSQL (relacional) | InfluxDB (séries temporais) |
|---|---|
| Dispositivos (210) e faixas normal e crítica | Measurement `telemetry`, a 10 Hz × 6 carros |
| Regras editáveis | Tags `car_id`, `team` e `tyre_compound` |
| Alertas (abertos e fechados) | Measurement `events` (pit, DNF, comandos) |
| Auditoria de comandos | Gravação em lotes, com falha indo para a DLQ |
| Jobs da IA (progresso) | Bucket `lab`: amostra dos dados sintéticos |
| Usuários (para o login) | Consulta do histórico em Flux |

- Página **Dispositivos**: CRUD com regras, alertas e auditoria.
- Página **Histórico**: consulta por carro, variável e janela, com Chart.js.

---

## 14. Tempo real: WebSocket

**Conteúdo**
- A API consome `q.ws` (aio-pika) e faz broadcast agrupado a cada 100 ms.
- Conexão com **ticket curto de uso único** (`POST /api/ws/ticket`), então nenhum token vai na URL.
- No frontend:
  - o store `live` fica fora da reatividade do Vue e é lido dentro do loop 3D;
  - o snapshot reativo a 4 Hz alimenta os cards.
- Sem dados por 2 s, a tela mostra o aviso **"SEM DADOS"** e a cena congela.

**Fala:** "Não redesenhamos a cena a cada mensagem: ela lê o store em cada quadro."

---

## 15. Tela 1: Corrida

**Conteúdo**
- O circuito em 3D com os 6 carros posicionados **somente** pela telemetria, interpolados entre as mensagens.
- Torre de tempos, HUD do carro selecionado e minimapa.
- Estratégia ao vivo: voltas até o cliff do pneu, combustível para N voltas e janela de pit.
- Três câmeras: aérea, perseguição e TV (teclas 1, 2 e 3).
- Árvores, postes e garagens feitos com **InstancedMesh**.
- **Ambiente reagindo a dados:** a garagem acende na cor da equipe quando o carro entra no pit; os postes ficam âmbar e piscam (bandeira amarela) com carro quebrado ou alerta crítico.

**Visual:** GIF da câmera de TV acompanhando o carro.

---

## 16. Tela 2: Garagem (gêmeo digital)

**Conteúdo**
- Carro procedural grande no centro. Arraste para girar, use a roda do mouse para zoom e passe o mouse sobre as peças para ver o valor ao vivo.
- **Clique numa peça** abre um painel com a última leitura, o gráfico de 60 s, a saúde e os botões de comando.
- Cores por estado: normal, atenção, crítico e sem dados. Elas vêm da faixa cadastrada do sensor **e da saúde prevista pela IA**.
- Cards ligados às peças por linhas-guia que seguem a projeção 3D → 2D a cada quadro, sem pontas soltas.
- Atuadores animados:
  - as aletas do radiador abrem e a luz traseira pisca no resfriamento;
  - a asa do DRS se move;
  - a PU **treme** conforme a vibração.
- Modo raio-X (PU, célula de combustível, ERS) e mapa térmico.

**Visual:** print grande da Garagem com o painel da PU aberto.

---

## 17. Os três fluxos obrigatórios

**Conteúdo**
1. **IoT → Web:** simulador → MQTT → gateway → RabbitMQ → influx-writer e API → WebSocket → 3D. ✅
2. **Web → IoT:** botão BOX → API → RabbitMQ → gateway → MQTT → simulador → o carro entra no pit e o desgaste volta a 0. ✅
3. **IA:** laboratório → treino → inferência → previsões pelo RabbitMQ → Insights e 3D. ✅

**Visual:** três setas coloridas sobre o diagrama do slide 5.

---

## 18. Segurança

**Conteúdo**
- Segredos gerados por `scripts/gen_secrets.py` e fora do Git. Não há senha padrão.
- Mosquitto sem anônimo e com ACL; RabbitMQ com usuário por serviço e sem guest.
- WebSocket com ticket de uso único.
- Containers sem root; **só a porta 8080** é publicada.
- UIs de administração (RabbitMQ, InfluxDB, pgAdmin) presas em **127.0.0.1**, com os links na página Sistemas.
- Auditoria no PostgreSQL de comandos, jobs da IA e perguntas ao assistente.
- LLM sem acesso aos bancos; a saída é tratada como texto não confiável (Markdown sem HTML) e há limite de 6 perguntas por minuto.
- Ainda não implementado: login JWT com 3 papéis, bcrypt e limite de tentativas.

---

## 19. Docker Compose

**Conteúdo**
- `python scripts/gen_secrets.py` e depois `docker compose up --build`: **um comando** sobe tudo.
- 14 serviços:
  - infra: mosquitto, rabbitmq, influxdb, postgres e pgadmin;
  - aplicação: simulator, gateway, influx-writer, rules-engine, api e frontend;
  - IA: ml-worker, inference e ollama (baixa e pré-carrega o modelo na subida).
- **Healthcheck** em todos (inclusive os workers, por arquivo de heartbeat) e `depends_on: service_healthy` para garantir a ordem de subida.
- Uma imagem Python compartilhada (`python.Dockerfile`) e o frontend com build do Vite servido pelo nginx, que faz proxy de `/api` e `/ws`.

**Visual:** print do `docker compose ps` com tudo *healthy*.

---

## 20. Laboratório de Dados: dados sintéticos massivos

**Conteúdo**
- Por que sintético? Uma PU real leva meses para falhar; simulamos a vida inteira de 100 PUs.
- Configurável pela tela: equipamentos, dias, minutos entre leituras, % que falha, modos de falha (rolamento, superaquecimento, vazamento de óleo, deriva de sensor), ruído, % faltantes, % outliers e semente.
- **Mesma física do simulador ao vivo**: o desgaste acelera sozinho (`dw/dt = k·(0,4 + w)`) e mexe em vibração, óleo e temperatura.
- Qualidade: ruído, uma variação própria de cada máquina (sobreposição entre saudáveis e doentes) e ciclo diário e sazonal.
- **≈ 1,74 milhão de leituras em ~1 s** (numpy em blocos), com teto de 5 milhões.
- Roda em segundo plano: tela → API → `q.jobs.generate` → ml-worker, com o progresso ao vivo. Uma amostra vai para o bucket `lab` do InfluxDB.
- Rótulos de verdade (saúde e horas até falhar) **só no dataset**.

**Visual:** print do Laboratório com a barra de progresso.

---

## 21. Treino: 2 modelos de regressão

**Conteúdo**
- Algoritmo simples: `RandomForestRegressor` (scikit-learn), 60 árvores.
- Features: média, desvio e máximo das **últimas 30 leituras** (só o passado), calculadas por um único código no treino e na inferência.
- Divisão **por equipamento**: 70 PUs no treino, 15 na validação e 15 no teste.

| Modelo | MAE | R² | Base (média) R² |
|---|---|---|---|
| Índice de saúde (0–100) | 2,3 | **0,98** | ≈ 0 |
| Vida útil restante (h) | 19,7 h | **0,76** | ≈ 0 |

- O atributo mais importante é a **vibração média**, o que faz sentido para desgaste de rolamento.
- O treino roda em segundo plano (`q.jobs.train`) e o modelo novo entra em uso **sem reiniciar** o serviço.

**Visual:** print da página Treino (tabela, gráfico previsto × real, importância).

**Fala:** "O modelo só vale se vencer a base que chuta sempre a média, e os dois vencem com folga."

---

## 22. Insights em tempo real

**Conteúdo**
- O serviço `inference` consome `q.inference`, aplica os 2 modelos a cada segundo por carro e publica `prediction.<carro>` de volta no RabbitMQ.
- Alerta preditivo com **histerese**: 3 previsões seguidas abaixo de 50 disparam, 10 acima de 60 limpam. O alerta é gravado no PostgreSQL.
- Página **Insights**: saúde, vida útil, tendência e alertas por carro.
- As mesmas previsões pintam a PU na Garagem e na Corrida.
- Demonstração: falha de rolamento no PW16, com a saúde caindo de 84 a 0 em cerca de 3,5 min, o alerta preditivo e o DNF.

**Visual:** GIF do card do PW16 ficando vermelho.

---

## 23. Assistente com LLM local

**Conteúdo**
- **Ollama** no Docker Compose com o modelo gratuito **`qwen2.5:1.5b`** (cerca de 1 GB, roda em CPU, sem chave e sem nuvem).
- O modelo é baixado e **pré-carregado** quando o Compose sobe.
- O backend monta um **resumo pronto** (leituras, saúde, vida útil, alertas, métricas e arquitetura) e envia com a pergunta. O LLM nunca acessa os bancos.
- Resposta em **streaming**, palavra a palavra.
- Segurança: Markdown renderizado sem HTML, limite de perguntas por minuto e cada pergunta registrada na auditoria.

**Visual:** print do chat respondendo "qual carro está com a pior saúde?".

---

## 24. Desafios e decisões técnicas

**Conteúdo**
- **Física da pista:** a curva mínima saía a 183 km/h; foi corrigida com um modelo de aderência que depende da velocidade.
- **Conflito de tipos no InfluxDB:** o campo `value` dos eventos chegava às vezes como texto e às vezes como número. Os lotes iam para a DLQ, e a correção foi tipar os campos de evento.
- **Alertas órfãos** depois de reiniciar o rules-engine: agora os alertas abertos são fechados na subida.
- **Desempenho 3D:** store não reativo, InstancedMesh e bloom calibrado.
- **Separação MQTT × AMQP:** cada broker com um papel claro.
- **Vida útil difícil de prever:** a primeira versão tinha R² 0,18. Usar no laboratório a mesma lei de desgaste do simulador levou o R² a 0,76.
- **Jobs longos × RabbitMQ:** o treino roda numa thread para o worker continuar mandando heartbeat ao broker.

---

## 25. Roteiro da demonstração ao vivo

1. `docker compose up` com os containers saudáveis
2. MQTT ao vivo com `mosquitto_sub` (e a recusa sem senha)
3. Swagger em `/api/docs`
4. Mensageria: parar e voltar o `influx-writer`
5. Histórico (InfluxDB), Dispositivos, regras e auditoria (PostgreSQL)
6. Corrida ao vivo; parar o simulador mostra "SEM DADOS"
7. Regra automática: PUSH → motor > 118 °C → resfriamento liga
8. Web → IoT: BOX com troca de composto
9. Laboratório: gerar cerca de 1,7 milhão de leituras sintéticas
10. Treino: métricas contra a base, previsto × real e importância
11. Falha injetada na PU: saúde, vida útil e alerta mudando no Insights e no 3D
12. Assistente: perguntar sobre a falha ao LLM local

---

## 26. Encerramento

**Conteúdo**
- O pipeline IoT do 1º bimestre virou uma plataforma AIoT com mensageria, dois bancos, tempo real e gêmeo digital 3D.
- A IA prevê a quebra da Power Unit antes de ela acontecer, e o LLM local explica o que fazer.
- Próximos passos: login com papéis (JWT) e repositório no GitHub.
- Perguntas?

**Visual:** a Garagem com o carro girando lentamente.
