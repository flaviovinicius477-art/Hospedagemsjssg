import os
import re
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from supabase import create_client, Client
Carrega variáveis do arquivo .env
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
Configurações do Pix
PIX_CHAVE = os.getenv("PIX_CHAVE", "sua-chave-pix-aqui")
PIX_NOME = os.getenv("PIX_NOME", "NOME RECEBEDOR")
PIX_CIDADE = os.getenv("PIX_CIDADE", "SAO PAULO")
Inicializa cliente Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
--- GERADOR DE PAYLOAD PIX EMV (COPIA E COLA) ---
def calcular_crc16(payload: str) -> str:
"""Calcula o CRC16-CCITT (0xFFFF) exigido pelo padrão do Banco Central."""
crc = 0xFFFF
for char in payload.encode('utf-8'):
crc ^= (char << 8)
for _ in range(8):
if (crc & 0x8000):
crc = ((crc << 1) ^ 0x1021) & 0xFFFF
else:
crc = (crc << 1) & 0xFFFF
return f"{crc:04X}"
def gerar_payload_pix(chave: str, nome: str, cidade: str, valor: float, identificador: str) -> str:
"""Gera o código 'Pix Copia e Cola' estático completo."""
def format_tlv(id_tag: str, val: str) -> str:
return f"{id_tag}{len(val):02d}{val}"
# Limpeza de strings conforme restrições EMV
nome_clean = re.sub(r'[^a-zA-Z0-9 ]', '', nome)[:25].upper()
cidade_clean = re.sub(r'[^a-zA-Z0-9 ]', '', cidade)[:15].upper()
txid_clean = re.sub(r'[^a-zA-Z0-9]', '', identificador)[:25] or "***"
merchant_account_info = (
format_tlv("00", "br.gov.bcb.pix") +
format_tlv("01", chave)
)
additional_data = format_tlv("05", txid_clean)
payload = (
format_tlv("00", "01") +                             # Format Indicator
format_tlv("26", merchant_account_info) +            # Conta do Recebedor
format_tlv("52", "0000") +                           # Merchant Category Code
format_tlv("53", "986") +                            # BRL Currency Code
format_tlv("54", f"{valor:.2f}") +                   # Valor do Produto
format_tlv("58", "BR") +                             # Country Code
format_tlv("59", nome_clean) +                       # Nome
format_tlv("60", cidade_clean) +                     # Cidade
format_tlv("62", additional_data) +                  # Identificador
"6304"                                               # CRC16 Marker
)
return payload + calcular_crc16(payload)
--- SETUP DO BOT DISCORD ---
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
class SalesBot(commands.Bot):
def init(self):
super().init(command_prefix="!", intents=intents)
async def setup_hook(self):
await self.tree.sync()
print("⚡ Comandos slash sincronizados com sucesso!")
bot = SalesBot()
--- INTERFACE DE PAGINAÇÃO DO CATÁLOGO (/COMPRAR) ---
class CatalogoView(discord.ui.View):
def init(self, produtos: list):
super().init(timeout=300)
self.produtos = produtos
self.index = 0
def criar_embed(self) -> discord.Embed:
produto = self.produtos[self.index]
embed = discord.Embed(
title=produto.get("nome", "Produto Sem Nome"),
description=produto.get("descricao", "Sem descrição disponível."),
color=discord.Color.blurple()
)
preco = float(produto.get("preco", 0.0))
embed.add_field(name="💰 Preço", value=f"R$ {preco:.2f}", inline=True)
embed.set_footer(text=f"Produto {self.index + 1} de {len(self.produtos)}")
if produto.get("imagem_url"):
embed.set_image(url=produto.get("imagem_url"))
return embed
@discord.ui.button(label="⬅️ Anterior", style=discord.ButtonStyle.secondary)
async def anterior(self, interaction: discord.Interaction, button: discord.ui.Button):
if self.index > 0:
self.index -= 1
await interaction.response.edit_message(embed=self.criar_embed(), view=self)
else:
await interaction.response.defer()
@discord.ui.button(label="➡️ Próximo", style=discord.ButtonStyle.secondary)
async def proximo(self, interaction: discord.Interaction, button: discord.ui.Button):
if self.index < len(self.produtos) - 1:
self.index += 1
await interaction.response.edit_message(embed=self.criar_embed(), view=self)
else:
await interaction.response.defer()
@discord.ui.button(label="🛒 Comprar", style=discord.ButtonStyle.success)
async def comprar(self, interaction: discord.Interaction, button: discord.ui.Button):
await interaction.response.defer(ephemeral=True)
produto = self.produtos[self.index]
guild = interaction.guild
user = interaction.user
# Permissões do canal privado
overwrites = {
guild.default_role: discord.PermissionOverwrite(read_messages=False),
user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
}
channel_name = f"carrinho-{user.name}".lower().replace(".", "")
canal_privado = await guild.create_text_channel(
name=channel_name,
overwrites=overwrites,
reason=f"Carrinho criado por {user.name}"
)
# Salva o pedido pendente no Supabase
res = supabase.table("pedidos").insert({
"usuario_id": str(user.id),
"usuario_tag": str(user),
"produto_id": produto["id"],
"produto_nome": produto["nome"],
"valor": float(produto["preco"]),
"status": "pendente",
"canal_id": str(canal_privado.id)
}).execute()
pedido_id = res.data[0]["id"] if res.data else "0"
# Identificador formatado com o usuário
identificador_pix = f"USER{user.id}"[:25]
# Gera o Pix Copia e Cola
payload_pix = gerar_payload_pix(
chave=PIX_CHAVE,
nome=PIX_NOME,
cidade=PIX_CIDADE,
valor=float(produto["preco"]),
identificador=identificador_pix
)
embed_carrinho = discord.Embed(
title="💳 Pedido Criado - Chave Pix para Pagamento",
description=f"Olá {user.mention}, seu pedido foi gerado!\n\n"
f"Produto: {produto['nome']}\n"
f"Valor: R$ {float(produto['preco']):.2f}\n"
f"ID do Pedido: {pedido_id}\n\n"
f"Copie e cole a chave abaixo no aplicativo do seu banco:",
color=discord.Color.green()
)
embed_carrinho.add_field(
name="📋 Pix Copia e Cola",
value=f"\n{payload_pix}\n",
inline=False
)
embed_carrinho.set_footer(text="Aguarde a validação do pagamento pela equipe de atendimento.")
await canal_privado.send(content=f"{user.mention}", embed=embed_carrinho)
await interaction.followup.send(content=f"✅ Seu carrinho privado foi criado em {canal_privado.mention}!", ephemeral=True)
--- INTERFACE DE APROVAÇÃO/RECUSA DE PEDIDOS (/PEDIDOS) ---
class ConfirmacaoPedidoView(discord.ui.View):
def init(self, pedido_id: int):
super().init(timeout=None)
self.pedido_id = pedido_id
@discord.ui.button(label="✅ Confirmar Compra", style=discord.ButtonStyle.success, custom_id="confirmar_pedido")
async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
# Atualiza status no banco
res = supabase.table("pedidos").update({"status": "aprovado"}).eq("id", self.pedido_id).execute()
if res.data:
pedido = res.data[0]
canal = interaction.guild.get_channel(int(pedido["canal_id"]))
if canal:
embed = discord.Embed(
title="🎉 Pagamento Confirmado!",
description="Sua compra foi aprovada com sucesso. Agradecemos a preferência!",
color=discord.Color.green()
)
await canal.send(embed=embed)
# Desativa os botões
for child in self.children:
child.disabled = True
await interaction.response.edit_message(content=f"🟢 Pedido #{self.pedido_id} APROVADO por {interaction.user.mention}.", view=self)
@discord.ui.button(label="❌ Negar Compra", style=discord.ButtonStyle.danger, custom_id="negar_pedido")
async def negar(self, interaction: discord.Interaction, button: discord.ui.Button):
res = supabase.table("pedidos").update({"status": "recusado"}).eq("id", self.pedido_id).execute()
if res.data:
pedido = res.data[0]
canal = interaction.guild.get_channel(int(pedido["canal_id"]))
if canal:
embed = discord.Embed(
title="❌ Compra Recusada",
description="O pagamento do seu pedido não foi aprovado ou foi cancelado.",
color=discord.Color.red()
)
await canal.send(embed=embed)
for child in self.children:
child.disabled = True
await interaction.response.edit_message(content=f"🔴 Pedido #{self.pedido_id} RECUSADO por {interaction.user.mention}.", view=self)
--- COMANDOS SLASH ---
@bot.tree.command(name="comprar", description="Exibe o catálogo de produtos para compra")
@app_commands.guild_only()
async def comprar_cmd(interaction: discord.Interaction):
if not supabase:
await interaction.response.send_message("❌ Erro ao conectar ao banco de dados Supabase.", ephemeral=True)
return
res = supabase.table("produtos").select("*").execute()
produtos = res.data
if not produtos:
await interaction.response.send_message("📦 Nenhum produto cadastrado no catálogo no momento.", ephemeral=True)
return
view = CatalogoView(produtos)
await interaction.response.send_message(embed=view.criar_embed(), view=view, ephemeral=True)
@bot.tree.command(name="pedidos", description="Lista os pedidos pendentes (Somente Creator e Creator 2°)")
@app_commands.guild_only()
async def pedidos_cmd(interaction: discord.Interaction):
# Verificação de cargos autorizados
cargos_permitidos = {"Creator", "Creator 2°"}
cargos_usuario = {role.name for role in interaction.user.roles}
if not cargos_permitidos.intersection(cargos_usuario):
await interaction.response.send_message("⛔ Você não tem permissão para usar este comando.", ephemeral=True)
return
res = supabase.table("pedidos").select("*").eq("status", "pendente").execute()
pedidos_pendentes = res.data
if not pedidos_pendentes:
await interaction.response.send_message("✅ Nenhum pedido pendente no momento.", ephemeral=True)
return
await interaction.response.send_message("📋 Lista de Pedidos Pendentes:", ephemeral=True)
for pedido in pedidos_pendentes:
embed = discord.Embed(
title=f"Pedido #{pedido['id']}",
color=discord.Color.gold()
)
embed.add_field(name="Cliente", value=f"<@{pedido['usuario_id']}> ({pedido['usuario_tag']})", inline=True)
embed.add_field(name="Produto", value=pedido['produto_nome'], inline=True)
embed.add_field(name="Valor", value=f"R$ {float(pedido['valor']):.2f}", inline=True)
embed.add_field(name="Canal", value=f"<#{pedido['canal_id']}>", inline=False)
view = ConfirmacaoPedidoView(pedido_id=pedido['id'])
await interaction.followup.send(embed=embed, view=view, ephemeral=True)
@bot.event
async def on_ready():
print(f"🤖 Bot conectado como {bot.user} (ID: {bot.user.id})")
if name == "main":
if DISCORD_TOKEN:
bot.run(DISCORD_TOKEN)
else:
print("❌ DIGITE O DISCORD_TOKEN NO ARQUIVO .ENV")