# -*- coding: utf-8 -*-
"""頻度リスト+辞書から words.js(各言語 最大10,000語)を生成する

意味の優先順位:
  1. MUSE 英日対訳の簡潔な訳語(最大3語を「、」区切り)
  2. EJDict の語義(注釈括弧・活用形メモを除去した最初の有効な語義)
欧州4言語は「各言語→英語→日本語」で解決し、英語候補は英語の使用頻度順に選ぶ。
"""
import json, re, os

DATA = os.environ.get("VOCAB_DATA", os.path.join(os.path.dirname(__file__), "data"))
TARGET = 10000
GLOSS_MAX = 90  # 意味の最大文字数(読点区切りで自然に収める)

def has_japanese(s):
    return any(("぀" <= c <= "ヿ") or ("一" <= c <= "鿿") for c in s)

INFLECTION_NOTE = re.compile(r"の(過去|現在|三人称|複数形?|単数形?|短縮形|比較級|最上級|化学記号|元素記号|記号)")
LEADING_PAREN = re.compile(r"^(?:[((][^))]*[))],?)+")

def shorten(s):
    if len(s) <= GLOSS_MAX:
        return s
    # 読点・セミコロン区切りで自然な長さまで採用する
    parts = re.split(r"(?<=[,、;・])", s)
    acc = ""
    for p in parts:
        if acc and len(acc) + len(p) > GLOSS_MAX:
            break
        acc += p
    return acc.strip(" ,、;・") if acc else s[:GLOSS_MAX] + "…"

def clean_gloss(m):
    """EJDictの意味欄から最初の「意味の通る」語義を抽出"""
    m = m.strip()
    if m.startswith("="):  # 参照エントリ
        return None
    for sense in re.split(r" / |/", m):
        s = sense.replace("『", "").replace("』", "").replace("《", "(").replace("》", ")")
        s = re.sub(r"\s+", " ", s).strip(" ;,・")
        if not s or not has_japanese(s):
            continue
        if INFLECTION_NOTE.search(s):  # 「burnの過去分詞」等の活用形メモは語義でない
            continue
        core = LEADING_PAREN.sub("", s).strip(" ,;")
        if core and has_japanese(core):
            s = core  # 「(通貨単位)ドル」→「ドル」のように先頭注釈を除去
        return shorten(s)
    return None

# ---- 英日辞書(EJDict, パブリックドメイン)----
# 小文字見出し(通常の単語)を優先する。「Be(化学記号)」等の大文字見出しで
# 「be」の意味を潰さないようにするため。
ej = {}
ej_is_lower = {}
with open(os.path.join(DATA, "ejdict.txt"), encoding="utf-8") as f:
    for line in f:
        if "\t" not in line:
            continue
        w, m = line.rstrip("\n").split("\t", 1)
        w = w.strip()
        g = clean_gloss(m)
        if not g:
            continue
        key = w.lower()
        is_lower = (w == key)
        if key not in ej or (is_lower and not ej_is_lower[key]):
            ej[key] = g
            ej_is_lower[key] = is_lower
print(f"EJDict entries usable: {len(ej)}")

# ---- MUSE 英日対訳(簡潔な訳語)----
muse_ja = {}
with open(os.path.join(DATA, "muse_en-ja.txt"), encoding="utf-8") as f:
    for line in f:
        parts = line.split()
        if len(parts) != 2:
            continue
        en, ja = parts
        if not has_japanese(ja):  # 「was was」のような未翻訳ペアを除外
            continue
        lst = muse_ja.setdefault(en.lower(), [])
        if ja not in lst and len(lst) < 3:
            lst.append(ja)
print(f"MUSE en-ja entries: {len(muse_ja)}")

KATAKANA_ONLY = re.compile(r"^[ァ-ヶーヴ・\s]+$")

def gloss_for_en(en):
    """英単語に対する日本語訳: MUSEの具体的な訳語を優先し、EJDictで補完。
    MUSEの訳がカタカナ音訳のみ(例: sort→ソート)なら辞書語義を優先する。"""
    en = en.lower()
    vals = muse_ja.get(en)
    if vals:
        meaningful = [v for v in vals if not KATAKANA_ONLY.match(v)]
        if meaningful:
            return "、".join(meaningful)
        return ej.get(en) or "、".join(vals)
    return ej.get(en)

# ---- 頻度リスト読み込み ----
def freq_words(lang):
    words = []
    with open(os.path.join(DATA, f"{lang}_50k.txt"), encoding="utf-8") as f:
        for line in f:
            w = line.split(" ")[0].strip()
            words.append(w)
    return words

WORD_RE = re.compile(r"^[a-zàâäáãåçèéêëìíîïñòóôöõùúûüßœæ'\-]+$", re.IGNORECASE)

def valid_word(w):
    if len(w) < 2 or len(w) > 24:
        return False
    if not WORD_RE.match(w):
        return False
    if w.startswith("-") or w.endswith("-") or w.startswith("'"):
        return False
    return True

# 英語の頻度順位(欧州語→英語の訳語候補の並べ替えに使う)
en_freq = freq_words("en")
en_rank = {w: i for i, w in enumerate(en_freq)}

result = {}

# ---- 英語: 頻度リスト → MUSE/EJDict ----
lst, seen = [], set()
for w in en_freq:
    if len(lst) >= TARGET:
        break
    if not valid_word(w) or w in seen:
        continue
    g = gloss_for_en(w)
    if g:
        lst.append([w, g])
        seen.add(w)
result["en"] = {"name": "英語", "list": lst}
print(f"en: {len(lst)}")

# ---- 欧州4言語: 頻度リスト → MUSE(→英語・頻度順) → 日本語 ----
for lang, name in [("es", "スペイン語"), ("fr", "フランス語"), ("de", "ドイツ語"), ("it", "イタリア語")]:
    muse = {}
    with open(os.path.join(DATA, f"muse_{lang}-en.txt"), encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) != 2:
                continue
            src, en = parts
            lst_c = muse.setdefault(src, [])
            if en not in lst_c and len(lst_c) < 5:
                lst_c.append(en)
    lst, seen = [], set()
    for w in freq_words(lang):
        if len(lst) >= TARGET:
            break
        if not valid_word(w) or w in seen:
            continue
        # 英語候補を頻度順に並べ、まず同綴りでない候補から解決を試みる
        cands = sorted(muse.get(w, []), key=lambda c: en_rank.get(c, 10**9))
        gloss = None
        for skip_same in (True, False):
            for en in cands:
                if skip_same and en == w:  # 同綴りの借用語は誤対応が多いので後回し
                    continue
                g = gloss_for_en(en)
                if g:
                    gloss = g
                    break
            if gloss:
                break
        if gloss:
            lst.append([w, gloss])
            seen.add(w)
    result[lang] = {"name": name, "list": lst}
    print(f"{lang}: {len(lst)}")

# ---- words.js 出力 ----
out = "// 自動生成ファイル: build_words.py により作成(頻度順)\nconst WORDS = "
out += json.dumps(result, ensure_ascii=False, separators=(",", ":"))
out += ";\n"
dst = os.path.join(os.path.dirname(__file__), "words.js")
with open(dst, "w", encoding="utf-8") as f:
    f.write(out)
print("words.js written:", os.path.getsize(dst), "bytes")
