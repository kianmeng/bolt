defmodule Bolt.USW do
  @moduledoc "USW - Uncomplicated Spam Wall"

  alias Bolt.ErrorFormatters
  alias Bolt.Events.Handler
  alias Bolt.Helpers
  alias Bolt.Humanizer
  alias Bolt.ModLog
  alias Bolt.Repo
  alias Bolt.Schema.Infraction
  alias Bolt.Schema.USWPunishmentConfig
  alias Bolt.Schema.USWRuleConfig
  alias Bolt.USW.Deduplicator
  alias Bolt.USW.Escalator
  alias Bolt.USW.Rules
  alias Nostrum.Api
  alias Nostrum.Cache.GuildCache
  alias Nostrum.Cache.Me
  alias Nostrum.Snowflake
  alias Nostrum.Struct.Message
  alias Nostrum.Struct.User
  import Ecto.Query, only: [from: 2]
  require Logger

  @filter_name_to_function %{
    "BURST" => &Rules.Burst.apply/4,
    "DUPLICATES" => &Rules.Duplicates.apply/4,
    "LINKS" => &Rules.Links.apply/4,
    "MENTIONS" => &Rules.Mentions.apply/4,
    "NEWLINES" => &Rules.Newlines.apply/4
  }

  @spec config_to_fn(Message.t(), USWRuleConfig) :: (() -> :action | :passthrough)
  defp config_to_fn(msg, config) do
    fn ->
      func = Map.fetch!(@filter_name_to_function, config.rule)

      snowflake_interval_seconds_ago =
        DateTime.utc_now()
        |> DateTime.to_unix()
        |> Kernel.-(config.interval)
        |> DateTime.from_unix!()
        |> Snowflake.from_datetime!()

      func.(msg, config.count, config.interval, snowflake_interval_seconds_ago)
    end
  end

  @doc """
  Apply spam filters on the given message.

  ## Return value
  If the message pops a spam filter and the filter takes action,
  `:action` is returned. Otherwise, `nil` is returned.
  """
  @spec apply(Message.t()) :: nil | :action
  def apply(msg) do
    # https://github.com/rrrene/credo/issues/634
    query =
      from(
        config in USWRuleConfig,
        where: [guild_id: ^msg.guild_id],
        select: config
      )

    query
    |> Repo.all()
    |> Stream.map(&config_to_fn(msg, &1))
    |> Enum.find(&(&1.() == :action))
  end

  @spec calculate_expiry(pos_integer(), non_neg_integer(), escalator_enabled :: boolean()) ::
          pos_integer()
  defp calculate_expiry(duration, escalator_level, true),
    do: duration + duration * escalator_level

  defp calculate_expiry(duration, _escalator_level, false), do: duration

  @spec maybe_bump_escalator(Snowflake.t(), pos_integer(), escalator_enabled :: boolean()) ::
          {:ok, reference()} | :ok
  defp maybe_bump_escalator(_user_id, _expiry_seconds, false), do: :ok

  defp maybe_bump_escalator(user_id, expiry_seconds, true),
    do: Escalator.bump(user_id, expiry_seconds * 1000 * 2)

  @spec level_description(escalator_enabled :: boolean(), escalator_level :: non_neg_integer()) ::
          String.t()
  defp level_description(false, _), do: ""
  defp level_description(true, 0), do: ""
  defp level_description(true, level), do: "- escalation level #{level}"

  @spec execute_config(USWPunishmentConfig, User.t(), String.t()) ::
          (() -> {:ok, Message.t()} | Api.error() | :noop)
  defp execute_config(
         %USWPunishmentConfig{
           guild_id: guild_id,
           escalate: escalator_enabled,
           punishment: "TEMPROLE",
           data: %{"role_id" => role_id},
           duration: expiry_seconds
         },
         user,
         description
       ) do
    case Api.add_guild_member_role(guild_id, user.id, role_id) do
      {:ok} ->
        escalator_level = Escalator.level_for(user.id)
        expiry_seconds = calculate_expiry(expiry_seconds, escalator_level, escalator_enabled)
        Deduplicator.add(user.id, expiry_seconds * 1000)
        level_string = level_description(escalator_enabled, escalator_level)
        maybe_bump_escalator(user.id, expiry_seconds, escalator_enabled)

        infraction_map = %{
          type: "temprole",
          guild_id: guild_id,
          user_id: user.id,
          actor_id: Me.get().id,
          reason: "(automod) #{description}#{level_string}",
          expires_at:
            DateTime.utc_now()
            |> DateTime.to_unix()
            |> Kernel.+(expiry_seconds)
            |> DateTime.from_unix!(),
          data: %{"role_id" => role_id}
        }

        {:ok, %Infraction{id: infraction_id}} = Handler.create(infraction_map)

        ModLog.emit(
          guild_id,
          "AUTOMOD",
          "added temporary role #{Humanizer.human_role(guild_id, role_id)} to #{Humanizer.human_user(user)}" <>
            " for #{expiry_seconds}s: #{description}#{level_string} (##{infraction_id})"
        )

        dm_user(guild_id, user)

      {:error, %{status_code: status, message: %{"message" => reason}}} ->
        ModLog.emit(
          guild_id,
          "AUTOMOD",
          "attempted adding temporary role #{Humanizer.human_role(guild_id, role_id)} to #{Humanizer.human_user(user)})" <>
            " but got API error: #{reason} (status code #{status})"
        )

      error ->
        ModLog.emit(
          guild_id,
          "AUTOMOD",
          "added temporary role #{Humanizer.human_role(guild_id, role_id)} to #{Humanizer.human_user(user)} " <>
            "but got an unexpected error: #{ErrorFormatters.fmt(nil, error)}"
        )
    end
  end

  defp execute_config(
         %USWPunishmentConfig{
           guild_id: guild_id,
           escalate: escalator_enabled,
           punishment: "TIMEOUT",
           duration: expiry_seconds
         },
         user,
         description
       ) do
    now = DateTime.utc_now()
    timeout_until = DateTime.add(now, expiry_seconds)

    case Api.modify_guild_member(guild_id, user.id, communication_disabled_until: timeout_until) do
      {:ok, _member} ->
        escalator_level = Escalator.level_for(user.id)
        expiry_seconds = calculate_expiry(expiry_seconds, escalator_level, escalator_enabled)
        Deduplicator.add(user.id, expiry_seconds * 1000)
        level_string = level_description(escalator_enabled, escalator_level)
        maybe_bump_escalator(user.id, expiry_seconds, escalator_enabled)

        infraction = %{
          type: "timeout",
          guild_id: guild_id,
          user_id: user.id,
          actor_id: Me.get().id,
          reason: "(automod) #{description}#{level_string}",
          expires_at: timeout_until,
          data: %{}
        }

        changeset = Infraction.changeset(%Infraction{}, infraction)

        {:ok, %Infraction{id: infraction_id}} = Repo.insert(changeset)

        ModLog.emit(
          guild_id,
          "AUTOMOD",
          "timed out user #{Humanizer.human_user(user)}" <>
            " for #{expiry_seconds}s: #{description}#{level_string} (##{infraction_id})"
        )

        dm_user(guild_id, user)

      {:error, %{status_code: status, response: %{message: reason}}} ->
        ModLog.emit(
          guild_id,
          "AUTOMOD",
          "attempted timing out #{Humanizer.human_user(user)})" <>
            " but got API error: #{reason} (status code #{status})"
        )

      error ->
        ModLog.emit(
          guild_id,
          "AUTOMOD",
          "timed out #{Humanizer.human_user(user)} " <>
            "but got an unexpected error: #{ErrorFormatters.fmt(nil, error)}"
        )
    end
  end

  @spec preflight_checks(USWPunishmentConfig.t(), User.t()) :: boolean()
  defp preflight_checks(config, user) do
    %User{id: my_id} = Me.get()
    {:ok, bot_above_user} = Helpers.is_above(config.guild_id, my_id, user.id)
    !Deduplicator.contains?(user.id) && bot_above_user
  end

  @spec punish(Guild.id(), User.t(), String.t()) :: :noop | {:ok, Message.t()}
  def punish(guild_id, user, description) do
    case Repo.get(USWPunishmentConfig, guild_id) do
      nil ->
        :noop

      config ->
        case preflight_checks(config, user) do
          true ->
            execute_config(config, user, description)

          false ->
            :noop
        end
    end
  end

  @spec dm_user(Guild.id(), User.t()) :: :noop | {:ok, Message.t()} | Api.Error
  defp dm_user(guild_id, user) do
    case Api.create_dm(user.id) do
      {:ok, dm} ->
        guild_desc =
          case GuildCache.select(guild_id, & &1.name) do
            {:ok, guild_name} ->
              guild_name

            _error ->
              guild_id
          end

        Api.create_message(
          dm.id,
          "you have been muted on `#{guild_desc}` for triggering " <>
            "a spam filter. contact a staff member for further information"
        )

      _error ->
        :noop
    end
  end
end
