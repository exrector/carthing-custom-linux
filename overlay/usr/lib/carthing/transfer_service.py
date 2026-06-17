"""transfer_service — A2DP relay ВНУТРИ единого рантайма (runtime-contract §Transfer).

Transfer = внутренняя маршрутизация аудио (iPhone -> Car Thing -> BT-динамик), НЕ вторая
BT-персона и НЕ режим. Обёртка над проверенным a2dp_bridge (AAC passthrough relay).

КЛЮЧЕВОЙ СТЫК (чинит «iPhone цепляется колонкой»): a2dp_bridge сам включал classic
connectable + COD_LOUDSPEAKER на старте. Здесь classic-connectable ГЕЙТИТ
accessory_orchestrator (connectable=False вне Transfer; True только при activate()).
Так relay сохраняется, а дефолтная A2DP-видимость убрана.

Получатель НЕ хардкожен (runtime-contract): из настройки/intent -> trusted speakers -> нет приёмника.
"""

import asyncio
import logging

import identity_service
import operation_mode
from a2dp_bridge import A2DPBridge
from app_state import normalize_address

logger = logging.getLogger(__name__)


class TransferService:
    def __init__(self, device, app_state, orchestrator, model, on_change=None, hci_gate=None):
        self.orch = orchestrator
        self.model = model
        self.on_change = on_change or (lambda: None)
        self.bridge = A2DPBridge(
            device, app_state,
            bt_name=identity_service.classic_audio_name(),
            autoconnect=False,                  # никакого авто-коннекта/визибилити по умолчанию
            hci_gate=hci_gate,
            on_state_change=self._sync,
            on_visibility_request=self._on_bridge_visibility,
        )
        self._speaker_enroll_task = None

    async def _on_bridge_visibility(self, connectable: bool, discoverable: bool):
        """Callback от a2dp_bridge — перенаправляем в оркестратор асинхронно.
        НЕ await здесь: этот callback вызывается изнутри _gate оркестратора →
        прямой await вызвал бы дедлок на asyncio.Lock."""
        if self.orch is None:
            return
        import asyncio
        asyncio.ensure_future(self.orch.set_transfer_connectable(connectable))

    async def start(self):
        """[CLAUDE 2026-06-04] ТРУБА ВСЕГДА ОТКРЫТА. Никаких режимов/кнопок/teardown.
        Car Thing = простой ретранслятор: iPhone connectable всегда; что iPhone пришлёт
        (метаданные по BLE = Play Now, или A2DP-поток = музыка) — то и обрабатываем.
        Если выбран динамик (Fosi) и он держится в standby — A2DP-поток льётся на него
        (forward_packet делает это сам, когда receiver_rtp_channel открыт). Если динамик не
        выбран — поток никуда не идёт, остаётся Play Now."""
        self.bridge.install_sdp_records()
        self.bridge.install_safe_link_key_provider()
        await self.bridge.start()               # AVDTP listener up
        # transfer_active=True ПОСТОЯННО — труба всегда «активна», forward работает сам.
        self.model.transfer_active = True
        try:
            self.bridge.state.transfer_active = True
        except Exception:
            pass
        await self.apply_operation_mode(
            getattr(self.bridge.state, "operation_mode", operation_mode.DEFAULT),
            reason="transfer.start",
        )
        await self.orch.on_a2dp_state(True)

    async def _stop_standby_loop(self):
        task = getattr(self.bridge, "_standby_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                logger.warning("standby loop cancel timed out")
            except Exception as exc:
                logger.info("standby loop stop ignored: %s", exc)
        if getattr(self.bridge, "_standby_task", None) is task and (task is None or task.done()):
            self.bridge._standby_task = None

    def _cancel_receiver_tasks(self):
        task = getattr(self.bridge, "_receiver_retry_task", None)
        if task is not None and not task.done():
            task.cancel()
        for runtime in list(getattr(self.bridge, "_speaker_runtimes", {}).values()):
            task = getattr(runtime, "connect_task", None)
            if task is not None and not task.done():
                task.cancel()

    async def _stop_all_receiver_streams(self):
        self._cancel_receiver_tasks()
        for address in list(getattr(self.bridge, "_speaker_runtimes", {}).keys()):
            try:
                await self.bridge.stop_receiver_stream(address)
                await self.bridge.disconnect_speaker_link(address)
            except Exception as exc:
                logger.info("receiver stream stop ignored for %s: %s", address, exc)
        try:
            await self.bridge.stop_receiver_stream()
        except Exception as exc:
            logger.info("receiver route clear ignored: %s", exc)

    def resource_state(self):
        standby_task = getattr(self.bridge, "_standby_task", None)
        if standby_task is not None and standby_task.done():
            self.bridge._standby_task = None
            standby_task = None
        runtimes = list(getattr(self.bridge, "_speaker_runtimes", {}).values())
        receiver_stream = any(
            getattr(getattr(runtime, "connector", None), "rtp_channel", None) is not None
            for runtime in runtimes
        )
        receiver_connecting = any(
            getattr(runtime, "connect_task", None) is not None
            and not runtime.connect_task.done()
            for runtime in runtimes
        )
        speaker_scan = any(
            task is not None and not task.done()
            for task in (
                getattr(self.bridge, "_scan_task", None),
                getattr(self.bridge, "_enroll_task", None),
                self._speaker_enroll_task,
            )
        )
        return {
            "actual_standby_loop": standby_task is not None and not standby_task.done(),
            "actual_receiver_stream": receiver_stream,
            "actual_receiver_connecting": receiver_connecting,
            "actual_a2dp_listener": bool(getattr(self.bridge, "listener", None)),
            "actual_speaker_scan": speaker_scan,
            "actual_source_stream": bool(getattr(self.bridge, "source_stream_active", False)),
            "packets_forwarded": int(getattr(self.bridge, "packets_forwarded", 0)),
            "packets_dropped": int(getattr(self.bridge, "packets_dropped", 0)),
        }

    async def apply_operation_mode(self, mode, reason=""):
        mode = operation_mode.normalize(mode)
        desired = operation_mode.resources(mode)
        try:
            self.bridge.state.operation_mode = mode
        except Exception:
            pass
        if desired.speaker_standby:
            self.bridge.start_standby_loop()
        else:
            await self._stop_standby_loop()
            await self._stop_all_receiver_streams()
            await self.stop_speaker_enrollment()
            try:
                self.bridge.local_sink_enabled = False
            except Exception:
                pass
            self.model.audio_sink = "builtin"
        resources = desired.as_dict()
        resources.update(self.resource_state())
        self.model.set_operation_mode(mode, resources)
        logger.info(
            "transfer mode applied: mode=%s reason=%s resources=%s",
            mode,
            reason or "-",
            resources,
        )
        self._sync()

    async def start_speaker_enrollment(self):
        if self._speaker_enroll_task is not None and not self._speaker_enroll_task.done():
            return
        self._speaker_enroll_task = asyncio.create_task(self._speaker_enrollment_loop())
        self._sync()

    async def _speaker_enrollment_loop(self):
        while bool(getattr(self.bridge.state, "pairing_mode", False)):
            try:
                await self.bridge.scan_pairable_speakers(duration=8.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("speaker enrollment scan failed: %s", e)
                try:
                    self.bridge.state.speaker_pairing_status = "error"
                except Exception:
                    pass
                self._sync()
                await asyncio.sleep(1.0)
                continue
            # [CLAUDE 2026-06-03] start_discovery (инквайри) гасит BLE-advertising на одном
            # радиочипе. Возрождаем рекламу СРАЗУ после каждого скана, иначе BLE «Car Thing»
            # умирает навсегда (источники перестают видеть его в эфире).
            try:
                await self.orch.apply_visibility()
            except Exception as e:
                logger.warning("revive advertising after inquiry failed: %s", e)
            if bool(getattr(self.bridge.state, "pairing_mode", False)):
                try:
                    self.bridge.state.speaker_pairing_status = "scan"
                except Exception:
                    pass
                self._sync()
                # [CLAUDE 2026-06-03] Ленивая каденция: пауза между инквайри больше (устройства
                # не мелькают в эфире). Список накопительный — спешить незачем.
                await asyncio.sleep(5.0)

    async def stop_speaker_enrollment(self):
        if self._speaker_enroll_task is not None and not self._speaker_enroll_task.done():
            self._speaker_enroll_task.cancel()
            try:
                await self._speaker_enroll_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("speaker enrollment loop stop ignored: %s", e)
        self._speaker_enroll_task = None
        try:
            await self.bridge.device.stop_discovery()
        except Exception:
            pass
        try:
            self.bridge.state.speaker_pairing_status = "idle"
        except Exception:
            pass
        self._sync()

    async def pair_speaker(self, address):
        normalized = normalize_address(address)
        try:
            existing = next(
                (d for d in getattr(self.bridge.state, "trusted", [])
                 if normalize_address(d.get("address")) == normalized),
                None,
            )
            is_existing_input = bool(existing and (
                existing.get("role") == "source"
                or "audio_input" in set(existing.get("capabilities") or [])
                or any(e.get("direction") == "input" for e in existing.get("endpoints") or [])
            ))
            if not is_existing_input:
                await self.bridge.forget_peer_key(normalized)
        except Exception as e:
            logger.warning("speaker forget key before pairing failed: %s", e)
        stale_connection = self.bridge._speaker_connection(normalized)
        if stale_connection is not None:
            try:
                await stale_connection.disconnect()
            except Exception:
                pass
        candidate = None
        try:
            candidate = next(
                (c for c in getattr(self.bridge.state, "speaker_candidates", [])
                 if c.get("address") == normalized),
                None,
            )
        except Exception:
            candidate = None
        if candidate is None:
            candidate = {"address": normalized, "label": normalized, "audio": True}
        # [CLAUDE 2026-06-03] УНИВЕРСАЛЬНЫЙ enroll: НЕ-аудио (телефон/ноут = источник) просто
        # заносим в доверенные как ИСТОЧНИК, БЕЗ classic-коннекта (иначе PAGE_TIMEOUT/AUTH флуд).
        # Реальная привязка источника — по BLE со стороны самого устройства (выбери Car Thing).
        if not candidate.get("audio"):
            try:
                self.bridge.state.enroll_trusted_device(
                    normalized, name=candidate.get("label") or normalized,
                    class_of_device=candidate.get("class_of_device"),
                    capabilities=["audio_input", "metadata_input", "control_output"],
                    metadata={"enrolled_from": "classic_inquiry", "input_enrolled": True})
                self.bridge.state.save_trusted()
                self.bridge.state.speaker_pairing_status = "done"
                self.bridge.state.pairing_message = (candidate.get("label") or normalized) + " добавлен (источник)"
                self.bridge.state.pairing_mode = False
            except Exception as e:
                logger.warning("source enroll failed: %s", e)
            self._sync()
            return
        try:
            existing = list(getattr(self.bridge.state, "speaker_candidates", []))
            existing = [c for c in existing if c.get("address") != normalized]
            existing.append(candidate)
            self.bridge.state.speaker_candidates = existing
        except Exception:
            pass
        ok = False
        try:
            await self.bridge.pair_speaker(normalized)
            if getattr(self.bridge.state, "speaker_pairing_status", "") == "done":
                ok = True
                if not getattr(self.bridge.state, "pairing_message", ""):
                    self.bridge.state.pairing_message = (candidate.get("label") or normalized) + " добавлен"
                    self._sync()
                await asyncio.sleep(2.4)
                # закрываем сканер, но СОЕДИНЕНИЕ ДЕРЖИМ (как настоящая ОС):
                # set_speaker_connected уже выставлен в True в bridge.pair_speaker,
                # соединение живёт в per-device SpeakerRuntime.
                self.bridge.state.pairing_mode = False
                self.bridge.state.speaker_pairing_status = "idle"
                self.bridge.state.pairing_message = ""
        except Exception as e:
            logger.warning("speaker pair failed: %s", e)
            try:
                self.bridge.state.speaker_pairing_status = "error"
                self.bridge.state.pairing_message = "Пара не завершена"
            except Exception:
                pass
        if not ok:
            # [CLAUDE 2026-06-03] Раньше здесь был «silent enrollment»: бридж соединял колонку,
            # а обёртка тут же РВАЛА линк -> Fosi возвращалась в мигание (режим пары). Теперь
            # рвём ТОЛЬКО при неудаче (очистка); при успехе держим ACL/AVDTP — колонка
            # перестаёт мигать и показывается подключённой (зелёной) в Routes.
            await self.bridge.forget_speaker_runtime(normalized)
            try:
                self.bridge.state.set_speaker_connected(normalized, False)
            except Exception:
                pass
        self._sync()

    async def forget_trusted(self, address):
        normalized = normalize_address(address)
        try:
            await self.bridge.forget_speaker_runtime(normalized)
        except Exception as e:
            logger.warning("speaker runtime forget failed: %s", e)
        try:
            removed = self.bridge.state.remove_trusted(normalized)
            if removed:
                self.bridge.state.save_trusted()
        except Exception as e:
            logger.warning("speaker registry forget failed: %s", e)
        try:
            await self.bridge.forget_peer_key(normalized)
        except Exception as e:
            logger.warning("speaker forget key failed: %s", e)
        self._sync()

    # ── активация Transfer (вручную из Routes-view, runtime-contract) ────────
    async def activate(self):
        self.model.transfer_active = True
        try:
            self.bridge.state.transfer_active = True
            self.bridge.state.transfer_status = "armed"
        except Exception:
            pass
        # [CLAUDE 2026-06-03] МАРШРУТ ПАССИВЕН. Car Thing НИКОГО НЕ ДЁРГАЕТ:
        #  - источник (iPhone) НЕ дозваниваем (раньше connect_source -> AUTHENTICATION_FAILURE 0x5
        #    и вообще неверно по модели). Просто становимся готовым connectable-sink'ом и ЖДЁМ,
        #    пока пользователь сам выберет Car Thing аудиовыходом на iPhone — он подключится сам.
        #  - выход (Fosi) — НАШЕ устройство вывода, его держим/реконнектим сами.
        await self.orch.set_transfer_connectable(True)   # connectable для bonded-источника (не discoverable)
        await self.orch.on_a2dp_state(True)
        # 2026-06-18: activation is explicit, but still route-scoped. Do not
        # launch a general trusted-device poll here; the selected output connect
        # below is the only radio work this user action requested.
        await self.bridge.request_receiver_connection()
        logger.info("transfer armed: route set, waiting for iPhone to pick Car Thing as output")
        self._sync()

    async def deactivate(self):
        # Transfer выключен: останавливаем аудиопоток и source. Standby-loop
        # принадлежит operation_mode: Play Now должен гасить его через
        # apply_operation_mode(), Коммутатор может держать его живым.
        self.model.transfer_active = False
        try:
            self.bridge.state.transfer_active = False
        except Exception:
            pass
        await self.bridge.stop_receiver_stream()
        # [CLAUDE 2026-06-02] CarThing-инициируемый возврат «на BLE»: сами рвём classic-ACL
        # источника (iPhone). BLE (AMS/ANCS/CTS) НЕ трогаем — он постоянный независимый
        # транспорт. Симметрия connect_source: весь тумблер classic держит CarThing.
        await self.bridge.disconnect_source()
        await self.orch.set_transfer_connectable(False)
        await self.orch.on_a2dp_state(False)
        self._sync()

    # ── Routes-view intents ──────────────────────────────────────────────────
    async def rescan(self):
        try:
            await self.bridge.scan_trusted_speakers()
        except Exception as e:
            logger.warning("speaker rescan failed: %s", e)
        self._sync()

    async def select(self, address):
        try:
            self.bridge.state.select_route_speaker(address)
            self.bridge.state.transfer_status = "standby"
            await self.bridge.ensure_trusted_speakers_connected()
        except Exception as e:
            logger.warning("speaker select failed: %s", e)
        self._sync()

    # ── входящий classic A2DP от iPhone (выбрал Car Thing аудиовыходом) ───────
    async def on_incoming_classic(self, connection):
        try:
            await self.bridge.handle_classic_connection(connection)
        except Exception as e:
            logger.warning("handle classic conn failed: %s", e)
        await self.orch.on_a2dp_state(True)
        self.model.transfer_active = True
        self._sync()

    def _sync(self):
        statuses = self.bridge.speaker_statuses()
        self.model.speakers = statuses
        active = next((speaker for speaker in statuses if speaker.get("active")), None)
        standby = next((speaker for speaker in statuses if speaker.get("standby")), None)
        visible = active or standby or next((speaker for speaker in statuses if speaker.get("connected")), None)
        ready = bool(active and active.get("standby"))
        self.model.speaker_connected = bool(visible and visible.get("connected"))
        self.model.speaker_name = visible.get("address") if visible else None
        status = getattr(self.bridge.state, "transfer_status", "")
        if status:
            self.model.mode_status = status if not ready else "transfer connected"
        self.on_change()
