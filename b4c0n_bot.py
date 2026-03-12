import discord
from discord import app_commands
import os
import aiohttp
import json
import base64
import uuid
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════════════════════════════════════════════
#  Bot Setup
# ═══════════════════════════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════════
QUOTES_CHANNEL_ID   = int(os.getenv('QUOTES_CHANNEL_ID', '0'))
SPEECH_BUBBLE_IMAGE = os.getenv('SPEECH_BUBBLE_IMAGE', '')
GITHUB_TOKEN        = os.getenv('GITHUB_TOKEN', '')
FITNESS_ROLE_ID     = int(os.getenv('FITNESS_ROLE_ID', '0'))

GITHUB_REPO      = 'Digital-Void-divo/B4C0N'
GITHUB_FILE_PATH = 'Fitness/b4c0nFitness.json'

# Stat fields: key → display label + goal direction
GOAL_FIELDS: dict[str, dict] = {
    'weight':             {'label': 'Weight',             'direction': 'decrease'},
    'body_fat_pct':       {'label': 'Body Fat %',         'direction': 'decrease'},
    'neck':               {'label': 'Neck',               'direction': 'increase'},
    'chest':              {'label': 'Chest',              'direction': 'increase'},
    'waist':              {'label': 'Waist',              'direction': 'decrease'},
    'resting_heart_rate': {'label': 'Resting Heart Rate', 'direction': 'decrease'},
    'bench':              {'label': 'Bench Press',        'direction': 'increase'},
    'cardio_duration':    {'label': 'Cardio Duration',    'direction': 'increase'},
}
STAT_FIELDS_P1 = ['weight', 'body_fat_pct', 'neck', 'chest', 'waist']
STAT_FIELDS_P2 = ['resting_heart_rate', 'bench', 'cardio_duration']

WORKOUT_CATEGORIES = ['Strength', 'Cardio', 'Flexibility', 'Sport', 'Other']
PAGE_SIZE = 5

# ═══════════════════════════════════════════════════════════════════════════════
#  GitHub I/O
# ═══════════════════════════════════════════════════════════════════════════════
async def gh_load() -> tuple[dict, str | None]:
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}'
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 404:
                return {'users': {}}, None
            if resp.status != 200:
                raise Exception(f'GitHub read failed: HTTP {resp.status}')
            payload = await resp.json()
            content = base64.b64decode(payload['content']).decode('utf-8')
            return json.loads(content), payload['sha']


async def gh_save(data: dict, sha: str | None, message: str = 'Update fitness data') -> bool:
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}'
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    encoded = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    payload  = {'message': message, 'content': encoded, 'branch': 'main'}
    if sha:
        payload['sha'] = sha
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=headers, json=payload) as resp:
            return resp.status in (200, 201)

# ═══════════════════════════════════════════════════════════════════════════════
#  Data Helpers
# ═══════════════════════════════════════════════════════════════════════════════
def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def week_start_for(dt: datetime | None = None) -> str:
    """Return the Sunday of the week containing dt as YYYY-MM-DD."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    offset = (dt.weekday() + 1) % 7   # days since Sunday (Mon=0…Sun=6)
    sunday = dt - timedelta(days=offset)
    return sunday.strftime('%Y-%m-%d')


def ensure_user(data: dict, member: discord.Member | discord.User) -> dict:
    uid = str(member.id)
    if uid not in data['users']:
        data['users'][uid] = {
            'meta': {
                'username':        member.display_name,
                'is_public':       True,
                'unit_preference': 'lbs',
                'joined':          utcnow(),
            },
            'baseline':      None,
            'goals':         [],
            'stats':         [],
            'workout_log':   [],
            'history_notes': [],
        }
    return data['users'][uid]


def unit_label(user_data: dict, field: str) -> str:
    unit = user_data['meta'].get('unit_preference', 'lbs')
    if field in ('weight', 'bench', 'neck', 'chest', 'waist'):
        return unit
    if field == 'body_fat_pct':       return '%'
    if field == 'resting_heart_rate': return 'bpm'
    if field == 'cardio_duration':    return ''  # already HH:MM
    return ''


def fmt_stat(field: str, value, user_data: dict) -> str:
    if value is None:
        return 'N/A'
    ul = unit_label(user_data, field)
    return f'{value} {ul}'.strip() if ul else str(value)


def cardio_to_min(hhmm: str) -> float:
    try:
        h, m = str(hhmm).strip().split(':')
        return int(h) * 60 + int(m)
    except Exception:
        return 0.0


def to_numeric(field: str, value) -> float:
    if field == 'cardio_duration':
        return cardio_to_min(value)
    try:
        return float(value)
    except Exception:
        return 0.0


def parse_num(raw: str) -> float | None:
    s = raw.strip() if raw else ''
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fitness_role_mention(guild: discord.Guild) -> str | None:
    if FITNESS_ROLE_ID:
        role = guild.get_role(FITNESS_ROLE_ID)
        if role:
            return role.mention
    return None


def check_goals_after_update(user_data: dict) -> list[dict]:
    """
    Compare the latest stat snapshot against all incomplete goals.
    Mutates goal records in-place (sets completed_at, milestones_announced).
    Returns a list of event dicts: {goal, type: 'completed'|'milestone', milestone_pct?}
    """
    events: list[dict] = []
    if not user_data.get('stats') or not user_data.get('goals'):
        return events

    latest   = user_data['stats'][-1]
    baseline = user_data.get('baseline') or {}

    for goal in user_data['goals']:
        if goal.get('completed_at'):
            continue

        field        = goal['field']
        target_raw   = goal.get('target_value')
        current_raw  = latest.get(field)
        baseline_raw = baseline.get(field)

        if any(v is None for v in (target_raw, current_raw, baseline_raw)):
            continue

        target    = to_numeric(field, target_raw)
        current   = to_numeric(field, current_raw)
        base_val  = to_numeric(field, baseline_raw)
        direction = goal['direction']

        # ── Goal completion ───────────────────────────────────────────────────
        completed = (direction == 'decrease' and current <= target) or \
                    (direction == 'increase' and current >= target)
        if completed:
            goal['completed_at'] = utcnow()
            events.append({'goal': goal, 'type': 'completed'})
            continue

        # ── Milestone check ───────────────────────────────────────────────────
        milestone_pct = goal.get('milestone_pct')
        if not milestone_pct:
            continue
        total_delta = abs(target - base_val)
        if total_delta == 0:
            continue
        progress = (base_val - current) if direction == 'decrease' else (current - base_val)
        if progress <= 0:
            continue

        progress_pct = (progress / total_delta) * 100
        announced    = goal.setdefault('milestones_announced', [])
        step         = float(milestone_pct)
        thresh       = step
        while thresh < 100.0:
            if progress_pct >= thresh and thresh not in announced:
                announced.append(thresh)
                events.append({'goal': goal, 'type': 'milestone', 'milestone_pct': thresh})
            thresh += step

    return events

# ═══════════════════════════════════════════════════════════════════════════════
#  Embed Builders
# ═══════════════════════════════════════════════════════════════════════════════
def build_baseline_embed(user_data: dict, member: discord.Member | discord.User) -> discord.Embed:
    b    = user_data['baseline']
    unit = user_data['meta'].get('unit_preference', 'lbs')
    ts   = datetime.fromisoformat(b['set_at'])
    e    = discord.Embed(
        title=f'📏 {member.display_name} — Baseline Stats',
        color=discord.Color.blurple(),
        timestamp=ts,
    )
    for f in list(GOAL_FIELDS.keys()):
        val = b.get(f)
        if val is not None:
            e.add_field(name=GOAL_FIELDS[f]['label'], value=fmt_stat(f, val, user_data), inline=True)
    if b.get('notes'):
        e.add_field(name='Notes', value=b['notes'], inline=False)
    e.set_footer(text=f'Units: {unit}')
    return e


def build_stats_embed(
    user_data: dict,
    member: discord.Member | discord.User,
    entry: dict | None = None
) -> discord.Embed:
    s = entry or (user_data['stats'][-1] if user_data.get('stats') else None)
    if s is None:
        return discord.Embed(title='No stats recorded yet.', color=discord.Color.red())
    ts = datetime.fromisoformat(s['recorded_at'])
    e  = discord.Embed(
        title=f'📊 {member.display_name} — Current Stats',
        color=discord.Color.green(),
        timestamp=ts,
    )
    for f in list(GOAL_FIELDS.keys()):
        val = s.get(f)
        if val is not None:
            e.add_field(name=GOAL_FIELDS[f]['label'], value=fmt_stat(f, val, user_data), inline=True)
    if s.get('notes'):
        e.add_field(name='Notes', value=s['notes'], inline=False)
    return e


def build_goals_embed(user_data: dict, member: discord.Member | discord.User) -> discord.Embed:
    goals = user_data.get('goals', [])
    e     = discord.Embed(title=f'🎯 {member.display_name} — Fitness Goals', color=discord.Color.gold())
    if not goals:
        e.description = 'No goals set yet. Use **Add Goal** to get started.'
        return e
    for g in goals:
        fl       = GOAL_FIELDS.get(g['field'], {}).get('label', g['field'])
        status   = '✅ Completed' if g.get('completed_at') else '🔄 In Progress'
        val_disp = fmt_stat(g['field'], g['target_value'], user_data)
        lines    = [f'**Target:** {val_disp}', f'**By:** {g.get("target_date","No date")}', f'**Status:** {status}']
        if g.get('milestone_pct'):
            lines.append(f'**Milestones:** every {g["milestone_pct"]}%')
        if g.get('milestones_announced'):
            reached = ', '.join(f'{int(p)}%' for p in sorted(g['milestones_announced']))
            lines.append(f'**Reached:** {reached}')
        e.add_field(name=f'🎯 {fl}', value='\n'.join(lines), inline=False)
    return e


def build_history_embed(
    user_data: dict,
    member: discord.Member | discord.User,
    ws: str,
) -> discord.Embed:
    ws_dt  = datetime.strptime(ws, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    we_dt  = ws_dt + timedelta(days=6)
    we_str = we_dt.strftime('%Y-%m-%d')
    label  = f'{ws_dt.strftime("%b %d")} – {we_dt.strftime("%b %d, %Y")}'
    e      = discord.Embed(
        title=f'📅 {member.display_name} — Week of {label}',
        color=discord.Color.teal(),
    )
    # Stat updates this week
    stats_week = [
        s for s in user_data.get('stats', [])
        if ws <= s['recorded_at'][:10] <= we_str
    ]
    if stats_week:
        lines = []
        for s in stats_week:
            parts = []
            for f in ['weight', 'body_fat_pct', 'bench', 'cardio_duration']:
                if s.get(f) is not None:
                    parts.append(f'{GOAL_FIELDS[f]["label"]}: {fmt_stat(f, s[f], user_data)}')
            lines.append(f'**{s["recorded_at"][:10]}** — {", ".join(parts) or "Updated"}')
        e.add_field(name='📊 Stat Updates', value='\n'.join(lines), inline=False)
    else:
        e.add_field(name='📊 Stat Updates', value='None this week', inline=False)

    # Workouts this week
    workouts = [
        w for w in user_data.get('workout_log', [])
        if ws <= w['logged_at'][:10] <= we_str
    ]
    if workouts:
        lines = [
            f'**{w["logged_at"][:10]}** [{w.get("category","?")}] {w["workout"]}'
            for w in workouts
        ]
        e.add_field(name='🏋️ Workouts', value='\n'.join(lines), inline=False)
    else:
        e.add_field(name='🏋️ Workouts', value='None logged this week', inline=False)

    # Note
    note_entry = next(
        (n for n in user_data.get('history_notes', []) if n['week_start'] == ws), None
    )
    e.add_field(
        name='📝 Note',
        value=note_entry['note'] if note_entry else 'No note for this week.',
        inline=False,
    )
    return e

# ═══════════════════════════════════════════════════════════════════════════════
#  Shared PublishView
# ═══════════════════════════════════════════════════════════════════════════════
class PublishView(discord.ui.View):
    """Reusable ephemeral → channel publish button."""
    def __init__(self, embed: discord.Embed, guild: discord.Guild):
        super().__init__(timeout=300)
        self.embed = embed
        self.guild = guild

    @discord.ui.button(label='📢 Publish to Channel', style=discord.ButtonStyle.secondary)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        mention = fitness_role_mention(self.guild)
        await interaction.channel.send(content=mention, embed=self.embed)
        button.disabled = True
        await interaction.response.edit_message(view=self)

# ═══════════════════════════════════════════════════════════════════════════════
#  BASELINE
# ═══════════════════════════════════════════════════════════════════════════════
class BaselineUnitView(discord.ui.View):
    """Step 1 of baseline setup: choose unit preference, then launch modal."""
    def __init__(self, existing_unit: str = 'lbs', existing: dict | None = None):
        super().__init__(timeout=120)
        self.unit     = existing_unit
        self.existing = existing

    @discord.ui.select(
        placeholder='Select your unit preference (lbs / kg)',
        options=[
            discord.SelectOption(label='Pounds (lbs)', value='lbs', emoji='🇺🇸'),
            discord.SelectOption(label='Kilograms (kg)', value='kg', emoji='🌍'),
        ],
        row=0,
    )
    async def unit_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.unit = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label='Continue →', style=discord.ButtonStyle.primary, row=1)
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            BaselineModal1(unit=self.unit, existing=self.existing)
        )


class BaselineModal1(discord.ui.Modal, title='Baseline — Part 1 of 2'):
    weight       = discord.ui.TextInput(label='Weight',     placeholder='e.g. 185',  required=False)
    body_fat_pct = discord.ui.TextInput(label='Body Fat %', placeholder='e.g. 22.5', required=False)
    neck         = discord.ui.TextInput(label='Neck',       placeholder='e.g. 15.5', required=False)
    chest        = discord.ui.TextInput(label='Chest',      placeholder='e.g. 42.0', required=False)
    waist        = discord.ui.TextInput(label='Waist',      placeholder='e.g. 36.0', required=False)

    def __init__(self, unit: str = 'lbs', existing: dict | None = None):
        super().__init__()
        self.unit = unit
        if existing:
            if existing.get('weight')       is not None: self.weight.default       = str(existing['weight'])
            if existing.get('body_fat_pct') is not None: self.body_fat_pct.default = str(existing['body_fat_pct'])
            if existing.get('neck')         is not None: self.neck.default         = str(existing['neck'])
            if existing.get('chest')        is not None: self.chest.default        = str(existing['chest'])
            if existing.get('waist')        is not None: self.waist.default        = str(existing['waist'])

    async def on_submit(self, interaction: discord.Interaction):
        part1 = {
            'weight':       self.weight.value or None,
            'body_fat_pct': self.body_fat_pct.value or None,
            'neck':         self.neck.value or None,
            'chest':        self.chest.value or None,
            'waist':        self.waist.value or None,
        }
        await interaction.response.send_modal(
            BaselineModal2(unit=self.unit, part1=part1, existing=self.existing if hasattr(self, 'existing') else None)
        )

    # Store existing on instance for Modal2 access
    @property
    def existing(self): return getattr(self, '_existing', None)
    @existing.setter
    def existing(self, v): self._existing = v


class BaselineModal2(discord.ui.Modal, title='Baseline — Part 2 of 2'):
    resting_heart_rate = discord.ui.TextInput(label='Resting Heart Rate (bpm)', placeholder='e.g. 65',    required=False)
    bench              = discord.ui.TextInput(label='Bench Press',              placeholder='e.g. 135',   required=False)
    cardio_duration    = discord.ui.TextInput(label='Cardio Duration (HH:MM)',  placeholder='e.g. 00:30', required=False)
    notes              = discord.ui.TextInput(
        label='Notes (optional — anything extra to track)',
        style=discord.TextStyle.paragraph,
        placeholder='e.g. Starting a cut, recovering from injury…',
        required=False,
        max_length=500,
    )

    def __init__(self, unit: str, part1: dict, existing: dict | None = None):
        super().__init__()
        self.unit  = unit
        self.part1 = part1
        if existing:
            if existing.get('resting_heart_rate') is not None:
                self.resting_heart_rate.default = str(existing['resting_heart_rate'])
            if existing.get('bench')              is not None: self.bench.default              = str(existing['bench'])
            if existing.get('cardio_duration')    is not None: self.cardio_duration.default    = str(existing['cardio_duration'])
            if existing.get('notes')              is not None: self.notes.default              = str(existing['notes'])

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            data, sha = await gh_load()
            user_data = ensure_user(data, interaction.user)
            user_data['meta']['unit_preference'] = self.unit

            baseline = {
                'set_at':             utcnow(),
                'weight':             parse_num(self.part1.get('weight')),
                'body_fat_pct':       parse_num(self.part1.get('body_fat_pct')),
                'neck':               parse_num(self.part1.get('neck')),
                'chest':              parse_num(self.part1.get('chest')),
                'waist':              parse_num(self.part1.get('waist')),
                'resting_heart_rate': parse_num(self.resting_heart_rate.value),
                'bench':              parse_num(self.bench.value),
                'cardio_duration':    self.cardio_duration.value.strip() or None,
                'notes':              self.notes.value.strip() or None,
            }
            user_data['baseline'] = baseline
            await gh_save(data, sha, f'Baseline set for {interaction.user.name}')

            embed = build_baseline_embed(user_data, interaction.user)
            view  = PublishView(embed=embed, guild=interaction.guild)
            await interaction.followup.send(
                '✅ **Baseline saved!** You can now set goals and log stats.',
                embed=embed, view=view, ephemeral=True,
            )
        except Exception as ex:
            await interaction.followup.send(f'❌ Error saving baseline: {ex}', ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  GOALS
# ═══════════════════════════════════════════════════════════════════════════════
class GoalsMainView(discord.ui.View):
    def __init__(self, user_data: dict, member: discord.Member | discord.User):
        super().__init__(timeout=120)
        self.user_data = user_data
        self.member    = member

    @discord.ui.button(label='➕ Add Goal', style=discord.ButtonStyle.primary, row=0)
    async def add_goal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            '🎯 **Which stat is this goal for?**',
            view=GoalFieldSelectView(editing_goal=None),
            ephemeral=True,
        )

    @discord.ui.button(label='✏️ Edit / Delete Goals', style=discord.ButtonStyle.secondary, row=0)
    async def manage_goals(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.user_data.get('goals'):
            await interaction.response.send_message('You have no goals set yet.', ephemeral=True)
            return
        embed = build_goals_embed(self.user_data, self.member)
        view  = GoalsManageView(self.user_data, self.member)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label='📢 Publish to Channel', style=discord.ButtonStyle.secondary, row=1)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed   = build_goals_embed(self.user_data, self.member)
        mention = fitness_role_mention(interaction.guild)
        await interaction.channel.send(content=mention, embed=embed)
        button.disabled = True
        await interaction.response.edit_message(view=self)


class GoalFieldSelectView(discord.ui.View):
    def __init__(self, editing_goal: dict | None = None):
        super().__init__(timeout=120)
        self.add_item(GoalFieldSelect(editing_goal=editing_goal))


class GoalFieldSelect(discord.ui.Select):
    def __init__(self, editing_goal: dict | None = None):
        self.editing_goal = editing_goal
        options = [
            discord.SelectOption(label=v['label'], value=k)
            for k, v in GOAL_FIELDS.items()
        ]
        super().__init__(placeholder='Select stat for this goal…', options=options)

    async def callback(self, interaction: discord.Interaction):
        field = self.values[0]
        await interaction.response.send_modal(
            GoalModal(field=field, editing_goal=self.editing_goal)
        )


class GoalModal(discord.ui.Modal, title='Set Fitness Goal'):
    target_value  = discord.ui.TextInput(label='Target Value',               placeholder='e.g. 180  or  01:00')
    target_date   = discord.ui.TextInput(label='Target Date (YYYY-MM-DD)',    placeholder='e.g. 2026-12-31')
    milestone_pct = discord.ui.TextInput(label='Milestone % (blank = none)', placeholder='e.g. 25', required=False)

    def __init__(self, field: str, editing_goal: dict | None = None):
        super().__init__()
        self.field        = field
        self.editing_goal = editing_goal
        self.title        = f'Goal: {GOAL_FIELDS[field]["label"]}'  # type: ignore[assignment]
        if editing_goal:
            self.target_value.default  = str(editing_goal.get('target_value', ''))
            self.target_date.default   = str(editing_goal.get('target_date', ''))
            mp = editing_goal.get('milestone_pct')
            if mp is not None:
                self.milestone_pct.default = str(int(mp)) if mp == int(mp) else str(mp)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            mp_raw = self.milestone_pct.value.strip()
            mp     = float(mp_raw) if mp_raw else None

            data, sha = await gh_load()
            user_data = ensure_user(data, interaction.user)

            if self.editing_goal:
                for g in user_data['goals']:
                    if g['id'] == self.editing_goal['id']:
                        g['target_value']  = self.target_value.value.strip()
                        g['target_date']   = self.target_date.value.strip()
                        g['milestone_pct'] = mp
                        break
            else:
                user_data['goals'].append({
                    'id':                    str(uuid.uuid4()),
                    'label':                 GOAL_FIELDS[self.field]['label'],
                    'field':                 self.field,
                    'direction':             GOAL_FIELDS[self.field]['direction'],
                    'target_value':          self.target_value.value.strip(),
                    'target_date':           self.target_date.value.strip(),
                    'milestone_pct':         mp,
                    'created_at':            utcnow(),
                    'completed_at':          None,
                    'milestones_announced':  [],
                })

            await gh_save(data, sha, f'Goal updated for {interaction.user.name}')
            embed = build_goals_embed(user_data, interaction.user)
            view  = GoalsManageView(user_data, interaction.user)
            await interaction.followup.send('✅ Goal saved!', embed=embed, view=view, ephemeral=True)
        except Exception as ex:
            await interaction.followup.send(f'❌ Error: {ex}', ephemeral=True)


class GoalsManageView(discord.ui.View):
    def __init__(self, user_data: dict, member: discord.Member | discord.User):
        super().__init__(timeout=300)
        self.user_data = user_data
        self.member    = member
        goals = user_data.get('goals', [])
        if goals:
            self.add_item(GoalActionSelect(goals))

    @discord.ui.button(label='📢 Publish to Channel', style=discord.ButtonStyle.secondary, row=1)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed   = build_goals_embed(self.user_data, self.member)
        mention = fitness_role_mention(interaction.guild)
        await interaction.channel.send(content=mention, embed=embed)
        button.disabled = True
        await interaction.response.edit_message(view=self)


class GoalActionSelect(discord.ui.Select):
    def __init__(self, goals: list[dict]):
        self.goals = goals
        options: list[discord.SelectOption] = []
        for g in goals:
            fl = GOAL_FIELDS.get(g['field'], {}).get('label', g['field'])
            options.append(discord.SelectOption(label=f'✏️ Edit: {fl}',   value=f'edit|{g["id"]}'))
            options.append(discord.SelectOption(label=f'🗑️ Delete: {fl}', value=f'del|{g["id"]}'))
        super().__init__(placeholder='Edit or delete a goal…', options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        action, goal_id = self.values[0].split('|', 1)
        goal = next((g for g in self.goals if g['id'] == goal_id), None)
        if not goal:
            await interaction.response.send_message('❌ Goal not found.', ephemeral=True)
            return

        if action == 'edit':
            await interaction.response.send_message(
                '✏️ Select the stat for this goal:',
                view=GoalFieldSelectView(editing_goal=goal),
                ephemeral=True,
            )
        else:
            await interaction.response.defer(ephemeral=True)
            data, sha = await gh_load()
            user_data = ensure_user(data, interaction.user)
            user_data['goals'] = [g for g in user_data['goals'] if g['id'] != goal_id]
            await gh_save(data, sha, f'Goal deleted for {interaction.user.name}')
            embed = build_goals_embed(user_data, interaction.user)
            view  = GoalsManageView(user_data, interaction.user)
            await interaction.followup.send('🗑️ Goal deleted.', embed=embed, view=view, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  STATS
# ═══════════════════════════════════════════════════════════════════════════════
class StatsMainView(discord.ui.View):
    def __init__(self, user_data: dict, member: discord.Member | discord.User):
        super().__init__(timeout=120)
        self.user_data = user_data
        self.member    = member

    @discord.ui.button(label='📊 View Stats', style=discord.ButtonStyle.secondary, row=0)
    async def view_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_stats_embed(self.user_data, self.member)
        view  = PublishView(embed=embed, guild=interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label='✏️ Update Stats', style=discord.ButtonStyle.primary, row=0)
    async def update_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = self.user_data['stats'][-1] if self.user_data.get('stats') else None
        await interaction.response.send_modal(StatsModal1(user_data=self.user_data, existing=existing))


class StatsModal1(discord.ui.Modal, title='Update Stats — Part 1 of 2'):
    weight       = discord.ui.TextInput(label='Weight',     placeholder='e.g. 185',  required=False)
    body_fat_pct = discord.ui.TextInput(label='Body Fat %', placeholder='e.g. 22.5', required=False)
    neck         = discord.ui.TextInput(label='Neck',       placeholder='e.g. 15.5', required=False)
    chest        = discord.ui.TextInput(label='Chest',      placeholder='e.g. 42.0', required=False)
    waist        = discord.ui.TextInput(label='Waist',      placeholder='e.g. 36.0', required=False)

    def __init__(self, user_data: dict, existing: dict | None = None):
        super().__init__()
        self.user_data = user_data
        if existing:
            if existing.get('weight')       is not None: self.weight.default       = str(existing['weight'])
            if existing.get('body_fat_pct') is not None: self.body_fat_pct.default = str(existing['body_fat_pct'])
            if existing.get('neck')         is not None: self.neck.default         = str(existing['neck'])
            if existing.get('chest')        is not None: self.chest.default        = str(existing['chest'])
            if existing.get('waist')        is not None: self.waist.default        = str(existing['waist'])

    async def on_submit(self, interaction: discord.Interaction):
        part1 = {
            'weight':       self.weight.value or None,
            'body_fat_pct': self.body_fat_pct.value or None,
            'neck':         self.neck.value or None,
            'chest':        self.chest.value or None,
            'waist':        self.waist.value or None,
        }
        prev = self.user_data['stats'][-1] if self.user_data.get('stats') else {}
        await interaction.response.send_modal(
            StatsModal2(user_data=self.user_data, part1=part1, prev=prev)
        )


class StatsModal2(discord.ui.Modal, title='Update Stats — Part 2 of 2'):
    resting_heart_rate = discord.ui.TextInput(label='Resting Heart Rate (bpm)', placeholder='e.g. 65',    required=False)
    bench              = discord.ui.TextInput(label='Bench Press',              placeholder='e.g. 145',   required=False)
    cardio_duration    = discord.ui.TextInput(label='Cardio Duration (HH:MM)',  placeholder='e.g. 00:35', required=False)
    notes              = discord.ui.TextInput(
        label='Notes',
        style=discord.TextStyle.paragraph,
        placeholder='How are you feeling? Any context?',
        required=False,
        max_length=500,
    )

    def __init__(self, user_data: dict, part1: dict, prev: dict):
        super().__init__()
        self.user_data = user_data
        self.part1     = part1
        self.prev      = prev
        if prev.get('resting_heart_rate') is not None:
            self.resting_heart_rate.default = str(prev['resting_heart_rate'])
        if prev.get('bench')              is not None: self.bench.default              = str(prev['bench'])
        if prev.get('cardio_duration')    is not None: self.cardio_duration.default    = str(prev['cardio_duration'])

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            data, sha = await gh_load()
            user_data = ensure_user(data, interaction.user)
            prev      = user_data['stats'][-1] if user_data.get('stats') else {}

            def n(raw: str | None, key: str) -> float | None:
                s = (raw or '').strip()
                if s:
                    v = parse_num(s)
                    return v if v is not None else prev.get(key)
                return prev.get(key)

            def cd(raw: str | None, key: str) -> str | None:
                s = (raw or '').strip()
                return s if s else prev.get(key)

            entry = {
                'recorded_at':        utcnow(),
                'weight':             n(self.part1.get('weight'),       'weight'),
                'body_fat_pct':       n(self.part1.get('body_fat_pct'), 'body_fat_pct'),
                'neck':               n(self.part1.get('neck'),         'neck'),
                'chest':              n(self.part1.get('chest'),        'chest'),
                'waist':              n(self.part1.get('waist'),        'waist'),
                'resting_heart_rate': n(self.resting_heart_rate.value,  'resting_heart_rate'),
                'bench':              n(self.bench.value,               'bench'),
                'cardio_duration':    cd(self.cardio_duration.value,    'cardio_duration'),
                'notes':              self.notes.value.strip() or None,
            }
            user_data['stats'].append(entry)

            # Check goals before saving
            events = check_goals_after_update(user_data)
            await gh_save(data, sha, f'Stats updated for {interaction.user.name}')

            embed = build_stats_embed(user_data, interaction.user, entry)
            view  = PublishView(embed=embed, guild=interaction.guild)
            await interaction.followup.send('✅ **Stats updated!**', embed=embed, view=view, ephemeral=True)

            # Surface any goal achievements
            if events:
                lines = []
                for ev in events:
                    fl = GOAL_FIELDS.get(ev['goal']['field'], {}).get('label', ev['goal']['field'])
                    if ev['type'] == 'completed':
                        lines.append(f'🏆 You completed your **{fl}** goal!')
                    else:
                        lines.append(f'🎉 **{int(ev["milestone_pct"])}%** milestone hit for **{fl}**!')

                achievement_embed = discord.Embed(
                    title=f'🏆 {interaction.user.display_name} — Fitness Achievement!',
                    description='\n'.join(lines),
                    color=discord.Color.gold(),
                    timestamp=datetime.now(timezone.utc),
                )
                achievement_view = PublishView(embed=achievement_embed, guild=interaction.guild)
                await interaction.followup.send(
                    '🎉 **You hit a milestone!** Want to share it?',
                    embed=achievement_embed,
                    view=achievement_view,
                    ephemeral=True,
                )
        except Exception as ex:
            await interaction.followup.send(f'❌ Error: {ex}', ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  HISTORY
# ═══════════════════════════════════════════════════════════════════════════════
class HistoryView(discord.ui.View):
    def __init__(self, user_data: dict, member: discord.Member | discord.User, ws: str):
        super().__init__(timeout=300)
        self.user_data = user_data
        self.member    = member
        self.ws        = ws  # YYYY-MM-DD of the Sunday

    @discord.ui.button(label='◀ Prev Week', style=discord.ButtonStyle.secondary, row=0)
    async def prev_week(self, interaction: discord.Interaction, button: discord.ui.Button):
        dt      = datetime.strptime(self.ws, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        self.ws = (dt - timedelta(weeks=1)).strftime('%Y-%m-%d')
        await self._refresh(interaction)

    @discord.ui.button(label='Next Week ▶', style=discord.ButtonStyle.secondary, row=0)
    async def next_week(self, interaction: discord.Interaction, button: discord.ui.Button):
        dt         = datetime.strptime(self.ws, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        future_ws  = (dt + timedelta(weeks=1)).strftime('%Y-%m-%d')
        if future_ws > week_start_for():
            await interaction.response.send_message("⚠️ Can't view future weeks.", ephemeral=True)
            return
        self.ws = future_ws
        await self._refresh(interaction)

    @discord.ui.button(label='📝 Add / Edit Note', style=discord.ButtonStyle.primary, row=1)
    async def add_note(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = next(
            (n for n in self.user_data.get('history_notes', []) if n['week_start'] == self.ws), None
        )
        await interaction.response.send_modal(
            HistoryNoteModal(ws=self.ws, existing_note=existing['note'] if existing else '')
        )

    @discord.ui.button(label='📢 Publish to Channel', style=discord.ButtonStyle.secondary, row=1)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed   = build_history_embed(self.user_data, self.member, self.ws)
        mention = fitness_role_mention(interaction.guild)
        await interaction.channel.send(content=mention, embed=embed)
        button.disabled = True
        await interaction.response.edit_message(view=self)

    async def _refresh(self, interaction: discord.Interaction):
        data, _   = await gh_load()
        user_data = ensure_user(data, interaction.user)
        self.user_data = user_data
        embed = build_history_embed(user_data, self.member, self.ws)
        await interaction.response.edit_message(embed=embed, view=self)


class HistoryNoteModal(discord.ui.Modal, title='Weekly Note'):
    note = discord.ui.TextInput(
        label='Note for this week',
        style=discord.TextStyle.paragraph,
        placeholder='How did the week go? Any highlights or setbacks?',
        max_length=1000,
    )

    def __init__(self, ws: str, existing_note: str = ''):
        super().__init__()
        self.ws = ws
        if existing_note:
            self.note.default = existing_note

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            data, sha = await gh_load()
            user_data = ensure_user(data, interaction.user)
            notes     = user_data.setdefault('history_notes', [])
            existing  = next((n for n in notes if n['week_start'] == self.ws), None)
            if existing:
                existing['note'] = self.note.value.strip()
            else:
                notes.append({'week_start': self.ws, 'note': self.note.value.strip()})
            await gh_save(data, sha, f'History note updated for {interaction.user.name}')
            embed = build_history_embed(user_data, interaction.user, self.ws)
            view  = HistoryView(user_data, interaction.user, self.ws)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as ex:
            await interaction.followup.send(f'❌ Error: {ex}', ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  WORKOUT LOG
# ═══════════════════════════════════════════════════════════════════════════════
def build_workout_log_page(
    user_data: dict,
    member: discord.Member | discord.User,
    page: int,
) -> tuple[discord.Embed, 'WorkoutLogPageView']:
    logs      = sorted(user_data.get('workout_log', []), key=lambda x: x['logged_at'], reverse=True)
    total     = len(logs)
    max_page  = max(0, (total - 1) // PAGE_SIZE) if total else 0
    page      = max(0, min(page, max_page))
    chunk     = logs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    e = discord.Embed(
        title=f'🏋️ {member.display_name} — Workout Log',
        description=f'Page {page + 1} of {max_page + 1}  ·  {total} total entries',
        color=discord.Color.blue(),
    )
    for w in chunk:
        e.add_field(
            name=f'[{w.get("category","?")}] {w["workout"]} — {w["logged_at"][:10]}',
            value=(w.get('details') or '')[:256],
            inline=False,
        )
    view = WorkoutLogPageView(user_data=user_data, member=member, page=page, max_page=max_page, logs=logs)
    return e, view


class WorkoutLogMainView(discord.ui.View):
    def __init__(self, user_data: dict, member: discord.Member | discord.User):
        super().__init__(timeout=120)
        self.user_data = user_data
        self.member    = member

    @discord.ui.button(label='➕ New Entry', style=discord.ButtonStyle.primary, row=0)
    async def new_entry(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            '🏋️ **Select a workout category:**',
            view=WorkoutCategorySelectView(),
            ephemeral=True,
        )

    @discord.ui.button(label='📋 View Log', style=discord.ButtonStyle.secondary, row=0)
    async def view_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, view = build_workout_log_page(self.user_data, self.member, page=0)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class WorkoutCategorySelectView(discord.ui.View):
    def __init__(self, editing_entry: dict | None = None):
        super().__init__(timeout=120)
        self.add_item(WorkoutCategorySelect(editing_entry=editing_entry))


class WorkoutCategorySelect(discord.ui.Select):
    def __init__(self, editing_entry: dict | None = None):
        self.editing_entry = editing_entry
        options = [
            discord.SelectOption(
                label=c,
                value=c,
                default=(editing_entry is not None and c == editing_entry.get('category')),
            )
            for c in WORKOUT_CATEGORIES
        ]
        super().__init__(placeholder='Select category…', options=options)

    async def callback(self, interaction: discord.Interaction):
        modal = WorkoutModal(category=self.values[0], editing_entry=self.editing_entry)
        if self.editing_entry:
            modal.workout.default = self.editing_entry.get('workout', '')
            modal.details.default = self.editing_entry.get('details', '')
        await interaction.response.send_modal(modal)


class WorkoutModal(discord.ui.Modal, title='Log Workout'):
    workout = discord.ui.TextInput(
        label='Workout Name',
        placeholder='e.g. Upper Body Day, 5K Run, Leg Day',
        max_length=100,
    )
    details = discord.ui.TextInput(
        label='Details',
        style=discord.TextStyle.paragraph,
        placeholder='e.g. Bench 3×8 @ 155lbs, 5K in 28:42…',
        max_length=1000,
        required=False,
    )

    def __init__(self, category: str, editing_entry: dict | None = None):
        super().__init__()
        self.category      = category
        self.editing_entry = editing_entry

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            data, sha = await gh_load()
            user_data = ensure_user(data, interaction.user)

            if self.editing_entry:
                for w in user_data['workout_log']:
                    if w['id'] == self.editing_entry['id']:
                        w['workout']  = self.workout.value.strip()
                        w['details']  = self.details.value.strip()
                        w['category'] = self.category
                        break
                msg = '✅ Entry updated!'
            else:
                user_data['workout_log'].append({
                    'id':        str(uuid.uuid4()),
                    'logged_at': utcnow(),
                    'category':  self.category,
                    'workout':   self.workout.value.strip(),
                    'details':   self.details.value.strip(),
                })
                msg = '✅ Workout logged!'

            await gh_save(data, sha, f'Workout log updated for {interaction.user.name}')
            embed, view = build_workout_log_page(user_data, interaction.user, page=0)
            await interaction.followup.send(msg, embed=embed, view=view, ephemeral=True)
        except Exception as ex:
            await interaction.followup.send(f'❌ Error: {ex}', ephemeral=True)


class WorkoutLogPageView(discord.ui.View):
    def __init__(
        self,
        user_data: dict,
        member: discord.Member | discord.User,
        page: int,
        max_page: int,
        logs: list[dict],
    ):
        super().__init__(timeout=300)
        self.user_data = user_data
        self.member    = member
        self.page      = page
        self.max_page  = max_page
        self.logs      = logs
        chunk = logs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        if chunk:
            self.add_item(WorkoutActionSelect(chunk))

    @discord.ui.button(label='◀ Prev', style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            embed, view = build_workout_log_page(self.user_data, self.member, self.page - 1)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.defer()

    @discord.ui.button(label='Next ▶', style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_page:
            embed, view = build_workout_log_page(self.user_data, self.member, self.page + 1)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.defer()

    @discord.ui.button(label='📢 Publish to Channel', style=discord.ButtonStyle.secondary, row=2)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        chunk = self.logs[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        pub   = discord.Embed(
            title=f'🏋️ {self.member.display_name} — Recent Workouts',
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        for w in chunk:
            pub.add_field(
                name=f'[{w.get("category","?")}] {w["workout"]} — {w["logged_at"][:10]}',
                value=(w.get('details') or '')[:256],
                inline=False,
            )
        mention = fitness_role_mention(interaction.guild)
        await interaction.channel.send(content=mention, embed=pub)
        button.disabled = True
        await interaction.response.edit_message(view=self)


class WorkoutActionSelect(discord.ui.Select):
    def __init__(self, chunk: list[dict]):
        self.chunk = chunk
        options: list[discord.SelectOption] = []
        for w in chunk:
            label = f'{w["workout"][:28]} ({w["logged_at"][:10]})'
            options.append(discord.SelectOption(label=f'✏️ Edit: {label}',   value=f'edit|{w["id"]}'))
            options.append(discord.SelectOption(label=f'🗑️ Delete: {label}', value=f'del|{w["id"]}'))
        super().__init__(placeholder='Edit or delete an entry…', options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        action, entry_id = self.values[0].split('|', 1)
        entry = next((w for w in self.chunk if w['id'] == entry_id), None)

        if action == 'del':
            await interaction.response.defer(ephemeral=True)
            data, sha = await gh_load()
            user_data = ensure_user(data, interaction.user)
            user_data['workout_log'] = [w for w in user_data['workout_log'] if w['id'] != entry_id]
            await gh_save(data, sha, f'Workout deleted for {interaction.user.name}')
            embed, view = build_workout_log_page(user_data, interaction.user, page=0)
            await interaction.followup.send('🗑️ Entry deleted.', embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(
                '✏️ Select the new category:',
                view=WorkoutCategorySelectView(editing_entry=entry),
                ephemeral=True,
            )

# ═══════════════════════════════════════════════════════════════════════════════
#  PRIVACY
# ═══════════════════════════════════════════════════════════════════════════════
class PrivacyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label='🌐 Set Public', style=discord.ButtonStyle.success)
    async def set_public(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set(interaction, True)

    @discord.ui.button(label='🔒 Set Private', style=discord.ButtonStyle.danger)
    async def set_private(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set(interaction, False)

    async def _set(self, interaction: discord.Interaction, value: bool):
        await interaction.response.defer(ephemeral=True)
        try:
            data, sha = await gh_load()
            user_data = ensure_user(data, interaction.user)
            user_data['meta']['is_public'] = value
            await gh_save(data, sha, f'Privacy updated for {interaction.user.name}')
            label = 'Public 🌐' if value else 'Private 🔒'
            await interaction.followup.send(f'✅ Your profile is now **{label}**.', ephemeral=True)
        except Exception as ex:
            await interaction.followup.send(f'❌ Error: {ex}', ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  FITNESS HUB  (/b4c0nfitness + panel button)
# ═══════════════════════════════════════════════════════════════════════════════
class FitnessHubView(discord.ui.View):
    def __init__(self, user_data: dict | None, member: discord.Member | discord.User):
        super().__init__(timeout=120)
        self.user_data = user_data
        self.member    = member
        self.add_item(FitnessHubSelect(user_data))


class FitnessHubSelect(discord.ui.Select):
    def __init__(self, user_data: dict | None):
        has_baseline = bool(user_data and user_data.get('baseline'))
        is_public    = user_data['meta']['is_public'] if user_data else True
        priv_label   = 'Public 🌐' if is_public else 'Private 🔒'
        nb           = '  ⚠️ (baseline required)' if not has_baseline else ''

        options = [
            discord.SelectOption(
                label='🔒 Privacy Settings',
                description=f'Currently: {priv_label}',
                value='privacy',
            ),
            discord.SelectOption(
                label='📏 Set Baseline',
                description='Set your starting stats (required first)',
                value='baseline',
            ),
            discord.SelectOption(
                label='🎯 Fitness Goals',
                description=f'View or manage your goals{nb}',
                value='goals',
            ),
            discord.SelectOption(
                label='📊 Current Stats',
                description=f'View or update your stats{nb}',
                value='stats',
            ),
            discord.SelectOption(
                label='📅 Fitness History',
                description='Browse your weekly progress',
                value='history',
            ),
            discord.SelectOption(
                label='🏋️ Workout Log',
                description='Log or browse workouts',
                value='workout',
            ),
        ]
        super().__init__(placeholder='Select a feature…', options=options)

    async def callback(self, interaction: discord.Interaction):
        choice    = self.values[0]
        user_data = self.view.user_data
        member    = self.view.member

        # Gate features that need a baseline
        if choice in ('goals', 'stats') and not (user_data and user_data.get('baseline')):
            await interaction.response.send_message(
                '⚠️ You need to **set your baseline** first using `/setfitbaseline` '
                'or the **Set Baseline** option above.',
                ephemeral=True,
            )
            return

        if choice == 'privacy':
            is_public = user_data['meta']['is_public'] if user_data else True
            await interaction.response.send_message(
                f'Your profile is currently **{"Public 🌐" if is_public else "Private 🔒"}**. '
                'Update below:',
                view=PrivacyView(),
                ephemeral=True,
            )

        elif choice == 'baseline':
            unit     = user_data['meta'].get('unit_preference', 'lbs') if user_data else 'lbs'
            existing = user_data.get('baseline') if user_data else None
            await interaction.response.send_message(
                '📏 **Set your baseline stats.**\nFirst, choose your unit preference:',
                view=BaselineUnitView(existing_unit=unit, existing=existing),
                ephemeral=True,
            )

        elif choice == 'goals':
            embed = build_goals_embed(user_data, member)
            view  = GoalsMainView(user_data, member)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        elif choice == 'stats':
            view = StatsMainView(user_data, member)
            await interaction.response.send_message(
                '📊 **Fitness Stats** — view your current numbers or log an update:',
                view=view,
                ephemeral=True,
            )

        elif choice == 'history':
            ws    = week_start_for()
            ud    = user_data or {'meta': {}, 'stats': [], 'workout_log': [], 'history_notes': []}
            embed = build_history_embed(ud, member, ws)
            view  = HistoryView(ud, member, ws)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        elif choice == 'workout':
            ud   = user_data or {'workout_log': []}
            view = WorkoutLogMainView(ud, member)
            await interaction.response.send_message(
                '🏋️ **Workout Log** — log a new workout or browse past entries:',
                view=view,
                ephemeral=True,
            )

# ═══════════════════════════════════════════════════════════════════════════════
#  QUOTE IMAGE GENERATION  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════
async def generate_quote_image(user: discord.Member, quote_text: str) -> bytes:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(user.display_avatar.url)) as resp:
                avatar_bytes = await resp.read()
            async with session.get(SPEECH_BUBBLE_IMAGE) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to download bubble: HTTP {resp.status}")
                bubble_bytes = await resp.read()

        avatar      = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
        bubble_orig = Image.open(BytesIO(bubble_bytes)).convert("RGBA")

        avatar_size = 120
        avatar = avatar.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        mask   = Image.new('L', (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar.putalpha(mask)

        font          = ImageFont.load_default(size=24)
        username_font = ImageFont.load_default(size=18)

        max_chars = 200
        if len(quote_text) > max_chars:
            quote_text = quote_text[:max_chars - 3] + "..."

        line_height   = 28
        h_pad_left    = 0.15
        h_pad_right   = 0.075
        v_pad_px      = 100
        draw_temp     = ImageDraw.Draw(Image.new('RGBA', (1, 1)))

        def wrap_text(text, max_width):
            lines, current_line = [], ""
            for word in text.split():
                test_line = current_line + word + " "
                if draw_temp.textbbox((0, 0), test_line, font=font)[2] <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line.strip())
                    current_line = word + " "
            if current_line:
                lines.append(current_line.strip())
            return lines

        best_width, best_diff = 450, float('inf')
        for tw in range(350, 750, 10):
            tl = wrap_text(quote_text, int(tw * (1 - h_pad_left - h_pad_right)))
            th = max(len(tl) * line_height + v_pad_px, 150)
            d  = abs(tw / th - 3.0)
            if d < best_diff:
                best_diff, best_width = d, tw

        target_bubble_width  = max(best_width, 300)
        text_area_width      = int(target_bubble_width * (1 - h_pad_left - h_pad_right))
        lines                = wrap_text(quote_text, text_area_width)
        text_block_height    = len(lines) * line_height
        target_bubble_height = max(text_block_height + v_pad_px, 120)

        bubble   = bubble_orig.resize((target_bubble_width, target_bubble_height), Image.Resampling.LANCZOS)
        padding  = 20
        bubble_x = avatar_size + padding
        bubble_y = padding
        avatar_x = padding
        avatar_y = bubble_y + target_bubble_height - avatar_size + 10

        canvas = Image.new('RGBA', (
            bubble_x + target_bubble_width + padding,
            max(avatar_y + avatar_size + 40, bubble_y + target_bubble_height + padding),
        ), (0, 0, 0, 0))
        canvas.paste(bubble, (bubble_x, bubble_y), bubble)
        canvas.paste(avatar, (avatar_x, avatar_y), avatar)

        draw             = ImageDraw.Draw(canvas)
        text_area_x      = bubble_x + int(target_bubble_width * h_pad_left)
        text_offset_y    = bubble_y + (target_bubble_height - text_block_height) // 3

        for i, line in enumerate(lines):
            lw    = draw.textbbox((0, 0), line, font=font)[2]
            tx    = text_area_x + (text_area_width - lw) // 2
            draw.text((tx, text_offset_y + i * line_height), line, font=font, fill=(255, 255, 255, 255))

        name_w = draw.textbbox((0, 0), user.display_name, font=username_font)[2]
        draw.text(
            (avatar_x + (avatar_size - name_w) // 2, avatar_y + avatar_size + 5),
            user.display_name, font=username_font, fill=(255, 255, 255, 255),
        )

        output = BytesIO()
        canvas.save(output, format='PNG')
        output.seek(0)
        return output.getvalue()

    except Exception as e:
        import traceback
        print(f"Error in generate_quote_image: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise

# ═══════════════════════════════════════════════════════════════════════════════
#  QUOTE MODALS  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════
class UserQuoteModal(discord.ui.Modal, title="Submit a Quote"):
    username   = discord.ui.TextInput(
        label="Who said it? (@ mention or display name)",
        style=discord.TextStyle.short, placeholder="e.g. @Dave or Dave",
        required=True, max_length=100,
    )
    quote_text = discord.ui.TextInput(
        label="What did they say?",
        style=discord.TextStyle.paragraph, placeholder="Enter the quote here...",
        required=True, max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        query  = str(self.username).lstrip("<@!>").rstrip(">")
        member = interaction.guild.get_member(int(query)) if query.isdigit() else None
        if not member:
            ql     = str(self.username).lower().lstrip("<@!>").rstrip(">")
            member = discord.utils.find(
                lambda m: m.display_name.lower() == ql or m.name.lower() == ql,
                interaction.guild.members,
            )
        if not member:
            await interaction.followup.send(
                f"❌ Couldn't find **{self.username}**. Try their exact display name or paste their @ mention.",
                ephemeral=True,
            )
            return
        try:
            image_bytes = await generate_quote_image(member, str(self.quote_text))
            if QUOTES_CHANNEL_ID:
                channel = client.get_channel(QUOTES_CHANNEL_ID)
                if channel:
                    await channel.send(
                        content=f"📜 {member.mention}'s quote submitted by {interaction.user.mention}",
                        file=discord.File(fp=BytesIO(image_bytes), filename="quote.png"),
                    )
                    await interaction.followup.send("✅ Quote posted!", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Quotes channel not found!", ephemeral=True)
            else:
                await interaction.followup.send("❌ QUOTES_CHANNEL_ID not configured!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error creating quote: {e}", ephemeral=True)


class QuoteModal(discord.ui.Modal, title="Submit a Quote"):
    quote_text = discord.ui.TextInput(
        label="What did they say?",
        style=discord.TextStyle.paragraph, placeholder="Enter the quote here...",
        required=True, max_length=500,
    )

    def __init__(self, user: discord.Member):
        super().__init__()
        self.quoted_user = user

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            image_bytes = await generate_quote_image(self.quoted_user, str(self.quote_text))
            if QUOTES_CHANNEL_ID:
                channel = client.get_channel(QUOTES_CHANNEL_ID)
                if channel:
                    await channel.send(
                        content=f"📜 {self.quoted_user.mention}'s quote submitted by {interaction.user.mention}",
                        file=discord.File(fp=BytesIO(image_bytes), filename="quote.png"),
                    )
                    await interaction.followup.send("✅ Quote posted!", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Quotes channel not found!", ephemeral=True)
            else:
                await interaction.followup.send("❌ QUOTES_CHANNEL_ID not configured!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error creating quote: {e}", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  BOT PANEL
# ═══════════════════════════════════════════════════════════════════════════════
BOT_COMMANDS = [
    {
        "name":         "📜 Quote",
        "description":  "Immortalise what someone said as a generated quote image.",
        "button_label": "Quote Someone",
        "button_id":    "btn_quote",
    },
    {
        "name":         "🏋️ Fitness Tracker",
        "description":  "Set goals, log workouts, track stats, and view your weekly progress.",
        "button_label": "Fitness Tracker",
        "button_id":    "btn_fitness",
    },
]


class BotPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for cmd in BOT_COMMANDS:
            self.add_item(PanelButton(label=cmd["button_label"], custom_id=cmd["button_id"]))


class PanelButton(discord.ui.Button):
    def __init__(self, label: str, custom_id: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        if self.custom_id == "btn_quote":
            await interaction.response.send_modal(UserQuoteModal())

        elif self.custom_id == "btn_fitness":
            try:
                data, _   = await gh_load()
                user_data = data['users'].get(str(interaction.user.id))
                # Ensure user record exists (without saving — first real action will save)
                if not user_data:
                    # Pre-populate for the hub but don't write yet
                    user_data = None
            except Exception:
                user_data = None

            embed = discord.Embed(
                title='🏋️ Fitness Tracker',
                description=(
                    'Track your fitness goals, stats, workout history, and more.\n\n'
                    '**First time?** Start with **Set Baseline** to record your starting point.\n'
                    'All responses are private to you unless you choose to publish them.'
                ),
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(
                embed=embed,
                view=FitnessHubView(user_data=user_data, member=interaction.user),
                ephemeral=True,
            )

# ═══════════════════════════════════════════════════════════════════════════════
#  EVENTS
# ═══════════════════════════════════════════════════════════════════════════════
@client.event
async def on_ready():
    client.add_view(BotPanelView())
    await tree.sync()
    print(f'✅ Logged in as {client.user}')
    print(f'📝 Commands synced and ready!')
    if QUOTES_CHANNEL_ID:
        print(f'📜 Posting quotes to channel ID: {QUOTES_CHANNEL_ID}')
    else:
        print(f'⚠️  QUOTES_CHANNEL_ID not set!')
    if GITHUB_TOKEN:
        print(f'🐙 GitHub token present — fitness data enabled')
    else:
        print(f'⚠️  GITHUB_TOKEN not set — fitness features will not save!')
    if FITNESS_ROLE_ID:
        print(f'💪 Fitness role ID: {FITNESS_ROLE_ID}')
    else:
        print(f'ℹ️  FITNESS_ROLE_ID not set — publishes will not ping a role')

# ═══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Existing ──────────────────────────────────────────────────────────────────
@tree.command(name="quote", description="Quote a server member")
async def quote(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.send_modal(QuoteModal(user))


@tree.command(name="initializeb4c0n", description="Post the bot command panel in this channel (admin only)")
@app_commands.checks.has_permissions(manage_guild=True)
async def initializeb4c0n(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🥓 b4c0n — Commands",
        description="\n\n".join(
            f"**{cmd['name']}**\n{cmd['description']}" for cmd in BOT_COMMANDS
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text="Use the buttons below or slash commands directly.")
    await interaction.response.send_message(embed=embed, view=BotPanelView())


@initializeb4c0n.error
async def initializeb4c0n_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need the **Manage Server** permission to use this command.", ephemeral=True
        )

# ── Fitness ───────────────────────────────────────────────────────────────────
@tree.command(name="b4c0nfitness", description="Open the fitness tracker hub")
async def b4c0nfitness(interaction: discord.Interaction):
    try:
        data, _   = await gh_load()
        user_data = data['users'].get(str(interaction.user.id))
    except Exception:
        user_data = None

    embed = discord.Embed(
        title='🏋️ Fitness Tracker',
        description=(
            'Track your fitness goals, stats, workout history, and more.\n\n'
            '**First time?** Start with **Set Baseline** to record your starting point.\n'
            'All responses are private to you unless you choose to publish them.'
        ),
        color=discord.Color.orange(),
    )
    await interaction.response.send_message(
        embed=embed,
        view=FitnessHubView(user_data=user_data, member=interaction.user),
        ephemeral=True,
    )


@tree.command(name="setfitbaseline", description="Set your fitness baseline (required before goals & stats)")
async def setfitbaseline(interaction: discord.Interaction):
    try:
        data, _   = await gh_load()
        user_data = data['users'].get(str(interaction.user.id))
    except Exception:
        user_data = None

    unit     = user_data['meta'].get('unit_preference', 'lbs') if user_data else 'lbs'
    existing = user_data.get('baseline') if user_data else None
    await interaction.response.send_message(
        '📏 **Set your baseline stats.**\nFirst, choose your unit preference:',
        view=BaselineUnitView(existing_unit=unit, existing=existing),
        ephemeral=True,
    )


@tree.command(name="setfitgoals", description="View or manage your fitness goals")
async def setfitgoals(interaction: discord.Interaction):
    try:
        data, _   = await gh_load()
        user_data = data['users'].get(str(interaction.user.id))
    except Exception:
        user_data = None

    if not user_data or not user_data.get('baseline'):
        await interaction.response.send_message(
            '⚠️ Set your baseline first with `/setfitbaseline`.', ephemeral=True
        )
        return

    embed = build_goals_embed(user_data, interaction.user)
    view  = GoalsMainView(user_data, interaction.user)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@tree.command(name="currentfitstats", description="View or update your current fitness stats")
async def currentfitstats(interaction: discord.Interaction):
    try:
        data, _   = await gh_load()
        user_data = data['users'].get(str(interaction.user.id))
    except Exception:
        user_data = None

    if not user_data or not user_data.get('baseline'):
        await interaction.response.send_message(
            '⚠️ Set your baseline first with `/setfitbaseline`.', ephemeral=True
        )
        return

    view = StatsMainView(user_data, interaction.user)
    await interaction.response.send_message(
        '📊 **Fitness Stats** — view your current numbers or log an update:',
        view=view,
        ephemeral=True,
    )


@tree.command(name="fithistory", description="Browse your weekly fitness history")
async def fithistory(interaction: discord.Interaction):
    try:
        data, _   = await gh_load()
        user_data = data['users'].get(str(interaction.user.id))
    except Exception:
        user_data = None

    ud    = user_data or {'meta': {}, 'stats': [], 'workout_log': [], 'history_notes': []}
    ws    = week_start_for()
    embed = build_history_embed(ud, interaction.user, ws)
    view  = HistoryView(ud, interaction.user, ws)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@tree.command(name="fitworkoutlog", description="Log a new workout or browse your workout history")
async def fitworkoutlog(interaction: discord.Interaction):
    try:
        data, _   = await gh_load()
        user_data = data['users'].get(str(interaction.user.id))
    except Exception:
        user_data = None

    ud   = user_data or {'workout_log': []}
    view = WorkoutLogMainView(ud, interaction.user)
    await interaction.response.send_message(
        '🏋️ **Workout Log** — log a new workout or browse past entries:',
        view=view,
        ephemeral=True,
    )


client.run(os.getenv('DISCORD_TOKEN'))
