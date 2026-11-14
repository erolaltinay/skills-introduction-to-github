#!/usr/bin/env python3
"""
YouTube Niş Radarı
==================
Son N günde açılmış, en az K videosu X+ izlenme almış yeni YouTube kanallarını
bulur; başlık / etiket / açıklamalardan anahtar kelimeleri çıkarır; bunları
hedef dillere (varsayılan: Almanca, İspanyolca) çevirip YouTube'da aratır ve
"bu niş o dilde hâlâ açık mı?" sorusuna cevap veren bir HTML rapor üretir.

Yalnızca resmi YouTube Data API v3'ü kullanır (ücretsiz, günde 10.000 birim).
Ek paket gerekmez: sadece Python 3.8+.

Örnekler:
  python radar.py                          # genel tarama (son 45 gün)
  python radar.py --konu "shark"           # belirli bir konuda tara
  python radar.py --kanal @TheDeepRecord-q5t   # tek bir kanalı analiz et
  python radar.py --gun 30 --min-izlenme 20000 --diller de,es,fr
"""
import argparse
import collections
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

API = "https://www.googleapis.com/youtube/v3/"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")

# Kotası maliyetleri (YouTube Data API v3)
COST = {"search": 100, "channels": 1, "videos": 1, "playlistItems": 1}

DEFAULT_SEEDS = [
    "documentary", "true story", "what happened", "explained", "history",
    "mystery", "the truth about", "they found", "why", "story",
]

LANG_NAMES = {"en": "İngilizce", "de": "Almanca", "es": "İspanyolca", "fr": "Fransızca",
              "pt": "Portekizce", "it": "İtalyanca", "tr": "Türkçe", "nl": "Felemenkçe",
              "pl": "Lehçe"}
LANG_REGION = {"en": "US", "de": "DE", "es": "MX", "fr": "FR", "pt": "BR", "it": "IT",
               "tr": "TR", "nl": "NL", "pl": "PL"}

STOP = set("""
a an the and or but of to in on at for from by with without about into over under after before
is are was were be been being am do does did done have has had having it its this that these
those there here they them their he she his her him we our you your i me my mine what which who
whom whose why how when where than then so such too very can could would should will just not no
nor only own same all any both each few more most other some again further once up down out off
off vs ft feat new full part episode ep official video videos 2024 2025 2026 2027 one two three
four five six seven eight nine ten after never ever every still even like get got gets one's
s t don didn doesn isn wasn weren won wouldn couldn shouldn ll re ve d m
year years day days week weeks month months minute minutes hour hours foot feet meter meters
first last next back time times thing things something someone nobody everyone everything nothing
really actually finally just saw see seen watched
""".split())


# ----------------------------------------------------------------------------- yardımcılar

def load_env():
    """.env dosyasındaki ANAHTAR=değer satırlarını ortam değişkenlerine yükler."""
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def iso_duration(s):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def fmt_len(sec):
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_n(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def rfc3339(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


class QuotaExceeded(Exception):
    pass


# ----------------------------------------------------------------------------- API istemcisi

class YouTube:
    def __init__(self, key, budget, cache_hours=20, verbose=True):
        self.key = key
        self.budget = budget
        self.used = 0
        self.cache_hours = cache_hours
        self.verbose = verbose
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _cache_path(self, endpoint, params):
        raw = endpoint + json.dumps(params, sort_keys=True)
        return os.path.join(CACHE_DIR, hashlib.sha1(raw.encode()).hexdigest() + ".json")

    def call(self, endpoint, **params):
        params = {k: v for k, v in params.items() if v is not None}
        cp = self._cache_path(endpoint, params)
        if os.path.exists(cp) and time.time() - os.path.getmtime(cp) < self.cache_hours * 3600:
            with open(cp, encoding="utf-8") as f:
                return json.load(f)
        cost = COST.get(endpoint, 1)
        if self.used + cost > self.budget:
            raise QuotaExceeded(f"Bu çalıştırma için ayrılan kota ({self.budget}) doldu.")
        url = API + endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"X-Goog-Api-Key": self.key,
                                                   "Accept": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                if e.code == 403 and "quota" in body.lower():
                    raise QuotaExceeded("Günlük YouTube API kotası doldu (Pasifik saatiyle gece yarısı sıfırlanır).")
                if e.code in (400, 401, 403):
                    raise SystemExit(f"\nAPI hatası {e.code}: {body[:400]}\n"
                                     "API anahtarını ve 'YouTube Data API v3'ün etkin olduğunu kontrol et.")
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
            except urllib.error.URLError:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        self.used += cost
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data

    # --- toplu yardımcılar
    def channels(self, ids):
        out = {}
        ids = list(dict.fromkeys(ids))
        for i in range(0, len(ids), 50):
            d = self.call("channels", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]),
                          maxResults=50)
            for c in d.get("items", []):
                out[c["id"]] = c
        return out

    def videos(self, ids, hl=None):
        out = {}
        ids = list(dict.fromkeys(ids))
        for i in range(0, len(ids), 50):
            d = self.call("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]),
                          maxResults=50, hl=hl)
            for v in d.get("items", []):
                out[v["id"]] = v
        return out

    def uploads(self, playlist_id, limit=100):
        ids, token = [], None
        while len(ids) < limit:
            d = self.call("playlistItems", part="contentDetails", playlistId=playlist_id,
                          maxResults=50, pageToken=token)
            ids += [it["contentDetails"]["videoId"] for it in d.get("items", [])]
            token = d.get("nextPageToken")
            if not token:
                break
        return ids[:limit]

    def search(self, q, **kw):
        d = self.call("search", part="snippet", type="video", q=q, maxResults=50, **kw)
        return d.get("items", [])

    def resolve_channel(self, ref):
        ref = ref.strip()
        m = re.search(r"(UC[\w-]{22})", ref)
        if m:
            return m.group(1)
        handle = ref.split("/")[-1]
        if not handle.startswith("@"):
            handle = "@" + handle
        d = self.call("channels", part="id", forHandle=handle)
        items = d.get("items", [])
        if not items:
            raise SystemExit(f"Kanal bulunamadı: {ref}")
        return items[0]["id"]


# ----------------------------------------------------------------------------- çeviri

class Translator:
    """Öncelik: ceviriler.json (elle) → DeepL (DEEPL_API_KEY) → Google Cloud Translation (GOOGLE_TRANSLATE=1)."""

    def __init__(self, yt_key):
        self.path = os.path.join(HERE, "ceviriler.json")
        self.manual = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.manual = json.load(f)
        self.deepl = os.environ.get("DEEPL_API_KEY")
        self.google = os.environ.get("GOOGLE_TRANSLATE") == "1"
        self.yt_key = yt_key
        self.missing = []
        self.source_used = collections.Counter()

    def translate(self, text, src, tgt):
        k = f"{src}>{tgt}"
        hit = self.manual.get(k, {}).get(text)
        if hit:
            self.source_used["elle"] += 1
            return hit
        res = None
        try:
            if self.deepl:
                res = self._deepl(text, src, tgt)
                self.source_used["DeepL"] += 1
            elif self.google:
                res = self._google(text, src, tgt)
                self.source_used["Google"] += 1
        except Exception as e:  # çeviri hatası taramayı durdurmasın
            print(f"  ! çeviri hatası ({text} → {tgt}): {e}")
        if res:
            self.manual.setdefault(k, {})[text] = res
            return res
        self.missing.append((k, text))
        self.manual.setdefault(k, {}).setdefault(text, "")
        return None

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.manual, f, ensure_ascii=False, indent=1)

    def _deepl(self, text, src, tgt):
        host = "api-free.deepl.com" if self.deepl.endswith(":fx") else "api.deepl.com"
        data = urllib.parse.urlencode({"text": text, "source_lang": src.upper(),
                                       "target_lang": tgt.upper()}).encode()
        req = urllib.request.Request(f"https://{host}/v2/translate", data=data,
                                     headers={"Authorization": f"DeepL-Auth-Key {self.deepl}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)["translations"][0]["text"]

    def _google(self, text, src, tgt):
        data = urllib.parse.urlencode({"q": text, "source": src, "target": tgt, "format": "text"}).encode()
        req = urllib.request.Request("https://translation.googleapis.com/language/translate/v2", data=data,
                                     headers={"X-Goog-Api-Key": self.yt_key})
        with urllib.request.urlopen(req, timeout=20) as r:
            return html.unescape(json.load(r)["data"]["translations"][0]["translatedText"])


# ----------------------------------------------------------------------------- analiz

def words(text):
    return re.findall(r"[a-zA-Z][a-zA-Z'\-]+", text.lower())


def extract_keywords(vids, top=15):
    """Başlık n-gramları + etiketler + açıklama hashtag'leri → ağırlıklı anahtar kelimeler."""
    score = collections.Counter()
    tags = collections.Counter()
    title_df = collections.Counter()   # ifadenin geçtiği başlık sayısı
    min_df = 2 if len(vids) >= 3 else 1
    for v in vids:
        sn = v["snippet"]
        title_words = [w.strip("'-") for w in words(sn["title"])]
        seen = set()
        for n in (1, 2, 3):
            for i in range(len(title_words) - n + 1):
                g = title_words[i:i + n]
                if g[0] in STOP or g[-1] in STOP or any(len(w) < 3 for w in g if w not in STOP):
                    continue
                if re.fullmatch(r"[\d\-]+", " ".join(g)):
                    continue
                seen.add(" ".join(g))
        for g in seen:  # her başlıkta bir kez say
            title_df[g] += 1
        for t in sn.get("tags", []) or []:
            t = t.lower().strip()
            if t:
                tags[t] += 1
                score[t] += 2.0
        for h in re.findall(r"#(\w+)", sn.get("description", "")):
            score[h.lower()] += 1.0
    for g, df in title_df.items():
        if df >= min_df:  # tek bir başlıkta geçen ifade niş anlatmaz
            score[g] += df * (1.0 + 0.5 * g.count(" "))
    # tek kelimelik ifadeyi, onu içeren daha uzun ifade kadar sık geçiyorsa ele
    ranked = [k for k, _ in score.most_common(200)]
    final = []
    for k in ranked:
        if score[k] < 2:
            continue
        if any(k != o and k in o and score[o] >= score[k] * 0.8 for o in ranked[:60]):
            continue
        final.append(k)
        if len(final) >= top:
            break
    return final, tags.most_common(25), score


def analyze_channel(yt, ch, args, hl=None):
    sn, st = ch["snippet"], ch["statistics"]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    vids_ids = yt.uploads(up, limit=args.max_video)
    vids = list(yt.videos(vids_ids).values())
    now = now_utc()
    rows = []
    for v in vids:
        secs = iso_duration(v["contentDetails"].get("duration"))
        pub = parse_time(v["snippet"]["publishedAt"])
        age_days = max((now - pub).total_seconds() / 86400, 0.25)
        views = int(v["statistics"].get("viewCount", 0))
        rows.append(dict(id=v["id"], title=v["snippet"]["title"], views=views, secs=secs,
                         pub=pub, age=age_days, vpd=views / age_days,
                         tags=v["snippet"].get("tags", []) or [],
                         lang=(v["snippet"].get("defaultAudioLanguage") or v["snippet"].get("defaultLanguage") or "")))
    rows.sort(key=lambda r: r["pub"])
    longs = [r for r in rows if r["secs"] >= args.min_sure]
    hits = [r for r in longs if r["views"] >= args.min_izlenme]
    # yükseliş: yeni yarının günlük izlenmesi / eski yarının
    trend = None
    if len(longs) >= 4:
        half = len(longs) // 2
        old = sum(r["vpd"] for r in longs[:half]) / half
        new = sum(r["vpd"] for r in longs[half:]) / (len(longs) - half)
        trend = new / old if old else None
    kws, tags, _ = extract_keywords([v for v in vids if iso_duration(v["contentDetails"].get("duration")) >= args.min_sure] or vids)
    created = parse_time(sn["publishedAt"])
    langs = collections.Counter(r["lang"].split("-")[0] for r in rows if r["lang"])
    return dict(
        id=ch["id"], title=sn["title"], handle=sn.get("customUrl", ""), desc=sn.get("description", ""),
        created=created, age_days=(now - created).days, country=sn.get("country", ""),
        subs=int(st.get("subscriberCount", 0) or 0), total_views=int(st.get("viewCount", 0) or 0),
        video_count=int(st.get("videoCount", 0) or 0), videos=rows, longs=longs, hits=hits, trend=trend,
        keywords=kws, tags=tags, lang=(langs.most_common(1)[0][0] if langs else sn.get("defaultLanguage", "") or ""),
    )


def discover(yt, args):
    cutoff = now_utc() - dt.timedelta(days=args.gun)
    seeds = [s.strip() for s in args.konu.split(",")] if args.konu else DEFAULT_SEEDS[:args.tohum]
    region = LANG_REGION.get(args.kaynak_dil, "US")
    print(f"\n[1/4] Keşif: {len(seeds)} arama × {len(args.sureler)} süre filtresi "
          f"(son {args.gun} gün, dil={args.kaynak_dil})")
    channel_ids = collections.Counter()
    for s in seeds:
        for dur in args.sureler:
            try:
                items = yt.search(s, order="viewCount", publishedAfter=rfc3339(cutoff),
                                  relevanceLanguage=args.kaynak_dil, regionCode=region, videoDuration=dur)
            except QuotaExceeded as e:
                print("  ! " + str(e))
                return channel_ids
            for it in items:
                channel_ids[it["snippet"]["channelId"]] += 1
            print(f"  '{s}' ({dur}): {len(items)} video")
    print(f"  → {len(channel_ids)} farklı kanal")
    return channel_ids


def gap_check(yt, tr, phrase, src, tgt, args):
    """Bir ifadeyi hedef dilde arar: son 30 gündeki rekabet + tüm zamanların talebi."""
    q = phrase if tgt == src else tr.translate(phrase, src, tgt)
    if not q:
        return None
    region = LANG_REGION.get(tgt, "US")
    since = rfc3339(now_utc() - dt.timedelta(days=30))
    recent = yt.search(q, relevanceLanguage=tgt, regionCode=region, publishedAfter=since, order="relevance")
    alltime = yt.search(q, relevanceLanguage=tgt, regionCode=region, order="viewCount") if args.talep else []
    ids = [it["id"]["videoId"] for it in recent + alltime]
    meta = yt.videos(ids)
    def row(it):
        v = meta.get(it["id"]["videoId"])
        if not v:
            return None
        sn = v["snippet"]
        audio = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").split("-")[0]
        return dict(id=v["id"], title=sn["title"], channel=sn["channelTitle"], channel_id=sn["channelId"],
                    views=int(v["statistics"].get("viewCount", 0)), secs=iso_duration(v["contentDetails"]["duration"]),
                    pub=sn["publishedAt"][:10], audio=audio, native=(audio == tgt) if audio else None)
    rec = [r for r in map(row, recent) if r and r["secs"] >= args.min_sure]
    allt = [r for r in map(row, alltime) if r]
    native = [r for r in rec if r["native"] is not False]   # bilinmeyen = yerli say (temkinli)
    foreign = [r for r in rec if r["native"] is False]
    traction = {r["channel_id"] for r in native if r["views"] >= args.min_izlenme}
    posting = {r["channel_id"] for r in native}
    demand = max([r["views"] for r in allt + rec], default=0)
    recent_max = max([r["views"] for r in rec], default=0)
    n = len(traction)
    if demand < 20_000 and recent_max < 10_000:
        verdict = ("TALEP ZAYIF", "weak")
    elif n == 0:
        verdict = ("BÜYÜK AÇIK", "open2")
    elif n <= 2:
        verdict = ("AÇIK", "open")
    elif n <= 5:
        verdict = ("GİRİLMİŞ / DARALIYOR", "mid")
    else:
        verdict = ("KALABALIK", "closed")
    return dict(phrase=phrase, query=q, lang=tgt, recent=rec, alltime=allt[:5], posting=len(posting),
                traction=n, foreign=len({r["channel_id"] for r in foreign}), demand=demand,
                recent_max=recent_max, verdict=verdict)


# ----------------------------------------------------------------------------- rapor

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mut:#6b6b66;--line:#e4e3df;--acc:#2f5bea;
--g:#1f8a4c;--g2:#0f6b39;--y:#b7791f;--r:#c0392b;--gr:#888}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--ink:#ecebe7;--mut:#a3a29d;
--line:#333;--acc:#7a9bff;--g:#4cc283;--g2:#7be0a8;--y:#e2b04a;--r:#ff7b6b;--gr:#999}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:24px 16px}
main{max-width:1100px;margin:0 auto}h1{font-size:26px;margin:0 0 4px}h2{font-size:20px;margin:0}
h3{font-size:15px;margin:18px 0 6px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.mut{color:var(--mut)}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:18px;margin:18px 0}.stats{display:flex;flex-wrap:wrap;gap:8px 22px;margin:8px 0}
.stats b{font-size:18px;display:block}table{width:100%;border-collapse:collapse;font-size:14px}
td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600}.num{text-align:right;white-space:nowrap}
.chip{display:inline-block;padding:2px 9px;border-radius:999px;border:1px solid var(--line);
margin:2px;font-size:13px}.v{font-weight:700;white-space:nowrap}.open2{color:var(--g2)}
.open{color:var(--g)}.mid{color:var(--y)}.closed{color:var(--r)}.weak{color:var(--gr)}
a{color:var(--acc);text-decoration:none}.scroll{overflow-x:auto}.scroll td:first-child{min-width:220px}details summary{cursor:pointer;color:var(--acc)}
"""


def render(report, path):
    e = html.escape
    out = [f"<!doctype html><html lang='tr'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>Niş Radarı</title>"
           f"<style>{CSS}</style></head><body><main>"]
    p = report["params"]
    out.append(f"<h1>Niş Radarı</h1><div class='mut'>{e(report['date'])} · son {p['gun']} gün · "
               f"min {p['min_videos']} video ≥ {fmt_n(p['min_izlenme'])} izlenme · hedef diller: "
               f"{e(', '.join(LANG_NAMES.get(l, l) for l in p['diller']))} · kullanılan kota: {report['quota']}</div>")
    if report.get("notes"):
        out.append("<div class='card'>" + "<br>".join(e(n) for n in report["notes"]) + "</div>")
    if not report["channels"]:
        out.append("<div class='card'>Kriterlere uyan kanal bulunamadı. <span class='mut'>--konu ile bir niş "
                   "vermeyi, --gun değerini artırmayı veya --min-izlenme değerini düşürmeyi dene.</span></div>")
    for c in report["channels"]:
        url = f"https://www.youtube.com/channel/{c['id']}"
        trend = (f"{c['trend']:.1f}×" if c["trend"] else "—")
        out.append(f"<div class='card'><h2><a href='{url}' target='_blank'>{e(c['title'])}</a> "
                   f"<span class='mut'>{e(c['handle'])}</span></h2>")
        out.append("<div class='stats'>"
                   f"<div><b>{c['created'][:10]}</b><span class='mut'>açılış ({c['age_days']} gün)</span></div>"
                   f"<div><b>{fmt_n(c['subs'])}</b><span class='mut'>abone</span></div>"
                   f"<div><b>{fmt_n(c['total_views'])}</b><span class='mut'>toplam izlenme</span></div>"
                   f"<div><b>{len(c['hits'])}/{len(c['longs'])}</b><span class='mut'>video ≥ {fmt_n(p['min_izlenme'])}</span></div>"
                   f"<div><b>{trend}</b><span class='mut'>yükseliş (yeni/eski günlük izlenme)</span></div>"
                   f"<div><b>{e(LANG_NAMES.get(c['lang'], c['lang'] or '?'))}</b><span class='mut'>dil</span></div></div>")
        if c["desc"]:
            out.append(f"<p class='mut'>{e(c['desc'][:400])}</p>")
        out.append("<h3>Videolar</h3><div class='scroll'><table><tr><th>Başlık</th><th class='num'>İzlenme</th>"
                   "<th class='num'>Günlük</th><th class='num'>Süre</th><th class='num'>Tarih</th></tr>")
        for v in sorted(c["videos"], key=lambda r: -r["views"])[:15]:
            out.append(f"<tr><td><a href='https://youtu.be/{v['id']}' target='_blank'>{e(v['title'])}</a></td>"
                       f"<td class='num'>{fmt_n(v['views'])}</td><td class='num'>{fmt_n(v['vpd'])}</td>"
                       f"<td class='num'>{fmt_len(v['secs'])}</td><td class='num'>{v['pub'][:10]}</td></tr>")
        out.append("</table></div>")
        out.append("<h3>Anahtar kelimeler (başlık + etiket + açıklama)</h3>" +
                   "".join(f"<span class='chip'>{e(k)}</span>" for k in c["keywords"]))
        if c["tags"]:
            out.append("<h3>Etiketler (tags)</h3>" + "".join(
                f"<span class='chip'>{e(t)} <span class='mut'>×{n}</span></span>" for t, n in c["tags"]))
        else:
            out.append("<h3>Etiketler (tags)</h3><span class='mut'>Kanal videolarına etiket girmemiş.</span>")
        if c.get("gaps"):
            out.append("<h3>Dil açığı analizi</h3><div class='scroll'><table><tr><th>İfade</th><th>Dil</th>"
                       "<th>Aranan</th><th class='num'>Yerli kanal (30g)</th><th class='num'>10K+ alan yerli</th>"
                       "<th class='num'>Çeviri/dublaj rakip</th><th class='num'>Talep (en yüksek)</th><th>Sonuç</th></tr>")
            for g in c["gaps"]:
                if g is None:
                    continue
                out.append(f"<tr><td>{e(g['phrase'])}</td><td>{e(g['lang'].upper())}</td><td>{e(g['query'])}</td>"
                           f"<td class='num'>{g['posting']}</td><td class='num'>{g['traction']}</td>"
                           f"<td class='num'>{g['foreign']}</td><td class='num'>{fmt_n(g['demand'])}</td>"
                           f"<td class='v {g['verdict'][1]}'>{g['verdict'][0]}</td></tr>")
            out.append("</table></div>")
            for g in c["gaps"]:
                if not g or g["lang"] == p["kaynak_dil"]:
                    continue
                out.append(f"<details><summary>{e(g['lang'].upper())} · “{e(g['query'])}” — son 30 günün en çok "
                           f"izlenenleri</summary><table>")
                for r in sorted(g["recent"], key=lambda r: -r["views"])[:8]:
                    tag = "yerli" if r["native"] else ("çeviri/yabancı" if r["native"] is False else "?")
                    out.append(f"<tr><td><a href='https://youtu.be/{r['id']}' target='_blank'>{e(r['title'])}</a>"
                               f"<br><span class='mut'>{e(r['channel'])} · {tag} · {r['pub']}</span></td>"
                               f"<td class='num'>{fmt_n(r['views'])}</td><td class='num'>{fmt_len(r['secs'])}</td></tr>")
                out.append("</table></details>")
        out.append("</div>")
    out.append("<p class='mut'>Okuma kılavuzu: <b class='open2'>BÜYÜK AÇIK</b> = talep var, o dilde 10K+ alan yerli "
               "kanal yok · <b class='open'>AÇIK</b> = 1-2 yerli kanal tutuyor, yer var · <b class='mid'>GİRİLMİŞ</b> "
               "= 3-5 yerli kanal · <b class='closed'>KALABALIK</b> = 6+ · <b class='weak'>TALEP ZAYIF</b> = "
               "kimse izlemiyor. “Çeviri/dublaj rakip”: sesi başka dilde olup başlığı çevrilmiş videolar.</p>")
    out.append("</main></body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(out))


# ----------------------------------------------------------------------------- ana akış

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    load_env()
    ap = argparse.ArgumentParser(description="YouTube Niş Radarı (ücretsiz YouTube Data API v3)")
    ap.add_argument("--konu", help="virgülle ayrılmış arama kelimeleri, örn. 'shark,ocean mystery'")
    ap.add_argument("--kanal", action="append", help="keşfi atla, bu kanal(lar)ı analiz et (@handle, URL veya UC... ID)")
    ap.add_argument("--gun", type=int, default=45, help="kanal en fazla kaç günlük olsun (varsayılan 45)")
    ap.add_argument("--min-izlenme", type=int, default=10000, help="'başarılı video' eşiği (varsayılan 10000)")
    ap.add_argument("--min-video", type=int, default=3, help="eşiği geçen en az video sayısı (varsayılan 3)")
    ap.add_argument("--min-sure", type=int, default=180, help="Shorts'u elemek için en kısa süre, saniye (180)")
    ap.add_argument("--max-abone", type=int, default=500000)
    ap.add_argument("--kaynak-dil", default="en", help="taranan kanalların dili (varsayılan en)")
    ap.add_argument("--diller", default="de,es", help="açık aranacak diller (varsayılan de,es)")
    ap.add_argument("--kelime", type=int, default=4, help="her kanal için kaç anahtar ifade aratılsın (4)")
    ap.add_argument("--kanal-sayisi", type=int, default=3, help="dil analizine girecek en iyi kanal sayısı (3)")
    ap.add_argument("--tohum", type=int, default=6, help="genel taramada kaç varsayılan arama kullanılsın (6)")
    ap.add_argument("--sureler", default="medium,long", help="YouTube süre filtreleri: medium (4-20dk), long (20dk+)")
    ap.add_argument("--max-video", type=int, default=60, help="kanal başına incelenecek en fazla video")
    ap.add_argument("--kota", type=int, default=9000, help="bu çalıştırmada harcanacak en fazla birim (günlük 10000)")
    ap.add_argument("--talep", action=argparse.BooleanOptionalAction, default=True,
                    help="tüm zamanların talebini de ölç (ifade başına +100 birim)")
    ap.add_argument("--acma", action="store_true", help="raporu tarayıcıda otomatik açma")
    args = ap.parse_args()
    args.sureler = [s.strip() for s in args.sureler.split(",") if s.strip()]
    targets = [l.strip() for l in args.diller.split(",") if l.strip() and l.strip() != args.kaynak_dil]

    key = os.environ.get("YT_API_KEY")
    if not key:
        raise SystemExit("YT_API_KEY bulunamadı. Bu klasöre .env dosyası oluşturup içine\n"
                         "YT_API_KEY=senin_anahtarin\nyaz (bkz. README.md).")
    yt = YouTube(key, args.kota)
    tr = Translator(key)
    notes = []
    cutoff = now_utc() - dt.timedelta(days=args.gun)

    # 1) aday kanallar
    if args.kanal:
        cand_ids = [yt.resolve_channel(k) for k in args.kanal]
    else:
        cand_ids = list(discover(yt, args).keys())

    # 2) kanal filtresi (açılış tarihi, abone)
    print(f"\n[2/4] {len(cand_ids)} kanalın bilgisi alınıyor…")
    chans = yt.channels(cand_ids)
    fresh = []
    for cid, c in chans.items():
        created = parse_time(c["snippet"]["publishedAt"])
        subs = int(c["statistics"].get("subscriberCount", 0) or 0)
        if args.kanal or (created >= cutoff and subs <= args.max_abone):
            fresh.append(c)
    print(f"  → son {args.gun} günde açılmış: {len(fresh)} kanal")

    # 3) video analizi
    print(f"\n[3/4] Videolar inceleniyor…")
    results = []
    for c in fresh:
        try:
            a = analyze_channel(yt, c, args)
        except QuotaExceeded as e:
            notes.append(str(e)); print("  ! " + str(e)); break
        ok = len(a["hits"]) >= args.min_video
        print(f"  {'✔' if ok else '·'} {a['title'][:40]:40s} {a['age_days']:3d} gün  {len(a['hits'])} video ≥ "
              f"{fmt_n(args.min_izlenme)}  abone {fmt_n(a['subs'])}")
        if ok or args.kanal:
            results.append(a)
    results.sort(key=lambda a: (-len(a["hits"]), -sum(v["views"] for v in a["hits"])))

    # 4) dil açığı
    print(f"\n[4/4] Dil açığı analizi ({', '.join([args.kaynak_dil] + targets)})…")
    for a in results[:args.kanal_sayisi]:
        a["gaps"] = []
        phrases = [k for k in a["keywords"] if " " in k][:args.kelime] or a["keywords"][:args.kelime]
        for ph in phrases:
            for lang in [args.kaynak_dil] + targets:
                try:
                    g = gap_check(yt, tr, ph, args.kaynak_dil, lang, args)
                except QuotaExceeded as e:
                    notes.append(str(e) + " Dil analizi yarım kaldı."); print("  ! " + str(e)); break
                a["gaps"].append(g)
                if g:
                    print(f"  {a['title'][:22]:22s} [{lang}] {g['query'][:40]:40s} → {g['verdict'][0]}")
            else:
                continue
            break
    tr.save()
    if tr.missing:
        notes.append(f"{len(tr.missing)} ifade çevrilemedi ve atlandı. ceviriler.json dosyasındaki boş "
                     "alanları doldurup tekrar çalıştır (önbellek sayesinde kota harcanmaz) ya da .env'e "
                     "DEEPL_API_KEY ekle.")

    # rapor
    os.makedirs(os.path.join(HERE, "rapor"), exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    def ser(a):
        a = dict(a)
        a["created"] = a["created"].isoformat()
        for k in ("videos", "longs", "hits"):
            a[k] = [dict(v, pub=v["pub"].isoformat()) for v in a[k]]
        return a
    report = dict(date=stamp, quota=yt.used, notes=notes, channels=[ser(a) for a in results],
                  params=dict(gun=args.gun, min_izlenme=args.min_izlenme, min_videos=args.min_video,
                              diller=targets, kaynak_dil=args.kaynak_dil))
    jpath = os.path.join(HERE, "rapor", f"radar_{stamp}.json")
    hpath = os.path.join(HERE, "rapor", f"radar_{stamp}.html")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    render(report, hpath)
    print(f"\nBitti. Kullanılan kota: {yt.used} birim.\nRapor: {hpath}")
    if not args.acma:
        try:
            import pathlib
            webbrowser.open(pathlib.Path(hpath).as_uri())
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDurduruldu.")
