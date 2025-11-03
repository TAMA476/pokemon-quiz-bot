import os
import aiohttp
import random
import discord
import asyncio
from dotenv import load_dotenv
from discord.ui import View, Select

# 環境変数を.envファイルから読み込み
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN") # DiscordのBOTトークンを取得

# どの情報を受け取るのかの設定
intents = discord.Intents.default() # デフォルト設定
intents.message_content = True # ユーザーの発言内容取得許可
# Discordサーバーと通信してメッセージやイベントを受け取るクライアントを作成
bot = discord.Client(intents=intents)

active_quizzes = {} # 現在稼働中のクイズ情報を記録する辞書
session: aiohttp.ClientSession = None  # APIとの通信用セッションを準備（グローバル共有セッション）

# 世代選択View
class GenerationSelect(View):
    """世代選択メニューUI作成クラス"""
    def __init__(self):
        """初期設定"""
        super().__init__(timeout=60)
        options = [
            discord.SelectOption(label="初代", value="generation-i"),
            discord.SelectOption(label="第2世代", value="generation-ii"),
            discord.SelectOption(label="第3世代", value="generation-iii"),
            discord.SelectOption(label="第4世代", value="generation-iv"),
            discord.SelectOption(label="第5世代", value="generation-v"),
            discord.SelectOption(label="第6世代", value="generation-vi"),
            discord.SelectOption(label="第7世代", value="generation-vii"),
            discord.SelectOption(label="第8世代", value="generation-viii"),
            discord.SelectOption(label="第9世代", value="generation-ix"),
        ]

        self.select = Select(
            placeholder="出題する世代を選んでね（複数可）",
            min_values=1,
            max_values=9,
            options=options
        )
        # ユーザーが選択時に呼ばれる関数を定義（select_callback()）
        self.select.callback = self.select_callback
        # 選択メニューをViewに追加
        self.add_item(self.select)
        # ユーザーが選択した世代を保存
        self.selected_generations = []

    async def select_callback(self, interaction: discord.Interaction): # ユーザーが操作した情報（誰が、どこで、何を選んだか）
        self.selected_generations = self.select.values
        readable = [opt.label for opt in self.select.options if opt.value in self.selected_generations]
        await interaction.response.send_message(
            f"選択された世代: {', '.join(readable)}", ephemeral=True
        )
        self.stop()  # ユーザー選択を確定

async def get_pokemon_species_data(pokemon_id):
    """PokéAPIからポケモン種(species)情報を取得"""
    global session
    url = f"https://pokeapi.co/api/v2/pokemon-species/{pokemon_id}"
    try:
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                return None
            data = await response.json()
            return data
    except Exception as e:
        print(f"[ERROR] Failed to fetch species data: {e}")
        return None

async def get_pokemon_detail_data(pokemon_id):
    """タイプ・特性などを取得（/pokemon エンドポイント）"""
    global session
    url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_id}"
    try:
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                return None
            data = await response.json()
            return data
    except Exception as e:
        print(f"[ERROR] Failed to fetch detail data: {e}")
        return None

def get_name_in_language(data, lang):
    """dataから特定の言語のポケモン名を取得"""
    for name_entry in data.get("names", []):
        if name_entry["language"]["name"] == lang:
            return name_entry["name"]
    return None

def get_english_flavor_text(data):
    """dataから英語の図鑑説明を取得"""
    entry = next(
        (e for e in data.get("flavor_text_entries", []) if e["language"]["name"] == "en"),
        None
    )
    if entry:
        return entry["flavor_text"].replace('\n', ' ').replace('\u3000', ' ')
    return "No English Pokédex entry found."

def get_generation_japanese(data):
    """登場世代を日本語で返す"""
    gen_en = data.get("generation", {}).get("name", "")
    mapping = {
        "generation-i": "初代",
        "generation-ii": "第2世代",
        "generation-iii": "第3世代",
        "generation-iv": "第4世代",
        "generation-v": "第5世代",
        "generation-vi": "第6世代",
        "generation-vii": "第7世代",
        "generation-viii": "第8世代",
        "generation-ix": "第9世代",
    } # data内の世代の対応
    return mapping.get(gen_en, "世代情報なし")

def get_color(data):
    """色（color）を取得"""
    return data.get("color", {}).get("name", "色情報なし")

def get_shape(data):
    """形（shape）を取得"""
    return data.get("shape", {}).get("name", "形情報なし")

def get_habitat(data):
    """生息地（habitat）を取得"""
    if not data.get("habitat"):
        return "生息地情報なし"
    return data["habitat"]["name"]

def get_egg_groups(data):
    """タマゴグループ（egg_groups）を取得"""
    groups = [g["name"] for g in data.get("egg_groups", [])]
    return ", ".join(groups) if groups else "タマゴグループ情報なし"

def get_types(detail_data):
    """タイプ（types）を取得"""
    types = [t["type"]["name"] for t in detail_data.get("types", [])]
    return ", ".join(types) if types else "タイプ情報なし"

def get_abilities(detail_data):
    """特性（abilities）を英語で取得"""
    abilities = [a["ability"]["name"] for a in detail_data.get("abilities", [])]
    return ", ".join(abilities) if abilities else "特性情報なし"

def has_regional_form(data):
    """varietiesの中に地域フォーム（アローラ・ガラル・ヒスイ・パルデアなど）が含まれているか確認"""
    regional_keywords = ["alola", "galar", "hisui", "paldea"]
    varieties = data.get("varieties", [])
    message = None
    for v in varieties:
        name = v["pokemon"]["name"]
        if any(region in name for region in regional_keywords):
            message = "リージョンがいるよ"
            return message
    message = "リージョンがいないよ"
    return message

def has_mega_form(data):
    """varietiesの中にメガシンカフォームが含まれているか確認"""
    varieties = data.get("varieties", [])
    for v in varieties:
        name = v["pokemon"]["name"]
        if "mega" in name:
            return "メガシンカするよ"
    return "メガシンカしないよ"

def get_base_stats(detail_data):
    """種族値を取得"""
    stats = detail_data.get("stats", [])
    if not stats:
        return "種族値情報なし"
    
    # 各ステータスを辞書化＋合計算出
    stat_map = {}
    total = 0
    for s in stats:
        name = s["stat"]["name"]
        value = s["base_stat"]
        stat_map[name] = value
        total += value  # 合計種族値を加算

    # 表示をわかりやすく整形
    formatted = (
        f"HP:{stat_map.get('hp', '?')} / "
        f"攻撃:{stat_map.get('attack', '?')} / "
        f"防御:{stat_map.get('defense', '?')} / "
        f"特攻:{stat_map.get('special-attack', '?')} / "
        f"特防:{stat_map.get('special-defense', '?')} / "
        f"素早:{stat_map.get('speed', '?')}\n"
        f"合計:{total}"
    )
    return formatted



@bot.event # イベント（on_ready）を登録
async def on_ready():
    """ログイン成功メッセージを表示"""
    global session
    session = aiohttp.ClientSession()
    print(f"✅ Logged in as: {bot.user}")


@bot.event # イベント（on_disconnect）を登録
async def on_disconnect():
    global session
    if session:
        await session.close() # セッションを閉じる
        print("🔻 Session closed.")

# クイズ開始
async def start_quiz(channel, selected_generations):
    """ランダムにポケモンを出題"""

    # 既存の selected_generations を保持する
    prev_data = active_quizzes.get(channel.id, {})
    selected_gens = selected_generations or prev_data.get("selected_generations")

    if not selected_gens:
        await channel.send("😡まず `問題` で出題する世代を選んでほしいよ😡")
        return

    # 世代→ポケモンID範囲のマッピング
    gen_ranges = {
        "generation-i": range(1, 152),
        "generation-ii": range(152, 252),
        "generation-iii": range(252, 387),
        "generation-iv": range(387, 494),
        "generation-v": range(494, 650),
        "generation-vi": range(650, 722),
        "generation-vii": range(722, 810),
        "generation-viii": range(810, 906),
        "generation-ix": range(906, 1026),
    }

    # 選ばれた世代すべての範囲を結合して候補を作る
    id_pool = []
    for g in selected_generations:
        if g in gen_ranges:
            id_pool.extend(gen_ranges[g])

    if not id_pool:
        await channel.send("😡有効な世代が選択されていません😡")
        return
    
    used_ids = prev_data.get("used_ids", [])
    print(f"[DEBUG] Used IDs: {used_ids}")

    available_ids = [pid for pid in id_pool if pid not in used_ids]
    print(f"[DEBUG] Available IDs: {available_ids}")
    if not available_ids:
        await channel.send("🎉 選んだ世代の全ポケモンを出題し終えました！\nもう一度やるには「問題」と入力してね。")
        del active_quizzes[channel.id]
        return

    pokemon_id = random.choice(available_ids)
    # pokemon_id = 6 # テスト用
    used_ids.append(pokemon_id)

    species_data = await get_pokemon_species_data(pokemon_id)
    detail_data = await get_pokemon_detail_data(pokemon_id)

    if not species_data or not detail_data:
        await channel.send("データの取得に失敗しました。")
        return

    # 各種データ抽出
    name_en = get_name_in_language(species_data, "en")
    name_jp = get_name_in_language(species_data, "ja-Hrkt")
    name_first_hint = name_jp[0]
    flavor_en = get_english_flavor_text(species_data)
    generation_jp = get_generation_japanese(species_data)
    color = get_color(species_data)
    shape = get_shape(species_data)
    habitat = get_habitat(species_data)
    egg_group = get_egg_groups(species_data)
    types = get_types(detail_data)
    abilities = get_abilities(detail_data)
    regional_exists = has_regional_form(species_data)
    mega_exists = has_mega_form(species_data)
    base_stats = get_base_stats(detail_data)

    print("--------------------------------------------------------------")
    print(f"[DEBUG] 図鑑番号: {pokemon_id}")
    print(f"[DEBUG] 出題ポケモン: {name_jp} ({name_en})")
    print("--------------------------------------------------------------")

    # 出題中のポケモン情報を保存
    active_quizzes[channel.id] = {
        "selected_generations": selected_gens,
        "used_ids": used_ids,
        "answer": name_jp,
        "hint": flavor_en,
        "generation": generation_jp,
        "color": color,
        "shape": shape,
        "habitat": habitat,
        "egg": egg_group,
        "types": types,
        "abilities": abilities,
        "regional_exists": regional_exists,
        "mega_exists": mega_exists,
        "stats": base_stats,
        "first_char": name_first_hint
    }

    # 出題時の表示
    await channel.send(
        f"👉**{name_en}**\n"
        f"図鑑説明：`{flavor_en}`\n"
        f"ヒントのコマンド: `世代` `色` `形` `生息地` `タマゴグループ` `タイプ` `特性` `リージョン` `メガ` `種族値` `最初の文字`\n"
        f"ギブアップ:`降参`\n"
        f"回答例: `aフシギダネ`"
    )


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()
    # print(f"[DEBUG] Message received: {content}")

    # カスタム反応
    if content == "さすたけ":
        await message.channel.send("こんさす")
        return
    if content == "こんさす":
        await message.channel.send("さすたか")
        return
    if content == "さすたか":
        await message.channel.send("こんさす")
        return
    if "高身長" in content:
        await message.channel.send("メンタルケア")
        return
    
    if content == "問題":
        # チャンネルごとの状態を「選択中」にする
        active_quizzes[message.channel.id] = {"state": "selecting_generation"}

        view = GenerationSelect() # 世代選択ビュー
        await message.channel.send("世代を選んでほしいよ", view=view)
        
        # 非同期で世代選択を待機
        async def wait_for_selection():
            await view.wait()
            # 世代が選ばれた場合
            if view.selected_generations:
                selected_gens = view.selected_generations
                readable = [opt.label for opt in view.select.options if opt.value in selected_gens]
                await message.channel.send(
                    f"出題世代を `{', '.join(readable)}` に設定したよ\n"
                    f"次は「出題」と打ってほしいよ"
                )
                active_quizzes[message.channel.id] = {
                    "selected_generations": selected_gens,
                    "state": "ready"
                }
            else:
                # 未選択のままタイムアウト
                if active_quizzes.get(message.channel.id, {}).get("state") == "selecting_generation":
                    del active_quizzes[message.channel.id]
                    await message.channel.send("世代選択がタイムアウトしました。もう一度「問題」と入力してね。")

        asyncio.create_task(wait_for_selection())
        return

    # クイズ開始
    if content == "出題":
        quiz_info = active_quizzes.get(message.channel.id)
        # 世代がまだ確定していない
        if not quiz_info or "selected_generations" not in quiz_info:
            await message.channel.send("😡まず `問題` で出題する世代を選んでほしいよ😡")
            return

        selected_gens = quiz_info["selected_generations"]
        await start_quiz(message.channel, selected_gens)
        return

    # クイズ進行
    if message.channel.id in active_quizzes:
        quiz_data = active_quizzes[message.channel.id]
        # クイズ中でない場合はスキップ
        if "answer" not in quiz_data:
            return

        hints = {
            "世代": quiz_data["generation"],
            "色": quiz_data['color'],
            "形": quiz_data['shape'],
            "生息地": quiz_data['habitat'],
            "タマゴグループ": quiz_data['egg'],
            "タイプ": quiz_data['types'],
            "特性": quiz_data['abilities'],
            "リージョン" :quiz_data['regional_exists'],
            "メガ": quiz_data['mega_exists'],
            "種族値": quiz_data["stats"],
            "最初の文字": quiz_data["first_char"]
            }

        if content in hints:
            await message.channel.send(hints[content])
            return

        if content == "降参":
            await message.channel.send(
                f"🤗**{quiz_data['answer']}**🤗\n"
                f"そのままの世代で続ける場合は「出題」\n"
                f"世代を変更する場合は「問題」"
                )
            return

        if content.lower().startswith("a"):
            answer = content[1:].strip()

            # ひらがな → カタカナ変換関数
            def hira_to_kata(text):
                return text.translate(str.maketrans(
                    {chr(h): chr(h + 96) for h in range(0x3041, 0x3097)} #Unicode範囲の変換
                ))
            # カタカナに統一して比較
            user_answer_kata = hira_to_kata(answer)
            correct_answer_kata = hira_to_kata(quiz_data["answer"])

            if user_answer_kata == correct_answer_kata:
                await message.channel.send(
                    "🎉 正解！\n"
                    f"そのままの世代で続ける場合は「出題」\n"
                    f"世代を変更する場合は「問題」"
                    )
            else:
                await message.channel.send("😙ぶっぶー😙")
            return

bot.run(TOKEN)