@dashboard.error
async def dashboard_error(self, inter: 
disnake.ApplicationCommandInteraction, error: 
commands.CommandError):
    if isinstance(error, commands.MissingRole):
        await inter.response.send_message("Você não tem permissão para usar este comando.", ephemeral=True)
    else:
        await inter.response.send_message("Ocorreu um erro inesperado.", ephemeral=True)
        print(f"Erro no comando /dashboard: {error}")

def setup(bot: commands.Bot):
    """Função que o disnake usa para carregar a cog."""
    bot.add_cog(StoreCog(bot))