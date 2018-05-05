import itertools
import operator

import discord
from discord.ext import commands
from sqlalchemy import and_

from .models import infraction as infraction_db
from .types import InfractionType


INFRACTION_TYPE_EMOJI = {
    InfractionType.note: '📔',
    InfractionType.warning: '⚠',
    InfractionType.mute: '🔇',
    InfractionType.kick: '👢',
    InfractionType.ban: '🔨'
}


class Mod:
    """Moderation Commands for Guilds."""

    def __init__(self, bot):
        self.bot = bot
        print('Loaded Cog Mod.')

    @staticmethod
    def __unload():
        print('Unloaded Cog Mod.')

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str=''):
        """Kick a Member with an optional reason.

        **Examples:**
        !kick @Guy#1337 - kicks Guy
        !Kick @Guy#1337 spamming - kick Guy and specifies the reason "spamming" for the Audit Log.
        """

        if ctx.message.guild.me.top_role.position <= member.top_role.position:
            return await ctx.send(embed=discord.Embed(
                title='Cannot kick:',
                description=('I cannot kick any Members that are in the same or higher position in the role hierarchy '
                             'as I am.'),
                colour=discord.Colour.red()
             ))

        await ctx.guild.kick(
            member,
            reason=f'Command invoked by {ctx.message.author}, reason: '
                   f'{"No reason specified" if reason == "" else reason}.'
        )

        response = discord.Embed(
            title=f'Kicked `{member}` (`{member.id}`)',
            colour=discord.Colour.green()
        )
        response.set_footer(
            text=f'Kicked by {ctx.author} ({ctx.author.id})',
            icon_url=ctx.author.avatar_url
        )

        query = infraction_db.insert().values(
            type=InfractionType.kick,
            guild_id=ctx.guild.id,
            user_id=member.id,
            moderator_id=ctx.author.id,
            reason=reason
        )
        result = await self.bot.db.execute(query)
        inserted_pk = result.inserted_primary_key[0]

        response.add_field(
            name='Reason',
            value=reason or 'no reason specified'
        ).add_field(
            name='Infraction',
            value=f'created with ID `{inserted_pk}`'
        )
        await ctx.send(embed=response)

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str=''):
        """Ban a Member with an optional reason.

        **Examples:**
        !ban @Guy#1337
        !ban @Guy#1337 spamming - bans Guy and specifies the reason "spamming" for the audit Log.
        """

        if ctx.message.guild.me.top_role.position <= member.top_role.position:
            return await ctx.send(embed=discord.Embed(
                title='Cannot ban:',
                description=('I cannot ban any Members that are in the same '
                             'or higher position in the role hierarchy as I am.'),
                colour=discord.Colour.red()
            ))

        await ctx.guild.ban(
            member,
            reason=f'banned by command invocation from {ctx.message.author}, reason: '
                   f'{"No reason specified" if reason == "" else reason}.',
            delete_message_days=7
        )

        response = discord.Embed(
            title=f'Banned `{member}` (`{member.id}`)',
            colour=discord.Colour.green()
        ).set_footer(
            text=f'Banned by {ctx.author} ({ctx.author.id})',
            icon_url=ctx.author.avatar_url
        )

        if reason:
            response.description = f'**Reason**: {reason}'

        query = infraction_db.insert().values(
            type=InfractionType.ban,
            guild_id=ctx.guild.id,
            user_id=member.id,
            moderator_id=ctx.author.id,
            reason=reason
        )
        result = await self.bot.db.execute(query)
        inserted_pk = result.inserted_primary_key[0]

        response.add_field(
            name='Reason',
            value=reason or 'no reason specified'
        ).add_field(
            name='Infraction',
            value=f'created with ID `{inserted_pk}`'
        )

        await ctx.send(embed=response)

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx, limit: int=100):
        """Purge a given amount of messages. Defaults to 100.

        Requires the `manage_messages` permission on both the Bot and
        the User that invokes the Command. Only works on Guilds.

        For more specific purge commands, use the various subcommands.

        **Examples:**
        purge - deletes 100 messages
        purge 50 - deletes 50 messages
        """

        total = len(await ctx.message.channel.purge(
            limit=limit,
        ))

        info_response = discord.Embed(
            title=f'Purged a total of `{total}` messages.',
            colour=discord.Colour.green()
        )
        info_response.set_footer(
            text=f'Purged by {ctx.author} ({ctx.author.id})',
            icon_url=ctx.author.avatar_url
        )

        await ctx.send(embed=info_response)

    @purge.command(name='id')
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge_id(self, ctx, *ids_to_purge: int):
        """Purge up to 1000 Messages sent by the User with the given ID.

        Useful when you want to purge Messages from one or more users that left the Server.

        **Examples:**
        purge id 129301
            searches the past 1000 messages for messages from the user and purges them.
        purge id 129301 128195
            searches the past 1000 messages for messages from these ID's and purges them.
        """

        if not ids_to_purge:
            return await ctx.send(embed=discord.Embed(
                title='Failed to purge by ID:',
                description='You need to specify at least one ID to purge.',
                color=discord.Colour.red()
            ))

        total = len(await ctx.message.channel.purge(
            check=lambda m: m.author.id in ids_to_purge,
            limit=1000
        ))
        pruned_ids = f'`{"`, `".join(str(x) for x in ids_to_purge)}`'

        info_response = discord.Embed(
            title=f'Purged a total of `{total}` messages.',
            description=f'Affected IDs: {pruned_ids}',
            colour=discord.Colour.green()
        )
        info_response.set_footer(
            text=f'Purged by {ctx.author} ({ctx.author.id})',
            icon_url=ctx.author.avatar_url
        )

        await ctx.send(embed=info_response)

    @purge.command(name='containing')
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge_containing(self, ctx, amount: int, *, message_contents: str):
        """Purges up to `amount` Messages containing the specified contents.

        **Examples:**
        purge containing 30 evil
            deletes messages in the last 30 messages containing 'evil'
        purge containing 80 zalgo comes
            deletes messages in the last 80 messages containing 'zalgo comes'
        """

        total = len(await ctx.message.channel.purge(
            check=lambda m: message_contents in m.content,
            limit=amount
        ))

        info_response = discord.Embed(
            title=f'Purged a total of `{total}` messages.',
            description=f'Specified message content: `{message_contents}`.',
            colour=discord.Colour.green()
        )
        info_response.set_footer(
            text=f'Purged by {ctx.author} ({ctx.author.id})',
            icon_url=ctx.author.avatar_url
        )

        await ctx.send(embed=info_response)

    @purge.command(name='user')
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge_user(self, ctx, amount: int, *to_purge: discord.Member):
        """Purge a mentioned Member, or a list of mentioned Members.

        **Examples:**
        purge user 300 @Person#1337 @Robot#7331
            purges messages from Person and Robot in the past 300 Messages.
        purge user 40 @Person#1337
            purges messages from Person in the past 40 Messages.
        """

        if not to_purge:
            return await ctx.send(embed=discord.Embed(
                title='Failed to purge User(s)',
                description='You need to mention at least one User to purge.',
                color=discord.Colour.red()
            ))

        total = len(await ctx.message.channel.purge(
            check=lambda m: m.author in to_purge,
            limit=amount
        ))

        affected_users = ', '.join(f'`{member}` (`{member.id}`)' for member in to_purge)
        info_response = discord.Embed(
            title=f'Purged a total of `{total}` messages.',
            description=f'Affected users: {affected_users}',
            colour=discord.Colour.green()
        )
        info_response.set_footer(
            text=f'Purged by {ctx.author} ({ctx.author.id})',
            icon_url=ctx.author.avatar_url
        )

        await ctx.send(embed=info_response)

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def note(self, ctx, user: discord.User, *, note: str):
        """Add the given note to the infraction database for the given user.

        **Examples:**
        note @Person#1337 likes ducks
        """

        query = infraction_db.insert().values(
            type=InfractionType.note,
            user_id=user.id,
            guild_id=ctx.guild.id,
            moderator_id=ctx.author.id,
            reason=note
        )
        result = await self.bot.db.execute(query)

        inserted_pk = result.inserted_primary_key[0]
        info_response = discord.Embed(
            title=f'Added a note for `{user}` (`{user.id}`)',
            description=f'View it in detail by using `infraction detail {inserted_pk}`.',
            colour=discord.Colour.green()
        )
        info_response.set_footer(
            text=f'Note added by {ctx.author} ({ctx.author.id})',
            icon_url=ctx.author.avatar_url
        )
        await ctx.send(embed=info_response)

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, user: discord.User, *, reason: str):
        """Warn the specified user with the given reason."""

        query = infraction_db.insert().values(
            type=InfractionType.warning,
            guild_id=ctx.guild.id,
            user_id=user.id,
            moderator_id=ctx.author.id,
            reason=reason
        )
        result = await self.bot.db.execute(query)
        created_infraction_id = result.inserted_primary_key[0]

        info_response = discord.Embed(
            title=f'Warned user `{user}` (`{user.id}`)',
            colour=0xFFCC00
        ).add_field(
            name='Reason',
            value=reason or 'no reason specified'
        ).add_field(
            name='Infraction',
            value=f'created with ID `{created_infraction_id}`'
        ).set_footer(
            text=f'Authored by {ctx.author} ({ctx.author.id})',
            icon_url=user.avatar_url
        )
        await ctx.send(embed=info_response)

    @commands.group()
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def infraction(self, _):
        """Contains infraction management commands."""

    @infraction.command(name='edit')
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def infraction_edit(self, ctx, id_: int, *, new_reason: str):
        """Change the reason of the given infraction ID to the given new reason."""

        query = infraction_db.update().where(
            infraction_db.c.id == id_,
            infraction_db.c.guild_id == ctx.guild.id
        ).values(reason=new_reason)
        result = await self.bot.db.execute(query)

        if result.rowcount == 0:
            await ctx.send(embed=discord.Embed(
                title=f'Failed to find infraction #`{id_}` on this guild.',
                colour=discord.Colour.red()
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title=f'Successfully edited infraction #`{id_}`.',
                description=f'**New reason**: {new_reason}',
                colour=discord.Colour.green()
            ))

    @infraction.command(name='delete')
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def infraction_delete(self, ctx, id_: int):
        """Delete the given infraction from the database."""

        query = infraction_db.delete().where(
            infraction_db.c.id == id_,
            infraction_db.c.guild_id == ctx.guild.id
        )
        result = await self.bot.db.execute(query)

        if result.rowcount == 0:
            await ctx.send(embed=discord.Embed(
                title=f'Failed to find infraction #`{id_}` on this Guild.',
                colour=discord.Colour.red()
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title=f'Successfully deleted infraction #`{id_}`.',
                colour=discord.Colour.green()
            ))

    @infraction.command(name='detail')
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def infraction_detail(self, ctx, id_: int):
        """Look up the given infraction ID in the database."""

        query = infraction_db.select().where(and_(
            infraction_db.c.id == id_,
            infraction_db.c.guild_id == ctx.guild.id
        ))
        result = await self.bot.db.execute(query)
        infraction = await result.first()

        if infraction is None:
            return await ctx.send(embed=discord.Embed(
                title=f'Failed to find infraction ID `{id_}`.',
                colour=discord.Colour.red()
            ))

        infraction_embed = discord.Embed(
            title=f'Infraction: `{id_}`',
            colour=discord.Colour.blue()
        )

        infraction_user = self.bot.get_user(infraction.user_id)
        infraction_embed.add_field(
            name='User',
            value=(f'`{infraction_user}` (`{infraction_user.id}`)'
                   if infraction_user is not None else f'`{infraction.user_id}`')
        )

        infraction_embed.add_field(
            name='Type',
            value=f'{INFRACTION_TYPE_EMOJI[infraction.type]} {infraction.type.value.title()}'
        ).add_field(
            name='Creation',
            value=str(infraction.created_on)
        ).add_field(
            name='Last edited',
            value=str(infraction.edited_on or 'never')
        ).add_field(
            name='Reason',
            value=infraction.reason,
            inline=False
        )

        author_moderator = self.bot.get_user(infraction.moderator_id)
        if author_moderator is not None:
            infraction_embed.set_footer(
                text=f'Authored by {author_moderator} ({author_moderator.id})',
                icon_url=author_moderator.avatar_url
            )
        else:
            infraction_embed.set_footer(
                text=f'Authored by unknown user (ID: {infraction.moderator_id})'
            )

        await ctx.send(embed=infraction_embed)

    @infraction.command(name='list')
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def infraction_list(self, ctx, *types: InfractionType):
        """List all infractions, or infractions with the specified type(s)."""

        if types:
            query = infraction_db.select().where(and_(
                infraction_db.c.guild_id == ctx.guild.id,
                infraction_db.c.type.in_(types)
            )).order_by(infraction_db.c.created_on)
            title = f'Infractions with types `{"`, `".join(f"`{type_}`" for type_ in types)}` on {ctx.guild.name}'
        else:
            query = infraction_db.select().where(
                infraction_db.c.guild_id == ctx.guild.id
            ).order_by(infraction_db.c.created_on)
            title = f'All infractions on {ctx.guild.name}'

        result = await self.bot.db.execute(query)
        all_infractions = await result.fetchall()

        list_embed_description = []
        for infraction in all_infractions:
            user = self.bot.get_user(infraction.user_id)
            if user is not None:
                user_string = f'`{user}` (`{user.id}`)'
            else:
                user_string = f'unknown user (`{user.id}`)'
            infraction_emoji = INFRACTION_TYPE_EMOJI[infraction.type]

            list_embed_description.append(
                f'• [`{infraction.id}`] {infraction_emoji} on {user_string} created {infraction.created_on}'
            )

        list_embed = discord.Embed(
            title=title,
            description='\n'.join(list_embed_description) or 'Seems like there\'s nothing here yet.',
            colour=discord.Colour.blue()
        )
        await ctx.send(embed=list_embed)

    @infraction.command(name='user')
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def infraction_user(self, ctx, user: discord.User):
        """Look up infractions for the specified user."""

        query = infraction_db.select().where(and_(
            infraction_db.c.guild_id == ctx.guild.id,
            infraction_db.c.user_id == user.id
        )).order_by(infraction_db.c.type)
        result = await self.bot.db.execute(query)
        rows = await result.fetchall()

        if not rows:
            return await ctx.send(embed=discord.Embed(
                title=f'No recorded infractions for `{user}` (`{user.id}`).',
                colour=discord.Colour.blue()
            ))

        most_recent = max(rows, key=operator.attrgetter('created_on'))
        response = discord.Embed(
            title=f'Infractions for `{user}` (`{user.id}`)',
            colour=discord.Colour.blue()
        ).set_footer(
            text=f'total infractions: {len(rows)}, most recent: #{most_recent.id} at {most_recent.created_on}',
            icon_url=user.avatar_url
        )

        for infraction_type, infractions in itertools.groupby(rows, key=operator.attrgetter('type')):
            response.add_field(
                name=f'{INFRACTION_TYPE_EMOJI[infraction_type]} {infraction_type.value}s',
                value='\n'.join(f'• [`{infraction.id}`] on {infraction.created_on}' for infraction in infractions)
            )

        await ctx.send(embed=response)
