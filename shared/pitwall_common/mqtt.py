"""Cliente MQTT — evolução da classe Broker do 1º bimestre (antigo arduino/config/broker.py).

Mudanças: API de callbacks v2 do paho 2.x, autenticação, reconexão automática,
re-assinatura no on_connect e Last Will opcional.
"""
import json
import logging
import time
from typing import Callable

import paho.mqtt.client as mqtt

log = logging.getLogger("mqtt")

OnMessage = Callable[[str, bytes], None]


class Broker:
    def __init__(self, host: str, port: int, username: str, password: str, client_id: str,
                 subscriptions: list[str] | None = None, on_message: OnMessage | None = None,
                 will: tuple[str, str] | None = None):
        self.host = host
        self.port = port
        self.subscriptions = subscriptions or []
        self._on_message = on_message

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.client.username_pw_set(username, password)
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        if will:
            self.client.will_set(will[0], will[1], qos=1, retain=True)
        self.client.on_connect = self._handle_connect
        self.client.on_disconnect = self._handle_disconnect
        self.client.on_message = self._handle_message

    # ------------------------------------------------------------------ conexão
    def connect(self, retries: int = 60) -> None:
        for attempt in range(1, retries + 1):
            try:
                self.client.connect(self.host, self.port, keepalive=30)
                self.client.loop_start()
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("MQTT indisponível (%s), tentativa %d/%d", exc, attempt, retries)
                time.sleep(2)
        raise RuntimeError("não foi possível conectar ao Mosquitto")

    def _handle_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            log.info("Conectado ao Mosquitto %s:%s", self.host, self.port)
            for topic in self.subscriptions:
                client.subscribe(topic, qos=0)
                log.info("Inscrito em %s", topic)
        else:
            log.error("Falha na conexão MQTT: %s", reason_code)

    def _handle_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning("Desconectado do Mosquitto (%s)", reason_code)

    def _handle_message(self, client, userdata, msg):
        if self._on_message:
            try:
                self._on_message(msg.topic, msg.payload)
            except Exception:  # noqa: BLE001
                log.exception("Erro ao tratar mensagem MQTT em %s", msg.topic)

    # ------------------------------------------------------------------ envio
    def publish(self, topic: str, data: dict | bytes | str, qos: int = 0, retain: bool = False) -> None:
        if isinstance(data, dict):
            data = json.dumps(data, separators=(",", ":"))
        self.client.publish(topic, data, qos=qos, retain=retain)

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
