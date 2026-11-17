# PITWALL: telemetria de F1 com gêmeo digital 3D

O PITWALL é a evolução do projeto IoT do 1º bimestre. O pipeline continua o mesmo (publisher → broker → consumer → banco → API → Web), mas o domínio passou a ser **Fórmula 1**. Seis carros simulados correm num circuito original e publicam telemetria em tempo real: velocidade, RPM, temperaturas do motor e do óleo, vibração da Power Unit, temperatura, desgaste e pressão de cada pneu, freios, combustível e ERS. O muro da equipe acompanha tudo em duas telas 3D e envia comandos ao carro.

| Tela | O que mostra |
|---|---|
| **Corrida** | O circuito em 3D com os carros posicionados **somente** pela telemetria do WebSocket. Tem torre de tempos, HUD do carro selecionado, estratégia da equipe (cliff do pneu, combustível, janela de pit), minimapa e três câmeras: aérea, perseguição e TV (teclas 1, 2 e 3). |
| **Garagem** | O carro grande no centro: arraste para girar, use a roda do mouse para dar zoom e passe o mouse sobre as peças para ver o valor ao vivo. Ao clicar numa peça abre um painel com a leitura, o gráfico dos últimos 60 s, a saúde e os comandos. Os cards ao redor ficam ligados às peças por linhas-guia. Tem modo raio-X (PU, célula de combustível, ERS e radiadores) e mapa térmico. |
| Histórico | Consulta ao InfluxDB por carro, variável e janela. |
| Dispositivos | Cadastro no PostgreSQL de carros, sensores, atuadores e equipamentos, com faixas normal e crítica, regras, alertas e auditoria. |
| Mensageria | Dados do RabbitMQ ao vivo: filas, taxas, consumidores, últimas mensagens e DLQ. |
| **Insights** | Por Power Unit: saúde prevista pela IA (0–100), vida útil restante, tendência e alertas preditivos. |
| **Laboratório** | Gerador de dados sintéticos massivos configurável (equipamentos, dias, % de falhas, modos de falha, ruído, faltantes, outliers, semente), com progresso ao vivo. |
| **Treino** | Treina os 2 modelos de regressão e mostra MAE, RMSE, R², a base simples, previsto × real e a importância dos atributos. |
| **Assistente** | Chat com LLM local e gratuito (Ollama + `qwen2.5:1.5b`, em CPU), com resposta em streaming. |
| Sistemas | Saúde dos serviços, links das UIs de administração e diagrama da arquitetura. |

## Arquitetura

```
simulator (Python, 6 carros, 10 Hz)
   │  MQTT  f1/<carro>/telemetry · f1/<carro>/event          ▲ f1/<carro>/cmd
   ▼                                                          │
Mosquitto (sem anônimo, ACL por tópico) ◀──────────────── gateway (MQTT ⇄ AMQP)
   │                                                          ▲
   ▼  gateway republica no exchange topic "f1"                │ q.commands
RabbitMQ  ── telemetry.<equipe>.car.<id> · event.<tipo>.<id> · alert.<id> · command.<id>
   ├─ q.influx    → influx-writer → InfluxDB (bucket telemetry)
   ├─ q.rules     → rules-engine  → alertas + comando automático (PostgreSQL: regras/alertas/auditoria)
   ├─ q.ws        → API FastAPI   → WebSocket → Vue 3 + Three.js
   ├─ q.commands  → gateway       → MQTT → simulador (atuador muda e aparece nas leituras seguintes)
   ├─ q.inference → inference     → prediction.<id> + alertas preditivos → q.ws → Insights e 3D
   ├─ q.jobs.generate / q.jobs.train → ml-worker → dataset (numpy) e modelos (scikit-learn)
   └─ f1.dlx → q.dead (DLQ, mensagem preservada)

API /api/assistant/chat → resumo dos dados + pergunta → Ollama (qwen2.5:1.5b, local) → streaming
```

Todas as mensagens usam o mesmo envelope JSON: `{id, ts, type, device, source, payload}`. Os rótulos de verdade, como o desgaste real da PU, ficam só no estado interno do simulador e nunca entram nas mensagens.

| Requisito | No PITWALL |
|---|---|
| Sensores (≥3) | velocidade, RPM, marcha, acelerador/freio, motor, óleo (temp./pressão), vibração da PU, combustível, ERS e, por roda, temperatura/desgaste/pressão do pneu e temperatura do freio |
| Atuador por regra | **Resfriamento / lift-and-coast**: liga com motor > 118 °C (5 leituras) e desliga abaixo de 108 °C (20 leituras). A regra fica na tabela `rules` e pode ser editada pela interface. |
| Atuador pela Web | **Modo do motor** (PUSH/STANDARD/CONSERVE), **modo ERS** e **chamada para o BOX** (troca de composto) |
| Equipamento monitorado | **Power Unit**: vibração, temperatura do óleo, pressão do óleo e temperatura do motor sobem ou caem aos poucos conforme ela se desgasta. Também os **pneus** (desgaste, temperatura e o cliff). |
| PostgreSQL | dispositivos, regras, alertas, auditoria, jobs da IA e usuários (a tabela de usuários será usada pelo login) |
| InfluxDB | measurement `telemetry` (tags `car_id`, `team`, `tyre_compound`) e measurement `events`; amostra do laboratório no bucket separado `lab` |
| Dados sintéticos | `ml-worker` simula a vida de N Power Units até a falha com as mesmas fórmulas do simulador; padrão: 100 PUs × 14 dias ≈ 1,7 milhão de leituras em ~1 s |
| 2 regressões | `RandomForestRegressor`: **índice de saúde** (R² ≈ 0,98) e **vida útil restante** em horas (R² ≈ 0,76), divisão por equipamento, comparação com a média |
| Inferência | `inference` consome `q.inference`, aplica os modelos a 1 Hz por carro e publica `prediction.<id>`; alerta com histerese (3 abaixo de 50 dispara, 10 acima de 60 limpa); troca de modelo sem reiniciar |
| LLM local | Ollama no Compose, modelo gratuito `qwen2.5:1.5b` pré-carregado; o backend envia o resumo pronto, limita 6 perguntas/min e audita cada pergunta |

## Como subir

Pré-requisitos: Docker Desktop (no Windows, reserve pelo menos 8 GB para o WSL2) e Python 3.10+ para rodar o gerador de segredos. Na primeira subida o container `ollama` baixa o modelo (~1 GB) e o deixa carregado na memória; até lá o Assistente mostra "carregando o modelo".

```bash
cd pitwall
python scripts/gen_secrets.py      # gera .env e infra/rabbitmq/definitions.json (fora do Git)
docker compose up --build          # sobe tudo; aguarde todos os serviços ficarem "healthy"
```

| Endereço | Serviço |
|---|---|
| http://localhost:8080 | aplicação (única porta publicada para fora) |
| http://localhost:8080/api/docs | documentação da API REST (Swagger) |
| http://127.0.0.1:15672 | RabbitMQ Management (usuário `pw_admin`) |
| http://127.0.0.1:8086 | InfluxDB (usuário `pitwall`) |
| http://127.0.0.1:5050 | pgAdmin |

As senhas ficam no `.env` gerado. Não existe senha padrão no repositório.

Para desenvolver o frontend com hot reload (o Vite repassa `/api` e `/ws` para o compose):

```bash
cd frontend && npm install && npm run dev    # http://localhost:5173
```

### Usuários e permissões

| Serviço | Usuário | Permissões |
|---|---|---|
| Mosquitto | `sim` | publica `f1/+/telemetry` e `f1/+/event`, lê `f1/+/cmd` |
| Mosquitto | `gateway` | lê `f1/+/telemetry` e `f1/+/event`, publica `f1/+/cmd` |
| Mosquitto | `monitor` | só leitura |
| RabbitMQ | `pw_gateway` | publica em `f1`, lê `q.commands` |
| RabbitMQ | `pw_writer` | lê `q.influx` |
| RabbitMQ | `pw_rules` | publica em `f1`, lê `q.rules` |
| RabbitMQ | `pw_api` | publica em `f1`, lê `q.ws` e `q.dead`, tag monitoring |
| RabbitMQ | `pw_ml` | lê `q.jobs.generate` e `q.jobs.train` |
| RabbitMQ | `pw_infer` | publica em `f1`, lê `q.inference` |
| RabbitMQ | `pw_admin` | administrador (apenas para a UI) |

O usuário `guest` não existe. Os containers da aplicação rodam sem root (o frontend usa `nginx-unprivileged`). O WebSocket é aberto com um ticket curto de uso único (`POST /api/ws/ticket`), então nenhum token vai na URL.

## Roteiro de demonstração

1. `docker compose up --build` e depois `docker compose ps`: todos os serviços aparecem como *healthy*.
2. MQTT ao vivo: `docker compose exec mosquitto sh -c 'mosquitto_sub -u monitor -P "$MQTT_MONITOR_PASSWORD" -t "f1/PW16/#" -C 3'`. Sem usuário e senha a conexão é recusada.
3. Swagger em `/api/docs`.
4. **Mensageria**: `docker compose stop influx-writer` faz a fila `q.influx` crescer, e `docker compose start influx-writer` faz ela esvaziar.
5. **Histórico** (InfluxDB) e **Dispositivos**, regras e auditoria (PostgreSQL).
6. **Corrida**: carros ao vivo e estratégia. `docker compose stop simulator` mostra o aviso **SEM DADOS** em até 2 s e congela a cena.
7. **Regra automática**: na Garagem, coloque o PW16 em **PUSH**. O motor passa de 118 °C, o rules-engine liga o resfriamento, as aletas abrem e a luz traseira pisca. Isso gera um alerta e um registro na auditoria.
8. **Web → IoT**: chame o **BOX** com outro composto. O carro entra no pit lane, para, troca os pneus, e o desgaste volta a 0 nas leituras seguintes.
9. **Laboratório**: clique em **Gerar dados** com o padrão (≈ 1,7 milhão de leituras). O progresso aparece ao vivo e a fila `q.jobs.generate` aparece na Mensageria.
10. **Treino**: clique em **Treinar modelos** (cerca de 1 min). Aparecem MAE, RMSE e R² contra a base (sempre a média), previsto × real e a importância. A versão nova entra em uso na inferência sem reiniciar nada.
11. **Falha injetada**: em **Insights** (ou no painel da PU na Garagem), use "Injetar falha". A vibração sobe, a saúde prevista e a vida útil caem, o alerta preditivo dispara depois de 3 previsões abaixo de 50, a PU fica vermelha na Garagem e os postes da pista ficam âmbar (bandeira amarela). Sem reparo, o motor quebra (DNF).
12. **Assistente**: pergunte "Qual carro está com a pior saúde e o que devo fazer?". A resposta chega em streaming, vinda do LLM local.

## Estrutura

```
pitwall/
  docker-compose.yml  python.Dockerfile  requirements.txt  scripts/gen_secrets.py
  infra/{mosquitto,rabbitmq,postgres}/         configs, ACL, schema e seeds
  shared/pitwall_common/                       envelope, tópicos, pista, clientes MQTT/AMQP
  simulator/  gateway/  api/                  serviços Python
  workers/                                     influx_writer, rules_engine, ml_worker (dados + treino), inference
  shared/pitwall_common/features.py            features da IA (o mesmo código no treino e na inferência)
  frontend/                                    Vue 3 + TS + Vite + Three.js + Chart.js
```

Reaproveitado do 1º bimestre (as pastas antigas foram removidas; o código evoluiu para cá):
- a classe `Broker` (`arduino/config/broker.py`) virou `shared/pitwall_common/mqtt.py`, agora com a API v2 do paho, autenticação e reconexão;
- o `on_message` do backend virou o `influx-writer`;
- `configs/db.py` virou `api/influx.py`;
- o lifespan e o CORS do FastAPI foram mantidos;
- o cliente axios e o Chart.js continuam no frontend.

## Observações sobre a IA

- **Escala de tempo**: o laboratório simula dias de uso (1 leitura por minuto), enquanto a falha injetada ao vivo acontece em poucos minutos para caber na demonstração. Por isso a vida útil ao vivo é mostrada nas horas "de laboratório": o que importa é a queda contínua até a quebra.
- **Rótulos de verdade** (saúde e horas até a falha) existem só no dataset do laboratório; as mensagens ao vivo nunca os carregam.
- **Sem modelo treinado**, a interface usa uma heurística de reserva e avisa "(heurística · treine o modelo)".

## Fora do escopo desta entrega

- Login JWT com os três papéis, bcrypt e limite de tentativas (a tabela `users` já existe).
- Repositório no GitHub com o histórico de commits de todos os integrantes.
