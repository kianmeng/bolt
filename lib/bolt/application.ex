defmodule Bolt.Application do
  use Application

  def start(_type, _args) do
    children = [
      Bolt.Repo,
      %{
        id: Bolt.Client,
        start: {Alchemy.Client, :start_link, [Application.fetch_env!(:bolt, :token), []]}
      }
    ]

    options = [strategy: :one_for_one, name: Bolt.Supervisor]
    startup_result = Supervisor.start_link(children, options)

    Application.fetch_env!(:bolt, :default_prefix)
    |> Alchemy.Cogs.set_prefix()

    load_cogs()
    startup_result
  end

  defp load_cogs() do
    alias Bolt.Commands

    use Commands.Echo
    use Commands.Help
    use Commands.GuildInfo
  end
end
