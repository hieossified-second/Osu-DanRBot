import sqlite3
import asyncio
import os
import re
import json
import urllib.parse
from urllib.parse import urlparse
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands, tasks
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ==============================================================================
# SERVIDOR HTTP SECUNDÁRIO PARA O RENDER (Garante Plano Gratuito / Web Service)
# ==============================================================================
async def handle_ping(request):
    return web.Response(text="Bot do Discord ativo e operante!")

async def iniciar_servidor_web():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"[Web Server] Escutando na porta {port} para o Render...")

# ==============================================================================
# CONFIGURAÇÃO DO TOKEN E HIERARQUIA DOS DANS
# ==============================================================================
TOKEN = os.getenv("DISCORD_TOKEN")

ORDEM_DANS = [
    "1st", "2nd", "3rd", "4th", "5th", 
    "6th", "7th", "8th", "9th", "10th", 
    "alpha", "beta", "gamma", "delta", 
    "epsilon", "zeta", "eta"
]

MAPA_DANS = {
    "1st": "1st Dan",
    "2nd": "2nd Dan",
    "3rd": "3rd Dan",
    "4th": "4th Dan",
    "5th": "5th Dan",
    "6th": "6th Dan",
    "7th": "7th Dan",
    "8th": "8th Dan",
    "9th": "9th Dan",
    "10th": "10th Dan",
    "alpha": "Alpha",
    "beta": "Beta",
    "gamma": "Gamma",
    "delta": "Delta",
    "epsilon": "Epsilon",
    "zeta": "Zeta",
    "eta": "Eta"
}

# ==============================================================================
# BANCO DE DADOS (SQLite)
# ==============================================================================
def iniciar_banco():
    conn = sqlite3.connect("usuarios.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vinculados (
            discord_id INTEGER PRIMARY KEY,
            url_perfil TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def salvar_usuario(discord_id: int, url_perfil: str):
    conn = sqlite3.connect("usuarios.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO vinculados (discord_id, url_perfil)
        VALUES (?, ?)
    """, (discord_id, url_perfil))
    conn.commit()
    conn.close()

def obter_todos_usuarios():
    conn = sqlite3.connect("usuarios.db")
    cursor = conn.cursor()
    cursor.execute("SELECT discord_id, url_perfil FROM vinculados")
    dados = cursor.fetchall()
    conn.close()
    return dados

# ==============================================================================
# LÓGICA DE PROCESSAMENTO DO DAN (REBAIXAMENTO DE LOW)
# ==============================================================================
def processar_dan_com_low(dan_texto_raw: str) -> str | None:
    texto = dan_texto_raw.lower().strip()
    
    dan_base = None
    for d in ORDEM_DANS:
        pattern = r'\b' + re.escape(d) + r'\b'
        if re.search(pattern, texto):
            dan_base = d
            break
            
    if not dan_base:
        for d in ORDEM_DANS:
            if texto.startswith(d):
                dan_base = d
                break

    if not dan_base:
        return None

    eh_low = ("-" in texto) or ("low" in texto)
    
    if eh_low:
        idx = ORDEM_DANS.index(dan_base)
        if idx > 0:
            dan_final = ORDEM_DANS[idx - 1]
            print(f"[Regra Low] Detectado '{dan_texto_raw}' (LOW). Rebaixado de '{dan_base}' para -> '{dan_final}'")
            return dan_final
        else:
            print(f"[Regra Low] Jogador é '{dan_base}' Low, mas já está no menor Dan disponível.")
            return dan_base

    print(f"[Regra Normal] Detectado '{dan_texto_raw}'. Dan final -> '{dan_base}'")
    return dan_base

async def extrair_dan(session: aiohttp.ClientSession, url_perfil: str) -> str | None:
    try:
        url_limpa = url_perfil.strip()
        url_decodificada = urllib.parse.unquote(url_limpa)
        parsed = urlparse(url_decodificada)
        
        caminho_base = parsed.path.rstrip('/')
        for sub in ['/skills', '/reform', '/scores', '/top']:
            if caminho_base.endswith(sub):
                caminho_base = caminho_base[:-len(sub)]
                break

        urls_para_testar = [
            f"{parsed.scheme}://{parsed.netloc}{caminho_base}/skills",
            f"{parsed.scheme}://{parsed.netloc}{caminho_base}"
        ]

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            for url_final in urls_para_testar:
                print(f"[Playwright] Acessando URL: {url_final}")
                try:
                    await page.goto(url_final, wait_until="networkidle", timeout=20000)
                except Exception:
                    continue
                
                content = await page.content()
                soup = BeautifulSoup(content, "html.parser")

                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    alt = img.get("alt", "").strip()
                    
                    if "/images/dans/" in src:
                        if alt:
                            print(f"[Sucesso Alt Img] Dan encontrado: '{alt}'")
                            await browser.close()
                            return processar_dan_com_low(alt)
                        
                        caminho_src = urlparse(src).path
                        nome_arquivo = os.path.basename(caminho_src)
                        dan_raw = os.path.splitext(nome_arquivo)[0]
                        if dan_raw:
                            print(f"[Sucesso Src Img] Dan encontrado: '{dan_raw}'")
                            await browser.close()
                            return processar_dan_com_low(dan_raw)

                for button in soup.find_all("button"):
                    title = button.get("title", "")
                    if "Regular dan estimate:" in title:
                        match = re.search(r'~([a-zA-Z0-9_\-\+\s]+?),', title)
                        if match:
                            dan_bruto = match.group(1).strip()
                            print(f"[Sucesso Title Button] Dan encontrado: '{dan_bruto}'")
                            await browser.close()
                            return processar_dan_com_low(dan_bruto)

            await browser.close()

        print(f"[Aviso] Nenhum registo de Dan foi localizado no perfil.")

    except Exception as e:
        print(f"[Erro Scraping] Falha ao processar {url_perfil}: {e}")
    return None

# ==============================================================================
# CONFIGURAÇÃO DO BOT DISCORD
# ==============================================================================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def atualizar_cargo_membro(guild: discord.Guild, membro: discord.Member, dan_chave: str):
    if dan_chave not in MAPA_DANS:
        return
    
    nome_cargo_alvo = MAPA_DANS[dan_chave]
    cargo_alvo = discord.utils.get(guild.roles, name=nome_cargo_alvo)
    
    if not cargo_alvo:
        return

    todos_cargos_dan = set(MAPA_DANS.values())
    cargos_dan_existentes = [
        role for role in membro.roles if role.name in todos_cargos_dan
    ]
    
    try:
        if cargo_alvo not in membro.roles:
            if cargos_dan_existentes:
                await membro.remove_roles(*cargos_dan_existentes)
            await membro.add_roles(cargo_alvo)
            print(f"[Sucesso] Cargo '{nome_cargo_alvo}' concedido a {membro.display_name} no servidor '{guild.name}'!")
    except discord.Forbidden:
        print(f"[Erro Permissão] O cargo do bot precisa de estar no TOPO da lista no servidor '{guild.name}'.")
    except Exception as e:
        print(f"[Erro de Atribuição] {e}")

# ==============================================================================
# TAREFA AGENDADA
# ==============================================================================
@tasks.loop(minutes=10)
async def sincronizar_cargos_loop():
    usuarios = obter_todos_usuarios()
    if not usuarios:
        return

    async with aiohttp.ClientSession() as session:
        for discord_id, url_perfil in usuarios:
            dan_detectado = await extrair_dan(session, url_perfil)
            if not dan_detectado:
                continue

            for guild in bot.guilds:
                try:
                    membro = guild.get_member(discord_id) or await guild.fetch_member(discord_id)
                    if membro:
                        await atualizar_cargo_membro(guild, membro, dan_detectado)
                except discord.NotFound:
                    continue
                except Exception as e:
                    print(f"[Aviso Loop] Erro ao buscar membro {discord_id} em {guild.name}: {e}")

            await asyncio.sleep(2)

@sincronizar_cargos_loop.before_loop
async def antes_do_loop():
    await bot.wait_until_ready()

# ==============================================================================
# EVENTOS E COMANDOS
# ==============================================================================
@bot.event
async def on_ready():
    iniciar_banco()
    print(f"Bot online em {len(bot.guilds)} servidores como {bot.user}")
    
    try:
        synced = await bot.tree.sync()
        print(f"Sincronizados {len(synced)} comandos Slash globalmente!")
    except Exception as e:
        print(f"Erro ao sincronizar comandos globalmente: {e}")
    
    if not sincronizar_cargos_loop.is_running():
        sincronizar_cargos_loop.start()

@bot.tree.command(name="registrar", description="Registra seu perfil do mania!tracker para sincronizar seu Dan.")
@app_commands.describe(url="Link do seu perfil no mania-tracker.com")
async def registrar(interaction: discord.Interaction, url: str):
    # 1. AVISA O DISCORD IMEDIATAMENTE QUE O BOT ESTÁ A PROCESSAR (Evita o erro "Não respondeu")
    await interaction.response.defer(ephemeral=True)
    
    try:
        url_limpa = urllib.parse.unquote(url.strip())
        match = re.search(r'https?://[^\s\)]+', url_limpa)
        if match:
            url_limpa = match.group(0)
        
        url_limpa = url_limpa.rstrip(">)]").lstrip("<([")

        if "mania-tracker.com" not in url_limpa.lower():
            await interaction.followup.send("URL inválida! Por favor, envie o link do mania-tracker.com.", ephemeral=True)
            return

        salvar_usuario(interaction.user.id, url_limpa)
        
        # 2. FAZ O SCRAPING COM O PLAYWRIGHT (Pode demorar vários segundos agora sem dar erro)
        async with aiohttp.ClientSession() as session:
            dan_detectado = await extrair_dan(session, url_limpa)

        if dan_detectado and dan_detectado in MAPA_DANS:
            membro = interaction.guild.get_member(interaction.user.id) or await interaction.guild.fetch_member(interaction.user.id)
            await atualizar_cargo_membro(interaction.guild, membro, dan_detectado)
            
            nome_cargo = MAPA_DANS[dan_detectado]
            await interaction.followup.send(
                f"Perfil vinculado com sucesso! Seu cargo foi atualizado para **{nome_cargo}** neste servidor.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "Perfil registrado! O bot tentará atualizar seu Dan no próximo ciclo automático.",
                ephemeral=True
            )
    except Exception as e:
        print(f"[Erro no Comand Registrar] {e}")
        await interaction.followup.send("Ocorreu um erro ao processar o seu registro. Tente novamente em instantes.", ephemeral=True)
# ==============================================================================
# INICIALIZAÇÃO
# ==============================================================================
async def main():
    if TOKEN:
        await iniciar_servidor_web()
        async with bot:
            await bot.start(TOKEN)
    else:
        print("ERRO: A variável de ambiente DISCORD_TOKEN não foi configurada!")

if __name__ == "__main__":
    asyncio.run(main())