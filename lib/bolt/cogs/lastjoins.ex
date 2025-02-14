defmodule Bolt.Cogs.LastJoins do
  @moduledoc false

  @behaviour Nosedrum.Command

  alias Bolt.{Constants, Helpers, Paginator, Parsers}
  alias Nosedrum.MessageCache.Agent, as: MessageCache
  alias Nosedrum.Predicates
  alias Nostrum.Api
  alias Nostrum.Cache.GuildCache
  alias Nostrum.Struct.Embed
  alias Nostrum.Struct.Guild.Member
  alias Nostrum.Struct.User

  # The default number of members shown in the response.
  @default_shown 15

  # Members shown per page.
  @shown_per_page @default_shown

  # The maximum number of members shown in the response.
  @maximum_shown @shown_per_page * 9

  @impl true
  def usage, do: ["lastjoins [options...]"]

  @impl true
  def description,
    do: """
    Display the most recently joined members.
    Requires the `MANAGE_MESSAGES` permission.

    The result of this command can be customized with the following options:
    `--no-roles`: Display only new members without any roles
    `--roles`: Display only new members with any roles
    `--total`: The total amount of members to display, defaults to #{@default_shown}, maximum is #{@maximum_shown}

    Returned members will be sorted by their account creation time.

    **Examples**:
    ```rs
    // display the #{@default_shown} most recently joined members
    .lastjoins

    // display the 30 most recently joined members that do not have a role assigned
    .lastjoins --total 10 --no-roles
    ```
    """

  @impl true
  def predicates, do: [&Predicates.guild_only/1, Predicates.has_permission(:manage_messages)]

  @impl true
  def parse_args(args) do
    OptionParser.parse(
      args,
      strict: [
        # --roles | --no-roles
        #   display only new members with or without roles
        roles: :boolean,
        # --total <int>
        #   the total amount of users to display
        total: :integer
      ]
    )
  end

  @impl true
  def command(msg, {options, _args, []}) do
    # we can avoid copying around things we don't care about by just selecting the members here
    case GuildCache.select(msg.guild_id, &Map.values(&1.members)) do
      {:ok, members} ->
        {limit, options} = Keyword.pop_first(options, :total, 5)

        pages =
          members
          |> Stream.reject(&(&1.joined_at == nil))
          |> Stream.reject(&(&1.user != nil and &1.user.bot))
          |> Enum.sort_by(&joindate_to_unix/1, &>=/2)
          |> filter_by_options(msg.guild_id, options)
          |> apply_limit(limit)
          |> Stream.map(&format_member/1)
          |> Stream.chunk_every(@shown_per_page)
          |> Enum.map(&%Embed{fields: &1})

        base_page = %Embed{
          title: "Recently joined members",
          color: Constants.color_blue()
        }

        Paginator.paginate_over(msg, base_page, pages)

      {:error, _reason} ->
        {:ok, _msg} = Api.create_message(msg.channel_id, "guild uncached, sorry")
    end
  end

  def command(msg, {_parsed, _args, invalid}) when invalid != [] do
    invalid_args = Parsers.describe_invalid_args(invalid)

    {:ok, _msg} =
      Api.create_message(
        msg.channel_id,
        "🚫 unrecognized argument(s) or invalid value: #{invalid_args}"
      )
  end

  defp filter_by_options(members, guild_id, [{:roles, true} | options]) do
    members
    |> Stream.filter(&Enum.any?(&1.roles))
    |> filter_by_options(guild_id, options)
  end

  defp filter_by_options(members, guild_id, [{:roles, false} | options]) do
    members
    |> Stream.filter(&Enum.empty?(&1.roles))
    |> filter_by_options(guild_id, options)
  end

  # these two fellas brilliantly inefficient, but we want to hand out
  # full result sets later. and that said, we only ever evaluate as many
  # results as needed due to streams
  defp filter_by_options(members, guild_id, [{:messages, true} | options]) do
    messages = MessageCache.recent_in_guild(guild_id, :infinity, Bolt.MessageCache)
    recent_authors = MapSet.new(messages, & &1.author.id)

    members
    |> Stream.filter(&MapSet.member?(recent_authors, &1.user.id))
    |> filter_by_options(guild_id, options)
  end

  defp filter_by_options(members, guild_id, [{:messages, false} | options]) do
    messages = MessageCache.recent_in_guild(guild_id, :infinity, Bolt.MessageCache)
    recent_authors = MapSet.new(messages, & &1.author.id)

    members
    |> Stream.filter(&(not MapSet.member?(recent_authors, &1.user.id)))
    |> filter_by_options(guild_id, options)
  end

  defp filter_by_options(members, _guild_id, []) do
    members
  end

  defp apply_limit(members, n) when n < 1, do: Enum.take(members, @default_shown)
  defp apply_limit(members, n) when n > @maximum_shown, do: Enum.take(members, @maximum_shown)
  defp apply_limit(members, n), do: Enum.take(members, n)

  @spec format_member(Member.t()) :: Embed.Field.t()
  defp format_member(member) do
    joined_at_human =
      member.joined_at
      |> DateTime.from_iso8601()
      |> elem(1)
      |> DateTime.to_unix()
      |> then(&"<t:#{&1}:R>")

    total_roles = length(member.roles)

    %Embed.Field{
      name: User.full_name(member.user),
      value: """
      ID: `#{member.user.id}`
      Joined: #{joined_at_human}
      has #{total_roles} #{Helpers.pluralize(total_roles, "role", "roles")}
      """,
      inline: true
    }
  end

  @spec joindate_to_unix(Member.t()) :: pos_integer()
  defp joindate_to_unix(member) do
    member.joined_at
    |> DateTime.from_iso8601()
    |> elem(1)
    |> DateTime.to_unix()
  end
end
