# VERTEX — Discord bot for our gaming server

Built with Python + [discord.py](https://discordpy.readthedocs.io/) + SQLite. Every feature lives in its own file in `cogs/`.
Commands work with the `,` prefix (`,balance`) **and** as slash commands (`/balance`).

## One-time Discord setup

1. Go to <https://discord.com/developers/applications> → **New Application**.
2. **Bot** tab → **Reset Token** → copy it (you'll paste it into `.env`).
3. Same page → turn on **both** privileged intents:
   - **Server Members Intent** (detects new members)
   - **Message Content Intent** (needed for `,commands` and XP from chatting)
4. **OAuth2 → URL Generator** → scopes: `bot` and `applications.commands`.
   Permissions: View Channels, Send Messages, Embed Links, **Manage Roles** (level rewards, shop, custom roles), **Manage Messages** (removes GIFs/pictures sent below the required level). Open the URL and add the bot to your server.
5. In Discord: **Settings → Advanced → Developer Mode** on. Right-click your server icon and the welcome channel → **Copy ID**.
6. In Server Settings → Roles, drag the bot's role **above** any role it should hand out (level rewards, tier roles).

## Run it (Windows, PowerShell)

```powershell
cd D:\VERTEX
py -3.12 -m venv .venv            # first time only (Python 3.12)
.\.venv\Scripts\pip install -r requirements.txt   # first time + after updates
copy .env.example .env            # first time only, then edit .env
.\.venv\Scripts\python bot.py
```

Stop with `Ctrl+C`. The bot is offline whenever this process isn't running. Data is stored in `data/vertex.db` (back this file up).

## Commands

### Levels and money

| Command | Who | What |
| --- | --- | --- |
| `,rank [@user]` (`,r`, `,lvl`, `,level`, `,xp`) | everyone | Level, rank and XP progress |
| `,balance [@user]` (`,bal`) | everyone | Vertex Coins and Credits |
| `,daily` | everyone | Claim 500 Vertex Coins every 24h |
| `,give @user amount` (`,pay`) | everyone | Send Vertex Coins |
| `,leaderboard [xp\|coins\|credits]` (`,lb`) | everyone | Top 10 |
| `,levelrole add <level> @role` / `remove` / `list` | Manage Server | Role rewards at levels |
| `,prestige` | everyone | At level 100: start over at level 1 and earn the next Prestige rank (up to 10) |
| `,setupbadges` | admins | Create the Level 0-90 and Prestige 1-10 roles and give them to everyone who already earned them |
| `,syncbadges` | admins | Re-check everyone and fix their level and prestige roles |
| `,addcoins` `,removecoins` `,addcredits` `,removecredits` `@user amount` | admins | Hand out or take back money/Credits |
| `,addlevel @user amount` | admins | Raise someone's level (runs the level-up message and role updates) |
| `,setlevel @user level` | admins | Set someone's level exactly (0-100; also fixes their badge if it goes down) |
| `,setprestige @user 0-10` | admins | Set someone's prestige (fixes their prestige role) |

### Shop and roles

| Command | Who | What |
| --- | --- | --- |
| `,shop` | everyone | Browse the shop (Credits roles + coin items) |
| `,buy <item>` | everyone | Buy a shop item (gives its role) |
| `,customrole create <name>` | any tier owner | Create your own role (free once you own a tier role: Elite, Divine, Mythic, Void or Eternal). See "Custom roles" below |
| `,customrole rename <name>` / `color #ff66aa` / `icon 🐐` / `delete` | role owner | Edit your custom role. `icon` needs Boost Level 2 |
| `,customrole give @friend` / `take @friend` / `friends` | role owner | Share your role with friends (instant), take it back, see who has it |
| `,customrole leave @owner` | friends | Give up a role someone shared with you |
| `,setuptiers` | admins | Create Elite/Divine/Mythic/Void/Eternal roles and add them to the shop |
| `,createroles` | admins | Create the staff roles (Owner, Co-Owner, Manager, Senior Moderator, Moderator, Junior Moderator, Trial Moderator) plus the 5 tier roles, **with no permissions**. Existing roles are left alone |
| `,makerole "name" [#color]` | admins | Create any single role (no permissions) |
| `,arrangeroles` | admins | Put every role in rank order (see below). `,createroles`, `,setupbadges` and buying a custom role do this automatically. Only works while the bot's own role is above the roles it moves |
| `,shop add "name" price coins\|credits @role [description]` / `,shop remove <name>` | Manage Server | Custom shop items |

### Social

| Command | Who | What |
| --- | --- | --- |
| `,hug` `,kiss` `,pat` `,slap` `,kill` `,cuddle` `,poke` `,bite` `,punch` `,tickle` `,handhold` `,highfive` `,nuzzle` `@user` | everyone | Anime GIF actions (counts how often you've done it to each person) |
| `,wave` `,wink` `,cry` `,blush` `,dance` `,smile` `,laugh` `,pout` `,nom` `,sleep` `,shrug` `,facepalm` `[@user]` | everyone | Solo actions, optionally aimed at someone |
| `,marry @user` / `,divorce` | everyone | Proposal with Accept/Decline buttons |
| `,adopt @user` / `,disown @user` / `,runaway` | everyone | Adoption (the child must accept; max 10 children) |
| `,family [@user]` | everyone | Partner, parent and children |

### Gambling

| Command | Who | What |
| --- | --- | --- |
| `,coinflip <bet> [heads\|tails]` (`,cf`) | everyone | 1.95x payout |
| `,slots <bet>` | everyone | Three reels, up to 500x |
| `,dice <bet> <high\|low\|1-6>` | everyone | High/low 1.95x, exact number 5.7x |
| `,blackjack <bet>` (`,bj`) | everyone | Hit / Stand / Double buttons, blackjack pays 3:2 |

Bets accept `500`, `1,000`, `5k`, `1.5m`, `half` or `all`. Minimum bet is 10, there's no maximum, and each game has a 3-second cooldown per player. Every game has a small house edge (return to player: slots 93%, coinflip/dice 95-97.5%, blackjack about 94-99% depending on skill). Unfinished blackjack hands auto-stand after 2 minutes, and stakes are refunded if the bot shuts down mid-hand.

### Other

| Command | Who | What |
| --- | --- | --- |
| `,quizdrop [flag\|math\|trivia]` | admins | Drop a quiz question right now (real prizes are paid) |
| `/testwelcome` | admins | Preview the welcome greeting |
| `,afk [reason]` | everyone | Go AFK. Your next message (GIF-only messages don't count) ends it, and the bot reports how long you were away and who pinged you |
| `,ping`, `,help` | everyone | Utility |

New members are greeted automatically in `WELCOME_CHANNEL_ID`.

## Short forms (cheat sheet)

Every command still works with its full name. These are the quick versions (type `,help` to see them all):

| Short | Full | | Short | Full |
| --- | --- | --- | --- | --- |
| `,b` `,bal` | `,balance` | | `,cr` `,role` | `,customrole` |
| `,d` | `,daily` | | `,cr make <name>` | `,customrole create` |
| `,send` `,pay` | `,give` | | `,cr c #ff66aa` | `,customrole color` |
| `,r` `,lvl` | `,rank` | | `,cr i 🐐` | `,customrole icon` |
| `,lb` `,top` | `,leaderboard` | | `,cr g @friend` | `,customrole give` |
| `,pres` `,pr` | `,prestige` | | `,cr rm @friend` | `,customrole take` |
| `,sh` `,store` | `,shop` | | `,cr who` | `,customrole friends` |
| `,cf` | `,coinflip` | | `,cr del` | `,customrole delete` |
| `,sl` | `,slots` | | `,fam` | `,family` |
| `,bj` | `,blackjack` | | `,hf` `,hh` | `,highfive` `,handhold` |
| `,h` `,cmds` | `,help` | | `,p` | `,ping` |

Admin short forms: `,ac` `,acr` (add coins / Credits), `,rmc` `,rmcr` (remove), `,addlvl` `,setlvl`, `,setpres`, `,badges` (setupbadges), `,sync` (syncbadges), `,tiers` (setuptiers), `,mkroles` (createroles), `,arrange`, `,mkrole`, `,quiz`, `,perms`, `,lr` (levelrole).

## Custom roles

Owning a **tier role** (from `,shop`, bought with Credits) unlocks your own custom role. It's free to create. You choose the name and color, and you can give it to friends:

| Tier | Friends you can share with |
| --- | --- |
| Elite | 0 (your own role only) |
| Divine | 8 |
| Mythic | 12 |
| Void | 16 |
| Eternal | 28 |

- `,cr Goat 🐐` (or `,cr make Goat 🐐`) → make it. `,cr c #ff66aa` colors it, `,cr name <new name>` renames it.
- `,cr g @friend` gives it instantly. `,cr rm @friend` gets it back and frees the slot, `,cr who` lists who has it. A friend can leave with `,cr leave @you`.
- `,cr` alone shows your status and the commands. If you mistype a sub-command (like `,cr colr`), it suggests the right one instead of making a role.
- **Emoji:** a normal emoji can go in the role's name any time (`Goat 🐐`). A real role **icon** (`,customrole icon 🐐`, or attach a picture under 256 KB) works only on servers with **Boost Level 2**, and a server's own custom emoji can't be used in a role name.
- If you own several tiers, the highest one sets your friend limit. If you lose all tiers you keep the role and your friends keep it too, but you can't add more friends.
- The role has **no permissions**, and names of staff, tier, level and prestige roles are reserved.
- The limits are in `TIER_FRIEND_LIMITS` in `config.py`.

## Role rank order

`,arrangeroles` puts the roles in this order, highest first (right under the bot's own role):

1. Owner · 2. Co-Owner · 3. Manager · 4. Senior Moderator · 5. Moderator · 6. Junior Moderator · 7. Trial Moderator
8. Eternal · 9. Void · 10. Mythic · 11. Divine · 12. Elite
13. *Roles that aren't in the ranking* (like "SOO GAY" and members' custom roles, in their current order)
14. Prestige 10 → Prestige 1
15. Level 100 → Level 0

Custom roles sit between Elite and Prestige 10 so their color shows over the badge colors. The order lives in `rolesutil.py`.

## Level badges and Prestige

Run `,setupbadges` once. It creates these roles (each with its own emoji and color):

- **Level 0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100**: badges are **permanent**. Once you earn one you keep it, so a level 20 member has Level 0, 5, 10 and 20. Everyone starts with "Level 0".
- **Prestige 1 to 10**: these stack too, so nothing is ever hidden.

It also gives the roles to everyone who already qualifies. If a role with that name already exists (even with an emoji after it, like "Level 5 🧠"), the bot uses it instead of making a duplicate.

**How prestige works**
1. Level up to **100**. XP stops there, and the bot tells you that you can prestige.
2. Run `,prestige` and confirm. You go back to **level 1** and get **Prestige 1**. You **keep every level badge** (Level 0 to 100), and your coins, Credits and shop roles too.
3. Reach level 100 again and `,prestige` for **Prestige 2**, and so on up to **Prestige 10**, the max. A Prestige 10 member holds Prestige 1 to 10 and every level badge.
4. Prestiged members keep GIF, picture and custom-role access, even while back at a low level.
5. On the XP leaderboard, higher prestige ranks above higher level.

- Skipping several levels at once (for example with `,addlevel`) lands you on the right badge.
- Want members to show only their highest level badge instead (Level 10 replacing Level 5)? Set `STACK_LEVEL_ROLES = False` in `config.py`, restart the bot, and run `,syncbadges`. `STACK_PRESTIGE_ROLES = False` does the same for prestige roles.
- Anyone with prestige 1+ counts as having finished level 100, so they hold all level badges. `,setprestige` gives that right away.
- If an admin lowers a member who has **not** prestiged (`,setlevel @user 12`), their badges above that level are removed.
- Change the levels, emojis or colors in `LEVEL_BADGES` and `PRESTIGE_ROLES` in `config.py`, then run `,setupbadges` again. It's safe to re-run.
- The bot needs **Manage Roles**, and its role must sit **above** these roles (new roles are created below it, so this works by default).
- Members can't name their custom role "Level ..." or "Prestige ...".

## Level-gated GIFs and pictures

- **Level 10+** can send GIFs (Tenor/Giphy links from Discord's GIF picker, direct `.gif` links, `.gif` uploads).
- **Level 20+** can send pictures (image uploads, and direct links to png/jpg/webp...).
- If someone below the level tries, the bot **deletes the message** and posts a short notice that disappears after 8 seconds. Editing a GIF link into an old message is caught too.
- **Admins and members with Manage Messages are exempt.**
- The bot needs the **Manage Messages** permission (Server Settings → Roles → the bot's role, no re-invite needed). Without it, nothing is removed and a warning is logged.
- Change the levels with `GIF_MIN_LEVEL` and `IMAGE_MIN_LEVEL` in `config.py`.

## Quiz drops

Questions appear on their own every 20-40 minutes, but only while chat is active (3+ messages in the last 10 minutes). Three kinds: **guess the flag**, **quick math** (add / subtract / multiply) and **trivia** (A/B/C/D). Everyone gets **one guess**, the first correct answer wins, and the question closes after 30 seconds.

Prize for a correct answer: ONE random reward, either **1,000-30,000 Vertex Coins** (75%) or **1,000-3,000 Credits** (25%), plus **40-100 XP** every time. All numbers are in `config.py` (`QUIZ_*`).

**Automatic drops are OFF until you set `QUIZ_CHANNEL_ID` in `.env`** (the channel ID of your general chat). `,quizdrop` works anywhere right away. Add your own trivia questions and countries in `quiz_data.py`.

## Tweaking numbers

Open `config.py`: currency names/emoji, XP per message (15–25, once per 60s), daily amount (500), prefix, the five tier roles and their Credits prices (`TIER_ROLES`), how many friends each tier can share with (`TIER_FRIEND_LIMITS`), quiz timing and prizes. Gambling odds live in `games.py`.

## Your own GIFs (optional)

Action GIFs come from the free otakugifs.xyz API. To use your own for any action, create `data/gifs.json`:

```json
{ "kill": ["https://example.com/one.gif", "https://example.com/two.gif"] }
```

Restart the bot afterwards. If the API is ever down, the bot still sends the message, just without a GIF.

## Adding a feature

1. Create `cogs/myfeature.py` (copy `cogs/leaderboard.py` as a template).
2. Restart the bot — every file in `cogs/` loads automatically (files starting with `_` are skipped).
