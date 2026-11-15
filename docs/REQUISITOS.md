# PITWALL: o que o documento pede e o que já existe

Conferência feita em 15/11/2026 contra o "Documento sem título.docx" (enunciado do 2º bimestre). A apresentação é em 16/11/2026.

Legenda: ✅ feito e testado · ⚠️ parcial · ❌ não existe ainda

## Resumo

| Critério de avaliação (1,0 cada) | Situação | O que falta |
|---|---|---|
| 1. Evolução, qualidade, segurança e GitHub com README | ⚠️ | Git/GitHub, JWT com 3 papéis, bcrypt, limite de login |
| 2. Sensores, atuadores e MQTT + Mosquitto | ✅ | Nada |
| 3. Regra automática e controle pela Web | ✅ | Nada |
| 4. RabbitMQ (exchange, filas, consumidores, DLQ, Mensageria) | ⚠️ | Consumidores de `q.inference`, `q.jobs.generate` e `q.jobs.train` |
| 5. PostgreSQL e InfluxDB | ✅ | Usar a tabela `users` (vem com o JWT) |
| 6. WebSocket, dashboard, gráficos e histórico | ✅ | Nada |
| 7. Interface 3D | ⚠️ | Cor pelos alertas da IA, saúde da IA no painel, 2 elementos do **ambiente** reagindo a dados |
| 8. Dados sintéticos e modelos de regressão | ❌ | Tudo: Laboratório, gerador, 2 modelos, página de Treino |
| 9. Insights de IA e LLM local | ❌ | Tudo: inferência, página Insights, Ollama, Assistente |
| 10. Docker Compose e apresentação completa | ⚠️ | Containers de IA e do LLM no Compose; roteiro completo |

Hoje cerca de **5 critérios estão completos e 3 estão parciais**. Os critérios 8 e 9 estão zerados, e os itens 11 (falha com saúde e RUL) e 12 (LLM) do roteiro de demonstração dependem deles.

---

## O que já está feito

### Stack obrigatória

| Camada | Tecnologia pedida | No PITWALL | |
|---|---|---|---|
| Frontend | Vue 3 ou React + TS + Vite | Vue 3 + TypeScript + Vite + vue-router | ✅ |
| 2D | Chart.js ou ECharts | Chart.js (histórico, sparklines, painel da peça) | ✅ |
| 3D | Three.js | Three.js 0.170 puro, carro e pista procedurais, bloom | ✅ |
| Backend | Python + FastAPI | FastAPI com REST + Swagger em `/api/docs` | ✅ |
| Tempo real | WebSocket | `/ws` com ticket de uso único, lotes a cada 100 ms | ✅ |
| IoT | MQTT + Mosquitto | Mosquitto sem anônimo, ACL por tópico | ✅ |
| Dispositivo | Simulador Python | 6 carros a 10 Hz, física com numpy | ✅ |
| Mensageria | RabbitMQ | Exchange topic `f1`, DLX, usuário por serviço | ✅ |
| IA | scikit-learn | — (não está no `requirements.txt`) | ❌ |
| LLM local | Ollama | — | ❌ |
| Relacional | PostgreSQL | Dispositivos, regras, alertas, auditoria, `users` | ✅ |
| Séries temporais | InfluxDB | Measurements `telemetry` e `events` | ✅ |
| Infra | Docker + Compose | 11 serviços com healthcheck | ✅ |
| Versionamento | Git + GitHub | A pasta **não é um repositório Git** | ❌ |

### Sensores, atuadores e equipamento

- ✅ **Mais de 3 sensores:** velocidade, RPM, marcha, acelerador e freio, motor, óleo (temperatura e pressão), vibração da PU, combustível, ERS e, em cada roda, temperatura, desgaste e pressão do pneu e temperatura do freio.
- ✅ **Atuador por regra:** resfriamento (lift-and-coast). Liga com motor > 118 °C em 5 leituras seguidas e desliga abaixo de 108 °C em 20 leituras, com histerese. A regra fica no Postgres e pode ser editada pela tela.
- ✅ **Atuadores pela Web:** modo do motor (PUSH, STANDARD, CONSERVE), modo ERS e chamada para o BOX com troca de composto. O estado muda e aparece nas leituras seguintes.
- ✅ **Equipamento monitorado:** a Power Unit. Vibração, temperatura do óleo, pressão do óleo e temperatura do motor (4 variáveis) mudam aos poucos com o desgaste. A falha de rolamento injetada pela tela leva ao DNF.
- ✅ **Rótulos de verdade fora das mensagens:** o desgaste real da PU (`_pu_wear`) fica só no estado interno do simulador.

### Fluxos obrigatórios

- ✅ **IoT → Web:** simulador → MQTT → gateway → RabbitMQ → influx-writer e API → WebSocket → tela.
- ✅ **Web → IoT:** botão → `POST /api/commands` → RabbitMQ `q.commands` → gateway → MQTT → simulador. O comando fica registrado na auditoria.
- ❌ **IA:** laboratório → treino → inferência → previsões pelo RabbitMQ → interface.

### RabbitMQ

- ✅ Exchange `f1` do tipo topic, com as routing keys `telemetry.<equipe>.car.<id>`, `event.<tipo>.<id>`, `command.<id>` e `alert.<id>`.
- ✅ Filas com consumidor: `q.influx` (influx-writer), `q.rules` (rules-engine), `q.ws` (API) e `q.commands` (gateway).
- ✅ DLQ: `f1.dlx` → `q.dead`, com a mensagem preservada. Mensagem inválida ou falha de gravação vai para lá.
- ✅ Envelope JSON único: `{id, ts, type, device, source, payload}`.
- ✅ Um usuário por serviço, com permissões mínimas, e sem o usuário `guest`.
- ✅ Página **Mensageria** ao vivo: filas, taxas, consumidores, últimas mensagens e DLQ. O backend consulta a API de gerenciamento; o navegador nunca fala com o broker.
- ✅ A demonstração do consumidor parado foi testada: `q.influx` cresce e depois esvazia.

### Bancos, dashboard e cadastro

- ✅ O InfluxDB guarda as leituras; o PostgreSQL guarda cadastro, regras, alertas e auditoria. Cada banco tem um papel claro.
- ✅ Página **Histórico**: consulta ao InfluxDB por carro, variável e janela, com Chart.js.
- ✅ Página **Dispositivos**: CRUD de carros, sensores, atuadores e equipamentos (210 dispositivos), com faixa normal e crítica, regras, alertas e auditoria.
- ✅ Dashboards ao vivo: torre de tempos, HUD, estratégia, cards da garagem e sparklines.

### Interface 3D

- ✅ A cena é movida **somente** pelo WebSocket. Não há ligação com o simulador.
- ✅ Se o simulador parar, o aviso "SEM DADOS" aparece em até 2 s e a cena congela.
- ✅ Cada peça tem o mesmo id do cadastro (`tyre_FL`, `pu`, `brake_RR`…), e a posição 3D fica só no frontend.
- ✅ Cores normal, atenção, crítico e sem dados pela faixa do sensor.
- ✅ Atuadores animados: aletas do radiador e luz traseira no resfriamento, asa móvel do DRS. A PU **treme** mais quanto maior a vibração.
- ✅ Clique numa peça abre o painel com a última leitura, o mini gráfico de 60 s e os comandos.
- ✅ As linhas-guia dos cards saem e chegam exatamente nas peças.
- ✅ Store fora da reatividade, lido no loop de animação, e InstancedMesh para árvores, postes e garagens.

### Segurança e infraestrutura

- ✅ `scripts/gen_secrets.py` gera o `.env` e o `definitions.json`, ambos no `.gitignore`. Não há senha padrão.
- ✅ Mosquitto sem anônimo, com ACL; RabbitMQ com usuário por serviço.
- ✅ WebSocket com ticket curto de uso único, sem token na URL.
- ✅ Containers sem root (`nginx-unprivileged` no frontend). Só a porta 8080 é publicada.
- ✅ UIs do RabbitMQ, InfluxDB e pgAdmin presas em `127.0.0.1`, com os links na página **Sistemas**.
- ✅ Healthchecks e `depends_on: service_healthy` em todos os serviços.
- ✅ A tabela de auditoria registra os comandos enviados.
- ✅ README com descrição, diagrama, como subir e roteiro de demonstração.

---

## O que falta (pendências)

### 1. Laboratório de Dados: gerador sintético massivo (critério 8)
- [ ] Página **Laboratório** (hoje desabilitada no menu).
- [ ] Parâmetros na tela:
  - número de equipamentos (PUs) e de sensores de cada tipo;
  - período simulado em dias;
  - percentual de PUs que vão falhar e os modos de falha: rolamento, superaquecimento, perda de pressão de óleo, deriva ou travamento de sensor;
  - ruído, percentual de leituras faltantes e de outliers;
  - semente aleatória.
- [ ] Degradação progressiva com ruído e **sobreposição** entre PUs saudáveis e doentes.
- [ ] Ciclo diário e sazonal nos dados (por exemplo, a temperatura ambiente do dia e da estação afetando motor e pneus).
- [ ] Rótulos de verdade em cada leitura de treino: se estava degradando e quanto faltava para falhar.
- [ ] **1 milhão de leituras ou mais**, geradas com numpy em blocos, com teto máximo.
- [ ] Job em segundo plano: `POST` → fila `q.jobs.generate` → serviço `data-lab`, com progresso mostrado na tela.
- [ ] Amostra gravada num bucket separado do InfluxDB (`lab`) e o dataset completo em arquivo (Parquet ou CSV) num volume.

### 2. Treino: 2 modelos de regressão (critério 8)
- [ ] Adicionar `scikit-learn` e `pandas` ou `pyarrow` ao `requirements.txt`.
- [ ] **Modelo 1, RUL da PU:** horas ou voltas até a falha.
- [ ] **Modelo 2, índice de saúde:** nota de 0 a 100.
- [ ] Um único módulo de features, usado no treino e na inferência (por exemplo `shared/pitwall_common/features.py`).
- [ ] Janelas só com o passado: média, desvio, tendência e máximo.
- [ ] Divisão em treino, validação e teste **por equipamento** (GroupShuffleSplit), nunca por linha.
- [ ] Página **Treino** com:
  - MAE, RMSE e R²;
  - gráfico de previsto contra real;
  - importância dos atributos;
  - comparação com uma base que prevê sempre a média; o modelo só vale se vencer essa base.
- [ ] Treino disparado pela tela → fila `q.jobs.train` → serviço `trainer` em segundo plano.
- [ ] O modelo novo entra em uso **sem reiniciar** o serviço, e a tela mostra a versão em uso. Por exemplo: o modelo vai para um volume com metadados no Postgres, e a inferência recarrega quando a versão muda.

### 3. Inferência e Insights (critério 9)
- [ ] Serviço `inference` consumindo `q.inference`. Isso completa as "4 filas com consumidores diferentes" exigidas, porque o documento cita a inferência nominalmente.
- [ ] Publicar previsões (`prediction.<id>`) e alertas preditivos de volta no exchange `f1` até a API e o WebSocket.
- [ ] Histerese nos alertas preditivos: por exemplo, 3 previsões seguidas abaixo do limite para disparar e 10 acima para limpar.
- [ ] Página **Insights**: por equipamento, a saúde, a RUL, a tendência e os alertas ativos.
- [ ] Trocar a heurística de saúde (`stores/insights.ts`) pela saúde da IA no painel da peça e na cor da cena 3D.

### 4. Assistente com LLM local (critério 9)
- [ ] Serviço `ollama` no Compose, com um modelo pequeno de CPU (`llama3.2:3b` ou `qwen2.5:1.5b`) **pré-carregado** ao subir, e volume para o modelo.
- [ ] Página **Assistente**: um chat.
- [ ] O backend monta o resumo: últimas leituras, pior saúde, RUL, alertas abertos, métricas do último treino e a arquitetura. O resumo vai pronto no prompt; o LLM nunca acessa os bancos.
- [ ] Resposta em **streaming**, com o aviso "carregando o modelo" enquanto ele sobe.
- [ ] Renderizar Markdown **sem HTML e sem imagens remotas**.
- [ ] Limite de perguntas por minuto por usuário e cada pergunta registrada na auditoria.

### 5. Segurança: login (critério 1)
- [ ] Login com **JWT** e 3 papéis:
  - `viewer` só vê;
  - `operator` comanda atuadores e o simulador;
  - `admin` também gera dados, treina e vê a auditoria.
- [ ] Senhas com **bcrypt** na tabela `users` (que já existe) e usuários de demonstração criados pelo `gen_secrets.py`, com senhas aleatórias.
- [ ] **Limite de tentativas** de login.
- [ ] Proteger as rotas por papel, inclusive o `POST /api/ws/ticket`, que hoje é aberto.
- [ ] Auditoria de **logins** e de **jobs disparados** (hoje só os comandos são registrados).
- [ ] Esconder ou desabilitar os botões na tela conforme o papel.

### 6. Interface 3D: ajustes (critério 7)
- [ ] A cor das peças também deve vir dos **alertas da IA**, não só da faixa do sensor.
- [ ] O painel da peça deve mostrar a **saúde prevista pela IA**.
- [ ] **2 elementos do ambiente** reagindo a dados. Hoje quem reage é o carro, não o cenário. Sugestões rápidas:
  - luz da garagem do box acende quando o carro está no pit (`in_pit`);
  - painel de bandeira ou luz amarela quando algum carro sofre DNF;
  - fumaça ou calor saindo da PU conforme `engine_temp` e `pu_vibration`;
  - iluminação do circuito ou céu pela temperatura da pista.

### 7. Docker Compose (critério 10)
- [ ] Adicionar `ollama`, `data-lab`, `trainer` e `inference` com healthcheck e ordem de subida.
- [ ] Testar `docker compose up` do zero (sem volumes) numa máquina com 8 GB para o WSL2.

### 8. Git e GitHub (critério 1)
- [ ] `git init`, primeiro commit e repositório no GitHub (o `.gitignore` já exclui `.env` e `definitions.json`).
- [ ] Histórico de commits de **todos os integrantes**.
- [ ] README: adicionar os **usuários de demonstração (sem as senhas)** e os passos de IA no roteiro.

---

## Ordem sugerida (pela pontuação)

1. **Git e GitHub:** é rápido e o critério 1 depende dele.
2. **Gerador e treino:** valem 1,0 ponto e destravam todo o resto da IA.
3. **Inferência e Insights:** usam os modelos treinados e ajustam a cena 3D.
4. **Ollama e Assistente:** metade do critério 9.
5. **JWT e papéis:** o item 2 do roteiro de demonstração.
6. **Elementos do ambiente na cena:** ajuste pequeno no critério 7.
