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
| Rodava manualmente | 11 containers no Docker Compose |
| Gráficos 2D | Gráficos 2D + duas cenas 3D |

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
- **IA (etapa 2):** scikit-learn + Ollama local

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
                                                    └─ f1.dlx     → q.dead (DLQ)
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
| Usuários (etapa 2) | Consulta do histórico em Flux |

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

**Visual:** GIF da câmera de TV acompanhando o carro.

---

## 16. Tela 2: Garagem (gêmeo digital)

**Conteúdo**
- Carro procedural grande no centro. Arraste para girar, use a roda do mouse para zoom e passe o mouse sobre as peças para ver o valor ao vivo.
- **Clique numa peça** abre um painel com a última leitura, o gráfico de 60 s, a saúde e os botões de comando.
- Cores por estado: normal, atenção, crítico e sem dados. Elas vêm da faixa cadastrada do sensor.
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
3. **IA:** laboratório → treino → inferência → previsões pelo RabbitMQ → Insights e 3D. *(etapa 2)*

**Visual:** três setas coloridas sobre o diagrama do slide 5.

---

## 18. Segurança

**Conteúdo**
- Segredos gerados por `scripts/gen_secrets.py` e fora do Git. Não há senha padrão.
- Mosquitto sem anônimo e com ACL; RabbitMQ com usuário por serviço e sem guest.
- WebSocket com ticket de uso único.
- Containers sem root; **só a porta 8080** é publicada.
- UIs de administração (RabbitMQ, InfluxDB, pgAdmin) presas em **127.0.0.1**, com os links na página Sistemas.
- Auditoria de comandos no PostgreSQL.
- *(etapa 2)* JWT com 3 papéis (visualizador, operador, administrador), bcrypt e limite de tentativas de login.

---

## 19. Docker Compose

**Conteúdo**
- `python scripts/gen_secrets.py` e depois `docker compose up --build`: **um comando** sobe tudo.
- 11 serviços:
  - infra: mosquitto, rabbitmq, influxdb, postgres e pgadmin;
  - aplicação: simulator, gateway, influx-writer, rules-engine, api e frontend.
- **Healthcheck** em todos (inclusive os workers, por arquivo de heartbeat) e `depends_on: service_healthy` para garantir a ordem de subida.
- Uma imagem Python compartilhada (`python.Dockerfile`) e o frontend com build do Vite servido pelo nginx, que faz proxy de `/api` e `/ws`.

**Visual:** print do `docker compose ps` com tudo *healthy*.

---

## 20. Inteligência artificial (etapa 2)

**Conteúdo**
- **Laboratório de Dados:** gerar mais de 1 milhão de leituras sintéticas com numpy em blocos.
  - Configurável: equipamentos, dias, % de falhas e modos de falha, ruído, faltantes, outliers e semente.
- **2 modelos de regressão** (scikit-learn):
  - **vida útil restante (RUL)** da PU;
  - **índice de saúde** de 0 a 100.
  - Divisão por equipamento; MAE, RMSE e R²; comparação com uma base que prevê sempre a média.
- **Inferência ao vivo** consumindo `q.inference`, publicando previsões e alertas com histerese.
- **Assistente com LLM local** (Ollama, `llama3.2:3b` em CPU), com o resumo dos dados no prompt e resposta em streaming.

**Fala:** "A infraestrutura (filas, tabela de usuários, menu) já está pronta para receber a IA."

---

## 21. Desafios e decisões técnicas

**Conteúdo**
- **Física da pista:** a curva mínima saía a 183 km/h; foi corrigida com um modelo de aderência que depende da velocidade.
- **Conflito de tipos no InfluxDB:** o campo `value` dos eventos chegava às vezes como texto e às vezes como número. Os lotes iam para a DLQ, e a correção foi tipar os campos de evento.
- **Alertas órfãos** depois de reiniciar o rules-engine: agora os alertas abertos são fechados na subida.
- **Desempenho 3D:** store não reativo, InstancedMesh e bloom calibrado.
- **Separação MQTT × AMQP:** cada broker com um papel claro.

---

## 22. Roteiro da demonstração ao vivo

1. `docker compose up` com os containers saudáveis
2. MQTT ao vivo com `mosquitto_sub` (e a recusa sem senha)
3. Swagger em `/api/docs`
4. Mensageria: parar e voltar o `influx-writer`
5. Histórico (InfluxDB), Dispositivos, regras e auditoria (PostgreSQL)
6. Corrida ao vivo; parar o simulador mostra "SEM DADOS"
7. Regra automática: PUSH → motor > 118 °C → resfriamento liga
8. Web → IoT: BOX com troca de composto
9. Falha injetada na PU: vibração, cor e alertas mudando

---

## 23. Encerramento

**Conteúdo**
- O pipeline IoT do 1º bimestre virou uma plataforma AIoT com mensageria, dois bancos, tempo real e gêmeo digital 3D.
- Próximos passos: IA preditiva, LLM local e login com papéis.
- Perguntas?

**Visual:** a Garagem com o carro girando lentamente.
