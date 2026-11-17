# PITWALL: o que o documento pede e o que já existe

Conferência feita em 15/11/2026 contra o "Documento sem título.docx" (enunciado do 2º bimestre), depois da entrega da parte de IA. A apresentação é em 16/11/2026.

Legenda: ✅ feito e testado · ⚠️ parcial · ❌ não existe ainda

## Resumo

| Critério de avaliação (1,0 cada) | Situação | O que falta |
|---|---|---|
| 1. Evolução, qualidade, segurança e GitHub com README | ⚠️ | Git/GitHub, JWT com 3 papéis, bcrypt, limite de login (fora do escopo desta entrega) |
| 2. Sensores, atuadores e MQTT + Mosquitto | ✅ | — |
| 3. Regra automática e controle pela Web | ✅ | — |
| 4. RabbitMQ (exchange, filas, consumidores, DLQ, Mensageria) | ✅ | — |
| 5. PostgreSQL e InfluxDB | ✅ | Usar a tabela `users` (vem com o JWT) |
| 6. WebSocket, dashboard, gráficos e histórico | ✅ | — |
| 7. Interface 3D | ✅ | — |
| 8. Dados sintéticos e modelos de regressão | ✅ | — |
| 9. Insights de IA e LLM local | ✅ | — |
| 10. Docker Compose e apresentação completa | ✅ | Testar `docker compose up` do zero numa máquina limpa |

Só o critério 1 continua parcial: faltam o login com papéis e o GitHub, que ficaram fora desta entrega a pedido. O passo 2 do roteiro de demonstração ("login e os três papéis") ainda não pode ser mostrado.

---

## O que está feito

### Stack obrigatória

| Camada | Tecnologia pedida | No PITWALL | |
|---|---|---|---|
| Frontend | Vue 3 ou React + TS + Vite | Vue 3 + TypeScript + Vite + vue-router | ✅ |
| 2D | Chart.js ou ECharts | Chart.js (histórico, sparklines, previsto × real) | ✅ |
| 3D | Three.js | Three.js 0.170 puro, carro e pista procedurais | ✅ |
| Backend | Python + FastAPI | FastAPI com REST + Swagger em `/api/docs` | ✅ |
| Tempo real | WebSocket | `/ws` com ticket de uso único | ✅ |
| IoT | MQTT + Mosquitto | Sem anônimo, ACL por tópico | ✅ |
| Dispositivo | Simulador Python | 6 carros a 10 Hz | ✅ |
| Mensageria | RabbitMQ | Exchange topic `f1`, DLX, usuário por serviço | ✅ |
| IA | scikit-learn | 2 × `RandomForestRegressor` | ✅ |
| LLM local | Ollama | `qwen2.5:1.5b` (gratuito, Apache 2.0, CPU) | ✅ |
| Relacional | PostgreSQL | Dispositivos, regras, alertas, auditoria, jobs, `users` | ✅ |
| Séries temporais | InfluxDB | `telemetry`, `events` e bucket `lab` | ✅ |
| Infra | Docker + Compose | 14 serviços com healthcheck | ✅ |
| Versionamento | Git + GitHub | A pasta não é um repositório Git | ❌ |

### Fluxos obrigatórios

- ✅ **IoT → Web:** simulador → MQTT → gateway → RabbitMQ → influx-writer e API → WebSocket → tela.
- ✅ **Web → IoT:** botão → API → `q.commands` → gateway → MQTT → simulador, e a mudança aparece nas leituras seguintes.
- ✅ **IA:**
  1. Laboratório → `q.jobs.generate` → ml-worker gera o dataset.
  2. Treino → `q.jobs.train` → ml-worker grava os modelos.
  3. `inference` consome `q.inference` e publica `prediction.<id>` e `alert.<id>`.
  4. As previsões chegam pelo `q.ws` ao WebSocket e aparecem no Insights e no 3D.

### Dados sintéticos massivos (Laboratório)

- ✅ Página com todos os parâmetros pedidos:
  - número de equipamentos e de sensores (5 por PU);
  - período em dias;
  - % que falha e os modos de falha (rolamento, superaquecimento, vazamento de óleo, deriva de sensor);
  - ruído, % de leituras faltantes, % de outliers e semente.
- ✅ Degradação progressiva com a mesma lei do simulador (`dw/dt = k·(0,4 + w)`). Há ruído, uma variação própria de cada máquina (que cria sobreposição entre saudáveis e doentes) e o ciclo diário e sazonal.
- ✅ Rótulos de verdade (`health`, `rul_h`) só no dataset, nunca nas mensagens ao vivo.
- ✅ Volume: o padrão gera cerca de 1,74 milhão de leituras em cerca de 1 s, com numpy em blocos por equipamento. O teto é de 5 milhões.
- ✅ Job em segundo plano por fila, com o progresso na tela (tabela `jobs`). Uma amostra de cerca de 5 mil pontos vai para o bucket `lab` do InfluxDB.

### Regressão (Treino)

- ✅ 2 modelos treinados: **índice de saúde** (R² 0,98, MAE 2,3) e **vida útil restante** (R² 0,76, MAE 19,7 h). Os dois vencem a base, que prevê sempre a média (R² ≈ 0).
- ✅ As features vêm de um único código ([features.py](../shared/pitwall_common/features.py)), usado no treino e na inferência.
- ✅ Janela só com o passado: média, desvio e máximo das últimas 30 leituras.
- ✅ Divisão por equipamento: 70 PUs no treino, 15 na validação e 15 no teste.
- ✅ A página mostra MAE, RMSE, R², a base, o gráfico previsto × real e a importância dos atributos.
- ✅ Treino disparado pela tela, em segundo plano. O modelo novo entra em uso sem reiniciar (`current.json` é trocado de forma atômica e a inferência recarrega sozinha), e a tela mostra a versão em uso.

### Insights e alertas preditivos

- ✅ Inferência ao vivo a 1 Hz por carro, publicando de volta no RabbitMQ.
- ✅ Histerese: 3 previsões abaixo de 50 disparam o alerta e 10 acima de 60 o limpam. O alerta fica gravado no PostgreSQL.
- ✅ Página **Insights**: saúde, vida útil, tendência, alertas ativos e versão do modelo.
- ✅ As mesmas previsões colorem a PU na Garagem e na Corrida e aparecem no painel da peça.
- ✅ Testado: falha de rolamento no PW16 → saúde de 84 a 0 em cerca de 3,5 min → alerta preditivo → DNF.

### Assistente com LLM local

- ✅ Ollama no Compose com `qwen2.5:1.5b`, sem chave e sem nuvem. O modelo é baixado e **pré-carregado** na subida (`OLLAMA_KEEP_ALIVE=-1`).
- ✅ O backend monta o resumo: leituras, pior saúde, vida útil, alertas abertos, métricas do treino e a arquitetura. O LLM não acessa os bancos e não recebe ferramentas.
- ✅ Resposta em streaming, com o aviso "carregando o modelo" enquanto ele sobe.
- ✅ Markdown renderizado sem HTML e sem imagens ([markdown.ts](../frontend/src/utils/markdown.ts)).
- ✅ Limite de 6 perguntas por minuto por cliente, e cada pergunta é registrada na auditoria.

### Interface 3D: ambiente reagindo a dados

- ✅ A garagem de cada carro acende na cor da equipe quando ele entra no pit (`in_pit`).
- ✅ Os postes de luz da pista ficam âmbar e piscam (bandeira amarela) quando há carro quebrado ou alerta crítico.
- ✅ A cor da PU também vem da IA (saúde abaixo de 70 = atenção, abaixo de 50 = crítico) e dos alertas preditivos.

### RabbitMQ

- ✅ 8 filas, todas com consumidor:

| Fila | Consumidor |
|---|---|
| `q.influx` | `pw_writer` |
| `q.rules` | `pw_rules` |
| `q.ws` | `pw_api` |
| `q.commands` | `pw_gateway` |
| `q.inference` | `pw_infer` |
| `q.jobs.generate` | `pw_ml` |
| `q.jobs.train` | `pw_ml` |
| `q.dead` | DLQ |

- ✅ Novos usuários com o mínimo de permissões: `pw_ml` só lê os jobs; `pw_infer` lê `q.inference` e publica em `f1`.

### Bancos, dashboard, segurança e infraestrutura (já entregues antes)

- ✅ Sensores, atuadores, a PU monitorada, a regra automática com histerese e os comandos pela Web.
- ✅ Mensageria ao vivo, Histórico (InfluxDB), Dispositivos, regras e auditoria (PostgreSQL).
- ✅ Segurança: segredos gerados fora do Git, Mosquitto sem anônimo, um usuário por serviço no RabbitMQ, ticket no WebSocket, containers sem root (exceto a imagem oficial do Ollama), só a porta 8080 publicada e as UIs de administração em 127.0.0.1.

---

## O que ainda falta (fora do escopo desta entrega)

### Login e papéis (critério 1, item 2 do roteiro)
- [ ] Login JWT com `viewer`, `operator` e `admin`.
- [ ] Senhas com bcrypt na tabela `users`, que já existe, e limite de tentativas.
- [ ] Proteger as rotas por papel, inclusive `POST /api/ws/ticket`, `/api/lab/*` e `/api/commands`.
- [ ] Auditoria de logins (comandos, jobs e perguntas ao assistente já são registrados).
- [ ] README: usuários de demonstração, sem as senhas.

### Git e GitHub (critério 1)
- [ ] `git init`, primeiro commit e repositório no GitHub (o `.gitignore` já exclui `.env` e `definitions.json`).
- [ ] Histórico de commits de todos os integrantes.

### Conferência final
- [ ] Rodar `docker compose up` do zero (`docker compose down -v` + `python scripts/gen_secrets.py --force`) para garantir a subida limpa, incluindo o download do modelo do Ollama.
