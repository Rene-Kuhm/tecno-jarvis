import asyncio
import time
import re
import threading
import json
import sys
import traceback
from pathlib import Path

import numpy as np
import sounddevice as sd
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
)
from memory.session_memory import (
    start_session, record_tool_call, record_conversation,
    get_session_context,
)
from core.config import (
    load_config, get_audio_device,
    load_system_prompt,
)
from core.tools import TOOL_DECLARATIONS
from core.provider import get_live_client, get_live_types
from core.mcp_manager import get_mcp_manager

types = get_live_types()

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024


def _describe_audio_device(kind: str) -> str:
    device = get_audio_device(kind)
    if device is None:
        return "system default"
    try:
        info = sd.query_devices(device, kind)
        return f"{device}: {info['name']}"
    except Exception:
        return f"device {device}"


_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self.ui.on_text_command = self._on_text_command
        self._turn_done_event: asyncio.Event | None = None
        self._mic_last_publish = 0.0
        self._mic_last_signal_at: float | None = None
        self._mic_status = "offline"
        self._runtime_last_publish = 0.0
        self._last_realtime_sent_at: float | None = None
        self._last_realtime_recv_at: float | None = None
        self._active_tool = "none"
        self._reconnect_attempt = 0
        self._last_failure_source = "connect"

    def _publish_mic_diag(self, status: str, level: float = 0.0, *, force: bool = False, detail: str = ""):
        now = time.monotonic()
        if not force and status == self._mic_status and (now - self._mic_last_publish) < 0.2:
            return

        age = None
        if self._mic_last_signal_at is not None:
            age = max(0.0, now - self._mic_last_signal_at)

        self._mic_status = status
        self._mic_last_publish = now
        self.ui.update_audio_diag(status=status, level=level, age=age, detail=detail)

    def _publish_runtime_status(self, session: str, stream: str = "idle", *, force: bool = False, detail: str = ""):
        now = time.monotonic()
        if not force and (now - self._runtime_last_publish) < 0.2:
            return

        last_tx_age = None if self._last_realtime_sent_at is None else max(0.0, now - self._last_realtime_sent_at)
        last_rx_age = None if self._last_realtime_recv_at is None else max(0.0, now - self._last_realtime_recv_at)
        out_queue = self.out_queue.qsize() if self.out_queue is not None else 0
        in_queue = self.audio_in_queue.qsize() if self.audio_in_queue is not None else 0

        self._runtime_last_publish = now
        self.ui.update_runtime_status(
            session=session,
            stream=stream,
            last_tx_age=last_tx_age,
            last_rx_age=last_rx_age,
            active_tool=self._active_tool,
            out_queue=out_queue,
            in_queue=in_queue,
            detail=detail,
        )

    def _reset_live_state(self):
        self.session = None
        self._loop = None
        self.audio_in_queue = None
        self.out_queue = None
        self._turn_done_event = None
        self._active_tool = "none"
        self._last_realtime_sent_at = None
        self._last_realtime_recv_at = None

    def _raise_component_error(self, source: str, error: Exception):
        self._last_failure_source = source
        raise RuntimeError(f"{source}: {error}") from error

    @staticmethod
    def _describe_session_error(error: Exception) -> tuple[str, bool]:
        text = str(error).strip() or error.__class__.__name__
        lower = text.lower()

        if any(token in lower for token in ["api key", "unauthorized", "permission denied", "authentication", "403", "401"]):
            return (f"Authentication failed: {text}", True)
        if any(token in lower for token in ["quota", "rate limit", "429", "resource exhausted"]):
            return (f"Rate or quota limit hit: {text}", False)
        if any(token in lower for token in ["timeout", "timed out", "connection", "network", "temporarily unavailable", "unavailable", "dns"]):
            return (f"Transient network error: {text}", False)
        return (text, False)

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        session_ctx = get_session_context()

        parts = [time_ctx]
        if session_ctx:
            parts.append(session_ctx)
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")
        self._active_tool = name
        self._publish_runtime_status("online", "tool", force=True, detail=f"Executing tool: {name}")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "mcp_list_tools":
                result = await get_mcp_manager().list_tools_text(args.get("server") or None)

            elif name == "mcp_call":
                result = await get_mcp_manager().call_tool_text(
                    args.get("server", ""),
                    args.get("tool", ""),
                    args.get("arguments_json") or None,
                )

            elif name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = "Vision module activated. Stay completely silent — vision module will speak directly."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                def _shutdown():
                    import time, os
                    time.sleep(1)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        self._active_tool = "none"
        self._publish_runtime_status("online", "idle", force=True, detail=f"Last tool: {name}")

        record_tool_call(name, str(args)[:120], str(result)[:200])

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            try:
                msg = await self.out_queue.get()
                self._last_realtime_sent_at = time.monotonic()
                self._publish_runtime_status("online", "sending", detail="Sending audio/text to Gemini Live")
                await self.session.send_realtime_input(media=msg)
            except Exception as e:
                self._raise_component_error("send", e)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()
        signal_threshold = 0.015
        input_device = get_audio_device("input")
        input_label = _describe_audio_device("input")

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking

            peak_level = (
                float(np.max(np.abs(indata.astype(np.float32)))) / 32768.0
                if len(indata)
                else 0.0
            )
            now = time.monotonic()
            if peak_level >= signal_threshold:
                self._mic_last_signal_at = now

            if self.ui.muted:
                diag_status = "muted"
            elif jarvis_speaking:
                diag_status = "paused"
            elif peak_level >= signal_threshold:
                diag_status = "hearing"
            else:
                diag_status = "silent"

            loop.call_soon_threadsafe(self._publish_mic_diag, diag_status, peak_level)

            if not jarvis_speaking and not self.ui.muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )

        try:
            with sd.InputStream(
                device=input_device,
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                self._publish_mic_diag("ready", force=True, detail=f"Using mic: {input_label}")
                self.ui.write_log(f"SYS: Microphone stream open ({input_label}).")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            self._publish_mic_diag("error", force=True, detail=str(e))
            self._raise_component_error("mic", e)

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        self._last_realtime_recv_at = time.monotonic()
                        self._publish_runtime_status("online", "receiving", detail="Receiving realtime audio from Gemini Live")
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                            out_buf = []

                            if full_in or full_out:
                                record_conversation(full_in, full_out)

                    if response.tool_call:
                        self._last_realtime_recv_at = time.monotonic()
                        self._publish_runtime_status("online", "tool", force=True, detail="Gemini requested tool execution")
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            self._raise_component_error("recv", e)

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")
        output_device = get_audio_device("output")
        output_label = _describe_audio_device("output")

        stream = sd.RawOutputStream(
            device=output_device,
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        self.ui.write_log(f"SYS: Audio output ready ({output_label}).")

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            self._raise_component_error("play", e)
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        client = get_live_client()

        reconnect_delay = 3.0
        max_reconnect_delay = 30.0

        while True:
            wait_seconds = reconnect_delay
            try:
                print("[JARVIS] 🔌 Connecting...")
                self.ui.set_state("THINKING")
                self._publish_runtime_status("connecting", "idle", force=True, detail="Connecting to Gemini Live...")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self._last_failure_source = "connect"
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)
                    self._turn_done_event = asyncio.Event()

                    print("[JARVIS] ✅ Connected.")
                    start_session()
                    if self._reconnect_attempt > 0:
                        self.ui.write_log(f"SYS: Live session recovered after {self._reconnect_attempt} retry attempt(s).")
                    self._reconnect_attempt = 0
                    reconnect_delay = 3.0
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")
                    self._publish_mic_diag("offline", force=True, detail="Voice session connected. Opening microphone stream...")
                    self._publish_runtime_status("online", "idle", force=True, detail="Live session connected.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                self._reconnect_attempt += 1
                detail, fatal = self._describe_session_error(e)
                source = self._last_failure_source or "connect"
                print(f"[JARVIS] ⚠️ {source}: {detail}")
                traceback.print_exc()
                self.ui.write_log(f"ERR: Live session failed in {source} ({detail})")
                self._publish_mic_diag("offline", force=True, detail=f"{source}: {detail}")
                if fatal:
                    self._publish_runtime_status("error", "idle", force=True, detail=f"Fatal {source} error. Fix credentials/config before retrying.")
                    self.set_speaking(False)
                    self.ui.set_state("THINKING")
                    self._reset_live_state()
                    print("[JARVIS] ⛔ Fatal live-session error. Waiting 30s before retry...")
                    await asyncio.sleep(30)
                    continue

                self._publish_runtime_status(
                    "retrying",
                    "idle",
                    force=True,
                    detail=f"{source} failed. Reconnect attempt {self._reconnect_attempt} in {wait_seconds:.0f}s...",
                )
                self.ui.write_log(f"SYS: {source} reconnect attempt {self._reconnect_attempt} in {wait_seconds:.0f}s")
                reconnect_delay = min(reconnect_delay * 1.6, max_reconnect_delay)
            self.set_speaking(False)
            self.ui.set_state("THINKING")
            self._reset_live_state()
            print(f"[JARVIS] 🔄 Reconnecting in {wait_seconds:.0f}s...")
            await asyncio.sleep(wait_seconds)

def main():
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()

        try:
            from actions.screen_processor import warmup_session
            warmup_session(player=ui)
            print("[JARVIS] 👁️ Vision session pre-warmed")
        except Exception as e:
            print(f"[JARVIS] ⚠️ Vision warmup skipped: {e}")

        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
